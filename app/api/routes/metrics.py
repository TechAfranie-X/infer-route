"""Prometheus scrape endpoint."""

from fastapi import APIRouter
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST

from app.api.dependencies import MetricsDep

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def metrics(metrics_service: MetricsDep) -> Response:
    return Response(content=metrics_service.render(), media_type=CONTENT_TYPE_LATEST)
