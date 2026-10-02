#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拼音首字母工具（构建期用，不进入游戏运行时）。

职责：
  1. 载入 Unihan 提取出的「字 -> 首字母」权威表；
  2. 校验对话语料库里每个汉字都有首字母，否则**构建失败**（不允许静默出错）；
  3. 生成 Lua 侧需要的紧凑首字母数据。

设计原则：
  - 构建期严格：语料里出现未收录的字，直接报错并列出，绝不猜。
  - 运行期宽松：匹配算法按「有序子序列」打分，个别字首字母不准也不会崩。
  - 无第三方依赖：只用标准库，因为这台机器 pip 连不上 PyPI。
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
UNIHAN_PATH = os.path.join(DATA, "unihan_initials.json")

# 语料里允许出现的非汉字字符（标点、数字、拉丁字母、空白）
NON_HAN_OK = re.compile(r"[\u3000-\u303f\uff00-\uffef\u2000-\u206f0-9A-Za-z\s,.;:!?()\[\]{}/\\'\"~`#$%^&*+=|<>_-]")


class PinyinTable:
    """字 -> 拼音首字母 的查询表。"""

    def __init__(self, path: str = UNIHAN_PATH):
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"缺少拼音表 {path}\n"
                f"请先运行：python build/extract_unihan.py（需要 build/Unihan.zip）"
            )
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        self._meta = doc.get("_meta", {})
        # JSON 里 key 是十六进制码点字符串，转成真正的字符
        self._map: dict[str, str] = {}
        for code_hex, ini in doc["map"].items():
            code_hex = code_hex.strip().upper().removeprefix("U+")
            self._map[chr(int(code_hex, 16))] = ini

    @property
    def meta(self) -> dict:
        return dict(self._meta)

    def initial(self, ch: str) -> str | None:
        return self._map.get(ch)

    def initials_of(self, text: str) -> str:
        """把一段中文转成首字母串。非汉字字符直接丢弃（标点不参与输入匹配）。"""
        out = []
        for ch in text:
            ini = self._map.get(ch)
            if ini:
                out.append(ini.upper())
        return "".join(out)

    def missing_chars(self, text: str) -> list[str]:
        """列出文本里查不到首字母的汉字（排除标点、数字、拉丁字母）。"""
        miss = []
        for ch in text:
            if ch in self._map:
                continue
            if NON_HAN_OK.match(ch):
                continue
            if ch not in miss:
                miss.append(ch)
        return miss


def audit_corpus(corpus_texts: list[str]) -> tuple[bool, list[str], PinyinTable]:
    """检查语料所有汉字都有首字母，返回 (是否通过, 缺失字列表, 表)。"""
    table = PinyinTable()
    missing: list[str] = []
    for text in corpus_texts:
        for ch in table.missing_chars(text):
            if ch not in missing:
                missing.append(ch)
    return (len(missing) == 0), missing, table


if __name__ == "__main__":
    t = PinyinTable()
    print(f"[OK] 拼音表 {len(t._map)} 字，来源 {t.meta.get('source', '?')}")
    for probe in ["你是谁", "怎么获得神之眼", "这里有什么好玩的", "给我讲讲这个世界"]:
        print(f"     {probe} -> {t.initials_of(probe)}")
    sys.exit(0)
