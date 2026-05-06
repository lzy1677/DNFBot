"""游戏状态枚举与状态机。

状态分为两类：
  检测驱动（YOLO + 启发式自动推断）：
    IN_ROOM, COMBAT, LOOTING, NAVIGATING, PORTAL, BOSS_ROOM, RESULT_SCREEN, LOADING, UNKNOWN
  动作驱动（Bot 在执行动作序列时直接设置）：
    IDLE, IN_TOWN, ENTERING_DUNGEON
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Set


class GameState(Enum):
    IDLE = "idle"
    IN_TOWN = "in_town"
    ENTERING_DUNGEON = "entering_dungeon"
    LOADING = "loading"
    IN_ROOM = "in_room"
    COMBAT = "combat"
    LOOTING = "looting"
    NAVIGATING = "navigating"
    PORTAL = "portal"
    BOSS_ROOM = "boss_room"
    RESULT_SCREEN = "result_screen"
    UNKNOWN = "unknown"


_TRANSITIONS: Dict[GameState, Set[GameState]] = {
    # 动作驱动：启动 → 城镇 → 进本
    GameState.IDLE:              {GameState.IN_TOWN},
    GameState.IN_TOWN:           {GameState.ENTERING_DUNGEON},
    GameState.ENTERING_DUNGEON:  {GameState.LOADING, GameState.IN_ROOM},

    # 加载中 → 任意状态（启发式检测可能误判，保持开放避免卡死）
    GameState.LOADING:           set(GameState),

    # 房间内评估 → 战斗 / 拾取 / 传送门 / 前进 / Boss / 结算
    GameState.IN_ROOM: {
        GameState.COMBAT, GameState.LOOTING, GameState.PORTAL,
        GameState.NAVIGATING, GameState.BOSS_ROOM, GameState.RESULT_SCREEN,
    },

    # 战斗结束 → 空房 / 拾取 / 传送门 / 前进 / Boss / 结算
    GameState.COMBAT: {
        GameState.IN_ROOM, GameState.LOOTING, GameState.PORTAL,
        GameState.NAVIGATING, GameState.BOSS_ROOM, GameState.RESULT_SCREEN,
    },

    # 拾取完毕 → 空房 / 传送门 / 前进 / 拾取中被偷袭 / 结算
    GameState.LOOTING: {
        GameState.IN_ROOM, GameState.PORTAL, GameState.NAVIGATING,
        GameState.COMBAT, GameState.RESULT_SCREEN,
    },

    # 前进探索 → 遇怪 / 见物 / 见门 / 到新区域 / Boss / 结算
    GameState.NAVIGATING: {
        GameState.COMBAT, GameState.LOOTING, GameState.PORTAL,
        GameState.IN_ROOM, GameState.BOSS_ROOM, GameState.RESULT_SCREEN,
    },

    # 传送门 → 加载 / 穿门失败 / 门附近有怪 / 发现掉落物
    GameState.PORTAL: {
        GameState.LOADING, GameState.IN_ROOM, GameState.COMBAT, GameState.LOOTING,
    },

    # Boss 房 → 战斗 / 拾取 / 通关结算
    GameState.BOSS_ROOM: {
        GameState.COMBAT, GameState.LOOTING, GameState.RESULT_SCREEN,
    },

    # 结算画面 → 加载（重新挑战成功）/ 回城（疲劳耗尽）
    GameState.RESULT_SCREEN: {
        GameState.LOADING, GameState.IN_TOWN, GameState.ENTERING_DUNGEON,
    },

    # UNKNOWN 可进出任意状态（恢复用）
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
