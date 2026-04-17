"""技能抽象与技能集合。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from utils.timer import Cooldown


@dataclass
class Skill:
    name: str
    key: str
    cooldown: float = 0.0
    priority: int = 0
    duration: float = 0.04          # 按键持续时间
    description: str = ""
    _cd: Cooldown = field(init=False)

    def __post_init__(self) -> None:
        self._cd = Cooldown(self.cooldown)

    def ready(self) -> bool:
        return self._cd.ready()

    def remaining(self) -> float:
        return self._cd.remaining()

    def trigger(self) -> None:
        self._cd.trigger()


class SkillSet:
    """职业的技能集合，支持按 key/name 查询与按优先级筛选。"""

    def __init__(self, skills: Optional[List[Skill]] = None) -> None:
        self._by_name: Dict[str, Skill] = {}
        for s in skills or []:
            self.add(s)

    def add(self, skill: Skill) -> None:
        self._by_name[skill.name] = skill

    def get(self, name: str) -> Optional[Skill]:
        return self._by_name.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._by_name

    def __iter__(self):
        return iter(self._by_name.values())

    def ready_skills(self) -> List[Skill]:
        return [s for s in self._by_name.values() if s.ready()]

    def highest_priority_ready(self) -> Optional[Skill]:
        candidates = self.ready_skills()
        return max(candidates, key=lambda s: s.priority) if candidates else None
