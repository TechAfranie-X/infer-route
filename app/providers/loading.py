"""Build HTTP providers from the committed provider config file."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx

from app.core.config import Settings
from app.models.provider import ProviderConfig
from app.providers.base import LLMProvider
from app.providers.http_provider import HTTPProvider

logger = logging.getLogger("inferroute.providers")


def load_provider_configs(path: str) -> list[ProviderConfig]:
    file_path = Path(path)
    if not file_path.is_file():
        logger.warning(
            "provider config file is missing",
            extra={"event": "providers_missing", "path": path},
        )
        return []
    raw = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("provider config must be a JSON list")
    return [ProviderConfig.model_validate(item) for item in raw]


def build_http_providers(settings: Settings, client: httpx.AsyncClient) -> list[LLMProvider]:
    configs = load_provider_configs(settings.providers_config_path)
    return [
        HTTPProvider(
            config,
            client,
            connect_timeout_seconds=settings.http_connect_timeout_seconds,
        )
        for config in configs
    ]
