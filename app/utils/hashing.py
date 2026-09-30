"""Canonical cache keys for chat requests.

The key covers the fields that change a deterministic completion. Role, content,
model, temperature, and max tokens are included. Volatile fields such as the
request id are not, so identical prompts share one Redis entry.
"""

from __future__ import annotations

import hashlib
import json

from app.models.requests import ChatCompletionRequest


def canonical_request(request: ChatCompletionRequest) -> str:
    payload = {
        "max_tokens": request.max_tokens,
        "messages": [message.model_dump() for message in request.messages],
        "model": request.model,
        "temperature": request.temperature,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def response_cache_key(request: ChatCompletionRequest) -> str:
    digest = hashlib.sha256(canonical_request(request).encode("utf-8")).hexdigest()
    return f"inferroute:response:{digest}"


def lock_cache_key(request: ChatCompletionRequest) -> str:
    digest = hashlib.sha256(canonical_request(request).encode("utf-8")).hexdigest()
    return f"inferroute:lock:{digest}"
