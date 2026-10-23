"""Read-only desktop-pet projection over native Session authorities."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from core.chat.session_activity import resolve_session_activity

from .session.timebase import parse_timestamp_utc
from .session.tool_approvals import list_tool_approval_requests
from .session_service import list_sessions, load_chat_turn_work_run_summary

_COMPLETION_PULSE_SECONDS = 15.0
_ERROR_ATTENTION_SECONDS = 300.0
_TONE_PRIORITY = {"approval": 0, "error": 1, "running": 2, "completed": 3, "idle": 4}


def get_pet_activity(*, now: datetime | None = None) -> dict[str, Any]:
    """Project safe desktop-pet activity without creating a second transcript."""

    observed_at = _as_utc(now or datetime.now(timezone.utc))
    sessions = list_sessions()
    work_run_summary = load_chat_turn_work_run_summary()
    active_items = work_run_summary.get("activeItems") if isinstance(work_run_summary, dict) else []
    live_by_session = {
        session_id: item
        for item in (active_items or [])
        if isinstance(item, dict)
        and (session_id := str(item.get("sessionId") or "").strip())
    }

    rows: list[dict[str, Any]] = []
    for session in sessions:
        if not isinstance(session, dict):
            continue
        session_id = str(session.get("id") or "").strip()
        if not session_id:
            continue
        live_item = live_by_session.get(session_id)
        needs_approval = bool(list_tool_approval_requests(session_id, status="pending"))
        tone = _resolve_tone(
            session,
            runtime_running=live_item is not None,
            needs_approval=needs_approval,
            now=observed_at,
        )
        if tone == "idle":
            continue
        phase = _resolve_phase(session, live_item=live_item, tone=tone)
        updated_at = str(session.get("updatedAt") or session.get("lastActive") or "").strip()
        rows.append(
            {
                "sessionId": session_id,
                "title": _safe_session_title(
                    session.get("title"),
                    session_id=session_id,
                    agent_name=session.get("agentDisplayName"),
                ),
                "agentId": str(session.get("agentId") or "").strip(),
                "agentDisplayName": _normalize_display_text(session.get("agentDisplayName"), limit=48),
                "tone": tone,
                "phase": phase,
                "updatedAt": updated_at,
                "_updatedSort": _parse_timestamp(updated_at).timestamp()
                if _parse_timestamp(updated_at) is not None
                else 0.0,
            }
        )

    def needs_attention(row: dict[str, Any]) -> bool:
        if row["tone"] == "approval":
            return True
        age = observed_at.timestamp() - float(row["_updatedSort"])
        return row["tone"] == "error" and 0 <= age <= _ERROR_ATTENTION_SECONDS

    rows.sort(key=lambda item: float(item["_updatedSort"]), reverse=True)
    rows.sort(key=lambda item: 4 if item["tone"] == "error" and not needs_attention(item)
              else _TONE_PRIORITY[str(item["tone"])])
    attention_count = sum(1 for row in rows if needs_attention(row))
    current_rows = [row for row in rows if row["tone"] != "error" or needs_attention(row)]
    for row in rows:
        row.pop("_updatedSort", None)

    aggregate_tone = str(current_rows[0]["tone"]) if current_rows else "idle"
    animation_state = _aggregate_animation_state(aggregate_tone, current_rows)
    return {
        "schemaVersion": 1,
        "aggregateTone": aggregate_tone,
        "animationState": animation_state,
        "activeCount": sum(1 for row in rows if row["tone"] in {"approval", "running"}),
        "attentionCount": attention_count,
        "generatedAt": observed_at.isoformat(),
        "sessions": rows,
    }


def _resolve_tone(
    session: dict[str, Any],
    *,
    runtime_running: bool,
    needs_approval: bool,
    now: datetime,
) -> str:
    if needs_approval:
        return "approval"
    # This summary reconciles stale chat-turn work runs before returning them,
    # so a remaining active item is the live authority when the persisted
    # Session projection still says ready from the previous turn.
    state = resolve_session_activity(session, runtime_running=runtime_running, authoritative_runtime=True)
    if state["execution"] in {"queued", "running", "stopping"}:
        return "running"
    if state["outcome"] == "failed":
        return "error"
    if state["outcome"] == "completed" and _is_recent(session, now=now):
        return "completed"
    return "idle"


def _resolve_phase(
    session: dict[str, Any],
    *,
    live_item: dict[str, Any] | None,
    tone: str,
) -> str:
    if tone == "approval":
        return "waiting"
    if tone == "error":
        return "error"
    if tone == "completed":
        return "completed"
    # A WorkRun may only carry execution status. Fill phase from another phase,
    # never from its status or the previous Turn's outcome.
    phase = resolve_session_activity(live_item or {})["phase"] or resolve_session_activity(session)["phase"]
    if phase == "editing":
        return "tooling"
    if phase in {"verifying", "tooling", "reading", "answering"}:
        return phase
    return "thinking"


def _aggregate_animation_state(aggregate_tone: str, rows: list[dict[str, Any]]) -> str:
    if aggregate_tone == "approval":
        return "waiting"
    if aggregate_tone == "error":
        return "alert"
    if aggregate_tone == "completed":
        return "celebrating"
    if aggregate_tone == "running":
        running = next((row for row in rows if row.get("tone") == "running"), None)
        return str((running or {}).get("phase") or "thinking")
    return "idle"


def _is_recent(session: dict[str, Any], *, now: datetime) -> bool:
    updated_at = _parse_timestamp(session.get("updatedAt") or session.get("lastActive"))
    if updated_at is None:
        return False
    age_seconds = (now - updated_at).total_seconds()
    return 0 <= age_seconds <= _COMPLETION_PULSE_SECONDS


def _parse_timestamp(value: Any) -> datetime | None:
    return parse_timestamp_utc(value)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _safe_session_title(raw: Any, *, session_id: str, agent_name: Any) -> str:
    text = _normalize_display_text(raw, limit=160)
    text = re.sub(r"[A-Za-z]:\\[^\s]+", " ", text)
    text = re.sub(r"\\\\[^\s]+", " ", text)
    text = re.sub(r"(?:^|[\s(])/(?:Users|home|tmp|var|etc|opt)[^\s]*", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", " ", text)
    text = _normalize_display_text(text, limit=48)
    if text:
        return text
    safe_agent_name = _normalize_display_text(agent_name, limit=32)
    if safe_agent_name:
        return f"{safe_agent_name} 的会话"
    short_id = session_id.removeprefix("session-")[:8]
    return f"会话 {short_id}" if short_id else "当前会话"


def safe_session_title(raw: Any, *, session_id: str, agent_name: Any) -> str:
    """Public wrapper so cross-service projections avoid the private symbol."""
    return _safe_session_title(raw, session_id=session_id, agent_name=agent_name)


def _normalize_display_text(value: Any, *, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) > limit:
        return f"{text[: limit - 1]}…"
    return text
