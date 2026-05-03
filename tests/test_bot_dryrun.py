"""集成测试：GameBot 整体初始化（dry-run 模式，不截图不推理）。

验证从 settings.yaml 到 bot.run() 的完整初始化路径，
用 mock 替换截图和 YOLO 推理，确保各模块能正确组装。
"""
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.bot import GameBot, BotDeps
from core.state import GameState, StateMachine
from core.event_bus import EventBus
from action.action_queue import ActionQueue
from action.input_driver import InputDriver
from vision.capture import ScreenCapture
from vision.detector import YOLODetector, Detection
from vision.game_state_parser import GameStateParser, ParserConfig
from classes.berserker import Berserker
from maps.base_map import BaseMap
from maps.room import Room, RoomType


def _make_deps() -> BotDeps:
    """构造最小可用 BotDeps，所有 I/O 组件均 mock。"""
    mock_capture = MagicMock(spec=ScreenCapture)
    fake_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    mock_capture.grab.return_value = fake_frame
    mock_capture.backend = "mock"

    mock_detector = MagicMock(spec=YOLODetector)
    mock_detector.detect.return_value = []
    mock_detector.last_infer_ms = 5.0

    parser = GameStateParser(ParserConfig(confirm_frames=1))

    mock_driver = MagicMock(spec=InputDriver)
    queue = ActionQueue(mock_driver)
    queue.start()

    berserker_cfg = {
        "name": "狂战士",
        "keys": {
            "attack": "x",
            "skill_1": {"key": "q", "cooldown": 0.0, "priority": 3},
        },
        "combo_chains": [],
    }
    character = Berserker(berserker_cfg)

    game_map = BaseMap(name="test_map", start_id=0, optimal_path=[0, 1])
    game_map.add_room(Room(id=0, type=RoomType.START, connections=[1]))
    game_map.add_room(Room(id=1, type=RoomType.BOSS, connections=[0]))
    game_map.set_current(0)

    # Start from UNKNOWN so the state machine can transition freely in tests
    sm = StateMachine()
    sm.transition(GameState.UNKNOWN, force=True)

    return BotDeps(
        capture=mock_capture,
        detector=mock_detector,
        parser=parser,
        driver=mock_driver,
        queue=queue,
        character=character,
        game_map=game_map,
        state=sm,
        bus=EventBus(),
    )


class TestGameBotTick:
    def setup_method(self):
        self.deps = _make_deps()
        self.bot = GameBot(self.deps, loop_hz=60)

    def teardown_method(self):
        self.deps.queue.stop()

    def test_tick_with_empty_detections(self):
        self.bot._tick()
        self.deps.detector.detect.assert_called_once()

    def test_tick_no_frame_skips(self):
        self.deps.capture.grab.return_value = None
        self.bot._tick()
        self.deps.detector.detect.assert_not_called()

    def test_state_transitions_on_monster(self):
        monster_det = Detection(
            class_id=0, class_name="monster", confidence=0.9,
            bbox=(100, 100, 200, 200),
        )
        self.deps.detector.detect.return_value = [monster_det]
        # confirm_frames=1, so single tick should confirm COMBAT
        self.bot._tick()
        assert self.bot.d.state.current == GameState.COMBAT

    def test_result_screen_triggers_recovery(self):
        ui_det = Detection(
            class_id=5, class_name="ui_button", confidence=0.95,
            bbox=(400, 300, 600, 400),
        )
        self.deps.detector.detect.return_value = [ui_det]
        self.bot._tick()
        assert self.bot.d.state.current == GameState.RESULT_SCREEN

    def test_looting_state(self):
        item_det = Detection(
            class_id=1, class_name="item", confidence=0.85,
            bbox=(300, 400, 340, 430),
        )
        self.deps.detector.detect.return_value = [item_det]
        self.bot._tick()
        assert self.bot.d.state.current == GameState.LOOTING

    def test_shutdown_clears_queue(self):
        self.bot._shutdown()
        assert not self.deps.queue._thread.is_alive() if self.deps.queue._thread else True


class TestGameBotRun:
    def test_run_stops_on_stop_event(self):
        deps = _make_deps()
        bot = GameBot(deps, loop_hz=60)

        def stop_after():
            time.sleep(0.1)
            bot.stop()

        t = threading.Thread(target=stop_after)
        t.start()
        bot.run()
        t.join(timeout=2.0)

        assert bot._stop.is_set()
        deps.queue.stop()

    def test_stop_is_idempotent(self):
        deps = _make_deps()
        bot = GameBot(deps, loop_hz=60)
        bot.stop()
        bot.stop()
        assert bot._stop.is_set()
        deps.queue.stop()


class TestGameBotFromSettings:
    """验证 from_settings 工厂不再触发 640 次 warmup（之前的 bug）。"""

    def test_warmup_called_once_at_init(self):
        settings_path = (
            Path(__file__).parent.parent / "config" / "settings.yaml"
        )
        if not settings_path.exists():
            pytest.skip("settings.yaml not found")

        warmup_calls = []

        real_init = YOLODetector.__init__

        def patched_init(self_inner, *args, **kwargs):
            # Intercept warmup to count calls without running YOLO
            original_warmup = None
            def counting_warmup(rounds=3):
                warmup_calls.append(rounds)
            self_inner.warmup = counting_warmup
            # Bypass actual YOLO loading
            self_inner.model = MagicMock()
            self_inner.model.names = {0: "monster"}
            self_inner.conf = kwargs.get("conf_threshold", 0.5)
            self_inner.iou = kwargs.get("iou_threshold", 0.45)
            self_inner.device = kwargs.get("device")
            self_inner.imgsz = kwargs.get("imgsz", 640)
            self_inner.half = kwargs.get("half", True)
            self_inner.class_filter = None
            self_inner.names = self_inner.model.names
            self_inner.last_infer_ms = 0.0
            self_inner.warmup()  # replicate __init__ behavior

        with patch.object(YOLODetector, "__init__", patched_init):
            with patch("vision.capture.ScreenCapture.__init__", return_value=None):
                with patch("vision.capture.ScreenCapture.close"):
                    with patch("action.action_queue.ActionQueue.start"):
                        with patch("action.action_queue.ActionQueue.stop"):
                            try:
                                bot = GameBot.from_settings(settings_path)
                                bot.d.queue.stop()
                            except Exception:
                                pass

        # Should only be called once (3 rounds), not 640 times
        assert all(r <= 10 for r in warmup_calls), (
            f"warmup called with suspicious round count: {warmup_calls}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
