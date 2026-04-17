# DNF 自动化工具 - 架构设计方案

## Context
构建一个DNF（地下城与勇士）游戏自动化工具，实现实时画面检测 + 自动操作。需要支持多地图形状适配和多职业技能扩展。技术栈：Python + YOLOv8 + Win32 API键盘模拟。

## 整体架构（分层设计）

```
┌─────────────────────────────────────────────────┐
│                   主控制器 (GameBot)              │
│          状态机驱动，协调各模块工作                  │
├─────────────────────────────────────────────────┤
│  决策层 (Strategy)                               │
│  ├── CombatStrategy    - 战斗决策                │
│  ├── NavigationStrategy - 过图/选门决策           │
│  └── LootStrategy      - 拾取决策                │
├─────────────────────────────────────────────────┤
│  感知层 (Vision)        │  执行层 (Action)        │
│  ├── ScreenCapture     │  ├── KeyboardDriver     │
│  ├── YOLODetector      │  ├── MouseDriver        │
│  └── GameStateParser   │  └── ActionQueue        │
├─────────────────────────────────────────────────┤
│  配置层 (Config)                                 │
│  ├── maps/             - 地图配置（YAML）         │
│  ├── classes/           - 职业技能配置（YAML）     │
│  └── settings.yaml     - 全局设置                │
└─────────────────────────────────────────────────┘
```

## 项目目录结构

```
dnf/
├── main.py                     # 入口
├── requirements.txt
├── config/
│   ├── settings.yaml           # 全局配置（截图区域、检测阈值等）
│   ├── maps/
│   │   ├── base.yaml           # 地图基础模板
│   │   ├── dungeon_01.yaml     # 具体地图配置（房间布局、传送门位置规则）
│   │   └── ...
│   └── classes/
│       ├── base.yaml           # 职业基础模板
│       ├── berserker.yaml      # 狂战士技能配置
│       ├── elementalist.yaml   # 元素师技能配置
│       └── ...
├── core/
│   ├── bot.py                  # GameBot 主控制器（状态机）
│   ├── state.py                # 游戏状态枚举与状态机定义
│   └── event_bus.py            # 事件总线，模块间通信
├── vision/
│   ├── capture.py              # 屏幕截图（Win32 API / DXCam）
│   ├── detector.py             # YOLO 推理封装
│   ├── game_state_parser.py    # 从检测结果解析游戏状态
│   └── models/                 # YOLO 模型权重
│       └── dnf_v1.pt
├── strategy/
│   ├── base.py                 # 策略基类
│   ├── combat.py               # 战斗策略（调用职业技能链）
│   ├── navigation.py           # 过图导航策略
│   ├── loot.py                 # 拾取策略
│   └── portal.py               # 传送门选择策略
├── action/
│   ├── input_driver.py         # Win32 SendInput 键盘/鼠标模拟
│   ├── action_queue.py         # 操作队列（防止指令冲突）
│   └── skill.py                # 技能抽象（冷却、连招）
├── classes/                    # 职业实现
│   ├── base_class.py           # 职业基类（定义技能列表、连招接口）
│   ├── berserker.py            # 狂战士
│   └── elementalist.py         # 元素师
├── maps/                       # 地图逻辑
│   ├── base_map.py             # 地图基类（房间数、路径规划接口）
│   ├── map_loader.py           # 从YAML加载地图配置
│   └── room.py                 # 房间抽象
└── utils/
    ├── logger.py
    └── timer.py
```

## 核心模块设计

### 1. 状态机（核心驱动）

游戏流程用有限状态机管理：

```
IDLE → IN_TOWN → ENTERING_DUNGEON → IN_ROOM → COMBAT → LOOTING
  → NAVIGATING → PORTAL_SELECT → BOSS_ROOM → RESULT_SCREEN → RETRY_OR_EXIT
```

每个状态对应一个处理逻辑，由 `GameStateParser` 检测当前状态，状态机驱动对应 Strategy 执行。

```python
# core/state.py
class GameState(Enum):
    IDLE = "idle"
    IN_TOWN = "in_town"
    IN_ROOM = "in_room"          # 房间内，无怪
    COMBAT = "combat"            # 房间内，有怪
    LOOTING = "looting"          # 拾取阶段
    NAVIGATING = "navigating"    # 移动到下一个房间
    PORTAL_SELECT = "portal"     # 选择传送门
    RESULT_SCREEN = "result"     # 结算画面
    LOADING = "loading"          # 加载中
```

### 2. 感知层 - YOLO检测

需要训练的目标类别：
- `monster` - 怪物
- `item` - 掉落物品
- `portal` - 传送门（分类型：普通/隐藏/Boss）
- `player` - 自身角色位置
- `minimap_arrow` - 小地图箭头/房间标记
- `ui_button` - UI按钮（再次挑战、确认等）
- `room_clear` - 通关标识

```python
# vision/detector.py
class YOLODetector:
    def __init__(self, model_path: str, conf_threshold: float = 0.5):
        self.model = YOLO(model_path)
    
    def detect(self, frame: np.ndarray) -> list[Detection]:
        """返回检测结果列表，每个包含 class, bbox, confidence"""
```

截图方案用 **DXCam**（比PIL/mss快很多，适合实时游戏截图）。

### 3. 职业系统（可扩展）

```python
# classes/base_class.py
class BaseClass(ABC):
    """职业基类"""
    def __init__(self, config_path: str):
        self.skills: list[Skill] = []       # 从YAML加载
        self.combo_chains: list[list] = []   # 连招链
    
    @abstractmethod
    def get_attack_sequence(self, context: CombatContext) -> list[Action]:
        """根据战斗上下文返回攻击序列"""
    
    @abstractmethod
    def get_buff_sequence(self) -> list[Action]:
        """开局buff序列"""
```

职业YAML配置示例：
```yaml
# config/classes/berserker.yaml
name: 狂战士
keys:
  attack: a
  jump: c
  skill_1: {key: q, cooldown: 5.0, priority: 3}
  skill_2: {key: w, cooldown: 8.0, priority: 2}
  skill_3: {key: e, cooldown: 15.0, priority: 1}
  awakening: {key: r, cooldown: 60.0, priority: 0}
combo_chains:
  - [attack, attack, skill_1]
  - [jump, attack, skill_2]
```

### 4. 地图/导航系统（可扩展）

用小地图识别当前位置和房间结构，每个地图配置房间连接关系：

```yaml
# config/maps/dungeon_01.yaml
name: 格兰之森
rooms:
  - id: 0
    type: start
    connections: [1]
  - id: 1
    type: normal
    connections: [0, 2, 3]
  - id: 2
    type: normal
    connections: [1]
  - id: 3
    type: boss
    connections: [1]
optimal_path: [0, 1, 3]   # 最优路径
```

导航策略通过小地图检测当前房间位置，按最优路径方向移动。

### 5. 传送门选择

```python
# strategy/portal.py
class PortalStrategy:
    def choose_portal(self, detections: list[Detection], map_config) -> Detection:
        """根据传送门类型和地图配置选择最优传送门"""
```

### 6. 键盘模拟（Win32 API SendInput）

使用 `ctypes` 调用 Win32 API `SendInput` 发送键盘/鼠标事件，无需额外驱动安装。

```python
# action/input_driver.py
import ctypes
from ctypes import wintypes

class InputDriver:
    """基于 Win32 SendInput 的键鼠模拟"""
    def press_key(self, key: str, duration: float = 0.05): ...
    def move(self, direction: str, duration: float): ...
    def combo(self, keys: list[tuple[str, float]]): ...  # 连招输入
```

## 主循环

```python
# main.py 核心逻辑
while running:
    frame = capture.grab()                    # ~1ms (DXCam)
    detections = detector.detect(frame)       # ~10-20ms (YOLOv8n GPU)
    state = state_parser.parse(detections)    # 判断当前状态
    
    match state:
        case GameState.COMBAT:
            actions = combat_strategy.decide(detections, current_class)
        case GameState.LOOTING:
            actions = loot_strategy.decide(detections)
        case GameState.NAVIGATING:
            actions = nav_strategy.decide(detections, current_map)
        case GameState.PORTAL_SELECT:
            actions = portal_strategy.decide(detections, current_map)
        case GameState.RESULT_SCREEN:
            actions = [Action("再次挑战按钮")]
    
    action_queue.execute(actions)
```

## 实施步骤

### Phase 1: 基础框架搭建
1. 项目结构、配置系统、日志
2. 屏幕截图模块（DXCam）
3. Win32 SendInput 输入模块
4. 状态机框架

### Phase 2: 感知能力
5. 收集截图数据、标注
6. 训练 YOLO 模型（先做怪物/物品/传送门检测）
7. GameStateParser 实现

### Phase 3: 核心策略
8. 战斗策略 + 一个职业实现
9. 拾取策略
10. 导航策略 + 一个地图配置

### Phase 4: 扩展
11. 更多职业配置
12. 更多地图配置
13. 传送门智能选择
14. 再次挑战/异常恢复

## 验证方式
- 截图模块：运行后确认能稳定 30+ FPS 截图
- YOLO检测：用测试截图验证检测精度
- 输入模块：在记事本中测试键盘输入是否生效
- 整体测试：选一个简单副本完整跑通一次流程

## 关键依赖
- `ultralytics` (YOLOv8)
- `dxcam` (高速截图)
- `ctypes` (Win32 SendInput，Python内置)
- `pyyaml` (配置文件)
- `numpy`, `opencv-python`
