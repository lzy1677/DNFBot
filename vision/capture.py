"""屏幕截图模块。

优先使用 DXCam（基于 Desktop Duplication API，性能最好），
环境不支持时回退到 mss。统一返回 BGR 格式的 numpy 数组。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np


Region = Tuple[int, int, int, int]  # (left, top, right, bottom)


@dataclass
class CaptureStats:
    frames: int = 0
    total_time: float = 0.0
    last_frame_time: float = 0.0

    @property
    def fps(self) -> float:
        return self.frames / self.total_time if self.total_time > 0 else 0.0


class ScreenCapture:
    """统一截图接口。

    Args:
        region: (left, top, right, bottom)，None 表示全屏。
        target_fps: DXCam 的目标 FPS 上限（仅在 backend=dxcam 时生效）。
        backend: "dxcam" | "mss" | "auto"。
    """

    def __init__(
        self,
        region: Optional[Region] = None,
        target_fps: int = 60,
        backend: str = "auto",
    ) -> None:
        self.region = region
        self.target_fps = target_fps
        self.stats = CaptureStats()
        self._backend_name: str = ""
        self._impl = self._init_backend(backend)

    def _init_backend(self, backend: str):
        if backend in ("auto", "dxcam"):
            try:
                import dxcam  # type: ignore

                camera = dxcam.create(output_color="BGR")
                if camera is None:
                    raise RuntimeError("dxcam.create returned None")
                self._backend_name = "dxcam"
                return camera
            except Exception as e:
                if backend == "dxcam":
                    raise
                print(f"[capture] dxcam init failed ({e}), fallback to mss")

        import mss  # type: ignore

        self._backend_name = "mss"
        return mss.mss()

    @property
    def backend(self) -> str:
        return self._backend_name

    def grab(self) -> Optional[np.ndarray]:
        """抓一帧。返回 BGR ndarray，失败返回 None。"""
        t0 = time.perf_counter()

        if self._backend_name == "dxcam":
            frame = self._impl.grab(region=self.region)
        else:
            frame = self._grab_mss()

        dt = time.perf_counter() - t0
        if frame is not None:
            self.stats.frames += 1
            self.stats.total_time += dt
            self.stats.last_frame_time = dt
        return frame

    def _grab_mss(self) -> np.ndarray:
        if self.region:
            l, t, r, b = self.region
            mon = {"left": l, "top": t, "width": r - l, "height": b - t}
        else:
            mon = self._impl.monitors[1]
        raw = np.array(self._impl.grab(mon))  # BGRA
        return raw[:, :, :3]  # drop alpha -> BGR

    def start_stream(self) -> bool:
        """DXCam 连续抓取模式（可选）。"""
        if self._backend_name != "dxcam":
            return False
        self._impl.start(region=self.region, target_fps=self.target_fps)
        return True

    def stop_stream(self) -> None:
        if self._backend_name == "dxcam":
            try:
                self._impl.stop()
            except Exception:
                pass

    def close(self) -> None:
        self.stop_stream()
        if self._backend_name == "mss":
            try:
                self._impl.close()
            except Exception:
                pass

    def __enter__(self) -> "ScreenCapture":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
