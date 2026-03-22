"""Unit tests for relay."""

from ccremote.relay import DraftBuilder, parse_claude_event


class TestClaudeEventParsing:
    def test_parse_system_init(self):
        event = {
            "type": "system",
            "subtype": "init",
            "session_id": "abc-123",
            "slash_commands": [{"name": "/commit", "description": "Create a commit"}],
        }
        result = parse_claude_event(event)
        assert result["type"] == "init"
        assert result["session_id"] == "abc-123"
        assert len(result["slash_commands"]) == 1

    def test_parse_assistant_text(self):
        event = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Hello world"}]},
        }
        result = parse_claude_event(event)
        assert result["type"] == "assistant"
        assert result["text"] == "Hello world"

    def test_parse_assistant_with_tool_use(self):
        event = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "Let me read that."},
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "Read",
                        "input": {"file_path": "/tmp/x"},
                    },
                ],
            },
        }
        result = parse_claude_event(event)
        assert result["type"] == "assistant"
        assert len(result["tool_uses"]) == 1
        assert result["tool_uses"][0]["name"] == "Read"

    def test_parse_tool_result(self):
        event = {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": "file contents"}
                ]
            },
            "tool_use_result": {"durationMs": 42, "filenames": ["/tmp/x"]},
        }
        result = parse_claude_event(event)
        assert result["type"] == "tool_result"
        assert result["duration_ms"] == 42
        assert "/tmp/x" in result["filenames"]

    def test_parse_stream_text_delta(self):
        event = {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "chunk"},
            },
        }
        result = parse_claude_event(event)
        assert result["type"] == "text_delta"
        assert result["text"] == "chunk"

    def test_parse_tool_start(self):
        event = {
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "content_block": {"type": "tool_use", "id": "t1", "name": "Bash"},
            },
        }
        result = parse_claude_event(event)
        assert result["type"] == "tool_start"
        assert result["name"] == "Bash"

    def test_parse_thinking_start(self):
        event = {
            "type": "stream_event",
            "event": {"type": "content_block_start", "content_block": {"type": "thinking"}},
        }
        result = parse_claude_event(event)
        assert result["type"] == "thinking_start"

    def test_parse_thinking_delta(self):
        event = {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "thinking_delta", "thinking": "hmm"},
            },
        }
        result = parse_claude_event(event)
        assert result["type"] == "thinking_delta"
        assert result["text"] == "hmm"

    def test_parse_result(self):
        event = {
            "type": "result",
            "subtype": "success",
            "result": "Final output",
        }
        result = parse_claude_event(event)
        assert result["type"] == "result"
        assert result["text"] == "Final output"

    def test_parse_api_retry(self):
        event = {"type": "system", "subtype": "api_retry", "attempt": 1, "error": "rate_limit"}
        result = parse_claude_event(event)
        assert result["type"] == "api_retry"

    def test_parse_unknown_event(self):
        result = parse_claude_event({"type": "unknown_thing"})
        assert result["type"] == "unknown"


class TestDraftBuilder:
    def test_text_delta_accumulates(self):
        d = DraftBuilder()
        d.process({"type": "text_delta", "text": "Hello "})
        d.process({"type": "text_delta", "text": "world"})
        assert "Hello world" in d.build_draft()

    def test_tool_start_shows_active(self):
        d = DraftBuilder()
        d.process({"type": "tool_start", "name": "Read", "id": "t1"})
        assert "Read" in d.build_draft()

    def test_tool_complete_shows_in_log(self):
        d = DraftBuilder()
        d.process({"type": "tool_start", "name": "Bash", "id": "t1"})
        d.process({"type": "input_delta", "json": '{"command": "ls /tmp"}'})
        d.process({"type": "block_stop"})
        draft = d.build_draft()
        assert "Bash" in draft
        assert "ls /tmp" in draft

    def test_quiet_tools_filtered_from_log(self):
        d = DraftBuilder()
        for tool in ("Read", "Edit", "Grep"):
            d.process({"type": "tool_start", "name": tool, "id": "t1"})
            d.process({"type": "block_stop"})
        assert d.tool_log == []

    def test_thinking_shows_indicator(self):
        d = DraftBuilder()
        d.process({"type": "thinking_start"})
        assert "Thinking" in d.build_draft()
        d.process({"type": "thinking_delta", "text": "Let me consider..."})
        assert "consider" in d.build_draft()
        d.process({"type": "block_stop"})
        assert "consider" not in d.build_draft()

    def test_bash_tool_shows_command(self):
        d = DraftBuilder()
        d.process({"type": "tool_start", "name": "Bash", "id": "t1"})
        d.process({"type": "input_delta", "json": '{"command": "ls -la"}'})
        d.process({"type": "block_stop"})
        assert "ls -la" in d.build_draft()

    def test_final_message_has_response(self):
        d = DraftBuilder()
        d.process({"type": "text_delta", "text": "The answer is 42."})
        d.process({"type": "result", "text": "The answer is 42.", "num_turns": 1})
        final = d.build_final()
        assert "The answer is 42." in final

    def test_truncates_to_max_length(self):
        d = DraftBuilder(max_length=50)
        d.process({"type": "text_delta", "text": "x" * 100})
        assert len(d.build_draft()) <= 50

    def test_tool_result_shows_duration(self):
        d = DraftBuilder()
        d.process(
            {
                "type": "tool_result",
                "results": [{"content": "ok"}],
                "duration_ms": 100,
                "filenames": [],
            }
        )
        assert "100ms" in d.build_draft()
