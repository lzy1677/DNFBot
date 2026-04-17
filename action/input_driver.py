"""Win32 SendInput 键鼠模拟。

不依赖任何第三方驱动，通过 ctypes 直接调用 user32.SendInput。
使用扫描码（Scan Code）发送键盘事件，兼容大多数游戏。
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import List, Tuple

# ---- Windows 常量 ----
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_EXTENDEDKEY = 0x0001

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010


# ---- SendInput 结构体 ----
ULONG_PTR = ctypes.c_size_t


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", _MOUSEINPUT),
        ("ki", _KEYBDINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


# ---- 扫描码表（DNF 常用按键） ----
# 参考：https://learn.microsoft.com/en-us/windows/win32/inputdev/about-keyboard-input
_SCAN = {
    "esc": 0x01,
    "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06,
    "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B,
    "minus": 0x0C, "equals": 0x0D, "backspace": 0x0E, "tab": 0x0F,
    "q": 0x10, "w": 0x11, "e": 0x12, "r": 0x13, "t": 0x14,
    "y": 0x15, "u": 0x16, "i": 0x17, "o": 0x18, "p": 0x19,
    "enter": 0x1C, "ctrl": 0x1D,
    "a": 0x1E, "s": 0x1F, "d": 0x20, "f": 0x21, "g": 0x22,
    "h": 0x23, "j": 0x24, "k": 0x25, "l": 0x26,
    "shift": 0x2A,
    "z": 0x2C, "x": 0x2D, "c": 0x2E, "v": 0x2F, "b": 0x30,
    "n": 0x31, "m": 0x32, "space": 0x39, "alt": 0x38,
    "f1": 0x3B, "f2": 0x3C, "f3": 0x3D, "f4": 0x3E, "f5": 0x3F,
    "f6": 0x40, "f7": 0x41, "f8": 0x42, "f9": 0x43, "f10": 0x44,
    "f11": 0x57, "f12": 0x58,
    # 方向键（扩展键）
    "up": 0xC8, "left": 0xCB, "right": 0xCD, "down": 0xD0,
}

# 需要带 EXTENDEDKEY 标志的扩展键
_EXTENDED = {"up", "down", "left", "right", "enter"}


def _key_scan(key: str) -> Tuple[int, bool]:
    k = key.lower().strip()
    if k not in _SCAN:
        raise KeyError(f"unsupported key: {key}")
    return _SCAN[k], k in _EXTENDED


def _make_key_input(scan: int, up: bool, extended: bool) -> _INPUT:
    flags = KEYEVENTF_SCANCODE
    if up:
        flags |= KEYEVENTF_KEYUP
    if extended:
        flags |= KEYEVENTF_EXTENDEDKEY
        # 扩展键高字节 0xE0 已编码在 scan 码高位（0xC8 等）
        scan = scan & 0xFF
    ki = _KEYBDINPUT(wVk=0, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
    return _INPUT(type=INPUT_KEYBOARD, u=_INPUT_UNION(ki=ki))


def _send(inputs: List[_INPUT]) -> int:
    n = len(inputs)
    arr = (_INPUT * n)(*inputs)
    return ctypes.windll.user32.SendInput(n, arr, ctypes.sizeof(_INPUT))


class InputDriver:
    """Win32 SendInput 键鼠驱动。"""

    def __init__(self, default_press_duration: float = 0.035) -> None:
        self.default_press = default_press_duration

    # ---- 键盘 ----
    def key_down(self, key: str) -> None:
        scan, ext = _key_scan(key)
        _send([_make_key_input(scan, up=False, extended=ext)])

    def key_up(self, key: str) -> None:
        scan, ext = _key_scan(key)
        _send([_make_key_input(scan, up=True, extended=ext)])

    def press(self, key: str, duration: float | None = None) -> None:
        duration = self.default_press if duration is None else duration
        self.key_down(key)
        time.sleep(duration)
        self.key_up(key)

    def hold(self, key: str, duration: float) -> None:
        self.key_down(key)
        time.sleep(duration)
        self.key_up(key)

    def combo(self, keys: List[Tuple[str, float]], interval: float = 0.03) -> None:
        """按序输入 [(key, duration), ...]，每次按键之间 sleep interval 秒。"""
        for key, dur in keys:
            self.press(key, dur)
            if interval > 0:
                time.sleep(interval)

    # ---- 鼠标 ----
    def mouse_move_abs(self, x: int, y: int) -> None:
        # 绝对坐标（0..65535 映射到屏幕）
        screen_w = ctypes.windll.user32.GetSystemMetrics(0)
        screen_h = ctypes.windll.user32.GetSystemMetrics(1)
        ax = int(x * 65535 / max(1, screen_w - 1))
        ay = int(y * 65535 / max(1, screen_h - 1))
        mi = _MOUSEINPUT(
            dx=ax, dy=ay, mouseData=0,
            dwFlags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE,
            time=0, dwExtraInfo=0,
        )
        _send([_INPUT(type=INPUT_MOUSE, u=_INPUT_UNION(mi=mi))])

    def mouse_click(self, x: int | None = None, y: int | None = None,
                    button: str = "left") -> None:
        if x is not None and y is not None:
            self.mouse_move_abs(x, y)
            time.sleep(0.01)
        down = MOUSEEVENTF_LEFTDOWN if button == "left" else MOUSEEVENTF_RIGHTDOWN
        up = MOUSEEVENTF_LEFTUP if button == "left" else MOUSEEVENTF_RIGHTUP
        for flag in (down, up):
            mi = _MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=flag,
                             time=0, dwExtraInfo=0)
            _send([_INPUT(type=INPUT_MOUSE, u=_INPUT_UNION(mi=mi))])
            time.sleep(0.01)

    # ---- 组合：方向移动 ----
    def move_direction(self, direction: str, duration: float) -> None:
        """direction: 'left'|'right'|'up'|'down'|'upleft'|... 复合方向用逗号分隔。"""
        keys = [d.strip() for d in direction.replace("+", ",").split(",")]
        for k in keys:
            self.key_down(k)
        time.sleep(duration)
        for k in reversed(keys):
            self.key_up(k)
