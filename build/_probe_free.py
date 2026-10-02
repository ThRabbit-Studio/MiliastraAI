#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时排查：哪些物理键已被文档事件占用。"""
import sys

sys.path.insert(0, "build")
import gen_keymap as G  # noqa: E402

ev = G.parse_doc()
used = {e["phys"] for e in ev if e["phys"]}

print("F 系列相关事件：")
for e in ev:
    if e["phys"] and e["phys"].startswith("F"):
        print("   ", e["phys"], e["event"], "|", e["desc"])

print("\n候选补键占用情况：")
CAND = ["BACKQUOTE", "MINUS", "EQUALS", "LBRACKET", "COMMA", "PERIOD", "SLASH",
        "UP", "DOWN", "LEFT", "RIGHT", "RCTRL", "RSHIFT", "CAPSLOCK",
        "SPACE", "TAB", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8",
        "F9", "F10"]
FREE, TAKEN = [], []
for k in CAND:
    (TAKEN if k in used else FREE).append(k)
print("   已占用:", TAKEN)
print("   空闲  :", FREE)
