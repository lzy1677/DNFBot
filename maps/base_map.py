"""地图基类。封装房间图结构、最优路径、当前位置。"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .room import Room, RoomType


@dataclass
class BaseMap:
    name: str
    rooms: Dict[int, Room] = field(default_factory=dict)
    start_id: int = 0
    optimal_path: List[int] = field(default_factory=list)
    current_id: int = 0
    # 小地图检测配置（来自 YAML minimap 节点）
    minimap_cfg: Dict[str, Any] = field(default_factory=dict)
    # 各房间在小地图中的归一化坐标 {room_id: (x, y)}
    room_minimap_xy: Dict[int, Tuple[float, float]] = field(default_factory=dict)

    # ---- 构造 ----
    def add_room(self, room: Room) -> None:
        self.rooms[room.id] = room

    # ---- 查询 ----
    def get(self, rid: int) -> Optional[Room]:
        return self.rooms.get(rid)

    def current(self) -> Optional[Room]:
        return self.rooms.get(self.current_id)

    def boss_room(self) -> Optional[Room]:
        return next((r for r in self.rooms.values() if r.type == RoomType.BOSS), None)

    # ---- 导航 ----
    def shortest_path(self, src: int, dst: int) -> List[int]:
        if src == dst:
            return [src]
        visited = {src}
        parent: Dict[int, int] = {}
        q = deque([src])
        while q:
            u = q.popleft()
            room = self.rooms.get(u)
            if not room:
                continue
            for v in room.connections:
                if v in visited:
                    continue
                visited.add(v)
                parent[v] = u
                if v == dst:
                    path = [dst]
                    while path[-1] != src:
                        path.append(parent[path[-1]])
                    return list(reversed(path))
                q.append(v)
        return []

    def next_room_towards_boss(self) -> Optional[int]:
        """沿 optimal_path 选下一房间，若当前不在路径里则退化为 BFS 到 Boss。"""
        boss = self.boss_room()
        if boss is None:
            return None

        if self.optimal_path and self.current_id in self.optimal_path:
            i = self.optimal_path.index(self.current_id)
            if i + 1 < len(self.optimal_path):
                return self.optimal_path[i + 1]

        path = self.shortest_path(self.current_id, boss.id)
        return path[1] if len(path) >= 2 else None

    def direction_to(self, src: int, dst: int) -> Optional[str]:
        """根据房间连接信息推断方向；如未配置 direction 则按 id 相对大小粗略判断。"""
        room = self.rooms.get(src)
        if not room:
            return None
        # 若配置里是 connections: [{id: 1, dir: right}] 结构，由 loader 写入 room 扩展字段
        dirs = getattr(room, "direction_map", {})  # type: ignore[attr-defined]
        if dst in dirs:
            return dirs[dst]
        return "right" if dst > src else "left"

    def mark_cleared(self, rid: Optional[int] = None) -> None:
        r = self.rooms.get(rid if rid is not None else self.current_id)
        if r:
            r.cleared = True

    def set_current(self, rid: int) -> None:
        if rid in self.rooms:
            self.current_id = rid

    def sync_from_minimap(self, detected_id: int) -> bool:
        """小地图检测到的房间与当前记录不符时强制修正。返回 True 表示发生了修正。"""
        if detected_id not in self.rooms:
            return False
        if detected_id == self.current_id:
            return False
        self.current_id = detected_id
        return True
