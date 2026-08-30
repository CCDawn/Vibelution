"""Typed HTTP contracts for the virtual-human-life plugin."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class VirtualHumanLocationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locationId: str
    countryCode: str
    countryName: str
    regionCode: str
    regionName: str
    cityCode: str
    cityName: str
    timezone: str
    locale: str
    latitude: float
    longitude: float
    precision: str
    sourceKind: str
    sourceVersion: str


class VirtualHumanSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    pluginId: str
    agentId: str
    installed: bool
    bound: bool
    binding: dict[str, Any] | None = None
    state: dict[str, Any] | None = None
    todaySchedule: dict[str, Any] | None = None
    tomorrowSchedule: dict[str, Any] | None = None
    todayCalendar: dict[str, Any] | None = None
    tomorrowCalendar: dict[str, Any] | None = None
    rhythms: dict[str, Any] | None = None
    causal: dict[str, Any] | None = None
    proactiveUsage: dict[str, int] = Field(default_factory=dict)
    health: dict[str, Any] | None = None


class VirtualHumanMemoryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    agentId: str
    episodeId: str
    text: str
    occurredAt: str = ""
    salienceScore: int = 0
    sourceEventIds: list[str] = Field(default_factory=list)
    promotedAt: str = ""


class VirtualHumanScheduleResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    agentId: str
    today: dict[str, Any] | None = None
    tomorrow: dict[str, Any] | None = None


class VirtualHumanEventResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    eventId: str
    agentId: str
    kind: str


class VirtualHumanDiaryEntryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    diaryEntryId: str
    agentId: str
    localDate: str
    sourceEventIds: list[str] = Field(default_factory=list)


class VirtualHumanRelationshipResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    targetId: str
    intimacy: int = 0
    trust: int = 0


class VirtualHumanCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agentId: str
    command: str = Field(min_length=1, max_length=80)
    expectedVersion: int = Field(ge=0)
    idempotencyKey: str = Field(min_length=1, max_length=200)
    arguments: dict[str, Any] = Field(default_factory=dict)


class VirtualHumanCommandResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    agentId: str
    command: str
    idempotencyKey: str
    stateVersion: int
    result: dict[str, Any] = Field(default_factory=dict)


class VirtualHumanLifeDraftUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agentId: str
    draftId: str = Field(min_length=1, max_length=200)
    expectedRevision: int = Field(ge=1)
    idempotencyKey: str = Field(min_length=1, max_length=200)
    patch: dict[str, Any] = Field(default_factory=dict)


class VirtualHumanLifeDraftResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    draftId: str
    revision: int
    status: str
    payload: dict[str, Any]


class VirtualHumanLifeWorldConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agentId: str
    draftId: str = Field(min_length=1, max_length=200)
    expectedDraftRevision: int = Field(ge=1)
    expectedBindingVersion: int = Field(ge=0)
    idempotencyKey: str = Field(min_length=1, max_length=200)


class VirtualHumanLifeWorldConfirmResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    agentId: str
    binding: dict[str, Any]
    lifeWorld: dict[str, Any]
    confirmation: dict[str, Any]


class VirtualHumanConversationMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clientSubmissionId: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=20000)
    contentUtf8Base64: str = Field(default="", max_length=40000)
    attachmentIds: list[str] = Field(default_factory=list, max_length=20)
    references: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    mentalModelEnabled: bool | None = None
    runtimeStatusEnabled: bool | None = None
    turnStatusTail: dict[str, Any] | None = None


class VirtualHumanConversationMessageResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    accepted: bool
    queued: bool
    sessionId: str
    turnId: str = ""
    status: str
    acceptedAt: str = ""
    clientSubmissionId: str
    queueSequence: int = Field(ge=1)


class LegacyPetImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    previewOnly: bool = True
    expectedSourceDigest: str = ""
    idempotencyKey: str = ""


class LegacyPetImportResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    agentId: str
    sourceDigest: str
