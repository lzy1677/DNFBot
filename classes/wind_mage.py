"""风法师：近战职业，利用风系技能衔接普通攻击。"""
from __future__ import annotations

from typing import List

from action.action_queue import Action, Move, Wait
from .base_class import BaseClass, CombatContext, register_class


@register_class("wind_mage")
class WindMage(BaseClass):

    def get_attack_sequence(self, ctx: CombatContext) -> List[Action]:
        need_x = ctx.distance_px > self.distance_x
        need_y = ctx.distance_y_px > self.distance_y and ctx.approach_y_direction

        # 超出攻击范围 → 只靠近不攻击
        if need_x and need_y:
            compound = f"{ctx.approach_direction},{ctx.approach_y_direction}"
            dur_x = min(0.6, ctx.distance_px / 400)
            dur_y = min(0.4, ctx.distance_y_px / 300)
            return [Move(direction=compound, duration=max(dur_x, dur_y),
                        tag="approach_xy")]
        if need_x:
            return self.approach(ctx.approach_direction,
                                duration=min(0.6, ctx.distance_px / 400))
        if need_y:
            return self.approach(ctx.approach_y_direction,
                                duration=min(0.4, ctx.distance_y_px / 300))

        # 在攻击范围内 → 先面向目标
        actions: List[Action] = self.face_target(ctx.approach_direction)

        if ctx.boss_present:
            for name in ("awakening", "skill_12", "skill_3", "skill_10"):
                seq = self.use_skill(name)
                if seq:
                    return actions + seq + [Wait(seconds=0.4)]

        # 普通战斗：冷却最短的技能优先
        best = self.skills.shortest_cooldown_ready()
        if best is not None and best.priority >= 1:
            actions += self.use_skill(best.name)
            return actions + [Wait(seconds=0.5)]

        actions += self.attack()
        return actions
