"""Public contracts for usage summary JSON routes.

Known envelope fields stay explicit for OpenAPI. Nested rollups still evolve,
so extras pass through. Routes must use response_model_exclude_unset=True.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class UsageSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    scope: str = ""
    filters: dict[str, str] = Field(default_factory=dict)
    updatedAt: str = ""
