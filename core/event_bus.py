"""轻量事件总线，用于模块间解耦通信。"""
from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any, Callable, DefaultDict, List


Handler = Callable[[Any], None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: DefaultDict[str, List[Handler]] = defaultdict(list)
        self._lock = threading.Lock()

    def on(self, event: str, handler: Handler) -> None:
        with self._lock:
            self._handlers[event].append(handler)

    def off(self, event: str, handler: Handler) -> None:
        with self._lock:
            if handler in self._handlers[event]:
                self._handlers[event].remove(handler)

    def emit(self, event: str, payload: Any = None) -> None:
        with self._lock:
            handlers = list(self._handlers.get(event, ()))
        for h in handlers:
            try:
                h(payload)
            except Exception:
                import logging
                logging.getLogger(__name__).exception("event handler error: %s", event)
