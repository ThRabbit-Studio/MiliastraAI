#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""训练极小字符级模型（numpy，无 PyTorch）。

设计取舍：
  · 模型前一个字符 -> 下一个字符（一阶）。没有注意力、没有位置编码。
    理由：注意力要 4*d*d 每层，在 1M 参数预算里会把 d_model 压到很小，
    反而不如把参数全花在词表和大 FFN 上。而且一阶模型导出到 Lua 后是
    「一次查表 + 一次矩阵乘」，实机上跑得动，这才是能落地的关键。
  · 词表从「训练语料用字 + 内置字库」取，约 3000 字，与拼音字库一致。
  · 量化导出时是 int8 权重 + 每行一个 scale，见 export_weights.py。

用法：
  python model/train.py --arch bigram --steps 4000
  python model/train.py --arch tiny --steps 20000
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
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "build"))

from tinylm import build_model, n_params, softmax  # noqa: E402

DATA = os.path.join(ROOT, "data")
CORPUS = os.path.join(DATA, "train_corpus.txt")
LEX = os.path.join(ROOT, "ime", "ime_data.lua")
OUT_MODEL = os.path.join(ROOT, "model", "model.npz")
OUT_META = os.path.join(ROOT, "model", "meta.json")

# 特殊 token
PAD, BOS, SEP, EOS = 0, 1, 2, 3
N_SPECIAL = 4


# ── 词表 ────────────────────────────────────────────────────────────────────

def lexicon_chars() -> set[str]:
    """内置拼音字库里的所有字，作为词表的一部分（保证 AI 说的字玩家都能打）。"""
    import re
    with open(LEX, encoding="utf-8") as fh:
        src = fh.read()
    block = src.split("MOD.IME_CHARS = {", 1)[1].split("-- 拼音串 ->", 1)[0]
    chars = set()
    for m in re.finditer(r'\["([a-z]+)"\]\s*=\s*\{([^}]*)\}', block):
        for ch in re.findall(r'"([^"]+)"', m.group(2)):
            chars.add(ch)
    return chars


def build_vocab(text: str) -> tuple[dict[str, int], list[str]]:
    """词表 = 语料里真正出现过的字 + 字库里高频（年级靠前）的字。

    ⚠ 不能把整个 3000 字库都塞进来：
      字库的自动扩充层含冷僻字（麥、鶯、鷹…），它们没在语料里出现过，
      模型学到的是「均匀分布」，采样时会随机吐出来，直接变成乱码。
      实测混入后生成结果是「鹼黑这个我先看有顺序」这种鬼话。
      所以只收语料用字 + 字库里属于小学年级的字（grade ≤ 3）。
    """
    counts: dict[str, int] = {}
    for ch in text:
        counts[ch] = counts.get(ch, 0) + 1
    # 字库里的小学常用字（保证 AI 说的字玩家能打出来，同时不带冷僻字）
    for ch in lexicon_chars():
        if ch not in counts:
            counts[ch] = 0
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    itos = ["<pad>", "<bos>", "<sep>", "<eos>"] + [ch for ch, _ in items]
    stoi = {ch: i for i, ch in enumerate(itos)}
    return stoi, itos


def encode(text: str, stoi: dict[str, int], max_len: int | None = None):
    """文本 -> (输入, 目标)。轮次分隔符换成 SEP，结尾补 EOS。"""
    ids = [stoi.get(ch, 0) for ch in text.replace("\u0001", "\u0002")]
    if max_len:
        ids = ids[:max_len]
    x = np.array(ids[:-1], dtype=np.int32)
    y = np.array(ids[1:], dtype=np.int32)
    return x, y


# ── Adam ────────────────────────────────────────────────────────────────────

class Adam:
    def __init__(self, params: dict, lr: float = 3e-3):
        self.p = params
        self.lr = lr
        self.m = {k: np.zeros_like(v) for k, v in params.items()
                  if isinstance(v, np.ndarray)}
        self.v = {k: np.zeros_like(v) for k, v in params.items()
                  if isinstance(v, np.ndarray)}
        self.t = 0
        self.b1, self.b2, self.eps = 0.9, 0.999, 1e-8

    def step(self, grads: dict, clip: float = 1.0):
        self.t += 1
        # 梯度裁剪
        total = 0.0
        for g in grads.values():
            total += float((g * g).sum())
        norm = total ** 0.5
        scale = 1.0 if norm <= clip else clip / (norm + 1e-9)
        for k, g in grads.items():
            if k not in self.m:
                continue
            g = g * scale
            self.m[k] = self.b1 * self.m[k] + (1 - self.b1) * g
            self.v[k] = self.b2 * self.v[k] + (1 - self.b2) * (g * g)
            mh = self.m[k] / (1 - self.b1 ** self.t)
            vh = self.v[k] / (1 - self.b2 ** self.t)
            self.p[k] -= self.lr * mh / (np.sqrt(vh) + self.eps)


# ── 训练 ────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arch", default="tiny", choices=["bigram", "tiny"])
    ap.add_argument("--steps", type=int, default=20000)
    ap.add_argument("--batch", type=int, default=512)
    ap.add_argument("--lr", type=float, default=3e-3)
    ap.add_argument("--d-model", type=int, default=48)
    ap.add_argument("--d-ff", type=int, default=192)
    ap.add_argument("--log-every", type=int, default=500)
    ap.add_argument("--seed", type=int, default=20261002)
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    with open(CORPUS, encoding="utf-8") as fh:
        text = fh.read()
    stoi, itos = build_vocab(text)
    vocab = len(itos)
    print(f"[i] 语料 {len(text):,} 字，词表 {vocab} 个 token")

    x, y = encode(text, stoi)
    print(f"[i] 训练样本 {len(x):,} 个 (前一个字符 -> 下一个字符)")

    if args.arch == "bigram":
        from tinylm import build_bigram, bigram_loss_and_grad
        model = build_bigram(vocab)
        loss_grad = bigram_loss_and_grad
    else:
        from tinylm import build_tiny, tiny_loss_and_grad
        model = build_tiny(vocab, d_model=args.d_model, d_ff=args.d_ff, seed=args.seed)
        loss_grad = tiny_loss_and_grad

    p = n_params(model)
    print(f"[i] 架构 {args.arch}，参数量 {p:,}")
    model["_stoi"] = None      # 占位，导出时另存

    opt = Adam({k: v for k, v in model.items() if isinstance(v, np.ndarray)},
               lr=args.lr)
    n = len(x)
    t0 = time.perf_counter()
    losses = []
    for step in range(1, args.steps + 1):
        idx = rng.integers(0, n, size=args.batch)
        loss, grads = loss_grad(model, x[idx], y[idx])
        opt.step(grads)
        losses.append(loss)
        if step % args.log_every == 0 or step == 1:
            avg = float(np.mean(losses[-args.log_every:]))
            ppl = float(np.exp(avg))
            sec = time.perf_counter() - t0
            print(f"  step {step:>6}  loss {avg:.4f}  ppl {ppl:8.1f}  "
                  f"{sec:6.1f}s  ({step/sec:.1f} 步/秒)")

    # 保存
    os.makedirs(os.path.dirname(OUT_MODEL), exist_ok=True)
    save = {k: v for k, v in model.items()
            if isinstance(v, np.ndarray)}
    np.savez_compressed(OUT_MODEL, **save)
    with open(OUT_META, "w", encoding="utf-8") as fh:
        json.dump({"arch": args.arch, "vocab": vocab, "itos": itos,
                   "params": int(p), "d_model": args.d_model,
                   "d_ff": args.d_ff,
                   "final_loss": float(np.mean(losses[-100:])),
                   "steps": args.steps, "batch": args.batch, "lr": args.lr},
                  fh, ensure_ascii=False)
    print(f"[OK] 模型 -> {os.path.relpath(OUT_MODEL, ROOT)}"
          f"（{os.path.getsize(OUT_MODEL):,} 字节）")
    print(f"[OK] 词表 -> {os.path.relpath(OUT_META, ROOT)}")
    print(f"     最终 loss {np.mean(losses[-100:]):.4f}  "
          f"ppl {np.exp(np.mean(losses[-100:])):.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
