#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""极小字符级语言模型（numpy 实现，带手写反向传播）。

为什么用 numpy 手写：
  本机装不上 PyTorch（PyPI TLS 被拦），只有 numpy。
  好在模型要压到 1M 参数以内，规模小到手写反向完全可行，
  而且自己实现的每一步都可验证——这对「导出到 Lua 后能否对齐」很关键。

支持两种架构：
  bigram  —— 只有一张 (V,V) 转移表。训练秒级，用来先跑通整条流水线、
             并给 Transformer 的输出质量做个下限参照。
  tiny    —— 1 层 Transformer（无位置编码），加一个前馈与残差。
             参数量控制在 1M 以内（词表 8000、d_model 64 时约 0.8M）。

接口（供 train / export 调用）：
  build_model(kind, config) -> dict           # 参数与缓存
  loss_and_grad(model, x, y) -> loss, grads   # x,y 都是 token 下标数组
  predict_next(model, token) -> 概率分布
"""
from __future__ import annotations

import math

import numpy as np


# ── 通用工具 ────────────────────────────────────────────────────────────────

def softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(axis=-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)


def layer_norm(x: np.ndarray, g: np.ndarray, b: np.ndarray,
               eps: float = 1e-5) -> tuple[np.ndarray, tuple]:
    mu = x.mean(axis=-1, keepdims=True)
    var = x.var(axis=-1, keepdims=True)
    inv = 1.0 / np.sqrt(var + eps)
    xn = (x - mu) * inv
    return xn * g + b, (x, xn, mu, var, inv, g)


def layer_norm_bwd(dout: np.ndarray, cache: tuple) -> tuple:
    x, xn, mu, var, inv, g = cache
    n = x.shape[-1]
    dg = (dout * xn).sum(axis=0)
    db = dout.sum(axis=0)
    dxn = dout * g
    dx = inv / n * (
        n * dxn
        - dxn.sum(axis=-1, keepdims=True)
        - xn * (dxn * xn).sum(axis=-1, keepdims=True)
    )
    return dx, dg, db


# ── bigram 基线 ─────────────────────────────────────────────────────────────

def build_bigram(vocab: int) -> dict:
    return {"kind": "bigram", "vocab": vocab, "W": np.zeros((vocab, vocab), np.float32)}


def bigram_loss_and_grad(model: dict, x: np.ndarray, y: np.ndarray):
    W = model["W"]
    logits = W[x]                              # (B, V)
    probs = softmax(logits)
    b = len(x)
    loss = -np.log(np.maximum(probs[np.arange(b), y], 1e-9)).mean()
    dlogits = probs.copy()
    dlogits[np.arange(b), y] -= 1.0
    dlogits /= b
    dW = np.zeros_like(W)
    np.add.at(dW, x, dlogits)
    return float(loss), {"W": dW}


def bigram_predict(model: dict, token: int) -> np.ndarray:
    return softmax(model["W"][token])


# ── tiny Transformer（1 层，无位置编码） ────────────────────────────────────

def build_tiny(vocab: int, d_model: int = 64, d_ff: int = 256,
               seed: int = 20261002) -> dict:
    rng = np.random.default_rng(seed)
    s = 0.02
    P = {
        "kind": "tiny", "vocab": vocab, "d": d_model, "f": d_ff,
        # 词嵌入（同时也是输出投影，省一半参数——对小模型很值得）
        "E": rng.normal(0, s, (vocab, d_model)).astype(np.float32),
        "g1": np.ones(d_model, np.float32), "b1": np.zeros(d_model, np.float32),
        # 前馈
        "W1": rng.normal(0, s, (d_model, d_ff)).astype(np.float32),
        "b1f": np.zeros(d_ff, np.float32),
        "W2": rng.normal(0, s, (d_ff, d_model)).astype(np.float32),
        "b2f": np.zeros(d_model, np.float32),
        "g2": np.ones(d_model, np.float32), "b2": np.zeros(d_model, np.float32),
    }
    return P


def tiny_params(model: dict) -> int:
    return sum(v.size for v in model.values() if isinstance(v, np.ndarray))


def tiny_loss_and_grad(model: dict, x: np.ndarray, y: np.ndarray):
    E, d, f = model["E"], model["d"], model["f"]
    h = E[x]                                   # (B, d)
    hn, c1 = layer_norm(h, model["g1"], model["b1"])
    # 前馈：GELU 近似用 tanh 版，反向简单
    z1 = hn @ model["W1"] + model["b1f"]
    t = np.tanh(z1)
    a1 = 0.5 * z1 * (1 + t)                    # 近似 GELU
    z2 = a1 @ model["W2"] + model["b2f"]
    out = hn + z2                              # 残差
    hn2, c2 = layer_norm(out, model["g2"], model["b2"])
    logits = hn2 @ E.T                         # 权重共享
    probs = softmax(logits)

    B = len(x)
    loss = -np.log(np.maximum(probs[np.arange(B), y], 1e-9)).mean()
    dlogits = probs.copy()
    dlogits[np.arange(B), y] -= 1.0
    dlogits /= B

    g = {}
    dhn2 = dlogits @ E
    g["E"] = dlogits.T @ hn2                   # 输出侧对 E 的梯度
    dout, g["g2"], g["b2"] = layer_norm_bwd(dhn2, c2)
    dhn = dout
    dz2 = dout
    g["W2"] = a1.T @ dz2
    g["b2f"] = dz2.sum(axis=0)
    da1 = dz2 @ model["W2"].T
    # 近似 GELU 的反向
    dz1 = da1 * (0.5 * (1 + t) + 0.5 * z1 * (1 - t * t))
    g["W1"] = hn.T @ dz1
    g["b1f"] = dz1.sum(axis=0)
    dhn2b = dz1 @ model["W1"].T
    dh, g["g1"], g["b1"] = layer_norm_bwd(dhn + dhn2b, c1)
    g["E"] = g["E"] + np.zeros_like(E)
    np.add.at(g["E"], x, dh)
    return float(loss), g


def tiny_predict(model: dict, token: int) -> np.ndarray:
    E = model["E"]
    h = E[[token]]
    hn, _ = layer_norm(h, model["g1"], model["b1"])
    z1 = hn @ model["W1"] + model["b1f"]
    t = np.tanh(z1)
    a1 = 0.5 * z1 * (1 + t)
    z2 = a1 @ model["W2"] + model["b2f"]
    out = hn + z2
    hn2, _ = layer_norm(out, model["g2"], model["b2"])
    return softmax(hn2 @ E.T)[0]


# ── 统一入口 ────────────────────────────────────────────────────────────────

def build_model(kind: str, vocab: int, **kw) -> dict:
    if kind == "bigram":
        return build_bigram(vocab)
    if kind == "tiny":
        return build_tiny(vocab, **kw)
    raise ValueError(f"未知架构：{kind}")


def n_params(model: dict) -> int:
    return sum(v.size for v in model.values() if isinstance(v, np.ndarray))


if __name__ == "__main__":
    for kind in ("bigram", "tiny"):
        m = build_model(kind, 8000)
        print(f"{kind:8} 参数量 {n_params(m):,}")
