"""传送门策略：按地图配置偏好选择传送门类型。"""
from __future__ import annotations

from typing import List, Optional

from action.action_queue import Action, KeyPress, Move
from maps.room import RoomType
from vision.detector import Detection
from .base import Strategy, StrategyContext


PORTAL_CLASSES = {"portal", "portal_hidden", "portal_boss"}
PLAYER_CLASS = "player"


# 优先级：当前房间下一跳是 boss 时选 boss 门，否则按地图类型偏好
_DEFAULT_PREF = {
    RoomType.BOSS: ["portal_boss", "portal", "portal_hidden"],
    RoomType.HIDDEN: ["portal_hidden", "portal", "portal_boss"],
    RoomType.ELITE: ["portal", "portal_boss", "portal_hidden"],
    RoomType.NORMAL: ["portal", "portal_boss", "portal_hidden"],
}


class PortalStrategy(Strategy):
    name = "portal"

    def __init__(self, interact_key: str = "enter") -> None:
        self.interact_key = interact_key

    def _preferred_class(self, ctx: StrategyContext) -> List[str]:
        if ctx.map is None:
            return ["portal_boss", "portal", "portal_hidden"]
        nxt_id = ctx.map.next_room_towards_boss()
        target_room = ctx.map.rooms.get(nxt_id) if nxt_id is not None else None
        rtype = target_room.type if target_room else RoomType.NORMAL
        return _DEFAULT_PREF.get(rtype, _DEFAULT_PREF[RoomType.NORMAL])

    def _pick(self, portals: List[Detection], pref: List[str]) -> Optional[Detection]:
        for cls in pref:
            matches = [p for p in portals if p.class_name == cls]
            if matches:
                return max(matches, key=lambda d: d.confidence)
        return portals[0] if portals else None

    def decide(self, ctx: StrategyContext) -> List[Action]:
        portals = [d for d in ctx.detections if d.class_name in PORTAL_CLASSES]
        if not portals:
            return []

        target = self._pick(portals, self._preferred_class(ctx))
        if target is None:
            return []

        actions: List[Action] = []
        player = next((d for d in ctx.detections if d.class_name == PLAYER_CLASS), None)
        if player is not None:
            dx = target.center[0] - player.center[0]
            if abs(dx) > 30:
                direction = "right" if dx > 0 else "left"
                actions.append(Move(direction=direction,
                                    duration=min(0.6, abs(dx) / 400),
                                    tag="to_portal"))
        actions.append(KeyPress(key=self.interact_key, duration=0.06, tag="enter_portal"))
        return actions
