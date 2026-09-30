"""Chat completion route. Provider selection lives in the inference service."""

from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.dependencies import InferenceDep
from app.models.requests import ChatCompletionRequest
from app.models.responses import ChatCompletionResponse
from app.services.inference import StreamMeta
from app.services.sse import sse_token

router = APIRouter(tags=["inference"])


def completion_headers(result: ChatCompletionResponse, *, cache_status: str) -> dict[str, str]:
    return {
        "X-InferRoute-Provider": result.provider,
        "X-InferRoute-Cache": cache_status,
        "X-InferRoute-Attempts": str(result.attempts),
        "X-InferRoute-Latency-Ms": f"{result.latency_ms:.2f}",
        "X-InferRoute-Fallback": "true" if result.fallback_used else "false",
    }


def stream_headers(meta: StreamMeta) -> dict[str, str]:
    return {
        "X-InferRoute-Provider": meta.provider,
        "X-InferRoute-Cache": meta.cache_status,
        "X-InferRoute-Attempts": str(meta.attempts),
        "X-InferRoute-Latency-Ms": f"{meta.ttft_ms:.2f}",
        "X-InferRoute-TTFT-Ms": f"{meta.ttft_ms:.2f}",
        "X-InferRoute-Fallback": "true" if meta.fallback_used else "false",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }


@router.post("/v1/chat/completions", response_model=None)
async def chat_completions(
    body: ChatCompletionRequest,
    request: Request,
    service: InferenceDep,
) -> JSONResponse | StreamingResponse:
    request_id = getattr(request.state, "request_id", None) or "req_unknown"
    if body.stream:
        meta, first_token, rest = await service.open_stream(body, request_id)
        return StreamingResponse(
            _stream_body(first_token, rest),
            media_type="text/event-stream",
            headers=stream_headers(meta),
        )
    result = await service.complete(body, request_id)
    return JSONResponse(
        content=result.model_dump(mode="json"),
        headers=completion_headers(result, cache_status=result.cache_status),
    )


async def _stream_body(first_token: str, rest: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    yield sse_token(first_token)
    async for chunk in rest:
        yield chunk
