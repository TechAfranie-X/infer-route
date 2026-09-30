"""Errors raised by a single provider call.

These stay inside the gateway. The inference service decides which client-facing
error to return after retries and fallback finish.
"""

from __future__ import annotations


class ProviderCallError(Exception):
    def __init__(
        self,
        message: str,
        *,
        provider_id: str,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.provider_id = provider_id
        self.status_code = status_code


class RetryableProviderError(ProviderCallError):
    """Timeouts, connection failures, and overloaded or broken endpoints."""


class NonRetryableProviderError(ProviderCallError):
    """Bad requests and authentication mistakes. Another provider will not fix these."""


class StreamInterruptedError(RetryableProviderError):
    """The provider closed a stream after zero or more tokens."""

    def __init__(
        self,
        message: str,
        *,
        provider_id: str,
        tokens_sent: int,
    ) -> None:
        super().__init__(message, provider_id=provider_id)
        self.tokens_sent = tokens_sent
