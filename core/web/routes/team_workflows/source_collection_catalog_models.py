"""Public contracts for source-collection catalog read routes.

Summary payloads still evolve. Only identifiers that exist on every
successful shape are required. Routes must use
response_model_exclude_unset=True so missing optional fields stay absent
instead of being filled with defaults.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SourceCollectionSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    runId: str = ""
