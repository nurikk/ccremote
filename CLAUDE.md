# ccremote Development Guidelines

## Tech Stack

- Python 3.11+ (src-layout, `src/ccremote/`)
- aiogram 3.4+ (Telegram bot)
- pydantic + pydantic-settings (models, config via `.ccremote` file)
- Typer (CLI — argparse in current impl)
- OpenAI Whisper API (raw HTTP via aiohttp, no SDK)

## Commands

```bash
source .venv/bin/activate
uv pip install -e ".[dev]"           # install deps
python -m pytest tests/ -v           # run tests
ruff check src/ tests/               # lint
ruff format src/ tests/              # format
ty check src/                        # type check
ccremote .                           # start in current directory
ccremote ~/code/myproject            # start in specific directory
```

## Config

All config via env vars or per-project `.ccremote` file (pydantic-settings, prefix `CCREMOTE_`):
- `CCREMOTE_BOT_TOKEN` — Telegram bot token (required)
- `CCREMOTE_ALLOWED_USER` — single Telegram user ID (required)
- `CCREMOTE_OPENAI_API_KEY` — for voice transcription (optional)
- `CCREMOTE_LOG_LEVEL` — `debug`, `info`, `warning`, `error` (default: `info`)
- `CCREMOTE_DRAFT_THROTTLE_MS` — min ms between draft updates (default: `300`)
- `CCREMOTE_MAX_MESSAGE_LENGTH` — max chars per Telegram message (default: `4000`)
- `CCREMOTE_INCLUDE_PARTIAL_MESSAGES` — include partial messages in stream (default: `true`)
- `CCREMOTE_CLAUDE_ALLOWED_TOOLS` — JSON array of tools to allow (default: not set, all tools allowed)

Priority: `.ccremote` file > env vars > defaults.

## Architecture

Single-process, DM-only. No daemon, no socket.

- `ccremote .` starts aiogram polling in-process
- One Claude session per process, resumed via `claude --print --resume <id>`
- `sendMessageDraft` (Bot API 9.3+) for live streaming preview
- `sendMessage` for final response with cost
- Markdown converted to Telegram HTML (`markdown.py`)
- Photos/documents saved to `.ccremote-attachments/`
- Voice messages transcribed via OpenAI Whisper (optional)
- Permission denials show inline buttons to allow & retry
- Slash commands from Claude init event registered as Telegram bot commands

## Key Files

```
src/ccremote/
  cli.py       — argparse entry point, starts bot + polling
  bot.py       — dispatcher, send_draft/send_message helpers, command registration
  relay.py     — Claude CLI subprocess, stream parsing, DraftBuilder, permission handling
  markdown.py  — Markdown to Telegram HTML converter
  config.py    — pydantic-settings Configuration, .ccremote file loading
  models.py    — Session pydantic model
```

## Code Style

- No local imports — all imports must be at module level, not inside functions or methods.

## Testing

- `tests/unit/` — pure logic (event parsing, DraftBuilder, config, models, commands)
- `tests/contract/` — config schema validation
- `tests/e2e/` — requires running bot + Telethon client (skipped in CI)
- `asyncio_mode = "auto"` in pytest config
