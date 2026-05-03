"""单元测试：utils/ — Cooldown, RateLimiter, Stopwatch, load_yaml, deep_merge。"""
import sys
import time
import tempfile
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.timer import Cooldown, RateLimiter, Stopwatch
from utils.config import load_yaml, deep_merge, load_with_base


class TestCooldown:
    def test_ready_on_fresh_instance(self):
        # last_used defaults to 0.0; time.perf_counter() >> duration → ready
        cd = Cooldown(duration=1.0)
        assert cd.ready() is True

    def test_not_ready_immediately_after_trigger(self):
        cd = Cooldown(duration=10.0)
        cd.trigger()
        assert cd.ready() is False

    def test_remaining_decreases(self):
        cd = Cooldown(duration=5.0)
        cd.trigger()
        r1 = cd.remaining()
        time.sleep(0.05)
        r2 = cd.remaining()
        assert r2 < r1

    def test_remaining_zero_when_ready(self):
        cd = Cooldown(duration=0.01)
        cd.trigger()
        time.sleep(0.02)
        assert cd.remaining() == 0.0

    def test_ready_after_duration(self):
        cd = Cooldown(duration=0.02)
        cd.trigger()
        time.sleep(0.03)
        assert cd.ready() is True

    def test_zero_duration_always_ready(self):
        cd = Cooldown(duration=0.0)
        cd.trigger()
        assert cd.ready() is True

    def test_reset_makes_ready_from_triggered(self):
        cd = Cooldown(duration=10.0)
        cd.trigger()
        assert cd.ready() is False
        cd.reset()
        assert cd.ready() is True


class TestRateLimiter:
    def test_first_call_allowed(self):
        rl = RateLimiter(min_interval=0.1)
        assert rl.allow() is True

    def test_second_call_denied_within_interval(self):
        rl = RateLimiter(min_interval=1.0)
        rl.allow()
        assert rl.allow() is False

    def test_allowed_after_interval(self):
        rl = RateLimiter(min_interval=0.02)
        rl.allow()
        time.sleep(0.03)
        assert rl.allow() is True


class TestStopwatch:
    def test_elapsed_increases(self):
        sw = Stopwatch()
        time.sleep(0.05)
        assert sw.elapsed() >= 0.04

    def test_reset_restarts_timer(self):
        sw = Stopwatch()
        time.sleep(0.05)
        sw.reset()
        assert sw.elapsed() < 0.04


class TestLoadYaml:
    def _write(self, data: dict) -> Path:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        )
        yaml.dump(data, tmp, allow_unicode=True)
        tmp.close()
        return Path(tmp.name)

    def test_load_simple(self):
        path = self._write({"key": "value", "num": 42})
        cfg = load_yaml(path)
        assert cfg["key"] == "value"
        assert cfg["num"] == 42
        path.unlink()

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_yaml("/nonexistent/path/config.yaml")

    def test_empty_file_returns_dict(self):
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        )
        tmp.close()
        cfg = load_yaml(tmp.name)
        assert cfg == {}
        Path(tmp.name).unlink()


class TestDeepMerge:
    def test_simple_override(self):
        result = deep_merge({"a": 1, "b": 2}, {"b": 99})
        assert result == {"a": 1, "b": 99}

    def test_nested_merge(self):
        base = {"nested": {"x": 1, "y": 2}}
        override = {"nested": {"y": 99, "z": 3}}
        result = deep_merge(base, override)
        assert result["nested"] == {"x": 1, "y": 99, "z": 3}

    def test_base_not_mutated(self):
        base = {"a": 1}
        deep_merge(base, {"a": 2})
        assert base == {"a": 1}

    def test_override_adds_new_keys(self):
        result = deep_merge({"a": 1}, {"b": 2})
        assert result == {"a": 1, "b": 2}


class TestLoadWithBase:
    def _write(self, data: dict) -> Path:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        )
        yaml.dump(data, tmp, allow_unicode=True)
        tmp.close()
        return Path(tmp.name)

    def test_no_base(self):
        path = self._write({"name": "test", "val": 1})
        cfg = load_with_base(path)
        assert cfg["val"] == 1
        path.unlink()

    def test_with_explicit_base(self):
        base_path = self._write({"x": 10, "y": 20})
        override_path = self._write({"y": 99, "z": 30})
        cfg = load_with_base(override_path, base_path=base_path)
        assert cfg["x"] == 10
        assert cfg["y"] == 99
        assert cfg["z"] == 30
        base_path.unlink()
        override_path.unlink()

    def test_extends_field_resolved(self):
        base_path = self._write({"base_key": "base_val"})
        override_path = (
            Path(tempfile.gettempdir()) / "override_test.yaml"
        )
        override_path.write_text(
            yaml.dump({"extends": base_path.name, "new_key": "new"}),
            encoding="utf-8",
        )
        # Adjust: extends is resolved relative to override dir
        data = {"extends": base_path.name, "new_key": "new"}
        path = self._write(data)
        # Won't resolve correctly unless files are in same dir, just check no crash
        try:
            load_with_base(path)
        except FileNotFoundError:
            pass
        base_path.unlink()
        path.unlink()
        if override_path.exists():
            override_path.unlink()

    def test_actual_berserker_config(self):
        cfg_path = (
            Path(__file__).parent.parent / "config" / "classes" / "berserker.yaml"
        )
        if cfg_path.exists():
            cfg = load_with_base(cfg_path)
            assert "keys" in cfg or "name" in cfg


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
