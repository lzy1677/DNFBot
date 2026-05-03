"""狂战士：近战职业，追求突进 + 大招打 boss。"""
from __future__ import annotations

from typing import List

from action.action_queue import Action, KeyPress, Move, Wait
from .base_class import BaseClass, CombatContext, register_class


@register_class("berserker")
class Berserker(BaseClass):
    # 垂直对齐阈值（像素）：Y 差超过此值先调整行
    _Y_THRESHOLD = 40

    def get_attack_sequence(self, ctx: CombatContext) -> List[Action]:
        actions: List[Action] = []

        need_x = ctx.distance_px > 120
        need_y = ctx.distance_y_px > self._Y_THRESHOLD and ctx.approach_y_direction

        if need_x and need_y:
            # 斜向同时靠近（同时按两个方向键）
            compound  = f"{ctx.approach_direction},{ctx.approach_y_direction}"
            dur_x     = min(0.6, ctx.distance_px   / 400)
            dur_y     = min(0.4, ctx.distance_y_px / 300)
            actions  += [Move(direction=compound, duration=max(dur_x, dur_y),
                              tag="approach_xy")]
        elif need_x:
            actions += self.approach(ctx.approach_direction,
                                     duration=min(0.6, ctx.distance_px / 400))
        elif need_y:
            actions += self.approach(ctx.approach_y_direction,
                                     duration=min(0.4, ctx.distance_y_px / 300))

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
