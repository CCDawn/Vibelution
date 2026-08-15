"""Public contracts for team workflow orchestration routes.

Workflow payloads still evolve. Dual-shape endpoints only require
identifiers that exist on every successful shape. Routes must use
response_model_exclude_unset=True so missing optional fields stay absent
instead of being filled with defaults.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class TeamWorkflowOrchestrationResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    teamId: str = ""
