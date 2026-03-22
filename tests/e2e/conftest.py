"""E2E test fixtures using Telethon."""

from __future__ import annotations

import os

import pytest

from tests.e2e.telegram_client import TelegramTestClient


def _e2e_configured() -> bool:
    """Check if e2e credentials are present and non-empty."""
    return bool(
        os.environ.get("TELEGRAM_API_ID")
        and os.environ.get("TELEGRAM_API_HASH")
        and os.environ.get("TELEGRAM_SESSION_STRING")
        and os.environ.get("CCREMOTE_BOT_TOKEN")
    )


e2e = pytest.mark.skipif(
    not _e2e_configured(),
    reason="E2E credentials not configured (set TELEGRAM_* and CCREMOTE_* env vars)",
)
"""Marker to skip e2e tests when credentials are missing."""


@pytest.fixture(scope="session")
def bot_username() -> str:
    """Bot username to test against (derived from token or env)."""
    return os.environ.get("CCREMOTE_BOT_USERNAME", "")


@pytest.fixture
async def tg_client():
    """Provide a connected Telethon test client."""
    async with TelegramTestClient() as client:
        yield client
