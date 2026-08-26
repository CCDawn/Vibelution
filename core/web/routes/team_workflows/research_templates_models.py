"""Public contracts for team workflow research template-baseline routes.

Template baselines freeze the experiment design authority per question
scope.  The write envelope stays a catch-all because the frozen baseline
record shape is owned by the service layer; routes only carry the required
creation fields explicitly.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TemplateBaselineCreatePayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    templateId: str
    parentBaselineId: str = ""
    version: int = 0
    content: dict[str, Any] = Field(default_factory=dict)
    approvedBy: str = ""
    approvalRef: str = ""
    semanticChangeReason: str = ""
    program: str = ""
    theme: str = ""
    campaign: str = ""
    question: str = ""
    branch: str = ""
    workflow: str = ""


class TemplateBaselineRouteResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    status: str = ""
