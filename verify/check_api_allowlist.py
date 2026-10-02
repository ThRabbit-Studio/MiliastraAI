#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API 白名单检查：main.lua 里用到的每个 game.* / script.* / 控件方法，都必须能在
工作区的文档里找到依据。

为什么要单独做这一步：
  千星沙箱的 API 在别处运行不了，只能靠文档核对。凭印象写一个不存在的方法
  （比如 game.GetCanvasSize），真机上只会静默失败或报错，而且极难定位。
  这个检查把所有调用抠出来逐个对文档，杜绝「拍脑袋的 API」。

依据文件（都在工作区里，可回溯）：
  - Lua客户端控件API文档.md   （game / script / 控件方法 / 枚举）
  - annotations.lua            （上一轮交付整理的 API 摘要，带文档哈希）

用法：
  python verify/check_api_allowlist.py
  python verify/check_api_allowlist.py --lua out/main.lua
"""
from __future__ import annotations

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORKSPACE = os.path.dirname(ROOT)          # with_tools 目录
DOC = os.path.join(WORKSPACE, "Lua客户端控件API文档.md")
ANNOT = os.path.join(WORKSPACE, "annotations.lua")
DEFAULT_LUA = os.path.join(ROOT, "out", "main.lua")

# 本地定义的函数/表，不是 API，不参与检查
LOCAL_NAMES = {
    "OnInit", "OnStart", "OnEnable", "OnDisable", "OnUpdate", "OnLevelUpdate", "OnDestroy",
    "print", "printerr", "typeof", "rawset", "pcall", "ipairs", "pairs", "tostring",
    "tonumber", "type", "select", "error", "assert", "setmetatable", "getmetatable",
    "table", "string", "math", "os", "debug", "Color", "Enum", "script", "game",
    "require", "unpack", "next", "load",
}

# main.lua 实际用到的控件属性（文档 §13(1)/§14(1)/§15(1)）
CONTROL_PROPS = {
    "name", "text", "fontSize", "fontColor", "bgColor", "enableOutline", "outlineColor",
    "horizontalAlignment", "verticalAlignment", "adaptiveFontSize", "minimumFontSize",
    "imageColor", "imageType", "imageSource", "imageId", "alive", "id", "prefabIndex",
    "active", "visible", "parent", "sizeDeltaX", "sizeDeltaY",
    "anchoredPositionX", "anchoredPositionY", "pivotX", "pivotY",
    "anchorMinX", "anchorMinY", "anchorMaxX", "anchorMaxY",
    "localScaleX", "localScaleY", "localScaleZ",
    "localRotationX", "localRotationY", "localRotationZ",
    "canControllerFocus", "interactable", "showScrollBar", "raycastTarget",
}


def load_doc() -> str:
    with open(DOC, encoding="utf-8") as fh:
        return fh.read()


def load_annotations() -> str:
    if not os.path.exists(ANNOT):
        return ""
    with open(ANNOT, encoding="utf-8") as fh:
        return fh.read()


def extract_calls(src: str) -> dict[str, list[int]]:
    """抽出源文件里对宿主 API 的引用，返回 {种类: [行号]}。

    三种形态都要抓，否则检查会漏掉一大半：
      1. game.Xxx(...) / G().Xxx(...)      全局函数
      2. script:Xxx(...)                   脚本方法
      3. foo:Xxx(...) / pcall(foo.Xxx, ...) 控件方法
      4. foo.xxx = ...                     控件属性赋值（属性也是 API 的一部分）
    """
    calls: dict[str, list[int]] = {}

    def note(name: str, lineno: int) -> None:
        calls.setdefault(name, []).append(lineno)

    for lineno, line in enumerate(src.splitlines(), start=1):
        code = line.split("--", 1)[0]      # 去掉行尾注释

        # 1. game.Xxx / G().Xxx
        for m in re.finditer(r"\b(?:game|G\(\))\.([A-Za-z_][A-Za-z0-9_]*)", code):
            note("game." + m.group(1), lineno)

        # 2. script:Xxx
        for m in re.finditer(r"\bscript:([A-Za-z_][A-Za-z0-9_]*)", code):
            note("script:" + m.group(1), lineno)

        # 3. 控件方法：冒号调用，以及 pcall(obj.Method, ...) 这种传引用的写法
        for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([A-Z][A-Za-z0-9_]*)\s*\(", code):
            if m.group(1) in ("game", "script"):
                continue
            note("control:" + m.group(2), lineno)
        for m in re.finditer(r"\bpcall\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*([A-Z][A-Za-z0-9_]*)", code):
            note("control:" + m.group(2), lineno)

        # 4. 控件属性：只认我们实际用到的那些名字（避免把普通字段当 API）
        for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*([a-z][A-Za-z0-9_]*)\s*=", code):
            prop = m.group(2)
            if prop in CONTROL_PROPS:
                note("control." + prop, lineno)

    return calls


def check_against_doc(calls: dict[str, list[int]], doc: str, annot: str) -> list[str]:
    """逐项核对。返回问题列表（空表示全通过）。"""
    problems: list[str] = []
    hay = doc + "\n" + annot

    for name in sorted(calls):
        lines = ", ".join(str(n) for n in calls[name])
        kind, token = name.split(":", 1) if ":" in name else (name.split(".", 1)[0], name.split(".", 1)[1])
        if name.startswith("game."):
            if f"game.{token}" not in hay:
                problems.append(f"[无依据] {name}（行 {lines}）不在文档中")
        elif name.startswith("script:"):
            if token not in hay:
                problems.append(f"[无依据] {name}（行 {lines}）不在文档中")
        elif name.startswith("control."):
            # 属性：文档里以 `属性名` 出现
            if f"`{token}`" not in hay:
                problems.append(f"[无依据] 控件属性 {token}（行 {lines}）不在文档中")
        else:
            # 控件方法：文档里以 `MethodName` 或 MethodName( 出现
            if f"`{token}`" not in hay and f"{token}(" not in hay:
                problems.append(f"[无依据] 控件方法 {token}（行 {lines}）不在文档中")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lua", default=DEFAULT_LUA)
    args = ap.parse_args()

    if not os.path.exists(args.lua):
        print(f"[FAIL] 找不到 {args.lua}")
        return 1
    if not os.path.exists(DOC):
        print(f"[FAIL] 找不到依据文档 {DOC}")
        return 1

    with open(args.lua, encoding="utf-8") as fh:
        src = fh.read()
    doc = load_doc()
    annot = load_annotations()

    calls = extract_calls(src)
    problems = check_against_doc(calls, doc, annot)

    n_game = sum(1 for k in calls if k.startswith("game."))
    n_script = sum(1 for k in calls if k.startswith("script:"))
    n_ctrl = sum(1 for k in calls if k.startswith("control:"))
    print(f"[i] 扫描 {os.path.relpath(args.lua, WORKSPACE)}")
    print(f"    game.* {n_game} 个，script:* {n_script} 个，控件方法/属性 {n_ctrl} 个")

    if problems:
        print(f"[FAIL] {len(problems)} 项找不到文档依据：")
        for p in problems:
            print("       -", p)
        return 1

    print("[OK] 全部调用都能在工作区文档里找到依据")
    print()
    print("    核对到的 game.*：")
    for name in sorted(k for k in calls if k.startswith("game.")):
        print(f"      - {name}")
    print("    核对到的 script:*：")
    for name in sorted(k for k in calls if k.startswith("script:")):
        print(f"      - {name}")
    print("    核对到的控件方法与属性：")
    for name in sorted(k for k in calls if k.startswith("control")):
        print(f"      - {name.split('.', 1)[1] if name.startswith('control.') else name.split(':', 1)[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
