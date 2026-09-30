"""Structured JSON logging.

Logs are single-line JSON objects so a request can be followed by ``request_id``
without a log shipper that understands multi-line tracebacks as one event.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

_STANDARD_LOG_RECORD_ATTRS = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """Format log records as JSON objects, including non-standard ``extra`` fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_LOG_RECORD_ATTRS or key.startswith("_"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    """Attach one JSON handler to the InferRoute logger tree.

    Idempotent: repeated calls replace the handler instead of stacking duplicates
    when the app is created more than once in a test process.
    """

    logger = logging.getLogger("inferroute")
    logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


def redact_url(url: str) -> str:
    """Hide userinfo in a URL before it is written to a log line."""

    parts = urlsplit(url)
    if parts.username is None and parts.password is None:
        return url
    hostname = parts.hostname or ""
    if parts.port is not None:
        hostname = f"{hostname}:{parts.port}"
    return urlunsplit((parts.scheme, f"***@{hostname}", parts.path, parts.query, parts.fragment))
