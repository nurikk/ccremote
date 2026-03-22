---
name: e2e-test
description: Run end-to-end tests for ccremote using Telethon as a real Telegram client. Tests bot connectivity, session spawning, message relay, media uploads, and voice transcription against a live bot instance.
---

# E2E Testing for ccremote

Run end-to-end tests that interact with the ccremote Telegram bot as a real user via the Telethon client.

## Prerequisites

Before running e2e tests, verify:

1. **`.env` file exists** at project root with:
   - `CCREMOTE_BOT_TOKEN` — your bot's token from @BotFather
   - `CCREMOTE_ALLOWED_USERS` — JSON array including the test user's Telegram ID
   - `CCREMOTE_OPENAI_API_KEY` — for voice transcription tests
   - `TELEGRAM_API_ID` — Telegram API credentials for the test client
   - `TELEGRAM_API_HASH` — Telegram API hash
   - `TELEGRAM_SESSION_STRING` — pre-authenticated Telethon session
   - `CCREMOTE_BOT_USERNAME` — bot's @username (without @)

2. **Daemon is running**: `ccremote start` must have been run
3. **Bot has forum topics enabled**: The test user's DM with the bot must have Topics mode on
4. **Dependencies installed**: `uv pip install -e ".[dev]"`

## Running Tests

### Run all e2e tests:
```bash
source .venv/bin/activate
python -m pytest tests/e2e/ -v
```

### Run specific test suites:
```bash
# Bot connectivity only
python -m pytest tests/e2e/test_bot_connectivity.py -v

# Message relay (requires an active session)
python -m pytest tests/e2e/test_bot_connectivity.py::TestMessageRelay -v

# Media uploads
python -m pytest tests/e2e/test_media.py -v
```

### Run with full output for debugging:
```bash
python -m pytest tests/e2e/ -v -s --log-cli-level=DEBUG
```

## Test Flow

The e2e test flow is:

1. **Check prerequisites** — verify env vars are set, skip if not
2. **Connect Telethon client** — authenticate as a real Telegram user using session string
3. **Send messages to bot** — `/start`, prompts in threads, media files
4. **Wait for responses** — poll for bot replies with configurable timeout
5. **Assert expectations** — verify bot responded, content is correct

## Writing New E2E Tests

Use the `TelegramTestClient` from `tests/e2e/telegram_client.py`:

```python
from tests.e2e.conftest import e2e
from tests.e2e.telegram_client import TelegramTestClient

@e2e
class TestMyFeature:
    async def test_something(self, tg_client: TelegramTestClient, bot_username: str):
        sent = await tg_client.send_message(bot_username, "test prompt")
        response = await tg_client.wait_for_response(
            bot_username, timeout=30, after_message_id=sent.id
        )
        assert response is not None
```

### Available methods on `TelegramTestClient`:
- `send_message(bot, text)` — send a DM
- `send_message_to_thread(bot, text, thread_id)` — send to a specific forum topic
- `wait_for_response(bot, timeout, after_message_id)` — wait for bot reply
- `wait_for_thread_response(bot, thread_id, timeout, after_message_id)` — wait for reply in thread
- `get_forum_topics(bot)` — list forum topics in bot DM
- `send_file(bot, path, caption, reply_to)` — send photo/document
- `send_voice(bot, path, reply_to)` — send voice note

### Important patterns:
- Always use `@e2e` marker to auto-skip when credentials are missing
- Use `after_message_id=sent.id` to avoid picking up old messages
- Set reasonable timeouts (10s for bot commands, 60s for Claude responses)
- Clean up test artifacts (temp files) in `finally` blocks

## Troubleshooting

**Tests all skip**: Check that all `TELEGRAM_*` and `CCREMOTE_*` env vars are set in `.env`

**"Bot did not respond"**: Ensure daemon is running (`ccremote status`), bot token is correct, and test user ID is in `CCREMOTE_ALLOWED_USERS`

**"No active session threads"**: Run `ccremote spawn .` before running relay/media tests

**Telethon auth error**: The session string may have expired. Generate a new one with:
```python
from telethon import TelegramClient
from telethon.sessions import StringSession
client = TelegramClient(StringSession(), API_ID, API_HASH)
await client.start()
print(client.session.save())
```
