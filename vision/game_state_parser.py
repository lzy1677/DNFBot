"""从 YOLO 检测结果推断 GameState。

当前模型类别：monster / stone / item / portal / player / ui_button

规则（按优先级从高到低）：
  1. 检测到 ui_button              → RESULT_SCREEN
  2. 检测到 portal 且数量>=2       → PORTAL_SELECT
  3. 检测到 monster 或 stone       → COMBAT
  4. 检测到 item，无怪无stone       → LOOTING
  5. 检测到 player，无怪无物        → IN_ROOM
  6. 其他（画面空或仅有传送门）      → NAVIGATING

为减少抖动，需要连续 N 帧（confirm_frames）同一状态才真正切换。
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Set

from core.state import GameState
from utils.logger import get_logger
from .detector import Detection


log = get_logger(__name__)


@dataclass
class ParserConfig:
    monster_classes: Set[str] = field(default_factory=lambda: {"monster", "stone"})
    # boss_classes 保留字段，当前模型无 boss 类别，默认为空
    boss_classes: Set[str] = field(default_factory=set)
    item_classes: Set[str] = field(default_factory=lambda: {"item"})
    portal_classes: Set[str] = field(default_factory=lambda: {"portal"})
    player_class: str = "player"
    ui_classes: Set[str] = field(default_factory=lambda: {"ui_button"})
    confirm_frames: int = 3

    @classmethod
    def from_dict(cls, d: Dict) -> "ParserConfig":
        def _set(k: str, default: Set[str]) -> Set[str]:
            v = d.get(k)
            return set(v) if v else default
        cfg = cls()
        cfg.monster_classes = _set("monster_classes", cfg.monster_classes)
        cfg.boss_classes    = _set("boss_classes",    cfg.boss_classes)
        cfg.item_classes    = _set("item_classes",    cfg.item_classes)
        cfg.portal_classes  = _set("portal_classes",  cfg.portal_classes)
        cfg.ui_classes      = _set("ui_classes",      cfg.ui_classes)
        cfg.player_class    = d.get("player_class", cfg.player_class)
        cfg.confirm_frames  = d.get("confirm_frames", cfg.confirm_frames)
        return cfg


class GameStateParser:
    def __init__(self, config: Optional[ParserConfig] = None) -> None:
        self.cfg = config or ParserConfig()
        self._window: Deque[GameState] = deque(maxlen=max(1, self.cfg.confirm_frames))
        self._confirmed: GameState = GameState.UNKNOWN

    def parse(self, detections: List[Detection]) -> GameState:
        raw = self._infer(detections)
        self._window.append(raw)
        window_full = (len(self._window) == self._window.maxlen
                       and all(s == raw for s in self._window))
        if window_full:
            if raw != self._confirmed:
                log.debug("[parser] 确认切换: %s → %s",
                          self._confirmed.value, raw.value)
            self._confirmed = raw
        else:
            log.debug("[parser] 防抖中  raw=%-12s  %d/%d帧  confirmed=%s",
                      raw.value, len(self._window),
                      self._window.maxlen, self._confirmed.value)
        return self._confirmed

    def _infer(self, detections: List[Detection]) -> GameState:
        names = [d.class_name for d in detections]
        nset = set(names)

        # 1) 结算 UI
        if nset & self.cfg.ui_classes:
            return GameState.RESULT_SCREEN

        # 2) 传送门选择（≥2 个，说明在路口）
        portals = [n for n in names if n in self.cfg.portal_classes]
        if len(portals) >= 2:
            return GameState.PORTAL_SELECT

        # 3) 战斗（monster / stone，有 boss_classes 时进 BOSS_ROOM）
        monsters = [n for n in names if n in self.cfg.monster_classes]
        if monsters:
            if self.cfg.boss_classes and any(n in self.cfg.boss_classes for n in monsters):
                return GameState.BOSS_ROOM
            return GameState.COMBAT

        # 4) 拾取（无怪无stone）
        items = [n for n in names if n in self.cfg.item_classes]
        if items:
            return GameState.LOOTING

        # 5) 玩家可见，无怪无物 → 空房间（刚进房或停留中）
        if self.cfg.player_class in nset:
            return GameState.IN_ROOM

        # 6) 画面空（房间已清场）→ 准备导航到下一房间
        return GameState.NAVIGATING

    @property
    def confirmed(self) -> GameState:
        return self._confirmed

    def reset(self) -> None:
        self._window.clear()
        self._confirmed = GameState.UNKNOWN
