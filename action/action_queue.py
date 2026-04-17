"""操作队列。

把高级动作编译成对 InputDriver 的调用，串行执行，避免指令冲突。
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, List, Optional

from utils.logger import get_logger
from .input_driver import InputDriver


log = get_logger(__name__)


@dataclass
class Action:
    """动作基类。子类实现 `execute(driver)`."""
    priority: int = 0  # 数值越大优先级越高
    tag: str = ""

    def execute(self, driver: InputDriver) -> None:
        raise NotImplementedError


@dataclass
class KeyPress(Action):
    key: str = ""
    duration: float = 0.04

    def execute(self, driver: InputDriver) -> None:
        driver.press(self.key, self.duration)


@dataclass
class KeyHold(Action):
    key: str = ""
    duration: float = 0.2

    def execute(self, driver: InputDriver) -> None:
        driver.hold(self.key, self.duration)


@dataclass
class Move(Action):
    direction: str = "right"
    duration: float = 0.3

    def execute(self, driver: InputDriver) -> None:
        driver.move_direction(self.direction, self.duration)


@dataclass
class Wait(Action):
    seconds: float = 0.1

    def execute(self, driver: InputDriver) -> None:
        time.sleep(self.seconds)


@dataclass
class MouseClick(Action):
    x: int = 0
    y: int = 0
    button: str = "left"

    def execute(self, driver: InputDriver) -> None:
        driver.mouse_click(self.x, self.y, self.button)


@dataclass
class Callback(Action):
    fn: Optional[Callable[[], None]] = None

    def execute(self, driver: InputDriver) -> None:
        if self.fn is not None:
            self.fn()


class ActionQueue:
    """串行执行 Action。

    由独立 worker 线程消费，避免主循环阻塞。
    调用 `submit()` 追加，`clear()` 清空（被打断连招）。
    """

    def __init__(self, driver: InputDriver) -> None:
        self.driver = driver
        self._q: Deque[Action] = deque()
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._current: Optional[Action] = None

    # ---- 生命周期 ----
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="ActionQueue", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        self._stop.set()
        with self._cv:
            self._cv.notify_all()
        if self._thread:
            self._thread.join(timeout=timeout)

    # ---- 外部 API ----
    def submit(self, actions: List[Action] | Action) -> None:
        if isinstance(actions, Action):
            actions = [actions]
        with self._cv:
            self._q.extend(actions)
            self._cv.notify()

    def clear(self) -> None:
        with self._cv:
            self._q.clear()

    def is_busy(self) -> bool:
        with self._lock:
            return bool(self._q) or self._current is not None

    def size(self) -> int:
        with self._lock:
            return len(self._q)

    # ---- 内部 ----
    def _run(self) -> None:
        while not self._stop.is_set():
            with self._cv:
                while not self._q and not self._stop.is_set():
                    self._cv.wait(timeout=0.1)
                if self._stop.is_set():
                    return
                action = self._q.popleft()
                self._current = action

            try:
                action.execute(self.driver)
            except Exception as e:
                log.warning("action %s failed: %s", action.tag or type(action).__name__, e)
            finally:
                with self._lock:
                    self._current = None
