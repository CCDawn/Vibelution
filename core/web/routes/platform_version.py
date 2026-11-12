"""Platform-version ledger routes: read-only snapshot plus live stream.

The UI never writes a version. Settlement is owned by the watcher, and even the
watcher only appends to the out-of-tree ledger, so these routes stay projection
reads over a single authority.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from core.platform_version.settler import get_watcher

router = APIRouter(prefix="/api/platform-version", tags=["platform-version"])
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get("")
async def platform_version_snapshot() -> dict[str, Any]:
    watcher = await get_watcher(PROJECT_ROOT)
    watcher.ensure_started()
    return watcher.current_snapshot()


@router.get("/stream")
async def platform_version_stream() -> StreamingResponse:
    watcher = await get_watcher(PROJECT_ROOT)

    async def events() -> AsyncIterator[str]:
        async for event in watcher.subscribe():
            yield _sse(event)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
