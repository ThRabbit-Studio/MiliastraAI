#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拼音字库自检（Python 侧，不进游戏）。

在跑真机之前，先用 Python 按构建出来的字表回答三个问题：
  1. 各个音节的首候选是不是常用字？（首候选决定玩家第一眼看到什么）
  2. 语料里每个字，能不能在它所属音节里被选出来？
  3. 「打完整拼音 -> 自动取首候选」能拼回问法原文吗？拼不回来的有多少？

第 3 条最要紧：如果首候选经常取错字，玩家就得频繁用数字键挑字，
体验会很差。这个脚本把问题量出来。

用法：
  python verify/check_lexicon.py
  python verify/check_lexicon.py --top 30   # 多列几个音节
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")

HAN = re.compile(r"[\u4e00-\u9fff]")


def load_lexicon():
    """从 ime/ime_data.lua 里读回字表（它是构建产物，最接近运行时的真相）。"""
    path = os.path.join(ROOT, "ime", "ime_data.lua")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()

    syl_block = src.split("MOD.IME_SYLLABLES = ", 1)[1].split("-- 音节 ->", 1)[0]
    syllables = re.findall(r'"([a-z]+)"', syl_block)

    # 只取「音节 -> 单字」那一段：后面还有 IME_WORDS / IME_BIGRAMS。
    # 不切开会把词表也当成单字表统计（曾经把 297 个音节误报成 846 个）。
    chars_block = src.split("MOD.IME_CHARS = {", 1)[1].split("-- 拼音串 ->", 1)[0]
    table: dict[str, list[str]] = {}
    for m in re.finditer(r'\["([a-z]+)"\]\s*=\s*\{([^}]*)\}', chars_block):
        syl = m.group(1)
        table[syl] = re.findall(r'"([^"]+)"', m.group(2))
    return syllables, table


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=12)
    args = ap.parse_args()

    syllables, table = load_lexicon()
    print(f"[i] 音节表 {len(syllables)} 条，有字音节 {len(table)} 个，"
          f"共 {sum(len(v) for v in table.values())} 字")

    # 1. 首候选一览（按候选数量排序，候选越多越需要玩家费神挑字）
    print(f"\n一、候选最多的 {args.top} 个音节（首候选是玩家第一眼看到的）")
    for syl in sorted(table, key=lambda s: -len(table[s]))[:args.top]:
        head = table[syl][0]
        print(f"   {syl:<8} {len(table[syl]):>2} 字   首候选={head}   "
              f"{''.join(table[syl][:10])}")

    # 2. 语料用字能否打出
    with open(os.path.join(DATA, "corpus_plain.json"), encoding="utf-8") as fh:
        corpus = json.load(fh)
    with open(os.path.join(DATA, "unihan_syllables.json"), encoding="utf-8") as fh:
        syl_of = {chr(int(k, 16)): v for k, v in json.load(fh)["map"].items()}

    texts = []
    for q in corpus["questions"]:
        texts.extend(q["q"])
        texts.extend(q["a"])
    texts.extend(corpus["persona"]["unknown"])
    texts.extend(corpus["persona"]["tooShort"])

    untypable: list[str] = []
    rank_stats: dict[str, list[int]] = defaultdict(list)   # 字 -> 它在候选里的位次
    for t in texts:
        for ch in HAN.findall(t):
            syl = syl_of.get(ch)
            if not syl or syl not in table:
                untypable.append(ch)
                continue
            lst = table[syl]
            if ch not in lst:
                untypable.append(ch)
                continue
            rank_stats[ch].append(lst.index(ch) + 1)

    if untypable:
        print(f"\n[FAIL] {len(set(untypable))} 个字打不出来："
              f"{''.join(sorted(set(untypable)))}")
    else:
        print("\n[OK] 语料全部用字都能在对应音节里被选出")

    # 3. 首候选命中率：位次 1 才算「不用挑字」
    first = sum(1 for r in rank_stats.values() if max(r) == 1)
    total = len(rank_stats)
    within3 = sum(1 for r in rank_stats.values() if max(r) <= 3)
    print(f"\n二、语料用字 {total} 个：首候选就命中 {first} 个"
          f"（{first/total*100:.0f}%），前三候选内 {within3} 个（{within3/total*100:.0f}%）")
    worst = sorted(rank_stats.items(), key=lambda kv: -max(kv[1]))[:args.top]
    if worst:
        print(f"   需要挑最多次的字：")
        for ch, rs in worst:
            print(f"     {ch}（{syl_of.get(ch)}）位次 {max(rs)}")

    # 4. 整句回放：打完整拼音、每音节取首候选，看能不能拼回原句
    def spell(text: str) -> str:
        out = []
        for ch in HAN.findall(text):
            syl = syl_of.get(ch)
            lst = table.get(syl or "", [])
            out.append(lst[0] if lst else "?")
        return "".join(out)

    q_total = q_exact = 0
    bad_examples = []
    for q in corpus["questions"]:
        for variant in q["q"]:
            q_total += 1
            if spell(variant) == variant:
                q_exact += 1
            elif len(bad_examples) < 8:
                bad_examples.append((variant, spell(variant)))
    print(f"\n三、问法回放（每音节都取首候选）：{q_total} 条问法中 "
          f"{q_exact} 条能原样拼出（{q_exact/q_total*100:.0f}%）")
    for want, got in bad_examples:
        print(f"   期望 {want}  实际 {got}")

    if untypable:
        return 1
    print("\n[OK] 字库自检完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
