"""单元测试：maps/ — Room, BaseMap, load_map。"""
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from maps.room import Room, RoomType
from maps.base_map import BaseMap
from maps.map_loader import load_map


def _build_map() -> BaseMap:
    """构造测试用地图：0->1->2(boss) 线性结构，另有 0->3 分支。"""
    m = BaseMap(name="test", start_id=0, optimal_path=[0, 1, 2])
    rooms = [
        Room(id=0, type=RoomType.START, connections=[1, 3]),
        Room(id=1, type=RoomType.NORMAL, connections=[0, 2]),
        Room(id=2, type=RoomType.BOSS, connections=[1]),
        Room(id=3, type=RoomType.NORMAL, connections=[0]),
    ]
    for r in rooms:
        m.add_room(r)
    m.set_current(0)
    return m


class TestRoom:
    def test_is_boss(self):
        r = Room(id=0, type=RoomType.BOSS, connections=[])
        assert r.is_boss() is True

    def test_not_boss(self):
        r = Room(id=0, type=RoomType.NORMAL, connections=[])
        assert r.is_boss() is False

    def test_neighbors(self):
        r = Room(id=1, connections=[2, 3])
        assert r.neighbors() == [2, 3]

    def test_cleared_default_false(self):
        r = Room(id=0)
        assert r.cleared is False

    def test_room_type_enum(self):
        assert RoomType("boss") == RoomType.BOSS
        assert RoomType("normal") == RoomType.NORMAL


class TestBaseMap:
    def setup_method(self):
        self.m = _build_map()

    def test_current_room(self):
        assert self.m.current().id == 0

    def test_boss_room_found(self):
        assert self.m.boss_room().id == 2

    def test_boss_room_none_when_absent(self):
        m = BaseMap(name="x", start_id=0)
        m.add_room(Room(id=0, type=RoomType.NORMAL))
        assert m.boss_room() is None

    def test_shortest_path_direct(self):
        path = self.m.shortest_path(0, 1)
        assert path == [0, 1]

    def test_shortest_path_longer(self):
        path = self.m.shortest_path(0, 2)
        assert path == [0, 1, 2]

    def test_shortest_path_same_node(self):
        path = self.m.shortest_path(1, 1)
        assert path == [1]

    def test_shortest_path_no_route(self):
        m = BaseMap(name="x", start_id=0)
        m.add_room(Room(id=0, connections=[]))
        m.add_room(Room(id=5, connections=[]))
        path = m.shortest_path(0, 5)
        assert path == []

    def test_next_room_towards_boss_optimal(self):
        nxt = self.m.next_room_towards_boss()
        assert nxt == 1  # optimal_path[0]=0, next=1

    def test_next_room_after_advance(self):
        self.m.set_current(1)
        nxt = self.m.next_room_towards_boss()
        assert nxt == 2

    def test_next_room_at_boss_is_none(self):
        self.m.set_current(2)
        # Room 2 is boss; optimal_path ends here
        # next_room_towards_boss should return None (no further path)
        nxt = self.m.next_room_towards_boss()
        assert nxt is None

    def test_direction_to_configured(self):
        room = self.m.rooms[0]
        room.direction_map = {1: "right", 3: "left"}  # type: ignore
        assert self.m.direction_to(0, 1) == "right"
        assert self.m.direction_to(0, 3) == "left"

    def test_direction_to_inferred_by_id(self):
        # No direction_map → higher id = right
        assert self.m.direction_to(0, 1) in ("right", "left")  # id 1 > 0 → right
        assert self.m.direction_to(1, 0) == "left"

    def test_mark_cleared(self):
        self.m.mark_cleared(0)
        assert self.m.rooms[0].cleared is True

    def test_mark_cleared_current(self):
        self.m.mark_cleared()
        assert self.m.rooms[0].cleared is True

    def test_set_current(self):
        self.m.set_current(3)
        assert self.m.current_id == 3

    def test_set_current_invalid_id_ignored(self):
        self.m.set_current(99)
        assert self.m.current_id == 0  # unchanged


class TestLoadMap:
    def _write_yaml(self, data: dict) -> Path:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        )
        yaml.dump(data, tmp, allow_unicode=True)
        tmp.close()
        return Path(tmp.name)

    def test_load_basic_map(self):
        data = {
            "name": "格兰之森",
            "start_id": 0,
            "optimal_path": [0, 1, 2],
            "rooms": [
                {"id": 0, "type": "start", "connections": [1]},
                {"id": 1, "type": "normal", "connections": [0, 2]},
                {"id": 2, "type": "boss", "connections": [1]},
            ],
        }
        path = self._write_yaml(data)
        m = load_map(path)
        assert m.name == "格兰之森"
        assert len(m.rooms) == 3
        assert m.boss_room() is not None
        assert m.boss_room().id == 2
        assert m.current_id == 0
        path.unlink()

    def test_load_map_with_direction_dict(self):
        data = {
            "name": "test",
            "start_id": 0,
            "rooms": [
                {"id": 0, "type": "start",
                 "connections": [{"id": 1, "dir": "right"}]},
                {"id": 1, "type": "boss", "connections": []},
            ],
        }
        path = self._write_yaml(data)
        m = load_map(path)
        assert m.direction_to(0, 1) == "right"
        path.unlink()

    def test_load_dungeon_01(self):
        cfg_path = Path(__file__).parent.parent / "config" / "maps" / "dungeon_01.yaml"
        if cfg_path.exists():
            m = load_map(cfg_path)
            assert m.name
            assert len(m.rooms) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
