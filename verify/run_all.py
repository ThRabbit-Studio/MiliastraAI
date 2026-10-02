#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键回归：构建 -> 语法/禁用构造 -> API 白名单 -> 离线交互验证。

改完 main.lua 或语料后跑这一个脚本就够了。任何一步失败以非 0 退出。

用法：
  python verify/run_all.py          # 完整回归（会重新构建数据段）
  python verify/run_all.py --quick  # 跳过构建，只跑检查
"""
from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

STEPS = [
    ("构建语料数据段", ["build/build_speech.py"]),
    ("字库自检", ["verify/check_lexicon.py"]),
    ("打字体验模拟", ["verify/simulate_typing.py"]),
    ("拼音引擎验证", ["verify/t_ime.py"]),
    ("语法与禁用构造", ["verify/check_syntax.py"]),
    ("API 白名单", ["verify/check_api_allowlist.py"]),
    ("生成网页试用", ["verify/make_demo.py"]),
]


def run(script: str) -> int:
    path = os.path.join(ROOT, script)
    if not os.path.exists(path):
        print(f"[FAIL] 找不到 {path}")
        return 1
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run([sys.executable, path], cwd=ROOT, env=env)
    return proc.returncode


def main() -> int:
    quick = "--quick" in sys.argv
    print("=" * 68)
    print("千星奇域离线对话 · 回归")
    print("=" * 68)
    failed = []
    for i, (name, argv) in enumerate(STEPS, start=1):
        if quick and name == "构建数据段":
            continue
        print(f"\n--- [{i}/{len(STEPS)}] {name} ---")
        code = run(argv[0])
        if code != 0:
            failed.append(name)

    print("\n" + "=" * 68)
    if failed:
        print(f"结果：{len(failed)} 步失败 -> {'、'.join(failed)}")
        return 1
    print("结果：全部通过")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
