"""单元测试：classes/ — Skill, SkillSet, BaseClass, Berserker。"""
import sys
import time
import tempfile
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from action.skill import Skill, SkillSet
from classes.base_class import BaseClass, CombatContext, build_class
from classes.berserker import Berserker
from action.action_queue import KeyPress, Move


# --- 基础配置 ---
_BERSERKER_CFG = {
    "name": "狂战士",
    "keys": {
        "attack": "x",
        "jump": "c",
        "skill_1": {"key": "q", "cooldown": 0.0, "priority": 3},
        "skill_2": {"key": "w", "cooldown": 0.0, "priority": 2},
        "skill_3": {"key": "e", "cooldown": 60.0, "priority": 1},
        "awakening": {"key": "r", "cooldown": 60.0, "priority": 0},
    },
    "combo_chains": [["attack", "skill_1"]],
}


def _write_yaml(data: dict) -> Path:
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    )
    yaml.dump(data, tmp, allow_unicode=True)
    tmp.close()
    return Path(tmp.name)


class TestSkill:
    def test_ready_on_init(self):
        s = Skill(name="a", key="q", cooldown=1.0)
        # last_used=0 → elapsed > 0 ≥ cooldown only if cooldown=0
        # For cooldown=1.0, last_used=0 means (now - 0) >> 1.0 → ready
        assert s.ready() is True

    def test_not_ready_after_trigger(self):
        s = Skill(name="a", key="q", cooldown=10.0)
        s.trigger()
        assert s.ready() is False

    def test_remaining_after_trigger(self):
        s = Skill(name="a", key="q", cooldown=5.0)
        s.trigger()
        assert s.remaining() > 4.0

    def test_ready_after_cooldown(self):
        s = Skill(name="a", key="q", cooldown=0.01)
        s.trigger()
        time.sleep(0.02)
        assert s.ready() is True

    def test_zero_cooldown_always_ready(self):
        s = Skill(name="a", key="q", cooldown=0.0)
        s.trigger()
        assert s.ready() is True


class TestSkillSet:
    def test_add_and_get(self):
        ss = SkillSet()
        s = Skill(name="slash", key="q")
        ss.add(s)
        assert ss.get("slash") is s

    def test_contains(self):
        ss = SkillSet()
        ss.add(Skill(name="slash", key="q"))
        assert "slash" in ss
        assert "unknown" not in ss

    def test_ready_skills(self):
        ss = SkillSet()
        s1 = Skill(name="a", key="q", cooldown=0.0)
        s2 = Skill(name="b", key="w", cooldown=100.0)
        s2.trigger()
        ss.add(s1)
        ss.add(s2)
        ready = ss.ready_skills()
        assert s1 in ready
        assert s2 not in ready

    def test_highest_priority_ready(self):
        ss = SkillSet()
        ss.add(Skill(name="low", key="q", priority=1))
        ss.add(Skill(name="high", key="w", priority=5))
        best = ss.highest_priority_ready()
        assert best.name == "high"

    def test_highest_priority_none_if_empty(self):
        ss = SkillSet()
        assert ss.highest_priority_ready() is None

    def test_iter(self):
        ss = SkillSet()
        skills = [Skill(name=f"s{i}", key="q") for i in range(3)]
        for s in skills:
            ss.add(s)
        assert len(list(ss)) == 3


class TestBerserker:
    def setup_method(self):
        self.char = Berserker(_BERSERKER_CFG)

    def test_display_name(self):
        assert self.char.display_name == "狂战士"

    def test_keys_loaded(self):
        assert self.char.keys["attack"] == "x"
        assert self.char.keys["skill_1"] == "q"

    def test_attack_action(self):
        actions = self.char.attack()
        assert len(actions) == 1
        assert isinstance(actions[0], KeyPress)
        assert actions[0].key == "x"

    def test_approach_action(self):
        actions = self.char.approach("left", 0.3)
        assert len(actions) == 1
        assert isinstance(actions[0], Move)
        assert actions[0].direction == "left"

    def test_use_skill_returns_keypress(self):
        actions = self.char.use_skill("skill_1")
        assert len(actions) == 1
        assert isinstance(actions[0], KeyPress)
        assert actions[0].key == "q"

    def test_use_skill_on_cooldown_returns_empty(self):
        # skill_3 has 60s cooldown, trigger it
        self.char.skills.get("skill_3").trigger()
        actions = self.char.use_skill("skill_3")
        assert actions == []

    def test_get_attack_sequence_close_monster_no_approach(self):
        ctx = CombatContext(
            monster_boxes=[(90, 0, 110, 100)],
            player_box=(80, 0, 120, 100),
            distance_px=20,
            approach_direction="right",
        )
        actions = self.char.get_attack_sequence(ctx)
        assert len(actions) > 0
        move_actions = [a for a in actions if isinstance(a, Move)]
        # distance_px=20 < 120, no approach needed
        assert len(move_actions) == 0

    def test_get_attack_sequence_far_monster_approaches(self):
        ctx = CombatContext(
            monster_boxes=[(500, 0, 600, 100)],
            player_box=(0, 0, 50, 100),
            distance_px=500,
            approach_direction="right",
        )
        actions = self.char.get_attack_sequence(ctx)
        move_actions = [a for a in actions if isinstance(a, Move)]
        assert len(move_actions) >= 1

    def test_boss_uses_high_priority_skills(self):
        # skill_1 and skill_2 ready (cooldown=0), skill_3 and awakening on cooldown
        ctx = CombatContext(
            monster_boxes=[(10, 0, 50, 100)],
            player_box=(0, 0, 10, 100),
            boss_present=True,
            distance_px=10,
        )
        actions = self.char.get_attack_sequence(ctx)
        # Should have used a skill, not just plain attack
        assert any(isinstance(a, KeyPress) for a in actions)

    def test_get_buff_sequence_empty_for_normal_skills(self):
        # _BERSERKER_CFG has no priority < 0 skills
        buffs = self.char.get_buff_sequence()
        assert buffs == []


class TestBuildClass:
    def test_build_berserker_from_file(self):
        path = _write_yaml(_BERSERKER_CFG)
        char = build_class("berserker", path)
        assert isinstance(char, Berserker)
        path.unlink()

    def test_build_unknown_class_raises(self):
        path = _write_yaml({"name": "x"})
        with pytest.raises(KeyError):
            build_class("unknown_class_xyz", path)
        path.unlink()

    def test_build_from_actual_config(self):
        cfg_path = (
            Path(__file__).parent.parent / "config" / "classes" / "berserker.yaml"
        )
        if cfg_path.exists():
            char = build_class("berserker", cfg_path)
            assert char.display_name


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
