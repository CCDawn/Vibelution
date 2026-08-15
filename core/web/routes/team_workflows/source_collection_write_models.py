"""Public contracts for source-collection start/session write routes.

Run start, agent-session context, and stage-session task payloads still
evolve. Dual-shape endpoints only require identifiers that exist on every
successful shape. Routes must use response_model_exclude_unset=True so
missing optional fields stay absent instead of being filled with defaults.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SourceCollectionRunStartResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    researchProjectId: str = ""


class SourceCollectionAgentSessionContextResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    teamId: str = ""
    runId: str = ""
    sessionId: str = ""


class SourceCollectionStageSessionTaskResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    teamId: str = ""
    runId: str = ""
    taskId: str = ""
