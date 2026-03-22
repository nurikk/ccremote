"""Contract tests for config schema."""

import os

import pytest

from ccremote.config import ConfigError, config_file_exists, load_config
from tests.conftest import set_valid_env, write_ccremote_file


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("CCREMOTE_"):
            monkeypatch.delenv(key)


class TestConfigFromFile:
    def test_loads_from_ccremote_file(self, tmp_path):
        write_ccremote_file(tmp_path)
        config = load_config(tmp_path)
        assert config.bot_token == "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
        assert config.allowed_user == 123456789

    def test_config_file_exists_check(self, tmp_path):
        assert not config_file_exists(tmp_path)
        write_ccremote_file(tmp_path)
        assert config_file_exists(tmp_path)

    def test_env_vars_override_file(self, tmp_path, monkeypatch):
        write_ccremote_file(tmp_path)
        monkeypatch.setenv("CCREMOTE_LOG_LEVEL", "debug")
        config = load_config(tmp_path)
        assert config.log_level == "debug"


class TestConfigFromEnv:
    def test_loads_from_env(self, monkeypatch):
        set_valid_env(monkeypatch)
        config = load_config()
        assert config.bot_token == "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"

    def test_missing_bot_token_raises(self, monkeypatch):
        monkeypatch.setenv("CCREMOTE_ALLOWED_USER", "1")
        with pytest.raises(ConfigError):
            load_config()

    def test_missing_allowed_user_raises(self, monkeypatch):
        monkeypatch.setenv("CCREMOTE_BOT_TOKEN", "123:ABC")
        with pytest.raises(ConfigError):
            load_config()


class TestConfigDefaults:
    def test_defaults(self, tmp_path):
        write_ccremote_file(tmp_path)
        config = load_config(tmp_path)
        assert config.log_level == "info"
        assert config.draft_throttle_ms == 300
        assert config.max_message_length == 4000
        assert "Read" in config.claude_allowed_tools
