"""单元测试：action/input_driver.py — InputDriver（mock Win32 SendInput）。"""
import ctypes
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import action.input_driver as _mod
from action.input_driver import InputDriver, _key_scan, _SCAN


class TestKeyScanTable:
    def test_common_keys_present(self):
        for key in ("a", "b", "c", "q", "w", "e", "r", "space", "enter", "esc"):
            assert key in _SCAN, f"key '{key}' missing from scan table"

    def test_direction_keys_present(self):
        for key in ("up", "down", "left", "right"):
            assert key in _SCAN

    def test_function_keys_present(self):
        for i in range(1, 13):
            assert f"f{i}" in _SCAN

    def test_unknown_key_raises(self):
        with pytest.raises(KeyError):
            _key_scan("not_a_key")

    def test_case_insensitive(self):
        sc1, _ = _key_scan("A")
        sc2, _ = _key_scan("a")
        assert sc1 == sc2

    def test_extended_keys_flagged(self):
        _, ext = _key_scan("up")
        assert ext is True
        _, ext = _key_scan("a")
        assert ext is False


class TestInputDriverMocked:
    """Patch SendInput so no actual keystrokes are sent during tests."""

    def setup_method(self):
        self._patcher = patch.object(
            ctypes.windll.user32, "SendInput", return_value=1
        )
        self._mock_send = self._patcher.start()
        self.driver = InputDriver(default_press_duration=0.001)

    def teardown_method(self):
        self._patcher.stop()

    def test_key_down_calls_send_input(self):
        self.driver.key_down("a")
        assert self._mock_send.called

    def test_key_up_calls_send_input(self):
        self.driver.key_up("a")
        assert self._mock_send.called

    def test_press_calls_down_then_up(self):
        call_count_before = self._mock_send.call_count
        self.driver.press("q", duration=0.001)
        assert self._mock_send.call_count == call_count_before + 2

    def test_hold_calls_down_then_up(self):
        call_count_before = self._mock_send.call_count
        self.driver.hold("right", duration=0.001)
        assert self._mock_send.call_count == call_count_before + 2

    def test_combo_sends_keys_in_order(self):
        combo = [("a", 0.001), ("b", 0.001), ("c", 0.001)]
        call_count_before = self._mock_send.call_count
        self.driver.combo(combo, interval=0.0)
        # Each key: down + up = 2 calls per key, 3 keys = 6 calls
        assert self._mock_send.call_count == call_count_before + 6

    def test_move_direction_single(self):
        call_count_before = self._mock_send.call_count
        self.driver.move_direction("right", 0.001)
        assert self._mock_send.call_count > call_count_before

    def test_move_direction_composite(self):
        """复合方向（逗号分隔）同时按下多个键。"""
        call_count_before = self._mock_send.call_count
        self.driver.move_direction("right,up", 0.001)
        # down(right) + down(up) + sleep + up(up) + up(right) = 4 calls
        assert self._mock_send.call_count == call_count_before + 4

    def test_mouse_move_calls_send(self):
        with patch.object(
            ctypes.windll.user32, "GetSystemMetrics", side_effect=[1920, 1080]
        ):
            self.driver.mouse_move_abs(960, 540)
        assert self._mock_send.called

    def test_mouse_click_calls_send(self):
        with patch.object(
            ctypes.windll.user32, "GetSystemMetrics", side_effect=[1920, 1080]
        ):
            call_count_before = self._mock_send.call_count
            self.driver.mouse_click(100, 100)
        assert self._mock_send.call_count > call_count_before

    def test_invalid_key_raises(self):
        with pytest.raises(KeyError):
            self.driver.key_down("invalid_key_xyz")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
