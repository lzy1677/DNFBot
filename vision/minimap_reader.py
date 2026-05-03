"""小地图读取器：通过 HSV 颜色检测识别玩家当前房间。

流程：
  1. 按 screen_region 裁出搜索区域（右上角）
  2. 用房间色 HSV 找到所有已探索房间像素的 bounding box → 小地图内容边界
  3. 用玩家标记色 HSV 找质心 → 玩家在小地图内的像素坐标
  4. 归一化后与各房间 minimap_xy 比距离 → 最近房间 ID
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import cv2
import numpy as np

from utils.logger import get_logger


log = get_logger(__name__)


class MinimapReader:
    # 单次检测最小有效蓝色像素数（过少说明小地图不可见）
    _MIN_ROOM_PX  = 30
    # 玩家标记最小像素数（过少判为噪声）
    _MIN_PLAYER_PX = 5

    def __init__(
        self,
        screen_region: Tuple[float, float, float, float],
        room_hsv_lower: Tuple[int, int, int],
        room_hsv_upper: Tuple[int, int, int],
        player_hsv_lower: Tuple[int, int, int],
        player_hsv_upper: Tuple[int, int, int],
        room_positions: Dict[int, Tuple[float, float]],
    ) -> None:
        self._sr            = screen_region           # (x1,y1,x2,y2) 归一化
        self._room_lo       = np.array(room_hsv_lower,   dtype=np.uint8)
        self._room_hi       = np.array(room_hsv_upper,   dtype=np.uint8)
        self._player_lo     = np.array(player_hsv_lower, dtype=np.uint8)
        self._player_hi     = np.array(player_hsv_upper, dtype=np.uint8)
        self._room_positions = room_positions          # {room_id: (x_norm, y_norm)}

    # ---- 工厂 ----
    @classmethod
    def from_map(cls, game_map) -> Optional["MinimapReader"]:
        """从 BaseMap 构建；地图无小地图配置时返回 None。"""
        cfg = getattr(game_map, "minimap_cfg", {})
        pos = getattr(game_map, "room_minimap_xy", {})
        if not cfg or not pos:
            return None
        return cls(
            screen_region    = tuple(cfg["screen_region"]),
            room_hsv_lower   = tuple(cfg["room_hsv_lower"]),
            room_hsv_upper   = tuple(cfg["room_hsv_upper"]),
            player_hsv_lower = tuple(cfg["player_hsv_lower"]),
            player_hsv_upper = tuple(cfg["player_hsv_upper"]),
            room_positions   = pos,
        )

    # ---- 主接口 ----
    def detect(self, frame: np.ndarray) -> Optional[int]:
        """从帧中检测当前房间 ID；无法检测时返回 None。"""
        try:
            roi = self._crop_search_region(frame)
            if roi is None or roi.size == 0:
                return None

            mm, mm_w, mm_h = self._find_minimap(roi)
            if mm is None:
                return None

            player_pos = self._find_player(mm)
            if player_pos is None:
                return None

            px_n = player_pos[0] / mm_w
            py_n = player_pos[1] / mm_h
            room_id = self._nearest_room(px_n, py_n)
            log.debug("[minimap] 玩家归一化位置=(%.2f, %.2f) → room %s", px_n, py_n, room_id)
            return room_id

        except Exception as e:
            log.debug("[minimap] 检测异常: %s", e)
            return None

    # ---- 内部步骤 ----
    def _crop_search_region(self, frame: np.ndarray) -> Optional[np.ndarray]:
        h, w = frame.shape[:2]
        x1 = int(self._sr[0] * w)
        y1 = int(self._sr[1] * h)
        x2 = int(self._sr[2] * w)
        y2 = int(self._sr[3] * h)
        if x2 <= x1 or y2 <= y1:
            return None
        return frame[y1:y2, x1:x2]

    def _find_minimap(
        self, roi: np.ndarray
    ) -> Tuple[Optional[np.ndarray], int, int]:
        """在 ROI 中找房间蓝色像素的 bounding box，裁出小地图内容区。"""
        hsv  = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self._room_lo, self._room_hi)

        # 轻微膨胀把相邻房间连起来，使 bounding box 更稳定
        k    = np.ones((3, 3), np.uint8)
        mask = cv2.dilate(mask, k, iterations=2)

        pts = cv2.findNonZero(mask)
        if pts is None or len(pts) < self._MIN_ROOM_PX:
            return None, 0, 0

        x, y, w, h = cv2.boundingRect(pts)
        pad = 4
        x  = max(0, x - pad)
        y  = max(0, y - pad)
        w  = min(roi.shape[1] - x, w + 2 * pad)
        h  = min(roi.shape[0] - y, h + 2 * pad)
        return roi[y:y + h, x:x + w], w, h

    def _find_player(self, mm: np.ndarray) -> Optional[Tuple[int, int]]:
        """在小地图内容区找玩家标记质心，返回像素坐标。"""
        hsv  = cv2.cvtColor(mm, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self._player_lo, self._player_hi)
        M    = cv2.moments(mask)
        if M["m00"] < self._MIN_PLAYER_PX:
            return None
        return int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"])

    def _nearest_room(self, px: float, py: float) -> Optional[int]:
        """返回 minimap_xy 距离 (px, py) 最近的房间 ID。"""
        if not self._room_positions:
            return None
        return min(
            self._room_positions,
            key=lambda rid: (self._room_positions[rid][0] - px) ** 2
                          + (self._room_positions[rid][1] - py) ** 2,
        )
