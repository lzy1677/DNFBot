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
from utils.logger import get_logger, setup_logging
from utils.timer import RateLimiter
from vision.capture import ScreenCapture
from vision.detector import YOLODetector
from vision.game_state_parser import GameStateParser, ParserConfig
from vision.minimap_reader import MinimapReader


log = get_logger(__name__)

# 心跳日志间隔（秒）
_HEARTBEAT_INTERVAL = 5.0


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
    minimap_reader: Optional[MinimapReader] = None


class GameBot:
    """组装 + 主循环。"""

    def __init__(self, deps: BotDeps, loop_hz: int = 20) -> None:
        self.d = deps
        self.loop_hz = max(1, loop_hz)
        self._stop = threading.Event()
        self._limiter = RateLimiter(1.0 / self.loop_hz)
        self._start_time: float = 0.0
        self._last_heartbeat: float = 0.0

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
        self._tick_count: int = 0
        # 每隔多少帧读一次小地图（20Hz 下约每 0.5s）
        self._minimap_interval: int = 10

    # ---- 工厂 ----
    @classmethod
    def from_settings(cls, settings_path: str | Path,
                      verbose: bool = False,
                      skip_dungeon: bool = False) -> "GameBot":
        cfg = load_yaml(settings_path)

        lg = cfg.get("logging", {})
        # verbose 优先级：CLI --verbose > settings.yaml logging.verbose > logging.level
        if verbose or lg.get("verbose", False):
            level = "DEBUG"
        else:
            level = lg.get("level", "INFO")
        setup_logging(level=level, log_file=lg.get("file"))

        log.info("=== DNF Bot 初始化 ===")

        # [1/5] 截图
        cap_cfg = cfg.get("capture", {})
        region = cap_cfg.get("region")
        if region is not None:
            region = tuple(region)
        backend = cap_cfg.get("backend", "auto")
        log.info("[1/5] 截图模块  backend=%s  region=%s",
                 backend, region or "全屏")
        capture = ScreenCapture(
            region=region,
            target_fps=cap_cfg.get("target_fps", 60),
            backend=backend,
            window_title=cap_cfg.get("window_title"),
        )
        log.info("[1/5] 截图后端已就绪: %s  region=%s",
                 capture.backend, capture.region or "全屏")

        # [2/5] YOLO 检测器
        det_cfg = cfg.get("detector", {})
        model_path = det_cfg.get("model_path", "yolov8n.pt")
        log.info("[2/5] 加载 YOLO 模型: %s  device=%s  imgsz=%d",
                 model_path, det_cfg.get("device") or "auto", det_cfg.get("imgsz", 640))
        detector = YOLODetector(
            model_path=model_path,
            conf_threshold=det_cfg.get("conf_threshold", 0.45),
            iou_threshold=det_cfg.get("iou_threshold", 0.45),
            imgsz=det_cfg.get("imgsz", 640),
            device=det_cfg.get("device"),
        )
        log.info("[2/5] 模型就绪  类别数=%d  首次推理 %.1fms",
                 len(detector.names), detector.last_infer_ms)

        # [3/5] 状态解析器
        log.info("[3/5] 状态解析器 ...")
        parser = GameStateParser(ParserConfig.from_dict(cfg.get("state_parser", {})))

        # [4/5] 输入驱动 + 动作队列
        log.info("[4/5] 输入驱动 + 动作队列 ...")
        driver = InputDriver()
        queue = ActionQueue(driver)
        queue.start()

        # [5/5] 职业 + 地图
        bot_cfg = cfg.get("bot", {})
        root = Path(settings_path).parent.parent
        class_name = bot_cfg.get("character_class", "berserker")
        class_cfg_path = root / "config" / "classes" / f"{class_name}.yaml"
        log.info("[5/5] 职业: %s  地图: %s",
                 class_name, bot_cfg.get("map") or "<无>")
        character = build_class(class_name, class_cfg_path)

        game_map = None
        map_name = bot_cfg.get("map")
        if map_name:
            map_path = root / "config" / "maps" / f"{map_name}.yaml"
            if map_path.exists():
                game_map = load_map(map_path)
                log.info("[5/5] 地图已加载: %s  共 %d 间房",
                         game_map.name, len(game_map.rooms))
            else:
                log.warning("[5/5] 地图配置不存在: %s，跳过", map_path)

        log.info("=== 初始化完成 | 目标频率 %d Hz ===",
                 bot_cfg.get("loop_hz", 20))

        sm = StateMachine()
        if skip_dungeon:
            sm.transition(GameState.IN_ROOM, force=True)
            log.info("--skip-dungeon: 初始状态强制设为 IN_ROOM")

        minimap_reader: Optional[MinimapReader] = None
        if game_map is not None:
            minimap_reader = MinimapReader.from_map(game_map)
            if minimap_reader:
                log.info("[5/5] 小地图读取器已就绪  rooms=%d", len(game_map.room_minimap_xy))
            else:
                log.info("[5/5] 地图无小地图配置，跳过小地图检测")

        deps = BotDeps(
            capture=capture, detector=detector, parser=parser,
            driver=driver, queue=queue, character=character,
            game_map=game_map, state=sm, bus=EventBus(),
            minimap_reader=minimap_reader,
        )
        return cls(deps, loop_hz=bot_cfg.get("loop_hz", 20))

    # ---- 生命周期 ----
    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        log.info("GameBot 启动 | 职业=%s 地图=%s",
                 self.d.character.display_name,
                 self.d.game_map.name if self.d.game_map else "<无>")
        self._start_time = time.monotonic()
        self._last_heartbeat = self._start_time
        try:
            while not self._stop.is_set():
                self._tick()
                self._maybe_heartbeat()
                time.sleep(max(0.0, 1.0 / self.loop_hz - 0.001))
        except KeyboardInterrupt:
            log.info("用户中断")
        finally:
            self._shutdown()

    def _shutdown(self) -> None:
        self.d.queue.clear()
        self.d.queue.stop()
        self.d.capture.close()
        if self._start_time:
            log.info("GameBot 已停止 | 共运行 %.1fs", time.monotonic() - self._start_time)
        else:
            log.info("GameBot 已停止")

    # ---- 心跳日志 ----
    def _maybe_heartbeat(self) -> None:
        now = time.monotonic()
        if now - self._last_heartbeat < _HEARTBEAT_INTERVAL:
            return
        elapsed = now - self._start_time
        log.info(
            "[心跳] 运行 %.0fs | 状态: %-16s | 队列: %d | FPS: %.1f | 推理: %.1fms",
            elapsed,
            self.d.state.current.value,
            self.d.queue.size(),
            self.d.capture.stats.fps,
            self.d.detector.last_infer_ms,
        )
        self._last_heartbeat = now

    # ---- 小地图校正 ----
    def _check_minimap(self, frame) -> None:
        if self.d.minimap_reader is None or self.d.game_map is None:
            return
        detected = self.d.minimap_reader.detect(frame)
        if detected is None:
            return
        if self.d.game_map.sync_from_minimap(detected):
            log.info("[minimap] 房间校正: current_id → %d", detected)

    # ---- 主循环单步 ----
    def _tick(self) -> None:
        self._tick_count += 1
        t_cap = time.perf_counter()
        frame = self.d.capture.grab()
        cap_ms = (time.perf_counter() - t_cap) * 1000

        if frame is None:
            log.debug("[tick] 截图返回 None，跳过本帧")
            return

        if self._tick_count % self._minimap_interval == 0:
            self._check_minimap(frame)

        detections = self.d.detector.detect(frame)
        new_state = self.d.parser.parse(detections)

        log.debug(
            "[tick] cap=%.1fms  infer=%.1fms  dets=%d  parser→%s  cur=%s",
            cap_ms,
            self.d.detector.last_infer_ms,
            len(detections),
            new_state.value,
            self.d.state.current.value,
        )

        if new_state != self.d.state.current:
            if self.d.state.transition(new_state):
                log.info("状态切换  %s → %s",
                         self.d.state.previous.value, new_state.value)
                self.d.bus.emit("state_change", new_state)
                self._on_state_enter(new_state)
            else:
                log.debug("[tick] 状态转移被阻止: %s → %s",
                          self.d.state.current.value, new_state.value)

        strategy = self.strategies.get(self.d.state.current)
        if strategy is None:
            log.debug("[tick] 当前状态 %s 无对应策略，跳过",
                      self.d.state.current.value)
            return

        if self.d.queue.is_busy() and self.d.state.current not in (
            GameState.RESULT_SCREEN, GameState.UNKNOWN
        ):
            log.debug("[tick] 动作队列忙，跳过策略决策")
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
            tags = [a.tag or type(a).__name__ for a in actions]
            log.debug("[策略] %s → %s", self.d.state.current.value, tags)
            self.d.queue.submit(actions)

    def _on_state_enter(self, s: GameState) -> None:
        if s in (GameState.IN_ROOM, GameState.COMBAT) and not self._buffed_once:
            buffs = self.d.character.get_buff_sequence()
            if buffs:
                log.info("[buff] 进房首次，释放 %d 个 buff", len(buffs))
                self.d.queue.submit(buffs)
            self._buffed_once = True

        if s == GameState.IN_TOWN:
            log.debug("[状态] 回城，重置 buff 标志")
            self._buffed_once = False

        if s == GameState.PORTAL_SELECT and self.d.game_map:
            nxt = self.d.game_map.next_room_towards_boss()
            if nxt is not None:
                log.info("[地图] 进门 room %d → room %d",
                         self.d.game_map.current_id, nxt)
                self.d.game_map.mark_cleared()
                self.d.game_map.set_current(nxt)
