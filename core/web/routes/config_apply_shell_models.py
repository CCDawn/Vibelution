"""Public contracts for config apply, shell, and media JSON routes.

Apply and language/intake reuse workspace/summary envelopes. Known shell and
image-upload fields stay explicit for OpenAPI and typed clients while
forward-compatible extras pass through.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ConfigOpenEnvironmentResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    opened: bool = False
    focused: bool = False
    method: str = ""
    cleanup_ok: bool = False
    cleanup_error: str | None = None


class ConfigImageUploadResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    path: str = ""
    url: str = ""
    contentType: str = ""
    sizeBytes: int = 0
