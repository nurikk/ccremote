"""CLI entry point for ccremote — just `ccremote .`"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys
import uuid
from pathlib import Path

from aiogram import Bot

from ccremote.bot import create_dispatcher, register_commands, send_message
from ccremote.config import SETUP_INSTRUCTIONS, ConfigError, config_file_exists, load_config
from ccremote.models import Session
from ccremote.relay import setup_relay_handlers

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
        dp = create_dispatcher(config)

        async with Bot(token=config.bot_token) as bot:
            me = await bot.get_me()
            logger.info("Bot connected: @%s", me.username)

            session = Session(
                session_id=str(uuid.uuid4()),
                claude_session_id=config.session_id,
                working_directory=cwd,
            )

            if config.session_id:
                msg = f"🟢 **ccremote active** (resuming)\n`{cwd}`"
            else:
                msg = f"🟢 **ccremote active**\n`{cwd}`"
            await send_message(bot, config.allowed_user, msg)
            await register_commands(
                bot,
                config.allowed_user,
                [
                    ("start", "Describe current session and working directory"),
                    ("new", "Start a new conversation"),
                ],
            )
            logger.info("ccremote active in %s — send messages to @%s", cwd, me.username)

            setup_relay_handlers(dp, bot, session, config)

            try:
                await dp.start_polling(bot)
            finally:
                logger.info("Stopping ccremote...")
                session.terminate()
                with contextlib.suppress(Exception):
                    await send_message(bot, config.allowed_user, "🔴 **ccremote stopped**")
                logger.info("Stopped.")

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_run())
