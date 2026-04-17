"""策略基类。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

from action.action_queue import Action
from classes.base_class import BaseClass
from maps.base_map import BaseMap
from vision.detector import Detection


@dataclass
class StrategyContext:
    """决策上下文：传给各个 Strategy。"""
    detections: List[Detection] = field(default_factory=list)
    frame_shape: tuple = (0, 0)           # (h, w)
    character: Optional[BaseClass] = None
    map: Optional[BaseMap] = None
    elapsed_in_state: float = 0.0

    def detections_of(self, *names: str) -> List[Detection]:
        s = set(names)
        return [d for d in self.detections if d.class_name in s]

    def first_of(self, *names: str) -> Optional[Detection]:
        for d in self.detections:
            if d.class_name in names:
                return d
        return None


class Strategy(ABC):
    name: str = "strategy"

    @abstractmethod
    def decide(self, ctx: StrategyContext) -> List[Action]:
        ...
