"""GameBot 主控制器：状态机驱动主循环。"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from action.action_queue import ActionQueue
from action.input_driver import InputDriver
from classes.base_class import BaseClass, build_class
from core.event_bus import EventBus
from core.state import GameState, StateMachine
from maps.base_map import BaseMap
from maps.map_loader import load_map
from strategy.base import Strategy, StrategyContext
from strategy.combat import CombatStrategy
from strategy.loot import LootStrategy
from strategy.navigation import NavigationStrategy
from strategy.portal import PortalStrategy
from strategy.recovery import RecoveryStrategy
from utils.config import load_yaml
from utils.logger import get_logger
from utils.timer import RateLimiter
from vision.capture import ScreenCapture
from vision.detector import YOLODetector
from vision.game_state_parser import GameStateParser, ParserConfig


log = get_logger(__name__)


@dataclass
class BotDeps:
    capture: ScreenCapture
    detector: YOLODetector
    parser: GameStateParser
    driver: InputDriver
    queue: ActionQueue
    character: BaseClass
    game_map: Optional[BaseMap]
    state: StateMachine
    bus: EventBus


class GameBot:
    """组装 + 主循环。"""

    def __init__(self, deps: BotDeps, loop_hz: int = 20) -> None:
        self.d = deps
        self.loop_hz = max(1, loop_hz)
        self._stop = threading.Event()
        self._limiter = RateLimiter(1.0 / self.loop_hz)

        self.strategies: Dict[GameState, Strategy] = {
            GameState.COMBAT: CombatStrategy(),
            GameState.BOSS_ROOM: CombatStrategy(),
            GameState.LOOTING: LootStrategy(),
            GameState.NAVIGATING: NavigationStrategy(),
            GameState.IN_ROOM: NavigationStrategy(),
            GameState.PORTAL_SELECT: PortalStrategy(),
            GameState.RESULT_SCREEN: RecoveryStrategy(),
            GameState.UNKNOWN: RecoveryStrategy(),
        }

        self._buffed_once = False

    # ---- 工厂 ----
    @classmethod
    def from_settings(cls, settings_path: str | Path) -> "GameBot":
        cfg = load_yaml(settings_path)

        from utils.logger import setup_logging
        lg = cfg.get("logging", {})
        setup_logging(level=lg.get("level", "INFO"), log_file=lg.get("file"))

        cap_cfg = cfg.get("capture", {})
        region = cap_cfg.get("region")
        if region is not None:
            region = tuple(region)
        capture = ScreenCapture(
            region=region,
            target_fps=cap_cfg.get("target_fps", 60),
            backend=cap_cfg.get("backend", "auto"),
        )

        det_cfg = cfg.get("detector", {})
        detector = YOLODetector(
            model_path=det_cfg.get("model_path", "yolov8n.pt"),
            conf_threshold=det_cfg.get("conf_threshold", 0.45),
            iou_threshold=det_cfg.get("iou_threshold", 0.45),
            imgsz=det_cfg.get("imgsz", 640),
            device=det_cfg.get("device"),
        )
        detector.warmup(det_cfg.get("imgsz", 640))

        parser = GameStateParser(ParserConfig.from_dict(cfg.get("state_parser", {})))

        driver = InputDriver()
        queue = ActionQueue(driver)
        queue.start()

        bot_cfg = cfg.get("bot", {})
        root = Path(settings_path).parent.parent
        class_name = bot_cfg.get("character_class", "berserker")
        class_cfg_path = root / "config" / "classes" / f"{class_name}.yaml"
        character = build_class(class_name, class_cfg_path)

        game_map = None
        map_name = bot_cfg.get("map")
        if map_name:
            map_path = root / "config" / "maps" / f"{map_name}.yaml"
            if map_path.exists():
                game_map = load_map(map_path)
            else:
                log.warning("map config %s not found, skip", map_path)

        deps = BotDeps(
            capture=capture, detector=detector, parser=parser,
            driver=driver, queue=queue, character=character,
            game_map=game_map, state=StateMachine(), bus=EventBus(),
        )
        return cls(deps, loop_hz=bot_cfg.get("loop_hz", 20))

    # ---- 生命周期 ----
    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        log.info("GameBot 启动 | 职业=%s 地图=%s",
                 self.d.character.display_name,
                 self.d.game_map.name if self.d.game_map else "<无>")
        try:
            while not self._stop.is_set():
                self._tick()
                # 节流：目标频率
                time.sleep(max(0.0, 1.0 / self.loop_hz - 0.001))
        except KeyboardInterrupt:
            log.info("用户中断")
        finally:
            self._shutdown()

    def _shutdown(self) -> None:
        self.d.queue.clear()
        self.d.queue.stop()
        self.d.capture.close()
        log.info("GameBot 已停止")

    # ---- 主循环单步 ----
    def _tick(self) -> None:
        frame = self.d.capture.grab()
        if frame is None:
            return

        detections = self.d.detector.detect(frame)
        new_state = self.d.parser.parse(detections)

        if new_state != self.d.state.current:
            if self.d.state.transition(new_state):
                log.info("state %s -> %s", self.d.state.previous.value, new_state.value)
                self.d.bus.emit("state_change", new_state)
                self._on_state_enter(new_state)

        strategy = self.strategies.get(self.d.state.current)
        if strategy is None:
            return

        # 队列里还有未执行动作时不重复下发（除了高优先级的 recovery）
        if self.d.queue.is_busy() and self.d.state.current not in (
            GameState.RESULT_SCREEN, GameState.UNKNOWN
        ):
            return

        ctx = StrategyContext(
            detections=detections,
            frame_shape=frame.shape[:2],
            character=self.d.character,
            map=self.d.game_map,
            elapsed_in_state=self.d.state.time_in_state(),
        )
        actions = strategy.decide(ctx)
        if actions:
            self.d.queue.submit(actions)

    def _on_state_enter(self, s: GameState) -> None:
        # 进房首次：开 buff
        if s in (GameState.IN_ROOM, GameState.COMBAT) and not self._buffed_once:
            buffs = self.d.character.get_buff_sequence()
            if buffs:
                self.d.queue.submit(buffs)
            self._buffed_once = True

        # 回城：重置 buff 标志
        if s == GameState.IN_TOWN:
            self._buffed_once = False

        # 进门/过图：推进地图当前位置
        if s == GameState.PORTAL_SELECT and self.d.game_map:
            nxt = self.d.game_map.next_room_towards_boss()
            if nxt is not None:
                self.d.game_map.mark_cleared()
                self.d.game_map.set_current(nxt)
