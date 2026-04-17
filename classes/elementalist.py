"""元素师：远程法师，保持距离输出。"""
from __future__ import annotations

from typing import List

from action.action_queue import Action, Wait
from .base_class import BaseClass, CombatContext, register_class


@register_class("elementalist")
class Elementalist(BaseClass):
    def get_attack_sequence(self, ctx: CombatContext) -> List[Action]:
        actions: List[Action] = []

        # 保持中等距离：太近就后撤
        if ctx.distance_px < 180 and ctx.player_box is not None:
            retreat = "left" if ctx.approach_direction == "right" else "right"
            actions += self.approach(retreat, duration=0.2)

        if ctx.boss_present:
            for name in ("awakening", "skill_3", "skill_2", "skill_1"):
                seq = self.use_skill(name)
                if seq:
                    return actions + seq + [Wait(seconds=0.15)]

        best = self.skills.highest_priority_ready()
        if best is not None:
            actions += self.use_skill(best.name)
            return actions

        actions += self.attack()
        return actions
