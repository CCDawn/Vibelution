"""Public rewind contracts for the session file-change ledger.

Preview is read-only; apply is a strict whole-turn restore with an explicit
force escape hatch. Responses pass through the ledger's per-file fields so
the client can render classification without a second round-trip.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class SessionRewindFileItem(BaseModel):
    """One checkpointed file inside a rewind plan."""

    model_config = ConfigDict(extra="allow")

    path: str
    action: str = "none"
    classification: str = "safe"
    state: str = ""
    currentExists: bool = False
    currentSize: int = 0


class SessionRewindPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    sessionId: str
    turnId: str
    files: list[SessionRewindFileItem] = []
    canApply: bool = False
    capabilityNote: str = ""


class SessionRewindApplyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turnId: str
    force: bool = False


class SessionRewindApplyResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    sessionId: str
    turnId: str
    status: str = ""
    alreadyApplied: bool = False
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
