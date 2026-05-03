"""单元测试：vision/detector.py — Detection 数据类与 YOLODetector (mock)。"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vision.detector import Detection, YOLODetector


class TestDetection:
    def test_center(self):
        d = Detection(class_id=0, class_name="monster", confidence=0.9,
                      bbox=(100, 200, 200, 300))
        assert d.center == (150, 250)

    def test_wh(self):
        d = Detection(class_id=0, class_name="item", confidence=0.8,
                      bbox=(10, 20, 60, 90))
        assert d.wh == (50, 70)

    def test_center_integer_division(self):
        d = Detection(class_id=1, class_name="portal", confidence=0.7,
                      bbox=(0, 0, 101, 101))
        assert d.center == (50, 50)

    def test_dataclass_fields(self):
        d = Detection(class_id=2, class_name="boss", confidence=0.99,
                      bbox=(5, 5, 15, 15))
        assert d.class_id == 2
        assert d.class_name == "boss"
        assert d.confidence == 0.99
        assert d.bbox == (5, 5, 15, 15)


class TestYOLODetectorMocked:
    """YOLODetector 用 mock 避免真实模型加载，专注接口逻辑测试。

    YOLO 是在 __init__ 内部 `from ultralytics import YOLO` 导入的，
    因此需要通过 sys.modules 注入来拦截，而不是 patch("vision.detector.YOLO")。
    """

    def _make_detector(self, names=None):
        names = names or {0: "monster", 1: "item", 2: "portal"}
        mock_model = MagicMock()
        mock_model.names = names
        mock_model.predict.return_value = []

        mock_ultralytics = MagicMock()
        mock_ultralytics.YOLO.return_value = mock_model

        with patch.dict("sys.modules", {"ultralytics": mock_ultralytics}):
            detector = YOLODetector(
                model_path="fake.pt",
                conf_threshold=0.5,
                iou_threshold=0.45,
                half=False,
            )
        return detector, mock_model

    def test_init_sets_names(self):
        detector, _ = self._make_detector({0: "monster"})
        assert detector.names == {0: "monster"}

    def test_detect_empty_results(self):
        detector, mock_model = self._make_detector()
        mock_model.predict.return_value = []
        result = detector.detect(np.zeros((640, 640, 3), dtype=np.uint8))
        assert result == []

    def test_detect_no_boxes(self):
        detector, mock_model = self._make_detector()
        mock_result = MagicMock()
        mock_result.boxes = None
        mock_model.predict.return_value = [mock_result]
        result = detector.detect(np.zeros((640, 640, 3), dtype=np.uint8))
        assert result == []

    def test_detect_returns_detections(self):
        detector, mock_model = self._make_detector({0: "monster", 1: "item"})

        mock_boxes = MagicMock()
        mock_boxes.__len__ = MagicMock(return_value=2)  # prevent early-exit on len()==0
        mock_boxes.xyxy.cpu.return_value.numpy.return_value = np.array(
            [[10, 20, 50, 60], [100, 100, 200, 200]], dtype=np.float32
        )
        mock_boxes.conf.cpu.return_value.numpy.return_value = np.array([0.9, 0.7])
        mock_boxes.cls.cpu.return_value.numpy.return_value = np.array([0, 1])

        mock_result = MagicMock()
        mock_result.boxes = mock_boxes
        mock_model.predict.return_value = [mock_result]

        dets = detector.detect(np.zeros((640, 640, 3), dtype=np.uint8))
        assert len(dets) == 2
        assert dets[0].class_name == "monster"
        assert dets[0].bbox == (10, 20, 50, 60)
        assert abs(dets[0].confidence - 0.9) < 1e-4
        assert dets[1].class_name == "item"

    def test_class_filter(self):
        detector, mock_model = self._make_detector({0: "monster", 1: "item"})
        detector.class_filter = {"monster"}

        mock_boxes = MagicMock()
        mock_boxes.__len__ = MagicMock(return_value=2)
        mock_boxes.xyxy.cpu.return_value.numpy.return_value = np.array(
            [[0, 0, 10, 10], [20, 20, 30, 30]], dtype=np.float32
        )
        mock_boxes.conf.cpu.return_value.numpy.return_value = np.array([0.9, 0.8])
        mock_boxes.cls.cpu.return_value.numpy.return_value = np.array([0, 1])

        mock_result = MagicMock()
        mock_result.boxes = mock_boxes
        mock_model.predict.return_value = [mock_result]

        dets = detector.detect(np.zeros((640, 640, 3), dtype=np.uint8))
        assert len(dets) == 1
        assert dets[0].class_name == "monster"

    def test_last_infer_ms_updated(self):
        detector, mock_model = self._make_detector()
        mock_model.predict.return_value = []
        detector.detect(np.zeros((640, 640, 3), dtype=np.uint8))
        assert detector.last_infer_ms >= 0

    def test_fps_estimate_zero_before_detect(self):
        detector, _ = self._make_detector()
        detector.last_infer_ms = 0.0
        assert detector.fps_estimate == 0.0

    def test_fps_estimate_after_detect(self):
        detector, mock_model = self._make_detector()
        mock_model.predict.return_value = []
        detector.detect(np.zeros((640, 640, 3), dtype=np.uint8))
        if detector.last_infer_ms > 0:
            assert detector.fps_estimate > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
