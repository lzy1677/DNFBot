# DNF 自动化工具 - 架构设计文档

> 最后更新：2026-05-03（状态机 v2 + 墙侧驱动传送门策略）

## Context

构建一个 DNF（地下城与勇士）游戏自动化工具，实现实时画面检测 + 自动操作。支持多地图形状适配和多职业技能扩展。
技术栈：Python 3.8+ · YOLOv8 (ultralytics) · Win32 SendInput · DXCam / mss。

---

## 整体架构（分层设计）

```
┌─────────────────────────────────────────────────────────┐
│                     main.py（入口）                       │
│   --verbose / --dry-run / --settings / --no-skip-dungeon │
├─────────────────────────────────────────────────────────┤
│                   GameBot（主控制器）                      │
│     状态机驱动，20 Hz 主循环，心跳日志                      │
│     LOADING 暗屏检测 / Boss 房地图覆盖 / 重新挑战超时       │
├──────────────────────────────┬──────────────────────────┤
│  决策层 Strategy              │  核心层 Core              │
│  ├── CombatStrategy          │  ├── GameState (枚举)     │
│  ├── NavigationStrategy      │  ├── StateMachine        │
│  ├── LootStrategy            │  └── EventBus            │
│  ├── PortalStrategy (墙侧)    │                          │
│  └── RecoveryStrategy        │                          │
├──────────────────────────────┼──────────────────────────┤
│  感知层 Vision                │  执行层 Action            │
│  ├── ScreenCapture           │  ├── InputDriver         │
│  │     (dxcam / mss)        │  │     (Win32 SendInput) │
│  ├── YOLODetector            │  ├── ActionQueue         │
│  │     (ultralytics)        │  │     (worker thread)   │
│  ├── GameStateParser         │  └── Skill / SkillSet    │
│  │     (debounce N帧)       │                          │
│  └── MinimapReader           │                          │
│        (HSV 检测定位)        │                          │
├──────────────────────────────┼──────────────────────────┤
│  职业层 Classes               │  地图层 Maps              │
│  ├── BaseClass (ABC)         │  ├── BaseMap (BFS)       │
│  ├── Berserker               │  ├── Room / RoomType     │
│  └── Elementalist            │  └── map_loader          │
├─────────────────────────────────────────────────────────┤
│  配置层 Config（YAML + extends 继承）                      │
│  ├── settings.yaml           ├── classes/base.yaml      │
│  ├── maps/dungeon_01.yaml    └── classes/berserker.yaml │
└─────────────────────────────────────────────────────────┘
```

---

## 项目目录结构

```
DNFBot/
├── main.py                        # 入口（--verbose / --dry-run / --no-skip-dungeon）
├── requirements.txt
├── ARCHITECTURE.md
│
├── config/
│   ├── settings.yaml              # 全局配置
│   ├── maps/
│   │   ├── base.yaml              # 地图继承基础模板
│   │   └── dungeon_01.yaml        # 格蓝迪发电站（9 间房，含 Boss 房）
│   └── classes/
│       ├── base.yaml              # 职业继承基础模板
│       ├── berserker.yaml         # 狂战士
│       └── elementalist.yaml      # 元素师
│
├── core/
│   ├── bot.py                     # GameBot：from_settings 工厂 + 主循环
│   ├── state.py                   # GameState 枚举 + StateMachine
│   └── event_bus.py               # 轻量事件总线
│
├── vision/
│   ├── capture.py                 # ScreenCapture（dxcam 优先，回退 mss）
│   ├── detector.py                # YOLODetector（warmup + detect）
│   ├── game_state_parser.py       # 检测结果 → GameState（confirm_frames 防抖）
│   └── minimap_reader.py          # 小地图 HSV 检测，房间级定位
│
├── action/
│   ├── input_driver.py            # Win32 SendInput 扫描码键鼠驱动
│   ├── action_queue.py            # ActionQueue（daemon worker thread）
│   │                              # Action / KeyPress / KeyHold / Move /
│   │                              # Wait / MouseClick / Callback
│   └── skill.py                   # Skill（冷却）+ SkillSet（优先级查询）
│
├── strategy/
│   ├── base.py                    # Strategy ABC + StrategyContext
│   ├── combat.py                  # 战斗（贴脸 + 技能优先级）
│   ├── loot.py                    # 拾取（向最近物品移动 + pickup 键）
│   ├── navigation.py              # 导航（沿 optimal_path 移动）
│   ├── portal.py                  # 传送门（墙侧驱动：地图方向 + bbox 比例）
│   └── recovery.py                # 恢复（结算自动重试 + 卡死抖动解卡）
│
├── classes/
│   ├── base_class.py              # BaseClass ABC + build_class + _REGISTRY
│   ├── berserker.py               # 狂战士（@register_class）
│   └── elementalist.py            # 元素师（@register_class）
│
├── maps/
│   ├── base_map.py                # BaseMap（BFS 最短路 + optimal_path 导航）
│   ├── room.py                    # Room + RoomType 枚举
│   └── map_loader.py              # load_map（YAML → BaseMap，支持方向字段）
│
├── utils/
│   ├── config.py                  # load_yaml / deep_merge / load_with_base
│   ├── logger.py                  # setup_logging（verbose 复调更新级别）
│   └── timer.py                   # Cooldown / RateLimiter / Stopwatch
│
├── data/
│   └── video_to_pic.py            # MKV → 帧图片（数据集制作工具）
│
├── train/
│   ├── train.py                   # YOLOv8n/s 训练脚本
│   └── prepare_dataset.py         # 数据集整理
│
└── tests/                         # 单元测试（202 个，pytest）
    ├── test_state_machine.py
    ├── test_game_state_parser.py
    ├── test_detector.py
    ├── test_capture.py
    ├── test_input_driver.py
    ├── test_action_queue.py
    ├── test_strategies.py
    ├── test_map.py
    ├── test_classes.py
    ├── test_event_bus.py
    ├── test_utils.py
    ├── test_bot_dryrun.py
    └── test_yolo_realtime.py      # 实时检测预览（需要真实模型）
```

---

## 核心模块设计

### 1. 状态机（v2）

状态分为两类：

| 类型 | 状态 | 判断方式 |
|------|------|----------|
| 检测驱动 | IN_ROOM, COMBAT, LOOTING, NAVIGATING, PORTAL, BOSS_ROOM, RESULT_SCREEN, LOADING, UNKNOWN | YOLO 检测 + 启发式（暗屏） |
| 动作驱动 | IDLE, IN_TOWN, ENTERING_DUNGEON | Bot 在执行动作序列时直接设置 |

```
                    ┌──── 检测驱动（YOLO + 启发式）────┐
                    │                                  │
IN_TOWN ──(动作)──→ ENTERING_DUNGEON ──(动作完成)──→ LOADING
  ↑                                                    │
  │                                                    ↓
  │             ┌───────────────── IN_ROOM ←───────────┘
  │             │                     │
  │             │         ┌───────────┼───────────┐
  │             │         ▼           ▼           ▼
  │             │     COMBAT      LOOTING    NAVIGATING
  │             │         │           │           │
  │             │         ├───────────┤           │
  │             │         ▼           ▼           │
  │             │     LOOTING ←── IN_ROOM        │
  │             │         │           │           │
  │             │         └───────────┘           │
  │             │                                 ▼
  │             │                              PORTAL
  │             │                                 │
  │             │                                 ▼
  │             │                              LOADING ──→ 回到 IN_ROOM
  │             │
  │             ▼
  │       BOSS_ROOM → COMBAT → LOOTING → RESULT_SCREEN
  │                                           │
  └── (动作：再次挑战失败) ◀────────────────────┘
  │
  └── (动作：再次挑战成功) → LOADING → IN_ROOM

任意状态 ──(超时卡死)──→ UNKNOWN ──(恢复)──→ 回原状态
```

状态枚举（12 个）：

```python
# core/state.py
class GameState(Enum):
    IDLE / IN_TOWN / ENTERING_DUNGEON / LOADING
    IN_ROOM / COMBAT / LOOTING / NAVIGATING
    PORTAL / BOSS_ROOM / RESULT_SCREEN / UNKNOWN
```

转移表：

```python
_TRANSITIONS = {
    IDLE:              {IN_TOWN},
    IN_TOWN:           {ENTERING_DUNGEON},
    ENTERING_DUNGEON:  {LOADING, IN_ROOM},
    LOADING:           set(GameState),          # 开放（启发式检测可能误判）
    IN_ROOM:           {COMBAT, LOOTING, PORTAL, NAVIGATING, BOSS_ROOM},
    COMBAT:            {IN_ROOM, LOOTING, BOSS_ROOM},
    LOOTING:           {IN_ROOM, NAVIGATING, COMBAT},
    NAVIGATING:        {COMBAT, LOOTING, PORTAL, IN_ROOM, BOSS_ROOM},
    PORTAL:            {LOADING, IN_ROOM, COMBAT},
    BOSS_ROOM:         {COMBAT, LOOTING, RESULT_SCREEN},
    RESULT_SCREEN:     {LOADING, IN_TOWN, ENTERING_DUNGEON},
    UNKNOWN:           set(GameState),
}
```

### 2. GameBot 主循环

```python
# core/bot.py  —  20 Hz，每 5 秒打一次心跳日志
while running:
    frame   = capture.grab()              # ~1ms (dxcam)
    dets    = detector.detect(frame)      # ~10-15ms (YOLOv8n GPU)

    if _is_loading(frame, dets):          # 暗屏 + 检测数 ≤ 1 → LOADING
        state = LOADING
    else:
        state = parser.parse(dets)        # confirm_frames=3 防抖

    if state == COMBAT and _is_boss_room():  # 地图覆盖：Boss 房 + 有怪 → BOSS_ROOM
        state = BOSS_ROOM

    if state != sm.current:
        sm.transition(state)
        bus.emit("state_change", state)

    if sm.current == RESULT_SCREEN and sm.time_in_state() > 30:
        sm.transition(IN_TOWN, force=True)   # 重新挑战超时放弃

    strategy = strategies[sm.current]
    if not queue.is_busy():
        actions = strategy.decide(ctx)
        queue.submit(actions)
```

`--skip-dungeon` 默认为 `True`：假设角色已在副本内，直接从 `IN_ROOM` 启动。
`--no-skip-dungeon` 从 `IDLE` 启动完整进图流程。

### 3. 感知层 — YOLO 检测

训练目标类别：

| 类别 | 说明 |
|------|------|
| `monster` | 普通怪物 |
| `item` | 掉落物品 |
| `portal` | 传送门 |
| `player` | 自身角色 |
| `ui_button` | 通关/重新挑战按钮 |
| `stone` | 可破坏物品（处理时视作 monster） |

`GameStateParser` 推断规则（优先级从高到低）：

```
1. ui_button 可见           → RESULT_SCREEN
2. monster / stone 可见     → COMBAT   （Boss 房由 bot.py 地图覆盖）
3. item 可见，无怪无stone   → LOOTING
4. portal 可见（≥1），无怪无物 → PORTAL
5. player 可见，无其他       → IN_ROOM
6. 画面空（无有效检测）      → NAVIGATING
```

LOADING 状态由 `bot.py` 独立检测：BGR 均值 < 50 + 检测数 ≤ 1 + 3 帧确认。

`confirm_frames=3`：连续 N 帧相同结果才真正切换，防止单帧误检抖动。

### 4. 执行层 — ActionQueue

```
主循环线程          ActionQueue worker 线程
    │                       │
    │── queue.submit([...]) ─►│ deque 追加
    │                       │── action.execute(driver)
    │                       │      KeyPress → driver.press(key, dur)
    │                       │      Move     → driver.move_direction(dir, dur)
    │                       │      Wait     → time.sleep(sec)
    │                       │      Callback → fn()
```

队列忙时主循环跳过策略决策（`RESULT_SCREEN` / `UNKNOWN` 状态除外，可被恢复策略打断）。

### 5. 传送门策略（墙侧驱动）

PortalStrategy 根据**门所在墙侧**（而非玩家-门相对偏移）计算助跑位，避免门框碰撞体挡路。

**墙侧判断（两优先级）：**
1. 地图连接方向：`direction_to(current_id, next_room_id)` — 绝对正确
2. Bbox 宽高比兜底：`w >= h` → 左右墙 + 画面位置判断左/右；`h > w` → 上下墙 + 画面位置判断上/下

**按墙侧计算助跑位：**

```
右墙门 (dir=right)：助跑位 = (portal.x - 3*player_w, portal.y)，冲入方向 = right
左墙门 (dir=left)： 助跑位 = (portal.x + 3*player_w, portal.y)，冲入方向 = left
上墙门 (dir=up)：   助跑位 = (portal.x, portal.y + 1*player_h)，冲入方向 = up
下墙门 (dir=down)： 助跑位 = (portal.x, portal.y - 1*player_h)，冲入方向 = down
```

分两步：移动到助跑位 → 向门方向冲刺。玩家在右上角、右墙门在下方时，会先向左脱离门框，再向下对齐，最后向右冲入。

### 6. 职业系统

```python
# classes/base_class.py
@register_class("berserker")
class Berserker(BaseClass):
    def get_attack_sequence(self, ctx: CombatContext) -> List[Action]:
        # 1. 距离 > 120px → 先贴脸（approach）
        # 2. boss_present → 优先大招（awakening > skill_3 > skill_2）
        # 3. 最高优先级就绪技能（priority >= 1）
        # 4. 否则 A 键普通攻击
```

- **技能冷却**：`Skill._cd = Cooldown(duration)`，`ready()` / `trigger()` 管理。
- **Buff 序列**：`get_buff_sequence()` 把 `priority < 0` 的技能全部触发一遍（进房首次执行）。
- **扩展新职业**：新建 `classes/xxx.py`，`@register_class("xxx")` 装饰，在 `config/classes/xxx.yaml` 写技能配置，`settings.yaml` 改 `character_class: xxx`。

职业 YAML 格式（支持 `extends: base.yaml` 继承）：
```yaml
extends: base.yaml
name: 狂战士
keys:
  attack: x
  skill_1: {key: a, cooldown: 5.0, priority: 3, desc: 崩山击}
  buff_1:  {key: q, cooldown: 180.0, priority: -1, desc: 血气之刃}
combo_chains:
  - [attack, attack, skill_1]
```

### 7. 地图系统

房间支持四种类型：`start / normal / elite / boss`。

连接格式支持带方向：
```yaml
connections:
  - {id: 1, dir: right}
```

`BaseMap` 导航逻辑：
1. 按 `optimal_path` 列表顺序推进；
2. 当前位置不在路径上时，退化为 BFS 到 Boss 房的最短路。

小地图修正：每 0.5s 通过 HSV 颜色检测读取小地图，发现房间 ID 与记录不符时自动修正 `game_map.current_id`。

Boss 房识别：`bot.py` 在每帧检查 `current_room.type == RoomType.BOSS`，有怪时将 parser 的 `COMBAT` 覆盖为 `BOSS_ROOM`。

```yaml
# config/maps/dungeon_01.yaml（格蓝迪发电站）
name: 格蓝迪发电站
start_id: 0
optimal_path: [0, 1, 2, 3, 6, 7, 8]
rooms:
  - {id: 0, type: start, connections: [{id: 1, dir: right}]}
  - {id: 1, type: normal, connections: [{id: 0, dir: left}, {id: 2, dir: right}]}
  # ... 共 9 间房，含 Boss (id: 8)
```

### 8. 恢复策略

`RecoveryStrategy` 处理两种异常情况：

- **结算画面**：检测到 `ui_button` → 按 page_down 自动重新挑战。超时 30s 后 bot.py 强制回 IN_TOWN（疲劳耗尽/装备损坏）。
- **卡死**：`UNKNOWN` 状态停留超过 `stuck_seconds`（默认 8s）→ 左右各抖动 0.15s + 跳一下。

### 9. 键盘驱动

使用 `ctypes` 直接调用 Win32 `SendInput`，发送**扫描码**（非虚拟键码），兼容大多数游戏的键盘钩子保护：

```python
# action/input_driver.py
driver.press("q", duration=0.04)          # 单键点按
driver.hold("right", duration=0.3)        # 长按
driver.move_direction("right,up", 0.2)    # 斜向（逗号分隔）
driver.mouse_click(x=640, y=360)          # 绝对坐标点击
```

---

## 日志与调试

| 运行方式 | 日志级别 | 说明 |
|----------|---------|------|
| `python main.py` | INFO | 初始化步骤 + 状态切换 + 5s 心跳 |
| `python main.py --verbose` | DEBUG | 每帧耗时 + 检测结果 + 动作队列详情 |
| `python main.py --dry-run` | INFO | 只初始化，验证配置是否正常，不进主循环 |
| `python main.py --no-skip-dungeon` | INFO | 从 IDLE 启动完整进图流程（默认 skip） |

`settings.yaml` 等效开关：`logging.verbose: true`。

心跳日志示例（INFO，每 5 秒）：
```
[心跳] 运行 30s | 状态: combat            | 队列: 2 | FPS: 59.8 | 推理: 11.2ms
```

---

## 训练流程

```bash
# 1. 录制游戏视频，提取帧
python data/video_to_pic.py          # MKV → frames/  (默认 3 fps)

# 2. 用 LabelImg 等工具标注，整理为 YOLO 格式
python train/prepare_dataset.py

# 3. 训练
python train/train.py --model yolov8n --epochs 200 --device 0

# 4. 把最优权重复制到 vision/models/
cp runs/detect/train/runs/yolov8n/weights/best.pt vision/models/dnf_v1.pt

# 5. 用实时预览脚本验证
python tests/test_yolo_realtime.py --model vision/models/dnf_v1.pt --window "地下城与勇士"
```

---

## 单元测试

```bash
# 全部测试（不含需要真实 GPU 的实时测试）
python -m pytest tests/ --ignore=tests/test_yolo_realtime.py -v

# 只跑纯逻辑（无任何外部依赖，最快）
python -m pytest tests/test_state_machine.py tests/test_game_state_parser.py \
                 tests/test_strategies.py tests/test_map.py tests/test_classes.py \
                 tests/test_event_bus.py tests/test_utils.py -v
```

覆盖范围：状态机、GameStateParser、YOLODetector（mock）、ScreenCapture（mock）、
InputDriver（mock SendInput）、ActionQueue 多线程、五种策略、BaseMap BFS 寻路、
Berserker/Elementalist 职业、EventBus 线程安全、Cooldown/RateLimiter、GameBot 集成。

---

## 关键依赖

```
ultralytics   # YOLOv8 推理 + 训练
dxcam         # 高速截图（Desktop Duplication API）
mss           # 截图备选（跨平台）
pyyaml        # 配置文件
numpy
opencv-python
ctypes        # Win32 SendInput（Python 内置）
pytest        # 单元测试
```
