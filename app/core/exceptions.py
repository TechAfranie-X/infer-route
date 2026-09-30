"""Gateway errors returned to API clients.

Handlers must log diagnostic detail server-side and return only ``code``,
``message``, and ``request_id``. Stack traces stay out of the response body.
"""

from __future__ import annotations


class InferRouteError(Exception):
    """Base class for failures that have a stable client-facing error code."""

    code = "internal_error"
    status_code = 500

    def __init__(self, message: str, *, request_id: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.request_id = request_id


def error_payload(
    code: str,
    message: str,
    request_id: str | None,
) -> dict[str, dict[str, str | None]]:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
        }
    }
