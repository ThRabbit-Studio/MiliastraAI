#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 token -> 音节 映射（data/token_map.json）。

为什么需要它：
  方案 A 的编码器要在 Lua 里推理，而 Lua 的算力只够做 O(n) 的「查表 + 平均」。
  所以编码器设计成：**输入字符的嵌入求平均** -> 线性投影 -> 64 维向量。
  但玩家可能打进字库里没有的字，这时要有兜底——兜底就是**音节**：
  字库里 3000 个字都映射到 412 个音节之一，没见过的字可按拼音归到同音节，
  等于自动获得了「同音字泛化」。

产物：
  {"syllables":["a","ai",...], "char2syl":{"你":0,"好":5,...}}
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
LEX = os.path.join(ROOT, "ime", "ime_data.lua")
UNIHAN = os.path.join(DATA, "unihan_syllables.json")
OUT = os.path.join(DATA, "token_map.json")


def main() -> int:
    with open(LEX, encoding="utf-8") as fh:
        src = fh.read()
    syl_block = src.split("MOD.IME_SYLLABLES = ", 1)[1].split("-- 音节 ->", 1)[0]
    syllables = list(dict.fromkeys(re.findall(r'"([a-z]+)"', syl_block)))
    syl_id = {s: i for i, s in enumerate(syllables)}

    chars_block = src.split("MOD.IME_CHARS = {", 1)[1].split("-- 拼音串 ->", 1)[0]
    char2syl: dict[str, int] = {}
    for m in re.finditer(r'\["([a-z]+)"\]\s*=\s*\{([^}]*)\}', chars_block):
        syl = m.group(1)
        if syl not in syl_id:
            continue
        for ch in re.findall(r'"([^"]+)"', m.group(2)):
            char2syl.setdefault(ch, syl_id[syl])

    # 再补一层：Unihan 里凡是音节在表内的字，也给它一个音节 id。
    # 这样玩家打出字库外的常用字时，仍能按同音归位。
    added = 0
    if os.path.exists(UNIHAN):
        with open(UNIHAN, encoding="utf-8") as fh:
            umap = json.load(fh)["map"]
        for code, syl in umap.items():
            ch = chr(int(code, 16))
            if ch in char2syl or syl not in syl_id:
                continue
            char2syl[ch] = syl_id[syl]
            added += 1

    doc = {"syllables": syllables, "char2syl": char2syl}
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, separators=(",", ":"))

    print(f"[OK] 音节 {len(syllables)} 个")
    print(f"[OK] 字->音节 {len(char2syl)} 条（字库 {len(char2syl)-added} + "
          f"Unihan 补充 {added}）")
    print(f"     -> {os.path.relpath(OUT, ROOT)}（{os.path.getsize(OUT):,} 字节）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
