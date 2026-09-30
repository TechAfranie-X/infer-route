"""Monotonic timing helpers."""

from __future__ import annotations

import time


def monotonic_ms() -> float:
    """Current monotonic clock in milliseconds."""

    return time.perf_counter() * 1000


def elapsed_ms(start_ms: float) -> float:
    """Milliseconds elapsed since ``start_ms`` from :func:`monotonic_ms`."""

    return monotonic_ms() - start_ms
