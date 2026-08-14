"""Loopback-only managed external-Agent backend API."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from core.external_agent.contracts import API_PROTOCOL_VERSION, SERVER_VERSION
from core.web.control import validate_control_request
from core.web.services.external_agent.service import (
    ExternalAgentAccessError,
    ExternalAgentConflictError,
    ExternalAgentTaskService,
    get_default_service,
)
from core.web.services.external_agent.store import ExternalAgentTaskStoreError
from core.infrastructure import developer_sandbox
from vibelution_storage import resolve_project_runtime_home

router = APIRouter(tags=["external-agent"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TASK_CAPABILITY_HEADER = "X-Vibelution-External-Agent-Task-Capability"
ADAPTER_CONNECTION_HEADER = "X-Vibelution-External-Agent-Connection"


class StartExternalAgentTaskPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    agent_id: str = Field(..., min_length=1, max_length=200)
    task: str = Field(..., min_length=1, max_length=64_000)
    permission_profile: str = Field(default="read_only", max_length=40)
    client_request_id: str = Field(default="", max_length=200)
    title: str = Field(default="", max_length=160)


class ResolveExternalAgentApprovalPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    decision: str = Field(..., min_length=1, max_length=40)
    expected_revision: str = Field(default="", max_length=200)
    reason: str = Field(default="", max_length=500)


class CancelExternalAgentTaskPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reason: str = Field(default="", max_length=200)


class ExternalAgentHeartbeatPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    lease_id: str = Field(..., min_length=1, max_length=200)


_SERVICE: ExternalAgentTaskService | Any | None = None


def _service() -> ExternalAgentTaskService | Any:
    return _SERVICE if _SERVICE is not None else get_default_service(PROJECT_ROOT)


def _require_control(request: Request) -> None:
    error = validate_control_request(request)
    if error is not None:
        raise HTTPException(status_code=error.status_code, detail=error.detail)


def _require_header(value: str, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise HTTPException(status_code=403, detail=f"Missing {label}")
    return normalized


def _operator_capabilities() -> set[str]:
    return (
        set(_service().operator_capabilities())
        if hasattr(_service(), "operator_capabilities")
        else set()
    )


def _runtime_revision() -> str:
    for path in (
        resolve_project_runtime_home(PROJECT_ROOT) / "launcher" / "state.json",
        developer_sandbox.formal_workspace_path(PROJECT_ROOT, "ui_runtime_state.json"),
    ):
        if not path.is_file():
            continue
        try:
            import json

            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        revision = str(
            payload.get("runtimeSourceCommit")
            or payload.get("sourceCommit")
            or payload.get("runningCodeCommit")
            or ""
        ).strip()
        if revision:
            return revision
    return ""


def _handle_service_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ExternalAgentAccessError):
        return HTTPException(
            status_code=404,
            detail={"code": exc.code, "message": str(exc)},
        )
    if isinstance(exc, ExternalAgentConflictError):
        return HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": str(exc)},
        )
    if isinstance(exc, (ValueError, ExternalAgentTaskStoreError)):
        return HTTPException(
            status_code=422, detail={"code": "INVALID_REQUEST", "message": str(exc)}
        )
    return HTTPException(
        status_code=500,
        detail={"code": "INTERNAL_ERROR", "message": "External Agent gateway failed."},
    )


@router.get("/v1/external-agent/info")
def external_agent_gateway_info(
    request: Request,
    adapter_connection_id: Annotated[str, Header(alias=ADAPTER_CONNECTION_HEADER)] = "",
) -> dict[str, Any]:
    _require_control(request)
    service = _service()
    if adapter_connection_id and hasattr(service, "record_adapter_event"):
        service.record_adapter_event(
            "external_agent.adapter.connected",
            adapter_connection_id=adapter_connection_id,
        )
    return {
        "apiProtocolVersion": API_PROTOCOL_VERSION,
        "serverVersion": SERVER_VERSION,
        "projectRoot": str(PROJECT_ROOT.resolve()),
        "runtimeSourceRevision": _runtime_revision(),
        "enabled": bool(getattr(service, "enabled", False)),
    }


@router.post("/v1/external-agent/connections/shutdown")
def external_agent_connection_shutdown(
    request: Request,
    adapter_connection_id: Annotated[str, Header(alias=ADAPTER_CONNECTION_HEADER)] = "",
) -> dict[str, Any]:
    _require_control(request)
    connection_id = _require_header(
        adapter_connection_id, "external Agent adapter connection"
    )
    service = _service()
    if hasattr(service, "record_adapter_event"):
        service.record_adapter_event(
            "external_agent.adapter.shutdown",
            adapter_connection_id=connection_id,
        )
    return {"status": "ok"}


@router.get("/v1/external-agent/agents")
def list_external_agents(request: Request, limit: int = 50) -> dict[str, Any]:
    _require_control(request)
    try:
        return _service().list_agents(limit=limit)
    except Exception as exc:
        raise _handle_service_error(exc) from exc


@router.post("/v1/external-agent/tasks", status_code=status.HTTP_201_CREATED)
def start_external_agent_task(
    request: Request,
    payload: StartExternalAgentTaskPayload,
    task_capability: Annotated[str, Header(alias=TASK_CAPABILITY_HEADER)] = "",
    adapter_connection_id: Annotated[str, Header(alias=ADAPTER_CONNECTION_HEADER)] = "",
) -> dict[str, Any]:
    _require_control(request)
    owner_id = _require_header(task_capability, "external Agent task capability")
    connection_id = _require_header(
        adapter_connection_id, "external Agent adapter connection"
    )
    try:
        return _service().start_task(
            owner_id=owner_id,
            adapter_connection_id=connection_id,
            capabilities=_operator_capabilities(),
            agent_id=payload.agent_id,
            task=payload.task,
            permission_profile=payload.permission_profile,
            client_request_id=payload.client_request_id,
            title=payload.title,
            runtime_revision=_runtime_revision(),
            include_private=True,
        )
    except Exception as exc:
        raise _handle_service_error(exc) from exc


@router.get("/v1/external-agent/tasks/{task_id}")
def get_external_agent_task(
    task_id: str,
    request: Request,
    task_capability: Annotated[str, Header(alias=TASK_CAPABILITY_HEADER)] = "",
) -> dict[str, Any]:
    _require_control(request)
    owner_id = _require_header(task_capability, "external Agent task capability")
    try:
        return _service().get_task(owner_id=owner_id, task_id=task_id)
    except Exception as exc:
        raise _handle_service_error(exc) from exc


@router.post("/v1/external-agent/tasks/{task_id}/approvals/{approval_id}/resolve")
def resolve_external_agent_approval(
    task_id: str,
    approval_id: str,
    request: Request,
    payload: ResolveExternalAgentApprovalPayload,
    task_capability: Annotated[str, Header(alias=TASK_CAPABILITY_HEADER)] = "",
) -> dict[str, Any]:
    _require_control(request)
    owner_id = _require_header(task_capability, "external Agent task capability")
    try:
        return _service().resolve_approval(
            owner_id=owner_id,
            capabilities=_operator_capabilities(),
            task_id=task_id,
            approval_id=approval_id,
            decision=payload.decision,
            expected_revision=payload.expected_revision,
            reason=payload.reason,
        )
    except Exception as exc:
        raise _handle_service_error(exc) from exc


@router.post("/v1/external-agent/tasks/{task_id}/cancel")
def cancel_external_agent_task(
    task_id: str,
    request: Request,
    payload: CancelExternalAgentTaskPayload,
    task_capability: Annotated[str, Header(alias=TASK_CAPABILITY_HEADER)] = "",
) -> dict[str, Any]:
    del (
        payload
    )  # Reason is accepted for forward-compatible audit without persisting free text.
    _require_control(request)
    owner_id = _require_header(task_capability, "external Agent task capability")
    try:
        return _service().cancel_task(owner_id=owner_id, task_id=task_id)
    except Exception as exc:
        raise _handle_service_error(exc) from exc


@router.post("/v1/external-agent/tasks/{task_id}/heartbeat")
def heartbeat_external_agent_task(
    task_id: str,
    request: Request,
    payload: ExternalAgentHeartbeatPayload,
    task_capability: Annotated[str, Header(alias=TASK_CAPABILITY_HEADER)] = "",
    adapter_connection_id: Annotated[str, Header(alias=ADAPTER_CONNECTION_HEADER)] = "",
) -> dict[str, Any]:
    _require_control(request)
    owner_id = _require_header(task_capability, "external Agent task capability")
    connection_id = _require_header(
        adapter_connection_id, "external Agent adapter connection"
    )
    try:
        return _service().heartbeat(
            owner_id=owner_id,
            task_id=task_id,
            lease_id=payload.lease_id,
            adapter_connection_id=connection_id,
        )
    except Exception as exc:
        raise _handle_service_error(exc) from exc


__all__ = [
    "ADAPTER_CONNECTION_HEADER",
    "TASK_CAPABILITY_HEADER",
    "router",
]
