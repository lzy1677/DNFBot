"""拾取策略：向最近物品移动并按拾取键。"""
from __future__ import annotations

from typing import List

from action.action_queue import Action, KeyPress, Move
from .base import Strategy, StrategyContext


ITEM_CLASSES = {"item", "gold"}
PLAYER_CLASS = "player"


class LootStrategy(Strategy):
    name = "loot"

    def __init__(self, pickup_key: str = "z", reach_px: int = 40) -> None:
        self.pickup_key = pickup_key
        self.reach_px = reach_px

    def decide(self, ctx: StrategyContext) -> List[Action]:
        items = [d for d in ctx.detections if d.class_name in ITEM_CLASSES]
        if not items:
            return []

        # 用职业配置里的 pickup 键（若有）
        pickup = self.pickup_key
        if ctx.character and "pickup" in ctx.character.keys:
            pickup = ctx.character.keys["pickup"]

        player = next((d for d in ctx.detections if d.class_name == PLAYER_CLASS), None)
        if player is None:
            # 看不到自己就原地拾取一下
            return [KeyPress(key=pickup, duration=0.05, tag="pickup_blind")]

        px, py = player.center
        nearest = min(items, key=lambda d: (d.center[0] - px) ** 2 + (d.center[1] - py) ** 2)
        dx = nearest.center[0] - px
        dy = nearest.center[1] - py

        actions: List[Action] = []
        if abs(dx) > self.reach_px:
            direction = "right" if dx > 0 else "left"
            duration = min(0.5, abs(dx) / 500)
            actions.append(Move(direction=direction, duration=duration, tag="loot_move_x"))
        if abs(dy) > self.reach_px:
            direction = "down" if dy > 0 else "up"
            duration = min(0.4, abs(dy) / 400)
            actions.append(Move(direction=direction, duration=duration, tag="loot_move_y"))

        actions.append(KeyPress(key=pickup, duration=0.05, tag="pickup"))
        return actions
