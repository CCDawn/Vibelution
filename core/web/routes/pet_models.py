"""Public contracts for pet space JSON routes.

Known summary identifiers stay explicit for OpenAPI. Attribute payloads still
evolve, so extras pass through. Routes must use
response_model_exclude_unset=True.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PetActionRequest(BaseModel):
    action: str


class PetSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = ""
    avatarPreset: str = ""


class PetActionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    action: str = ""
    message: str = ""
