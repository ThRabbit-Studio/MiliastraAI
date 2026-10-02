#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 Unihan 读音反推真实存在的拼音音节表。

之前用「声母 × 韵母」笛卡尔积生成，结果产出 982 个音节——里面有大量汉语里根本
不存在的组合（buoh、jvan、shvn 之类）。那种表会让切分算法把乱敲的字母也切成
"合法"音节，输入体验直接坏掉。

正确做法是反过来：Unihan 里每个字都有真实读音，把所有读音收集起来，
再按「至少 N 个不同汉字共用该读音」过滤，得到的就是真实音节表。
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
SYLL_PATH = os.path.join(DATA, "unihan_syllables.json")
OUT_PATH = os.path.join(DATA, "syllables_real.json")

# 至少要有这么多个不同汉字共用，才认为它是真实音节（滤掉 Unihan 里的录入噪声）
MIN_CHARS = 2

# 这些音节真实存在但用字很少，会被阈值滤掉；它们是玩家可能真的会打的，手工补回
ALLOWLIST = {"eng", "kei", "shei", "nun", "din", "dia", "cei", "rua"}


def main() -> int:
    with open(SYLL_PATH, encoding="utf-8") as fh:
        doc = json.load(fh)
    counts: dict[str, int] = defaultdict(int)
    for _code, syl in doc["map"].items():
        counts[syl] += 1

    real = sorted(s for s, n in counts.items() if n >= MIN_CHARS or s in ALLOWLIST)
    rare = sorted(s for s, n in counts.items() if n < MIN_CHARS and s not in ALLOWLIST)

    out = {
        "_meta": {
            "source": os.path.basename(SYLL_PATH),
            "min_chars": MIN_CHARS,
            "syllables": len(real),
            "dropped_rare": rare,
        },
        "syllables": real,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    print(f"[OK] 真实音节 {len(real)} 个（要求至少 {MIN_CHARS} 个汉字共用）")
    print(f"     丢弃过少见的 {len(rare)} 个：{' '.join(rare)}")
    print(f"     已写入 {OUT_PATH}")
    longest = sorted(real, key=len, reverse=True)[:6]
    print(f"     最长音节：{' '.join(longest)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
