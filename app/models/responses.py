"""Normalized inference responses."""

from typing import Literal

from pydantic import BaseModel, Field


class ChatCompletionResponse(BaseModel):
    id: str
    model: str
    provider: str
    cached: bool
    attempts: int = Field(ge=1)
    latency_ms: float = Field(ge=0)
    fallback_used: bool = False
    cache_status: Literal["HIT", "MISS", "BYPASS"] = Field(default="BYPASS", exclude=True)
    content: str
