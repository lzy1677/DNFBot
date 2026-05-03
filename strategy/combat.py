"""战斗策略：根据怪群与玩家位置，调用职业攻击序列。"""
from __future__ import annotations

from typing import List

from action.action_queue import Action
from classes.base_class import CombatContext
from .base import Strategy, StrategyContext


MONSTER_CLASSES = {"monster", "stone", "elite", "boss"}
BOSS_CLASSES = {"boss"}
PLAYER_CLASS = "player"


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
