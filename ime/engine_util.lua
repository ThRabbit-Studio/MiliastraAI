-- ============================================================================
-- 拼音引擎 · 汉字识别
--
-- 为什么不直接用 Lua 的字符类 [一-鿿]：
--   字符类是否按「字符」还是按「字节」解释，取决于 Lua 版本与 locale。
--   本项目的离线验证台用的是 lupa 内嵌 Lua 5.5 + 默认 locale，实测它按**字节**
--   处理，会把一个汉字切成两三个假字符，导致匹配打分完全错乱。
--   真机是 Lua 5.3，行为可能不同——这种「取决于环境」的东西不能当地基。
-- 所以这里显式解码 UTF-8 码点再判断范围，行为与语言环境无关。
--
-- 本文件由 build_speech.py 内联进 main.lua，不写 return / require。
-- ============================================================================

-- 逐个返回 UTF-8 字符及其码点：迭代器给出 (字符, 码点)
local function utf8_iter(s)
    local i, n = 1, #s
    return function()
        if i > n then return nil end
        local b = s:byte(i)
        local len, cp
        if b < 0x80 then
            len, cp = 1, b
        elseif b < 0xE0 then
            len = 2
            cp = (b - 0xC0) * 0x40 + ((s:byte(i + 1) or 0x80) - 0x80)
        elseif b < 0xF0 then
            len = 3
            cp = (b - 0xE0) * 0x1000
                + ((s:byte(i + 1) or 0x80) - 0x80) * 0x40
                + ((s:byte(i + 2) or 0x80) - 0x80)
        else
            len = 4
            cp = (b - 0xF0) * 0x40000
                + ((s:byte(i + 1) or 0x80) - 0x80) * 0x1000
                + ((s:byte(i + 2) or 0x80) - 0x80) * 0x40
                + ((s:byte(i + 3) or 0x80) - 0x80)
        end
        local ch = s:sub(i, i + len - 1)
        i = i + len
        return ch, cp
    end
end

-- 只保留汉字（CJK 统一表意文字基本区），返回「字 -> 出现次数」与总字数
local function han_counts(s)
    local cnt, total = {}, 0
    for ch, cp in utf8_iter(s) do
        if cp >= 0x4E00 and cp <= 0x9FFF then
            cnt[ch] = (cnt[ch] or 0) + 1
            total = total + 1
        end
    end
    return cnt, total
end

-- 只要汉字列表（按出现顺序，含重复）
local function han_list(s)
    local out = {}
    for ch, cp in utf8_iter(s) do
        if cp >= 0x4E00 and cp <= 0x9FFF then out[#out + 1] = ch end
    end
    return out
end
