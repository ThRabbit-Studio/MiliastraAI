#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时排查：main.lua 为什么 load 失败。"""
from lupa import LuaRuntime

lua = LuaRuntime(unpack_returned_tuples=True)
src = open("out/main.lua", encoding="utf-8").read()
fn = lua.eval('function(s) return load(s, "main.lua", "t") end')
r = fn(src)
print("load 返回类型:", type(r))
if isinstance(r, tuple):
    print("长度:", len(r))
    print("第一个:", type(r[0]), repr(r[0])[:200])
    if len(r) > 1:
        print("第二个（错误）:", repr(r[1])[:500])
else:
    print("可调用:", callable(r))
