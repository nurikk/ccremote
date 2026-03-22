"""Telethon-based Telegram test client for e2e testing."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import Message

logger = logging.getLogger(__name__)

# Load .env from project root
load_dotenv(Path(__file__).parent.parent.parent / ".env")


class TelegramTestClient:
    """A Telethon client that acts as a real Telegram user for e2e testing.

    Connects using a session string (no interactive auth needed).
    Can send messages to a bot, read responses, and interact with forum topics.
    """

    def __init__(
        self,
        api_id: int | None = None,
        api_hash: str | None = None,
        session_string: str | None = None,
    ) -> None:
        self.api_id = api_id or int(os.environ["TELEGRAM_API_ID"])
        self.api_hash = api_hash or os.environ["TELEGRAM_API_HASH"]
        self.session_string = session_string or os.environ["TELEGRAM_SESSION_STRING"]
        self.client = TelegramClient(
            StringSession(self.session_string),
            self.api_id,
            self.api_hash,
        )

    async def start(self) -> TelegramTestClient:
        await self.client.start()
        me = await self.client.get_me()
        logger.info("Test client connected as @%s (ID: %s)", me.username, me.id)
        return self

    async def stop(self) -> None:
        await self.client.disconnect()

    async def __aenter__(self) -> TelegramTestClient:
        return await self.start()

    async def __aexit__(self, *args: object) -> None:
        await self.stop()

    @property
    def user_id(self) -> int:
        """Get the connected user's Telegram ID."""
        return self.client._self_id  # type: ignore[return-value]

    async def get_me(self) -> object:
        """Get the connected user entity."""
        return await self.client.get_me()

    async def send_message(
        self,
        bot_username: str,
        text: str,
        reply_to: int | None = None,
    ) -> Message:
        """Send a message to a bot."""
        entity = await self.client.get_entity(bot_username)
        return await self.client.send_message(
            entity,
            text,
            reply_to=reply_to,
        )

    async def send_message_to_thread(
        self,
        bot_username: str,
        text: str,
        thread_id: int,
    ) -> Message:
        """Send a message to a specific forum topic thread."""
        entity = await self.client.get_entity(bot_username)
        return await self.client.send_message(
            entity,
            text,
            reply_to=thread_id,
        )

    async def wait_for_response(
        self,
        bot_username: str,
        timeout: float = 30.0,
        after_message_id: int | None = None,
    ) -> Message | None:
        """Wait for a new message from the bot.

        Args:
            bot_username: Bot to watch for responses from.
            timeout: Max seconds to wait.
            after_message_id: Only return messages newer than this ID.

        Returns:
            The bot's response message, or None if timeout.
        """
        entity = await self.client.get_entity(bot_username)
        deadline = asyncio.get_event_loop().time() + timeout

        while asyncio.get_event_loop().time() < deadline:
            messages = await self.client.get_messages(entity, limit=5)
            for msg in messages:
                if msg.out:
                    continue  # skip our own messages
                if after_message_id and msg.id <= after_message_id:
                    continue
                return msg
            await asyncio.sleep(0.5)
        return None

    async def wait_for_thread_response(
        self,
        bot_username: str,
        thread_id: int,
        timeout: float = 30.0,
        after_message_id: int | None = None,
    ) -> Message | None:
        """Wait for a bot response in a specific thread."""
        entity = await self.client.get_entity(bot_username)
        deadline = asyncio.get_event_loop().time() + timeout

        while asyncio.get_event_loop().time() < deadline:
            messages = await self.client.get_messages(entity, limit=10, reply_to=thread_id)
            for msg in messages:
                if msg.out:
                    continue
                if after_message_id and msg.id <= after_message_id:
                    continue
                return msg
            await asyncio.sleep(0.5)
        return None

    async def get_forum_topics(self, bot_username: str) -> list:
        """List forum topics in a chat with the bot.

        Note: Telethon v2 removed GetForumTopicsRequest.
        This uses raw TL function if available, otherwise returns empty.
        """
        try:
            from telethon.tl import functions

            entity = await self.client.get_entity(bot_username)
            result = await self.client(
                functions.channels.GetForumTopicsRequest(
                    channel=entity,
                    offset_date=0,
                    offset_id=0,
                    offset_topic=0,
                    limit=100,
                )
            )
            return result.topics
        except (ImportError, AttributeError):
            logger.debug("GetForumTopicsRequest not available in this Telethon version")
            return []
        except Exception:
            logger.debug("Could not fetch forum topics", exc_info=True)
            return []

    async def send_file(
        self,
        bot_username: str,
        file_path: str,
        caption: str = "",
        reply_to: int | None = None,
    ) -> Message:
        """Send a file (photo, document) to the bot."""
        entity = await self.client.get_entity(bot_username)
        return await self.client.send_file(
            entity,
            file_path,
            caption=caption,
            reply_to=reply_to,
        )

    async def send_voice(
        self,
        bot_username: str,
        file_path: str,
        reply_to: int | None = None,
    ) -> Message:
        """Send a voice message to the bot."""
        entity = await self.client.get_entity(bot_username)
        return await self.client.send_file(
            entity,
            file_path,
            voice_note=True,
            reply_to=reply_to,
        )
