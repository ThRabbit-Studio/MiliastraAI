#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看一眼模型生成的文本到底什么样。

这一步是整个「接入模型」路线的**判定点**：
  如果生成的东西读不通，那把它塞进关卡只会让玩家觉得坏了，
  这时候就不该硬上，而应该换成「意图匹配 + 答案池」那种可控方案。
所以先肉眼验，再决定要不要导出到 Lua。

用法：
  python model/sample.py --n 6
  python model/sample.py --seed-text 你好 --n 4
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "build"))

from train import BOS, EOS, PAD, SEP  # noqa: E402


def load():
    npz = np.load(os.path.join(HERE, "model.npz"))
    with open(os.path.join(HERE, "meta.json"), encoding="utf-8") as fh:
        meta = json.load(fh)
    return npz, meta


def sample(W: np.ndarray, stoi, itos, seed_token: int, n: int,
           temperature: float, rng, max_len: int = 60) -> str:
    out = []
    tok = seed_token
    for _ in range(max_len):
        p = W[tok].astype(np.float64)
        if p.sum() <= 0:
            break
        if temperature != 1.0:
            p = np.power(p, 1.0 / temperature)
        p = p / p.sum()
        tok = int(rng.choice(len(p), p=p))
        if tok == EOS:
            break
        if tok >= 4:
            out.append(itos[tok])
        if len(out) >= n:
            break
    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--len", type=int, default=40)
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--seed-text", default=None)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    npz, meta = load()
    itos = meta["itos"]
    stoi = {ch: i for i, ch in enumerate(itos)}
    W = npz["W"]
    rng = np.random.default_rng(args.seed)

    print(f"[i] 架构 {meta['arch']}  词表 {meta['vocab']}  "
          f"参数量 {meta.get('params', 0):,}  训练 ppl {meta.get('train_ppl', 0):.1f}")

    # 以「回答开头」为种子，看它续出什么
    print("\n=== 从常见开头续写（这是它当回复时的样子）===")
    for seed_text in ("可以", "我", "这个", "不", "你", "如果"):
        s = stoi.get(seed_text[-1], BOS)
        text = sample(W, stoi, itos, s, args.len, args.temperature, rng)
        print(f"  {seed_text}… -> {seed_text}{text}")

    if args.seed_text:
        print(f"\n=== 指定种子「{args.seed_text}」 ===")
        for i in range(args.n):
            s = stoi.get(args.seed_text[-1], BOS)
            print(f"  {i+1}. {args.seed_text}"
                  f"{sample(W, stoi, itos, s, args.len, args.temperature, rng)}")

    # 从句子开头（BOS）生成，看整体
    print("\n=== 从零生成（BOS）===")
    for i in range(args.n):
        text = sample(W, stoi, itos, BOS, args.len, args.temperature, rng)
        print(f"  {i+1}. {text}")

    print("\n判读要点：")
    print("  · 如果输出是「词能认、但句子不通」——这是 bigram 的正常水平，")
    print("    它只记相邻两字的关系，没有长程上下文。")
    print("  · 如果出现大量重复同一个字或乱码，说明模型/语料有问题。")
    print("  结论请据此判断：能不能把它当「生成式回复」用。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
