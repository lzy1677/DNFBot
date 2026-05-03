"""单元测试：core/event_bus.py — EventBus。"""
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.event_bus import EventBus


class TestEventBus:
    def setup_method(self):
        self.bus = EventBus()

    def test_emit_calls_handler(self):
        received = []
        self.bus.on("test", lambda p: received.append(p))
        self.bus.emit("test", "hello")
        assert received == ["hello"]

    def test_emit_no_handlers_is_safe(self):
        self.bus.emit("nonexistent_event")

    def test_multiple_handlers_all_called(self):
        results = []
        self.bus.on("e", lambda p: results.append(1))
        self.bus.on("e", lambda p: results.append(2))
        self.bus.emit("e", None)
        assert sorted(results) == [1, 2]

    def test_off_removes_handler(self):
        received = []
        handler = lambda p: received.append(p)
        self.bus.on("e", handler)
        self.bus.off("e", handler)
        self.bus.emit("e", "x")
        assert received == []

    def test_off_nonexistent_handler_is_safe(self):
        self.bus.off("e", lambda p: None)  # should not raise

    def test_emit_passes_payload(self):
        payloads = []
        self.bus.on("data", lambda p: payloads.append(p))
        self.bus.emit("data", {"key": "value"})
        assert payloads == [{"key": "value"}]

    def test_emit_none_payload(self):
        received = []
        self.bus.on("e", lambda p: received.append(p))
        self.bus.emit("e")
        assert received == [None]

    def test_handler_exception_does_not_propagate(self):
        def bad_handler(p):
            raise ValueError("boom")

        self.bus.on("e", bad_handler)
        self.bus.emit("e")  # should not raise

    def test_thread_safe_concurrent_emit(self):
        results = []
        lock = threading.Lock()

        def handler(p):
            with lock:
                results.append(p)

        self.bus.on("e", handler)

        threads = [threading.Thread(target=self.bus.emit, args=("e", i)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 50

    def test_different_events_independent(self):
        a_results = []
        b_results = []
        self.bus.on("a", lambda p: a_results.append(p))
        self.bus.on("b", lambda p: b_results.append(p))
        self.bus.emit("a", 1)
        self.bus.emit("b", 2)
        assert a_results == [1]
        assert b_results == [2]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
