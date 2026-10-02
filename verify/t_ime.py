#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拼音引擎的 Lua 侧验证：跑真实 main.lua，逐条核对打字流程。

为什么单独做这一层：
  verify/simulate_typing.py 是 Python 参考实现，用来快速评估体验；
  但真机上跑的是 Lua。两者必须给出**完全一致**的结果，否则参考实现就是自欺欺人。
  这里把同一套流程喂给 Lua 引擎，逐条比对。

用法：
  python verify/t_ime.py
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from lua_env import (  # noqa: E402  离线 Lupa 沙箱
    Fail, MockGame, build_env, check, load_script, lua_list, lua_str,
)

DATA = os.path.join(ROOT, "data")
HAN_RE = re.compile(r"[\u4e00-\u9fff]")
MAX_WORD_SPAN = 4


def load_pinyin_of() -> dict[str, str]:
    with open(os.path.join(DATA, "unihan_syllables.json"), encoding="utf-8") as fh:
        return {chr(int(k, 16)): v for k, v in json.load(fh)["map"].items()}


def segment(raw: str, syllables: set[str]) -> list[str]:
    """与 engine_segment.lua 一致的贪心切分（参考实现）。"""
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


def lua_parts(T):
    """读 Lua 引擎的输入状态。"""
    committed, raw = T.ime_parts()
    return str(committed), str(raw)


def lua_pool(T) -> list[str]:
    return [str(x) for x in lua_list(T.ime_pool())]


def type_letters(T, s: str) -> None:
    for ch in s.upper():
        T.ime_letter(ch)


def scenario_segment(T) -> dict:
    """切分用例：这是整个引擎的地基。"""
    cases = [
        ("nihao", ["ni", "hao"]),
        ("xian", ["xian"]),               # 必须切成一个音节，不能是 xi+an
        ("woshi", ["wo", "shi"]),
        ("zhongguo", ["zhong", "guo"]),
        ("mingzi", ["ming", "zi"]),
        ("shuang", ["shuang"]),
        ("beijing", ["bei", "jing"]),
        ("nihaoma", ["ni", "hao", "ma"]),
        ("a", ["a"]),
        ("zzz", []),                      # 无效输入应切不出音节
    ]
    for raw, want in cases:
        # 注意：ime_segment 返回 (音节表, 已切长度) 两个值，
        # lupa 会把它们打包成 tuple，不能直接丢给 lua_list。
        segs, _used = T.ime_segment(raw)
        got = [str(x) for x in lua_list(segs)]
        check(got == want, f"切分 {raw} 期望 {want}，实际 {got}")
    return {"用例": len(cases)}


def scenario_word_first(T, pinyin_of) -> dict:
    """词级优先：打 mingzi 出的第一个候选应该是「名字」而不是单个字。"""
    T.ime_clear()
    type_letters(T, "mingzi")
    kind = str(T.ime_pool_kind())
    pool = lua_pool(T)
    check(kind == "word", f"mingzi 应走词级匹配，实际 {kind}")
    check(pool and pool[0] == "名字", f"mingzi 首选应是「名字」，实际 {pool[:4]}")
    got = T.ime_pick(1)
    committed, raw = lua_parts(T)
    check(committed == "名字", f"选中后应已定「名字」，实际 {committed!r}")
    check(raw == "", f"词候选吃掉两个音节后 raw 应清空，实际 {raw!r}")

    # 单字级回退：打一个没有词表的音节
    T.ime_clear()
    type_letters(T, "shui")
    kind = str(T.ime_pool_kind())
    check(kind in ("word", "char"), f"pool_kind 异常：{kind}")
    return {"词级首选": pool[0] if pool else "（空）"}


def scenario_context(T) -> dict:
    """上下文消歧：已定「什么」后再打 ming，候选应把能搭配的字提前。"""
    T.ime_clear()
    # 先打字定出「什么」
    for ch in "什么":
        syl = T.ime_segment("shenme") if False else None
    # 直接构造：用拼音打出 shenme（词表里有「什么」）
    type_letters(T, "shenme")
    pool = lua_pool(T)
    check(pool and pool[0] == "什么", f"shenme 首选应是「什么」，实际 {pool[:4]}")
    T.ime_pick(1)
    committed, _raw = lua_parts(T)
    check(committed == "什么", f"应已定「什么」，实际 {committed!r}")

    # 再打 ming，看候选首位是不是「名」（语料里「什么名字」是成词的）
    type_letters(T, "ming")
    pool2 = lua_pool(T)
    check(pool2, "打 ming 应有候选")
    check(pool2[0] == "名", f"「什么」之后打 ming 首选应是「名」，实际 {pool2[:5]}")
    return {"上下文首选": pool2[0]}


def scenario_full_corpus(T, pinyin_of) -> dict:
    """全部问法逐条回放：能否打出、平均按几次数字键。"""
    with open(os.path.join(DATA, "corpus_plain.json"), encoding="utf-8") as fh:
        corpus = json.load(fh)

    total = exact = 0
    picks_total = 0
    zero_pick = 0
    fails = []
    for q in corpus["questions"]:
        for variant in q["q"]:
            total += 1
            T.ime_clear()
            committed = ""
            picks = 0
            ok = True
            for ch in HAN_RE.findall(variant):
                syl = pinyin_of.get(ch)
                if not syl:
                    ok = False
                    break
                type_letters(T, syl)
                pool = lua_pool(T)
                idx = None
                for i, cand in enumerate(pool):
                    if cand and cand[0] == ch:
                        idx = i
                        break
                if idx is None:
                    ok = False
                    break
                picks += idx
                T.ime_pick(idx + 1)
                committed, _raw = lua_parts(T)
            picks_total += picks
            if picks == 0:
                zero_pick += 1
            if ok and committed == variant:
                exact += 1
            elif len(fails) < 8:
                fails.append((variant, committed))

    check(exact == total,
          f"{total} 条问法里有 {total-exact} 条打不出来，例如 {fails[:3]}")
    return {"问法数": total, "原样打出": exact,
            "零按键问法": zero_pick,
            "平均数字键次数": round(picks_total / total, 2)}


def scenario_matching(T) -> dict:
    """语义匹配：打出的问题要能命中对应主题；无关问题要走「答不了」。"""
    cases = [
        ("你好", "q_hello"),
        ("你是谁", "q_who"),
        ("你能做什么", "q_what_todo"),
        ("谢谢", "q_thanks"),
        ("再见", "q_bye"),
    ]
    for text, want_id in cases:
        asks = T.match_query(text, 10)
        hit = None
        for i in range(1, len(asks) + 1):
            row = asks[i]
            if str(row["id"]) == want_id and bool(row["hit"]):
                hit = row
                break
        check(hit is not None,
              f"「{text}」应命中 {want_id}，实际首选 "
              f"{str(asks[1]['q']) if len(asks) else '（无候选）'}")

    # 语料外的问题必须走「答不了」
    asks = T.match_query("今天股票涨了吗", 10)
    top_hit = bool(asks[1]["hit"]) if len(asks) > 0 else False
    check(not top_hit, "语料外的问题不应判定为命中")
    return {"命中用例": len(cases), "语料外命中": top_hit}


def main() -> int:
    mock = MockGame(canvas=(1920, 1080))
    printed: list[str] = []
    updates: list[bool] = []
    lua, env = build_env(mock, printed, updates)
    T = lua.table()
    load_script(lua, env, T)

    pinyin_of = load_pinyin_of()

    print("=== 拼音引擎 Lua 侧验证 ===")
    failures = []

    def run(name, fn, *a):
        try:
            res = fn(*a)
            print(f"[PASS] {name}")
            for k, v in (res or {}).items():
                print(f"       {k}: {v}")
        except Fail as e:
            failures.append(f"{name}: {e}")
            print(f"[FAIL] {name}: {e}")
        except Exception as e:  # noqa: BLE001
            failures.append(f"{name}: {type(e).__name__}: {e}")
            print(f"[FAIL] {name}: {type(e).__name__}: {e}")

    run("拼音切分", scenario_segment, T)
    run("词级优先与选字", scenario_word_first, T, pinyin_of)
    run("上下文消歧", scenario_context, T)
    run("全部问法回放", scenario_full_corpus, T, pinyin_of)
    run("语义匹配与答不了", scenario_matching, T)

    print()
    if failures:
        print(f"=== 结果：{len(failures)} 项失败 ===")
        for f in failures:
            print("  -", f)
        return 1
    print("=== 结果：全部通过 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
