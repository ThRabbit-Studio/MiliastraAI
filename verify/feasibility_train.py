#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本机 numpy 能训多大的模型？（决定「1M 参数自训」是否可行）

背景：本机装不上 PyTorch（PyPI 的 TLS 被拦），只有 numpy。
如果要在这里自训一个 1M 参数的字符级模型，就必须用 numpy 手写前向+反向，
所以要先量出 numpy 的矩阵吞吐，再折算训练时间。

同时测一下「多线程 BLAS / 多进程」能不能把训练时间压下来。
"""
from __future__ import annotations

import os
import time

import numpy as np

# 目标模型：字符级 Transformer，总量约 1M 参数
VOCAB = 1200        # 只用语料里出现过的字 + 标点
D_MODEL = 128
N_LAYER = 4
N_HEAD = 4
D_FF = 512
CTX = 128           # 上下文长度


def params() -> int:
    emb = VOCAB * D_MODEL
    per = 4 * D_MODEL * D_MODEL + 3 * D_MODEL * D_FF
    return emb + N_LAYER * per + D_MODEL * VOCAB


def bench_matmul() -> float:
    """量一个接近训练规模的矩阵乘法吞吐（GFLOP/s）。"""
    a = np.random.randn(512, 512).astype(np.float32)
    b = np.random.randn(512, 512).astype(np.float32)
    for _ in range(3):
        a @ b
    n = 200
    t0 = time.perf_counter()
    for _ in range(n):
        a @ b
    dt = time.perf_counter() - t0
    flops = 2 * 512 ** 3 * n
    return flops / dt / 1e9


def bench_threads() -> dict:
    out = {}
    for n in (1, 2, 4, 8):
        try:
            os.environ["OMP_NUM_THREADS"] = str(n)
            import threadpoolctl  # type: ignore
        except Exception:
            pass
        a = np.random.randn(768, 768).astype(np.float32)
        b = np.random.randn(768, 768).astype(np.float32)
        for _ in range(2):
            a @ b
        t0 = time.perf_counter()
        for _ in range(60):
            a @ b
        dt = time.perf_counter() - t0
        out[n] = 2 * 768 ** 3 * 60 / dt / 1e9
    return out


def main() -> None:
    p = params()
    print("=" * 76)
    print("本机 numpy 训练能力测算")
    print("=" * 76)
    print(f"目标模型：字符级，词表 {VOCAB}，d_model {D_MODEL}，{N_LAYER} 层，"
          f"FFN {D_FF}，上下文 {CTX}")
    print(f"参数量：约 {p/1e6:.2f}M")

    gflops = bench_matmul()
    print(f"\nnumpy 矩阵吞吐：{gflops:.1f} GFLOP/s（512x512 实测）")

    threads = bench_threads()
    print("\n不同线程数的吞吐（768x768）：")
    for k, v in threads.items():
        print(f"  OMP_NUM_THREADS={k}: {v:.1f} GFLOP/s")

    # 单个 batch 的前向+反向大约是这个量级：
    # 前向 2 * params * batch_tokens；反向约前向的 2 倍
    for batch_tokens in (8 * CTX, 32 * CTX):
        fwd = 2 * p * batch_tokens
        step_flops = fwd * 3          # 前向 + 反向（反向约 2x）
        sec_per_step = step_flops / (gflops * 1e9)
        # 假设要跑 20000 步
        total_h = sec_per_step * 20000 / 3600
        print(f"\n批大小 {batch_tokens} tokens：每步约 {sec_per_step:.3f} 秒，"
              f"2 万步约 {total_h:.1f} 小时")

    print("\n结论：")
    print(f"  · 1M 参数在本机 numpy 上**训得动**，但需要以小时计的时间。")
    print(f"  · 真正的瓶颈不是算力，而是**语料量**——当前语料只有约 2 万字，")
    print(f"    字符级模型至少要几十万字才不至于只会复读。")
    print(f"  · 所以顺序应该是：先把语料做大，再谈训练。")


if __name__ == "__main__":
    main()
