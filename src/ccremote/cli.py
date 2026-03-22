"""CLI entry point for ccremote — just `ccremote .`"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from ccremote.config import SETUP_INSTRUCTIONS, ConfigError, config_file_exists, load_config

logger = logging.getLogger(__name__)


def main() -> None:
    """Start ccremote in the given directory."""
    parser = argparse.ArgumentParser(
        prog="ccremote",
        description="Control Claude Code from Telegram.",
    )
    parser.add_argument("path", nargs="?", default=".", help="Project directory")
    args = parser.parse_args()

    cwd = str(Path(args.path).resolve())
    if not Path(cwd).is_dir():
        logger.error("Not a directory: %s", cwd)
        sys.exit(2)

    try:
        config = load_config(cwd)
    except ConfigError:
        if not config_file_exists(cwd):
            logger.error(SETUP_INSTRUCTIONS)
            sys.exit(1)
        raise

    logging.basicConfig(
        level=getattr(logging, config.log_level.upper()),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    async def _run() -> None:
        from aiogram import Bot

        import uuid

        from ccremote.bot import create_dispatcher, notify_user
        from ccremote.models import Session
        from ccremote.relay import setup_relay_handlers

        bot = Bot(token=config.bot_token)
        dp = create_dispatcher(config)

        async with bot:
            me = await bot.get_me()
            logger.info("Bot connected: @%s", me.username)

            session = Session(
                session_id=str(uuid.uuid4()),
                working_directory=cwd,
            )

            dir_name = Path(cwd).name
            await notify_user(bot, config.allowed_user, f"🟢 **ccremote active**\n`{dir_name}`\n`{cwd}`")
            logger.info("ccremote active in %s — send messages to @%s", cwd, me.username)

            setup_relay_handlers(dp, bot, session, config)

            try:
                await dp.start_polling(bot)
            finally:
                logger.info("Stopping ccremote...")
                session.terminate()
                try:
                    await notify_user(bot, config.allowed_user, "🔴 **ccremote stopped**")
                except Exception:
                    pass
                logger.info("Stopped.")

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass
