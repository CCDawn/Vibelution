"""Persist the session collaboration mode on the session runtime row.

The session row is the source of truth. The live agent runtime carries a copy
for the current turn so a plan switch is visible to the next tool call.
"""

from __future__ import annotations

from typing import Any

from core.authorization.collaboration_mode import (
    entered_plan_state,
    exited_plan_state,
    normalize_collaboration_state,
    plan_is_enabled,
)


def load_collaboration_state(session_id: str) -> dict[str, Any]:
    row = _load_row(session_id)
    if row is None:
        return normalize_collaboration_state(None)
    return normalize_collaboration_state(row.get("collaborationMode"))


def enter_session_plan_mode(session_id: str) -> dict[str, Any]:
    row = _require_row(session_id)
    previous = normalize_collaboration_state(row.get("collaborationMode"))
    state = entered_plan_state(previous)
    _save_state(session_id, row, state)
    return {
        "mode": state["mode"],
        "previousMode": previous["mode"],
        "planEnabled": True,
        "previousPlanEnabled": plan_is_enabled(previous),
    }


def exit_session_plan_mode(session_id: str) -> dict[str, Any]:
    row = _require_row(session_id)
    previous = normalize_collaboration_state(row.get("collaborationMode"))
    if not plan_is_enabled(previous):
        raise CollaborationModeError("当前不在计划模式，不能退出计划。")
    state = exited_plan_state(previous)
    _save_state(session_id, row, state)
    return {
        "mode": state["mode"],
        "previousMode": previous["mode"],
        "planEnabled": False,
        "previousPlanEnabled": True,
    }


class CollaborationModeError(ValueError):
    """Raised when the session cannot change collaboration mode."""


def _require_row(session_id: str) -> dict[str, Any]:
    row = _load_row(session_id)
    if row is None:
        raise CollaborationModeError("当前没有可切换模式的会话。")
    return row


def _load_row(session_id: str) -> dict[str, Any] | None:
    normalized = str(session_id or "").strip()
    if not normalized:
        return None
    from core.ui.chat_state import load_session_chat_state

    row = load_session_chat_state(_project_root(), normalized)
    return dict(row) if isinstance(row, dict) else None


def _save_state(session_id: str, row: dict[str, Any], state: dict[str, Any]) -> None:
    payload = dict(row)
    payload["collaborationMode"] = state
    from core.ui.chat_state import save_session_chat_state

    save_session_chat_state(_project_root(), session_id, payload)
    _publish_live_state(state)


def _publish_live_state(state: dict[str, Any]) -> None:
    from core.web.services.agent_directory_service import _CURRENT_AGENT_RUNTIME

    current = _CURRENT_AGENT_RUNTIME.get({})
    if isinstance(current, dict) and current:
        current["collaborationMode"] = dict(state)


def _project_root():
    from core.web.services.session_service import PROJECT_ROOT

    return PROJECT_ROOT
