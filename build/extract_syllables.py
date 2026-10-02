#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 Unihan.zip 提取「单字 -> 完整拼音音节（无声调）」。

与 extract_unihan.py 的区别：那个只要首字母（用于问法检索），这个要完整音节
（用于拼音输入法：玩家打 "nihao"，脚本要切成 ni + hao 再查字）。

产物：data/unihan_syllables.json
  {"_meta": {...}, "map": {"4F60": "ni", "597D": "hao", ...}}
"""
from __future__ import annotations

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
OUT_PATH = os.path.join(DATA, "unihan_syllables.json")

TONE_MAP = str.maketrans({
    "ā": "a", "á": "a", "ǎ": "a", "à": "a",
    "ē": "e", "é": "e", "ě": "e", "è": "e",
    "ī": "i", "í": "i", "ǐ": "i", "ì": "i",
    "ō": "o", "ó": "o", "ǒ": "o", "ò": "o",
    "ū": "u", "ú": "u", "ǔ": "u", "ù": "u",
    "ǖ": "v", "ǘ": "v", "ǚ": "v", "ǜ": "v", "ü": "v",
    "ń": "n", "ň": "n", "ḿ": "m",
})


def syllable_of(reading: str) -> str | None:
    """把带调拼音归一成无声调音节。ü 统一写成 v（玩家键盘上没有 ü）。"""
    s = reading.strip().lower().translate(TONE_MAP)
    s = re.sub(r"[^a-z]", "", s)
    return s or None


def main() -> int:
    if not os.path.exists(ZIP_PATH):
        print(f"[FAIL] 缺少 {ZIP_PATH}")
        return 1
    with open(ZIP_PATH, "rb") as fh:
        blob = fh.read()
    sha = hashlib.sha256(blob).hexdigest().upper()
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        name = [n for n in zf.namelist() if n.endswith("Unihan_Readings.txt")][0]
        text = zf.read(name).decode("utf-8")

    mapping: dict[str, str] = {}
    conflicts: dict[str, set[str]] = {}
    stat = {"lines": 0, "kmandarin": 0, "conflict": 0, "bad": 0}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        stat["lines"] += 1
        parts = line.split("\t")
        if len(parts) < 3 or parts[1] != "kMandarin":
            continue
        stat["kmandarin"] += 1
        code = parts[0].strip().upper().removeprefix("U+")
        first = re.split(r"[\s,]+", parts[2].strip())[0]
        syl = syllable_of(first)
        if syl is None:
            stat["bad"] += 1
            continue
        if code in mapping and mapping[code] != syl:
            # 同字多音：记下来，构建字表时以第一个读音为准并提示
            stat["conflict"] += 1
            conflicts.setdefault(code, {mapping[code]}).add(syl)
            continue
        mapping[code] = syl

    doc = {
        "_meta": {
            "source": "https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip",
            "member": name,
            "zip_sha256": sha,
            "extracted_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "entries": len(mapping),
            "stats": stat,
            "note": "kMandarin 的首读音；同字多音取第一个，冲突数见 stats.conflict",
        },
        "map": mapping,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    print(f"[OK] 完整音节表 {len(mapping)} 字，多音冲突 {stat['conflict']} 条")
    print(f"     已写入 {OUT_PATH}（{os.path.getsize(OUT_PATH)} 字节）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
