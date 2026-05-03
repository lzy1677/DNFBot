"""DNF Bot 入口。

默认读取 config/settings.yaml。支持 --settings 覆盖。
使用 Ctrl+C 或热键 F12（在 settings.yaml 中配置）退出。
"""
from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

from core.bot import GameBot
from utils.logger import get_logger


def main() -> int:
    ap = argparse.ArgumentParser(description="DNF 自动化 Bot")
    ap.add_argument("--settings", default="config/settings.yaml")
    ap.add_argument("--dry-run", action="store_true",
                    help="只初始化，不进入主循环（自检用）")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="DEBUG 级别日志：显示每帧耗时、检测结果、动作队列详情")
    ap.add_argument("--skip-dungeon", action="store_true",
                    help="跳过进城/进本流程，直接从 IN_ROOM 状态启动（已在副本内时使用）")
    args = ap.parse_args()

    settings = Path(args.settings)
    if not settings.exists():
        print(f"settings 文件不存在: {settings}", file=sys.stderr)
        return 2

    log = get_logger("main")
    log.info("加载配置: %s", settings)

    bot = GameBot.from_settings(settings, verbose=args.verbose,
                                skip_dungeon=args.skip_dungeon)
    signal.signal(signal.SIGINT, lambda *_: bot.stop())
    try:
        signal.signal(signal.SIGTERM, lambda *_: bot.stop())
    except (ValueError, AttributeError):
        pass

    if args.dry_run:
        log.info("dry-run 自检通过")
        bot._shutdown()
        return 0

    bot.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
