#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成网页试用（docs/demo.html，自包含单文件）。

为什么需要：
  真机要装原神、建关卡、填索引；验证一次成本很高。而拼音引擎的绝大部分逻辑
  （切分、词级匹配、上下文消歧、语义匹配）与宿主 API 无关，完全可以在浏览器里
  重跑一遍，让使用者在几秒内感受到打字手感。

怎么保证「网页里试到的」和「真机上跑的」是同一个东西：
  1. 数据全部从构建产物 ime/ime_data.lua 与语料里读出，不另写一份；
  2. JS 版引擎逐条对齐 ime/*.lua 的算法；
  3. 页面加载后**自动跑一遍自检**：把语料的每条问法在 JS 里打一遍，
     统计可打率/零按键率，并与 Lua 侧的已知结果比对。不一致就在页面上标红。

用法：
  python verify/make_demo.py
  python verify/make_demo.py --serve     # 生成后起本地服务并打开浏览器
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
OUT = os.path.join(DOCS, "demo.html")
LEX = os.path.join(ROOT, "ime", "ime_data.lua")
CORPUS = os.path.join(ROOT, "data", "corpus_plain.json")

# Lua 侧实测结果（verify/t_ime.py 的输出），网页自检会拿来对账
LUA_TOTAL = 126
LUA_TYPEABLE = 126
LUA_ZERO_PICK = 77


def read_lua_table(src: str, marker: str, stop: str) -> tuple[list[str], dict[str, list[str]]]:
    """从 Lua 产物里读回「一个数组 + 一张 串->串数组 的表」。"""
    head = src.split(marker, 1)[1].split(stop, 1)[0]
    arr = re.findall(r'"([a-z]+)"', head.split("= {", 1)[0]) if "= {" in head else []
    # 数组段（音节表）单独取
    if marker == "MOD.IME_SYLLABLES = ":
        syllables = re.findall(r'"([a-z]+)"', head)
        return syllables, {}
    table: dict[str, list[str]] = {}
    for m in re.finditer(r'\["([a-z]+)"\]\s*=\s*\{([^}]*)\}', head):
        table[m.group(1)] = re.findall(r'"([^"]+)"', m.group(2))
    return arr, table


def build_payload() -> dict:
    with open(LEX, encoding="utf-8") as fh:
        src = fh.read()

    syllables, _ = read_lua_table(src, "MOD.IME_SYLLABLES = ", "-- 音节 ->")

    chars_block = src.split("MOD.IME_CHARS = {", 1)[1].split("-- 拼音串 ->", 1)[0]
    chars: dict[str, list[str]] = {}
    for m in re.finditer(r'\["([a-z]+)"\]\s*=\s*\{([^}]*)\}', chars_block):
        chars[m.group(1)] = re.findall(r'"([^"]+)"', m.group(2))

    words_block = src.split("MOD.IME_WORDS = {", 1)[1].split("-- 上下文搭配", 1)[0]
    words: dict[str, list[str]] = {}
    for m in re.finditer(r'\["([a-z]+)"\]\s*=\s*\{([^}]*)\}', words_block):
        words[m.group(1)] = re.findall(r'"([^"]+)"', m.group(2))

    big_block = src.split("MOD.IME_BIGRAMS = {", 1)[1]
    bigrams: dict[str, dict[str, int]] = {}
    for m in re.finditer(r'\["([^"]+)"\]\s*=\s*\{([^}]*)\}', big_block):
        prev, body = m.group(1), m.group(2)
        pairs = {}
        for nxt, n in re.findall(r'\["([^"]+)"\]\s*=\s*(\d+)', body):
            pairs[nxt] = int(n)
        if pairs:
            bigrams[prev] = pairs

    with open(CORPUS, encoding="utf-8") as fh:
        corpus = json.load(fh)

    bank = []
    for q in corpus["questions"]:
        for variant in q["q"]:
            bank.append({"id": q["id"], "q": variant, "topic": q["topic"]})

    return {
        "syllables": syllables,
        "chars": chars,
        "words": words,
        "bigrams": bigrams,
        "persona": corpus["persona"],
        "answers": {q["id"]: q["a"] for q in corpus["questions"]},
        "topics": {q["id"]: {"topic": q["topic"], "cat": q["cat"],
                             "q": q["q"]} for q in corpus["questions"]},
        "bank": bank,
        "expect": {"total": LUA_TOTAL, "typeable": LUA_TYPEABLE, "zeroPick": LUA_ZERO_PICK},
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>千星奇域内置 AI · 拼音输入法试用</title>
<style>
  :root{--bg:#0e1116;--panel:#161b22;--line:#26303c;--fg:#e6edf3;--dim:#8b949e;
        --accent:#3fb0ac;--accent2:#f0883e;--ok:#3fb950;--bad:#f85149}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
       font:14px/1.7 "Microsoft YaHei","PingFang SC",system-ui,sans-serif}
  header{padding:18px 24px;border-bottom:1px solid var(--line)}
  h1{margin:0 0 4px;font-size:18px}
  h2{font-size:15px;margin:26px 0 10px;color:var(--accent)}
  .sub{color:var(--dim);font-size:12px}
  main{padding:18px 24px 70px;max-width:1180px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}
  .stat{display:inline-block;background:#1a1f29;border:1px solid var(--line);
        border-radius:8px;padding:6px 12px;margin:0 8px 8px 0}
  .stat b{color:var(--accent);font-size:17px;margin-right:6px}
  .stat span{color:var(--dim);font-size:12px}
  /* 屏幕键盘 */
  .kb{display:flex;flex-direction:column;gap:6px;align-items:center;margin:14px 0}
  .kb .row{display:flex;gap:6px}
  .key{background:#21262d;border:1px solid var(--line);color:var(--fg);
       min-width:42px;padding:9px 0;border-radius:6px;cursor:pointer;font-size:13px;
       font-family:ui-monospace,Consolas,monospace;text-align:center;user-select:none}
  .key:hover{border-color:var(--accent)}
  .key.fn{min-width:74px;font-size:12px;color:var(--dim)}
  .key.send{background:#8a4b1e;border-color:var(--accent2);color:#fff;min-width:64px}
  .key.num{min-width:38px;background:#1d232b}
  /* 输入显示 */
  .inputbar{background:#0d1117;border:1px solid var(--line);border-radius:8px;
            padding:12px 14px;font-size:19px;min-height:56px;
            font-family:ui-monospace,Consolas,monospace;letter-spacing:1px}
  .inputbar .committed{color:var(--fg)}
  .inputbar .raw{color:var(--accent2);border-bottom:2px solid var(--accent2)}
  .inputbar .caret{color:var(--accent)}
  .inputbar .hint{color:var(--dim);font-size:13px;letter-spacing:0;font-family:inherit}
  /* 候选 */
  .cands{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}
  .cand{background:#1a1f29;border:1px solid var(--line);border-radius:6px;
        padding:6px 11px;cursor:pointer;font-size:15px;min-width:52px;text-align:center}
  .cand:hover,.cand.best{border-color:var(--accent);background:#22414a}
  .cand .n{color:var(--accent2);font-size:11px;margin-right:5px}
  .cand .w{border:1px dashed var(--accent2);border-radius:3px;padding:0 3px}
  .log{max-height:230px;overflow:auto;font-family:ui-monospace,Consolas,monospace;
       font-size:12px;color:var(--dim)}
  .log .u{color:var(--accent2)}
  .log .a{color:var(--fg)}
  .log .m{color:#6e7681}
  table{border-collapse:collapse;width:100%;font-size:12px}
  th,td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left}
  th{color:var(--dim);font-weight:400}
  .tag{display:inline-block;padding:1px 7px;border-radius:4px;font-size:11px}
  .tag.ok{background:rgba(63,185,80,.15);color:var(--ok)}
  .tag.bad{background:rgba(248,81,73,.15);color:var(--bad)}
  details{margin:8px 0}
  summary{cursor:pointer;color:var(--accent)}
  .mono{font-family:ui-monospace,Consolas,monospace;color:var(--dim);font-size:12px}
  .flow{font-family:ui-monospace,Consolas,monospace;font-size:12px;color:var(--dim);
        white-space:pre;line-height:1.6}
</style>
</head>
<body>
<header>
  <h1>千星奇域内置 AI · 拼音输入法试用</h1>
  <div class="sub">
    数据取自构建产物 <code>ime/ime_data.lua</code> 与 <code>data/corpus_plain.json</code>（__GEN__）　·　
    本页完全离线，算法与 <code>ime/*.lua</code> 逐条对齐
  </div>
</header>
<main>
  <div id="selftest" class="card" style="margin-bottom:16px"></div>

  <h2>一、打字（点键盘，或直接用物理键盘敲字母/数字）</h2>
  <div class="card">
    <div class="inputbar" id="inputbar"></div>
    <div class="cands" id="cands"></div>
    <div class="mono" id="tipline"></div>
    <div class="kb" id="kb"></div>
    <div class="flow" id="flow"></div>
  </div>

  <h2>二、对话</h2>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
    <div class="card">
      <div class="mono">对白（按「发送」或物理回车）</div>
      <div class="log" id="log" style="margin-top:8px"></div>
      <div style="margin-top:10px">
        <button class="key fn" onclick="doSend()">发送</button>
        <button class="key fn" onclick="doClear()">清空输入</button>
        <button class="key fn" onclick="resetChat()">清空对话</button>
      </div>
    </div>
    <div class="card">
      <div class="mono">语义匹配排名（当前已定文字）</div>
      <table id="rank"><thead><tr>
        <th>#</th><th>问法</th><th>相关度</th><th>判定</th>
      </tr></thead><tbody></tbody></table>
      <details>
        <summary>匹配规则</summary>
        <div class="mono" style="white-space:pre-wrap;margin-top:6px">相关度 = 字面重合的 F1（按多重集计）
  precision = 打出的字里有多少在问法里
  recall    = 问法里有多少字被打到
候选门槛 0.40，命中门槛 0.60 —— 低于门槛直接回「我不知道」，不硬凑答案</div>
      </details>
    </div>
  </div>

  <h2>三、数据规模</h2>
  <div class="card" id="stats"></div>

  <h2>四、语料（默认折叠）</h2>
  <details class="card">
    <summary>展开看 30 个主题 / __NVAR__ 种问法 / __NANS__ 条答句</summary>
    <div id="corpus" style="margin-top:12px"></div>
  </details>
</main>

<script>
const D = __PAYLOAD__;

/* ============ 引擎：与 ime/*.lua 逐条对齐 ============ */

// 汉字判定：显式按码点，不用字符类（字符类是否按字节解释取决于环境）
const isHan = (ch) => { const c = ch.codePointAt(0); return c >= 0x4E00 && c <= 0x9FFF; };
const hanList = (s) => [...s].filter(isHan);
const hanCount = (s) => { const m = new Map(); for (const ch of s) if (isHan(ch)) m.set(ch, (m.get(ch)||0)+1); return m; };

const SYL = new Set(D.syllables);
const MAX_WORD_SPAN = 4;

// engine_segment：贪心最长匹配
function segment(raw) {
  const out = []; let i = 0;
  while (i < raw.length) {
    let matched = null;
    for (let len = Math.min(6, raw.length - i); len >= 1; len--) {
      const cand = raw.slice(i, i + len);
      if (SYL.has(cand)) { matched = cand; i += len; break; }
    }
    if (!matched) break;
    out.push(matched);
  }
  return out;
}

// engine_compose：词级优先（最长 4 音节），否则单字级 + 上下文消歧
function wordMatch(segs) {
  for (let span = Math.min(MAX_WORD_SPAN, segs.length); span >= 2; span--) {
    const key = segs.slice(0, span).join('');
    const ws = D.words[key];
    if (ws && ws.length) return { words: ws, span };
  }
  return null;
}
function contextOrder(base, prev) {
  const p = D.bigrams[prev];
  if (!prev || !p) return base.slice();
  return base.map((ch, i) => ({ ch, known: p[ch] !== undefined ? 1 : 0,
                                bonus: p[ch] || 0, i }))
             .sort((a, b) => (b.known - a.known) || (b.bonus - a.bonus) || (a.i - b.i))
             .map(o => o.ch);
}
function refresh(st) {
  st.segs = segment(st.raw);
  st.pool = []; st.poolKind = 'char'; st.poolSpan = 1;
  if (!st.segs.length) return;
  const wm = wordMatch(st.segs);
  if (wm) { st.pool = wm.words.slice(0, 48); st.poolKind = 'word'; st.poolSpan = wm.span; return; }
  const base = D.chars[st.segs[0]] || [];
  const prev = st.committed ? [...st.committed].pop() : '';
  st.pool = contextOrder(base, prev).slice(0, 48);
}
function pick(st, idx) {
  const item = st.pool[idx]; if (item === undefined) return null;
  const span = Math.max(1, st.poolSpan);
  let cut = 0;
  for (let i = 0; i < span; i++) { if (!st.segs[i]) break; cut += st.segs[i].length; }
  st.raw = st.raw.slice(cut);
  st.committed += item;
  refresh(st);
  return item;
}

// engine_match：字面重合 F1，先打分排序再按主题去重
const MATCH_KEEP = 0.40, MATCH_MIN = 0.60;
const BANK = D.bank.map(r => {
  const cnt = hanCount(r.q);
  return { id: r.id, q: r.q, topic: r.topic, chars: cnt, n: cnt.size };
});
function matchQuery(text) {
  const qcnt = hanCount(text), qn = [...qcnt.values()].reduce((a,b)=>a+b,0);
  if (!qn) return [];
  const scored = [];
  for (const e of BANK) {
    let hit = 0;
    for (const [ch, c] of qcnt) { const ec = e.chars.get(ch); if (ec) hit += Math.min(c, ec); }
    const prec = hit / qn, rec = hit / e.n;
    const s = (prec + rec) === 0 ? 0 : 2 * prec * rec / (prec + rec);
    if (s >= MATCH_KEEP) scored.push({ ...e, score: s, exact: e.q === text });
  }
  scored.sort((a,b) => (Math.abs(a.score-b.score) > 1e-4 ? b.score-a.score
                        : (a.exact !== b.exact ? (a.exact ? -1 : 1)
                        : (a.q < b.q ? -1 : 1))));
  const out = [], seen = new Set();
  for (const c of scored) { if (!seen.has(c.id)) { seen.add(c.id); out.push(c); } }
  return out.slice(0, 10).map((c, i) => ({ ...c, hit: i === 0 && c.score >= MATCH_MIN }));
}

// 答句生成：与 compose() 一致（确定性 LCG + 首句轮换）
function mixInt(x){x=Math.abs(Math.floor(x))>>>0;x=(x^0x9E3779B1)>>>0;x=Math.imul(x,0x85EBCA6B)>>>0;
  x=(x^(x>>>13))>>>0;x=Math.imul(x,0xC2B2AE35)>>>0;return (x^(x>>>16))>>>0;}
function lcg(seed){let s=mixInt(seed)%2147483647;if(s<=0)s+=2147483646;
  return ()=>{s=(s*16807)%2147483647;return (s-1)/2147483646;};}
const CLAUSE_END = new Set(['。','！','？','；','…','.','!','?',';','　']);
function splitClauses(t){const out=[];let buf='';for(const ch of t){buf+=ch;if(CLAUSE_END.has(ch)){out.push(buf);buf='';}}
  if(buf)out.push(buf);return out;}
function compose(seed, id, charCount){
  const vars = D.answers[id]; if(!vars||!vars.length) return null;
  const rnd = lcg(seed);
  const variant = vars[Math.min(vars.length-1, Math.floor(rnd()*vars.length))];
  const heads = []; for(const v of vars){const h=splitClauses(v)[0]; if(h&&!heads.includes(h))heads.push(h);}
  const base = splitClauses(variant);
  let head = base[0];
  if(heads.length>1){let i=Math.floor(rnd()*heads.length); if(heads[i]===head)i=(i+1)%heads.length; head=heads[i];}
  const parts=[]; const quirk=Math.floor(rnd()*3);
  const confirm=D.persona.confirm||[];
  if(confirm.length&&charCount>0&&charCount<=3&&quirk===0) parts.push(confirm[Math.floor(rnd()*confirm.length)]);
  parts.push(head); for(let i=1;i<base.length;i++) parts.push(base[i]);
  return parts.join('');
}

/* ============ 自检：用 JS 引擎把语料每条问法打一遍 ============ */
function selfTest(){
  let typeable=0, zeroPick=0; const fails=[];
  for(const row of D.bank){
    const st={raw:'',committed:'',segs:[],pool:[],poolKind:'char',poolSpan:1};
    let picks=0, ok=true;
    for(const target of hanList(row.q)){
      // 找出该字的拼音：从 chars 反查
      let syl=null;
      for(const [s,list] of Object.entries(D.chars)) if(list.includes(target)){ syl=s; break; }
      if(!syl){ ok=false; break; }
      st.raw += syl; refresh(st);
      const idx = st.pool.findIndex(c => c && c[0]===target);
      if(idx<0){ ok=false; break; }
      picks += idx; pick(st, idx);
    }
    if(picks===0) zeroPick++;
    if(ok && st.committed===row.q) typeable++; else if(fails.length<6) fails.push([row.q, st.committed]);
  }
  return {total:D.bank.length, typeable, zeroPick, fails};
}

/* ============ 界面 ============ */
const $ = id => document.getElementById(id);
const st = {raw:'',committed:'',segs:[],pool:[],poolKind:'char',poolSpan:1};
let round = 0, chat = [];

function renderInput(){
  const bar = $('inputbar');
  if(!st.committed && !st.raw){
    bar.innerHTML = '<span class="hint">打拼音即可，例如 <b>nihao</b> → 你好　　1-0 选字 · 退格删除 · 回车发送</span>';
  } else {
    bar.innerHTML = '<span class="committed">'+esc(st.committed)+'</span>' +
      (st.raw ? '<span class="raw">'+esc(st.raw)+'</span>' : '') +
      '<span class="caret">▕</span>';
  }
  const box = $('cands'); box.innerHTML = '';
  st.pool.slice(0,10).forEach((c,i) => {
    const d = document.createElement('div');
    d.className = 'cand' + (i===0?' best':'');
    const isWord = st.poolKind==='word';
    d.innerHTML = '<span class="n">'+(i+1)%10+'</span>' +
      (isWord ? '<span class="w">'+esc(c)+'</span>' : esc(c));
    d.onclick = () => { pick(st,i); onChanged(); };
    box.appendChild(d);
  });
  const tip = st.poolKind==='word'
    ? '词级匹配：一次定 '+st.poolSpan+' 个字'
    : (st.pool.length ? '单字级：'+st.pool.length+' 个候选' : '');
  $('tipline').textContent = tip;
  $('flow').textContent =
    '玩家输入   ' + (st.raw || '—') + '\n' +
    '切分       ' + (st.segs.length ? st.segs.join(' | ') : '—') + '\n' +
    '候选       ' + (st.pool.length ? st.pool.slice(0,6).join('  ') : '—') + '\n' +
    '已定       ' + (st.committed || '—');
}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}

function renderRank(){
  const key = st.committed;
  const rows = key ? matchQuery(key) : [];
  const tb = $('rank').querySelector('tbody'); tb.innerHTML = '';
  if(!rows.length){
    tb.innerHTML = '<tr><td colspan="4" class="mono">'+(key?'没有达到门槛的候选':'（先打出几个字）')+'</td></tr>';
    return;
  }
  rows.forEach((r,i)=>{
    const tr=document.createElement('tr');
    tr.innerHTML='<td>'+(i+1)+'</td><td>'+esc(r.q)+'</td><td>'+r.score.toFixed(3)+'</td>'+
      '<td>'+(r.hit?'<span class="tag ok">命中</span>':'<span class="tag bad">候选</span>')+'</td>';
    tb.appendChild(tr);
  });
}
function renderLog(){
  $('log').innerHTML = chat.map(l =>
    l.role==='u' ? '<div><span class="u">你 ›</span> '+esc(l.text)+'</div>'
    : l.role==='m' ? '<div class="m">'+esc(l.text)+'</div>'
    : '<div><span class="a">AI ›</span> '+esc(l.text)+'</div>').join('');
  $('log').scrollTop = $('log').scrollHeight;
}
function onChanged(){ renderInput(); renderRank(); }

function doSend(){
  const key = st.committed;
  if(!key){ chat.push({role:'m',text:'（还没打出内容）'}); renderLog(); return; }
  round++;
  chat.push({role:'u',text:key});
  const rows = matchQuery(key);
  const chosen = rows[0] && rows[0].hit ? rows[0] : null;
  let text;
  if(chosen){ text = compose(round, chosen.id, [...key].length) || '……'; }
  else { const pool=D.persona.unknown; text = pool[(round-1)%pool.length]; }
  chat.push({role:'m',text:(chosen?('命中「'+chosen.q+'」 '):'未命中（答不了） ')+'相关度 '+(rows[0]?rows[0].score.toFixed(3):'—')});
  chat.push({role:'a',text});
  st.committed=''; st.raw=''; refresh(st);
  onChanged(); renderLog();
}
function doClear(){ st.committed=''; st.raw=''; refresh(st); onChanged(); }
function resetChat(){ chat=[]; renderLog(); }

function typeChar(ch){
  const b = ch.toUpperCase();
  if(b>='A' && b<='Z'){ if(st.raw.length<24) st.raw += ch.toLowerCase(); refresh(st); onChanged(); }
  else if(ch>='0' && ch<='9'){ const i=(ch==='0')?10:parseInt(ch); if(st.pool[i-1]!==undefined){ pick(st,i-1); onChanged(); } }
}
function doBackspace(){
  if(st.raw.length){ st.raw = st.raw.slice(0,-1); refresh(st); }
  else if(st.committed.length){ const a=[...st.committed]; a.pop(); st.committed=a.join(''); refresh(st); }
  onChanged();
}

function renderKeyboards(){
  const rows=[['QWERTYUIOP'],['ASDFGHJKL'],['ZXCVBNM']];
  const kb=$('kb'); kb.innerHTML='';
  rows.forEach(([r],ri)=>{
    const d=document.createElement('div'); d.className='row';
    if(ri===1) d.innerHTML='<div class="key fn" style="visibility:hidden"></div>';
    for(const ch of r){ const k=document.createElement('div'); k.className='key'; k.textContent=ch;
      k.onclick=()=>typeChar(ch); d.appendChild(k); }
    if(ri===2){
      const bs=document.createElement('div'); bs.className='key fn'; bs.textContent='⌫'; bs.onclick=doBackspace; d.appendChild(bs);
      const sd=document.createElement('div'); sd.className='key send'; sd.textContent='发送'; sd.onclick=doSend; d.appendChild(sd);
    }
    kb.appendChild(d);
  });
  const d=document.createElement('div'); d.className='row';
  for(const n of '1234567890'){ const k=document.createElement('div'); k.className='key num';
    k.textContent=n; k.onclick=()=>typeChar(n); d.appendChild(k); }
  kb.appendChild(d);
}
function renderStats(){
  const nChars=Object.values(D.chars).reduce((a,b)=>a+b.length,0);
  const nWords=Object.values(D.words).reduce((a,b)=>a+b.length,0);
  const nAns=Object.values(D.answers).reduce((a,b)=>a+b.length,0);
  const s=[['音节表',D.syllables.length],['有字音节',Object.keys(D.chars).length],
           ['汉字',nChars],['词条',nWords],['主题',Object.keys(D.answers).length],
           ['问法',D.bank.length],['答句变体',nAns]];
  $('stats').innerHTML = s.map(([k,v])=>'<div class="stat"><b>'+v+'</b><span>'+k+'</span></div>').join('');
}
function renderCorpus(){
  $('corpus').innerHTML = Object.entries(D.topics).map(([id,t])=>
    '<div style="margin-bottom:10px"><b>'+esc(t.topic)+'</b> <span class="mono">'+esc(t.cat)+' · '+id+'</span>'+
    '<div class="mono" style="margin-top:4px">问法：'+t.q.map(esc).join(' / ')+'</div>'+
    '<div style="margin-top:4px">'+D.answers[id].map(a=>'· '+esc(a)).join('<br>')+'</div></div>').join('');
}
function renderSelfTest(){
  const r = selfTest();
  const e = D.expect;
  const okType = r.typeable >= e.typeable;
  const okZero = Math.abs(r.zeroPick - e.zeroPick) <= 2;
  const cls = (okType && okZero) ? 'ok' : 'bad';
  let html = '<div class="mono">网页自检（把语料每条问法在 JS 引擎里打一遍，与 Lua 侧结果对账）</div>' +
    '<div style="margin-top:8px">' +
    '<div class="stat"><b>'+r.typeable+'/'+r.total+'</b><span>可打出的问法</span></div>' +
    '<div class="stat"><b>'+r.zeroPick+'</b><span>零按键问法</span></div>' +
    '<div class="stat"><b>'+(r.zeroPick/r.total*100).toFixed(0)+'%</b><span>不用挑字</span></div>' +
    '<div class="stat"><b>'+r.total+'</b><span>Lua 侧问法数</span></div>' +
    '</div>' +
    '<div style="margin-top:8px">JS 结果与 Lua 侧（'+e.typeable+'/'+e.total+' 可打，'+e.zeroPick+' 零按键）' +
    ' <span class="tag '+cls+'">'+(cls==='ok'?'一致':'有偏差')+'</span></div>';
  if(r.fails.length){
    html += '<details><summary>打不出来的例子</summary><div class="mono">' +
      r.fails.map(([w,g])=>'期望 '+esc(w)+'　实际 '+esc(g||'（卡住）')).join('<br>') + '</div></details>';
  }
  $('selftest').innerHTML = html;
}

/* 物理键盘 */
document.addEventListener('keydown', e => {
  if(e.ctrlKey||e.metaKey||e.altKey) return;
  if(e.key==='Backspace'){ e.preventDefault(); doBackspace(); return; }
  if(e.key==='Enter'){ e.preventDefault(); doSend(); return; }
  if(e.key==='Escape'){ doClear(); return; }
  if(/^[a-zA-Z]$/.test(e.key)){ e.preventDefault(); typeChar(e.key); return; }
  if(/^[0-9]$/.test(e.key)){ e.preventDefault(); typeChar(e.key); }
});

refresh(st);
renderKeyboards(); renderInput(); renderRank(); renderLog();
renderStats(); renderCorpus(); renderSelfTest();
</script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--port", type=int, default=8788)
    args = ap.parse_args()

    payload = build_payload()
    n_var = len(payload["bank"])
    n_ans = sum(len(v) for v in payload["answers"].values())
    html = (HTML
            .replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            .replace("__GEN__", payload["generatedAt"])
            .replace("__NVAR__", str(n_var))
            .replace("__NANS__", str(n_ans)))

    os.makedirs(DOCS, exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(html)
    print(f"[OK] 已生成 {os.path.relpath(OUT, ROOT)}（{os.path.getsize(OUT):,} 字节）")
    print(f"     字库 {len(payload['syllables'])} 音节 / "
          f"{sum(len(v) for v in payload['chars'].values())} 字 / "
          f"{sum(len(v) for v in payload['words'].values())} 词")
    print(f"     用浏览器打开：file:///{OUT.replace(os.sep, '/')}")

    if args.serve:
        import functools
        import http.server
        import socketserver
        import threading
        import webbrowser

        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=DOCS)
        with socketserver.TCPServer(("127.0.0.1", args.port), handler) as httpd:
            url = f"http://127.0.0.1:{args.port}/demo.html"
            print(f"[OK] 本地服务：{url}（Ctrl+C 结束）")
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("\n[i] 已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())
