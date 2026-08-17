"""Bulk chat session delete orchestration for the workbench conversation index."""

from __future__ import annotations

from time import perf_counter
from typing import Any

from core.web.services.runtime_scene_service import record_runtime_scene_event

from .agent_sessions import delete_chat_session_lightweight


MAX_BULK_SESSION_IDS = 100


def _dedupe_session_ids(session_ids: list[str] | None) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in list(session_ids or []):
        session_id = str(item or "").strip()
        if not session_id or session_id in seen:
            continue
        seen.add(session_id)
        deduped.append(session_id)
    return deduped


def _skip_item(session_id: str, reason: str, message: str) -> dict[str, str]:
    return {"sessionId": session_id, "reason": reason, "message": message}


def _failed_item(session_id: str, reason: str, message: str) -> dict[str, str]:
    return {"sessionId": session_id, "reason": reason, "message": message}


def _busy_skip_reason(error: Exception) -> str:
    return "busy"


def _not_found_skip_reason(error: Exception) -> str:
    return "not_found"


def _status(success_count: int, skipped_count: int, failed_count: int) -> str:
    if failed_count:
        return "partial_failed" if success_count or skipped_count else "failed"
    return "completed"


def _summary(
    requested_count: int,
    success: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    failed: list[dict[str, Any]],
) -> dict[str, int]:
    return {
        "requestedCount": requested_count,
        "successCount": len(success),
        "skippedCount": len(skipped),
        "failedCount": len(failed),
    }


def bulk_delete_chat_sessions(session_ids: list[str] | None) -> dict[str, Any]:
    """Remove multiple chat sessions. Earlier successes stay committed if a later session fails."""

    from . import agent_sessions as session_module

    s = session_module._service()
    requested_session_ids = _dedupe_session_ids(session_ids)
    if len(requested_session_ids) > MAX_BULK_SESSION_IDS:
        raise s.SessionValidationError(
            s.text_for(
                s.get_web_language(),
                zh=f"批量移除会话一次最多 {MAX_BULK_SESSION_IDS} 条。",
                en=f"Bulk session remove accepts at most {MAX_BULK_SESSION_IDS} session ids.",
            )
        )

    started_at = perf_counter()
    success: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    last_next_active_session_id = ""

    for session_id in requested_session_ids:
        try:
            result = delete_chat_session_lightweight(session_id)
        except s.SessionBusyError as exc:
            skipped.append(_skip_item(session_id, _busy_skip_reason(exc), str(exc)))
            continue
        except s.SessionNotFoundError as exc:
            skipped.append(_skip_item(session_id, _not_found_skip_reason(exc), str(exc)))
            continue
        except s.SessionValidationError as exc:
            failed.append(_failed_item(session_id, "invalid", str(exc)))
            continue
        except Exception as exc:
            failed.append(_failed_item(session_id, "error", str(exc)))
            continue

        next_active_session_id = str(result.get("nextActiveSessionId") or "").strip()
        if next_active_session_id:
            last_next_active_session_id = next_active_session_id
        success.append(
            {
                "sessionId": session_id,
                "deleted": bool(result.get("deleted")),
                "nextActiveSessionId": next_active_session_id,
                "replacementDirectSessionId": str(result.get("replacementDirectSessionId") or "").strip(),
            }
        )

    summary = _summary(len(requested_session_ids), success, skipped, failed)
    duration_ms = round((perf_counter() - started_at) * 1000, 3)
    record_runtime_scene_event(
        "conversation_service",
        "delete",
        "session.bulk_delete.completed",
        outcome="failed" if summary["failedCount"] else "succeeded",
        fields={
            **summary,
            "durationMs": duration_ms,
            "lastNextActiveSessionId": last_next_active_session_id,
        },
    )
    return {
        "status": _status(summary["successCount"], summary["skippedCount"], summary["failedCount"]),
        "requestedSessionIds": requested_session_ids,
        "success": success,
        "skipped": skipped,
        "failed": failed,
        "summary": summary,
        "nextActiveSessionId": last_next_active_session_id,
        "durationMs": duration_ms,
    }
