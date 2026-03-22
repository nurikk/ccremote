"""Configuration via pydantic-settings with .ccremote file."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

SETUP_INSTRUCTIONS = """\
Missing required configuration (CCREMOTE_BOT_TOKEN, CCREMOTE_ALLOWED_USER).

Either set them as environment variables or create a .ccremote file:

1. Create a Telegram bot via https://t.me/BotFather
2. Get your user ID via https://t.me/userinfobot
3. Create a .ccremote file in the project directory:

   CCREMOTE_BOT_TOKEN=<your-bot-token>
   CCREMOTE_ALLOWED_USER=<your-user-id>

   Or export them as environment variables.

4. Run: ccremote .
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
    claude_allowed_tools: list[str] = [
        "Read", "Edit", "Write", "Glob", "Grep", "Bash",
    ]

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
