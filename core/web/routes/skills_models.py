"""Public contracts for skill library JSON routes.

Known catalog identifiers stay explicit for OpenAPI. Preview and content
payloads still evolve, so extras pass through. Routes must use
response_model_exclude_unset=True.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SkillLibraryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    mode: str = ""


class SkillLibraryDetailResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    command: str = ""
    name: str = ""
