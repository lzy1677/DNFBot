"""游戏状态枚举与状态机。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Set, Tuple


class GameState(Enum):
    IDLE = "idle"
    IN_TOWN = "in_town"
    ENTERING_DUNGEON = "entering_dungeon"
    IN_ROOM = "in_room"
    COMBAT = "combat"
    LOOTING = "looting"
    NAVIGATING = "navigating"
    PORTAL_SELECT = "portal_select"
    BOSS_ROOM = "boss_room"
    RESULT_SCREEN = "result_screen"
    LOADING = "loading"
    UNKNOWN = "unknown"


# 合法状态转移（宽松：UNKNOWN/LOADING 可进出任何状态）
_TRANSITIONS: Dict[GameState, Set[GameState]] = {
    GameState.IDLE: {GameState.IN_TOWN, GameState.LOADING},
    GameState.IN_TOWN: {GameState.ENTERING_DUNGEON, GameState.LOADING},
    GameState.ENTERING_DUNGEON: {GameState.IN_ROOM, GameState.COMBAT, GameState.LOADING},
    GameState.IN_ROOM: {
        GameState.COMBAT, GameState.LOOTING, GameState.NAVIGATING,
        GameState.PORTAL_SELECT, GameState.LOADING,
    },
    GameState.COMBAT: {GameState.IN_ROOM, GameState.LOOTING, GameState.LOADING},
    GameState.LOOTING: {GameState.IN_ROOM, GameState.NAVIGATING, GameState.LOADING},
    GameState.NAVIGATING: {
        GameState.IN_ROOM, GameState.COMBAT, GameState.PORTAL_SELECT,
        GameState.BOSS_ROOM, GameState.LOADING,
    },
    GameState.PORTAL_SELECT: {GameState.LOADING, GameState.IN_ROOM, GameState.BOSS_ROOM},
    GameState.BOSS_ROOM: {GameState.COMBAT, GameState.RESULT_SCREEN, GameState.LOADING},
    GameState.RESULT_SCREEN: {GameState.IN_TOWN, GameState.LOADING, GameState.ENTERING_DUNGEON},
    GameState.LOADING: set(GameState),
    GameState.UNKNOWN: set(GameState),
}


@dataclass
class StateMachine:
    current: GameState = GameState.IDLE
    previous: GameState = GameState.IDLE
    entered_at: float = field(default_factory=time.perf_counter)

    def can_transition(self, target: GameState) -> bool:
        if target == self.current:
            return True
        allowed = _TRANSITIONS.get(self.current, set())
        return target in allowed or self.current == GameState.UNKNOWN

    def transition(self, target: GameState, *, force: bool = False) -> bool:
        if target == self.current:
            return False
        if not force and not self.can_transition(target):
            return False
        self.previous = self.current
        self.current = target
        self.entered_at = time.perf_counter()
        return True

    def time_in_state(self) -> float:
        return time.perf_counter() - self.entered_at

    def is_one_of(self, *states: GameState) -> bool:
        return self.current in states
