"""异常恢复策略：处理结算画面 / 卡死状态。"""
from __future__ import annotations

from typing import List

from action.action_queue import Action, KeyPress, Move, Wait
from .base import Strategy, StrategyContext


UI_CLASSES = {"ui_button"}


class RecoveryStrategy(Strategy):
    """结算画面自动再次挑战；长时间 UNKNOWN 时尝试小范围抖动解卡。"""
    name = "recovery"

    def __init__(self, stuck_seconds: float = 8.0,
                 retry_key: str = "page_down") -> None:
        self.stuck_seconds = stuck_seconds
        self.retry_key = retry_key

    def decide(self, ctx: StrategyContext) -> List[Action]:
        # 结算画面：按 page_down 重新挑战
        ui = [d for d in ctx.detections if d.class_name in UI_CLASSES]
        if ui:
            return [
                KeyPress(key=self.retry_key, duration=0.08, tag="retry"),
                Wait(seconds=0.3),
            ]

        # 疑似卡死（UNKNOWN 状态停留太久）
        if ctx.elapsed_in_state >= self.stuck_seconds:
            return [
                Move(direction="right", duration=0.15, tag="unstick_r"),
                Move(direction="left",  duration=0.15, tag="unstick_l"),
                KeyPress(key="c",       duration=0.04, tag="unstick_jump"),
            ]

        return []
