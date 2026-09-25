"""Startup recovery sweep for chat-room rounds orphaned by a backend restart.

Split from ``chat_room_service`` so the lifecycle hook stays declarative: the
``session_recovery`` feature gate lives here, the round mechanics (close-out,
authority checks, roster narrowing, re-send) live in the room service.
"""

from __future__ import annotations

from typing import Any


def recover_chat_room_rounds_on_startup() -> dict[str, Any]:
    """Re-drive chat-room rounds a restart orphaned; gated by ``session_recovery``.

    Flag off means a deliberate no-op: the lazy read-path reconcile keeps its
    current close-orphan behavior on the first room read, so a disabled switch
    changes nothing for existing rooms.
    """

    from core.session_recovery_flags import (
        is_session_recovery_enabled,
        session_recovery_max_auto_retries,
    )

    if not is_session_recovery_enabled():
        return {"enabled": False, "orphanCount": 0, "outcomes": []}
    from .chat_room_service import recover_orphaned_chat_room_rounds_on_startup

    return recover_orphaned_chat_room_rounds_on_startup(
        max_auto_retries=session_recovery_max_auto_retries()
    )
