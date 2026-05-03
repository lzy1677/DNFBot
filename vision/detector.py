"""YOLO 推理封装。"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from utils.logger import get_logger


log = get_logger(__name__)


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
    def bottom_center(self) -> Tuple[int, int]:
        """角色脚底中心（x 中心，y 底边），用于 2.5D 定位对齐。"""
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) // 2, y2)

    @property
    def wh(self) -> Tuple[int, int]:
        x1, y1, x2, y2 = self.bbox
        return (x2 - x1, y2 - y1)


class YOLODetector:
    """Ultralytics YOLOv8 推理封装，针对 60+ FPS 游戏实时检测优化。

    Args:
        model_path: .pt / .onnx / .engine 权重路径。
        conf_threshold: 置信度阈值。
        iou_threshold: NMS IoU 阈值。
        device: "cuda:0" | "cpu" | None(自动)。
        imgsz: 推理输入尺寸，640 时 FPS 最高。
        half: FP16 推理，NVIDIA GPU 上可提速 ~2x，强烈建议开启。
        class_filter: 只保留这些类名，None 表示不过滤。
    """

    def __init__(
        self,
        model_path: str,
        conf_threshold: float = 0.5,
        iou_threshold: float = 0.45,
        device: Optional[str] = None,
        imgsz: int = 640,
        half: bool = True,
        class_filter: Optional[List[str]] = None,
    ) -> None:
        from ultralytics import YOLO

        log.info("加载模型权重: %s", model_path)
        self.model = YOLO(model_path)
        self.conf = conf_threshold
        self.iou = iou_threshold
        self.device = device
        self.imgsz = imgsz
        self.half = half
        self.class_filter = set(class_filter) if class_filter else None
        self.names: dict = self.model.names
        self.last_infer_ms: float = 0.0

        log.info("模型类别 (%d): %s", len(self.names),
                 list(self.names.values())[:10])  # 最多显示 10 个

        self.warmup()

    def detect(self, frame: np.ndarray) -> List[Detection]:
        t0 = time.perf_counter()
        results = self.model.predict(
            frame,
            conf=self.conf,
            iou=self.iou,
            imgsz=self.imgsz,
            device=self.device,
            half=self.half,
            verbose=False,
        )
        self.last_infer_ms = (time.perf_counter() - t0) * 1000

        detections: List[Detection] = []
        if not results:
            return detections

        r = results[0]
        if r.boxes is None or len(r.boxes) == 0:
            log.debug("[detect] %.1fms  0 目标", self.last_infer_ms)
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

        if detections:
            summary = ", ".join(
                f"{d.class_name}({d.confidence:.2f})" for d in detections
            )
            log.debug("[detect] %.1fms  %d 目标: %s",
                      self.last_infer_ms, len(detections), summary)
        else:
            log.debug("[detect] %.1fms  0 目标（过滤后）", self.last_infer_ms)

        return detections

    @property
    def fps_estimate(self) -> float:
        """根据最近一次推理时间估算 FPS。"""
        return 1000.0 / self.last_infer_ms if self.last_infer_ms > 0 else 0.0

    def warmup(self, rounds: int = 3) -> None:
        """用随机噪声预热，消除 CUDA JIT 和内存分配延迟。"""
        log.info("YOLO 预热 (%d 轮) ...", rounds)
        dummy = np.zeros((self.imgsz, self.imgsz, 3), dtype=np.uint8)
        t0 = time.perf_counter()
        for i in range(rounds):
            self.model.predict(
                dummy,
                imgsz=self.imgsz,
                device=self.device,
                half=self.half,
                verbose=False,
            )
            log.debug("[warmup] %d/%d", i + 1, rounds)
        # 最后一轮计时作为 last_infer_ms 参考
        self.last_infer_ms = (time.perf_counter() - t0) / rounds * 1000
        log.info("预热完成  平均推理 %.1fms  (~%.0f FPS)",
                 self.last_infer_ms, self.fps_estimate)
