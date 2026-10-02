#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时排查：LETTER_KEY / EXTRA_EVENTS 暴露出来的内容。"""
import sys

sys.path.insert(0, "verify")
from lua_env import MockGame, build_env, load_script, lua_list  # noqa: E402

mock = MockGame()
lua, env = build_env(mock, [], [])
T = lua.table()
load_script(lua, env, T)

lk = {str(k): str(v) for k, v in T.LETTER_KEY.items()}
print("LETTER_KEY 共", len(lk))
for k in sorted(lk):
    print(f"   {k} -> {lk[k]}")
print()
try:
    ex = {str(k): str(v) for k, v in T.EXTRA_EVENTS.items()}
    print("EXTRA_EVENTS 共", len(ex), ex)
except Exception as e:  # noqa: BLE001
    print("EXTRA_EVENTS 读取失败:", type(e).__name__, e)
