"""计时与速率控制。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Cooldown:
    """冷却计时器。`ready()` 判断是否可用，`trigger()` 刷新时间戳。"""
    duration: float
    last_used: float = field(default=0.0)

    def ready(self) -> bool:
        return (time.perf_counter() - self.last_used) >= self.duration

    def remaining(self) -> float:
        return max(0.0, self.duration - (time.perf_counter() - self.last_used))

    def trigger(self) -> None:
        self.last_used = time.perf_counter()

    def reset(self) -> None:
        self.last_used = 0.0


@dataclass
class RateLimiter:
    """最小间隔限流。"""
    min_interval: float
    _last: float = field(default=0.0)

    def allow(self) -> bool:
        now = time.perf_counter()
        if now - self._last >= self.min_interval:
            self._last = now
            return True
        return False


class Stopwatch:
    def __init__(self) -> None:
        self._start = time.perf_counter()

    def elapsed(self) -> float:
        return time.perf_counter() - self._start

    def reset(self) -> None:
        self._start = time.perf_counter()
