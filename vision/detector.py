"""YOLO 推理封装。"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np


@dataclass
class Detection:
    class_id: int
    class_name: str
    confidence: float
    bbox: Tuple[int, int, int, int]  # (x1, y1, x2, y2)

    @property
    def center(self) -> Tuple[int, int]:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    @property
    def wh(self) -> Tuple[int, int]:
        x1, y1, x2, y2 = self.bbox
        return (x2 - x1, y2 - y1)


class YOLODetector:
    """Ultralytics YOLOv8 推理封装。

    Args:
        model_path: .pt 权重路径。
        conf_threshold: 置信度阈值。
        iou_threshold: NMS IoU 阈值。
        device: "cuda:0" | "cpu" | None(自动)。
        imgsz: 推理输入尺寸。
        class_filter: 只保留这些类名的检测结果，None 表示不过滤。
    """

    def __init__(
        self,
        model_path: str,
        conf_threshold: float = 0.5,
        iou_threshold: float = 0.45,
        device: Optional[str] = None,
        imgsz: int = 640,
        class_filter: Optional[List[str]] = None,
    ) -> None:
        from ultralytics import YOLO  # 延迟导入

        self.model = YOLO(model_path)
        self.conf = conf_threshold
        self.iou = iou_threshold
        self.device = device
        self.imgsz = imgsz
        self.class_filter = set(class_filter) if class_filter else None
        self.names: dict = self.model.names
        self.last_infer_time: float = 0.0

    def detect(self, frame: np.ndarray) -> List[Detection]:
        t0 = time.perf_counter()
        results = self.model.predict(
            frame,
            conf=self.conf,
            iou=self.iou,
            imgsz=self.imgsz,
            device=self.device,
            verbose=False,
        )
        self.last_infer_time = time.perf_counter() - t0

        detections: List[Detection] = []
        if not results:
            return detections

        r = results[0]
        if r.boxes is None or len(r.boxes) == 0:
            return detections

        xyxy = r.boxes.xyxy.cpu().numpy()
        confs = r.boxes.conf.cpu().numpy()
        clss = r.boxes.cls.cpu().numpy().astype(int)

        for (x1, y1, x2, y2), conf, cid in zip(xyxy, confs, clss):
            name = self.names.get(int(cid), str(cid))
            if self.class_filter and name not in self.class_filter:
                continue
            detections.append(
                Detection(
                    class_id=int(cid),
                    class_name=name,
                    confidence=float(conf),
                    bbox=(int(x1), int(y1), int(x2), int(y2)),
                )
            )
        return detections

    def warmup(self, size: int = 640) -> None:
        dummy = np.zeros((size, size, 3), dtype=np.uint8)
        self.detect(dummy)
