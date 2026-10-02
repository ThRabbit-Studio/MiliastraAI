#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成内置拼音字库的 Lua 数据段。

输入：
  ime/lexicon_groups.json        手写的语义分组字表（决定玩家能打出哪些字）
  data/unihan_syllables.json     字 -> 完整拼音音节（权威读音）
  data/syllables_real.json       真实音节表（用于切分连续拼音）
  data/corpus_plain.json         语料（用于校验覆盖度 + 给语料用字更高优先级）

输出：
  ime/ime_data.lua               由 build_speech.py 内联进 main.lua

关键校验（不通过就直接失败）：
  1. 分组里每个字都必须能在 Unihan 查到读音；
  2. 每个读音都必须是真实音节（否则玩家打不出来）；
  3. **语料里出现的每个汉字都必须在字库里**——否则 AI 说了玩家打不出的字，
     玩家就没法接着这个话题问下去。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")

GROUPS_PATH = os.path.join(ROOT, "ime", "lexicon_groups.json")
WORDS_PATH = os.path.join(ROOT, "ime", "word_groups.json")
SYLL_PATH = os.path.join(DATA, "unihan_syllables.json")
REAL_PATH = os.path.join(DATA, "syllables_real.json")
CORPUS_PATH = os.path.join(DATA, "corpus_plain.json")
COMMON_PATH = os.path.join(DATA, "unihan_commonness.json")
OUT_PATH = os.path.join(ROOT, "ime", "ime_data.lua")

BEGIN = "-- [[IME_DATA_BEGIN]] 以下内容由 build/build_lexicon.py 生成，请勿手改"
END = "-- [[IME_DATA_END]]"

HAN = lambda ch: "\u4e00" <= ch <= "\u9fff"  # noqa: E731
HAN_RE = re.compile(r"[\u4e00-\u9fff]")

# 字库目标字数：手写的常用字 + 自动扩充的常用字。
# 上限主要受体积约束（编辑器关卡 20MB）：3000 字约 200KB，远低于上限。
TARGET_CHARS = 3000


def lua_quote(s: str) -> str:
    out = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ord(ch) < 0x20:
            out.append("\\%d" % ord(ch))
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def lua_string_array(items: list[str], indent: str) -> str:
    """把列表写成 Lua 数组，每行若干项，便于人读与 diff。"""
    lines = []
    row = []
    for i, it in enumerate(items):
        row.append(lua_quote(it))
        if len(row) == 14:
            lines.append(indent + ", ".join(row) + ",")
            row = []
    if row:
        lines.append(indent + ", ".join(row) + ",")
    return "{\n" + "\n".join(lines) + "\n" + indent[:-4] + "}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    with open(GROUPS_PATH, encoding="utf-8") as fh:
        groups = json.load(fh)["groups"]
    with open(SYLL_PATH, encoding="utf-8") as fh:
        syl_map = {chr(int(k, 16)): v for k, v in json.load(fh)["map"].items()}
    with open(REAL_PATH, encoding="utf-8") as fh:
        real_syllables = json.load(fh)["syllables"]
    real_set = set(real_syllables)
    with open(CORPUS_PATH, encoding="utf-8") as fh:
        corpus = json.load(fh)

    # ---- 1. 逐字查读音 ----
    # 分两层：
    #   主力层 = ime/lexicon_groups.json 手写的常用字（有语义分组，人工确认过）
    #   扩充层 = 按 Unihan 年级 + 字频自动补齐到 TARGET_CHARS 字
    # 扩充足为了「玩家想打的字尽量都能打出来」，但不能挤掉主力层的位置，
    # 所以排序键里主力层永远优先（见下面的 order 表）。
    missing_reading: list[str] = []
    bad_syllable: list[tuple[str, str]] = []
    char_syllable: dict[str, str] = {}
    for gname, chars in groups.items():
        for ch in chars:
            if ch in char_syllable:
                continue
            syl = syl_map.get(ch)
            if not syl:
                missing_reading.append(ch)
                continue
            if syl not in real_set:
                bad_syllable.append((ch, syl))
                continue
            char_syllable[ch] = syl

    if missing_reading:
        print(f"[FAIL] 手写字库里 {len(missing_reading)} 个字查不到读音："
              f"{' '.join(missing_reading)}")
        return 1
    if bad_syllable:
        print(f"[FAIL] {len(bad_syllable)} 个手写字的读音不是真实音节：")
        for ch, syl in bad_syllable[:20]:
            print(f"       {ch} -> {syl}")
        return 1
    hand_count = len(char_syllable)

    # 自动扩充：按 (年级升序, 字频降序) 挑最常用的字补到目标字数
    common_all = {}
    if os.path.exists(COMMON_PATH):
        with open(COMMON_PATH, encoding="utf-8") as fh:
            common_all = json.load(fh)
    pinlu_all = common_all.get("pinlu", {})
    grade_all = common_all.get("grade", {})

    def commonness(ch: str) -> tuple:
        code = "%04X" % ord(ch)
        return (grade_all.get(code, 99), -pinlu_all.get(code, 0), ord(ch))

    cands = [ch for ch, syl in syl_map.items()
             if syl in real_set and ch not in char_syllable and HAN(ch)]
    cands.sort(key=commonness)
    added = 0
    for ch in cands:
        if len(char_syllable) >= TARGET_CHARS:
            break
        char_syllable[ch] = syl_map[ch]
        added += 1
    print(f"[OK] 字库 {len(char_syllable)} 字（手写 {hand_count} + 自动扩充 {added}，"
          f"目标 {TARGET_CHARS}）")
    if added == 0 and hand_count < TARGET_CHARS:
        print("[!] 没有可扩充的字，检查 extract_commonness.py 是否跑过")

    # ---- 2. 语料覆盖度 ----
    corpus_chars: Counter[str] = Counter()
    texts = [corpus["persona"]["greeting"]] + corpus["persona"]["unknown"] \
        + corpus["persona"]["tooShort"] + corpus["persona"]["confirm"]
    for q in corpus["questions"]:
        texts.extend(q["q"])
        texts.extend(q["a"])
    for t in texts:
        for ch in t:
            if HAN(ch):
                corpus_chars[ch] += 1

    not_in_lex: list[str] = sorted(set(corpus_chars) - set(char_syllable))
    if not_in_lex:
        print(f"[FAIL] 语料里有 {len(not_in_lex)} 个汉字不在内置字库里"
              f"（AI 会说出玩家打不出的字）：")
        print("       " + " ".join(not_in_lex))
        print("       处理：把这些字补进 ime/lexicon_groups.json 的某个分组。")
        return 1
    print(f"[OK] 语料用字 {len(corpus_chars)} 个，全部在字库内（玩家能打出 AI 说的每个字）")

    # 问法里出现拉丁字母就是个坑：玩家只能打汉字拼音，打不出 "AI"。
    # 这种问法在真机上永远选不中，必须在构建期拦下来。
    latin: list[tuple[str, str]] = []
    for q in corpus["questions"]:
        for variant in q["q"]:
            bad = [c for c in variant
                   if not HAN(c) and c not in "，。？！、；：（）…—· "]
            if bad:
                latin.append((q["id"], variant))
    if latin:
        print(f"[FAIL] {len(latin)} 条问法含打不出的字符（只能是汉字与中文标点）：")
        for qid, variant in latin[:10]:
            print(f"       {qid}: {variant}")
        return 1

    # ---- 3. 归并成「音节 -> 候选字」，并按真实常用度排序 ----
    # 排序键（越靠前越优先）：
    #   1) kHanyuPinlu 里有没有记录（有记录才算真常用字）
    #   2) 字频从高到低
    #   3) kGradeLevel 年级从低到高（小学的比初中的基础）
    #   4) 语料出现次数从高到低
    #   5) 语义分组顺序兜底
    # 教训：只按语义分组顺序排时，「名」会掉到第 11 位、整句回放只有 21%；
    # 换成 Unihan 的真实字频后常用字自然浮上来。
    common = {}
    if os.path.exists(COMMON_PATH):
        with open(COMMON_PATH, encoding="utf-8") as fh:
            common = json.load(fh)
    pinlu = common.get("pinlu", {})
    grade = common.get("grade", {})
    if not pinlu:
        print(f"[!] 缺少 {os.path.basename(COMMON_PATH)}，首候选排序会退化成分组顺序")
        print("     先跑：python build/extract_commonness.py")
    else:
        print(f"[OK] 读到字频表 {len(pinlu)} 字 / 年级表 {len(grade)} 字")

    corpus_freq: Counter[str] = Counter()
    for t in texts:
        for ch in HAN_RE.findall(t):
            corpus_freq[ch] += 1

    order: dict[str, tuple[int, int]] = {}
    hand_set = set()
    for gi, (gname, chars) in enumerate(groups.items()):
        for ci, ch in enumerate(chars):
            if ch not in order:
                order[ch] = (gi, ci)
                hand_set.add(ch)

    by_syllable: dict[str, list[str]] = defaultdict(list)
    for ch, syl in char_syllable.items():
        by_syllable[syl].append(ch)

    def rank(ch: str) -> tuple:
        code = "%04X" % ord(ch)
        freq = pinlu_all.get(code, 0)
        lvl = grade_all.get(code, 99)
        gi, ci = order.get(ch, (99, 99))
        # 第一优先级：手写层 > 自动扩充层。
        # 手写层是人工确认过的常用字，不能让自动扩充的冷僻字把它们挤下去。
        hand = 0 if ch in hand_set else 1
        return (0 if freq > 0 else 1, hand, -freq, lvl, -corpus_freq.get(ch, 0), gi, ci)

    table: dict[str, list[str]] = {}
    for syl, chars in by_syllable.items():
        chars.sort(key=rank)
        table[syl] = chars

    # 音节表：真实音节 ∪ 字库里用到的音节（保证切分认识它们）
    all_syllables = sorted(set(real_syllables) | set(table))
    print(f"[OK] 归并出 {len(table)} 个有字的音节，音节表共 {len(all_syllables)} 条")

    # ---- 4. 词表：拼音串 -> 候选词 ----
    # 单字级无法消歧（ming 到底是「名」还是「命」？），所以要做词级匹配。
    # 词表来源：手写常用词 + 从语料里抽出的二字组合。拼音由 Unihan 逐字查出后拼，
    # 不手写，避免录入错误；拼出来的拼音串必须能切成真实音节，否则丢弃。
    word_chars: set[str] = set()
    if os.path.exists(WORDS_PATH):
        with open(WORDS_PATH, encoding="utf-8") as fh:
            for w in json.load(fh)["words"]:
                w = w.strip()
                if 2 <= len(w) <= 4 and all(HAN(c) for c in w):
                    word_chars.add(w)

    # 语料里相邻两字组合（只要两字都在字库里就收），提高真实用词覆盖率
    corpus_words: Counter[str] = Counter()
    for t in texts:
        han = HAN_RE.findall(t)
        for i in range(len(han) - 1):
            bigram = han[i] + han[i + 1]
            if bigram[0] in char_syllable and bigram[1] in char_syllable:
                corpus_words[bigram] += 1
    for bigram, n in corpus_words.items():
        if n >= 2:          # 出现两次以上才认为是真词而不是巧合
            word_chars.add(bigram)

    def pinyin_of(word: str) -> str | None:
        parts = []
        for ch in word:
            syl = char_syllable.get(ch)
            if not syl:
                return None
            parts.append(syl)
        return "".join(parts)

    word_table: dict[str, list[str]] = defaultdict(list)
    for w in word_chars:
        py = pinyin_of(w)
        if not py:
            continue
        word_table[py].append(w)

    # 同一个拼音串有多个词时：语料里出现过的优先，短词优先
    def word_rank(w: str) -> tuple:
        return (-corpus_words.get(w, 0), len(w), w)

    words_out: dict[str, list[str]] = {}
    for py, ws in word_table.items():
        ws.sort(key=word_rank)
        words_out[py] = ws

    multi = sum(1 for ws in words_out.values() if len(ws) >= 1)
    print(f"[OK] 词表 {len(word_chars)} 个词，覆盖 {multi} 个拼音串"
          f"（其中来自语料 {sum(1 for w in word_chars if corpus_words.get(w, 0) >= 2)} 个）")

    # ---- 5. 上下文搭配表：用于单字候选的消歧 ----
    # 只用相邻二字（bigram）覆盖面太窄：语料里问法是「你叫什么名字」，
    # 玩家却可能先打出「什么」再打 ming，此时 bigram 里没有「什么名」这条。
    # 所以补一层**问法内共现**：同一句问法里出现过的字对，按距离加权记分。
    # 距离越近权重越高（相邻 3 分、隔一字 2 分、再远 1 分）。
    pair_score: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    # ⚠ 只用**问法**建这张表，不要用答句：
    #   答句又长又多，里面的字对大多是噪声（实测「什」的高频搭配全是答句里的
    #   远距离字对），会把问法里真正的搭配（如「什么」+「名」）挤出前几名。
    #   而玩家打字时模拟的正是问法，所以问法才是正确的训练信号。
    q_texts: list[str] = []
    for q in corpus["questions"]:
        q_texts.extend(q["q"])
    # 先按标点切子句，只在子句内部统计字对：
    #   跨子句的字对几乎都是噪声（「你有什么想问的」里的 什-问 并不是搭配），
    #   会把真正的搭配挤出前几名。
    CLAUSE_SPLIT = "，。？！、；：（）…—· "
    for t in q_texts:
        for clause in re.split("[" + CLAUSE_SPLIT + "]", t):
            han = HAN_RE.findall(clause)
            n = len(han)
            for i in range(n):
                for j in range(n):
                    if i == j:
                        continue
                    d = abs(i - j)
                    if d == 1:
                        w = 6
                    elif d == 2:
                        w = 4
                    elif d == 3:
                        w = 2
                    else:
                        continue
                    pair_score[han[i]][han[j]] += w

    print(f"[OK] 上下文搭配表 {len(pair_score)} 个字有搭配记录"
          f"（只用语料问法，共 {len(q_texts)} 条）")
    if os.environ.get("LEX_DEBUG"):
        for ch in "什":
            tops = sorted(pair_score[ch].items(), key=lambda kv: -kv[1])
            print(f"     [debug] {ch} 的搭配（门限>=4，最多 16）：")
            print("       " + ", ".join(f"{k}={v}" for k, v in tops if v >= 4))

    # ---- 6. 生成 Lua ----
    lines = [BEGIN]
    lines.append("-- 生成时间：%s" % __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    lines.append("-- 字库 %d 字 / 有字音节 %d 个 / 音节表 %d 条"
                 % (len(char_syllable), len(table), len(all_syllables)))
    lines.append("MOD.IME_SYLLABLES = " + lua_string_array(all_syllables, "    "))
    lines.append("-- 音节 -> 候选字（按常用度已排序，数字键从上往下选）")
    lines.append("MOD.IME_CHARS = {")
    for syl in sorted(table):
        lines.append("    [%s] = %s," % (lua_quote(syl), lua_string_array(table[syl], "        ")))
    lines.append("}")
    lines.append("-- 拼音串 -> 候选词（词级优先于单字：单字无法消歧）")
    lines.append("MOD.IME_WORDS = {")
    for py in sorted(words_out):
        lines.append("    [%s] = %s," % (lua_quote(py), lua_string_array(words_out[py], "        ")))
    lines.append("}")
    lines.append("-- 上下文搭配：prev -> { next = 权重 }，用于单字候选的上下文消歧")
    lines.append("MOD.IME_BIGRAMS = {")
    for prev in sorted(pair_score):
        # 保留「够强」的搭配，而不是固定取前 N 个：
        # 固定截断会把分数略低但语义正确的搭配切掉（实测「什」->「名」排第 13，
        # 被前 12 的截断线正好切掉，导致「什么」之后打 ming 首选还是「命」）。
        pairs = sorted(pair_score[prev].items(), key=lambda kv: -kv[1])
        pairs = [(k, v) for k, v in pairs if v >= 4][:20]
        body = ", ".join('[%s] = %d' % (lua_quote(k), v) for k, v in pairs if v > 0)
        if body:
            lines.append("    [%s] = { %s }," % (lua_quote(prev), body))
    lines.append("}")
    lines.append(END)
    block = "\n".join(lines)

    if args.check:
        print("[OK] --check，未写文件")
        return 0

    with open(OUT_PATH, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(block + "\n")
    print(f"[OK] 已写入 {OUT_PATH}（{len(block.encode('utf-8'))} 字节）")
    longest = max(table, key=lambda s: len(table[s]))
    print(f"     候选最多的音节：{longest} -> {len(table[longest])} 字")
    return 0


if __name__ == "__main__":
    sys.exit(main())
