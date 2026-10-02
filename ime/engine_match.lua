-- ============================================================================
-- 拼音引擎 · 语义匹配与检索
--
-- 玩家打出的是自然中文（由拼音逐字选出来），所以这里不能再用「精确首字母」
-- 匹配，改成算**字面重合度**（按多重集）：
--   precision = 玩家打出的字里，有多少字出现在这条问法里
--   recall    = 这条问法里，有多少字被玩家打到
--   相关度    = 两者的调和平均（F1），对长短不对等比较公平
--
-- 相关度低于阈值就明确回答「答不了」，不硬凑一条不相干的答案。
--
-- 本文件由 build_speech.py 内联进 main.lua，不写 return / require。
-- ============================================================================

local MATCH_MIN = 0.60      -- 相关度低于此值视为「答不了」（宁可不答，不要答非所问）
local MATCH_KEEP = 0.40     -- 候选列表里保留的最低相关度

-- 把语料整理成便于打分的表（只做一次）。注意存的是**字频**不是集合。
local MATCH_BANK = {}
for i = 1, #MOD.BANK do
    local row = MOD.BANK[i]
    MATCH_BANK[#MATCH_BANK + 1] = {
        ini = row[1],
        id = row[2],
        q = row[3],
        chars = {},
        n = 0,
    }
    local e = MATCH_BANK[#MATCH_BANK]
    local cnt = han_counts(e.q)
    e.chars = cnt
    for _ch in pairs(cnt) do
        e.n = e.n + 1
    end
    -- 注意：n 这里是「不同字数」，用于算 recall；精确重合度靠 chars 里的计数
end

-- 玩家输入 -> 字频表。必须按**多重集**算重合：问法「你做不到什么」与
-- 「你能做什么」的不同字有 4 个重合，用集合算会得到假高分把精确匹配挤下去。
local function match_chars(text)
    return han_counts(text)
end

-- 相关度：字面重合的 F1。玩家已经用拼音逐字选出汉字，字面就是最强信号；
-- 掺拼音首字母只会引入同音噪声，所以不掺。
-- 用 F1 而非单纯相似度：「只打了问法一部分」和「打了问法之外的字」都会被罚。
local function match_score(qcnt, qn, e)
    if qn == 0 or e.n == 0 then return 0 end
    local hit = 0
    for ch, c in pairs(qcnt) do
        local ec = e.chars[ch]
        if ec then hit = hit + math.min(c, ec) end
    end
    local precision = hit / qn
    local recall = hit / e.n
    if precision + recall == 0 then return 0 end
    return clamp01(2 * precision * recall / (precision + recall))
end

-- 检索：返回按相关度降序的候选 { {id=, q=, score=, hit=bool}, ... }
--
-- ⚠ 去重必须发生在「打分之后、排序之前」，不能拿 seen 事先跳过条目：
--   同一主题有多个问法变体，它们共用 id。如果先到的那条分不高，
--   后面那条**完全一致**的问法就会被 seen 挡掉——
--   实测「你能做什么」就是这样被「你会些什么」挡住，精确匹配永远选不中。
local function match_query(text, maxN)
    maxN = maxN or CFG.MAX_CAND
    local qcnt, qn = match_chars(text)
    if qn == 0 then return {} end
    local scored = {}
    for i = 1, #MATCH_BANK do
        local e = MATCH_BANK[i]
        local s = match_score(qcnt, qn, e)
        if s >= MATCH_KEEP then
            scored[#scored + 1] = {
                id = e.id, q = e.q, score = s, initials = e.ini,
                exact = (e.q == text),
            }
        end
    end
    -- 先按分数排序，再按 id 去重（每个主题只留最高分的那条）
    table.sort(scored, function(a, b)
        if math.abs(a.score - b.score) > 0.0001 then return a.score > b.score end
        if a.exact ~= b.exact then return a.exact end
        return a.q < b.q
    end)
    local out, seen = {}, {}
    for i = 1, #scored do
        local c = scored[i]
        if not seen[c.id] then
            seen[c.id] = true
            out[#out + 1] = c
        end
    end
    local trimmed = {}
    for i = 1, math.min(maxN, #out) do trimmed[i] = out[i] end
    for i, c in ipairs(trimmed) do
        c.hit = (i == 1) and (c.score >= MATCH_MIN)
    end
    return trimmed
end
