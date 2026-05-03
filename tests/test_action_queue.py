"""单元测试：action/action_queue.py — Action 类型与 ActionQueue。"""
import sys
import time
import threading
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from action.action_queue import (
    Action, ActionQueue, Callback, KeyHold, KeyPress, MouseClick, Move, Wait,
)
from action.input_driver import InputDriver


class TestActionTypes:
    def setup_method(self):
        self.driver = MagicMock(spec=InputDriver)

    def test_key_press_executes(self):
        a = KeyPress(key="a", duration=0.04)
        a.execute(self.driver)
        self.driver.press.assert_called_once_with("a", 0.04)

    def test_key_hold_executes(self):
        a = KeyHold(key="right", duration=0.3)
        a.execute(self.driver)
        self.driver.hold.assert_called_once_with("right", 0.3)

    def test_move_executes(self):
        a = Move(direction="left", duration=0.5)
        a.execute(self.driver)
        self.driver.move_direction.assert_called_once_with("left", 0.5)

    def test_wait_sleeps(self):
        a = Wait(seconds=0.01)
        t0 = time.perf_counter()
        a.execute(self.driver)
        assert time.perf_counter() - t0 >= 0.008

    def test_mouse_click_executes(self):
        a = MouseClick(x=100, y=200, button="left")
        a.execute(self.driver)
        self.driver.mouse_click.assert_called_once_with(100, 200, "left")

    def test_callback_executes(self):
        called = []
        a = Callback(fn=lambda: called.append(1))
        a.execute(self.driver)
        assert called == [1]

    def test_callback_none_is_safe(self):
        a = Callback(fn=None)
        a.execute(self.driver)  # should not raise

    def test_base_action_raises(self):
        a = Action()
        with pytest.raises(NotImplementedError):
            a.execute(self.driver)

    def test_action_tag(self):
        a = KeyPress(key="q", tag="skill:q")
        assert a.tag == "skill:q"


class TestActionQueue:
    def setup_method(self):
        self.driver = MagicMock(spec=InputDriver)
        self.driver.press = MagicMock()
        self.queue = ActionQueue(self.driver)
        self.queue.start()

    def teardown_method(self):
        self.queue.stop()

    def test_submit_single_action(self):
        executed = threading.Event()
        self.queue.submit(Callback(fn=executed.set))
        assert executed.wait(timeout=2.0), "Action was not executed"

    def test_submit_list_actions(self):
        results = []
        lock = threading.Lock()
        done = threading.Event()

        def append(v):
            with lock:
                results.append(v)
                if len(results) == 3:
                    done.set()

        self.queue.submit([
            Callback(fn=lambda: append(1)),
            Callback(fn=lambda: append(2)),
            Callback(fn=lambda: append(3)),
        ])
        assert done.wait(timeout=2.0)
        assert results == [1, 2, 3]

    def test_clear_empties_queue(self):
        # Fill queue with slow waits then clear before they run
        for _ in range(20):
            self.queue.submit(Wait(seconds=0.5))
        self.queue.clear()
        assert self.queue.size() <= 1  # at most the one currently executing

    def test_is_busy_true_while_running(self):
        flag = threading.Event()

        def slow():
            time.sleep(0.1)
            flag.set()

        self.queue.submit(Callback(fn=slow))
        time.sleep(0.02)
        assert self.queue.is_busy()
        flag.wait(timeout=1.0)

    def test_is_busy_false_when_empty(self):
        done = threading.Event()
        self.queue.submit(Callback(fn=done.set))
        done.wait(timeout=1.0)
        time.sleep(0.05)
        assert not self.queue.is_busy()

    def test_stop_and_restart(self):
        self.queue.stop()
        self.queue.start()
        executed = threading.Event()
        self.queue.submit(Callback(fn=executed.set))
        assert executed.wait(timeout=2.0)

    def test_exception_in_action_does_not_crash_worker(self):
        def bad():
            raise RuntimeError("intentional error")

        done = threading.Event()
        self.queue.submit(Callback(fn=bad))
        self.queue.submit(Callback(fn=done.set))
        assert done.wait(timeout=2.0), "Worker crashed after exception"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
