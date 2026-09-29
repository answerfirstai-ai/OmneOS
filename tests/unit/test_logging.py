"""Logging configuration tests."""

from __future__ import annotations

import json
from io import StringIO

from core.config.settings import Settings
from core.logging_config import configure_logging, get_logger


def test_text_log_contains_level_and_message() -> None:
    buffer = StringIO()
    configure_logging(Settings(log_format="text", log_level="INFO"), stream=buffer)

    get_logger("core").info("core ready")

    output = buffer.getvalue()
    assert "INFO" in output
    assert "OMNE.core" in output
    assert "core ready" in output


def test_json_log_is_structured() -> None:
    buffer = StringIO()
    configure_logging(Settings(log_format="json", log_level="INFO"), stream=buffer)

    get_logger("api").warning("listening")

    payload = json.loads(buffer.getvalue())
    assert payload["message"] == "listening"
    assert payload["level"] == "WARNING"
    assert payload["logger"] == "OMNE.api"
    assert isinstance(payload["timestamp"], str)


def test_reconfigure_does_not_duplicate_handlers() -> None:
    buffer = StringIO()
    settings = Settings()
    configure_logging(settings, stream=buffer)
    configure_logging(settings, stream=buffer)

    get_logger("core").info("once")

    assert buffer.getvalue().count("once") == 1


def test_debug_records_are_filtered_at_info() -> None:
    buffer = StringIO()
    configure_logging(Settings(log_level="INFO"), stream=buffer)

    get_logger("core").debug("hidden detail")
    get_logger("core").info("visible")

    output = buffer.getvalue()
    assert "hidden detail" not in output
    assert "visible" in output
