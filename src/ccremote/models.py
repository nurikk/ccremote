"""Data models for ccremote."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class SessionStatus(StrEnum):
    ACTIVE = "active"
    TERMINATED = "terminated"


class Session(BaseModel):
    session_id: str
    claude_session_id: str = ""
    working_directory: str
    status: SessionStatus = SessionStatus.ACTIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_message_at: datetime | None = None
    process_pid: int | None = None
    slash_commands: list[tuple[str, str]] = Field(default_factory=list)

    def terminate(self) -> None:
        self.status = SessionStatus.TERMINATED
