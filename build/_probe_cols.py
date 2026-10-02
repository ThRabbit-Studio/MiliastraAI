#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时核对：文档 §26(3) 表里每一列的原始内容（不分栏位猜测）。"""
import io
import re

P = r"C:\ugc\2DPrompt\with_tools\Lua客户端控件API文档.md"
lines = io.open(P, encoding="utf-8").readlines()
print("表头：")
for l in lines:
    if "枚举名" in l and "物理键" in l:
        print("  ", repr(l.strip()))
        break
print()
print("奇匠按键（按下）每一列：")
n = 0
for line in lines:
    if "Enum.KeyEventType" not in line:
        continue
    m = re.search(r"KeyboardCraftspersonKey(\d+)Down", line)
    if not m:
        continue
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    n += 1
    if n <= 12 or n >= 28:
        print(f"  {m.group(1):>3}  列数={len(cells)}  {cells}")
print(f"\n共 {n} 个奇匠按键（按下）")
