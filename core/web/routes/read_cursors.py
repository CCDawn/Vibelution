"""Read-cursor routes for the team and conversation unread projection.

Only read/write of the per-scope cursor lives here. Unread counts stay a
client-side projection over the existing session/room timestamps, so these
routes never become a second message authority.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core.web.services.read_cursors import list_read_cursors, mark_read

router = APIRouter(prefix="/read-cursors", tags=["read-cursors"])

_SCHEMA_VERSION = 1


class ReadCursorEntryPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    scope_kind: Literal["team", "conversation"] = Field(alias="scopeKind")
    scope_id: str = Field(alias="scopeId", min_length=1, max_length=200)
    read_at: str | None = Field(default=None, alias="readAt", max_length=64)


class MarkReadPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    entries: list[ReadCursorEntryPayload] = Field(default_factory=list, max_length=500)


def _payload(cursors: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "schemaVersion": _SCHEMA_VERSION,
        "cursors": cursors,
        "updatedAt": datetime.now(UTC).isoformat(),
    }


@router.get("")
async def read_cursors_snapshot() -> dict[str, Any]:
    return _payload(list_read_cursors())


@router.post("")
async def read_cursors_mark(payload: MarkReadPayload) -> dict[str, Any]:
    entries = [entry.model_dump(by_alias=True) for entry in payload.entries]
    try:
        cursors = mark_read(entries)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return _payload(cursors)
