"""Public contracts for retired Web reset JSON routes.

These endpoints always return HTTP 410 with a stable migration envelope.
Known detail fields stay explicit for OpenAPI. Routes must declare
response_model so the untyped-endpoint budget stays honest.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ResetSelectionPayload(BaseModel):
    itemIds: list[str] = Field(default_factory=list)


class ResetExecutePayload(ResetSelectionPayload):
    confirmed: bool = False


class ResetMigratedResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    code: str = ""
    message: str = ""
    launcherPath: str = ""
