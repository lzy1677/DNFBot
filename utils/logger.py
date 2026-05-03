"""简单日志封装。"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional


_CONFIGURED = False


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    fmt: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
) -> None:
    """初始化日志。重复调用只更新级别，不重复添加 handler。"""
    global _CONFIGURED

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    if _CONFIGURED:
        return

    formatter = logging.Formatter(fmt, datefmt="%H:%M:%S")

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(formatter)
    root.addHandler(sh)

    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(formatter)
        root.addHandler(fh)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    if not _CONFIGURED:
        setup_logging()
    return logging.getLogger(name)
