"""Telegram bot setup — filters and helpers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeChat

from ccremote.markdown import md_to_tg_html

if TYPE_CHECKING:
    from ccremote.config import Configuration

logger = logging.getLogger(__name__)


def create_dispatcher(config: Configuration) -> Dispatcher:
    """Create a Dispatcher with allowlist filter."""
    dp = Dispatcher()
    dp.message.filter(F.from_user.id == config.allowed_user, ~F.from_user.is_bot)

    return dp


async def send_draft(bot: Bot, chat_id: int, text: str, draft_id: int) -> None:
    """Send a draft (live typing preview) to a user DM."""
    try:
        await bot.send_message_draft(
            chat_id=chat_id,
            text=md_to_tg_html(text),
            draft_id=draft_id,
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.debug("Draft send failed: %s", e)


async def send_message(
    bot: Bot,
    chat_id: int,
    text: str,
    reply_markup: types.InlineKeyboardMarkup | None = None,
) -> None:
    """Send a message with HTML formatting."""
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=md_to_tg_html(text),
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
    except Exception:
        logger.debug("send_message failed for chat %s", chat_id)


async def register_commands(bot: Bot, chat_id: int, commands: list[tuple[str, str]]) -> None:
    """Register slash commands with Telegram for autocomplete in this chat.

    Fetches current commands first and only calls set_my_commands if they differ.
    """
    if not commands:
        await unregister_commands(bot, chat_id)
        return

    scope = BotCommandScopeChat(chat_id=chat_id)
    new_commands = {(name, desc or name) for name, desc in commands}

    try:
        existing = await bot.get_my_commands(scope=scope)
        current = {(c.command, c.description) for c in existing}
        if current == new_commands:
            logger.debug("Commands unchanged for chat %s, skipping", chat_id)
            return
    except Exception:
        logger.debug("Could not fetch existing commands for chat %s", chat_id)

    tg_commands = [BotCommand(command=name, description=desc) for name, desc in new_commands]
    try:
        await bot.set_my_commands(tg_commands, scope=scope)
        logger.info("Registered %d commands for chat %s", len(tg_commands), chat_id)
    except Exception:
        logger.exception("Failed to register commands for chat %s", chat_id)


async def unregister_commands(bot: Bot, chat_id: int) -> None:
    """Remove all bot commands for this chat."""
    try:
        await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=chat_id))
        logger.info("Unregistered commands for chat %s", chat_id)
    except Exception:
        logger.exception("Failed to unregister commands for chat %s", chat_id)
