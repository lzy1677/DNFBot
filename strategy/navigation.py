"""导航策略：按地图最优路径朝下一个房间移动。"""
from __future__ import annotations

from typing import List

from action.action_queue import Action, Move
from .base import Strategy, StrategyContext


class NavigationStrategy(Strategy):
    name = "navigation"

    def __init__(self, step_duration: float = 0.6) -> None:
        self.step_duration = step_duration

    def decide(self, ctx: StrategyContext) -> List[Action]:
        if ctx.map is None:
            return [Move(direction="right", duration=self.step_duration, tag="nav_default")]

        nxt = ctx.map.next_room_towards_boss()
        if nxt is None:
            return []

        direction = ctx.map.direction_to(ctx.map.current_id, nxt) or "right"
        return [Move(direction=direction, duration=self.step_duration, tag="nav")]
