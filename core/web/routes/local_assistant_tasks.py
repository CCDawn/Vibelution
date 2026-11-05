"""Private Launcher transport; existing external routes retain their policy."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from hashlib import sha256
from pydantic import BaseModel, Field

from core.infrastructure.launcher_assistant_authority import verify_launcher_authority
from core.web.routes import external_agent
from core.web.services.local_assistant.service import build_local_service, route_service

LOCAL_ASSISTANT_LEASE_SECONDS = 300


def local_service():
    service = build_local_service(external_agent.PROJECT_ROOT)
    # The resident host can spend a full model turn between renewal cycles;
    # its transport must not inherit a short-lived third-party MCP lease.
    service.lease_seconds = LOCAL_ASSISTANT_LEASE_SECONDS
    return service


async def _local_principal(request: Request):
    external_agent._require_control(request)
    capability = request.headers.get("X-Vibelution-Management-Capability", "")
    if (request.headers.get("X-Vibelution-Management-Subject") != "launcher-local"
            or not verify_launcher_authority(capability)):
        raise HTTPException(status_code=403, detail={"code": "LAUNCHER_AUTHORITY_REQUIRED"})
    service = local_service()
    service.request_authority_fingerprint = sha256(capability.encode()).hexdigest()
    token = route_service.set(service)
    try:
        yield
    finally:
        route_service.reset(token)


router = APIRouter()
router.include_router(external_agent.router, prefix="/local-assistant", dependencies=[Depends(_local_principal)])


class CleanupResource(BaseModel):
    kind: str
    count: int
    bytes: int


class CleanupRetained(BaseModel):
    kind: str
    reason: str
    bytes: int | None = None


class CleanupPreviewResponse(BaseModel):
    schemaVersion: Literal[1]
    taskId: str
    revision: int
    status: Literal["ready", "blocked"]
    alreadyDeleted: bool = False
    fingerprint: str
    estimatedBytes: int
    resources: list[CleanupResource]
    retained: list[CleanupRetained]


class CleanupTaskPayload(BaseModel):
    revision: int = Field(strict=True, ge=1)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class CleanupTaskResponse(BaseModel):
    schemaVersion: Literal[1]
    taskId: str
    status: Literal["deleted", "partial", "blocked"]
    alreadyDeleted: bool = False
    releasedBytes: int
    storageDeltaBytes: int | None = None
    retained: list[CleanupRetained]
    failures: list[CleanupRetained]


@router.post("/local-assistant/v1/external-agent/tasks/{task_id}/cleanup/preview",
             dependencies=[Depends(_local_principal)], response_model=CleanupPreviewResponse,
             response_model_exclude_none=True)
def preview_local_task_cleanup(task_id: str, response: Response,
    task_capability: Annotated[str, Header(alias=external_agent.TASK_CAPABILITY_HEADER)] = ""):
    from core.web.services.local_assistant.task_cleanup import preview_task_cleanup
    owner_id = external_agent._require_header(task_capability, "external Agent task capability")
    response.headers["Cache-Control"] = "no-store"
    try:
        return preview_task_cleanup(route_service.get(), owner_id=owner_id, task_id=task_id)
    except Exception as exc:
        raise external_agent._handle_service_error(exc) from exc


@router.post("/local-assistant/v1/external-agent/tasks/{task_id}/cleanup",
             dependencies=[Depends(_local_principal)], response_model=CleanupTaskResponse,
             response_model_exclude_none=True)
def cleanup_local_task(task_id: str, payload: CleanupTaskPayload, response: Response,
    task_capability: Annotated[str, Header(alias=external_agent.TASK_CAPABILITY_HEADER)] = ""):
    from core.web.services.local_assistant.task_cleanup import cleanup_task
    owner_id = external_agent._require_header(task_capability, "external Agent task capability")
    response.headers["Cache-Control"] = "no-store"
    try:
        return cleanup_task(route_service.get(), owner_id=owner_id, task_id=task_id,
                            revision=payload.revision, fingerprint=payload.fingerprint)
    except Exception as exc:
        raise external_agent._handle_service_error(exc) from exc


@router.post("/local-assistant/v1/external-agent/legacy-tasks/{task_id}/cleanup/preview",
             dependencies=[Depends(_local_principal)], response_model=CleanupPreviewResponse,
             response_model_exclude_none=True)
def preview_legacy_task_cleanup(task_id: str, response: Response,
    task_capability: Annotated[str, Header(alias=external_agent.TASK_CAPABILITY_HEADER)] = ""):
    from core.web.services.local_assistant.legacy_cleanup import build_legacy_cleanup_service
    from core.web.services.local_assistant.task_cleanup import preview_task_cleanup
    owner_id = external_agent._require_header(task_capability, "external Agent task capability")
    response.headers["Cache-Control"] = "no-store"
    try:
        return preview_task_cleanup(build_legacy_cleanup_service(route_service.get()), owner_id=owner_id, task_id=task_id)
    except Exception as exc:
        raise external_agent._handle_service_error(exc) from exc


@router.post("/local-assistant/v1/external-agent/legacy-tasks/{task_id}/cleanup",
             dependencies=[Depends(_local_principal)], response_model=CleanupTaskResponse,
             response_model_exclude_none=True)
def cleanup_legacy_task(task_id: str, payload: CleanupTaskPayload, response: Response,
    task_capability: Annotated[str, Header(alias=external_agent.TASK_CAPABILITY_HEADER)] = ""):
    from core.web.services.local_assistant.legacy_cleanup import build_legacy_cleanup_service
    from core.web.services.local_assistant.task_cleanup import cleanup_task
    owner_id = external_agent._require_header(task_capability, "external Agent task capability")
    response.headers["Cache-Control"] = "no-store"
    try:
        return cleanup_task(build_legacy_cleanup_service(route_service.get()), owner_id=owner_id, task_id=task_id,
                            revision=payload.revision, fingerprint=payload.fingerprint)
    except Exception as exc:
        raise external_agent._handle_service_error(exc) from exc
