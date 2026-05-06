"""GameBot 主控制器：状态机驱动主循环。"""
from __future__ import annotations

import threading
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set

import numpy as np

from action.action_queue import ActionQueue, Wait
from action.input_driver import InputDriver
from classes.base_class import BaseClass, build_class
from core.event_bus import EventBus
from core.state import GameState, StateMachine
from maps.base_map import BaseMap
from maps.map_loader import load_map
from maps.room import RoomType
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
from vision.detector import Detection, YOLODetector
from vision.game_state_parser import GameStateParser, ParserConfig
from vision.minimap_reader import MinimapReader


log = get_logger(__name__)

_HEARTBEAT_INTERVAL = 5.0

# LOADING 检测参数
_LOADING_BRIGHTNESS = 50       # BGR 均值低于此视为暗屏
_LOADING_MAX_DETS = 1          # 最多允许 1 个检测目标
_LOADING_CONFIRM = 3           # 连续 N 帧确认

# 重新挑战超时（秒），超过则放弃回城
_RECHALLENGE_TIMEOUT = 30.0
# 拾取超时（秒），超过则强制离开（防止 YOLO 误检 item 导致卡死）
_LOOTING_TIMEOUT = 8.0
# 战斗超时（秒），超过且无怪物则强制离开（防止 YOLO 单帧误检 monster 触发立即切换后卡死）
_COMBAT_TIMEOUT = 5.0


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
            GameState.PORTAL: PortalStrategy(),
            GameState.RESULT_SCREEN: RecoveryStrategy(),
            GameState.UNKNOWN: RecoveryStrategy(),
        }

        self._buffed_once = False
        self._tick_count: int = 0
        self._minimap_interval: int = 10

        # LOADING 检测防抖
        self._loading_frames: int = 0
        # 已触发过进房技能的房间 ID 集合（每局重置）
        self._room_skill_triggered: Set[int] = set()
        # skip_dungeon 模式下，首次 tick 强制检查进房技能
        self._check_room_skills_once = False
        # 最新一帧 YOLO 检测结果（供心跳日志统计）
        self._last_detections: List[Detection] = []
        # 传送门待确认的下一房间号（PORTAL 时设定，LOADING→房间后应用，防止重复推进）
        self._pending_next_room: Optional[int] = None

    # ---- 工厂 ----
    @classmethod
    def from_settings(cls, settings_path: str | Path,
                      verbose: bool = False,
                      skip_dungeon: bool = True) -> "GameBot":
        cfg = load_yaml(settings_path)

        lg = cfg.get("logging", {})
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
            log.info("--skip-dungeon: 初始状态强制设为 IN_ROOM（默认，直接从副本内启动）")

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
        bot = cls(deps, loop_hz=bot_cfg.get("loop_hz", 20))
        if skip_dungeon:
            bot._check_room_skills_once = True
        return bot

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
        det_counts = Counter(d.class_name for d in self._last_detections)
        det_summary = " ".join(f"{k}={v}" for k, v in sorted(det_counts.items()))
        log.info(
            "[心跳] 运行 %.0fs | 状态: %-16s | 队列: %d | FPS: %.1f | 推理: %.1fms | YOLO: %s",
            elapsed,
            self.d.state.current.value,
            self.d.queue.size(),
            self.d.capture.stats.fps,
            self.d.detector.last_infer_ms,
            det_summary,
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
            # 校正后重置 PORTAL 状态，让寻门逻辑用正确房间号重新开始
            if self.d.state.current == GameState.PORTAL:
                log.info("[minimap] 房间已校正，重置 PORTAL 寻门计时")
                self._pending_next_room = None
                self.d.state.transition(GameState.NAVIGATING, force=True)
                self.d.bus.emit("state_change", GameState.NAVIGATING)
                self._on_state_enter(GameState.NAVIGATING)
        # IN_TOWN 状态下检测到房间 → 说明实际在副本中，强制恢复
        if self.d.state.current == GameState.IN_TOWN and detected is not None:
            log.warning("[minimap] 实际在副本中（检测到房间 %d），从 IN_TOWN 恢复", detected)
            self.d.state.transition(GameState.IN_ROOM, force=True)
            self.d.bus.emit("state_change", GameState.IN_ROOM)
            self._on_state_enter(GameState.IN_ROOM)

    # ---- LOADING 检测 ----
    def _is_loading(self, frame: np.ndarray, detections) -> bool:
        """暗屏 + 极少检测目标 → 推断为加载界面。"""
        if len(detections) > _LOADING_MAX_DETS:
            self._loading_frames = 0
            return False
        brightness = float(np.mean(frame))
        if brightness < _LOADING_BRIGHTNESS:
            self._loading_frames += 1
            if self._loading_frames >= _LOADING_CONFIRM:
                return True
        else:
            self._loading_frames = max(0, self._loading_frames - 1)
        return False

    # ---- Boss 房判断 ----
    def _is_boss_room(self) -> bool:
        """地图确认为 Boss 房间。"""
        if self.d.game_map is None:
            return False
        cur = self.d.game_map.current()
        return cur is not None and cur.type == RoomType.BOSS

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
        self._last_detections = detections

        # LOADING 检测优先于 parser（暗屏 + 低检测数）
        if self._is_loading(frame, detections):
            new_state = GameState.LOADING
        else:
            new_state = self.d.parser.parse(detections)

        # 地图驱动覆盖：parser 返回 COMBAT 但地图确认为 Boss 房 → BOSS_ROOM
        if new_state == GameState.COMBAT and self._is_boss_room():
            new_state = GameState.BOSS_ROOM

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

        # 重新挑战超时检测
        if self.d.state.current == GameState.RESULT_SCREEN:
            if self.d.state.time_in_state() > _RECHALLENGE_TIMEOUT:
                log.warning("[rechallenge] 超时 %.0fs，放弃回城",
                           self.d.state.time_in_state())
                self.d.queue.clear()
                self.d.state.transition(GameState.IN_TOWN, force=True)
                self.d.bus.emit("state_change", GameState.IN_TOWN)
                self._on_state_enter(GameState.IN_TOWN)

        # 拾取超时检测：YOLO 可能持续误检 item，防止卡死在 LOOTING
        if self.d.state.current == GameState.LOOTING:
            if self.d.state.time_in_state() > _LOOTING_TIMEOUT:
                log.warning("[loot] 拾取超时 %.0fs，YOLO 可能误检 item，强制离开",
                           self.d.state.time_in_state())
                self.d.queue.clear()
                self.d.state.transition(GameState.IN_ROOM, force=True)
                self.d.bus.emit("state_change", GameState.IN_ROOM)
                self._on_state_enter(GameState.IN_ROOM)

        # COMBAT 超时检测：YOLO 单帧误检 monster/stone 触发切换后，画面无怪则强制离开
        if self.d.state.current == GameState.COMBAT:
            if self.d.state.time_in_state() > _COMBAT_TIMEOUT:
                has_enemy = any(d.class_name in ("monster", "stone")
                                for d in self._last_detections)
                if not has_enemy:
                    log.warning("[combat] 战斗超时 %.0fs 且画面无怪，YOLO 误检，强制离开",
                               self.d.state.time_in_state())
                    self.d.queue.clear()
                    self.d.state.transition(GameState.IN_ROOM, force=True)
                    self.d.bus.emit("state_change", GameState.IN_ROOM)
                    self._on_state_enter(GameState.IN_ROOM)

        # skip-dungeon 模式首次 tick：检查初始房间是否有进房技能
        if self._check_room_skills_once and self.d.state.current == GameState.IN_ROOM:
            self._check_room_skills_once = False
            self._trigger_room_skills()

        strategy = self.strategies.get(self.d.state.current)
        if strategy is None:
            log.debug("[tick] 当前状态 %s 无对应策略，跳过",
                      self.d.state.current.value)
            return

        if self.d.queue.is_busy() and self.d.state.current not in (
            GameState.UNKNOWN,
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

        if s in (GameState.IN_TOWN, GameState.RESULT_SCREEN):
            log.debug("[状态] %s，重置副本状态", s.value)
            self._buffed_once = False
            self._room_skill_triggered.clear()
            self._pending_next_room = None
            self.d.character.skills.reset_all()
            if self.d.game_map:
                self.d.game_map.set_current(self.d.game_map.start_id)

        # 真正过门后（LOADING → 房间），应用待确认的房间切换
        if s in (GameState.IN_ROOM, GameState.COMBAT, GameState.BOSS_ROOM):
            if self._pending_next_room is not None and self.d.state.previous == GameState.LOADING:
                if self.d.game_map:
                    log.info("[地图] 进入 room %d", self._pending_next_room)
                    self.d.game_map.set_current(self._pending_next_room)
                self._pending_next_room = None
            self._trigger_room_skills()

        if s == GameState.PORTAL and self.d.game_map:
            # 防止 PORTAL↔COMBAT 抖动导致房间号重复推进：
            # 只在首次进入 PORTAL 时决定下一房间号，真正过门（LOADING→IN_ROOM）后才切换
            if self._pending_next_room is not None:
                return
            nxt = self.d.game_map.next_room_towards_boss()
            if nxt is not None:
                self._pending_next_room = nxt
                self.d.game_map.mark_cleared()
                log.info("[地图] 准备离开 room %d → room %d",
                         self.d.game_map.current_id, nxt)

        if s == GameState.LOADING:
            self._loading_frames = 0

    # ---- 房间特定技能 -----------------------------------------------------------
    def _trigger_room_skills(self) -> None:
        if self.d.game_map is None:
            return
        room = self.d.game_map.current()
        if room is None:
            return
        if room.id in self._room_skill_triggered:
            return

        class_name = self.d.character.name
        skill_names = room.on_enter_skills.get(class_name, [])
        if not skill_names:
            return

        self._room_skill_triggered.add(room.id)
        actions: list = []
        for sn in skill_names:
            seq = self.d.character.use_skill(sn)
            if seq:
                actions.extend(seq)
                actions.append(Wait(seconds=0.15))
        if actions:
            log.info("[room_skill] 房间 %d  职业 %s → %s", room.id, class_name, skill_names)
            self.d.queue.submit(actions)
