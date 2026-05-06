"""异常恢复策略：处理结算画面 / 卡死状态。

结算画面优先级：stone → item → page_down（8s 超时跳过拾取）
- 长时间 UNKNOWN 时尝试小范围抖动解卡
"""
from __future__ import annotations

from typing import List, Optional

from action.action_queue import Action, KeyPress, Move, Wait
from .base import Strategy, StrategyContext


UI_CLASSES = {"ui_button"}
ITEM_CLASSES = {"item", "gold"}
STONE_CLASSES = {"stone"}
PLAYER_CLASS = "player"

_SPEED_H = 500
_SPEED_V = 400


class RecoveryStrategy(Strategy):
    """结算画面自动再次挑战；长时间 UNKNOWN 时尝试小范围抖动解卡。"""
    name = "recovery"

    def __init__(self, stuck_seconds: float = 8.0,
                 retry_key: str = "page_down") -> None:
        self.stuck_seconds = stuck_seconds
        self.retry_key = retry_key

    def decide(self, ctx: StrategyContext) -> List[Action]:
        ui = [d for d in ctx.detections if d.class_name in UI_CLASSES]
        if ui:
            if ctx.elapsed_in_state >= 8.0:
                # 超时放弃拾取/攻击，直接翻牌
                return [
                    KeyPress(key=self.retry_key, duration=0.08, tag="retry"),
                    Wait(seconds=0.3),
                ]

            # 优先攻击 stone
            stones = [d for d in ctx.detections if d.class_name in STONE_CLASSES]
            if stones:
                return self._attack_stone(stones, ctx)

            # 其次拾取 item
            items = [d for d in ctx.detections if d.class_name in ITEM_CLASSES]
            if items:
                return self._loot_first(items, ctx)

            # 全部清理完毕 → 翻牌
            return [
                KeyPress(key=self.retry_key, duration=0.08, tag="retry"),
                Wait(seconds=0.3),
            ]

        # 疑似卡死（UNKNOWN 状态停留太久）
        if ctx.elapsed_in_state >= self.stuck_seconds:
            return [
                Move(direction="right", duration=0.15, tag="unstick_r"),
                Move(direction="left",  duration=0.15, tag="unstick_l"),
                KeyPress(key="c",       duration=0.04, tag="unstick_jump"),
            ]

        return []

    # ---- stone 攻击 -----------------------------------------------------------
    def _attack_stone(self, stones, ctx: StrategyContext) -> List[Action]:
        player = next((d for d in ctx.detections if d.class_name == PLAYER_CLASS), None)
        if player is None:
            attack_key = ctx.character.keys.get("attack", "x") if ctx.character else "x"
            return [KeyPress(key=attack_key, duration=0.04, tag="rs_stone_blind")]

        px, py = player.center
        nearest = min(stones, key=lambda d:
                      abs(d.center[0] - px) + abs(d.center[1] - py) * 0.5)
        dx = nearest.center[0] - px
        dy = nearest.center[1] - py
        direction = "right" if dx >= 0 else "left"
        y_direction = "down" if dy > 0 else ("up" if dy < 0 else "")

        # 在范围内 → 面向 + 技能/普攻
        if abs(dx) <= 100 and abs(dy) <= 100:
            actions: list = [Move(direction=direction, duration=0.02, tag="rs_face_stone")]
            if ctx.character:
                for sn in ("skill_1", "skill_2"):
                    seq = ctx.character.use_skill(sn)
                    if seq:
                        return actions + seq + [Wait(seconds=0.4)]
            attack_key = ctx.character.keys.get("attack", "x") if ctx.character else "x"
            return actions + [KeyPress(key=attack_key, duration=0.04, tag="rs_stone_attack")]

        # 靠近 stone
        if abs(dx) > 100 and y_direction and abs(dy) > 100:
            direction = f"{direction},{y_direction}"
        elif y_direction and abs(dy) > 100:
            direction = y_direction
        dur = min(0.4, max(abs(dx) / _SPEED_H, abs(dy) / _SPEED_V))
        return [Move(direction=direction, duration=dur, tag="rs_approach_stone")]

    def _loot_first(self, items, ctx: StrategyContext) -> List[Action]:
        pickup = self.retry_key  # fallback
        if ctx.character and "pickup" in ctx.character.keys:
            pickup = ctx.character.keys["pickup"]

        player = next((d for d in ctx.detections if d.class_name == PLAYER_CLASS), None)
        if player is None:
            return [KeyPress(key=pickup, duration=0.05, tag="rs_pickup_blind")]

        px, py = player.bottom_center
        nearest = min(items, key=lambda d:
                      (d.bottom_center[0] - px) ** 2 + (d.bottom_center[1] - py) ** 2)
        ix, iy = nearest.bottom_center

        dx = ix - px
        dy = iy - py
        dist = (dx ** 2 + dy ** 2) ** 0.5

        if dist <= 40:
            return [KeyPress(key=pickup, duration=0.05, tag="rs_pickup")]

        return [self._make_move(dx, dy)]

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

        return Move(direction=direction, duration=dur, tag="rs_loot_move")
