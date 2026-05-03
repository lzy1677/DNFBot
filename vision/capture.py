"""屏幕截图模块。

优先使用 DXCam（基于 Desktop Duplication API，性能最好），
环境不支持时回退到 mss。统一返回 BGR 格式的 numpy 数组。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import time
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np


Region = Tuple[int, int, int, int]  # (left, top, right, bottom)


# ---- Win32 辅助 ----

class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize",    ctypes.wintypes.DWORD),
        ("rcMonitor", ctypes.wintypes.RECT),
        ("rcWork",    ctypes.wintypes.RECT),
        ("dwFlags",   ctypes.wintypes.DWORD),
    ]


def find_window_region(title: str) -> Optional[Region]:
    """通过窗口标题查找窗口在虚拟桌面上的坐标，返回 (left, top, right, bottom)。"""
    hwnd = ctypes.windll.user32.FindWindowW(None, title)
    if not hwnd:
        return None
    rect = ctypes.wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return (rect.left, rect.top, rect.right, rect.bottom)


def _monitor_info_for_point(cx: int, cy: int) -> Tuple[int, int, int]:
    """
    返回 (mon_left, mon_top, output_idx)。
    output_idx 是 EnumDisplayMonitors 的枚举顺序，对应 dxcam 的 output_idx。
    """
    pt = ctypes.wintypes.POINT()
    pt.x, pt.y = cx, cy
    hmon = ctypes.windll.user32.MonitorFromPoint(pt, 2)  # MONITOR_DEFAULTTONEAREST

    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(_MONITORINFO)
    ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(info))

    monitors: list = []
    _CB = ctypes.WINFUNCTYPE(
        ctypes.c_bool,
        ctypes.c_size_t, ctypes.c_size_t,
        ctypes.POINTER(ctypes.wintypes.RECT),
        ctypes.c_size_t,
    )

    def _cb(hm, hdc, lprect, data):
        monitors.append(hm)
        return True

    ctypes.windll.user32.EnumDisplayMonitors(None, None, _CB(_cb), 0)

    try:
        output_idx = monitors.index(hmon)
    except ValueError:
        output_idx = 0

    return info.rcMonitor.left, info.rcMonitor.top, output_idx


# ---- 截图模块 ----

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
        region: (left, top, right, bottom) 虚拟桌面坐标，None 表示全屏。
        target_fps: DXCam 的目标 FPS 上限。
        backend: "dxcam" | "mss" | "auto"。
        window_title: 按窗口标题自动定位 region（region 为 None 时生效）。
    """

    def __init__(
        self,
        region: Optional[Region] = None,
        target_fps: int = 60,
        backend: str = "auto",
        window_title: Optional[str] = None,
    ) -> None:
        self.target_fps = target_fps
        self.stats = CaptureStats()
        self._backend_name: str = ""
        self._dxcam_region: Optional[Region] = None  # 显示器相对坐标

        if region is not None:
            self.region = region
        elif window_title:
            self.region = find_window_region(window_title)
            if self.region:
                print(f"[capture] 窗口 '{window_title}' 定位成功: {self.region}")
            else:
                print(f"[capture] 未找到窗口 '{window_title}'，回退为全屏")
                self.region = None
        else:
            self.region = None

        self._impl = self._init_backend(backend)

    def _init_backend(self, backend: str):
        if backend in ("auto", "dxcam"):
            try:
                import dxcam  # type: ignore

                output_idx = 0
                if self.region is not None:
                    cx = (self.region[0] + self.region[2]) // 2
                    cy = (self.region[1] + self.region[3]) // 2
                    mon_left, mon_top, output_idx = _monitor_info_for_point(cx, cy)
                    # dxcam 需要相对于所在显示器左上角的坐标
                    self._dxcam_region = (
                        self.region[0] - mon_left,
                        self.region[1] - mon_top,
                        self.region[2] - mon_left,
                        self.region[3] - mon_top,
                    )
                    print(f"[capture] dxcam output_idx={output_idx}  "
                          f"monitor_origin=({mon_left},{mon_top})  "
                          f"dxcam_region={self._dxcam_region}")

                camera = dxcam.create(output_idx=output_idx, output_color="BGR")
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
            frame = self._impl.grab(region=self._dxcam_region)
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
        self._impl.start(region=self._dxcam_region, target_fps=self.target_fps)
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
