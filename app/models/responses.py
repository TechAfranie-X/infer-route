"""Normalized inference responses."""

from pydantic import BaseModel, Field


class ChatCompletionResponse(BaseModel):
    id: str
    model: str
    provider: str
    cached: bool
    attempts: int = Field(ge=1)
    latency_ms: float = Field(ge=0)
    content: str
