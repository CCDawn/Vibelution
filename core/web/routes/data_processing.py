"""Generic data processing API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from core.web.services.data_processing_service import (
    DataProcessingError,
    DataProcessingNotFoundError,
    add_record,
    create_collection_assignment,
    create_processing_run,
    get_processing_run,
    get_processing_status,
    get_profile,
    list_collection_assignments,
    list_profiles,
    list_processing_runs,
    list_records,
    record_collection_output,
)


router = APIRouter(tags=["data-processing"])


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


@router.get("/data-processing/profiles")
def data_processing_profiles() -> dict:
    return list_profiles()


@router.get("/data-processing/profiles/{profile_id}")
def data_processing_profile_detail(profile_id: str) -> dict:
    try:
        return get_profile(profile_id)
    except DataProcessingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DataProcessingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/data-processing/runs", status_code=status.HTTP_201_CREATED)
def data_processing_run_create(payload: DataProcessingRunCreatePayload) -> dict:
    try:
        return create_processing_run(
            profile_id=payload.profileId,
            title=payload.title,
            scope=payload.scope,
            metadata=payload.metadata,
        )
    except DataProcessingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DataProcessingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/data-processing/runs")
def data_processing_run_list(
    limit: int = Query(50, ge=1, le=200),
    profile_id: str = Query("", alias="profileId", max_length=120),
    team_id: str = Query("", alias="teamId", max_length=160),
    started_from: str = Query("", alias="startedFrom", max_length=160),
) -> dict:
    metadata_filters: dict[str, Any] = {}
    scope_filters: dict[str, Any] = {}
    if team_id:
        metadata_filters["teamId"] = team_id
        scope_filters["teamId"] = team_id
    if started_from:
        metadata_filters["startedFrom"] = started_from
    return list_processing_runs(
        limit=limit,
        profile_id=profile_id,
        metadata_filters=metadata_filters,
        scope_filters=scope_filters,
    )


@router.get("/data-processing/runs/{run_id}")
def data_processing_run_detail(run_id: str) -> dict:
    try:
        return get_processing_run(run_id)
    except DataProcessingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DataProcessingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/data-processing/runs/{run_id}/records")
def data_processing_records(run_id: str) -> dict:
    try:
        return list_records(run_id)
    except DataProcessingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DataProcessingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/data-processing/runs/{run_id}/records", status_code=status.HTTP_201_CREATED)
def data_processing_record_create(run_id: str, payload: DataRecordCreatePayload) -> dict:
    try:
        return add_record(run_id, payload.model_dump())
    except DataProcessingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DataProcessingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/data-processing/runs/{run_id}/collection-assignments")
def data_processing_collection_assignments(run_id: str) -> dict:
    try:
        return list_collection_assignments(run_id)
    except DataProcessingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DataProcessingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/data-processing/runs/{run_id}/collection-assignments", status_code=status.HTTP_201_CREATED)
def data_processing_collection_assignment_create(run_id: str, payload: CollectionAssignmentCreatePayload) -> dict:
    try:
        return create_collection_assignment(run_id, payload.model_dump())
    except DataProcessingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DataProcessingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/data-processing/runs/{run_id}/collection-assignments/{assignment_id}/outputs", status_code=status.HTTP_201_CREATED)
def data_processing_collection_output_create(run_id: str, assignment_id: str, payload: CollectionOutputCreatePayload) -> dict:
    try:
        return record_collection_output(run_id, assignment_id, payload.model_dump())
    except DataProcessingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DataProcessingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/data-processing/runs/{run_id}/status")
def data_processing_run_status(run_id: str) -> dict:
    try:
        return get_processing_status(run_id)
    except DataProcessingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DataProcessingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
