"""Typed Agent-scoped virtual-human-life routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from core.agent_plugins.virtual_human_life.service import (
    AgentUnavailableError,
    BindingConflictError,
    BindingDisabledError,
    VirtualHumanLifeError,
)
from core.web.routes.virtual_human_life_models import (
    LegacyPetImportRequest,
    LegacyPetImportResponse,
    VirtualHumanCommandRequest,
    VirtualHumanCommandResponse,
    VirtualHumanDiaryEntryResponse,
    VirtualHumanEventResponse,
    VirtualHumanRelationshipResponse,
    VirtualHumanScheduleResponse,
    VirtualHumanSnapshotResponse,
)
from core.web.services.virtual_human_life_service import (
    execute_virtual_human_command,
    import_legacy_pet,
    preview_legacy_pet_import,
    virtual_human_diary,
    virtual_human_events,
    virtual_human_relationships,
    virtual_human_schedule,
    virtual_human_snapshot,
)

router = APIRouter(tags=["virtual-human-life"])


def _raise_life_http_error(exc: Exception) -> None:
    if isinstance(exc, AgentUnavailableError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, BindingConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, (BindingDisabledError, VirtualHumanLifeError, ValueError)):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


@router.get(
    "/agents/{agent_id}/plugins/virtual-human-life/snapshot",
    response_model=VirtualHumanSnapshotResponse,
    response_model_exclude_unset=True,
)
def life_snapshot(agent_id: str) -> dict:
    try:
        return virtual_human_snapshot(agent_id)
    except Exception as exc:
        _raise_life_http_error(exc)
        raise


@router.get(
    "/agents/{agent_id}/plugins/virtual-human-life/schedule",
    response_model=VirtualHumanScheduleResponse,
    response_model_exclude_unset=True,
)
def life_schedule(agent_id: str, localDate: str = "") -> dict:
    try:
        result = virtual_human_schedule(agent_id, localDate)
        if localDate:
            return {"agentId": agent_id, "today": result, "tomorrow": None}
        return result
    except Exception as exc:
        _raise_life_http_error(exc)
        raise


@router.get(
    "/agents/{agent_id}/plugins/virtual-human-life/events",
    response_model=list[VirtualHumanEventResponse],
    response_model_exclude_unset=True,
)
def life_events(
    agent_id: str,
    localDate: Annotated[str, Query(max_length=10)] = "",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict]:
    try:
        return virtual_human_events(agent_id, local_date=localDate, limit=limit)
    except Exception as exc:
        _raise_life_http_error(exc)
        raise


@router.get(
    "/agents/{agent_id}/plugins/virtual-human-life/diary",
    response_model=list[VirtualHumanDiaryEntryResponse],
    response_model_exclude_unset=True,
)
def life_diary(
    agent_id: str,
    localDate: Annotated[str, Query(max_length=10)] = "",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict]:
    try:
        return virtual_human_diary(agent_id, local_date=localDate, limit=limit)
    except Exception as exc:
        _raise_life_http_error(exc)
        raise


@router.get(
    "/agents/{agent_id}/plugins/virtual-human-life/relationships",
    response_model=list[VirtualHumanRelationshipResponse],
    response_model_exclude_unset=True,
)
def life_relationships(agent_id: str) -> list[dict]:
    try:
        return virtual_human_relationships(agent_id)
    except Exception as exc:
        _raise_life_http_error(exc)
        raise


@router.post(
    "/agents/{agent_id}/plugins/virtual-human-life/commands",
    response_model=VirtualHumanCommandResponse,
    response_model_exclude_unset=True,
)
def life_command(agent_id: str, payload: VirtualHumanCommandRequest) -> dict:
    if str(payload.agentId or "").strip() != str(agent_id or "").strip():
        raise HTTPException(status_code=422, detail="Payload agentId must match the route Agent.")
    try:
        return execute_virtual_human_command(
            agent_id,
            command=payload.command,
            expected_version=payload.expectedVersion,
            idempotency_key=payload.idempotencyKey,
            arguments=payload.arguments,
        )
    except Exception as exc:
        _raise_life_http_error(exc)
        raise


@router.post(
    "/agents/{agent_id}/plugins/virtual-human-life/import-legacy-pet",
    response_model=LegacyPetImportResponse,
    response_model_exclude_unset=True,
)
def life_import_legacy_pet(agent_id: str, payload: LegacyPetImportRequest) -> dict:
    try:
        if payload.previewOnly:
            return preview_legacy_pet_import(agent_id)
        if not payload.expectedSourceDigest or not payload.idempotencyKey:
            raise VirtualHumanLifeError(
                "Import requires expectedSourceDigest and idempotencyKey after preview."
            )
        return import_legacy_pet(
            agent_id,
            expected_source_digest=payload.expectedSourceDigest,
            idempotency_key=payload.idempotencyKey,
        )
    except Exception as exc:
        _raise_life_http_error(exc)
        raise
