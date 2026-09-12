"""Question-scoped session inventory and removal for retire/reset cleanup.

The conversation directory store keeps one row per agent session.  Challenge
Cup question work creates sessions whose titles carry the question token
(``SCI-xxx``): per-question team-agent sessions plus hidden child sessions for
rooms, candidate previews and reviews.  Question reset/retire must remove those
rows and their runtime transcripts; this module owns the read/inventory side and
composes the existing bulk session delete so the store, chat state and workspace
cleanup semantics stay in one place.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.chat.conversation_store import ConversationStore

from . import directory_runtime

_MAX_QUESTION_SESSION_DETAIL = 50
_DIRECTORY_PAGE_LIMIT = 200
PROJECT_ROOT = Path(__file__).resolve().parents[4]


def _project_root() -> Path:
    return Path(PROJECT_ROOT)


def _question_token_pattern(question_id: str) -> re.Pattern[str]:
    token = re.escape(str(question_id or "").strip())
    return re.compile(rf"(?i)(?<![0-9a-z]){token}(?![0-9])")


def _iso_from_ms(value: Any) -> str:
    try:
        timestamp = int(value or 0)
    except (TypeError, ValueError):
        return ""
    if timestamp <= 0:
        return ""
    return (
        datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _directory_rows() -> list[dict[str, Any]]:
    """Page every non-archived directory session, hidden rows included."""

    store = directory_runtime.get_open_directory_store()
    if store is not None:
        open_root = directory_runtime.directory_store_project_root()
        if open_root is None or Path(open_root).resolve() != _project_root().resolve():
            store = None
    owned_store = False
    if store is None:
        store = ConversationStore(
            directory_runtime.conversation_store_path(_project_root())
        )
        store.open()
        owned_store = True
    try:
        rows: list[dict[str, Any]] = []
        before: tuple[int, str] | None = None
        while True:
            page = store.repository.list_directory_page(
                include_hidden=True,
                limit=_DIRECTORY_PAGE_LIMIT,
                before=before,
            )
            batch = [item for item in list(page.get("rows") or []) if isinstance(item, dict)]
            rows.extend(batch)
            cursor = str(page.get("nextCursor") or "").strip()
            if not batch or not cursor:
                break
            recency, _, session_id = cursor.partition(":")
            try:
                before = (int(recency), session_id)
            except ValueError:
                break
            if not session_id:
                break
        return rows
    finally:
        if owned_store:
            store.close()


def list_question_session_summaries(question_id: str) -> list[dict[str, Any]]:
    """Return every session whose title is bound to one question token."""

    pattern = _question_token_pattern(question_id)
    summaries: list[dict[str, Any]] = []
    for row in _directory_rows():
        title = str(row.get("title") or "")
        if not pattern.search(title):
            continue
        summaries.append(
            {
                "sessionId": str(row.get("sessionId") or "").strip(),
                "title": title[:200],
                "sessionKind": str(row.get("sessionKind") or "").strip(),
                "hiddenFromIndex": bool(row.get("hiddenFromIndex")),
                "updatedAt": _iso_from_ms(row.get("updatedAtMs")),
                "updatedAtMs": int(row.get("updatedAtMs") or 0),
            }
        )
    summaries.sort(key=lambda item: int(item.get("updatedAtMs") or 0), reverse=True)
    return summaries


def remove_question_sessions_for_question(question_id: str) -> dict[str, Any]:
    """Delete every question-bound session through the bulk delete contract."""

    session_ids = [
        str(item.get("sessionId") or "").strip()
        for item in list_question_session_summaries(question_id)
        if str(item.get("sessionId") or "").strip()
    ]
    return remove_question_sessions(session_ids, retire_ghost_rows=True)


def _retire_ghost_directory_rows(session_ids: list[str]) -> tuple[list[str], list[dict[str, str]]]:
    """Archive directory-only ghost rows and tombstone their workspaces.

    A question-bound row can survive the bulk delete as ``not_found`` when its
    chat-state record is already gone but its workspace still holds recoverable
    activity.  Selecting such a row would archive it; the question cleanup must
    do the same so the residue does not stay visible in the session list.
    """

    from . import agent_sessions as session_module

    service = session_module._service()
    retired: list[str] = []
    failed: list[dict[str, str]] = []
    for session_id in session_ids:
        try:
            service._retire_unopenable_directory_session(
                session_id, source="question_conversation_cleanup"
            )
            service._mark_session_workspace_intentionally_deleted(
                session_id, reason="question_cleanup"
            )
        except Exception as exc:  # noqa: BLE001 - report per session and continue
            failed.append({"sessionId": session_id, "reason": f"ghost:{type(exc).__name__}"})
            continue
        retired.append(session_id)
    return retired, failed


def _open_standalone_archive_store() -> ConversationStore | None:
    """Open a temporary directory store when the runtime store is not loaded.

    Offline callers (CLI cleanup) have no open directory runtime, and
    ``archive_directory_session_safe`` intentionally no-ops without one.  The
    question cleanup must still archive the rows it deleted, so it opens the
    store for the duration of the removal and closes it again.
    """

    if directory_runtime.get_open_directory_store() is not None:
        open_root = directory_runtime.directory_store_project_root()
        if open_root is not None and Path(open_root).resolve() == _project_root().resolve():
            return None
    store = ConversationStore(
        directory_runtime.conversation_store_path(_project_root())
    )
    store.open()
    return store


def _archive_directory_rows(store: ConversationStore | None, session_ids: list[str]) -> None:
    if store is None:
        return
    for session_id in session_ids:
        try:
            store.repository.archive_directory_session(session_id).result(timeout=10)
        except Exception:  # noqa: BLE001 - the session body is already removed
            continue


def remove_question_sessions(
    session_ids: list[str] | None,
    *,
    retire_ghost_rows: bool = False,
) -> dict[str, Any]:
    """Chunk the requested sessions through the shared bulk delete path."""

    from .session_bulk_delete import MAX_BULK_SESSION_IDS, bulk_delete_chat_sessions

    requested: list[str] = []
    seen: set[str] = set()
    for value in list(session_ids or []):
        session_id = str(value or "").strip()
        if not session_id or session_id in seen:
            continue
        seen.add(session_id)
        requested.append(session_id)
    removed_session_ids: list[str] = []
    skipped: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []
    archive_store = _open_standalone_archive_store()
    try:
        for start in range(0, len(requested), MAX_BULK_SESSION_IDS):
            chunk = requested[start : start + MAX_BULK_SESSION_IDS]
            chunk_removed_start = len(removed_session_ids)
            result = bulk_delete_chat_sessions(chunk)
            for item in list(result.get("success") or []):
                session_id = str(item.get("sessionId") or "").strip()
                if session_id:
                    removed_session_ids.append(session_id)
            for item in list(result.get("skipped") or []):
                session_id = str(item.get("sessionId") or "").strip()
                reason = str(item.get("reason") or "").strip()
                if retire_ghost_rows and reason == "not_found" and session_id:
                    retired, ghost_failed = _retire_ghost_directory_rows([session_id])
                    removed_session_ids.extend(retired)
                    failed.extend(ghost_failed)
                    if retired:
                        continue
                skipped.append({"sessionId": session_id, "reason": reason})
            for item in list(result.get("failed") or []):
                failed.append(
                    {
                        "sessionId": str(item.get("sessionId") or "").strip(),
                        "reason": str(item.get("reason") or "").strip(),
                    }
                )
            _archive_directory_rows(
                archive_store, removed_session_ids[chunk_removed_start:]
            )
    finally:
        if archive_store is not None:
            archive_store.close()
    return {
        "requestedSessionCount": len(requested),
        "removedSessionCount": len(removed_session_ids),
        "skippedSessionCount": len(skipped),
        "failedSessionCount": len(failed),
        "removedSessionIds": removed_session_ids[:_MAX_QUESTION_SESSION_DETAIL],
        "skippedSessions": skipped[:_MAX_QUESTION_SESSION_DETAIL],
        "failedSessions": failed[:_MAX_QUESTION_SESSION_DETAIL],
        "truncatedDetails": len(requested) > _MAX_QUESTION_SESSION_DETAIL,
    }


__all__ = [
    "list_question_session_summaries",
    "remove_question_sessions",
    "remove_question_sessions_for_question",
]
