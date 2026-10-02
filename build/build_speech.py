#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建：data/corpus_plain.json -> Lua 数据段，并把拼音引擎内联进 out/main.lua。

做四件事：
  1. 校验语料结构化字段齐全、id 唯一；
  2. 用 Unihan 表把每个问法转成拼音首字母，**有汉字查不到就构建失败**；
  3. 生成 Lua 紧凑数据表，替换 out/main.lua 中 ©BANK_BEGIN/END© 之间的内容；
  4. 产出构建报告 docs/构建报告.md，含逐字首字母审计表（可人工抽查）。

用法：
  python build/build_speech.py            # 构建（缺 out/main.lua 时从模板复制）
  python build/build_speech.py --check    # 只校验，不写文件
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from pinyin import PinyinTable  # noqa: E402

DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "out")
DOCS = os.path.join(ROOT, "docs")
IME = os.path.join(ROOT, "ime")
QUESTIONS = os.path.join(DATA, "corpus_plain.json")
TARGET = os.path.join(OUT, "main.lua")
REPORT = os.path.join(DOCS, "构建报告.md")

BEGIN = "-- [[SPEECH_BANK_BEGIN]] 以下内容由 build/build_speech.py 生成，请勿手改"
END = "-- [[SPEECH_BANK_END]]"

# 拼音引擎源码；构建时按顺序内联进 main.lua（单文件部署，但源码可单独测试）
ENGINE_FILES = [
    "ime/engine_segment.lua",
    "ime/engine_util.lua",
    "ime/engine_compose.lua",
    "ime/engine_match.lua",
]
IME_BEGIN = "-- [[IME_ENGINE_BEGIN]] 以下内容由 build/build_speech.py 从 ime/ 内联，请勿手改"
IME_END = "-- [[IME_ENGINE_END]]"

# 千星客户端 Lua 里标识符不能用的字符
ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def lua_quote(s: str) -> str:
    """按 Lua 字符串字面量转义。只处理确实需要转义的字符。"""
    out = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20:
            out.append("\\%d" % ord(ch))
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def lua_array(items: list[str], indent: str) -> str:
    if not items:
        return "{}"
    body = (",\n" + indent).join(lua_quote(x) for x in items)
    return "{\n" + indent + body + ",\n" + indent[:-4] + "}"


def validate(bank: dict) -> list[str]:
    errs: list[str] = []
    if bank.get("schema") != "speech-bank/1":
        errs.append(f"schema 不是 speech-bank/1：{bank.get('schema')!r}")
    if not isinstance(bank.get("persona"), dict):
        errs.append("缺少 persona")
    qs = bank.get("questions")
    if not isinstance(qs, list) or not qs:
        errs.append("questions 必须是非空数组")
        return errs
    seen: set[str] = set()
    for i, q in enumerate(qs):
        where = f"questions[{i}]"
        qid = q.get("id")
        if not isinstance(qid, str) or not ID_RE.match(qid):
            errs.append(f"{where}.id 非法（需为 Lua 标识符）：{qid!r}")
            continue
        if qid in seen:
            errs.append(f"{where}.id 重复：{qid}")
        seen.add(qid)
        for field in ("cat", "topic"):
            if not isinstance(q.get(field), str) or not q[field].strip():
                errs.append(f"{where}.{field} 缺失或为空")
        for field in ("q", "a"):
            arr = q.get(field)
            if not isinstance(arr, list) or not arr:
                errs.append(f"{where}.{field} 必须是非空数组")
            elif not all(isinstance(x, str) and x.strip() for x in arr):
                errs.append(f"{where}.{field} 存在空字符串项")
    persona = bank.get("persona") or {}
    # greeting / tone 允许为空：普通 AI 助手的语料没有人设问候语，也没有语气动作描写
    if not isinstance(persona.get("greeting"), str):
        errs.append("persona.greeting 必须是字符串（可以为空）")
    for field in ("unknown", "tooShort"):
        val = persona.get(field)
        if not isinstance(val, list) or not val:
            errs.append(f"persona.{field} 必须是非空数组")
    for field in ("confirm", "tone"):
        val = persona.get(field, [])
        if not isinstance(val, list):
            errs.append(f"persona.{field} 必须是数组（可以为空）")
    return errs


def collect_texts(bank: dict) -> list[str]:
    texts: list[str] = []
    p = bank["persona"]
    if p.get("greeting"):
        texts.append(p["greeting"])
    for field in ("unknown", "tooShort", "confirm", "tone"):
        texts.extend(p.get(field) or [])
    for q in bank["questions"]:
        texts.extend(q["q"])
        texts.extend(q["a"])
    return texts


def read_block(path: str, begin: str, end: str) -> str:
    """读出一个被标记包裹的文件段。"""
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    if begin not in src or end not in src:
        raise SystemExit(f"[FAIL] {path} 里找不到标记 {begin}")
    return src.split(begin, 1)[1].split(end, 1)[0]


def build_lua_block(bank: dict, table: PinyinTable) -> tuple[str, dict]:
    """生成 Lua 数据段，同时返回构建统计。"""
    # 问法索引：把同一 id 的所有同义问法都变成 (首字母, id)
    entries: list[tuple[str, str, str]] = []  # (initials, id, 原问法)
    for q in bank["questions"]:
        for variant in q["q"]:
            ini = table.initials_of(variant)
            if not ini:
                raise SystemExit(f"[FAIL] 问法「{variant}」转换后首字母为空")
            entries.append((ini, q["id"], variant))

    # 排序：先按首字母长度，再按字典序 —— 短输入更快命中，且构建结果稳定
    entries.sort(key=lambda e: (len(e[0]), e[0], e[1]))
    # 同一 (首字母,id) 只留一条，附上最短原文做显示
    dedup: dict[tuple[str, str], str] = {}
    for ini, qid, text in entries:
        key = (ini, qid)
        if key not in dedup or len(text) < len(dedup[key]):
            dedup[key] = text
    rows = [(ini, qid, text) for (ini, qid), text in dedup.items()]
    rows.sort(key=lambda r: (len(r[0]), r[0], r[1]))

    p = bank["persona"]
    lines: list[str] = []
    lines.append(BEGIN)
    lines.append("-- 生成时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    lines.append("-- 语料版本：%s   问法索引：%d 条" % (bank["schema"], len(rows)))
    lines.append("MOD.PERSONA = {")
    lines.append("    name     = %s," % lua_quote(p.get("name", "")))
    lines.append("    role     = %s," % lua_quote(p.get("role", "")))
    lines.append("    greeting = %s," % lua_quote(p.get("greeting", "")))
    lines.append("    unknown  = %s," % lua_array(p["unknown"], "                "))
    lines.append("    tooShort = %s," % lua_array(p["tooShort"], "                "))
    lines.append("    confirm  = %s," % lua_array(p.get("confirm") or ["好。"], "                "))
    lines.append("    tone     = %s," % lua_array(p.get("tone") or [], "                "))
    lines.append("}")
    lines.append("-- 问法索引：(拼音首字母大写, 主题id, 展示用问法, 首字母小写)")
    lines.append("-- 小写那一列是给「玩家打出中文后按同音补充打分」用的，避免运行时再做转换。")
    lines.append("MOD.BANK = {")
    for ini, qid, text in rows:
        lines.append("    { %s, %s, %s, %s },"
                     % (lua_quote(ini), lua_quote(qid), lua_quote(text),
                        lua_quote(ini.lower())))
    lines.append("}")
    lines.append("MOD.ANSWERS = {")
    for q in bank["questions"]:
        lines.append("    [%s] = %s," % (lua_quote(q["id"]), lua_array(q["a"], "        ")))
    lines.append("}")
    lines.append("MOD.TOPICS = {")
    for q in bank["questions"]:
        lines.append(
            "    [%s] = { cat = %s, topic = %s },"
            % (lua_quote(q["id"]), lua_quote(q["cat"]), lua_quote(q["topic"]))
        )
    lines.append("}")
    lines.append(END)

    stat = {
        "questions": len(bank["questions"]),
        "variants": sum(len(q["q"]) for q in bank["questions"]),
        "index_rows": len(rows),
        "answers": sum(len(q["a"]) for q in bank["questions"]),
        "block_bytes": len("\n".join(lines).encode("utf-8")),
    }
    return "\n".join(lines), stat


def write_report(bank: dict, table: PinyinTable, stat: dict, texts: list[str], lua_file: str) -> None:
    os.makedirs(DOCS, exist_ok=True)
    chars: dict[str, set[str]] = {}
    for text in texts:
        for ch in text:
            ini = table.initial(ch)
            if ini:
                chars.setdefault(ini.upper(), set()).add(ch)

    lines: list[str] = []
    lines.append("# 构建报告 — 千星奇域离线对话（输入：拼音首字母）")
    lines.append("")
    lines.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("## 1. 规模")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| 主题数 | {stat['questions']} |")
    lines.append(f"| 同义问法数 | {stat['variants']} |")
    lines.append(f"| 问法索引条数（去重后） | {stat['index_rows']} |")
    lines.append(f"| 答句变体数 | {stat['answers']} |")
    lines.append(f"| 生成数据段字节数 | {stat['block_bytes']} |")
    lines.append(f"| 目标文件 | `{os.path.relpath(lua_file, ROOT)}` |")
    lines.append("")
    meta = table.meta
    lines.append("## 2. 拼音依据")
    lines.append("")
    lines.append("所有汉字的首字母来自 Unicode 官方 Unihan 的 `kMandarin` 字段，非人工录入：")
    lines.append("")
    lines.append(f"- 来源：{meta.get('source', '?')}")
    lines.append(f"- zip SHA256：`{meta.get('zip_sha256', '?')}`")
    lines.append(f"- 提取时间：{meta.get('extracted_at', '?')}")
    lines.append(f"- 收录字数：{meta.get('entries', '?')}")
    lines.append("")
    total_chars = sum(len(v) for v in chars.values())
    lines.append(f"## 3. 语料用字审计（共 {total_chars} 个字头，全部已收录）")
    lines.append("")
    lines.append("| 首字母 | 用到的字 |")
    lines.append("|---|---|")
    for ini in sorted(chars):
        lines.append(f"| {ini} | {' '.join(sorted(chars[ini]))} |")
    lines.append("")
    lines.append("## 4. 构建期强制校验")
    lines.append("")
    lines.append("- 语料中每个汉字都必须能在 Unihan 表里查到首字母，否则构建**直接失败**；")
    lines.append("- 因此本表不存在「猜的拼音」，上表任意一行都可人工抽查。")
    lines.append("")
    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = ap.parse_args()

    with open(QUESTIONS, encoding="utf-8") as fh:
        bank = json.load(fh)

    errs = validate(bank)
    if errs:
        print("[FAIL] 语料校验未通过：")
        for e in errs:
            print("       -", e)
        return 1
    print("[OK] 语料结构校验通过")

    table = PinyinTable()
    texts = collect_texts(bank)
    ok, missing, _ = _audit(texts, table)
    if not ok:
        print("[FAIL] 以下汉字在 Unihan 表中查不到拼音首字母，构建中止：")
        print("       " + " ".join(missing))
        print("       处理方式：换用同义字，或确认该字是否生僻到不该出现在对白里。")
        return 1
    print(f"[OK] 语料用字首字母全部可查（{len(set(''.join(texts)))} 个不同字符）")

    block, stat = build_lua_block(bank, table)
    print(
        "[OK] 生成数据段：主题 %d / 问法 %d / 索引 %d / 答句 %d / %d 字节"
        % (stat["questions"], stat["variants"], stat["index_rows"], stat["answers"], stat["block_bytes"])
    )

    # 拼音引擎：从 ime/ 内联进 main.lua，保证部署时仍是单文件
    engine = []
    for rel in ENGINE_FILES:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            print(f"[FAIL] 缺少引擎源码 {rel}")
            return 1
        with open(path, encoding="utf-8") as fh:
            src = fh.read().rstrip()
        engine.append(src)
        print(f"     内联 {rel}（{len(src.encode('utf-8'))} 字节）")
    engine_block = IME_BEGIN + "\n" + "\n\n".join(engine) + "\n" + IME_END
    eng_bytes = len(engine_block.encode("utf-8"))
    print(f"[OK] 内联拼音引擎 {len(ENGINE_FILES)} 个文件 / {eng_bytes} 字节")

    if args.check:
        print("[OK] --check 模式，未写入文件")
        return 0

    os.makedirs(OUT, exist_ok=True)
    if not os.path.exists(TARGET):
        print(f"[FAIL] 找不到 {TARGET}，请先放入 main.lua 骨架")
        return 1
    with open(TARGET, encoding="utf-8") as fh:
        lua = fh.read()

    for begin, end, payload, label in (
        (BEGIN, END, block, "语料数据段"),
        ("-- [[IME_DATA_BEGIN]] 以下内容由 build/build_lexicon.py 生成，请勿手改",
         "-- [[IME_DATA_END]]", None, "拼音字库"),
        (IME_BEGIN, IME_END, engine_block, "拼音引擎"),
    ):
        if payload is None:
            # 字库段已在 ime/ime_data.lua 里生成好，直接读出来替换
            src_path = os.path.join(ROOT, "ime", "ime_data.lua")
            if not os.path.exists(src_path):
                print(f"[FAIL] 缺少 {src_path}，请先运行 build/build_lexicon.py")
                return 1
            payload = open(src_path, encoding="utf-8").read().rstrip()
        if begin not in lua or end not in lua:
            print(f"[FAIL] {TARGET} 里找不到 {label} 的标记（{begin}）")
            return 1
        head, rest = lua.split(begin, 1)
        _old, tail = rest.split(end, 1)
        lua = head + payload + tail
        print(f"[OK] 已替换{label}")

    with open(TARGET, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(lua)
    print(f"[OK] 已写入 {TARGET}（{len(lua.encode('utf-8'))} 字节）")

    write_report(bank, table, stat, texts, TARGET)
    print(f"[OK] 已写入 {REPORT}")
    return 0


def _audit(texts: list[str], table: PinyinTable) -> tuple[bool, list[str], PinyinTable]:
    missing: list[str] = []
    for text in texts:
        for ch in table.missing_chars(text):
            if ch not in missing:
                missing.append(ch)
    return (len(missing) == 0), missing, table


if __name__ == "__main__":
    sys.exit(main())
