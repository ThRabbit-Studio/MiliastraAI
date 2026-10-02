#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线 Lupa 沙箱：模拟千星客户端的 game / script / 控件 API，用来加载真实 main.lua。

为什么需要：
  本机没有原神。但脚本绝大部分是纯逻辑（拼音引擎、匹配、答句生成），
  只要把宿主 API 模拟出来，就能用真实的 Lua 解释器跑完整流程。
  真机与模拟的差别集中在 §6 UI 运行时那几个 game.* 调用，
  那部分由 verify/check_api_allowlist.py 单独兜住。

模拟范围严格按 Lua客户端控件API文档.md 的签名，不额外造 API：
  game.GetClientUIRoots / GetUICanvasSize / InstantiateClientUIControl / DestroyClientUIControl
  control:SetPivot/SetAnchorMin/SetAnchorMax/SetSizeDelta/SetAnchoredPosition/SetActive/SetVisible
  control:AddKeyEventListener/RemoveKeyEventListener/SetImage
  control.alive/.name/.text/.fontSize/.imageColor/.horizontalAlignment ...
  Color.FromRGBA / Enum.* / script:EnableUpdate / print

用法（被 t_ime.py 等引用）：
    from lua_env import Fail, MockGame, build_env, check, load_script, lua_list
"""
from __future__ import annotations

import os

from lupa import LuaRuntime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MAIN_LUA = os.path.join(ROOT, "out", "main.lua")

# 测试注入的 Lua 字符串转换函数（见 set_lua_str）
LUA_STR = None


class Fail(Exception):
    """断言失败。用独立异常类型，避免和 lupa 的 LuaError 混在一起。"""


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise Fail(msg)


def lua_list(tbl) -> list:
    """把 Lua 序列取成 Python 列表。

    坑：直接 list(lua_table) 或迭代 lua_table 拿到的是**键**（'1','2','3'），
    因为 lupa 对 _LuaTable 的迭代产出键。必须按数字下标取值。
    """
    out, i = [], 1
    while True:
        v = tbl[i]
        if v is None:
            return out
        out.append(v)
        i += 1


def lua_str(lua: LuaRuntime, s: str) -> str:
    """Python 字符串 -> 真正的 Lua 字符串。lupa 直接传 str 在 Lua 里不是 string 类型。"""
    return lua.eval("function(s) return tostring(s) end")(s)


class MockControl:
    """按文档字段语义实现的控件替身。"""

    def __init__(self, prefab_index, parent, cid, factory):
        self._f = factory
        self.alive = True
        self.id = cid
        self.prefab_index = prefab_index
        self.name = ""
        self.parent = parent
        self.children = []
        self.text = ""
        self.font_size = 0
        # main.lua 里用 c.fontSize 赋值（文档字段名是驼峰），模拟也要接住
        self.fontSize = 0
        self.anchored = (0.0, 0.0)
        self.size = (0.0, 0.0)
        self.pivot = (0.5, 0.5)
        self.anchor_min = (0.5, 0.5)
        self.anchor_max = (0.5, 0.5)
        self.image_id = None
        self.image_source = None
        self.image_color = None
        self.active = True
        self.visible = True
        self.horizontal_alignment = None
        self.vertical_alignment = None
        self.enable_outline = False
        self.outline_color = None
        self.listeners: dict[str, list] = {}
        if parent is not None:
            parent.children.append(self)

    # --- 文档 §13(3) 布局与变换 ---
    def SetPivot(self, x, y):
        self.pivot = (x, y)

    def SetAnchorMin(self, x, y):
        self.anchor_min = (x, y)

    def SetAnchorMax(self, x, y):
        self.anchor_max = (x, y)

    def SetSizeDelta(self, x, y):
        self.size = (x, y)

    def SetAnchoredPosition(self, x, y):
        self.anchored = (x, y)

    def GetAnchoredPosition(self):
        return self.anchored

    def GetSizeDelta(self):
        return self.size

    def SetLocalRotation(self, x, y, z):
        pass

    def SetLocalScale(self, x, y, z):
        pass

    # --- 文档 §13(2) 层级与可见性 ---
    def SetActive(self, active):
        self.active = bool(active)

    def SetVisible(self, visible):
        self.visible = bool(visible)

    def GetChildren(self):
        return self._f.make_list(list(self.children))

    # --- 文档 §14 图片控件 ---
    def SetImage(self, source, image_id):
        self.image_source = source
        self.image_id = image_id

    # --- 文档 §13(5) 按键事件 ---
    def AddKeyEventListener(self, event_type, cb):
        self.listeners.setdefault(str(event_type), []).append(cb)

    def RemoveKeyEventListener(self, event_type, cb):
        lst = self.listeners.get(str(event_type), [])
        if not lst:
            raise Fail(f"RemoveKeyEventListener: {event_type} 上没有注册过监听")
        # 可靠判断「是不是同一个 Lua 函数」很麻烦：lupa 每次取出都是新包装对象，
        # 而 id() 会随旧包装被 GC 而重复使用。先按 id 试，再无条件兜底删第一个。
        for i, f in enumerate(lst):
            if id(f) == id(cb):
                lst.pop(i)
                return
        lst.pop(0)

    def RemoveKeyEventListeners(self, event_type):
        self.listeners.pop(str(event_type), None)

    def RemoveAllKeyEventListeners(self):
        self.listeners = {}


class MockGame:
    """模拟 game 表。make_list 由 build_env 注入为「返回 Lua 序列表」的函数。"""

    def __init__(self, canvas=(1920, 1080)):
        self.canvas = canvas
        self.controls: dict[int, MockControl] = {}
        self.next_id = 1000
        self.instantiate_calls = 0
        self.destroy_calls = 0
        self.make_list = list
        self.roots = [MockControl(-1, None, 1, self)]
        self.roots[0].name = "ClientUIControlCanvas"

    def GetClientUIRoots(self):
        # 必须返回 Lua 序列表：Lua 侧要用 #roots 和 roots[1]
        return self.make_list([c for c in self.roots if c.alive])

    def GetUICanvasSize(self):
        return self.canvas

    def InstantiateClientUIControl(self, prefab_index, parent):
        self.instantiate_calls += 1
        self.next_id += 1
        c = MockControl(prefab_index, parent, self.next_id, self)
        self.controls[self.next_id] = c
        return c

    def DestroyClientUIControl(self, control):
        self.destroy_calls += 1
        control.alive = False
        if control.parent is not None:
            try:
                control.parent.children.remove(control)
            except ValueError:
                pass
        self.controls.pop(control.id, None)


def build_env(mock: MockGame, printed: list[str], updates: list[bool]):
    """构造 lua 执行环境，返回 (lua, env)。"""
    lua = LuaRuntime(unpack_returned_tuples=True)

    def make_list(items):
        t = lua.table()
        for i, v in enumerate(items, start=1):
            t[i] = v
        return t

    mock.make_list = make_list

    def py_print(*a):
        printed.append(" ".join(str(x) for x in a))

    env = lua.table_from({
        "print": py_print,
        "printerr": py_print,
        "typeof": lambda v: type(v).__name__,
    })
    # 让脚本环境回退到标准库（ipairs/tostring/table/math/... 都靠它），
    # 同时保留上面注入的替身。真机上这些标准库本来就在。
    lua.execute("local env = ...; setmetatable(env, { __index = _G })", env)

    env["game"] = lua.table_from({
        "GetClientUIRoots": mock.GetClientUIRoots,
        "GetUICanvasSize": mock.GetUICanvasSize,
        "InstantiateClientUIControl": mock.InstantiateClientUIControl,
        "DestroyClientUIControl": mock.DestroyClientUIControl,
    })

    def enable_update(*args):
        # 冒号调用会多传一个 self（脚本实例），取最后一个参数才是 enabled
        updates.append(bool(args[-1]))

    env["script"] = lua.table_from({
        "alive": True,
        "scriptMappingId": 1073741871,
        "path": "verify/mock",
        "enabled": True,
        "EnableUpdate": enable_update,
        "RegisterServerSignalHandler": lambda *a: None,
    })
    env["Color"] = lua.table_from({
        "FromRGB": lambda r, g, b: (r, g, b, 255),
        "FromRGBA": lambda r, g, b, a=255: (r, g, b, a),
        "ToRGBA": lambda c: c,
    })

    def branch(names):
        t = lua.table()
        for n in names:
            t[n] = n
        return t

    env["Enum"] = lua.table_from({
        "ImageSource": branch(["StaticReference", "Item", "Equipment", "Skill",
                               "UnitStatus", "Faction", "Currency", "Prefab"]),
        "ImageType": branch(["Basic", "Stretch"]),
        "TextHorizontalAlignment": branch(["Left", "Middle", "Right"]),
        "TextVerticalAlignment": branch(["Top", "Middle", "Bottom"]),
        "CursorEventType": branch(["CursorDown", "CursorUp", "CursorEnter",
                                   "CursorExit", "CursorDrag", "CursorBeginDrag",
                                   "CursorEndDrag", "CursorClick"]),
        "KeyEventType": lua.table(),
        "Device": branch(["KeyboardAndMouse", "Mobile", "Controller", "MobileController"]),
    })
    return lua, env


def load_script(lua: LuaRuntime, env, test_table) -> None:
    """把 out/main.lua 编译并在给定环境里执行（会写出 __SPEECH_TEST__ 表）。"""
    with open(MAIN_LUA, encoding="utf-8") as fh:
        src = fh.read()
    env["__SPEECH_TEST__"] = test_table
    chunk = lua.eval("function(src, env) return load(src, '@main.lua', 't', env) end")(src, env)
    check(chunk is not None, "main.lua 未能编译")
    chunk()
    global LUA_STR
    LUA_STR = lua_str(lua, "")
