"""Thin Team workflow routes: G12 calibration judgement records.

Recording a manifest or a judgement IS the credential that satisfies the
G12 calibration gate read (``g12_calibration_store``); both write paths and
the status read are server-principal privileged operations. Handlers stay
thin; fail-closed validation, binding and storage live in the store service.
"""
from __future__ import annotations

from fastapi import HTTPException, Request

from core.web.services.team_workflow.research_runtime.g12_calibration_store import (
    G12CalibrationStoreError,
    g12_calibration_gate_status,
    record_g12_calibration_manifest,
    record_g12_judgements,
)
from core.web.services.team_workflow.research_runtime.operator_authorization import (
    require_privileged_server_operator,
    server_operator_scope_from_http,
)

from ._errors import _raise_team_workflow_route_error
from ._router import router
from .g12_calibration_models import (
    G12GateStatusResponse,
    G12JudgementsRecordRequest,
    G12JudgementsRecordResponse,
    G12ManifestRecordRequest,
    G12ManifestRecordResponse,
)

_G12_STORE_ERROR_STATUS = {
    "recorded_by_missing": 403,
    "manifest_not_found": 404,
    "manifest_id_missing": 422,
    "manifest_invalid": 422,
    "manifest_gate_invalid": 422,
    "manifest_hash_conflict": 409,
    "judgement_conflict": 409,
    "judgements_invalid": 422,
    "judgement_invalid": 422,
    "bundle_invalid": 422,
    "store_corrupt": 409,
    "policy_identity_invalid": 422,
    "payload_invalid": 422,
}


def _raise_g12_store_route_error(operation: str, team_id: str, exc: Exception) -> None:
    code = getattr(exc, "code", "")
    status_code = _G12_STORE_ERROR_STATUS.get(str(code), 422)
    _raise_team_workflow_route_error(
        operation, team_id, exc, status_code=status_code
    )


@router.post(
    "/teams/{team_id}/workflow-orchestration/challenge-program/g12-calibration/manifests",
    response_model=G12ManifestRecordResponse,
    response_model_exclude_unset=True,
)
def g12_calibration_record_manifest(
    team_id: str,
    request: Request,
    payload: G12ManifestRecordRequest,
) -> dict:
    """Record (or idempotently reuse) one G12 sample manifest."""

    try:
        with server_operator_scope_from_http(request):
            operator = require_privileged_server_operator(
                command="record_g12_calibration"
            )
            return record_g12_calibration_manifest(
                team_id,
                payload.model_dump(),
                recorded_by=operator.operator_id,
            )
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "command_forbidden", "message": str(exc)},
        ) from exc
    except G12CalibrationStoreError as exc:
        _raise_g12_store_route_error("g12_calibration.record_manifest", team_id, exc)


@router.post(
    "/teams/{team_id}/workflow-orchestration/challenge-program/g12-calibration/judgements",
    response_model=G12JudgementsRecordResponse,
    response_model_exclude_unset=True,
)
def g12_calibration_record_judgements(
    team_id: str,
    request: Request,
    payload: G12JudgementsRecordRequest,
) -> dict:
    """Record operator judgements bound fail-closed to a stored manifest."""

    try:
        with server_operator_scope_from_http(request):
            operator = require_privileged_server_operator(
                command="record_g12_calibration"
            )
            return record_g12_judgements(
                team_id,
                payload.model_dump(),
                recorded_by=operator.operator_id,
            )
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "command_forbidden", "message": str(exc)},
        ) from exc
    except G12CalibrationStoreError as exc:
        _raise_g12_store_route_error("g12_calibration.record_judgements", team_id, exc)


@router.get(
    "/teams/{team_id}/workflow-orchestration/challenge-program/g12-calibration/status",
    response_model=G12GateStatusResponse,
    response_model_exclude_unset=True,
)
def g12_calibration_status(team_id: str, request: Request) -> dict:
    """Read-only gate status: stored bundle projection + gate verdict."""

    try:
        with server_operator_scope_from_http(request):
            operator = require_privileged_server_operator(
                command="read_g12_calibration"
            )
            status = g12_calibration_gate_status(team_id)
            status["recordedBy"] = operator.operator_id
            return status
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "command_forbidden", "message": str(exc)},
        ) from exc
    except G12CalibrationStoreError as exc:
        _raise_g12_store_route_error("g12_calibration.status", team_id, exc)
