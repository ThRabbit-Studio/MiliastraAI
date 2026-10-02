#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""列出每个音节的候选字（供人工排序用）。

首候选决定玩家第一眼看到什么，必须按真实常用度排。分组顺序排不出常用度，
所以要人工过一遍。这个脚本把「需要人工排序的音节」按候选数量列出来，
方便逐个敲定顺序。

用法：
  python build/list_syllables.py > docs/音节候选一览.txt
  python build/list_syllables.py --min 2    # 只看候选>=2个的音节
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=int, default=1)
    args = ap.parse_args()

    with open(os.path.join(ROOT, "ime", "lexicon_groups.json"), encoding="utf-8") as fh:
        groups = json.load(fh)["groups"]
    with open(os.path.join(DATA, "unihan_syllables.json"), encoding="utf-8") as fh:
        syl_of = {chr(int(k, 16)): v for k, v in json.load(fh)["map"].items()}

    by_syl: dict[str, list[str]] = defaultdict(list)
    for gname, chars in groups.items():
        for ch in chars:
            syl = syl_of.get(ch)
            if syl and ch not in by_syl[syl]:
                by_syl[syl].append(ch)

    rows = [(s, c) for s, c in by_syl.items() if len(c) >= args.min]
    rows.sort(key=lambda kv: (-len(kv[1]), kv[0]))
    print(f"# 有字音节 {len(by_syl)} 个，候选 >= {args.min} 的 {len(rows)} 个")
    print(f"# 格式：音节  候选数  现有顺序（这个顺序是分组顺序，不是常用度）")
    for syl, chars in rows:
        print(f"{syl}\t{len(chars)}\t{''.join(chars)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
