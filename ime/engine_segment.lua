-- ============================================================================
-- 拼音引擎 · 连续拼音切分
--
-- 玩家打的是连续字母串（"nihao"），要先切成音节（ni + hao）才能查字。
-- 切分策略是**贪心优先匹配**，不是「最优切分」：优先切出长音节，
-- 这样 xian 会切成一个音节（先/现/线…），而不是 xi + an。
-- 这与主流输入法的手感一致，也让同一串字母的切分结果稳定可预期。
--
-- 本文件由 build_speech.py 内联进 main.lua，因此不写 return、不写 require。
-- ============================================================================

-- 引擎自有的数据引用（由 §1 数据段提供）
local IME = {
    syllables = MOD.IME_SYLLABLES or {},
    chars = MOD.IME_CHARS or {},
    -- 音节集合，加速判断
    syl_set = {},
}
for i = 1, #IME.syllables do
    IME.syl_set[IME.syllables[i]] = true
end

-- 某个字符串是不是合法音节
local function ime_is_syllable(s)
    return s ~= nil and s ~= "" and IME.syl_set[s] == true
end

-- 取候选字列表（已按常用度排序）。没有该音节则返回空表。
local function ime_chars_of(syl)
    if syl == nil or syl == "" then return {} end
    return IME.chars[syl] or {}
end

-- 连续拼音 -> 音节数组。返回 (音节表, 已切长度)。
-- 未匹配到音节的尾巴不会出现在结果里，留在 pending 中让玩家继续打。
local function ime_segment(s)
    local out = {}
    local i, n = 1, #s
    while i <= n do
        -- 贪心：先看「当前字符 + 分隔符 + 剩余」里最长的合法音节
        local matched = nil
        local maxLen = math.min(6, n - i + 1)   -- 最长音节 6 个字母（chuang）
        for len = maxLen, 1, -1 do
            local cand = s:sub(i, i + len - 1)
            if ime_is_syllable(cand) then
                matched = cand
                i = i + len
                break
            end
        end
        if not matched then
            break
        end
        out[#out + 1] = matched
    end
    return out, i - 1
end

-- 诊断用：把切分结果拼成 "ni|hao" 便于日志排查
local function ime_segment_str(segs)
    return table.concat(segs, "|")
end
