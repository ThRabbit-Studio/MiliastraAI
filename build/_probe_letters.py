#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统计文档里「所有键鼠按键事件」覆盖了哪些字母。"""
import io
import re

P = r"C:\ugc\2DPrompt\with_tools\Lua客户端控件API文档.md"
lines = io.open(P, encoding="utf-8").readlines()

rows = []
for line in lines:
    if "Enum.KeyEventType" not in line:
        continue
    m = re.search(r"`(Keyboard[A-Za-z0-9_]+)`", line)
    if not m:
        continue
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    if len(cells) < 4:
        continue
    phys = cells[3].strip("`").strip()
    rows.append((m.group(1), cells[2], phys))

downs = [(n, d, p) for n, d, p in rows if n.endswith("Down")]
print(f"键鼠「按下」事件 {len(downs)} 个\n")

letters = {}
for n, d, p in downs:
    if len(p) == 1 and p.isalpha():
        letters[p.upper()] = n
print(f"覆盖字母 {len(letters)} 个：{''.join(sorted(letters))}")
missing = sorted(set("ABCDEFGHIJKLMNOPQRSTUVWXYZ") - set(letters))
print(f"缺失字母 {len(missing)} 个：{''.join(missing)}\n")
print("逐字母对应的键鼠事件：")
for ch in sorted(letters):
    print(f"  {ch}  {letters[ch]}")
