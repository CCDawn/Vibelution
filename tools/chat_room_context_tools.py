"""Room-scoped exact context lookup for an active chat-room speaker."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.chatroom.context_checkpoint import (
    ChatRoomContextRefError,
    resolve_chat_room_context_refs,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _current_runtime() -> dict[str, Any]:
    try:
        from core.web.services.agent_directory_service import current_agent_runtime

        runtime = current_agent_runtime()
    except ImportError:
        runtime = {}
    return dict(runtime) if isinstance(runtime, dict) else {}


def _load_room(room_id: str) -> dict[str, Any] | None:
    from core.chatroom.store import ChatRoomStore
    from core.infrastructure import developer_sandbox

    workspace_root = developer_sandbox.formal_workspace_path(PROJECT_ROOT)
    state = ChatRoomStore(root=workspace_root.parent).load()
    for room in list(state.get("rooms") or []):
        if not isinstance(room, dict):
            continue
        if str(room.get("roomId") or room.get("id") or "").strip() == room_id:
            return room
    return None


def read_chat_room_context_refs(refs: list[str]) -> str:
    """Read up to five exact messages referenced by the current room context.

    ``refs`` must use the server-issued ``roomId/roundId/messageId`` form. The
    active Agent runtime supplies the room identity; callers cannot select a
    different room. Results are capped at 32 KiB and are never truncated.
    """

    runtime = _current_runtime()
    room_id = str(runtime.get("roomId") or "").strip()
    if not room_id:
        return json.dumps(
            {
                "ok": False,
                "error": "chat_room_runtime_required",
                "message": "当前 Agent 不在群聊发言运行时中。",
            },
            ensure_ascii=False,
        )
    room = _load_room(room_id)
    if room is None:
        return json.dumps(
            {
                "ok": False,
                "error": "chat_room_not_found",
                "message": "当前群聊不存在或已删除。",
            },
            ensure_ascii=False,
        )
    try:
        messages = resolve_chat_room_context_refs(room, list(refs or []))
    except ChatRoomContextRefError as exc:
        return json.dumps(
            {
                "ok": False,
                "error": "chat_room_context_ref_invalid",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {"ok": True, "roomId": room_id, "messages": messages},
        ensure_ascii=False,
        sort_keys=True,
    )


__all__ = ["read_chat_room_context_refs"]
