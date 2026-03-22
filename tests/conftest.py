"""Shared test fixtures for ccremote."""

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Ensure no real .ccremote file interferes with tests."""
    monkeypatch.chdir(os.path.dirname(__file__))


def set_valid_env(monkeypatch, **overrides):
    """Set minimal valid env vars for config."""
    defaults = {
        "CCREMOTE_BOT_TOKEN": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        "CCREMOTE_ALLOWED_USER": "123456789",
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        monkeypatch.setenv(k, str(v))


def write_ccremote_file(directory: Path, **fields) -> Path:
    """Write a .ccremote file with the given fields."""
    defaults = {
        "CCREMOTE_BOT_TOKEN": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        "CCREMOTE_ALLOWED_USER": "123456789",
    }
    defaults.update(fields)
    ccremote = directory / ".ccremote"
    ccremote.write_text("\n".join(f"{k}={v}" for k, v in defaults.items()) + "\n")
    return ccremote


@pytest.fixture
def valid_env(monkeypatch):
    set_valid_env(monkeypatch)
