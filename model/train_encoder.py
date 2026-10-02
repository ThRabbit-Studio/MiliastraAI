#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""训练意图匹配编码器（方案 A）。

设计目标不是「最强」，而是「**Lua 里跑得动 + 能泛化到没见过的说法**」：

  编码 = 输入字符的嵌入求平均  ->  线性投影  ->  L2 归一化  ->  64 维向量

为什么是这个结构：
  · Lua 侧推理只需「查表 + 求平均 + 一次 64x64 矩阵乘」，是 O(n)，
    每字约 130 次乘加，30 字的输入合计不到 4000 次 —— 实机上远低于 1ms。
  · 双嵌入表（汉字 + 拼音音节）让字库外的字能按同音归位，
    等于自带「同音字泛化」，玩家打错同音字也能匹配上。

训练用对比损失（InfoNCE）：让问法向量靠近所属主题的向量，远离其它主题。

用法：
  python model/train_encoder.py --steps 6000
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
POOL = os.path.join(DATA, "answer_pool.json")
TMAP = os.path.join(DATA, "token_map.json")
OUT_NPZ = os.path.join(HERE, "encoder.npz")
OUT_META = os.path.join(HERE, "encoder_meta.json")

CHAR_DIM = 64
SYL_DIM = 40
PROJ = 64


def load_data():
    with open(POOL, encoding="utf-8") as fh:
        pool = json.load(fh)
    with open(TMAP, encoding="utf-8") as fh:
        tmap = json.load(fh)
    return pool, tmap


def build_index(pool, tmap):
    """词表：所有出现过的字 + 所有音节（出现在输入里的，而非全表）。"""
    chars, syls = {}, {}
    topics = []
    rows = []          # (topic_idx, char_ids, syl_ids)
    for ti, e in enumerate(pool["entries"]):
        topics.append(e)
        for q in e["q"]:
            cids, sids = [], []
            for ch in q:
                if ch.strip() == "" or ch in "，。？！、；：（）…—·":
                    continue
                if ch not in chars:
                    chars[ch] = len(chars)
                cids.append(chars[ch])
                s = tmap["char2syl"].get(ch)
                if s is not None:
                    if s not in syls:
                        syls[s] = len(syls)
                    sids.append(syls[s])
            if cids:
                rows.append((ti, np.array(cids, np.int32), np.array(sids, np.int32)))
    return topics, chars, syls, rows


def encode_batch(rows, idx, n_char, n_syl, C, S):
    """把一个 batch 的问法编码成向量。

    关键优化：用稀疏矩阵做「嵌入求平均」，而不是拼 one-hot 稠密矩阵。
    """
    from scipy import sparse  # type: ignore
    have_scipy = True
    return have_scipy, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=6000)
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--lr", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=20261002)
    args = ap.parse_args()

    pool, tmap = load_data()
    topics, chars, syls, rows = build_index(pool, tmap)
    n_char = len(chars)
    n_syl = len(syls)
    n_topic = len(topics)
    print(f"[i] 答案池 {n_topic} 主题 / {len(rows)} 条问法")
    print(f"[i] 输入用字 {n_char} 个 / 音节 {n_syl} 个")

    rng = np.random.default_rng(args.seed)
    sc = 0.05
    C = rng.normal(0, sc, (n_char, CHAR_DIM)).astype(np.float32)   # 汉字嵌入
    S = rng.normal(0, sc, (n_syl, SYL_DIM)).astype(np.float32)     # 音节嵌入
    W = rng.normal(0, sc, (CHAR_DIM + SYL_DIM, PROJ)).astype(np.float32)
    b = np.zeros(PROJ, np.float32)
    params = {"C": C, "S": S, "W": W, "b": b}
    n_params = sum(v.size for v in params.values())
    print(f"[i] 编码器参数量 {n_params:,}"
          f"（汉字 {C.size:,} + 音节 {S.size:,} + 投影 {W.size:,}）")

    # Adam
    m = {k: np.zeros_like(v) for k, v in params.items()}
    v = {k: np.zeros_like(v) for k, v in params.items()}
    b1, b2, eps = 0.9, 0.999, 1e-8

    def encode_batch(batch_rows):
        """-> (嵌入, 缓存)。用 np.add.at 做稀疏平均。"""
        B = len(batch_rows)
        ec = np.zeros((B, CHAR_DIM), np.float32)
        es = np.zeros((B, SYL_DIM), np.float32)
        for i, (_ti, cids, sids) in enumerate(batch_rows):
            if len(cids):
                ec[i] = C[cids].mean(axis=0)
            if len(sids):
                es[i] = S[sids].mean(axis=0)
        h = np.concatenate([ec, es], axis=1)
        z = h @ W + b
        n = np.linalg.norm(z, axis=1, keepdims=True)
        zn = z / np.maximum(n, 1e-6)
        return zn, (h, z, n, ec, es)

    def topic_matrix():
        """主题向量 = 它的所有问法向量的平均（每步重算，保证与编码器同步）。"""
        per_topic = [[] for _ in range(n_topic)]
        for ti, cids, sids in rows:
            per_topic[ti].append((cids, sids))
        # 为省时间，每步只抽样若干问法
        reps = []
        for ti in range(n_topic):
            picks = per_topic[ti]
            k = min(8, len(picks))
            sel = [picks[j] for j in rng.choice(len(picks), size=k, replace=False)]
            batch = [(ti, c, s) for c, s in sel]
            zn, _ = encode_batch(batch)
            t = zn.mean(axis=0)
            t = t / max(np.linalg.norm(t), 1e-6)
            reps.append(t)
        T = np.stack(reps)                       # (n_topic, PROJ)
        return T

    t0 = time.perf_counter()
    losses = []
    for step in range(1, args.steps + 1):
        idx = rng.integers(0, len(rows), size=args.batch)
        batch = [rows[i] for i in idx]
        ti = np.array([r[0] for r in batch], np.int64)
        zn, cache = encode_batch(batch)
        h, z, n, ec, es = cache

        T = topic_matrix()
        sim = zn @ T.T                            # (B, n_topic)
        sim = sim / 0.05                          # 温度
        sim = sim - sim.max(axis=1, keepdims=True)
        p = np.exp(sim)
        p /= p.sum(axis=1, keepdims=True)
        loss = float(-np.log(np.maximum(p[np.arange(len(ti)), ti], 1e-9)).mean())

        # 反传：dL/dz_n
        dp = p.copy()
        dp[np.arange(len(ti)), ti] -= 1.0
        dp /= len(ti)
        dsim = dp / 0.05
        dzn = dsim @ T                            # (B, PROJ)
        dz = (dzn - (dzn * zn).sum(axis=1, keepdims=True) * zn) / np.maximum(n, 1e-6)
        dW = h.T @ dz
        db = dz.sum(axis=0)
        dh = dz @ W.T
        dec, des = dh[:, :CHAR_DIM], dh[:, CHAR_DIM:]

        dC = np.zeros_like(C)
        dS = np.zeros_like(S)
        for i, (_t, cids, sids) in enumerate(batch):
            if len(cids):
                np.add.at(dC, cids, dec[i] / len(cids))
            if len(sids):
                np.add.at(dS, sids, des[i] / len(sids))
        grads = {"C": dC, "S": dS, "W": dW, "b": db}

        # Adam
        for k in params:
            g = grads[k]
            m[k] = b1 * m[k] + (1 - b1) * g
            v[k] = b2 * v[k] + (1 - b2) * (g * g)
            mh = m[k] / (1 - b1 ** step)
            vh = v[k] / (1 - b2 ** step)
            params[k] -= args.lr * mh / (np.sqrt(vh) + eps)

        C, S, W, b = params["C"], params["S"], params["W"], params["b"]
        losses.append(loss)
        if step % 500 == 0 or step == 1:
            acc = 0.0
            if step % 2000 == 0:
                # 训练集上的意图命中率（用整批算）
                acc = float((sim.argmax(axis=1) == ti).mean())
            sec = time.perf_counter() - t0
            print(f"  step {step:>5}  loss {np.mean(losses[-500:]):.4f}"
                  f"  batch_acc {acc:.3f}  {sec:5.1f}s")

    np.savez_compressed(OUT_NPZ, C=C, S=S, W=W, b=b)
    with open(OUT_META, "w", encoding="utf-8") as fh:
        json.dump({
            "char_dim": CHAR_DIM, "syl_dim": SYL_DIM, "proj": PROJ,
            "n_char": n_char, "n_syl": n_syl, "n_topic": n_topic,
            "params": int(n_params),
            "char_list": list(chars.keys()),
            "syl_list": list(syls.keys()),
            "topics": [{"topic": e["topic"], "a": e["a"]} for e in topics],
            "final_loss": float(np.mean(losses[-200:])),
        }, fh, ensure_ascii=False)
    print(f"[OK] 编码器 -> {os.path.relpath(OUT_NPZ, ROOT)}"
          f"（{os.path.getsize(OUT_NPZ):,} 字节）")
    print(f"     最终 loss {np.mean(losses[-200:]):.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
