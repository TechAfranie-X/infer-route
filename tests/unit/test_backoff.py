"""Retry delay growth."""

from app.services.backoff import backoff_seconds


def test_backoff_doubles_each_retry_when_jitter_is_zero() -> None:
    assert backoff_seconds(1, base_seconds=0.05, jitter_seconds=0) == 0.05
    assert backoff_seconds(2, base_seconds=0.05, jitter_seconds=0) == 0.1
    assert backoff_seconds(3, base_seconds=0.05, jitter_seconds=0) == 0.2
