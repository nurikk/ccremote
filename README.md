# ccremote

Control Claude Code from your phone via Telegram.

ccremote bridges Claude Code CLI to Telegram DMs. Send prompts from your phone, get streaming responses via live draft previews, send photos/documents/voice messages — all without sitting at your computer.

## How it works

```
Phone (Telegram)            Local Machine
──────────────────          ──────────────────
  DM with bot               ccremote
  "fix the bug"  ────►       ├─ Telegram bot (aiogram)
  ◄ streaming draft...       ├─ claude -p --resume <id>
  ◄ final response           └─ Whisper transcription
```

1. Run `ccremote .` in any project directory
2. Chat with Claude in your bot's DM
3. Responses stream as live draft previews, then appear as final messages
4. Send photos, documents, or voice messages
5. Permission denials show inline buttons to approve and retry

## Setup

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- OpenAI API key (optional, for voice transcription — no SDK needed)

### Install

```bash
git clone https://github.com/your-user/ccremote.git
cd ccremote
uv venv .venv
source .venv/bin/activate
uv pip install -e .
```

## Configuration

ccremote uses two layers of configuration:

### 1. Global environment variables

Set these in your shell profile (`~/.zshrc`, `~/.bashrc`) for defaults that apply to all projects:

```bash
export CCREMOTE_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
export CCREMOTE_ALLOWED_USER=123456789
export CCREMOTE_OPENAI_API_KEY=sk-...
```

### 2. Per-project `.ccremote` file

Create a `.ccremote` file in any project directory to override globals for that project. This is useful when you have multiple bots or want different settings per project.

```env
CCREMOTE_BOT_TOKEN=999888:XYZ-different-bot-token
CCREMOTE_ALLOWED_USER=123456789
CCREMOTE_OPENAI_API_KEY=sk-...
```

**Priority order** (highest to lowest):
1. Per-project `.ccremote` file
2. Global environment variables
3. Built-in defaults

This means a `.ccremote` file always wins over env vars. If you set `CCREMOTE_BOT_TOKEN` globally but also have it in a project's `.ccremote`, the project file takes precedence.

### Finding your Telegram user ID

Send `/start` to [@userinfobot](https://t.me/userinfobot).

### Configuration options

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CCREMOTE_BOT_TOKEN` | yes | — | Telegram bot token from @BotFather |
| `CCREMOTE_ALLOWED_USER` | yes | — | Your Telegram user ID |
| `CCREMOTE_OPENAI_API_KEY` | no | `""` | OpenAI key for voice transcription |
| `CCREMOTE_LOG_LEVEL` | no | `info` | `debug`, `info`, `warning`, `error` |
| `CCREMOTE_INCLUDE_PARTIAL_MESSAGES` | no | `true` | Include partial messages in stream |
| `CCREMOTE_DRAFT_THROTTLE_MS` | no | `300` | Min ms between draft updates |
| `CCREMOTE_MAX_MESSAGE_LENGTH` | no | `4000` | Max chars per Telegram message |
| `CCREMOTE_CLAUDE_ALLOWED_TOOLS` | no | `["Read","Edit",...]` | JSON array of tools to allow |

> **Tip:** Add `.ccremote` to your global `.gitignore` — it contains secrets.

## Usage

```bash
# Start ccremote in the current project
ccremote .

# Or specify a path
ccremote ~/code/myproject
```

That's it. The bot connects to Telegram and you can start chatting.

### Message types

- **Text** — sent directly as prompts to Claude
- **Photos** — downloaded to `.ccremote-attachments/` in the project, path passed to Claude
- **Documents** — same as photos, keeps original filename
- **Voice messages** — transcribed via OpenAI Whisper, sent as text (requires `CCREMOTE_OPENAI_API_KEY`)

### Permission handling

When Claude tries to use a tool that's blocked by permissions, you'll see an inline keyboard:

```
⚠️ Permission denied:
  • Bash: ls ~/Downloads

[✅ Allow & Retry]  [❌ Skip]
```

Tapping **Allow & Retry** re-runs the prompt with the denied tools added to `--allowedTools`.

### Session continuity

ccremote uses `claude -p --resume <session_id>` to maintain conversation context. Each message continues the same Claude session, so context builds up naturally across your conversation.

## Architecture

```
src/ccremote/
├── cli.py          Entry point — starts bot, creates session
├── bot.py          aiogram dispatcher, message sending helpers
├── relay.py        Claude ↔ Telegram relay, streaming, permissions
├── markdown.py     Markdown → Telegram HTML converter
├── config.py       pydantic-settings configuration
└── models.py       Pydantic data models (Session)
```

**Key design decisions:**
- Single session mode — one `ccremote` process per project, DM-only
- Each prompt spawns `claude -p --resume <id>` (stateless process, persistent session)
- `sendMessageDraft` (Bot API 9.3+) for flicker-free live streaming
- Final messages include cost (e.g. `$0.005`)
- Markdown converted to Telegram HTML for formatted output
- Per-project `.ccremote` overrides global env vars

## Development

```bash
# Install dev dependencies
uv pip install -e ".[dev]"

# Run tests
python -m pytest tests/ -v

# Lint
ruff check src/ tests/

# Format
ruff format src/ tests/

# Type check
ty check src/
```

## License

MIT
