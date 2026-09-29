"""Stdlib logging setup for the ``OMNE`` logger hierarchy."""

from __future__ import annotations

import json
import logging
import sys
from contextlib import suppress
from datetime import UTC, datetime
from typing import TextIO

from core.config.settings import Settings

LOGGER_NAMESPACE = "OMNE"


class RetainStreamHandler(logging.StreamHandler[TextIO]):
    """Stream handler that leaves the caller-owned stream open."""

    def close(self) -> None:
        # A caller may already have closed the stream, for example a test capture.
        with suppress(ValueError):
            self.flush()
        logging.Handler.close(self)


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Emit a single-line text record."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )


def get_logger(suffix: str = "core") -> logging.Logger:
    """Return a logger under the ``OMNE`` namespace."""

    if suffix == "" or suffix == LOGGER_NAMESPACE:
        return logging.getLogger(LOGGER_NAMESPACE)
    if suffix.startswith(f"{LOGGER_NAMESPACE}."):
        return logging.getLogger(suffix)
    return logging.getLogger(f"{LOGGER_NAMESPACE}.{suffix}")


def configure_logging(settings: Settings, *, stream: TextIO | None = None) -> logging.Logger:
    """Configure the ``OMNE`` logger from settings.

    Repeated calls replace the previous handler so logs are not duplicated.
    """

    logger = logging.getLogger(LOGGER_NAMESPACE)
    logger.setLevel(settings.log_level)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    handler = RetainStreamHandler(stream if stream is not None else sys.stderr)
    handler.setLevel(settings.log_level)
    if settings.log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(TextFormatter())
    logger.addHandler(handler)
    return logger
