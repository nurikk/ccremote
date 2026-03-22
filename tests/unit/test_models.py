"""Unit tests for data models."""

from datetime import UTC, datetime

from ccremote.models import Session, SessionStatus


class TestSession:
    def test_new_session_is_active(self):
        session = Session(session_id="test-123", working_directory="/tmp/test")
        assert session.status == SessionStatus.ACTIVE

    def test_terminate_session(self):
        session = Session(session_id="test-123", working_directory="/tmp/test")
        session.terminate()
        assert session.status == SessionStatus.TERMINATED

    def test_created_at_is_set(self):
        before = datetime.now(UTC)
        session = Session(session_id="test-123", working_directory="/tmp/test")
        assert session.created_at >= before

    def test_slash_commands_default_empty(self):
        session = Session(session_id="test-123", working_directory="/tmp/test")
        assert session.slash_commands == []

    def test_claude_session_id_default_empty(self):
        session = Session(session_id="test-123", working_directory="/tmp/test")
        assert session.claude_session_id == ""
