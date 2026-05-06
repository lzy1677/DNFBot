"""单元测试：core/state.py — GameState 枚举与 StateMachine。"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state import GameState, StateMachine


class TestGameState:
    def test_all_states_have_value(self):
        expected = {
            "idle", "in_town", "entering_dungeon", "in_room", "combat",
            "looting", "navigating", "portal", "boss_room",
            "result_screen", "loading", "unknown",
        }
        assert {s.value for s in GameState} == expected

    def test_enum_lookup_by_value(self):
        assert GameState("combat") == GameState.COMBAT


class TestStateMachine:
    def test_initial_state(self):
        sm = StateMachine()
        assert sm.current == GameState.IDLE
        assert sm.previous == GameState.IDLE

    def test_valid_transition(self):
        sm = StateMachine()
        result = sm.transition(GameState.IN_TOWN)
        assert result is True
        assert sm.current == GameState.IN_TOWN
        assert sm.previous == GameState.IDLE

    def test_invalid_transition_returns_false(self):
        sm = StateMachine()
        # IDLE -> COMBAT is not in the allowed set
        result = sm.transition(GameState.COMBAT)
        assert result is False
        assert sm.current == GameState.IDLE

    def test_force_transition_bypasses_rules(self):
        sm = StateMachine()
        result = sm.transition(GameState.COMBAT, force=True)
        assert result is True
        assert sm.current == GameState.COMBAT

    def test_same_state_transition_returns_false(self):
        sm = StateMachine()
        result = sm.transition(GameState.IDLE)
        assert result is False

    def test_loading_can_go_anywhere(self):
        sm = StateMachine()
        sm.transition(GameState.LOADING, force=True)
        # LOADING -> COMBAT should be allowed
        result = sm.transition(GameState.COMBAT)
        assert result is True

    def test_unknown_can_go_anywhere(self):
        sm = StateMachine()
        sm.transition(GameState.UNKNOWN, force=True)
        result = sm.transition(GameState.BOSS_ROOM)
        assert result is True

    def test_time_in_state_increases(self):
        sm = StateMachine()
        t0 = sm.time_in_state()
        time.sleep(0.05)
        assert sm.time_in_state() > t0

    def test_time_resets_on_transition(self):
        sm = StateMachine()
        time.sleep(0.05)
        sm.transition(GameState.IN_TOWN)
        assert sm.time_in_state() < 0.05

    def test_can_transition_query(self):
        sm = StateMachine()
        assert sm.can_transition(GameState.IN_TOWN) is True
        assert sm.can_transition(GameState.COMBAT) is False

    def test_is_one_of(self):
        sm = StateMachine()
        assert sm.is_one_of(GameState.IDLE, GameState.COMBAT) is True
        assert sm.is_one_of(GameState.COMBAT, GameState.LOOTING) is False

    def test_full_dungeon_run_path(self):
        sm = StateMachine()
        path = [
            GameState.IN_TOWN,
            GameState.ENTERING_DUNGEON,
            GameState.IN_ROOM,
            GameState.COMBAT,
            GameState.LOOTING,
            GameState.NAVIGATING,
            GameState.PORTAL,
            GameState.LOADING,
            GameState.RESULT_SCREEN,
        ]
        for state in path:
            sm.transition(state, force=True)
        assert sm.current == GameState.RESULT_SCREEN


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
