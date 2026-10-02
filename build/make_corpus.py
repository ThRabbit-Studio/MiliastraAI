#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把语料扩到能训字符级模型的规模。

为什么需要：
  字符级模型至少要几十万字的语料，否则只会复读训练集里的句子。
  当前语料只有约 2 万字，直接拿去训必然失败。
  而本机没有可用的中文语料来源（HF 主站被拦、PyPI TLS 被拦），
  所以只能**自己造**。

怎么造得不那么假：
  不是随机拼字，而是按「问法模板 × 答句骨架 × 槽位词表」组合，
  并保证每一条都是语法通顺、语义可读的中文句子。
  代价是内容重复度高（同一句式换词），所以它的用途明确——
  让字符级模型学会「这个助手的说话方式、常用字、句长分布」，
  而不是让它学会百科知识。
  这一点必须写清楚，不能把它当成真语料。

输出：data/train_corpus.txt（每行一条对话轮次，用于字符级训练）
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from itertools import product

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "train_corpus.txt")
SRC = os.path.join(DATA, "corpus_plain.json")

SEP = "\u0001"      # 轮次分隔符（训练时映射成特殊 token）

# ── 槽位词表 ────────────────────────────────────────────────────────────────
# 主语 / 对象 / 场景，用于把模板撑开成大量不同句子
SUBJECTS = ["你", "这个助手", "它", "这类模型", "人工智能", "语言模型",
            "这套系统", "这些东西", "我们", "大家", "我", "他们"]
TOPICS = ["学习方法", "工作效率", "写作", "翻译", "编程", "数据分析",
          "时间管理", "沟通表达", "记忆技巧", "阅读理解", "逻辑思维",
          "情绪管理", "职业规划", "健康作息", "理财", "旅行计划",
          "演讲准备", "会议记录", "项目排期", "需求分析"]
VERBS = ["解释", "说明", "介绍", "分析", "总结", "整理", "拆解", "梳理",
         "对比", "评估", "优化", "改进", "检查", "复盘"]
OBJECTS = ["这个方案", "这段文字", "这个问题", "那份报告", "这个想法",
           "这些数据", "那份计划", "这个流程", "那段代码", "这个结论"]
FEELINGS = ["有点累", "很开心", "挺焦虑", "很平静", "有点烦躁", "特别兴奋",
            "比较迷茫", "很放松", "压力很大", "状态不错"]
ADVICE = ["先停下来歇一会儿", "把事情拆小一点再动手", "先把最要紧的那件做完",
          "别一次想太多", "找个安静的角落待十分钟", "把想法写下来再看",
          "先睡一觉再决定", "找个人聊两句", "给自己留点余量"]
REASONS = ["因为一次做太多容易乱", "因为人的注意力本来就有限",
           "因为急着推进通常会更慢", "因为想清楚比做快更重要",
           "因为休息也是进度的一部分", "因为标准不明确就容易返工"]

# ── 问法模板 ────────────────────────────────────────────────────────────────
Q_TEMPLATES = [
    "{S}能{VERB}一下{O}吗",
    "帮我{VERB}一下{O}",
    "{O}怎么{VERB}",
    "我想让你{VERB}{O}",
    "{S}会怎么{VERB}{O}",
    "能不能{VERB}一下{O}",
    "关于{T}，{S}有什么建议",
    "{T}方面我该注意什么",
    "{T}要怎么入门",
    "我想提升{T}，怎么做比较好",
    "你觉得{T}重要吗",
    "{T}难不难",
    "{T}需要多久才能有进步",
    "我最近{FEEL}，怎么办",
    "我今天{FEEL}",
    "{FEEL}的时候该做什么",
    "为什么会{FEEL}",
    "{S}能理解{FEEL}这种感觉吗",
]

# ── 答句骨架 ────────────────────────────────────────────────────────────────
A_TEMPLATES = [
    "可以。我先把{O}{VERB}一遍，重点放在结构上，你看完再告诉我要不要调整。",
    "{O}的话，建议先看它想解决什么，再看它怎么做到，最后看有没有遗漏。",
    "这件事不难，难的是把标准说清楚。{O}你想达到什么程度？",
    "我{VERB}完了：{O}里有三处可以再收紧，我已经标出来放在下面。",
    "关于{T}，我一般建议从最小的那一步开始，先做起来再谈优化。",
    "{T}没有捷径，但有顺序：先弄清目标，再找方法，最后才谈效率。",
    "{FEEL}的时候，{ADVICE}。{REASON}。",
    "我明白那种感觉。{ADVICE}，等缓过来再处理也不迟。",
    "{REASON}，所以{ADVICE}会更有用。",
    "这个问题问得好。简单说：先判断它属于哪一类，再对症下药。",
    "我不确定你指的是哪一种情况，你能再说细一点吗？",
    "这个我不太清楚，怕说错了误导你。你可以换个问法，或者问点别的。",
    "我答不上来。这类具体信息我手里没有，你得自己再核一下。",
    "好，我记下了。你接着说。",
    "嗯，我在听。",
    "可以，你说。",
]

# ── 与语料无关的通用对话骨架（撑句长分布） ────────────────────────────────
CHITCHAT = [
    "你好。有什么想问的直接说就行。",
    "在的，你说吧。",
    "嗯，我在。",
    "行，我看看。",
    "这个问题我熟，你把背景说清楚点。",
    "先别急，我们一步一步来。",
    "你先把需求写出来，我帮你理一遍。",
    "可以，不过我需要更多信息才能给准建议。",
    "换个角度想，这件事可能没那么麻烦。",
    "有道理，那你打算怎么开始？",
    "我建议先试一个小样本，看看效果再说。",
    "如果是我，我会先把最不确定的那部分先验证掉。",
]


def gen_templates(rng: random.Random, limit: int) -> list[str]:
    """按模板组合出对话轮次。"""
    out = []
    seen = set()
    combos = list(product(SUBJECTS, VERBS, OBJECTS))
    rng.shuffle(combos)
    for s, v, o in combos:
        q = rng.choice(Q_TEMPLATES).format(S=s, VERB=v, O=o,
                                           T=rng.choice(TOPICS),
                                           FEEL=rng.choice(FEELINGS))
        a = rng.choice(A_TEMPLATES).format(S=s, VERB=v, O=o,
                                           T=rng.choice(TOPICS),
                                           FEEL=rng.choice(FEELINGS),
                                           ADVICE=rng.choice(ADVICE),
                                           REASON=rng.choice(REASONS))
        line = q + SEP + a
        if line not in seen:
            seen.add(line)
            out.append(line)
        if len(out) >= limit:
            break
    # 主题向
    for t in TOPICS:
        for qt in Q_TEMPLATES:
            for at in A_TEMPLATES:
                q = qt.format(S=rng.choice(SUBJECTS), VERB=rng.choice(VERBS),
                              O=rng.choice(OBJECTS), T=t,
                              FEEL=rng.choice(FEELINGS))
                a = at.format(S=rng.choice(SUBJECTS), VERB=rng.choice(VERBS),
                              O=rng.choice(OBJECTS), T=t,
                              FEEL=rng.choice(FEELINGS),
                              ADVICE=rng.choice(ADVICE),
                              REASON=rng.choice(REASONS))
                line = q + SEP + a
                if line not in seen:
                    seen.add(line)
                    out.append(line)
                if len(out) >= limit:
                    return out
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=120000, help="最多生成多少轮")
    ap.add_argument("--seed", type=int, default=20261002)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    lines: list[str] = []

    # 1) 真实语料：原样放进来（这部分是「真」的）
    with open(SRC, encoding="utf-8") as fh:
        corpus = json.load(fh)
    p = corpus["persona"]
    for q in corpus["questions"]:
        for variant in q["q"]:
            for a in q["a"]:
                lines.append(variant + SEP + a)
    for a in p["unknown"]:
        lines.append("（无法回答的问题）" + SEP + a)
    n_real = len(lines)
    print(f"[i] 真实语料 {n_real} 轮")

    # 2) 闲聊骨架
    for c in CHITCHAT:
        lines.append(c + SEP + rng.choice(CHITCHAT))
    n_chat = len(lines) - n_real

    # 3) 模板扩充
    lines.extend(gen_templates(rng, max(0, args.limit - len(lines))))
    lines = list(dict.fromkeys(lines))     # 去重且保序

    total_chars = sum(len(x) for x in lines)
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")

    print(f"[i] 闲聊骨架 {n_chat} 轮")
    print(f"[OK] 训练语料 {len(lines)} 轮 / {total_chars} 字"
          f" -> {os.path.relpath(OUT, ROOT)}（{os.path.getsize(OUT):,} 字节）")
    print()
    print("⚠ 这份语料里绝大多数是模板生成的，用途只有一个：")
    print("  让字符级模型学会「这个助手的说话方式、常用字、句长分布」。")
    print("  它**不是**知识语料，不能指望模型从中学到事实。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
