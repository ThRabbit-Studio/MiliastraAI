# MiliastraAI · 千星奇域内置 AI 对话

> 在《原神》千星奇域（千星沙箱）里跑一个能对话的 AI。
> **不联网、不调外部大模型**——所有逻辑都跑在客户端 Lua 脚本里。

[English](#english) | 中文

---

## 先说清楚平台边界

这几条不是"难不难"的问题，是千星沙箱的能力边界。绕不过去，只能按它设计：

| 你可能期望的 | 是否支持 | 依据 |
|---|---|---|
| 调用外部大模型 API（DeepSeek / GPT…） | **不支持**。客户端 Lua 没有任何网络接口，唯一对外通道是 `ServerSignal` → 服务器节点图，节点图也不接外网 | 客户端控件 API 文档 §9 |
| 玩家用系统输入法打字 | **不支持**。没有文本输入控件，也没有 IME 接口 | 文档 §15 §16 |
| 玩家按键输入 | **支持，但只有固定的 49 个映射键**，没有通用字符回调 | 文档 §26 |
| 模型在关卡里本地跑 | **支持** | 本项目就是这么做的 |

**所以"能对话"在这里只有一种可行形态**：脚本自己带拼音字库，玩家打拼音逐字选字拼出句子，脚本本地匹配语料作答。

## 内置拼音输入法

这是本项目的核心：**玩家打完整拼音，脚本切分音节、给候选汉字、逐字定字**。

```
玩家输入   n i h a o m a
切分       ni | hao | ma
候选       你好  吗
选字       1 → 你好      （词级匹配，一次定两个字）
           1 → 吗
成句       你好吗
```

- **词级优先**：`mingzi` → `名字`，一次定两个字。单字级无法消歧（`ming` 到底是「名」还是「命」），必须靠词。
- **上下文消歧**：已定「什么」后再打 `ming`，候选里「名」会被提到首位（靠语料问法统计出的搭配表）。
- **答不了就直说**：问法匹配用的是字面重合度 F1，低于阈值直接回「我不知道」，不硬凑答案。

### 实测指标

| 指标 | 数值 |
|---|---|
| 内置字库 | 787 字 / 297 个有字音节 / 412 条音节表 |
| 词表 | 575 个词 |
| 语料 | 30 个主题 / 126 种问法 / 90 条答句变体 |
| 语料用字可打率 | **100%**（AI 说的每个字玩家都能打出来，构建期强制校验） |
| 问法可打率 | **126/126 = 100%** |
| 完全不用挑字的问法 | **77/126 = 61%**（零次数字键） |
| 平均数字键次数 | **0.95 次/问法** |

## 快速开始

```bash
# 1. 取 Unihan 数据（拼音读音的权威来源，8.3MB）
#    下载 https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip
#    放到 build/Unihan.zip

# 2. 提取数据表
python build/extract_unihan.py        # 字 -> 拼音首字母
python build/extract_syllables.py     # 字 -> 完整音节
python build/extract_commonness.py    # 字频与年级（候选排序用）
python build/derive_syllables.py      # 反推真实音节表

# 3. 生成拼音字库 + 打包进脚本
python build/build_lexicon.py         # -> ime/ime_data.lua
python build/build_speech.py          # -> out/main.lua（单文件交付物）

# 4. 一键回归（构建 + 字库自检 + 打字模拟 + 引擎验证 + 语法 + API 白名单）
python verify/run_all.py
```

交付物是 `out/main.lua`，单文件，贴进千星沙箱的客户端脚本即可。

## 目录结构

```
build/    构建脚本：从 Unihan 提取数据、生成字库、打包 main.lua
ime/      拼音引擎源码（构建时内联进 main.lua，但可单独测试）
          engine_util.lua     汉字识别（显式 UTF-8 解码，不依赖 locale）
          engine_segment.lua  连续拼音切分（贪心最长匹配）
          engine_compose.lua  输入成句（词级优先 + 上下文消歧）
          engine_match.lua    语义匹配（字面重合 F1）
data/     语料与中间数据
out/      main.lua（正式交付物）
verify/   离线验证：字库自检、打字模拟、Lua 引擎验证、语法、API 白名单
docs/     交付说明、创作者操作步骤、构建报告
```

## 为什么引擎源码单独放在 `ime/`

部署必须是单文件（客户端脚本只挂一个入口），但把 4000 行全写在一个文件里没法测。
所以引擎拆成 4 个模块，**构建时按顺序内联进 `main.lua`**：源码可单独阅读和测试，产物仍是单文件。

## 离线验证怎么做的

本机没有原神，所以验证分三层，全部不需要真机：

1. **Python 参考实现**（`verify/simulate_typing.py`、`verify/check_lexicon.py`）：快速评估打字体验与字库覆盖；
2. **真实 Lua 引擎验证**（`verify/t_ime.py`）：用 lupa 内嵌 Lua 加载真实 `main.lua`，跑同一套流程，与参考实现比对；
3. **静态检查**（`verify/check_syntax.py`、`verify/check_api_allowlist.py`）：语法、沙箱禁用构造、每个 `game.*` 调用都必须能在文档里找到依据。

**真机仍未验证**，详见 `docs/交付说明.md` 的待核对项。

## 构建期强制校验（这是质量的关键）

以下情况会**直接构建失败**，而不是默默产出坏数据：

- 语料里有汉字不在内置字库里（AI 会说出玩家打不出来的字）
- 问法里出现拉丁字母等非汉字字符（玩家打不出来）
- 字库里有字查不到读音，或读音不是真实音节
- 语料结构不完整、id 重复、字段为空

## 数据来源与许可

- 拼音读音、字频、教学年级：**Unicode Unihan 数据库**（`kMandarin` / `kHanyuPinlu` / `kGradeLevel`），提取结果带来源 URL 与 SHA256，见 `data/*.json` 的 `_meta`。
- 语料：本项目自行编写。
- 代码：见 `LICENSE`。

## 已知限制

- 只能打内置字库里的 787 个字；生僻字打不出来。要扩展就改 `ime/lexicon_groups.json` 再重新构建。
- 词表 575 个词，不是完整词库；没有词条时退回单字级，需要玩家挑字。
- 语料 126 种问法，问法之外的问题一律回「我不知道」——这是有意设计，不是缺陷。

---

<a name="english"></a>
## English

An offline conversational AI for **Genshin Impact's Miliastra Wonderland** (千星奇域), running entirely inside the client-side Lua sandbox.

**Hard platform limits** (design constraints, not implementation gaps):

- **No network access.** No HTTP/socket API in client Lua; the only outbound path is `ServerSignal` to the server node graph, which is also offline. Calling an external LLM API is impossible.
- **No text input.** There is no text field control and no IME hook; the engine only exposes 49 fixed mapped keys.

**Therefore the only viable conversational form** is: the script ships its own pinyin lexicon, the player types pinyin and picks characters one by one, and matching happens locally against a dialogue corpus.

**Built-in pinyin IME:** word-level first (`mingzi` → 名字), context-aware single-character disambiguation, and an explicit "I don't know" when relevance falls below threshold.

Measured: 787 characters / 412 syllables / 575 words; **100%** of corpus questions are typeable (126/126); **61%** need zero keystrokes; average **0.95** keystrokes per question.

```bash
python build/build_lexicon.py   # build lexicon from Unihan
python build/build_speech.py    # emit single-file out/main.lua
python verify/run_all.py        # full offline regression
```

Extraction data comes from the Unicode **Unihan** database (`kMandarin`, `kHanyuPinlu`, `kGradeLevel`), with source URL and SHA256 recorded in each `data/*.json` `_meta` block.
