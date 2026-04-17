"""狂战士：近战职业，追求突进 + 大招打 boss。"""
from __future__ import annotations

from typing import List

from action.action_queue import Action, KeyPress, Move, Wait
from .base_class import BaseClass, CombatContext, register_class


@register_class("berserker")
class Berserker(BaseClass):
    def get_attack_sequence(self, ctx: CombatContext) -> List[Action]:
        actions: List[Action] = []

        # 先贴脸
        if ctx.distance_px > 120:
            actions += self.approach(ctx.approach_direction,
                                     duration=min(0.6, ctx.distance_px / 400))

        # Boss 优先大招
        if ctx.boss_present:
            for name in ("awakening", "skill_3", "skill_2"):
                seq = self.use_skill(name)
                if seq:
                    return actions + seq + [Wait(seconds=0.2)]

        # 普通战斗：就绪技能按优先级
        best = self.skills.highest_priority_ready()
        if best is not None and best.priority >= 1:
            actions += self.use_skill(best.name)
            return actions

        # 否则 A 怪
        actions += self.attack()
        return actions
