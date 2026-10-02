#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""训练一阶字符模型（bigram）：闭式解，一次计数即可。

为什么不用梯度下降：
  bigram 的最优解就是「条件频率」，把 (前字, 后字) 数一遍、加平滑归一化就完了。
  之前用 mini-batch + Adam 每步都建一个 (V,V) 的梯度矩阵（1770 万元素），
  3000 步跑不完——那是实现问题，不是算法问题。闭式解一秒就出结果。

代价与收益（必须说清）：
  · 模型只记「一个字后面常跟什么」，没有长程上下文，生成的东西不保证通顺。
  · 但它**确实是一个 1M 级参数的语言模型**，在千星 Lua 里跑得动，
    而且给出了「生成式回复」的质量下限——后面上真 Transformer 时用来对照。

输出：model/model.npz + model/meta.json（与 train.py 同格式，便于统一导出）
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

from train import (CORPUS, OUT_META, OUT_MODEL, build_vocab,  # noqa: E402
                   encode, SEP, EOS, PAD, BOS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--alpha", type=float, default=0.05,
                    help="拉普拉斯平滑系数，越小越贴合语料、越大越平滑")
    ap.add_argument("--topk", type=int, default=0, help="只保留每行前 k 个（0=全留）")
    args = ap.parse_args()

    t0 = time.perf_counter()
    with open(CORPUS, encoding="utf-8") as fh:
        text = fh.read()
    stoi, itos = build_vocab(text)
    V = len(itos)
    print(f"[i] 语料 {len(text):,} 字，词表 {V} 个 token")

    x, y = encode(text, stoi)
    print(f"[i] 计数 {len(x):,} 个字符转移")

    # 一次 bincount 完成计数
    flat = x.astype(np.int64) * V + y.astype(np.int64)
    counts = np.bincount(flat, minlength=V * V).reshape(V, V).astype(np.float32)
    print(f"[i] 非零转移 {int((counts > 0).sum()):,} / {V*V:,} "
          f"（{100*(counts>0).mean():.2f}% 稠密）")

    # 平滑 + 行归一化 -> log 概率（导出时量化成 int8）
    counts += args.alpha
    logits = np.log(counts, dtype=np.float32)
    logits -= logits.max(axis=1, keepdims=True)
    probs = np.exp(logits)
    probs /= probs.sum(axis=1, keepdims=True)

    # 评估：训练集上的平均负对数似然
    p_true = probs[x, y]
    loss = float(-np.log(np.maximum(p_true, 1e-9)).mean())
    print(f"[i] 训练集 loss {loss:.4f}  ppl {np.exp(loss):.1f}")

    if args.topk > 0:
        idx = np.argpartition(-probs, args.topk - 1, axis=1)[:, :args.topk]
        mask = np.zeros_like(probs, dtype=bool)
        np.put_along_axis(mask, idx, True, axis=1)
        probs = np.where(mask, probs, 0.0)
        probs /= np.maximum(probs.sum(axis=1, keepdims=True), 1e-9)
        print(f"[i] 每行只保留前 {args.topk} 个 token")

    os.makedirs(os.path.dirname(OUT_MODEL), exist_ok=True)
    np.savez_compressed(OUT_MODEL, W=probs.astype(np.float32))
    with open(OUT_META, "w", encoding="utf-8") as fh:
        json.dump({"arch": "bigram", "vocab": V, "itos": itos,
                   "params": int(V * V), "alpha": args.alpha,
                   "topk": args.topk, "train_loss": loss,
                   "train_ppl": float(np.exp(loss))},
                  fh, ensure_ascii=False)
    print(f"[OK] 模型 -> {os.path.relpath(OUT_MODEL, ROOT)}"
          f"（{os.path.getsize(OUT_MODEL):,} 字节）")
    print(f"     参数量 {V*V:,}，耗时 {time.perf_counter()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
