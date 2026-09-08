"""Public contracts for pet space JSON routes.

Known summary identifiers stay explicit for OpenAPI. Attribute payloads still
evolve, so extras pass through. Routes must use
response_model_exclude_unset=True.
"""

from __future__ import annotations

from typing import Literal

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


PetActivityTone = Literal["approval", "error", "running", "completed", "idle"]
PetActivityPhase = Literal[
    "waiting",
    "error",
    "thinking",
    "reading",
    "tooling",
    "verifying",
    "answering",
    "completed",
]
PetAnimationState = Literal[
    "idle",
    "waiting",
    "alert",
    "thinking",
    "reading",
    "tooling",
    "verifying",
    "answering",
    "celebrating",
]


class PetActivitySessionResponse(BaseModel):
    sessionId: str
    title: str
    agentId: str = ""
    agentDisplayName: str = ""
    tone: PetActivityTone
    phase: PetActivityPhase
    updatedAt: str = ""


class PetActivityResponse(BaseModel):
    schemaVersion: Literal[1] = 1
    aggregateTone: PetActivityTone
    animationState: PetAnimationState
    activeCount: int
    attentionCount: int
    generatedAt: str
    sessions: list[PetActivitySessionResponse]
