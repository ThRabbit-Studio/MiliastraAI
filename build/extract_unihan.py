#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 Unihan.zip 提取「单字 -> 拼音首字母」权威表。

为什么要做这一步：
  千星奇域里用「拼音首字母」当输入，就必须保证「字 -> 首字母」的对应是对的。
  凭记忆写这张表一定会错，所以用 Unicode 官方 Unihan 数据库的 kMandarin 字段
  生成，并把 来源文件 + 文件哈希 + 提取时间 一起落盘，保证结论可回溯。

用法：
  python build/extract_unihan.py            # 需要 build/Unihan.zip 存在
  python build/extract_unihan.py --offline  # 只校验已生成的表，不读 zip

产物：data/unihan_initials.json
  {
    "_meta": { 来源、哈希、提取时间、条目数 },
    "map": { "4F60": "n", "4EEC": "m", ... }     # key = 码点大写十六进制
  }
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
ZIP_PATH = os.path.join(HERE, "Unihan.zip")
OUT_PATH = os.path.join(DATA, "unihan_initials.json")

# 声母表：按长度降序匹配，保证 zh/ch/sh 不被 z/c/s 抢走
INITIALS_BY_LEN = ("zh", "ch", "sh", "b", "p", "m", "f", "d", "t", "n", "l",
                   "g", "k", "h", "j", "q", "x", "r", "z", "c", "s", "y", "w")

# kMandarin 里出现声调字母，先归一化为无调形式
TONE_MAP = str.maketrans({
    "ā": "a", "á": "a", "ǎ": "a", "à": "a",
    "ē": "e", "é": "e", "ě": "e", "è": "e",
    "ī": "i", "í": "i", "ǐ": "i", "ì": "i",
    "ō": "o", "ó": "o", "ǒ": "o", "ò": "o",
    "ū": "u", "ú": "u", "ǔ": "u", "ù": "u",
    "ǖ": "v", "ǘ": "v", "ǚ": "v", "ǜ": "v", "ü": "v",
    "ń": "n", "ň": "n", "ḿ": "m",
})


def initial_of(syllable: str) -> str | None:
    """把一个无声调拼音音节切成声母。

    零声母（a/o/e 开头，如 哦 o、阿 a、儿 er、安 an）没有真正的声母，但也必须
    能在输入里表示出来，否则含这类字的问法玩家永远打不出来。
    做法是取它的**首字母元音**（o/a/e），因为 26 个字母全都有按键，
    这样规则统一、无需任何特殊键，而且拼音首字母输入法的习惯也是这样。
    """
    s = syllable.strip().lower().translate(TONE_MAP)
    s = re.sub(r"[^a-z]", "", s)
    if not s:
        return None
    for ini in INITIALS_BY_LEN:
        if s.startswith(ini):
            return ini
    # 走到这里说明是零声母，首字符必然是 a/o/e 之一
    return s[0].upper()


def parse_readings(text: str) -> tuple[dict[str, str], dict[str, int]]:
    """解析 Unihan_Readings.txt，返回 {码点: 首字母} 与统计。"""
    out: dict[str, str] = {}
    stat = {"lines": 0, "kmandarin": 0, "no_initial": 0, "conflict": 0}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        stat["lines"] += 1
        parts = line.split("\t")
        if len(parts) < 3 or parts[1] != "kMandarin":
            continue
        stat["kmandarin"] += 1
        # Unihan 的码点写作 U+4E00，这里统一去掉前缀并存大写十六进制
        code = parts[0].strip().upper().removeprefix("U+")
        value = parts[2]
        # kMandarin 可能是「nǐ」或「nǐ gé」这种多读音，取第一个读音
        first = re.split(r"[\s,]+", value.strip())[0]
        ini = initial_of(first)
        if ini is None:
            stat["no_initial"] += 1
            continue
        if code in out and out[code] != ini:
            stat["conflict"] += 1
            continue
        out[code] = ini
    return out, stat


def load_from_zip() -> tuple[dict[str, str], dict[str, int], dict]:
    with open(ZIP_PATH, "rb") as fh:
        blob = fh.read()
    sha = hashlib.sha256(blob).hexdigest().upper()
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = [n for n in zf.namelist() if n.endswith("Unihan_Readings.txt")]
        if not names:
            raise SystemExit("Unihan.zip 里找不到 Unihan_Readings.txt")
        text = zf.read(names[0]).decode("utf-8")
    mapping, stat = parse_readings(text)
    meta = {
        "source": "https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip",
        "member": names[0],
        "zip_sha256": sha,
        "zip_bytes": len(blob),
        "extracted_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "entries": len(mapping),
        "stats": stat,
    }
    return mapping, stat, meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="只读取已有产物做校验")
    args = ap.parse_args()

    os.makedirs(DATA, exist_ok=True)

    if args.offline:
        if not os.path.exists(OUT_PATH):
            print(f"[FAIL] 找不到 {OUT_PATH}，先联网跑一次")
            return 1
        with open(OUT_PATH, encoding="utf-8") as fh:
            doc = json.load(fh)
        print(f"[OK] 已有表：{len(doc['map'])} 条，提取于 {doc['_meta'].get('extracted_at')}")
        return 0

    if not os.path.exists(ZIP_PATH):
        print(f"[FAIL] 缺少 {ZIP_PATH}，请先下载 Unihan.zip")
        return 1

    mapping, stat, meta = load_from_zip()
    doc = {"_meta": meta, "map": mapping}
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    print(f"[OK] kMandarin 行 {stat['kmandarin']}，有效首字母 {len(mapping)} 条")
    print(f"     零声母跳过 {stat['no_initial']}，多音冲突跳过 {stat['conflict']}")
    print(f"     已写入 {OUT_PATH}（{os.path.getsize(OUT_PATH)} 字节）")
    print(f"     zip sha256 = {meta['zip_sha256'][:16]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
