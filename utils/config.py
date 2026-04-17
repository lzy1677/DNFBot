"""YAML 配置加载。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml


def load_yaml(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"config not found: {p}")
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def deep_merge(base: dict, override: dict) -> dict:
    """深度合并，override 覆盖 base。"""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_with_base(path: str | Path, base_path: str | Path | None = None) -> dict:
    """如果配置里有 `extends:` 字段或传入 base_path，则先加载基础模板再合并。"""
    cfg = load_yaml(path)
    ext = cfg.pop("extends", None) if isinstance(cfg, dict) else None
    parent = base_path or (Path(path).parent / ext if ext else None)
    if parent:
        base = load_yaml(parent)
        cfg = deep_merge(base, cfg)
    return cfg
