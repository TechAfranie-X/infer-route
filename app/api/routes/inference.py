"""Chat completion route. Provider selection lives in the inference service."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.dependencies import InferenceDep
from app.models.requests import ChatCompletionRequest
from app.models.responses import ChatCompletionResponse

router = APIRouter(tags=["inference"])


def completion_headers(result: ChatCompletionResponse, *, cache_status: str) -> dict[str, str]:
    return {
        "X-InferRoute-Provider": result.provider,
        "X-InferRoute-Cache": cache_status,
        "X-InferRoute-Attempts": str(result.attempts),
        "X-InferRoute-Latency-Ms": f"{result.latency_ms:.2f}",
        "X-InferRoute-Fallback": "true" if result.fallback_used else "false",
    }


@router.post("/v1/chat/completions")
async def chat_completions(
    body: ChatCompletionRequest,
    request: Request,
    service: InferenceDep,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or "req_unknown"
    result = await service.complete(body, request_id)
    return JSONResponse(
        content=result.model_dump(mode="json"),
        headers=completion_headers(result, cache_status="BYPASS"),
    )
