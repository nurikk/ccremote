"""Unit tests for config."""

from ccremote.config import load_config
from tests.conftest import set_valid_env, write_ccremote_file


class TestConfig:
    def test_loads_from_ccremote_file(self, tmp_path):
        write_ccremote_file(tmp_path)
        config = load_config(tmp_path)
        assert config.bot_token.startswith("123456:")

    def test_allowed_tools_json(self, monkeypatch):
        set_valid_env(monkeypatch, CCREMOTE_CLAUDE_ALLOWED_TOOLS='["Read", "Write"]')
        assert load_config().claude_allowed_tools == ["Read", "Write"]
