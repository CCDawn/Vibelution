"""Read Agent avatar assets without importing the optional management API."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from core.web.services.agent_directory_service import resolve_agent_avatar_file

router = APIRouter(tags=["agents"])


@router.get("/agents/avatar-image/{filename}", response_class=FileResponse)
def agent_avatar_image(filename: str) -> FileResponse:
    try:
        path = resolve_agent_avatar_file(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Agent avatar image not found") from exc
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Agent avatar image not found")
    return FileResponse(path)
