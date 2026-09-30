"""OpenAI-compatible mock model endpoint.

Modes are development controls used to demonstrate latency, failure, and recovery.
They are exposed only by this process, never by the gateway.
"""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import AsyncIterator
from typing import Literal

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.mock.settings import MockMode, MockSettings

_REPLY = "Distributed systems share work across machines and tolerate partial failure."


class MockState:
    def __init__(self, settings: MockSettings) -> None:
        self.settings = settings
        self.mode: MockMode = settings.mock_mode
        self._rng = random.Random(0)

    def reply(self) -> str:
        return f"[{self.settings.mock_provider_id}] {_REPLY}"


class ModeUpdate(BaseModel):
    mode: MockMode


class MockChatRequest(BaseModel):
    model: str = "general"
    messages: list[dict[str, str]] = Field(default_factory=list)
    temperature: float = 0.7
    max_tokens: int = 200
    stream: bool = False


def create_mock_app(settings: MockSettings | None = None) -> FastAPI:
    resolved = settings or MockSettings()
    state = MockState(resolved)
    app = FastAPI(title=f"InferRoute mock {resolved.mock_provider_id}")
    app.state.mock_state = state

    @app.get("/health")
    async def health() -> JSONResponse:
        if state.mode == "offline":
            return JSONResponse(status_code=503, content={"status": "offline"})
        return JSONResponse(
            content={
                "status": "ok",
                "provider": resolved.mock_provider_id,
                "mode": state.mode,
            }
        )

    @app.post("/mock/mode")
    async def set_mode(body: ModeUpdate) -> dict[str, str]:
        state.mode = body.mode
        return {"provider": resolved.mock_provider_id, "mode": state.mode}

    @app.post("/v1/chat/completions", response_model=None)
    async def completions(body: MockChatRequest) -> JSONResponse | StreamingResponse:
        failure = await _prepare(state)
        if failure is not None:
            return failure
        content = state.reply()
        if body.stream:
            return StreamingResponse(
                _stream(content, state),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        return JSONResponse(
            content={
                "id": f"mock_{resolved.mock_provider_id}",
                "choices": [{"message": {"role": "assistant", "content": content}}],
            }
        )

    return app


async def _prepare(state: MockState) -> JSONResponse | None:
    mode: Literal["healthy", "slow", "failing", "offline"] = state.mode
    if mode == "offline":
        await asyncio.sleep(state.settings.mock_offline_delay_seconds)
        return JSONResponse(status_code=503, content={"error": "offline"})
    if mode == "failing" or state._rng.random() < state.settings.mock_failure_rate:
        return JSONResponse(status_code=500, content={"error": "injected failure"})
    if mode == "slow":
        delay_ms = state.settings.mock_slow_latency_ms
    else:
        delay_ms = state.settings.mock_latency_ms
    if delay_ms > 0:
        await asyncio.sleep(delay_ms / 1000)
    return None


async def _stream(content: str, state: MockState) -> AsyncIterator[str]:
    parts = content.split(" ")
    for index, part in enumerate(parts):
        token = part if index == len(parts) - 1 else f"{part} "
        payload = {"choices": [{"delta": {"content": token}}]}
        yield f"data: {json.dumps(payload)}\n\n"
        if state.mode == "failing":
            return
    yield "data: [DONE]\n\n"
