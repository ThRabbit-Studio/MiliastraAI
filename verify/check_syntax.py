#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""语法与禁用构造检查。

两件事：
  1. 语法：用 lupa 内嵌的真实 Lua 解释器把 out/main.lua 编译一遍，语法错直接暴露；
  2. 禁用构造：千星客户端 Lua 明确禁用了 io.* / coroutine.* / string.dump /
     除 os.time,os.date,os.clock,os.difftime 之外的 os.* / 除 debug.traceback 之外
     的 debug.*（见工作区 annotations.lua §运行环境），这里静态扫一遍防手滑。

用法：
  python verify/check_syntax.py
"""
from __future__ import annotations

import argparse
import os
import re
import sys

from lupa import LuaRuntime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_LUA = os.path.join(ROOT, "out", "main.lua")

# 禁用构造 -> 说明。正则匹配源码里出现的调用。
FORBIDDEN = [
    (r"\bio\s*\.", "io.* 在沙箱里被禁用（无文件读写）"),
    (r"\bcoroutine\s*\.", "coroutine.* 在沙箱里被禁用"),
    (r"\bstring\s*\.\s*dump\b", "string.dump 在沙箱里被禁用"),
    (r"\bos\s*\.\s*(?!time\b|date\b|clock\b|difftime\b)([A-Za-z_][A-Za-z0-9_]*)",
     "os.* 只允许 time/date/clock/difftime"),
    (r"\bdebug\s*\.\s*(?!traceback\b)([A-Za-z_][A-Za-z0-9_]*)",
     "debug.* 只允许 debug.traceback"),
    (r"\bloadstring\b", "loadstring 在 Lua 5.3+ 已移除"),
    (r"\brequire\s*\(", "外置 Lua 文件模式不支持 require"),
    (r"\bpackage\s*\.", "package 库在沙箱里不可用"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lua", default=DEFAULT_LUA)
    args = ap.parse_args()

    with open(args.lua, encoding="utf-8") as fh:
        src = fh.read()

    # 1) 语法
    lua = LuaRuntime()
    chunk = lua.eval("function(s) return load(s, '@main.lua', 't') end")(src)
    if chunk is None:
        print("[FAIL] 语法检查未通过")
        return 1
    print(f"[OK] 语法检查通过（lupa 内嵌 {lua.eval('_VERSION')}，"
          f"{len(src.splitlines())} 行 / {len(src.encode('utf-8'))} 字节）")

    # 2) 禁用构造
    problems = []
    for lineno, line in enumerate(src.splitlines(), start=1):
        code = line.split("--", 1)[0]
        if not code.strip():
            continue
        for pattern, why in FORBIDDEN:
            if re.search(pattern, code):
                problems.append(f"行 {lineno}: {code.strip()[:70]}  —— {why}")

    if problems:
        print(f"[FAIL] 命中 {len(problems)} 处禁用构造：")
        for p in problems:
            print("       -", p)
        return 1
    print("[OK] 未使用任何沙箱禁用构造")

    # 3) 生命周期回调齐全
    need = ["OnInit", "OnStart", "OnEnable", "OnDisable", "OnUpdate", "OnDestroy"]
    missing = [n for n in need if not re.search(rf"^function\s+{n}\s*\(", src, re.M)]
    if missing:
        print(f"[FAIL] 缺少生命周期回调：{missing}")
        return 1
    print(f"[OK] 生命周期回调齐全：{' '.join(need)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
