"""单元测试：vision/capture.py — ScreenCapture（mock dxcam / mss）。"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vision.capture import ScreenCapture, CaptureStats


class TestCaptureStats:
    def test_fps_zero_when_no_frames(self):
        stats = CaptureStats()
        assert stats.fps == 0.0

    def test_fps_calculated(self):
        stats = CaptureStats(frames=60, total_time=2.0)
        assert stats.fps == 30.0


class TestScreenCaptureMss:
    """测试 mss 后端（不需要真实 GPU）。

    mss 也是在方法内部 `import mss` 导入的，需要用 sys.modules 注入。
    """

    def _make_capture(self, region=None) -> ScreenCapture:
        mock_mss_obj = MagicMock()
        mock_mss_obj.monitors = [None, {"left": 0, "top": 0, "width": 1920, "height": 1080}]
        fake_frame = np.zeros((1080, 1920, 4), dtype=np.uint8)
        mock_mss_obj.grab.return_value = fake_frame

        mock_mss_module = MagicMock()
        mock_mss_module.mss.return_value = mock_mss_obj

        with patch.dict("sys.modules", {"dxcam": None, "mss": mock_mss_module}):
            cap = ScreenCapture(region=region, backend="mss")

        return cap

    def test_backend_name(self):
        cap = self._make_capture()
        assert cap.backend == "mss"

    def test_grab_returns_bgr_frame(self):
        cap = self._make_capture()
        frame = cap.grab()
        assert frame is not None
        assert frame.ndim == 3
        assert frame.shape[2] == 3  # BGR, no alpha

    def test_grab_with_region(self):
        cap = self._make_capture(region=(0, 0, 640, 480))
        frame = cap.grab()
        assert frame is not None

    def test_stats_updated(self):
        cap = self._make_capture()
        assert cap.stats.frames == 0
        cap.grab()
        assert cap.stats.frames == 1

    def test_stats_fps_after_grabs(self):
        cap = self._make_capture()
        for _ in range(5):
            cap.grab()
        assert cap.stats.fps > 0

    def test_context_manager(self):
        cap = self._make_capture()
        with cap:
            assert cap.grab() is not None


class TestScreenCaptureDxcam:
    """测试 dxcam 后端（mock dxcam）。"""

    def _make_capture(self, region=None) -> ScreenCapture:
        fake_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        mock_camera = MagicMock()
        mock_camera.grab.return_value = fake_frame

        mock_dxcam = MagicMock()
        mock_dxcam.create.return_value = mock_camera

        with patch.dict("sys.modules", {"dxcam": mock_dxcam}):
            cap = ScreenCapture(region=region, backend="dxcam")

        cap._impl = mock_camera
        return cap

    def test_backend_name(self):
        cap = self._make_capture()
        assert cap.backend == "dxcam"

    def test_grab_returns_frame(self):
        cap = self._make_capture()
        frame = cap.grab()
        assert frame is not None
        assert frame.shape == (720, 1280, 3)

    def test_grab_none_returns_none(self):
        cap = self._make_capture()
        cap._impl.grab.return_value = None
        frame = cap.grab()
        assert frame is None

    def test_grab_none_doesnt_update_stats(self):
        cap = self._make_capture()
        cap._impl.grab.return_value = None
        cap.grab()
        assert cap.stats.frames == 0

    def test_start_stream(self):
        cap = self._make_capture()
        result = cap.start_stream()
        assert result is True
        cap._impl.start.assert_called_once()

    def test_close_stops_stream(self):
        cap = self._make_capture()
        cap.close()
        cap._impl.stop.assert_called_once()


class TestScreenCaptureAutoFallback:
    def test_auto_falls_back_to_mss_when_dxcam_unavailable(self):
        mock_mss_obj = MagicMock()
        mock_mss_obj.monitors = [None, {"left": 0, "top": 0, "width": 1920, "height": 1080}]
        mock_mss_module = MagicMock()
        mock_mss_module.mss.return_value = mock_mss_obj

        with patch.dict("sys.modules", {"dxcam": None, "mss": mock_mss_module}):
            cap = ScreenCapture(backend="auto")

        assert cap.backend == "mss"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
