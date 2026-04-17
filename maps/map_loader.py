"""从 YAML 加载地图配置。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from utils.config import load_with_base
from .base_map import BaseMap
from .room import Room, RoomType


def _parse_connection(conn: Any) -> tuple[int, str | None]:
    if isinstance(conn, int):
        return conn, None
    if isinstance(conn, dict):
        return int(conn["id"]), conn.get("dir")
    raise ValueError(f"bad connection: {conn}")


def load_map(path: str | Path) -> BaseMap:
    cfg = load_with_base(path)
    m = BaseMap(
        name=cfg.get("name", "unnamed"),
        start_id=int(cfg.get("start_id", 0)),
        optimal_path=list(cfg.get("optimal_path", [])),
    )
    for r in cfg.get("rooms", []):
        rtype = RoomType(r.get("type", "normal"))
        conns = []
        dir_map: Dict[int, str] = {}
        for c in r.get("connections", []):
            cid, d = _parse_connection(c)
            conns.append(cid)
            if d:
                dir_map[cid] = d
        room = Room(
            id=int(r["id"]),
            type=rtype,
            connections=conns,
            name=r.get("name", ""),
        )
        # 附加方向映射（BaseMap.direction_to 会读）
        setattr(room, "direction_map", dir_map)
        m.add_room(room)

    m.set_current(m.start_id)
    return m
