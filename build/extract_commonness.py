#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 Unihan 提取「常用度信号」，用于给拼音候选字排序。

为什么需要：
  首候选决定玩家第一眼看到什么。如果按语义分组顺序排，实测「名」会掉到第 11 位，
  玩家打 mingzi 要翻十下才能选到字，体验直接废掉。所以必须用真实的常用度排序。

用 Unihan 里的两个字段（都是权威数据，不是我估的）：
  kHanyuPinlu  汉语拼音字频表——《现代汉语频率词典》的读音频次，有该字的才算常用
  kGradeLevel  教学年级（1-6 小学、7-9 初中等），数字越小越基础
排序键：(有字频 ? 0 : 1, 年级 ? 年级 : 99, 语料字频取负, 码点)

产物：data/unihan_commonness.json
"""
from __future__ import annotations

import io
import json
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
ZIP_PATH = os.path.join(HERE, "Unihan.zip")
OUT_PATH = os.path.join(DATA, "unihan_commonness.json")


def main() -> int:
    if not os.path.exists(ZIP_PATH):
        print(f"[FAIL] 缺少 {ZIP_PATH}")
        return 1
    with zipfile.ZipFile(ZIP_PATH) as zf:
        names = zf.namelist()
        readings = zf.read([n for n in names if n.endswith("Unihan_Readings.txt")][0]).decode("utf-8")
        like = zf.read([n for n in names if n.endswith("Unihan_DictionaryLikeData.txt")][0]).decode("utf-8")

    pinlu: dict[str, int] = {}
    for line in readings.splitlines():
        if not line or line.startswith("#"):
            continue
        p = line.split("\t")
        if len(p) < 3 or p[1] != "kHanyuPinlu":
            continue
        # 格式形如 "de(1234) dì(56)"：括号里是出现次数，取最大者
        code = p[0].strip().upper().removeprefix("U+")
        best = 0
        for seg in p[2].split():
            if "(" in seg and seg.endswith(")"):
                try:
                    best = max(best, int(seg[seg.index("(") + 1:-1]))
                except ValueError:
                    pass
        if best > 0:
            pinlu[code] = max(pinlu.get(code, 0), best)

    grade: dict[str, int] = {}
    for line in like.splitlines():
        if not line or line.startswith("#"):
            continue
        p = line.split("\t")
        if len(p) < 3 or p[1] != "kGradeLevel":
            continue
        code = p[0].strip().upper().removeprefix("U+")
        try:
            grade[code] = int(p[2].strip())
        except ValueError:
            continue

    out = {
        "_meta": {
            "source": "Unihan.zip（kHanyuPinlu 字频 + kGradeLevel 教学年级）",
            "with_pinlu": len(pinlu),
            "with_grade": len(grade),
            "note": "pinlu 是该字在《现代汉语频率词典》里的出现次数；"
                    "grade 是教学年级，1-6 小学、7-9 初中、10-12 高中",
        },
        "pinlu": pinlu,
        "grade": grade,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    print(f"[OK] 字频表 {len(pinlu)} 字，年级表 {len(grade)} 字")
    print(f"     已写入 {OUT_PATH}（{os.path.getsize(OUT_PATH)} 字节）")
    # 抽查几个关键字的排序依据
    for ch in "名你是我好这什有":
        code = "%04X" % ord(ch)
        print(f"     {ch}  pinlu={pinlu.get(code, '-')}  grade={grade.get(code, '-')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
