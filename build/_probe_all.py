#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时排查：58 个键鼠 keydown 事件的全部物理键，按类分组。"""
import sys

sys.path.insert(0, "build")
import gen_keymap as G  # noqa: E402

ev = G.parse_doc()
print(f"共 {len(ev)} 个 keydown\n")
letters, others = [], []
for e in ev:
    p = e["phys"] or "?"
    if len(p) == 1 and p.isalpha():
        letters.append((p.upper(), e["event"], e["desc"]))
    else:
        others.append((p, e["event"], e["desc"]))

print(f"--- 占用了字母的键（{len(letters)} 个）---")
for p, n, d in sorted(letters):
    print(f"  {p}  {n:<42} {d}")
print(f"\n--- 其它键（{len(others)} 个）---")
for p, n, d in others:
    print(f"  {p:<10} {n:<42} {d}")
