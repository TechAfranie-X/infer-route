"""Exception handlers that keep internal failures off the wire."""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.exceptions import InferRouteError, error_payload

logger = logging.getLogger("inferroute.errors")


async def inferroute_error_handler(request: Request, exc: InferRouteError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or exc.request_id
    logger.warning(
        exc.message,
        extra={
            "event": "gateway_error",
            "request_id": request_id,
            "error_code": exc.code,
        },
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(exc.code, exc.message, request_id),
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    logger.exception(
        "unhandled error",
        extra={"event": "internal_error", "request_id": request_id},
    )
    response = JSONResponse(
        status_code=500,
        content=error_payload(
            "internal_error",
            "An internal error occurred.",
            request_id,
        ),
    )
    if request_id:
        response.headers["X-Request-ID"] = request_id
    return response
