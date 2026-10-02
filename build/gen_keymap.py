#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 API 文档生成键表（唯一事实来源）。

规则（用户明确）：**文档列出来的才能用。**

三次踩坑记录（都是为了不再重犯）：
  1. 最开始按「物理键栏与枚举序号错位一行」去推枚举 11-36 = A-Z —— 错的。
  2. 改从文档读，但只读了「奇匠按键」那批，漏了移动键/动作键/技能键，
     于是误判「只有 12 个字母可用」。
  3. 实际把文档里**全部键鼠按下事件**并起来看：
       覆盖 22 个字母：A D E F G H I J K L O P Q R S T U V W X Y Z
       缺失  4 个字母：B C M N
     与用户观察一致（用户说「只有四个字母没有」）。

那 4 个字母用空闲键补：F5-F10、` - = [ , . / 、方向键、右Ctrl、右Shift 都空着。
特意选 6 个功能/标点键，不与任何已有字母或功能冲突。

产物：data/keymap.json（供 main.lua 与自检共用）
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

# 物理键栏的写法 -> 我们的键名
PHYS_ALIAS = {
    "`": "BACKQUOTE", "-": "MINUS", "\\=": "EQUALS", "=": "EQUALS",
    "[": "LBRACKET", ",": "COMMA", ".": "PERIOD", "/": "SLASH",
    "↑": "UP", "↓": "DOWN", "←": "LEFT", "→": "RIGHT",
    "右Ctrl": "RCTRL", "右Shift": "RSHIFT", "Backspace": "BACKSPACE",
    "CapsLock": "CAPSLOCK", "Space": "SPACE", "Tab": "TAB",
    "鼠标左键": "MOUSE_LEFT", "鼠标右键": "MOUSE_RIGHT",
}
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    PHYS_ALIAS[_c] = _c
for _c in "1234567890":
    PHYS_ALIAS[_c] = _c
for _i in range(1, 11):
    PHYS_ALIAS[f"F{_i}"] = f"F{_i}"

# 给缺失字母分配：选当前没有任何用途的功能键
# （F5-F10 都在文档里、且原本没被用作字母；发送键改用 [ 后它们就空出来了）
MISSING_ASSIGN = {
    "B": "F5",
    "C": "F6",
    "M": "F7",
    "N": "F8",
}

# 发送键：必须是文档里列出的键，且不与字母/删除冲突。
# 原先是 F5，现在 F5 让给字母 B，发送改用 [（枚举 32）。
SEND_KEY = "LBRACKET"


def parse_doc() -> list[dict]:
    """抠出文档里全部「键鼠按下」事件。"""
    with open(DOC, encoding="utf-8") as fh:
        lines = fh.readlines()
    out = []
    for line in lines:
        if "Enum.KeyEventType" not in line:
            continue
        m = re.search(r"`(Keyboard[A-Za-z0-9_]+)`", line)
        if not m:
            continue
        name = m.group(1)
        if not name.endswith("Down"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        phys_raw = cells[3].strip("`").strip()
        phys = PHYS_ALIAS.get(phys_raw)
        out.append({"event": name, "desc": cells[2], "phys_raw": phys_raw,
                    "phys": phys})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    events = parse_doc()
    if not events:
        print("[FAIL] 没能从文档解析出键鼠事件")
        return 1
    print(f"[OK] 文档解析出键鼠「按下」事件 {len(events)} 个")

    # 字母覆盖
    letter_event: dict[str, str] = {}
    for e in events:
        p = e["phys"]
        if p and len(p) == 1 and p.isalpha():
            letter_event.setdefault(p.upper(), e["event"])
    covered = set(letter_event)
    want = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    missing = sorted(want - covered)
    print(f"     字母键事件覆盖 {len(covered)} 个字母：{''.join(sorted(covered))}")
    print(f"     缺失 {len(missing)} 个：{''.join(missing)}")

    # 补齐：把缺失字母挂到空闲键上
    used_keys = {e["phys"] for e in events if e["phys"]}
    extra = {}
    for ch in missing:
        k = MISSING_ASSIGN.get(ch)
        if not k:
            print(f"[FAIL] 缺失字母 {ch} 没有分配补键")
            return 1
        if k in used_keys:
            print(f"[FAIL] 补键 {k} 已被占用，换一个")
            return 1
        extra[ch] = k
        used_keys.add(k)
    print(f"     补齐方案：" + "  ".join(f"{ch}={k}" for ch, k in extra.items()))

    # 真正可用的字母键表：字母 -> 事件名
    letters: dict[str, str] = {}
    for ch, ev in letter_event.items():
        letters[ch] = ev
    phys_of_event = {e["event"]: e["phys"] for e in events}
    for ch, k in extra.items():
        # 补键本身没有字母事件，运行时用它的物理键事件来触发该字母
        letters[ch] = f"__BY_PHYS__{k}"

    keymap = {
        "source": "Lua客户端控件API文档.md §26(3) Enum.KeyEventType",
        "rule": "文档列出的事件才能用",
        "events": [{"event": e["event"], "phys": e["phys"],
                    "desc": e["desc"]} for e in events],
        "letters": letters,
        "letter_covered": sorted(covered),
        "letter_missing": missing,
        "extra_assign": extra,
    }
    with open(OUT_JSON, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(keymap, fh, ensure_ascii=False, indent=1)
    print(f"[OK] 键表 -> {os.path.relpath(OUT_JSON, ROOT)}")

    # 生成 Lua 块
    L = []
    L.append("-- [[KEYMAP_BEGIN]] 由 build/gen_keymap.py 从 API 文档生成，请勿手改")
    L.append("-- 键鼠「按下」事件（文档列出）= 唯一可用的按键来源")
    L.append("MOD.KEY_EVENTS = {")
    for e in events:
        if e["phys"]:
            L.append(f'    ["{e["phys"]}"] = "{e["event"]}",')
    L.append("}")
    L.append("-- 字母 -> 物理键（22 个来自文档，4 个是补键 B/C/M/N）")
    L.append("MOD.LETTER_KEY = {")
    for ch in sorted(letters):
        ev = letters[ch]
        if ev.startswith("__BY_PHYS__"):
            L.append(f'    ["{ch}"] = "{ev.replace("__BY_PHYS__", "")}",   -- 补键')
        else:
            phys = phys_of_event.get(ev, "")
            L.append(f'    ["{ch}"] = "{phys}",')
    L.append("}")
    L.append("-- [[KEYMAP_END]]")
    print("[OK] Lua 键表块已生成")

    if args.write:
        main_lua = os.path.join(ROOT, "out", "main.lua")
        with open(main_lua, encoding="utf-8") as fh:
            src = fh.read()
        b, e_ = "-- [[KEYMAP_BEGIN]]", "-- [[KEYMAP_END]]"
        if b not in src or e_ not in src:
            print(f"[!] {main_lua} 里没有 KEYMAP 标记，跳过写入")
        else:
            head, rest = src.split(b, 1)
            _, tail = rest.split(e_, 1)
            with open(main_lua, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(head + "\n".join(L) + tail)
            print("[OK] 已写入 main.lua")
    return 0


if __name__ == "__main__":
    sys.exit(main())
