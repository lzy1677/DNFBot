"""传送门策略：带助跑的传送门进入逻辑。

水平传送门：先跑到传送门对面 3 个角色宽度处（助跑位），再冲入。
垂直传送门：先后退 1 个角色高度，再冲入。
无传送门可见时回退为导航移动。
"""
from __future__ import annotations

from typing import List, Optional

from action.action_queue import Action, Move
from vision.detector import Detection
from .base import Strategy, StrategyContext


PORTAL_CLASSES = {"portal"}
PLAYER_CLASS   = "player"

# 找不到玩家时的尺寸回退值（像素，按 1280×720 估算）
_DEFAULT_PLAYER_W = 80
_DEFAULT_PLAYER_H = 120

# 水平传送门：以玩家宽为单位的助跑距离
_RUNUP_WIDTHS = 3
# 进入判定：水平/垂直阈值
_X_ALIGN = 30
_Y_ALIGN = 25
# 水平/垂直速度估算（px/s），用于换算 duration
_SPEED_H = 400
_SPEED_V = 300


class PortalStrategy(Strategy):
    name = "portal"

    def __init__(self, step_duration: float = 0.4) -> None:
        self.step_duration = step_duration

    def decide(self, ctx: StrategyContext) -> List[Action]:
        portals = [d for d in ctx.detections if d.class_name in PORTAL_CLASSES]

        # 无传送门可见：按地图方向前进
        if not portals:
            if ctx.map:
                nxt = ctx.map.next_room_towards_boss()
                direction = (ctx.map.direction_to(ctx.map.current_id, nxt)
                             if nxt is not None else None) or "right"
            else:
                direction = "right"
            return [Move(direction=direction, duration=self.step_duration,
                         tag="nav_to_portal")]

        player = next((d for d in ctx.detections if d.class_name == PLAYER_CLASS), None)
        if player is None:
            # 看不到玩家，继续朝地图方向前进
            return [Move(direction="right", duration=self.step_duration, tag="nav_blind")]

        px, py = player.bottom_center
        pw, ph  = player.wh if player.wh[0] > 0 else (_DEFAULT_PLAYER_W, _DEFAULT_PLAYER_H)

        # 选最近传送门
        target = min(portals, key=lambda d: abs(d.center[0] - px))
        tx, ty  = target.center
        dx = tx - px
        dy = ty - py

        # 判断以水平还是垂直方向为主
        if abs(dx) >= abs(dy) * 0.7:
            return self._approach_horizontal(dx, dy, px, py, pw, ph)
        else:
            return self._approach_vertical(dx, dy, px, py, pw, ph)

    # ------------------------------------------------------------------ #
    def _approach_horizontal(self, dx, dy, px, py, pw, ph) -> List[Action]:
        """
        水平传送门进入逻辑：
          - 传送门在左（dx<0）：助跑位 = portal_x + 3*pw，然后向左冲入
          - 传送门在右（dx>0）：助跑位 = portal_x - 3*pw，然后向右冲入
        """
        runup = _RUNUP_WIDTHS * pw

        if dx < 0:  # 传送门在左侧
            # portal_x = px + dx，助跑位在传送门右侧 runup 处
            portal_x   = px + dx
            stage_x    = portal_x + runup          # 目标助跑位（屏幕 X）
            stage_dx   = stage_x - px              # 需要往右移的量（正=右，负=左）
            entry_dir  = "left"
        else:        # 传送门在右侧
            portal_x   = px + dx
            stage_x    = portal_x - runup
            stage_dx   = stage_x - px
            entry_dir  = "right"

        actions: List[Action] = []

        # Step 1：移动到助跑位（同时修正 Y 对齐）
        need_stage = abs(stage_dx) > _X_ALIGN
        need_y     = abs(dy) > _Y_ALIGN

        if need_stage or need_y:
            if need_stage and need_y:
                h_part = "right" if stage_dx > 0 else "left"
                v_part = "down"  if dy       > 0 else "up"
                direction = f"{h_part},{v_part}"
                dur = min(0.8, max(abs(stage_dx) / _SPEED_H,
                                   abs(dy)       / _SPEED_V))
            elif need_stage:
                direction = "right" if stage_dx > 0 else "left"
                dur = min(0.8, abs(stage_dx) / _SPEED_H)
            else:
                direction = "down" if dy > 0 else "up"
                dur = min(0.4, abs(dy) / _SPEED_V)
            actions.append(Move(direction=direction, duration=dur, tag="portal_stage"))

        # Step 2：助跑冲入（距离 = runup + 一点余量确保穿过传送门）
        entry_dur = min(0.8, (runup + pw * 0.5) / _SPEED_H)
        actions.append(Move(direction=entry_dir, duration=entry_dur, tag="portal_entry"))
        return actions

    def _approach_vertical(self, dx, dy, px, py, pw, ph) -> List[Action]:
        """
        垂直传送门进入逻辑：
          - 传送门在下方（dy>0）：先向上退 1 个角色高度，再向下冲入
          - 传送门在上方（dy<0）：先向下退 1 个角色高度，再向上冲入
        """
        actions: List[Action] = []

        # 先修正 X 对齐
        if abs(dx) > _X_ALIGN:
            x_dir = "right" if dx > 0 else "left"
            actions.append(Move(direction=x_dir,
                                duration=min(0.5, abs(dx) / _SPEED_H),
                                tag="portal_align_x"))

        if dy > 0:   # 传送门在下方
            actions.append(Move(direction="up",
                                duration=min(0.4, ph / _SPEED_V),
                                tag="portal_stage_up"))
            entry_dir = "down"
        else:        # 传送门在上方
            actions.append(Move(direction="down",
                                duration=min(0.4, ph / _SPEED_V),
                                tag="portal_stage_down"))
            entry_dir = "up"

        entry_dur = min(0.8, (ph + abs(dy)) / _SPEED_V)
        actions.append(Move(direction=entry_dir, duration=entry_dur, tag="portal_entry"))
        return actions
