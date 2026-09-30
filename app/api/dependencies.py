"""FastAPI dependencies for shared application services."""

from typing import Annotated

from fastapi import Depends, Request

from app.core.config import Settings
from app.services.readiness import RedisProbe


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_redis(request: Request) -> RedisProbe:
    return request.app.state.redis


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
RedisDep = Annotated[RedisProbe, Depends(get_redis)]
