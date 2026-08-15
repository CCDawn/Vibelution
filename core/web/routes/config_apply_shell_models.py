"""Public contracts for config apply, shell, and media JSON routes.

Apply and language/intake reuse workspace/summary envelopes. Open-environment
and image-upload payloads still evolve, so only fields that exist on every
successful shape are required. Routes must use
response_model_exclude_unset=True so missing optional fields stay absent.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ConfigOpenEnvironmentResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    opened: bool = False


class ConfigImageUploadResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    url: str = ""
