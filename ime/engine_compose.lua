-- ============================================================================
-- 拼音引擎 · 输入成句（词级优先）
--
-- 为什么是词级：单字级拼音无法消歧。打 ming 时候选里既有「名」也有「命」，
-- 只按单字频次排会把「命」放前面；但「mingzi」作为词就唯一指向「名字」。
-- 所以刷新候选时先做词级匹配（最长 4 音节），匹配不到才退回单字级。
--
-- 单字级再叠一层上下文消歧：玩家刚定下的那个字，如果能和某候选字在语料里
-- 成词，就把它提前（靠 MOD.IME_BIGRAMS 这张搭配表）。
--
-- 状态：
--   raw        还没定字的拼音字母
--   committed  已经定下来的汉字
--   pool       当前候选（可能是词也可能是单字）
--   pool_span  选中一个候选会吃掉几个音节
--
-- 本文件由 build_speech.py 内联进 main.lua，不写 return / require。
-- ============================================================================

local IMEST = {
    raw = "",
    committed = "",
    segs = {},
    pool = {},
    pool_kind = "char",
    pool_span = 1,
    -- 候选池上限。UI 只显示前 10 个（数字键 1-0），但池子要留得更宽：
    -- 实测「失」在 shi 里排第 14，池子截到 12 就选不到它了。
    maxp = 48,
}

-- 词级匹配：从长到短试，最长 4 个音节。
-- 必须满足「词的拼音串 == 这几个音节拼起来的串」，这样才不会把
-- xian（一个音节）误当成 xi + an（两个音节）。
local function ime_word_match(segs)
    local table_words = MOD.IME_WORDS
    if table_words == nil then return nil, 0 end
    local n = #segs
    for span = math.min(4, n), 2, -1 do
        local key = table.concat(segs, "", 1, span)
        local words = table_words[key]
        if words and #words > 0 then
            return words, span
        end
    end
    return nil, 0
end

-- 上下文消歧：按「上一个字 + 候选字」在语料问法里的搭配分重排单字候选。
-- 两段式：先看「有没有搭配记录」，没有记录的一律排后面；都有记录的再比搭配分。
-- 为什么不用纯搭配分排序：搭配分整体很小（问法只有 126 条），
-- 如果直接拿分数当主键，会把单字表里本来很靠前的常用字压下去。
local function ime_context_order(base, prev_char)
    local bigrams = MOD.IME_BIGRAMS
    if prev_char == "" or bigrams == nil then return base end
    local rank_of = bigrams[prev_char]
    if rank_of == nil then return base end
    local scored = {}
    for i = 1, #base do
        local bonus = rank_of[base[i]]
        scored[#scored + 1] = {
            ch = base[i],
            known = (bonus ~= nil) and 1 or 0,
            bonus = bonus or 0,
            idx = i,
        }
    end
    table.sort(scored, function(a, b)
        if a.known ~= b.known then return a.known > b.known end
        if a.bonus ~= b.bonus then return a.bonus > b.bonus end
        return a.idx < b.idx
    end)
    local out = {}
    for i = 1, #scored do out[i] = scored[i].ch end
    return out
end

-- 重新切分并刷新候选。raw 每次变化后都要调用。
local function ime_refresh()
    local segs, _used = ime_segment(IMEST.raw)
    IMEST.segs = segs
    IMEST.pool = {}
    IMEST.pool_kind = "char"
    IMEST.pool_span = 1
    if #segs == 0 then return 0 end

    -- 1) 词级
    local words, span = ime_word_match(segs)
    if words then
        local pool = {}
        for i = 1, math.min(#words, IMEST.maxp) do pool[i] = words[i] end
        IMEST.pool = pool
        IMEST.pool_kind = "word"
        IMEST.pool_span = span
        return #pool
    end

    -- 2) 单字级 + 上下文消歧
    local base = ime_chars_of(segs[1])
    local prev = ""
    if #IMEST.committed > 0 then
        prev = utf8_last(IMEST.committed, 1)
    end
    base = ime_context_order(base, prev)
    local pool = {}
    for i = 1, math.min(#base, IMEST.maxp) do pool[i] = base[i] end
    IMEST.pool = pool
    return #pool
end

-- 拼音缓冲过长时只保留最近的部分（并返回丢掉了多少字符）
local function ime_trim(max_raw)
    local cut = 0
    if #IMEST.raw > max_raw then
        cut = #IMEST.raw - max_raw
        IMEST.raw = IMEST.raw:sub(cut + 1)
        ime_refresh()
    end
    return cut
end

-- 追加字母（只接受 a-z / A-Z）
local function ime_letter(ch)
    if ch == nil or #ch ~= 1 then return false end
    local b = ch:byte()
    local lower = (b >= 65 and b <= 90) and string.char(b + 32) or ch
    if not lower:match("^[a-z]$") then return false end
    IMEST.raw = IMEST.raw .. lower
    ime_trim(24)
    ime_refresh()
    return true
end

-- 退格：优先退未定字的字母；字母退完了再退已定的汉字
local function ime_backspace()
    if #IMEST.raw > 0 then
        IMEST.raw = IMEST.raw:sub(1, #IMEST.raw - 1)
        ime_refresh()
        return "raw"
    end
    if #IMEST.committed > 0 then
        IMEST.committed = utf8_sub(IMEST.committed, 1, utf8_len(IMEST.committed) - 1)
        ime_refresh()
        return "committed"
    end
    return nil
end

-- 选候选。idx 从 1 开始。
-- 词候选会吃掉 pool_span 个音节，单字候选吃一个。
local function ime_pick(idx)
    local item = IMEST.pool[idx]
    if item == nil then return nil end
    local span = IMEST.pool_span
    if span < 1 then span = 1 end
    -- 从 raw 头部去掉这些音节的字母
    local cut = 0
    for i = 1, span do
        local syl = IMEST.segs[i]
        if syl == nil then break end
        cut = cut + #syl
    end
    IMEST.raw = IMEST.raw:sub(cut + 1)
    IMEST.committed = IMEST.committed .. item
    ime_refresh()
    return item
end

-- 取走全部已定文字（提交给 AI 用），并清空状态
local function ime_take()
    local text = IMEST.committed
    IMEST.committed = ""
    IMEST.raw = ""
    IMEST.segs = {}
    IMEST.pool = {}
    IMEST.pool_kind = "char"
    IMEST.pool_span = 1
    return text
end

local function ime_clear()
    IMEST.committed = ""
    IMEST.raw = ""
    IMEST.segs = {}
    IMEST.pool = {}
    IMEST.pool_kind = "char"
    IMEST.pool_span = 1
end

-- 分词返回：已定汉字、未定拼音（UI 分两截显示）
local function ime_parts()
    return IMEST.committed, IMEST.raw
end

-- 「已定汉字 + 无歧义的首音节字」= 拿去匹配问法的字串。
-- 这样玩家打完 nihaoma 不选字也能直接发送（只要这些音节的首候选是唯一的）。
local function ime_key()
    local out = IMEST.committed
    if IMEST.segs[1] and IMEST.pool_kind == "char" then
        local chars = ime_chars_of(IMEST.segs[1])
        if #chars == 1 then out = out .. chars[1] end
    elseif IMEST.segs[1] and IMEST.pool_kind == "word" and #IMEST.pool == 1 then
        out = out .. IMEST.pool[1]
    end
    return out
end

local function ime_pool()
    return IMEST.pool
end

-- 当前候选是词还是单字（UI 提示用）
local function ime_pool_kind()
    return IMEST.pool_kind
end

local function ime_rows()
    return #IMEST.segs
end

local function ime_busy()
    return #IMEST.raw > 0 or #IMEST.pool > 0
end

