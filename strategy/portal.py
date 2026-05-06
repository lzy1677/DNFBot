"""传送门策略：墙侧驱动的助跑+穿门。

门墙侧判断：bbox 宽高比决定物理朝向，地图方向用于区左/右或上/下。
  - w > h → 扁宽门 → 上墙或下墙
  - w < h → 细高门 → 左墙或右墙

选门严格按 optimal_path。目标门不在画面内时，沿地图方向移动寻找；
超时后兜底进入任意可见门。每帧只发一个 action（staging 或 entry），
下一帧重新评估位置。
"""
from __future__ import annotations

from typing import List, Optional

from action.action_queue import Action, Move
from utils.logger import get_logger
from vision.detector import Detection
from .base import Strategy, StrategyContext


log = get_logger(__name__)

PORTAL_CLASSES = {"portal"}
PLAYER_CLASS   = "player"

_DEFAULT_PLAYER_W = 80
_DEFAULT_PLAYER_H = 120

# 助跑距离（以玩家尺寸为单位）
_RUNUP_W_UNITS = 3
_RUNUP_H_UNITS = 1

# 对齐判定阈值（像素）
_X_ALIGN = 30
_Y_ALIGN = 25

# 速度估算（px/s）
_SPEED_H = 400
_SPEED_V = 300

# 找不到目标门时，持续搜索超时（秒），之后兜底进入任意可见门
_SEEK_TIMEOUT = 5.0
# 寻找目标门时每一步的移动时长（秒），短步快评
_SEEK_STEP = 0.25


def _get_map_direction(ctx: StrategyContext) -> Optional[str]:
    """从 optimal_path 获取当前房间的期望行进方向。"""
    if not ctx.map:
        return None
    nxt = ctx.map.next_room_towards_boss()
    if nxt is None:
        return None
    d = ctx.map.direction_to(ctx.map.current_id, nxt)
    return d if d in ("left", "right", "up", "down") else None


def _get_wall_side(ctx: StrategyContext, portal: Detection) -> str:
    """判断传送门在哪面墙上（纯位置驱动，不依赖地图方向）。

    - w > h → 扁宽，上墙或下墙，按画面上下半区判断
    - w < h → 细高，左墙或右墙，按画面左右半区判断"""
    pw, ph = portal.wh

    if pw > ph:
        _, frame_h = ctx.frame_shape[1], ctx.frame_shape[0]
        return "down" if portal.center[1] > frame_h / 2 else "up"
    else:
        _, frame_w = ctx.frame_shape[1], ctx.frame_shape[0]
        return "right" if portal.center[0] > frame_w / 2 else "left"


class PortalStrategy(Strategy):
    """墙侧驱动的传送门策略。"""

    name = "portal"

    def __init__(self, step_duration: float = 0.4,
                 seek_timeout: float = _SEEK_TIMEOUT) -> None:
        self.step_duration = step_duration
        self.seek_timeout = seek_timeout
        self._timeout_logged = False

    # ---- 入口 ---------------------------------------------------------------
    def decide(self, ctx: StrategyContext) -> List[Action]:
        portals = [d for d in ctx.detections if d.class_name in PORTAL_CLASSES]

        # 有怪物/可破坏物 → 不处理传送门，交给 combat 接管
        if any(d.class_name in ("monster", "stone") for d in ctx.detections):
            return []

        expected_dir = _get_map_direction(ctx)

        # 画面内无传送门 → 沿地图方向寻找
        if not portals:
            return self._seek(expected_dir)

        player = next((d for d in ctx.detections if d.class_name == PLAYER_CLASS), None)
        if player is None:
            return self._seek(expected_dir)

        px, py = player.bottom_center
        pw, ph = player.wh if player.wh[0] > 0 else (_DEFAULT_PLAYER_W, _DEFAULT_PLAYER_H)

        # 寻找 optimal_path 指定的目标门
        target = self._pick_target(portals, ctx, expected_dir)

        if target is None:
            # 目标门不在画面中 → 搜索超时后兜底进入任意门
            if ctx.elapsed_in_state >= self.seek_timeout:
                if not self._timeout_logged:
                    log.info("[portal] 搜索超时 %.1fs，兜底进入任意可见门",
                             ctx.elapsed_in_state)
                    self._timeout_logged = True
                target = portals[0]
            else:
                return self._seek(expected_dir)
        else:
            self._timeout_logged = False

        wall = _get_wall_side(ctx, target)
        tx = target.center[0]
        ty = target.bottom_center[1]
        return self._approach(wall, px, py, pw, ph, tx, ty)

    # ---- 选门 ---------------------------------------------------------------
    @staticmethod
    def _pick_target(portals: List[Detection], ctx: StrategyContext,
                     expected_dir: Optional[str]) -> Optional[Detection]:
        """在可见门中选 optimal_path 方向匹配的。未匹配时返回 None。"""
        if expected_dir is None:
            # 无 optimal_path → 选最近的门兜底
            return portals[0]

        for p in portals:
            if _get_wall_side(ctx, p) == expected_dir:
                return p
        return None

    # ---- 寻找 ---------------------------------------------------------------
    @staticmethod
    def _seek(expected_dir: Optional[str]) -> List[Action]:
        """沿地图方向短步移动，寻找目标传送门。"""
        direction = expected_dir or "right"
        return [Move(direction=direction, duration=_SEEK_STEP, tag="seek_portal")]

    # ---- 接近（每帧一个 action）---------------------------------------------
    @staticmethod
    def _approach(wall: str, px: float, py: float,
                  pw: float, ph: float, tx: float, ty: float) -> List[Action]:
        """单帧单动作：到达助跑位则冲入，否则移动到助跑位。"""
        runup_w = _RUNUP_W_UNITS * pw
        runup_h = _RUNUP_H_UNITS * ph

        if wall == "right":
            stage_x, stage_y = tx - runup_w, ty
            entry_dir, entry_dur = "right", min(0.8, (runup_w + pw * 0.5) / _SPEED_H)
        elif wall == "left":
            stage_x, stage_y = tx + runup_w, ty
            entry_dir, entry_dur = "left", min(0.8, (runup_w + pw * 0.5) / _SPEED_H)
        elif wall == "up":
            stage_x, stage_y = tx, ty + runup_h
            entry_dir, entry_dur = "up", min(0.8, (runup_h + ph * 0.5) / _SPEED_V)
        else:  # "down"
            stage_x, stage_y = tx, ty - runup_h
            entry_dir, entry_dur = "down", min(0.8, (runup_h + ph * 0.5) / _SPEED_V)

        at_x = abs(px - stage_x) <= _X_ALIGN
        at_y = abs(py - stage_y) <= _Y_ALIGN

        if at_x and at_y:
            return [Move(direction=entry_dir, duration=entry_dur,
                        tag=f"portal_entry_{wall[0]}")]

        return [_make_move(px, py, stage_x, stage_y, tag=f"portal_stage_{wall[0]}")]


# ---- 工具 -------------------------------------------------------------------
def _make_move(px: float, py: float, tx: float, ty: float,
               tag: str) -> Move:
    """复合方向移动（水平+垂直同时）。"""
    dx = tx - px
    dy = ty - py

    h_dir: Optional[str] = None
    v_dir: Optional[str] = None

    if abs(dx) > _X_ALIGN:
        h_dir = "right" if dx > 0 else "left"
    if abs(dy) > _Y_ALIGN:
        v_dir = "down" if dy > 0 else "up"

    if h_dir and v_dir:
        direction = f"{h_dir},{v_dir}"
        dur = min(0.8, max(abs(dx) / _SPEED_H, abs(dy) / _SPEED_V))
    elif h_dir:
        direction = h_dir
        dur = min(0.8, abs(dx) / _SPEED_H)
    elif v_dir:
        direction = v_dir
        dur = min(0.6, abs(dy) / _SPEED_V)
    else:
        direction = "right"
        dur = 0.1

    return Move(direction=direction, duration=dur, tag=tag)
