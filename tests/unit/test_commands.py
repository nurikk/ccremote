"""Unit tests for slash command extraction and normalization."""

from ccremote.relay import normalize_slash_commands, parse_claude_event


class TestSlashCommandExtraction:
    def test_extract_from_init_event(self):
        event = {
            "type": "system",
            "subtype": "init",
            "session_id": "abc",
            "slash_commands": [
                {"name": "/commit", "description": "Create a commit"},
                {"name": "/review-pr", "description": "Review a PR"},
            ],
        }
        result = parse_claude_event(event)
        assert len(result["slash_commands"]) == 2

    def test_empty_slash_commands(self):
        event = {
            "type": "system",
            "subtype": "init",
            "session_id": "abc",
        }
        result = parse_claude_event(event)
        assert result["slash_commands"] == []


class TestCommandNormalization:
    def test_strip_leading_slash(self):
        cmds = [{"name": "/commit", "description": "Commit"}]
        result = normalize_slash_commands(cmds)
        assert result[0][0] == "commit"

    def test_replace_hyphens_with_underscores(self):
        cmds = [{"name": "/review-pr", "description": "Review"}]
        result = normalize_slash_commands(cmds)
        assert result[0][0] == "review_pr"

    def test_lowercase(self):
        cmds = [{"name": "/MyCommand", "description": "Test"}]
        result = normalize_slash_commands(cmds)
        assert result[0][0] == "mycommand"

    def test_truncate_to_32_chars(self):
        cmds = [{"name": "/" + "a" * 40, "description": "Test"}]
        result = normalize_slash_commands(cmds)
        assert len(result[0][0]) == 32

    def test_skip_empty_names(self):
        cmds = [
            {"name": "/valid", "description": "OK"},
            {"name": "", "description": "Bad"},
        ]
        result = normalize_slash_commands(cmds)
        assert len(result) == 1

    def test_description_truncated_to_256(self):
        cmds = [{"name": "/cmd", "description": "x" * 300}]
        result = normalize_slash_commands(cmds)
        assert len(result[0][1]) == 256
