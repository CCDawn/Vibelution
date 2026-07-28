"""Canonical-source projection and atomic reconcile bridge for session catalog."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence

from core.chat.session_catalog import (
    CatalogError,
    CatalogUnavailableError,
    SessionCatalogStore,
)


@dataclass(frozen=True)
class CatalogSourceSnapshot:
    source_revision: str
    rows: tuple[dict[str, Any], ...]
    watermark: str
    orphan_journal_count: int = 0


@dataclass(frozen=True)
class CatalogReconcileResult:
    status: str
    session_count: int
    source_revision: str
    orphan_journal_count: int = 0


@dataclass(frozen=True)
class SessionQueryShadowComparison:
    status: str
    mismatch_kinds: tuple[str, ...] = ()
    legacy_count: int = 0
    candidate_count: int = 0
    error_type: str = ""


@dataclass(frozen=True)
class SessionQueryCatalogRead:
    """Bounded result of one catalog candidate read before legacy fallback."""

    status: str
    payload: Mapping[str, Any] | None = None
    candidate_count: int = 0
    error_type: str = ""


_SHADOW_PROVIDER_LOCK = threading.Lock()
_SESSION_QUERY_SHADOW_PROVIDER: (
    Callable[[Mapping[str, Any]], Mapping[str, Any]] | None
) = None
_SHADOW_STATE_FIELDS = (
    "conversationIndexVisibility",
    "sessionKind",
    "status",
    "currentPhase",
    "childStatus",
)


def set_session_query_shadow_provider(
    provider: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None,
) -> None:
    """Install the bounded SQL candidate provider; ``None`` keeps rollout off."""

    global _SESSION_QUERY_SHADOW_PROVIDER
    with _SHADOW_PROVIDER_LOCK:
        _SESSION_QUERY_SHADOW_PROVIDER = provider


def run_session_query_shadow(
    legacy_payload: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
) -> SessionQueryShadowComparison:
    candidate_read = read_session_query_catalog(request=request)
    if candidate_read.payload is None:
        return SessionQueryShadowComparison(
            status=candidate_read.status,
            legacy_count=len(_payload_items(legacy_payload)),
            candidate_count=candidate_read.candidate_count,
            error_type=candidate_read.error_type,
        )
    return compare_session_query_payloads(legacy_payload, candidate_read.payload)


def read_session_query_catalog(
    *,
    request: Mapping[str, Any],
) -> SessionQueryCatalogRead:
    """Read the registered catalog candidate without exposing provider errors."""

    with _SHADOW_PROVIDER_LOCK:
        provider = _SESSION_QUERY_SHADOW_PROVIDER
    if provider is None:
        return SessionQueryCatalogRead(status="disabled")
    try:
        candidate = provider(dict(request))
        if not isinstance(candidate, Mapping):
            raise TypeError("Session catalog query provider returned a non-mapping payload.")
        payload = dict(candidate)
        items = payload.get("items")
        if not isinstance(items, list) or not all(
            isinstance(item, Mapping) for item in items
        ):
            raise TypeError("Session catalog query provider returned invalid items.")
        if any(not str(item.get("id") or "").strip() for item in items):
            raise TypeError("Session catalog query provider returned an item without an id.")
        total = payload.get("totalEstimate")
        if isinstance(total, bool) or not isinstance(total, int):
            raise TypeError("Session catalog query provider returned an invalid total.")
        if total < len(items) or total < 0:
            raise ValueError("Session catalog query provider returned an invalid total.")
        limit = _session_query_request_integer(request, "limit", minimum=1)
        cursor = _session_query_request_integer(request, "cursor", minimum=0)
        start = min(cursor, total)
        expected_item_count = min(limit, total - start)
        if len(items) != expected_item_count:
            raise ValueError("Session catalog query provider returned an invalid page size.")
        next_cursor = payload.get("nextCursor")
        if not isinstance(next_cursor, str):
            raise TypeError("Session catalog query provider returned an invalid cursor.")
        next_offset = start + len(items)
        expected_next_cursor = str(next_offset) if next_offset < total else ""
        if next_cursor != expected_next_cursor:
            raise ValueError("Session catalog query provider returned an invalid cursor.")
        return SessionQueryCatalogRead(
            status="healthy",
            payload=payload,
            candidate_count=len(items),
        )
    except Exception as exc:
        return SessionQueryCatalogRead(
            status="degraded",
            error_type=type(exc).__name__,
        )


def _session_query_request_integer(
    request: Mapping[str, Any],
    field: str,
    *,
    minimum: int,
) -> int:
    raw_value = request.get(field)
    if isinstance(raw_value, bool):
        raise TypeError(f"Session catalog query request has an invalid {field}.")
    try:
        value = int(raw_value or 0)
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"Session catalog query request has an invalid {field}."
        ) from exc
    if value < minimum:
        raise ValueError(f"Session catalog query request has an invalid {field}.")
    return value


def compare_session_query_payloads(
    legacy_payload: Mapping[str, Any],
    candidate_payload: Mapping[str, Any],
) -> SessionQueryShadowComparison:
    """Compare only bounded query contract fields, never titles or user text."""

    legacy_items = _payload_items(legacy_payload)
    candidate_items = _payload_items(candidate_payload)
    mismatches: list[str] = []
    if [_item_id(item) for item in legacy_items] != [
        _item_id(item) for item in candidate_items
    ]:
        mismatches.append("item_ids")
    if [_item_state(item) for item in legacy_items] != [
        _item_state(item) for item in candidate_items
    ]:
        mismatches.append("item_state")
    if str(legacy_payload.get("nextCursor") or "") != str(
        candidate_payload.get("nextCursor") or ""
    ):
        mismatches.append("next_cursor")
    if _safe_int(legacy_payload.get("totalEstimate")) != _safe_int(
        candidate_payload.get("totalEstimate")
    ):
        mismatches.append("total_estimate")
    return SessionQueryShadowComparison(
        status="mismatch" if mismatches else "match",
        mismatch_kinds=tuple(mismatches),
        legacy_count=len(legacy_items),
        candidate_count=len(candidate_items),
    )


def build_session_catalog_query_provider(
    store: SessionCatalogStore,
) -> Callable[[Mapping[str, Any]], Mapping[str, Any]]:
    """Adapt catalog rows to the frozen session-list query payload."""

    def provider(request: Mapping[str, Any]) -> Mapping[str, Any]:
        if store.untrusted_sentinel_path.exists() or store.dirty_session_count() != 0:
            raise CatalogUnavailableError("Session catalog freshness is not proven.")
        page = store.query_session_page(
            q=str(request.get("q") or ""),
            agent_id=str(request.get("agent_id") or ""),
            session_kind=str(request.get("session_kind") or ""),
            state=str(request.get("state") or ""),
            sort=str(request.get("sort") or "updatedAt_desc"),
            limit=int(request.get("limit") or 50),
            cursor=str(request.get("cursor") or ""),
        )
        return {
            "items": [_catalog_query_item(row) for row in page["rows"]],
            "nextCursor": str(page["next_cursor"]),
            "totalEstimate": int(page["total"]),
        }

    return provider


def build_catalog_snapshot(
    conversations: Sequence[Mapping[str, Any]],
    journal_inventory: Mapping[str, Mapping[str, Any]],
    *,
    workspace_key: str,
    indexed_at: str,
    agent_signature: str = "",
    team_signature: str = "",
) -> CatalogSourceSnapshot:
    """Project known canonical conversations; orphan journals stay invisible."""

    normalized_workspace_key = str(workspace_key or "").strip()
    if not normalized_workspace_key:
        raise ValueError("workspace_key is required")
    rows: list[dict[str, Any]] = []
    known_session_ids: set[str] = set()
    for conversation in conversations:
        if not isinstance(conversation, Mapping):
            continue
        session_id = _text(
            conversation,
            "conversation_id",
            "conversationId",
            "session_id",
            "sessionId",
            "id",
        )
        if not session_id or session_id in known_session_ids:
            continue
        known_session_ids.add(session_id)
        journal = journal_inventory.get(session_id)
        journal = journal if isinstance(journal, Mapping) else {}
        row = _project_row(
            conversation,
            journal,
            session_id=session_id,
            source_order=len(rows),
            workspace_key=normalized_workspace_key,
            indexed_at=str(indexed_at or ""),
        )
        rows.append(row)
    rows.sort(key=lambda item: item["session_id"])
    revision_payload = {
        "workspaceKey": normalized_workspace_key,
        "agentSignature": str(agent_signature or ""),
        "teamSignature": str(team_signature or ""),
        "rows": [
            {
                key: value
                for key, value in row.items()
                if key not in {"indexed_at", "source_revision"}
            }
            for row in rows
        ],
    }
    source_revision = _canonical_hash(revision_payload)
    for row in rows:
        row["source_revision"] = _canonical_hash(
            {
                key: value
                for key, value in row.items()
                if key not in {"indexed_at", "source_revision"}
            }
        )
    orphan_count = sum(
        1
        for session_id in journal_inventory
        if str(session_id or "").strip() not in known_session_ids
    )
    watermark = max(
        (str(row.get("journal_rel_path") or "") for row in rows),
        default="",
    )
    return CatalogSourceSnapshot(
        source_revision=source_revision,
        rows=tuple(rows),
        watermark=watermark,
        orphan_journal_count=orphan_count,
    )


class CatalogReconciler:
    """Lease and publish a source-stable catalog generation."""

    def __init__(
        self,
        store: SessionCatalogStore,
        *,
        source_loader: Callable[[], CatalogSourceSnapshot],
    ) -> None:
        self._store = store
        self._source_loader = source_loader

    def reconcile(
        self,
        *,
        owner: str,
        now: str,
        lease_expires_at: str,
    ) -> CatalogReconcileResult:
        if not self._store.try_acquire_lease(
            owner,
            now=str(now),
            expires_at=str(lease_expires_at),
        ):
            return CatalogReconcileResult(
                status="lease_busy",
                session_count=0,
                source_revision="",
            )
        try:
            dirty_before_reconcile = self._store.dirty_sessions()
            candidate = self._source_loader()
            confirmation = self._source_loader()
            if candidate.source_revision != confirmation.source_revision:
                self._store.release_lease(owner, status="pending")
                return _result("source_changed", candidate)
            published = self._store.replace_sessions(
                candidate.rows,
                owner=owner,
                source_revision=candidate.source_revision,
                watermark=candidate.watermark,
                source_revision_reader=lambda: self._source_loader().source_revision,
            )
            if not published:
                self._store.release_lease(owner, status="pending")
                return _result("source_changed", candidate)
            try:
                self._store.clear_dirty_sessions_if_unchanged(dirty_before_reconcile)
                self._store.clear_untrusted_after_reconcile()
            except CatalogError as exc:
                self._store.mark_untrusted(type(exc).__name__)
            return _result("complete", candidate)
        except Exception:
            try:
                self._store.release_lease(owner, status="failed")
            except CatalogError:
                pass
            raise


def _result(
    status: str,
    snapshot: CatalogSourceSnapshot,
) -> CatalogReconcileResult:
    return CatalogReconcileResult(
        status=status,
        session_count=len(snapshot.rows),
        source_revision=snapshot.source_revision,
        orphan_journal_count=snapshot.orphan_journal_count,
    )


def _project_row(
    conversation: Mapping[str, Any],
    journal: Mapping[str, Any],
    *,
    session_id: str,
    source_order: int,
    workspace_key: str,
    indexed_at: str,
) -> dict[str, Any]:
    updated_at = _text(conversation, "updated_at", "updatedAt")
    title = _text(conversation, "title")
    last_active_at = _text(
        conversation,
        "last_active_at",
        "lastActiveAt",
        "last_active",
        "lastActive",
    ) or updated_at
    visibility = _text(
        conversation,
        "conversation_index_visibility",
        "conversationIndexVisibility",
        "visibility",
    )
    if bool(
        conversation.get("hidden_from_index")
        or conversation.get("hiddenFromIndex")
    ):
        visibility = "hidden"
    visibility = visibility or "normal"
    return {
        "session_id": session_id,
        "title": title,
        "task_title": _text(conversation, "task_title", "taskTitle"),
        "task_summary": _text(conversation, "task_summary", "taskSummary"),
        "session_kind": _text(
            conversation,
            "session_kind",
            "sessionKind",
        )
        or "main",
        "visibility": visibility,
        "agent_id": _text(conversation, "agent_id", "agentId"),
        "agent_code": _text(conversation, "agent_code", "agentCode"),
        "agent_display_name": _text(
            conversation,
            "agent_display_name",
            "agentDisplayName",
        ),
        "team_id": _text(conversation, "team_id", "teamId"),
        "parent_session_id": _text(
            conversation,
            "parent_session_id",
            "parentSessionId",
        ),
        "source_session_id": _text(
            conversation,
            "source_session_id",
            "sourceSessionId",
        ),
        "workspace_key": workspace_key,
        "dialogue_model_id": _text(
            conversation,
            "dialogue_model_id",
            "dialogueModelId",
        ),
        "status": _text(conversation, "status"),
        "current_phase": _text(
            conversation,
            "current_phase",
            "currentPhase",
        ),
        "child_status": _text(
            conversation,
            "child_status",
            "childStatus",
        ),
        "created_at": _text(conversation, "created_at", "createdAt"),
        "updated_at": updated_at,
        "last_active_at": last_active_at,
        "source_order": max(0, int(source_order)),
        "updated_at_sort_key": _timestamp_sort_key(updated_at or last_active_at),
        "title_sort_key": _title_sort_key(title),
        "last_turn_status": _text(
            journal,
            "last_turn_status",
            "lastTurnStatus",
        ),
        "open_turn_id": _text(journal, "open_turn_id", "openTurnId"),
        "latest_sequence": _nonnegative_int(
            journal.get("latest_sequence", journal.get("latestSequence", 0))
        ),
        "event_count": _nonnegative_int(
            journal.get("event_count", journal.get("eventCount", 0))
        ),
        "message_count": _nonnegative_int(
            journal.get("message_count", journal.get("messageCount", 0))
        ),
        "journal_rel_path": _safe_relative_path(
            _text(journal, "journal_rel_path", "journalRelPath")
        ),
        "journal_size": _nonnegative_int(
            journal.get("journal_size", journal.get("journalSize", 0))
        ),
        "journal_mtime_ns": _nonnegative_int(
            journal.get("journal_mtime_ns", journal.get("journalMtimeNs", 0))
        ),
        "source_revision": "",
        "indexed_at": indexed_at,
    }


def _catalog_query_item(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("session_id") or ""),
        "title": str(row.get("title") or ""),
        "taskTitle": str(row.get("task_title") or ""),
        "taskSummary": str(row.get("task_summary") or ""),
        "agentId": str(row.get("agent_id") or ""),
        "agentCode": str(row.get("agent_code") or ""),
        "agentDisplayName": str(row.get("agent_display_name") or ""),
        "dialogueModelId": str(row.get("dialogue_model_id") or ""),
        "sessionKind": str(row.get("session_kind") or ""),
        "status": str(row.get("status") or ""),
        "currentPhase": str(row.get("current_phase") or ""),
        "childStatus": str(row.get("child_status") or ""),
        "conversationIndexVisibility": str(row.get("visibility") or ""),
        "updatedAt": str(row.get("updated_at") or ""),
        "lastActive": str(row.get("last_active_at") or ""),
    }


def _text(value: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        candidate = str(value.get(key) or "").strip()
        if candidate:
            return candidate
    return ""


def _timestamp_sort_key(value: Any) -> float:
    """Match the legacy session-query timestamp ordering exactly."""

    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _title_sort_key(value: Any) -> str:
    """Match the legacy session-query title sort key exactly."""

    return str(value or "").strip().lower()


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_relative_path(value: str) -> str:
    normalized = str(value or "").strip().replace("\\", "/")
    parts = [part for part in normalized.split("/") if part and part != "."]
    if not normalized or normalized.startswith("/") or ".." in parts:
        return ""
    if len(parts) > 1 and parts[0].endswith(":"):
        return ""
    return "/".join(parts)


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _payload_items(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return []
    return [item for item in raw_items if isinstance(item, Mapping)]


def _item_id(item: Mapping[str, Any]) -> str:
    return str(item.get("id") or item.get("sessionId") or "").strip()


def _item_state(item: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(str(item.get(field) or "").strip() for field in _SHADOW_STATE_FIELDS)


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
