"""战斗策略：根据怪群与玩家位置，调用职业攻击序列。

Stone 特殊处理：100×100 范围内用 a/s 技能攻击，无技能则普攻 X。
"""
from __future__ import annotations

from typing import List

from action.action_queue import Action, KeyPress, Move, Wait
from classes.base_class import CombatContext
from .base import Strategy, StrategyContext


MONSTER_CLASSES = {"monster", "stone", "elite", "boss"}
BOSS_CLASSES = {"boss"}
STONE_CLASSES = {"stone"}
PLAYER_CLASS = "player"

# Stone 专用距离阈值
_STONE_DIST_X = 300
_STONE_DIST_Y = 100
# 移动速度估算（px/s）
_SPEED_H = 400
_SPEED_V = 300


class CombatStrategy(Strategy):
    name = "combat"

    def decide(self, ctx: StrategyContext) -> List[Action]:
        if ctx.character is None:
            return []

        monsters = [d for d in ctx.detections if d.class_name in MONSTER_CLASSES]
        if not monsters:
            return []

        player = next((d for d in ctx.detections if d.class_name == PLAYER_CLASS), None)
        boss_present = any(d.class_name in BOSS_CLASSES for d in monsters)

        # 选最近的怪作为主目标
        if player is not None:
            px, py = player.center
            target = min(monsters, key=lambda d: abs(d.center[0] - px) + abs(d.center[1] - py) * 0.5)
            dx = target.center[0] - px
            dy = target.center[1] - py
            direction   = "right" if dx >= 0 else "left"
            y_direction = "down"  if dy >  0 else ("up" if dy < 0 else "")
            player_box  = player.bbox
        else:
            target      = monsters[0]
            dx, dy      = 300, 0
            direction   = "right"
            y_direction = ""
            player_box  = None

        # Stone 特殊处理：50×50 范围内只普攻，范围外靠近
        if target.class_name in STONE_CLASSES:
            return self._handle_stone(abs(dx), abs(dy), direction, y_direction, ctx)

        combat_ctx = CombatContext(
            monster_boxes=[m.bbox for m in monsters],
            player_box=player_box,
            boss_present=boss_present,
            approach_direction=direction,
            distance_px=abs(dx),
            approach_y_direction=y_direction,
            distance_y_px=abs(dy),
        )
        return ctx.character.get_attack_sequence(combat_ctx)

    @staticmethod
    def _handle_stone(dist_x: int, dist_y: int,
                      direction: str, y_direction: str,
                      ctx: StrategyContext) -> List[Action]:
        need_x = dist_x > _STONE_DIST_X
        need_y = dist_y > _STONE_DIST_Y and y_direction

        if need_x and need_y:
            compound = f"{direction},{y_direction}"
            dur = min(0.3, max(dist_x / _SPEED_H, dist_y / _SPEED_V))
            return [Move(direction=compound, duration=dur, tag="stone_approach_xy")]
        if need_x:
            dur = min(0.3, dist_x / _SPEED_H)
            return [Move(direction=direction, duration=dur, tag="stone_approach_x")]
        if need_y:
            dur = min(0.3, dist_y / _SPEED_V)
            return [Move(direction=y_direction, duration=dur, tag="stone_approach_y")]

        # 在范围内 → 面向 + 技能优先（a/s），无技能则普攻
        actions: list = [Move(direction=direction, duration=0.02, tag="face_stone")]
        for sn in ("skill_1", "skill_2"):
            seq = ctx.character.use_skill(sn)
            if seq:
                return actions + seq + [Wait(seconds=0.4)]
        attack_key = ctx.character.keys.get("attack", "x")
        return actions + [KeyPress(key=attack_key, duration=0.04, tag="stone_attack")]
