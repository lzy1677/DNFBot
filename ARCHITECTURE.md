# DNF 自动化工具 - 架构设计文档

> 最后更新：2026-04-26（与代码实际实现同步）

## Context

构建一个 DNF（地下城与勇士）游戏自动化工具，实现实时画面检测 + 自动操作。支持多地图形状适配和多职业技能扩展。
技术栈：Python 3.8+ · YOLOv8 (ultralytics) · Win32 SendInput · DXCam / mss。

---

## 整体架构（分层设计）

```
┌─────────────────────────────────────────────────────────┐
│                     main.py（入口）                       │
│         --verbose / --dry-run / --settings              │
├─────────────────────────────────────────────────────────┤
│                   GameBot（主控制器）                      │
│          状态机驱动，20 Hz 主循环，心跳日志                  │
├──────────────────────────────┬──────────────────────────┤
│  决策层 Strategy              │  核心层 Core              │
│  ├── CombatStrategy          │  ├── GameState (枚举)     │
│  ├── NavigationStrategy      │  ├── StateMachine        │
│  ├── LootStrategy            │  └── EventBus            │
│  ├── PortalStrategy          │                          │
│  └── RecoveryStrategy        │                          │
├──────────────────────────────┼──────────────────────────┤
│  感知层 Vision                │  执行层 Action            │
│  ├── ScreenCapture           │  ├── InputDriver         │
│  │     (dxcam / mss)        │  │     (Win32 SendInput) │
│  ├── YOLODetector            │  ├── ActionQueue         │
│  │     (ultralytics)        │  │     (worker thread)   │
│  └── GameStateParser         │  └── Skill / SkillSet    │
│        (debounce N帧)        │                          │
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

## 项目目录结构（实际）

```
DNFBot/
├── main.py                        # 入口（--verbose / --dry-run）
├── requirements.txt
├── ARCHITECTURE.md
│
├── config/
│   ├── settings.yaml              # 全局配置
│   ├── maps/
│   │   ├── base.yaml              # 地图继承基础模板
│   │   └── dungeon_01.yaml        # 格兰之森（6 间房 + 隐藏房）
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
│   └── game_state_parser.py       # 检测结果 → GameState（confirm_frames 防抖）
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
│   ├── portal.py                  # 传送门（按目标房间类型偏好选门）
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
└── tests/                         # 单元测试（201 个，pytest）
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

### 1. 状态机

```
IDLE → IN_TOWN → ENTERING_DUNGEON → IN_ROOM ⇄ COMBAT ⇄ LOOTING
                                         ↓
                                    NAVIGATING → PORTAL_SELECT
                                                      ↓
                                               BOSS_ROOM → RESULT_SCREEN
                              LOADING / UNKNOWN 可进出任意状态
```

每个状态对应一个 `Strategy`，由 `GameStateParser` 每帧推断，
`StateMachine.transition()` 根据合法转移表决定是否切换（`force=True` 可绕过）。

启动参数中添加skip_entering_dugeon, 初始状态从in_room开始

```python
# core/state.py
class GameState(Enum):
    IDLE / IN_TOWN / ENTERING_DUNGEON / IN_ROOM / COMBAT
    LOOTING / NAVIGATING / PORTAL_SELECT / BOSS_ROOM
    RESULT_SCREEN / LOADING / UNKNOWN
```

### 2. GameBot 主循环

```python
# core/bot.py  —  20 Hz，每 5 秒打一次心跳日志
while running:
    frame   = capture.grab()              # ~1ms (dxcam)
    dets    = detector.detect(frame)      # ~10-15ms (YOLOv8n GPU)
    state   = parser.parse(dets)          # confirm_frames=3 防抖

    if state != sm.current:
        sm.transition(state)              # 验证合法性后切换
        bus.emit("state_change", state)

    strategy = strategies[sm.current]
    if not queue.is_busy():               # 队列空闲才下发新动作
        actions = strategy.decide(ctx)
        queue.submit(actions)
```

`--verbose` / `logging.verbose: true` 时每帧打印：
```
[tick] cap=0.8ms  infer=11.2ms  dets=3  parser→combat  cur=combat
[策略] combat → ['approach', 'skill:q']
[action] ▶ skill:q   [action] ✓ skill:q (42ms)
```

### 3. 感知层 — YOLO 检测

训练目标类别：

| 类别 | 说明 |
|------|------|
| `monster` | 普通怪物 |
| `item` | 掉落物品 |
| `portal` | 普通传送门 |
| `player` | 自身角色 |
| `ui_button` | 通关标识 |
| `stone` | 可破坏物品，实际处理时可以当作monster |

`GameStateParser` 推断规则（优先级从高到低）：
1. 检测到 `ui_button` → `RESULT_SCREEN`
2. 检测到 ≥2 个传送门 → `PORTAL_SELECT`
3. 检测到 怪物，stone → `COMBAT`
4. 检测到物品、无怪、无stone → `LOOTING`
5. 检测到 无物品，无怪，无stone → `NAVIGATING`
6. 检测到 `player` 无怪无物 → `IN_ROOM`
7. 其他 → `UNKNOWN`

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

### 5. 职业系统

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

### 6. 地图系统

房间支持四种类型：`start / normal / elite / boss 。

连接格式支持纯 id 或带方向：
```yaml
connections:
  - {id: 1, dir: right}   # 带方向
  - 2                     # 纯 id（方向由 id 大小推断）
```

`BaseMap` 导航逻辑：
1. 按 `optimal_path` 列表顺序推进；
2. 当前位置不在路径上时，退化为 BFS 到 Boss 房的最短路。

```yaml
# config/maps/dungeon_01.yaml（已实现）
name: 格兰之森
start_id: 0
optimal_path: [0, 1, 3, 5]
rooms:
  - {id: 0, type: start,  connections: [{id: 1, dir: right}]}
  - {id: 1, type: normal, connections: [{id: 0, dir: left}, {id: 2, dir: up}, {id: 3, dir: right}]}
  - {id: 2, type: normal, connections: [{id: 1, dir: down}]}
  - {id: 3, type: elite,  connections: [{id: 1, dir: left}, {id: 4, dir: up},  {id: 5, dir: right}]}
  - {id: 4, type: hidden, connections: [{id: 3, dir: down}]}
  - {id: 5, type: boss,   connections: [{id: 3, dir: left}]}
```

### 7. 传送门策略

`PortalStrategy` 根据**目标房间类型**选择偏好的门类型：

所有传送门是相同的，所以不存在传送门策略。实际工作时，优先按照地图配置寻找，如果地图配置路径中无法找到传送门，则按照最短路径寻路到boss

### 8. 恢复策略

`RecoveryStrategy` 处理两种异常情况：
- **结算画面**：检测到 `ui_button` → 按 page_down 自动重新挑战；
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

## 实施进度

### Phase 1 — 基础框架 ✅
- 项目结构、YAML 配置（含 `extends` 继承）、日志（verbose 开关）
- ScreenCapture（dxcam/mss 自动回退）
- Win32 SendInput 输入驱动
- StateMachine + EventBus

### Phase 2 — 感知能力 ✅
- YOLODetector（warmup + 推理日志）
- GameStateParser（规则推断 + confirm_frames 防抖）
- 数据集工具（video_to_pic.py）+ 训练脚本（train.py）
- 模型已训练：`vision/models/dnf_v1.pt`

### Phase 3 — 核心策略 ✅
- 5 个策略全部实现：Combat / Loot / Navigation / Portal / Recovery
- 2 个职业：Berserker + Elementalist
- 1 个地图：dungeon_01（格兰之森，含隐藏房）

### Phase 4 — 扩展 🔄 进行中
- [ ] 更多地图配置
- [ ] 更多职业（剑魂、鬼泣等）
- [ ] 小地图识别辅助定位（当前纯靠传送门检测）
- [ ] 异常截图自动保存（用于后续标注迭代）

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
