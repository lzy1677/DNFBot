"""单元测试：vision/game_state_parser.py — GameStateParser。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state import GameState
from vision.detector import Detection
from vision.game_state_parser import GameStateParser, ParserConfig


def _det(class_name: str, conf: float = 0.9) -> Detection:
    return Detection(class_id=0, class_name=class_name, confidence=conf,
                     bbox=(0, 0, 10, 10))


def _parse_confirmed(parser: GameStateParser, detections, repeat: int = 3) -> GameState:
    """送入 repeat 帧相同检测结果，确保防抖窗口填满。"""
    result = GameState.UNKNOWN
    for _ in range(repeat):
        result = parser.parse(detections)
    return result


class TestParserConfig:
    def test_from_dict_defaults(self):
        cfg = ParserConfig.from_dict({})
        assert "monster" in cfg.monster_classes
        assert "item" in cfg.item_classes
        assert cfg.confirm_frames == 3

    def test_from_dict_override(self):
        cfg = ParserConfig.from_dict({
            "monster_classes": ["mob"],
            "confirm_frames": 5,
        })
        assert cfg.monster_classes == {"mob"}
        assert cfg.confirm_frames == 5


class TestGameStateParser:
    def setup_method(self):
        self.parser = GameStateParser(ParserConfig(confirm_frames=1))

    def test_empty_detections_returns_navigating(self):
        state = self.parser.parse([])
        assert state == GameState.NAVIGATING

    def test_monster_triggers_combat(self):
        state = self.parser.parse([_det("monster")])
        assert state == GameState.COMBAT

    def test_boss_in_monster_classes_triggers_combat(self):
        """Boss 房判断已移至 bot.py（地图驱动），parser 仅返回 COMBAT。"""
        parser = GameStateParser(ParserConfig(
            confirm_frames=1,
            monster_classes={"monster", "boss"},
        ))
        state = parser.parse([_det("boss")])
        assert state == GameState.COMBAT

    def test_unknown_class_returns_navigating(self):
        state = self.parser.parse([_det("boss")])
        assert state == GameState.NAVIGATING

    def test_items_no_monsters_triggers_looting(self):
        state = self.parser.parse([_det("item")])
        assert state == GameState.LOOTING

    def test_two_portals_triggers_portal(self):
        state = self.parser.parse([_det("portal"), _det("portal")])
        assert state == GameState.PORTAL

    def test_one_portal_triggers_portal(self):
        """单 portal 也触发 PORTAL（不再需要 ≥2）。"""
        state = self.parser.parse([_det("portal")])
        assert state == GameState.PORTAL

    def test_ui_button_triggers_result_screen(self):
        state = self.parser.parse([_det("ui_button")])
        assert state == GameState.RESULT_SCREEN

    def test_ui_takes_priority_over_monster(self):
        state = self.parser.parse([_det("ui_button"), _det("monster")])
        assert state == GameState.RESULT_SCREEN

    def test_player_alone_is_in_room(self):
        state = self.parser.parse([_det("player")])
        assert state == GameState.IN_ROOM

    def test_unrecognized_class_is_navigating(self):
        state = self.parser.parse([_det("room_clear")])
        assert state == GameState.NAVIGATING

    def test_debounce_confirm_frames(self):
        """用 LOOTING 测试 debounce（COMBAT 已绕过 debounce 直接切换）。"""
        parser = GameStateParser(ParserConfig(confirm_frames=3))
        # Frame 1 & 2: shouldn't confirm yet
        parser.parse([_det("item")])
        assert parser.confirmed == GameState.UNKNOWN
        parser.parse([_det("item")])
        assert parser.confirmed == GameState.UNKNOWN
        # Frame 3: now confirms
        parser.parse([_det("item")])
        assert parser.confirmed == GameState.LOOTING

    def test_debounce_resets_on_change(self):
        """用 PORTAL → LOOTING 测试 debounce 窗口重置（COMBAT 绕过 debounce）。"""
        parser = GameStateParser(ParserConfig(confirm_frames=3, portal_classes={"portal"}))
        parser.parse([_det("portal")])
        parser.parse([_det("portal")])
        # Different detection breaks the streak
        parser.parse([_det("item")])
        parser.parse([_det("portal")])
        # Still only 1 consecutive portal frame
        assert parser.confirmed == GameState.UNKNOWN

    def test_reset_clears_window(self):
        parser = GameStateParser(ParserConfig(confirm_frames=1))
        parser.parse([_det("monster")])
        assert parser.confirmed == GameState.COMBAT
        parser.reset()
        assert parser.confirmed == GameState.UNKNOWN

    def test_monster_beats_item(self):
        """Monster + item → COMBAT, not LOOTING."""
        state = self.parser.parse([_det("monster"), _det("item")])
        assert state == GameState.COMBAT

    def test_stone_triggers_combat(self):
        state = self.parser.parse([_det("stone")])
        assert state == GameState.COMBAT

    def test_gold_not_in_parser_item_classes(self):
        """gold is lootable in strategy but not a parser item class → NAVIGATING."""
        state = self.parser.parse([_det("gold")])
        assert state == GameState.NAVIGATING


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
