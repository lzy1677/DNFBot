"""单元测试：strategy/ — CombatStrategy, LootStrategy, NavigationStrategy, RecoveryStrategy。"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vision.detector import Detection
from strategy.base import StrategyContext
from strategy.combat import CombatStrategy
from strategy.loot import LootStrategy
from strategy.navigation import NavigationStrategy
from strategy.recovery import RecoveryStrategy
from action.action_queue import KeyPress, Move, Wait


def _det(name: str, x1=0, y1=0, x2=100, y2=100, conf=0.9) -> Detection:
    return Detection(class_id=0, class_name=name, confidence=conf, bbox=(x1, y1, x2, y2))


def _ctx(**kwargs) -> StrategyContext:
    defaults = dict(detections=[], frame_shape=(720, 1280), character=None,
                    map=None, elapsed_in_state=0.0)
    defaults.update(kwargs)
    return StrategyContext(**defaults)


class TestCombatStrategy:
    def setup_method(self):
        self.strategy = CombatStrategy()

    def _mock_char(self):
        char = MagicMock()
        char.get_attack_sequence.return_value = [KeyPress(key="x")]
        return char

    def test_no_character_returns_empty(self):
        ctx = _ctx(detections=[_det("monster")])
        assert self.strategy.decide(ctx) == []

    def test_no_monsters_returns_empty(self):
        char = self._mock_char()
        ctx = _ctx(detections=[_det("player")], character=char)
        assert self.strategy.decide(ctx) == []

    def test_monster_detected_calls_attack_sequence(self):
        char = self._mock_char()
        ctx = _ctx(detections=[_det("monster"), _det("player", 200, 0, 250, 100)],
                   character=char)
        actions = self.strategy.decide(ctx)
        assert len(actions) > 0
        char.get_attack_sequence.assert_called_once()

    def test_combat_context_has_boss_present(self):
        char = self._mock_char()
        ctx = _ctx(detections=[_det("boss"), _det("player", 200, 0, 250, 100)],
                   character=char)
        self.strategy.decide(ctx)
        call_args = char.get_attack_sequence.call_args[0][0]
        assert call_args.boss_present is True

    def test_combat_context_direction(self):
        char = self._mock_char()
        # Player at x=300, monster at x=100 → approach left
        ctx = _ctx(
            detections=[
                _det("monster", x1=50, y1=0, x2=150, y2=100),
                _det("player", x1=270, y1=0, x2=330, y2=100),
            ],
            character=char,
        )
        self.strategy.decide(ctx)
        call_args = char.get_attack_sequence.call_args[0][0]
        assert call_args.approach_direction == "left"

    def test_no_player_uses_default_direction(self):
        char = self._mock_char()
        ctx = _ctx(detections=[_det("monster")], character=char)
        self.strategy.decide(ctx)
        call_args = char.get_attack_sequence.call_args[0][0]
        assert call_args.approach_direction == "right"
        assert call_args.distance_px == 300


class TestLootStrategy:
    def setup_method(self):
        self.strategy = LootStrategy(pickup_key="z", reach_px=40)

    def test_no_items_returns_empty(self):
        ctx = _ctx(detections=[_det("player")])
        assert self.strategy.decide(ctx) == []

    def test_no_player_blind_pickup(self):
        ctx = _ctx(detections=[_det("item")])
        actions = self.strategy.decide(ctx)
        assert any(isinstance(a, KeyPress) and a.tag == "pickup_blind" for a in actions)

    def test_item_nearby_player_just_picks_up(self):
        # Player at 100, item at 120 — within reach_px=40
        ctx = _ctx(detections=[
            _det("item", x1=100, y1=0, x2=140, y2=60),
            _det("player", x1=80, y1=0, x2=120, y2=60),
        ])
        actions = self.strategy.decide(ctx)
        assert any(isinstance(a, KeyPress) and a.tag == "pickup" for a in actions)
        assert not any(a.tag == "loot_move_x" for a in actions)

    def test_item_far_from_player_moves_first(self):
        # Player center at 50, item center at 550 — far right
        ctx = _ctx(detections=[
            _det("item", x1=500, y1=0, x2=600, y2=60),
            _det("player", x1=30, y1=0, x2=70, y2=60),
        ])
        actions = self.strategy.decide(ctx)
        move_actions = [a for a in actions if isinstance(a, Move)]
        assert len(move_actions) >= 1
        assert move_actions[0].direction == "right"

    def test_gold_is_also_lootable(self):
        ctx = _ctx(detections=[_det("gold")])
        actions = self.strategy.decide(ctx)
        assert len(actions) > 0

    def test_character_pickup_key_override(self):
        char = MagicMock()
        char.keys = {"pickup": "v"}
        ctx = _ctx(detections=[_det("item")], character=char)
        actions = self.strategy.decide(ctx)
        pickup_actions = [a for a in actions if isinstance(a, KeyPress) and "pickup" in a.tag]
        assert all(a.key == "v" for a in pickup_actions)


class TestNavigationStrategy:
    def setup_method(self):
        self.strategy = NavigationStrategy(step_duration=0.3)

    def test_no_map_moves_right(self):
        ctx = _ctx()
        actions = self.strategy.decide(ctx)
        assert len(actions) == 1
        assert isinstance(actions[0], Move)
        assert actions[0].direction == "right"

    def test_with_map_uses_direction(self):
        mock_map = MagicMock()
        mock_map.next_room_towards_boss.return_value = 2
        mock_map.current_id = 1
        mock_map.direction_to.return_value = "left"
        ctx = _ctx(map=mock_map)
        actions = self.strategy.decide(ctx)
        assert len(actions) == 1
        assert actions[0].direction == "left"

    def test_no_next_room_returns_empty(self):
        mock_map = MagicMock()
        mock_map.next_room_towards_boss.return_value = None
        ctx = _ctx(map=mock_map)
        assert self.strategy.decide(ctx) == []


class TestRecoveryStrategy:
    def setup_method(self):
        self.strategy = RecoveryStrategy(stuck_seconds=5.0)

    def test_ui_button_triggers_page_down(self):
        ctx = _ctx(detections=[_det("ui_button")])
        actions = self.strategy.decide(ctx)
        key_presses = [a for a in actions if isinstance(a, KeyPress)]
        assert any(a.key == "page_down" for a in key_presses)

    def test_multiple_ui_buttons_still_triggers(self):
        ctx = _ctx(detections=[_det("ui_button"), _det("ui_button")])
        actions = self.strategy.decide(ctx)
        assert len(actions) > 0

    def test_ui_response_includes_wait(self):
        ctx = _ctx(detections=[_det("ui_button")])
        actions = self.strategy.decide(ctx)
        assert any(isinstance(a, Wait) for a in actions)

    def test_stuck_triggers_unstick(self):
        ctx = _ctx(elapsed_in_state=10.0)
        actions = self.strategy.decide(ctx)
        assert len(actions) > 0
        move_actions = [a for a in actions if isinstance(a, Move)]
        assert len(move_actions) >= 1

    def test_not_stuck_yet_returns_empty(self):
        ctx = _ctx(elapsed_in_state=2.0)
        assert self.strategy.decide(ctx) == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
