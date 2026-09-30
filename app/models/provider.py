"""Static provider configuration.

Runtime health is tracked separately and must not be stored on this object.
"""

from pydantic import BaseModel, Field


class ProviderConfig(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    model: str = Field(min_length=1)
    weight: float = Field(default=1.0, gt=0)
    enabled: bool = True
    timeout_seconds: float = Field(default=20.0, gt=0)
    max_retries: int = Field(default=1, ge=0)
