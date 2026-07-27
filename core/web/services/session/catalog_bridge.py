"""Canonical-source projection and atomic reconcile bridge for session catalog."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from core.chat.session_catalog import CatalogError, SessionCatalogStore


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
    workspace_key: str,
    indexed_at: str,
) -> dict[str, Any]:
    updated_at = _text(conversation, "updated_at", "updatedAt")
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
        "title": _text(conversation, "title"),
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
        "last_active_at": _text(
            conversation,
            "last_active_at",
            "lastActiveAt",
            "last_active",
            "lastActive",
        )
        or updated_at,
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


def _text(value: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        candidate = str(value.get(key) or "").strip()
        if candidate:
            return candidate
    return ""


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
