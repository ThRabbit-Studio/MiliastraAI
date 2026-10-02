#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成意图匹配用的答案池（data/answer_pool.json）。

为什么需要它：
  生成式模型实测输出不通顺（见 docs/模型路线实测记录.md），所以改为
  「小神经网把输入编码成向量 -> 与答案池比相似度 -> 取出最合适的答句」。
  这条路要成立，答案池必须**够大且质量可控**——模型只负责找，不负责编。

答案池怎么来的：
  · seeds  = 人工写的问法与答句（质量由人保证，这是池子的骨架）
  · expand = 对种子问法做同义改写，扩大语义覆盖面（模型要能匹配到）
  每条记录带 topic，便于统计覆盖度。

输出格式：
  {"schema":"answer-pool/1","entries":[{"topic":..,"q":[..],"a":[..]}, ...]}
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "answer_pool.json")
SRC = os.path.join(DATA, "corpus_plain.json")

# 同义改写前后缀：把一条种子问法撑成多种说法，让匹配器有更多锚点
Q_PREFIX = ["", "请问", "我想问", "想问一下", "问一下", "麻烦问下"]
Q_SUFFIX = ["", "呢", "啊", "？", "可以吗", "行吗"]


def expand_questions(base: list[str]) -> list[str]:
    out: list[str] = []
    for q in base:
        for pre in Q_PREFIX:
            for suf in Q_SUFFIX:
                out.append(pre + q + suf)
    # 去重保序
    return list(dict.fromkeys(out))


def main() -> int:
    with open(SRC, encoding="utf-8") as fh:
        corpus = json.load(fh)

    entries = []
    for q in corpus["questions"]:
        entries.append({
            "topic": q["topic"],
            "cat": q["cat"],
            "q": expand_questions(q["q"]),
            "a": q["a"],
        })
    n_raw = sum(len(e["q"]) for e in entries)
    print(f"[i] 种子 {len(entries)} 个主题 -> 问法 {n_raw} 条（已同义改写）")

    pool = {
        "schema": "answer-pool/1",
        "note": "意图匹配用答案池。条目由人工编写，模型只负责检索不负责生成。",
        "persona": corpus["persona"],
        "entries": entries,
    }
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(pool, fh, ensure_ascii=False, indent=1)

    total_a = sum(len(e["a"]) for e in entries)
    print(f"[OK] 答案池：主题 {len(entries)} / 问法 {n_raw} / 答句 {total_a}")
    print(f"     -> {os.path.relpath(OUT, ROOT)}（{os.path.getsize(OUT):,} 字节）")
    print()
    print("下一步（方案 A）：")
    print("  1. 训练 0.5M 编码器，把问法编成向量（model/train_encoder.py）")
    print("  2. 量化导出（int8 + 每维 scale），体积约 0.6MB")
    print("  3. 在 Lua 里做「嵌入查表 + 全维点积」选最相近的答案")
    return 0


if __name__ == "__main__":
    sys.exit(main())
