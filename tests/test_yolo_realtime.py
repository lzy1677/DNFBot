"""实时 YOLO 检测测试脚本。

功能：
  - 实时截取游戏窗口（或指定区域 / 全屏）
  - 跑 YOLO 推理
  - OpenCV 窗口实时展示检测框、FPS、类别/置信度

用法：
    # 全屏 + 默认模型权重
    python tests/test_yolo_realtime.py --model vision/models/dnf_v1.pt

    # 指定区域（DNF 通常是 1280x720 窗口）
    python tests/test_yolo_realtime.py --model vision/models/dnf_v1.pt \
        --region 0,0,1280,720

    # 通过窗口标题自动定位（Windows 下）
    python tests/test_yolo_realtime.py --model yolov8n.pt --window "地下城与勇士"

快捷键：
  q / ESC : 退出
  s       : 保存当前帧到 tests/captures/
  p       : 暂停/继续
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from collections import deque
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vision.capture import ScreenCapture  # noqa: E402
from vision.detector import YOLODetector, Detection  # noqa: E402


# 每个类分配一个固定颜色（BGR）
_PALETTE = [
    (0, 255, 0), (0, 255, 255), (255, 128, 0), (255, 0, 255),
    (0, 128, 255), (128, 255, 0), (255, 255, 0), (0, 0, 255),
    (128, 0, 255), (255, 0, 128), (0, 255, 128), (128, 128, 255),
]


def color_for(class_id: int) -> Tuple[int, int, int]:
    return _PALETTE[class_id % len(_PALETTE)]


def parse_region(s: str) -> Tuple[int, int, int, int]:
    parts = [int(x.strip()) for x in s.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("region 必须是 left,top,right,bottom")
    return tuple(parts)  # type: ignore


def find_window_region(title_substr: str) -> Optional[Tuple[int, int, int, int]]:
    """通过窗口标题片段查找窗口矩形（Windows only）。"""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32

        EnumWindows = user32.EnumWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(
            ctypes.c_bool, wintypes.HWND, wintypes.LPARAM
        )
        GetWindowTextW = user32.GetWindowTextW
        GetWindowTextLengthW = user32.GetWindowTextLengthW
        IsWindowVisible = user32.IsWindowVisible
        GetWindowRect = user32.GetWindowRect

        found = []

        def cb(hwnd, lparam):
            if not IsWindowVisible(hwnd):
                return True
            n = GetWindowTextLengthW(hwnd)
            if n == 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            GetWindowTextW(hwnd, buf, n + 1)
            if title_substr in buf.value:
                rect = wintypes.RECT()
                GetWindowRect(hwnd, ctypes.byref(rect))
                found.append((rect.left, rect.top, rect.right, rect.bottom))
                return False
            return True

        EnumWindows(EnumWindowsProc(cb), 0)
        return found[0] if found else None
    except Exception as e:
        print(f"[warn] 窗口查找失败: {e}")
        return None


def draw_detections(
    frame: np.ndarray, detections, show_center: bool = False
) -> np.ndarray:
    out = frame
    for d in detections:
        x1, y1, x2, y2 = d.bbox
        color = color_for(d.class_id)
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)

        label = f"{d.class_name} {d.confidence:.2f}"
        (tw, th), baseline = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
        )
        cv2.rectangle(
            out, (x1, y1 - th - baseline - 4), (x1 + tw + 4, y1), color, -1
        )
        cv2.putText(
            out, label, (x1 + 2, y1 - baseline - 2),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA,
        )

        if show_center:
            cx, cy = d.center
            cv2.circle(out, (cx, cy), 3, color, -1)
    return out


def draw_hud(
    frame: np.ndarray,
    fps: float,
    cap_ms: float,
    infer_ms: float,
    n_det: int,
    backend: str,
    paused: bool,
) -> np.ndarray:
    lines = [
        f"FPS: {fps:5.1f}  cap: {cap_ms:4.1f}ms  infer: {infer_ms:5.1f}ms",
        f"backend: {backend}   detections: {n_det}" + ("   [PAUSED]" if paused else ""),
        "q/ESC quit | s save | p pause",
    ]
    y = 20
    for line in lines:
        cv2.putText(
            frame, line, (10, y),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3, cv2.LINE_AA,
        )
        cv2.putText(
            frame, line, (10, y),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA,
        )
        y += 20
    return frame


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model",
                    # default="runs/detect/train/runs/yolov8n/weights/best.pt",
                    default="runs/detect/train/runs/yolov8n2/weights/best.pt",
                    help="YOLO 权重路径")
    ap.add_argument("--region", type=parse_region, default=None,
                    help="截图区域 left,top,right,bottom")
    ap.add_argument("--window", default=None,
                    help="按窗口标题片段自动定位区域")
    ap.add_argument("--conf", type=float, default=0.35)
    ap.add_argument("--iou", type=float, default=0.45)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--device", default=None, help="'cuda:0' / 'cpu' / None")
    ap.add_argument("--half", action="store_true", default=True,
                    help="FP16 推理，NVIDIA GPU 上约 2x 提速（默认开启）")
    ap.add_argument("--no-half", dest="half", action="store_false",
                    help="关闭 FP16（CPU 推理时需要加此选项）")
    ap.add_argument("--backend", default="auto", choices=["auto", "dxcam", "mss"])
    ap.add_argument("--target-fps", type=int, default=60)
    ap.add_argument("--max-width", type=int, default=1280,
                    help="展示窗口最大宽度（超出则等比缩放）")
    args = ap.parse_args()

    region = args.region
    if region is None and args.window:
        region = find_window_region(args.window)
        if region is None:
            print(f"[error] 找不到包含 '{args.window}' 的窗口")
            return 1
        print(f"[info] 锁定窗口区域: {region}")

    if not os.path.exists(args.model):
        print(f"[warn] 模型文件 {args.model} 不存在，"
              f"ultralytics 会尝试从网络下载（仅适用于官方权重如 yolov8n.pt）")

    print("[info] 初始化 YOLO（含 warmup）...")
    detector = YOLODetector(
        model_path=args.model,
        conf_threshold=args.conf,
        iou_threshold=args.iou,
        device=args.device,
        imgsz=args.imgsz,
        half=args.half,
    )
    print(f"[info] 类别: {detector.names}")

    print("[info] 初始化截图 ...")
    capture = ScreenCapture(
        region=region, target_fps=args.target_fps, backend=args.backend
    )
    print(f"[info] 截图后端: {capture.backend}")

    save_dir = Path(__file__).parent / "captures"
    save_dir.mkdir(exist_ok=True)

    win_name = "DNF YOLO Realtime"
    cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)

    frame_times = deque(maxlen=30)
    paused = False
    last_frame: Optional[np.ndarray] = None
    last_dets = []

    try:
        while True:
            t_loop = time.perf_counter()

            if not paused:
                t_cap = time.perf_counter()
                frame = capture.grab()
                cap_ms = (time.perf_counter() - t_cap) * 1000
                if frame is None:
                    time.sleep(0.005)
                    continue
                last_frame = frame
                last_dets = detector.detect(frame)
            else:
                cap_ms = 0.0
                if last_frame is None:
                    time.sleep(0.02)
                    continue

            infer_ms = detector.last_infer_ms
            display = last_frame.copy()
            display = draw_detections(display, last_dets, show_center=True)

            frame_times.append(time.perf_counter() - t_loop)
            fps = len(frame_times) / sum(frame_times) if frame_times else 0.0

            display = draw_hud(
                display, fps, cap_ms, infer_ms,
                len(last_dets), capture.backend, paused,
            )

            if display.shape[1] > args.max_width:
                scale = args.max_width / display.shape[1]
                display = cv2.resize(
                    display, (args.max_width, int(display.shape[0] * scale))
                )

            cv2.imshow(win_name, display)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            elif key == ord("s") and last_frame is not None:
                ts = time.strftime("%Y%m%d_%H%M%S")
                raw_path = save_dir / f"frame_{ts}.png"
                ann_path = save_dir / f"frame_{ts}_annotated.png"
                cv2.imwrite(str(raw_path), last_frame)
                cv2.imwrite(str(ann_path), display)
                print(f"[save] {raw_path.name} + {ann_path.name}")
            elif key == ord("p"):
                paused = not paused
                print(f"[{'paused' if paused else 'resumed'}]")
    except KeyboardInterrupt:
        pass
    finally:
        capture.close()
        cv2.destroyAllWindows()

    s = capture.stats
    print(f"\n[stats] 总帧数 {s.frames}, 平均截图 FPS {s.fps:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
