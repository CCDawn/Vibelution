"""Private Launcher transport; existing external routes retain their policy."""
from fastapi import APIRouter, Depends, HTTPException, Request
from hashlib import sha256

from core.infrastructure.launcher_assistant_authority import verify_launcher_authority
from core.web.routes import external_agent
from core.web.services.local_assistant.service import build_local_service, route_service


def local_service():
    return build_local_service(external_agent.PROJECT_ROOT)


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
