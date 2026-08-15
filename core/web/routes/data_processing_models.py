"""Public contracts for data-processing JSON routes.

Known envelope fields stay explicit for OpenAPI. Nested run, record, assignment,
and output payloads still evolve, so extras pass through. Routes must use
response_model_exclude_unset=True.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DataProcessingRunCreatePayload(BaseModel):
    profileId: str = Field("generic_document_processing", max_length=120)
    title: str = Field("", max_length=180)
    scope: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DataRecordCreatePayload(BaseModel):
    sourceType: str = Field("unknown", max_length=80)
    sourceRef: str = Field("", max_length=1000)
    rawLocation: str = Field("", max_length=1000)
    title: str = Field("", max_length=260)
    summary: str = Field("", max_length=4000)
    status: str = Field("collected", max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict)
    qualitySignals: dict[str, Any] = Field(default_factory=dict)
    collectionTrace: dict[str, Any] = Field(default_factory=dict)


class CollectionAssignmentCreatePayload(BaseModel):
    agentRole: str = Field("", max_length=120)
    agentId: str = Field("", max_length=160)
    status: str = Field("open", max_length=80)
    scope: dict[str, Any] = Field(default_factory=dict)
    inputRefs: list[str] = Field(default_factory=list, max_length=120)
    expectedRecordTypes: list[str] = Field(default_factory=list, max_length=40)
    acceptance: dict[str, Any] = Field(default_factory=dict)


class CollectionOutputCreatePayload(BaseModel):
    status: str = Field("completed", max_length=80)
    records: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    notes: str = Field("", max_length=4000)
    qualitySignals: dict[str, Any] = Field(default_factory=dict)
    blockingIssues: list[str] = Field(default_factory=list, max_length=80)


class DataProcessingProfilesResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    defaultProfileId: str = ""
    profiles: list[dict[str, Any]] = Field(default_factory=list)


class DataProcessingProfileResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    profileId: str = ""
    displayName: str = ""
    description: str = ""


class DataProcessingRunResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    runId: str = ""
    profileId: str = ""
    title: str = ""
    status: str = ""
    scope: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    createdAt: str = ""
    updatedAt: str = ""
    storage: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    processingStatus: dict[str, Any] = Field(default_factory=dict)


class DataProcessingRunListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    runs: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class DataProcessingRunStatusResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    runId: str = ""
    profileId: str = ""
    runStatus: str = ""
    summary: dict[str, Any] = Field(default_factory=dict)
    nextActions: list[dict[str, Any]] = Field(default_factory=list)
    boundaries: dict[str, Any] = Field(default_factory=dict)


class DataProcessingRecordListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    runId: str = ""
    records: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class DataProcessingRecordResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    recordId: str = ""
    runId: str = ""
    sourceType: str = ""
    sourceRef: str = ""
    title: str = ""
    status: str = ""
    collectionTrace: dict[str, Any] = Field(default_factory=dict)


class DataProcessingCollectionAssignmentListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    runId: str = ""
    assignments: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class DataProcessingCollectionAssignmentResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    assignmentId: str = ""
    runId: str = ""
    agentRole: str = ""
    agentId: str = ""
    status: str = ""
    scope: dict[str, Any] = Field(default_factory=dict)


class DataProcessingCollectionOutputResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    output: dict[str, Any] = Field(default_factory=dict)
    createdRecords: list[dict[str, Any]] = Field(default_factory=list)
