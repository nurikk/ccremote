"""E2E tests: bot connectivity.

Requires a running ccremote process and valid .env with TELEGRAM_* credentials.
"""

from __future__ import annotations

import pytest

from tests.e2e.conftest import e2e
from tests.e2e.telegram_client import TelegramTestClient


@e2e
class TestBotConnectivity:
    async def test_bot_responds_to_start(self, tg_client: TelegramTestClient, bot_username: str):
        if not bot_username:
            pytest.skip("CCREMOTE_BOT_USERNAME not set")

        sent = await tg_client.send_message(bot_username, "/start")
        response = await tg_client.wait_for_response(
            bot_username, timeout=10, after_message_id=sent.id
        )
        assert response is not None, "Bot did not respond to /start within 10s"
        assert "ccremote" in response.text.lower() or "user id" in response.text.lower()

    async def test_bot_responds_to_message(self, tg_client: TelegramTestClient, bot_username: str):
        if not bot_username:
            pytest.skip("CCREMOTE_BOT_USERNAME not set")

        sent = await tg_client.send_message(bot_username, "hello")
        response = await tg_client.wait_for_response(
            bot_username, timeout=10, after_message_id=sent.id
        )
        assert response is not None, "Bot did not respond"
