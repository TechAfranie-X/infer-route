"""Public inference request models.

The gateway accepts a small OpenAI-shaped subset. Provider-specific parameters
stay out of this contract.
"""

from typing import Literal

from pydantic import BaseModel, Field

MessageRole = Literal["system", "user", "assistant"]


class ChatMessage(BaseModel):
    role: MessageRole
    content: str = Field(min_length=1, max_length=100_000)


class ChatCompletionRequest(BaseModel):
    model: str = Field(default="general", min_length=1, max_length=128)
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=200, ge=1, le=4096)
    stream: bool = False
