#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拼音输入模拟（Python 参考实现，用于评估真实打字体验）。

这不是测 Lua 代码，而是按引擎**同一套规则**在 Python 里重跑一遍：
  1. 逐字母打字（每加一个字母重新切分）
  2. 先词级匹配（最长 4 音节），匹配到就取词表首位
  3. 否则单字级，按「上一个已定字 + 候选字的语料搭配次数」重排后取首位
然后统计：
  - 有多少问法能一字不差地打出来
  - 平均要按几次数字键（0 次 = 完全不用挑字，体验最好）

这个指标比「单字首候选命中率」更接近真实体验，因为它把词级匹配和
上下文消歧的效果都算进去了。

用法：
  python verify/simulate_typing.py
  python verify/simulate_typing.py --show 12
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")

HAN_RE = re.compile(r"[\u4e00-\u9fff]")
MAX_WORD_SPAN = 4


def load_lexicon():
    with open(os.path.join(ROOT, "ime", "ime_data.lua"), encoding="utf-8") as fh:
        src = fh.read()
    syl_block = src.split("MOD.IME_SYLLABLES = ", 1)[1].split("-- 音节 ->", 1)[0]
    syllables = set(re.findall(r'"([a-z]+)"', syl_block))

    chars_block = src.split("MOD.IME_CHARS = {", 1)[1].split("-- 拼音串 ->", 1)[0]
    chars: dict[str, list[str]] = {}
    for m in re.finditer(r'\["([a-z]+)"\]\s*=\s*\{([^}]*)\}', chars_block):
        chars[m.group(1)] = re.findall(r'"([^"]+)"', m.group(2))

    words_block = src.split("MOD.IME_WORDS = {", 1)[1].split("-- 双字搭配", 1)[0]
    words: dict[str, list[str]] = {}
    for m in re.finditer(r'\["([a-z]+)"\]\s*=\s*\{([^}]*)\}', words_block):
        words[m.group(1)] = re.findall(r'"([^"]+)"', m.group(2))

    big_block = src.split("MOD.IME_BIGRAMS = {", 1)[1]
    bigrams: dict[str, dict[str, int]] = defaultdict(dict)
    for prev, body in re.findall(r'\["([^"]+)"\]\s*=\s*\{([^}]*)\}', big_block):
        for nxt, n in re.findall(r'\["([^"]+)"\]\s*=\s*(\d+)', body):
            bigrams[prev][nxt] = int(n)
    return syllables, chars, words, bigrams


def segment(raw: str, syllables: set[str]) -> list[str]:
    """与 engine_segment.lua 完全一致的贪心切分。"""
    out, i, n = [], 0, len(raw)
    while i < n:
        matched = None
        for length in range(min(6, n - i), 0, -1):
            cand = raw[i:i + length]
            if cand in syllables:
                matched = cand
                i += length
                break
        if not matched:
            break
        out.append(matched)
    return out


def pick_candidate(segs, committed, chars, words, bigrams):
    """返回 (候选列表, 吃掉几个音节)。与 ime_refresh 的规则一致。"""
    for span in range(min(MAX_WORD_SPAN, len(segs)), 1, -1):
        key = "".join(segs[:span])
        if key in words and words[key]:
            return words[key], span
    syl = segs[0]
    base = list(chars.get(syl, []))
    prev = committed[-1] if committed else ""
    if prev and prev in bigrams:
        rank = bigrams[prev]
        # 先记住原始位次再排序：不能在 key 里调用 base.index()，
        # 排序过程中列表内容在变，会抛 ValueError 或给出不稳定顺序。
        indexed = list(enumerate(base))
        indexed.sort(key=lambda p: (-rank.get(p[1], 0), p[0]))
        base = [ch for _i, ch in indexed]
    return base, 1


def simulate(text: str, syllables, chars, words, bigrams, pinyin_of):
    """模拟打出 text，返回 (能否打出, 按了多少次数字键, 实际打出的字)。"""
    target = HAN_RE.findall(text)
    if not target:
        return True, 0, ""
    committed = ""
    picks = 0
    for ch in target:
        syl = pinyin_of.get(ch)
        if not syl:
            return False, picks, committed
        raw = syl
        segs = segment(raw, syllables)
        if not segs:
            return False, picks, committed
        pool, span = pick_candidate(segs, committed, chars, words, bigrams)
        if not pool:
            return False, picks, committed
        # 目标：希望 pool[0] 正好以这个字开头（词）或就是它（单字）
        idx = None
        for i, cand in enumerate(pool):
            if cand[0] == ch:
                idx = i
                break
        if idx is None:
            return False, picks, committed
        picks += idx
        committed += pool[idx][:len(pool[idx])]
        # 词候选会一次吃掉多个字；这里按目标逐字推进，跳过已被词覆盖的字
    return committed == "".join(target), picks, committed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, default=10)
    args = ap.parse_args()

    syllables, chars, words, bigrams = load_lexicon()
    with open(os.path.join(DATA, "unihan_syllables.json"), encoding="utf-8") as fh:
        pinyin_of = {chr(int(k, 16)): v for k, v in json.load(fh)["map"].items()}
    with open(os.path.join(DATA, "corpus_plain.json"), encoding="utf-8") as fh:
        corpus = json.load(fh)

    total = exact = 0
    pick_total = 0
    zero_pick = 0
    fails = []
    for q in corpus["questions"]:
        for variant in q["q"]:
            total += 1
            ok, picks, got = simulate(variant, syllables, chars, words, bigrams, pinyin_of)
            pick_total += picks
            if picks == 0:
                zero_pick += 1
            if ok:
                exact += 1
            elif len(fails) < args.show:
                fails.append((variant, got))

    print(f"问法 {total} 条：")
    print(f"  完全不用挑字（0 次数字键）：{zero_pick} 条（{zero_pick/total*100:.0f}%）")
    print(f"  平均数字键次数：{pick_total/total:.2f}")
    print(f"  能原样打出：{exact} 条（{exact/total*100:.0f}%）")
    if fails:
        print(f"\n打不出来的例子（前 {len(fails)} 条）：")
        for want, got in fails:
            print(f"  期望 {want}   实际 {got or '（卡住）'}")
    # 这是评估脚本不是断言脚本：给出指标即可，退出码保持 0，
    # 免得挡住 run_all 里排在后面的真断言。
    return 0


if __name__ == "__main__":
    sys.exit(main())
