"""拾取策略：移动到物品上方再按拾取键。

- 用 bottom_center（脚底/地面位置）做距离判断，比几何中心更准
- 距离 > reach_px → 只移动不拾取（复合方向，同时修正 X 和 Y）
- 距离 ≤ reach_px → 只按拾取键（下一帧物品还在就再按）
- 卡住检测：同位置连续接近无进展 → 自动绕行，绕行失败则放弃
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from action.action_queue import Action, KeyPress, Move
from .base import Strategy, StrategyContext


ITEM_CLASSES = {"item", "gold"}
PLAYER_CLASS = "player"

# 移动速度估算（px/s）
_SPEED_H = 500
_SPEED_V = 400

# 卡住检测参数
_STUCK_THRESHOLD = 5       # 连续 N 次同位置无进展 → 绕行
_STUCK_POS_THRESH = 30     # 物品位置变化小于此值算"没动"（px）


class LootStrategy(Strategy):
    name = "loot"

    def __init__(self, pickup_key: str = "z", reach_px: int = 40) -> None:
        self.pickup_key = pickup_key
        self.reach_px = reach_px
        self._last_item_pos: Optional[Tuple[float, float]] = None
        self._stuck_count: int = 0
        self._detour_phase: int = 0   # 0=直行, 1/2/3=绕行三步, 4+=重新寻路

    def decide(self, ctx: StrategyContext) -> List[Action]:
        items = [d for d in ctx.detections if d.class_name in ITEM_CLASSES]
        if not items:
            self._reset_stuck()
            return []

        pickup = self.pickup_key
        if ctx.character and "pickup" in ctx.character.keys:
            pickup = ctx.character.keys["pickup"]

        player = next((d for d in ctx.detections if d.class_name == PLAYER_CLASS), None)
        if player is None:
            self._reset_stuck()
            return [KeyPress(key=pickup, duration=0.05, tag="pickup_blind")]

        # 用脚底位置（地面参考点）
        px, py = player.bottom_center
        nearest = min(items, key=lambda d:
                      (d.bottom_center[0] - px) ** 2 + (d.bottom_center[1] - py) ** 2)
        ix, iy = nearest.bottom_center
        iy += 15 # 让人物适当移动到物品的下面一点位置，防止卡在边缘

        dx = ix - px
        dy = iy - py
        dist = (dx ** 2 + dy ** 2) ** 0.5

        # 已在物品旁边 → 只拾取
        if dist <= self.reach_px:
            self._reset_stuck()
            return [KeyPress(key=pickup, duration=0.05, tag="pickup")]

        # ---- 卡住检测 ----
        item_pos = (ix, iy)
        if self._last_item_pos is not None:
            lx, ly = self._last_item_pos
            if abs(ix - lx) < _STUCK_POS_THRESH and abs(iy - ly) < _STUCK_POS_THRESH:
                self._stuck_count += 1
            else:
                # 位置有变化 → 在前进，重置计数（逐渐衰减避免抖动）
                self._stuck_count = max(0, self._stuck_count - 2)
        self._last_item_pos = item_pos

        # 连续卡住 → 绕行
        if self._stuck_count >= _STUCK_THRESHOLD:
            return self._detour_move(dx, dy, px, ctx.frame_shape[1])

        # 正常接近
        return [self._make_move(dx, dy)]

    def _detour_move(self, dx: float, dy: float, px: float, frame_width: int) -> List[Action]:
        """绕行：判断人物在画面左半/右半，向远离墙壁方向绕开障碍物后重新寻路。

        左半 → 被左侧墙壁突起卡住 → 向右绕行
        右半 → 被右侧墙壁突起卡住 → 向左绕行
        """
        on_left = px < frame_width / 2
        h_escape = "right" if on_left else "left"

        if self._detour_phase == 0:
            self._detour_phase = 1
            v_away = "down" if dy < 0 else "up"
            return [Move(direction=v_away, duration=0.5, tag="loot_detour1")]

        if self._detour_phase == 1:
            self._detour_phase = 2
            return [Move(direction=h_escape, duration=1.0, tag="loot_detour2")]

        if self._detour_phase == 2:
            self._detour_phase = 3
            v_toward = "up" if dy < 0 else "down"
            return [Move(direction=v_toward, duration=1.0, tag="loot_detour3")]

        # 绕行完成，正常寻路
        self._reset_stuck()
        return [self._make_move(dx, dy)]

    def _reset_stuck(self) -> None:
        self._last_item_pos = None
        self._stuck_count = 0
        self._detour_phase = 0

    @staticmethod
    def _make_move(dx: float, dy: float) -> Move:
        h_dir: Optional[str] = None
        v_dir: Optional[str] = None

        if abs(dx) > 2:
            h_dir = "right" if dx > 0 else "left"
        if abs(dy) > 2:
            v_dir = "down" if dy > 0 else "up"

        if h_dir and v_dir:
            direction = f"{h_dir},{v_dir}"
            dur = min(0.6, max(abs(dx) / _SPEED_H, abs(dy) / _SPEED_V))
        elif h_dir:
            direction = h_dir
            dur = min(0.5, abs(dx) / _SPEED_H)
        elif v_dir:
            direction = v_dir
            dur = min(0.4, abs(dy) / _SPEED_V)
        else:
            direction = "right"
            dur = 0.05

        return Move(direction=direction, duration=dur, tag="loot_move")
