"""Public contracts for Team write JSON routes.

Create/update/archive/sync reuse the catalog detail envelope. Canvas writes
reuse the catalog canvas envelope. AI-search start, team messages, and Agent
repair payloads still evolve, so only identifiers that exist on every
successful shape are required. Routes must use
response_model_exclude_unset=True so missing optional fields stay absent.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class TeamAiSearchRunResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    runId: str = ""


class TeamMessageResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    eventId: str = ""


class TeamRepairResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    teamId: str = ""
