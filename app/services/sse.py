"""Server-Sent Events for token streaming.

Each event is one ``data:`` line followed by a blank line. Headers include
``Cache-Control: no-cache`` and ``X-Accel-Buffering: no`` so proxies do not
hold the body until the model finishes.
"""

from __future__ import annotations

import json


def sse_token(token: str) -> bytes:
    return _event({"token": token})


def sse_done() -> bytes:
    return b"data: [DONE]\n\n"


def sse_error(message: str) -> bytes:
    return _event({"error": {"code": "stream_interrupted", "message": message}})


def _event(payload: dict[str, object]) -> bytes:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n".encode()
