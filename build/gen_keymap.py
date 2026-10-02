#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 API 文档生成键表（唯一事实来源）。

规则（用户明确）：**文档列出来的才能用。**

之前的错误（记录在此，避免重犯）：
  我按「物理键栏与枚举序号错位一行」的猜测，推出枚举 11-36 = A-Z。
  实际上文档 §26(3) 的「默认物理键」栏是权威的，真实映射是：
    1-10 = 1..0 ；11-22 = U Z Y G H I O P J K L V ；23-28 = F5..F10 ；
    29 = ` ；30 = - ；31 = = ；32 = [ ；33 = , ；34 = . ；35 = / ；
    36-39 = 方向键 ；40 = 右Ctrl ；41 = 右Shift ；42 = Backspace ；43 = CapsLock
  结论：**只有 12 个字母有独立按键**，A B C D E F M N Q R S T W X 这 14 个
  字母没有对应事件。这就是「有几个键位用不了」的真正原因。

于是拼音字母分成两层（F 键切层，F 本身是枚举 16）：
  第 0 层（默认，12 个字母）：U Z Y G H I O P J K L V
  第 1 层（切层后，14 个字母里取 12 个映射到同样这 12 个键）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORKSPACE = os.path.dirname(ROOT)
DOC = os.path.join(WORKSPACE, "Lua客户端控件API文档.md")
OUT_JSON = os.path.join(ROOT, "data", "keymap.json")

# 文档里「默认物理键」栏 -> 我们的物理键名
PHYS_ALIAS = {
    "`": "BACKQUOTE", "-": "MINUS", "\\=": "EQUALS", "=": "EQUALS",
    "[": "LBRACKET", ",": "COMMA", ".": "PERIOD", "/": "SLASH",
    "↑": "UP", "↓": "DOWN", "←": "LEFT", "→": "RIGHT",
    "右Ctrl": "RCTRL", "右Shift": "RSHIFT", "Backspace": "BACKSPACE",
    "CapsLock": "CAPSLOCK",
}

# 第 1 层的字母分配：缺失的 14 个字母，10 个放到那 12 个可用字母键之外，
# 剩下 4 个放到标点键上（标点在有独立按键的键里，且拼音输入用不到标点）
LAYER1_LETTERS = list("ABCDEFMNP")
LAYER1_EXTRA = {"MINUS": "Q", "EQUALS": "R", "LBRACKET": "S",
                "COMMA": "T", "PERIOD": "W", "SLASH": "X"}


def parse_doc() -> list[tuple[int, str, str]]:
    """返回 [(枚举编号, 物理键名, 事件名)]，只含奇匠按键的「按下」。"""
    with open(DOC, encoding="utf-8") as fh:
        lines = fh.readlines()
    out = []
    for line in lines:
        if "Enum.KeyEventType" not in line:
            continue
        m = re.search(r"`(KeyboardCraftspersonKey(\d+)Down)`\s*\|([^|]*)\|\s*`([^`]*)`",
                      line)
        if not m:
            continue
        n = int(m.group(2))
        phys_raw = m.group(4).strip()
        phys = PHYS_ALIAS.get(phys_raw, phys_raw.upper())
        out.append((n, phys, m.group(1)))
    return sorted(out, key=lambda x: x[0])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    table = parse_doc()
    if not table:
        print("[FAIL] 没能从文档解析出奇匠按键")
        return 1
    print(f"[OK] 文档解析出奇匠按键 {len(table)} 个（枚举 "
          f"{table[0][0]}~{table[-1][0]}）")

    by_phys = {phys: (n, ev) for n, phys, ev in table}
    letters = [p for p in by_phys if len(p) == 1 and "A" <= p <= "Z"]
    letters.sort()
    print(f"     其中有独立按键的字母 {len(letters)} 个：{' '.join(letters)}")
    all_letters = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    missing = sorted(all_letters - set(letters))
    print(f"     没有按键的字母 {len(missing)} 个：{' '.join(missing)}")

    # 第 1 层：把缺失字母映射到可用的 12 个键 + 2 个标点键
    layer1 = {}
    avail = letters                       # 12 个可用字母键
    for phys, ch in zip(avail, LAYER1_LETTERS):
        layer1[phys] = ch
    for phys, ch in LAYER1_EXTRA.items():
        layer1[phys] = ch
    covered = set(layer1.values())
    still = sorted(all_letters - set(letters) - covered)
    print(f"     切层后覆盖缺失字母 {len(covered)} 个，仍缺 {still or '无'}")

    keymap = {
        "source": "Lua客户端控件API文档.md §26(3) Enum.KeyEventType",
        "rule": "文档列出的事件才能用；物理键取文档「默认物理键」栏",
        "events": {phys: ev for _n, phys, ev in table},
        "table": [{"n": n, "phys": phys, "event": ev} for n, phys, ev in table],
        "letters_direct": {p: p for p in letters},
        "letters_layer1": layer1,
        "layer_key": "I",        # 切层键（I = 枚举 16）
        "letters_missing": missing,
    }
    with open(OUT_JSON, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(keymap, fh, ensure_ascii=False, indent=1)
    print(f"[OK] 键表 -> {os.path.relpath(OUT_JSON, ROOT)}")

    # 生成 Lua 块
    lines = ["-- [[KEYMAP_BEGIN]] 由 build/gen_keymap.py 从 API 文档生成，请勿手改",
             "-- 文档列出的奇匠按键事件（唯一事实来源）",
             "MOD.KEY_EVENTS = {"]
    for n, phys, ev in table:
        lines.append(f'    ["{phys}"] = "{ev}",   -- 枚举 {n}')
    lines.append("}")
    lines.append("-- 第 0 层：有独立按键的 12 个字母")
    lines.append("MOD.LETTER_LAYER0 = {")
    for p in letters:
        lines.append(f'    ["{p}"] = "{p}",')
    lines.append("}")
    lines.append("-- 第 1 层：切层后同一批键输出另外 12 个字母")
    lines.append("MOD.LETTER_LAYER1 = {")
    for p, ch in sorted(layer1.items()):
        lines.append(f'    ["{p}"] = "{ch}",')
    lines.append("}")
    lines.append(f'MOD.LAYER_KEY = "{keymap["layer_key"]}"')
    lines.append("-- [[KEYMAP_END]]")
    print("[OK] Lua 键表块已生成（--write 可写入 main.lua）")

    if args.write:
        main_lua = os.path.join(ROOT, "out", "main.lua")
        with open(main_lua, encoding="utf-8") as fh:
            src = fh.read()
        b, e = "-- [[KEYMAP_BEGIN]]", "-- [[KEYMAP_END]]"
        if b not in src or e not in src:
            print(f"[!] {main_lua} 里没有 KEYMAP 标记，跳过")
        else:
            head, rest = src.split(b, 1)
            _, tail = rest.split(e, 1)
            with open(main_lua, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(head + "\n".join(lines) + tail)
            print("[OK] 已写入 main.lua")
    return 0


if __name__ == "__main__":
    sys.exit(main())
