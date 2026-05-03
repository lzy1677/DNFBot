"""职业基类。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Type

from action.action_queue import Action, KeyPress, Move, Wait
from action.skill import Skill, SkillSet
from utils.config import load_with_base


@dataclass
class CombatContext:
    """战斗决策所需信息（2.5D 四方向）。"""
    monster_boxes: List[Tuple[int, int, int, int]] = field(default_factory=list)
    player_box: Optional[Tuple[int, int, int, int]] = None
    boss_present: bool = False
    # 水平方向：'left' | 'right'
    approach_direction: str = "right"
    distance_px: int = 0
    # 垂直方向：'up' | 'down' | ''（已对齐时为空）
    approach_y_direction: str = ""
    distance_y_px: int = 0


class BaseClass(ABC):
    """职业基类，从 YAML 加载技能配置。"""

    name: str = "base"

    def __init__(self, config: Dict) -> None:
        self.config = config
        self.display_name: str = config.get("name", self.name)
        self.keys: Dict[str, str] = {}
        self.skills = SkillSet()
        self.combo_chains: List[List[str]] = config.get("combo_chains", [])
        self._load_skills(config)

    def _load_skills(self, cfg: Dict) -> None:
        keys_cfg = cfg.get("keys", {})
        for name, val in keys_cfg.items():
            if isinstance(val, str):
                self.keys[name] = val
                self.skills.add(Skill(name=name, key=val))
            elif isinstance(val, dict):
                key = val["key"]
                self.keys[name] = key
                self.skills.add(Skill(
                    name=name,
                    key=key,
                    cooldown=float(val.get("cooldown", 0.0)),
                    priority=int(val.get("priority", 0)),
                    duration=float(val.get("duration", 0.04)),
                    description=val.get("desc", ""),
                ))

    # ---- 工厂 ----
    @classmethod
    def from_config_file(cls, path: str | Path) -> "BaseClass":
        cfg = load_with_base(path)
        return cls(cfg)

    # ---- 基础动作（子类可复用） ----
    def attack(self) -> List[Action]:
        key = self.keys.get("attack", "x")
        return [KeyPress(key=key, duration=0.04, tag="attack")]

    def approach(self, direction: str, duration: float = 0.3) -> List[Action]:
        return [Move(direction=direction, duration=duration, tag="approach")]

    def use_skill(self, name: str) -> List[Action]:
        s = self.skills.get(name)
        if s is None or not s.ready():
            return []
        s.trigger()
        return [KeyPress(key=s.key, duration=s.duration, tag=f"skill:{name}",
                         priority=s.priority)]

    # ---- 由子类实现 ----
    @abstractmethod
    def get_attack_sequence(self, ctx: CombatContext) -> List[Action]: ...

    def get_buff_sequence(self) -> List[Action]:
        """开局 buff；基类默认把所有 priority<0 的 buff 技能挨个按一遍。"""
        out: List[Action] = []
        for s in self.skills:
            if s.priority < 0 and s.ready():
                s.trigger()
                out.append(KeyPress(key=s.key, duration=s.duration, tag=f"buff:{s.name}"))
                out.append(Wait(seconds=0.1))
        return out


# ---- 注册表 ----
_REGISTRY: Dict[str, Type[BaseClass]] = {}


def register_class(name: str):
    def deco(cls: Type[BaseClass]) -> Type[BaseClass]:
        _REGISTRY[name] = cls
        cls.name = name
        return cls
    return deco


def build_class(name: str, config_path: str | Path) -> BaseClass:
    if name not in _REGISTRY:
        raise KeyError(f"unknown class: {name}, available: {list(_REGISTRY)}")
    cfg = load_with_base(config_path)
    return _REGISTRY[name](cfg)
