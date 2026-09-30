"""Request identifiers."""

from __future__ import annotations

import re
from uuid import uuid4

REQUEST_ID_PATTERN = re.compile(r"^req_[a-f0-9]{12}$")


def generate_request_id() -> str:
    """Return an identifier such as ``req_7f3be91a0c4d``."""

    return f"req_{uuid4().hex[:12]}"


def resolve_request_id(header_value: str | None) -> str:
    """Reuse a caller-supplied id only when it matches the gateway format.

    Arbitrary header values are rejected so a client cannot inject newlines or
    extra JSON into structured logs.
    """

    if header_value and REQUEST_ID_PATTERN.fullmatch(header_value):
        return header_value
    return generate_request_id()
