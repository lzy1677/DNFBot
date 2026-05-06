"""房间抽象。"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class RoomType(str, Enum):
    START = "start"
    NORMAL = "normal"
    ELITE = "elite"
    BOSS = "boss"
    HIDDEN = "hidden"
    EXIT = "exit"


@dataclass
class Room:
    id: int
    type: RoomType = RoomType.NORMAL
    connections: List[int] = field(default_factory=list)
    name: str = ""
    cleared: bool = False
    # 进房时按职业固定释放技能 {class_name: [skill_name, ...]}
    on_enter_skills: Dict[str, List[str]] = field(default_factory=dict)

    def is_boss(self) -> bool:
        return self.type == RoomType.BOSS

    def neighbors(self) -> List[int]:
        return list(self.connections)
