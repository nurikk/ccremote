"""Configuration via pydantic-settings with .ccremote file."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

SETUP_INSTRUCTIONS = """\
ccremote is not configured. Two variables are required:

  CCREMOTE_BOT_TOKEN     — Telegram bot token
  CCREMOTE_ALLOWED_USER  — your Telegram user ID

Quick setup:

  1. Create a bot:     open https://t.me/BotFather, send /newbot, copy the token
  2. Get your user ID: open https://t.me/userinfobot, send /start, copy the number
  3. Create a .ccremote file in your project directory:

     CCREMOTE_BOT_TOKEN=123456:ABC-DEF...
     CCREMOTE_ALLOWED_USER=123456789

  Or export them as environment variables (CCREMOTE_BOT_TOKEN, CCREMOTE_ALLOWED_USER).

  4. Run: ccremote .

Optional: set CCREMOTE_OPENAI_API_KEY for voice message transcription.

Full docs: https://github.com/nurikk/ccremote#setup
"""


class ConfigError(Exception):
    pass


class Configuration(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CCREMOTE_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str
    allowed_user: int
    openai_api_key: str = ""
    log_level: str = "info"
    include_partial_messages: bool = True
    draft_throttle_ms: int = 300
    max_message_length: int = 4000
    claude_allowed_tools: list[str] | None = None
    session_id: str = ""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # .ccremote file overrides OS env vars
        return (init_settings, dotenv_settings, env_settings)


def load_config(cwd: str | Path | None = None) -> Configuration:
    ccremote_file = Path(cwd) / ".ccremote" if cwd else Path(".ccremote")
    try:
        return Configuration(_env_file=str(ccremote_file))  # type: ignore[call-arg]
    except Exception as e:
        raise ConfigError(str(e)) from e


def config_file_exists(cwd: str | Path) -> bool:
    return (Path(cwd) / ".ccremote").exists()


def save_session_id(cwd: str | Path, session_id: str) -> None:
    """Write or update CCREMOTE_SESSION_ID in the .ccremote file."""
    path = Path(cwd) / ".ccremote"
    key = "CCREMOTE_SESSION_ID"

    lines = path.read_text().splitlines() if path.exists() else []

    found = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            if session_id:
                lines[i] = f"{key}={session_id}"
            else:
                lines.pop(i)
            found = True
            break

    if not found and session_id:
        lines.append(f"{key}={session_id}")

    path.write_text(("\n".join(lines) + "\n") if lines else "")
