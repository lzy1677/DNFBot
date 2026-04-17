"""从 YOLO 检测结果推断 GameState。

规则（按优先级从高到低）：
  1. 若检测到 RESULT_SCREEN 相关 UI（如 retry_button） → RESULT_SCREEN
  2. 若检测到 portal_classes 且数量>=2 → PORTAL_SELECT
  3. 若检测到 monster_classes → COMBAT / BOSS_ROOM（有 boss 类）
  4. 若检测到 item_classes 且无怪 → LOOTING
  5. 检测到 clear_flag 且仅剩物品 → NAVIGATING/IN_ROOM
  6. 其他：IN_ROOM / UNKNOWN

为减少抖动，需要连续 N 帧（`confirm_frames`）同一状态才真正切换。
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Set

from core.state import GameState
from .detector import Detection


@dataclass
class ParserConfig:
    monster_classes: Set[str] = field(default_factory=lambda: {"monster", "elite", "boss"})
    boss_classes: Set[str] = field(default_factory=lambda: {"boss"})
    item_classes: Set[str] = field(default_factory=lambda: {"item", "gold"})
    portal_classes: Set[str] = field(default_factory=lambda: {"portal", "portal_hidden", "portal_boss"})
    boss_portal_classes: Set[str] = field(default_factory=lambda: {"portal_boss"})
    player_class: str = "player"
    ui_classes: Set[str] = field(default_factory=lambda: {"retry_button", "confirm_button"})
    clear_flag: str = "room_clear"
    confirm_frames: int = 3

    @classmethod
    def from_dict(cls, d: Dict) -> "ParserConfig":
        def _set(k: str, default: Set[str]) -> Set[str]:
            v = d.get(k)
            return set(v) if v else default
        cfg = cls()
        cfg.monster_classes = _set("monster_classes", cfg.monster_classes)
        cfg.item_classes = _set("item_classes", cfg.item_classes)
        cfg.portal_classes = _set("portal_classes", cfg.portal_classes)
        cfg.ui_classes = _set("ui_classes", cfg.ui_classes)
        cfg.player_class = d.get("player_class", cfg.player_class)
        cfg.clear_flag = d.get("clear_flag", cfg.clear_flag)
        cfg.confirm_frames = d.get("confirm_frames", cfg.confirm_frames)
        return cfg


class GameStateParser:
    def __init__(self, config: Optional[ParserConfig] = None) -> None:
        self.cfg = config or ParserConfig()
        self._window: Deque[GameState] = deque(maxlen=max(1, self.cfg.confirm_frames))
        self._confirmed: GameState = GameState.UNKNOWN

    def parse(self, detections: List[Detection]) -> GameState:
        raw = self._infer(detections)
        self._window.append(raw)
        if len(self._window) == self._window.maxlen and all(s == raw for s in self._window):
            self._confirmed = raw
        return self._confirmed

    def _infer(self, detections: List[Detection]) -> GameState:
        names = [d.class_name for d in detections]
        nset = set(names)

        # 1) 结算/UI 画面
        if nset & self.cfg.ui_classes:
            return GameState.RESULT_SCREEN

        # 2) 传送门选择
        portals = [n for n in names if n in self.cfg.portal_classes]
        if len(portals) >= 2:
            return GameState.PORTAL_SELECT

        # 3) 战斗 / Boss
        monsters = [n for n in names if n in self.cfg.monster_classes]
        if monsters:
            if any(n in self.cfg.boss_classes for n in monsters):
                return GameState.BOSS_ROOM
            return GameState.COMBAT

        # 4) 拾取
        items = [n for n in names if n in self.cfg.item_classes]
        if items:
            return GameState.LOOTING

        # 5) 通关标识 / 已清场 → 准备导航
        if self.cfg.clear_flag in nset:
            return GameState.NAVIGATING

        # 6) 检测结果里有玩家但无怪无物 → 空房间
        if self.cfg.player_class in nset:
            return GameState.IN_ROOM

        return GameState.UNKNOWN

    @property
    def confirmed(self) -> GameState:
        return self._confirmed

    def reset(self) -> None:
        self._window.clear()
        self._confirmed = GameState.UNKNOWN
