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
        self._detour_phase: int = 0   # 0=直行, 1=绕行1, 2=绕行2

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
            return self._detour_move(dx, dy)

        # 正常接近
        return [self._make_move(dx, dy)]

    def _detour_move(self, dx: float, dy: float) -> List[Action]:
        """绕行：先退后 + 横移创造空间，再从侧面斜向接近。

        Phase 1 反向远离物品（避免直冲障碍物），
        Phase 2 从侧面斜向接近物品。
        斜向移动解决纯横移无法越过不规则突起的问题。
        """
        vertical_primary = abs(dy) > abs(dx)
        h_to = "right" if dx > 0 else "left"
        v_to = "down" if dy > 0 else "up"
        h_away = "left" if dx > 0 else "right"
        v_away = "up" if dy > 0 else "down"

        if self._detour_phase == 0:
            self._detour_phase = 1
            if vertical_primary:
                # 横移方向：dx 模糊时默认向右（避开左侧墙体）
                if abs(dx) < 15:
                    h_dodge = "right"
                else:
                    h_dodge = "right" if dx > 0 else "left"
                d = f"{h_dodge},{v_away}"   # 横移 + 后退
            else:
                if abs(dy) < 15:
                    v_dodge = "down"
                else:
                    v_dodge = "down" if dy > 0 else "up"
                d = f"{h_away},{v_dodge}"   # 后退 + 纵移
            return [Move(direction=d, duration=0.5, tag="loot_detour1")]

        if self._detour_phase == 1:
            self._detour_phase = 2
            if vertical_primary:
                h_dodge = "left" if dx > 0 else "right"
                d = f"{h_dodge},{v_to}"     # 反向横移 + 前进
            else:
                v_dodge = "up" if dy > 0 else "down"
                d = f"{h_to},{v_dodge}"     # 前进 + 反向纵移
            return [Move(direction=d, duration=0.5, tag="loot_detour2")]

        # 两次绕行都失败 → 放弃此物品
        self._reset_stuck()
        return []

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
