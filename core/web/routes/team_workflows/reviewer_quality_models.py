# -*- coding: utf-8 -*-
"""Public contracts for the reviewer diagnostic-reward quality route."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ReviewerDiagnosticRewardResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 1
    teamId: str = ""
    roundCount: int = 0
    ordinalHydratedFromAuthority: bool = False
    snapshotPersisted: bool = False
