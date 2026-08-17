"""Generic data processing API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from core.web.routes.data_processing_models import (
    CollectionAssignmentCreatePayload,
    CollectionOutputCreatePayload,
    DataProcessingCollectionAssignmentListResponse,
    DataProcessingCollectionAssignmentResponse,
    DataProcessingCollectionOutputResponse,
    DataProcessingProfileResponse,
    DataProcessingProfilesResponse,
    DataProcessingRecordListResponse,
    DataProcessingRecordResponse,
    DataProcessingRunCreatePayload,
    DataProcessingRunListResponse,
    DataProcessingRunResponse,
    DataProcessingRunStatusResponse,
    DataRecordCreatePayload,
)
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


@router.get(
    "/data-processing/profiles",
    response_model=DataProcessingProfilesResponse,
    response_model_exclude_unset=True,
)
def data_processing_profiles() -> dict:
    return list_profiles()


@router.get(
    "/data-processing/profiles/{profile_id}",
    response_model=DataProcessingProfileResponse,
    response_model_exclude_unset=True,
)
def data_processing_profile_detail(profile_id: str) -> dict:
    try:
        return get_profile(profile_id)
    except DataProcessingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DataProcessingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/data-processing/runs",
    status_code=status.HTTP_201_CREATED,
    response_model=DataProcessingRunResponse,
    response_model_exclude_unset=True,
)
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


@router.get(
    "/data-processing/runs",
    response_model=DataProcessingRunListResponse,
    response_model_exclude_unset=True,
)
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


@router.get(
    "/data-processing/runs/{run_id}",
    response_model=DataProcessingRunResponse,
    response_model_exclude_unset=True,
)
def data_processing_run_detail(run_id: str) -> dict:
    try:
        return get_processing_run(run_id)
    except DataProcessingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DataProcessingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/data-processing/runs/{run_id}/records",
    response_model=DataProcessingRecordListResponse,
    response_model_exclude_unset=True,
)
def data_processing_records(run_id: str) -> dict:
    try:
        return list_records(run_id)
    except DataProcessingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DataProcessingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/data-processing/runs/{run_id}/records",
    status_code=status.HTTP_201_CREATED,
    response_model=DataProcessingRecordResponse,
    response_model_exclude_unset=True,
)
def data_processing_record_create(run_id: str, payload: DataRecordCreatePayload) -> dict:
    try:
        return add_record(run_id, payload.model_dump())
    except DataProcessingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DataProcessingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/data-processing/runs/{run_id}/collection-assignments",
    response_model=DataProcessingCollectionAssignmentListResponse,
    response_model_exclude_unset=True,
)
def data_processing_collection_assignments(run_id: str) -> dict:
    try:
        return list_collection_assignments(run_id)
    except DataProcessingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DataProcessingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/data-processing/runs/{run_id}/collection-assignments",
    status_code=status.HTTP_201_CREATED,
    response_model=DataProcessingCollectionAssignmentResponse,
    response_model_exclude_unset=True,
)
def data_processing_collection_assignment_create(run_id: str, payload: CollectionAssignmentCreatePayload) -> dict:
    try:
        return create_collection_assignment(run_id, payload.model_dump())
    except DataProcessingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DataProcessingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/data-processing/runs/{run_id}/collection-assignments/{assignment_id}/outputs",
    status_code=status.HTTP_201_CREATED,
    response_model=DataProcessingCollectionOutputResponse,
    response_model_exclude_unset=True,
)
def data_processing_collection_output_create(run_id: str, assignment_id: str, payload: CollectionOutputCreatePayload) -> dict:
    try:
        return record_collection_output(run_id, assignment_id, payload.model_dump())
    except DataProcessingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DataProcessingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/data-processing/runs/{run_id}/status",
    response_model=DataProcessingRunStatusResponse,
    response_model_exclude_unset=True,
)
def data_processing_run_status(run_id: str) -> dict:
    try:
        return get_processing_status(run_id)
    except DataProcessingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DataProcessingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
