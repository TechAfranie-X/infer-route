"""Small bounded delays between retries.

Inference traffic is latency sensitive, so the base delay stays well under a
typical model call. Jitter avoids synchronized retries from many gateway workers.
"""

from __future__ import annotations

import random


def backoff_seconds(retry_number: int, *, base_seconds: float, jitter_seconds: float) -> float:
    """``base * 2^(retry-1) + jitter``, with ``retry_number`` starting at 1."""

    if retry_number < 1:
        raise ValueError("retry_number starts at 1")
    growth = base_seconds * (2 ** (retry_number - 1))
    return growth + random.uniform(0, jitter_seconds)
