#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在「20MB 关卡上限 + 纯 Lua 解算」下，各档模型的表现对照。

这个脚本回答一个问题：要让回复时长可接受，模型最多能有多大？
反过来，给定模型大小，回复要等多久？

实测量级：lupa 上纯 Lua 整数乘加循环约 2e7~5e7 次/秒。
真机 CPU 通常弱于桌面，取 1.5e7 作保守值、4e7 作乐观值。
"""
from __future__ import annotations

LUA_MACS_SLOW = 1.5e7   # 保守（手机 / 老 CPU）
LUA_MACS_FAST = 4.0e7   # 乐观（桌面 CPU）
LEVEL_LIMIT = 20 * 1024 * 1024
# 20MB 要留给脚本本身，权重最多占 16MB；base64 每参数 1.33 字节
WEIGHT_BUDGET = 16 * 1024 * 1024
BYTES_PER_PARAM = 4 / 3

# (名称, 参数M, 词表, hidden, 层数)
MODELS = [
    ("MiniMind2-Small", 26.0, 6400, 768, 12),
    ("MiniMind2 (base)", 104.0, 6400, 768, 16),
    ("自训 8M（约 Small 的 1/3）", 8.0, 3200, 512, 6),
    ("自训 4M", 4.0, 2400, 384, 6),
    ("意图分类器 0.5M（不生成文字）", 0.5, 2400, 128, 2),
]


def mac_per_token(vocab: int, hidden: int, layers: int) -> float:
    emb = vocab * hidden
    per_layer = 4 * hidden * hidden + 2 * hidden * (4 * hidden)
    return emb + layers * per_layer


def main() -> None:
    print("=" * 84)
    print("在千星沙箱里跑神经网络：各档模型对照")
    print(f"（关卡上限 20MB，权重预算 {WEIGHT_BUDGET/1024/1024:.0f}MB，"
          f"Lua 解算 {LUA_MACS_SLOW/1e7:.1f}e7~{LUA_MACS_FAST/1e7:.1f}e7 MAC/s）")
    print("=" * 84)
    print(f"{'模型':<30}{'参数':>8}{'int8权重':>10}{'装得下?':>9}"
          f"{'每字':>14}{'20字回复':>16}")
    for name, pm, vocab, hidden, layers in MODELS:
        params = pm * 1e6
        weight_bytes = params * BYTES_PER_PARAM
        fits = "是" if weight_bytes <= WEIGHT_BUDGET else "否"
        mac = mac_per_token(vocab, hidden, layers)
        t_lo = mac / LUA_MACS_FAST
        t_hi = mac / LUA_MACS_SLOW
        reply_lo = t_lo * 20
        reply_hi = t_hi * 20
        print(f"{name:<30}{pm:>7.1f}M{weight_bytes/1024/1024:>9.1f}M{fits:>9}"
              f"{t_lo:>6.2f}~{t_hi:.2f}s{reply_lo:>7.0f}~{reply_hi:.0f}s")

    print()
    print("读法：")
    print("  · 回复时长按 20 个字算。玩家能接受的上限大约是 3~5 秒，")
    print("    也就是每字 0.15~0.25 秒 —— 对应模型规模约 0.5M~1M 参数。")
    print("  · MiniMind2-Small 每字 1.8~4.5 秒，20 字要 36~90 秒，远超可接受范围。")
    print("  · 体积不是瓶颈（16MB 能装 12M 参数），**速度才是瓶颈**。")


if __name__ == "__main__":
    main()
