"""异常恢复策略：处理结算画面 / 卡死状态。"""
from __future__ import annotations

from typing import List

from action.action_queue import Action, KeyPress, Move, Wait
from .base import Strategy, StrategyContext


UI_CLASSES = {"retry_button", "confirm_button"}


class RecoveryStrategy(Strategy):
    """结算画面自动再次挑战；长时间 UNKNOWN 时尝试小范围抖动解卡。"""
    name = "recovery"

    def __init__(self, stuck_seconds: float = 8.0, interact_key: str = "enter") -> None:
        self.stuck_seconds = stuck_seconds
        self.interact_key = interact_key

    def decide(self, ctx: StrategyContext) -> List[Action]:
        # 结算画面：点击 retry / confirm
        ui = [d for d in ctx.detections if d.class_name in UI_CLASSES]
        if ui:
            btn = max(ui, key=lambda d: d.confidence)
            # 优先 retry
            retry = [d for d in ui if d.class_name == "retry_button"]
            if retry:
                btn = max(retry, key=lambda d: d.confidence)
            return [
                # 很多游戏按回车即可确认再次挑战
                KeyPress(key=self.interact_key, duration=0.08, tag="retry"),
                Wait(seconds=0.3),
            ]

        # 疑似卡死（UNKNOWN 状态停留太久）
        if ctx.elapsed_in_state >= self.stuck_seconds:
            return [
                Move(direction="right", duration=0.15, tag="unstick_r"),
                Move(direction="left", duration=0.15, tag="unstick_l"),
                KeyPress(key="c", duration=0.04, tag="unstick_jump"),
            ]

        return []
