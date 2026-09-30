"""Structured logging helpers."""

import json
import logging

from app.core.logging import JsonFormatter, configure_logging, redact_url


def test_json_formatter_includes_extra_event_fields() -> None:
    record = logging.LogRecord(
        name="inferroute.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="redis connection established",
        args=(),
        exc_info=None,
    )
    record.event = "redis_connected"
    record.request_id = "req_abc123def456"
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "redis connection established"
    assert payload["event"] == "redis_connected"
    assert payload["request_id"] == "req_abc123def456"
    assert payload["level"] == "INFO"


def test_redact_url_hides_password() -> None:
    assert redact_url("redis://:s3cret@redis:6379/0") == "redis://***@redis:6379/0"


def test_redact_url_leaves_urls_without_credentials_unchanged() -> None:
    url = "redis://redis:6379/0"
    assert redact_url(url) == url


def test_configure_logging_replaces_handlers() -> None:
    configure_logging("INFO")
    configure_logging("WARNING")
    logger = logging.getLogger("inferroute")
    assert len(logger.handlers) == 1
    assert logger.level == logging.WARNING
