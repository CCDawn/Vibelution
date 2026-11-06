"""DAO, repository, and unit-of-work boundaries for conversation storage."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future
from typing import TYPE_CHECKING, Any

from . import runtime as sqlite3

if TYPE_CHECKING:
    from .database import ConversationDatabase
    from .writer import ConversationWriter

LAST_PREVIEW_MAX_CHARS = 240
QUEUE_METADATA_MAX_BYTES = 16 * 1024 * 1024
_DIRECTORY_SESSION_COLUMNS = (
    "session_id, agent_id, parent_session_id, agent_config_revision_id, "
    "title, status, recency_at_ms, updated_at_ms, created_at_ms, archived_at_ms, "
    "session_kind, session_role, conversation_index_kind, "
    "conversation_index_visibility, hidden_from_index, team_id, "
    "last_preview, last_preview_at_ms, pinned_at_ms"
)
_CHAT_STATE_ROOT_KEYS = {
    "version",
    "active_conversation_id",
    "state_revision",
    "updated_at",
    "conversations",
}
_CHAT_STATE_DEBUG_KEYS = {
    "agentPromptSnapshot",
    "agent_prompt_snapshot",
    "last_prompt_assembly",
    "lastPromptAssembly",
    "last_context_composition",
    "lastContextComposition",
    "last_cache_composition",
    "lastCacheComposition",
    "last_llm_payload_trace",
    "lastLlmPayloadTrace",
}


class AgentConfigRevisionConflictError(RuntimeError):
    """A config update targeted a revision that is no longer current."""


class ChatStateRevisionConflictError(RuntimeError):
    """A chat state save targeted a stale ``state_revision``.

    Callers must re-read the current document and replay a deterministic
    mutation with a bounded retry budget instead of overwriting blindly.
    """

    def __init__(self, *, expected: int, current: int) -> None:
        super().__init__(
            f"chat state revision conflict: expected {expected}, current {current}"
        )
        self.expected = expected
        self.current = current


class SessionQueueControlConflictError(RuntimeError):
    """A metadata-bound queue cancellation no longer targets a removable row."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AgentDao:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def create(
        self,
        *,
        agent_id: str,
        display_name: str,
        kind: str,
        config: Mapping[str, Any],
        source: str,
    ) -> dict[str, Any]:
        now_ms = _now_ms()
        config_json = _canonical_json(config)
        config_hash = hashlib.sha256(config_json.encode("utf-8")).hexdigest()
        revision_id = f"{agent_id}:{config_hash}"
        self._connection.execute(
            """
            INSERT INTO agents(
              agent_id, display_name, kind, status,
              current_config_revision_id, created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, 'active', NULL, ?, ?)
            """,
            (agent_id, display_name, kind, now_ms, now_ms),
        )
        self._connection.execute(
            """
            INSERT INTO agent_config_revisions(
              revision_id, agent_id, config_hash, config_json, source, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (revision_id, agent_id, config_hash, config_json, source, now_ms),
        )
        self._connection.execute(
            "UPDATE agents SET current_config_revision_id=? WHERE agent_id=?",
            (revision_id, agent_id),
        )
        return {
            "agentId": agent_id,
            "configRevisionId": revision_id,
            "configHash": config_hash,
        }

    def get(self, agent_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            """
            SELECT agent_id, display_name, kind, status,
                   current_config_revision_id, created_at_ms, updated_at_ms,
                   archived_at_ms
            FROM agents WHERE agent_id=?
            """,
            (agent_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "agentId": str(row["agent_id"]),
            "displayName": str(row["display_name"]),
            "kind": str(row["kind"]),
            "status": str(row["status"]),
            "currentConfigRevisionId": str(row["current_config_revision_id"] or ""),
            "createdAtMs": int(row["created_at_ms"]),
            "updatedAtMs": int(row["updated_at_ms"]),
            "archivedAtMs": (
                int(row["archived_at_ms"])
                if row["archived_at_ms"] is not None
                else None
            ),
        }

    def upsert_config_snapshot(
        self,
        *,
        agent_id: str,
        display_name: str,
        kind: str,
        status: str,
        config: Mapping[str, Any],
        source: str,
    ) -> dict[str, Any]:
        """Import one immutable configuration snapshot without deleting siblings.

        The enclosing writer mutation is one transaction, so a registry import
        either updates every validated Agent snapshot or none of them.
        """

        normalized_agent_id = str(agent_id).strip()
        if not normalized_agent_id:
            raise ValueError("Agent configuration snapshot requires an agent_id.")
        normalized_display_name = str(display_name).strip() or normalized_agent_id
        normalized_kind = str(kind).strip() or "assistant"
        normalized_status = str(status).strip() or "active"
        normalized_source = str(source).strip()
        if not normalized_source:
            raise ValueError("Agent configuration snapshot requires a source.")

        now_ms = _now_ms()
        config_json = _canonical_json(config)
        config_hash = hashlib.sha256(config_json.encode("utf-8")).hexdigest()
        revision_id = f"{normalized_agent_id}:{config_hash}"
        agent_row = self._connection.execute(
            """
            SELECT display_name, kind, status, current_config_revision_id, archived_at_ms
            FROM agents WHERE agent_id=?
            """,
            (normalized_agent_id,),
        ).fetchone()
        revision_row = self._connection.execute(
            """
            SELECT revision_id FROM agent_config_revisions
            WHERE agent_id=? AND config_hash=?
            """,
            (normalized_agent_id, config_hash),
        ).fetchone()

        if agent_row is None:
            self._connection.execute(
                """
                INSERT INTO agents(
                  agent_id, display_name, kind, status,
                  current_config_revision_id, created_at_ms, updated_at_ms, archived_at_ms
                ) VALUES (?, ?, ?, ?, NULL, ?, ?, ?)
                """,
                (
                    normalized_agent_id,
                    normalized_display_name,
                    normalized_kind,
                    normalized_status,
                    now_ms,
                    now_ms,
                    now_ms if normalized_status == "archived" else None,
                ),
            )
            action = "created"
        else:
            current_revision_id = str(agent_row["current_config_revision_id"] or "")
            action = "revised" if current_revision_id != revision_id else "reused"

        if revision_row is None:
            self._connection.execute(
                """
                INSERT INTO agent_config_revisions(
                  revision_id, agent_id, config_hash, config_json, source, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    normalized_agent_id,
                    config_hash,
                    config_json,
                    normalized_source,
                    now_ms,
                ),
            )

        if agent_row is None or action != "reused" or any(
            (
                str(agent_row["display_name"]) != normalized_display_name,
                str(agent_row["kind"]) != normalized_kind,
                str(agent_row["status"]) != normalized_status,
                (
                    agent_row["archived_at_ms"] is None
                    if normalized_status == "archived"
                    else agent_row["archived_at_ms"] is not None
                ),
            )
        ):
            self._connection.execute(
                """
                UPDATE agents
                SET display_name=?, kind=?, status=?, current_config_revision_id=?,
                    updated_at_ms=?, archived_at_ms=?
                WHERE agent_id=?
                """,
                (
                    normalized_display_name,
                    normalized_kind,
                    normalized_status,
                    revision_id,
                    now_ms,
                    now_ms if normalized_status == "archived" else None,
                    normalized_agent_id,
                ),
            )
        return {
            "action": action,
            "agentId": normalized_agent_id,
            "configRevisionId": revision_id,
            "configHash": config_hash,
        }

    def get_current_config(self, agent_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            """
            SELECT revision_id, config_hash, config_json, source, created_at_ms
            FROM agent_config_revisions
            WHERE agent_id=? AND revision_id=(
              SELECT current_config_revision_id FROM agents WHERE agent_id=?
            )
            """,
            (agent_id, agent_id),
        ).fetchone()
        return _config_revision_row(row)

    def compare_and_swap_config_snapshot(
        self,
        *,
        agent_id: str,
        expected_config_revision_id: str,
        display_name: str,
        kind: str,
        status: str,
        config: Mapping[str, Any],
        source: str,
    ) -> dict[str, Any]:
        """Advance configuration only if the caller still owns the current revision."""

        normalized_agent_id = str(agent_id).strip()
        expected_revision_id = str(expected_config_revision_id).strip()
        row = self._connection.execute(
            "SELECT current_config_revision_id FROM agents WHERE agent_id=?",
            (normalized_agent_id,),
        ).fetchone()
        current_revision_id = str(row["current_config_revision_id"] or "") if row else ""
        if not expected_revision_id or current_revision_id != expected_revision_id:
            raise AgentConfigRevisionConflictError(
                "Agent configuration changed before this update could be applied."
            )
        return self.upsert_config_snapshot(
            agent_id=normalized_agent_id,
            display_name=display_name,
            kind=kind,
            status=status,
            config=config,
            source=source,
        )

    def get_config_revision(
        self,
        agent_id: str,
        revision_id: str,
    ) -> dict[str, Any] | None:
        row = self._connection.execute(
            """
            SELECT revision_id, config_hash, config_json, source, created_at_ms
            FROM agent_config_revisions
            WHERE agent_id=? AND revision_id=?
            """,
            (agent_id, revision_id),
        ).fetchone()
        return _config_revision_row(row)


class SessionDao:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def create(
        self,
        *,
        session_id: str,
        agent_id: str,
        agent_config_revision_id: str,
        title: str,
        parent_session_id: str | None = None,
        status: str = "ready",
        session_kind: str = "main",
        session_role: str = "",
        conversation_index_kind: str = "",
        conversation_index_visibility: str = "",
        hidden_from_index: bool = False,
        team_id: str = "",
        last_preview: str = "",
        archived: bool = False,
    ) -> dict[str, Any]:
        now_ms = _now_ms()
        preview = _bounded_preview(last_preview)
        self._connection.execute(
            """
            INSERT INTO sessions(
              session_id, agent_id, parent_session_id,
              agent_config_revision_id, title, status,
              recency_at_ms, updated_at_ms, created_at_ms,
              session_kind, session_role, conversation_index_kind,
              conversation_index_visibility, hidden_from_index, team_id,
              last_preview, last_preview_at_ms, archived_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                agent_id,
                parent_session_id or None,
                agent_config_revision_id,
                title,
                str(status or "ready").strip() or "ready",
                now_ms,
                now_ms,
                now_ms,
                str(session_kind or "main").strip() or "main",
                str(session_role or "").strip(),
                str(conversation_index_kind or "").strip(),
                str(conversation_index_visibility or "").strip(),
                1 if hidden_from_index else 0,
                str(team_id or "").strip(),
                preview,
                now_ms if preview else None,
                now_ms if archived else None,
            ),
        )
        return {"sessionId": session_id, "agentId": agent_id}

    def get(self, session_id: str, *, include_archived: bool = False) -> dict[str, Any] | None:
        row = self._connection.execute(
            f"""
            SELECT {_DIRECTORY_SESSION_COLUMNS}
            FROM sessions
            WHERE session_id=? AND (? OR archived_at_ms IS NULL)
            """,
            (session_id, include_archived),
        ).fetchone()
        return None if row is None else _session_row(row)

    def upsert_directory_session(
        self,
        *,
        session_id: str,
        agent_id: str,
        agent_config_revision_id: str,
        title: str,
        parent_session_id: str | None = None,
        status: str = "ready",
        session_kind: str = "main",
        session_role: str = "",
        conversation_index_kind: str = "",
        conversation_index_visibility: str = "",
        hidden_from_index: bool = False,
        team_id: str = "",
        last_preview: str = "",
        touch_recency: bool = True,
        archived: bool = False,
    ) -> dict[str, Any]:
        existing = self._connection.execute(
            f"SELECT {_DIRECTORY_SESSION_COLUMNS} FROM sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if existing is None:
            self.create(
                session_id=session_id,
                agent_id=agent_id,
                agent_config_revision_id=agent_config_revision_id,
                title=title,
                parent_session_id=parent_session_id,
                status=status,
                session_kind=session_kind,
                session_role=session_role,
                conversation_index_kind=conversation_index_kind,
                conversation_index_visibility=conversation_index_visibility,
                hidden_from_index=hidden_from_index,
                team_id=team_id,
                last_preview=last_preview,
                archived=archived,
            )
            return {"sessionId": session_id, "agentId": agent_id, "action": "created"}
        if str(existing["agent_id"]) != str(agent_id).strip():
            raise ValueError("Session directory record belongs to a different Agent.")
        now_ms = _now_ms()
        preview = _bounded_preview(last_preview)
        recency_at_ms = now_ms if touch_recency else int(existing["recency_at_ms"])
        preview_at = now_ms if preview else existing["last_preview_at_ms"]
        # archived=True keeps the earliest seal (COALESCE-style: an already
        # sealed row keeps its original archived_at_ms); archived=False clears
        # the seal. Deriving this from the payload archive_state on every sync
        # is what keeps agent-archived rows sealed even when an unrelated
        # upsert re-syncs them.
        archived_at_ms = (
            int(existing["archived_at_ms"] or now_ms) if archived else None
        )
        self._connection.execute(
            """
            UPDATE sessions
            SET title=?, status=?, parent_session_id=?,
                session_kind=?, session_role=?, conversation_index_kind=?,
                conversation_index_visibility=?, hidden_from_index=?, team_id=?,
                last_preview=?, last_preview_at_ms=?, recency_at_ms=?,
                updated_at_ms=?, archived_at_ms=?
            WHERE session_id=?
            """,
            (
                title,
                str(status or existing["status"]).strip() or str(existing["status"]),
                parent_session_id or None,
                str(session_kind or "main").strip() or "main",
                str(session_role or "").strip(),
                str(conversation_index_kind or "").strip(),
                str(conversation_index_visibility or "").strip(),
                1 if hidden_from_index else 0,
                str(team_id or "").strip(),
                preview if preview else str(existing["last_preview"] or ""),
                preview_at,
                recency_at_ms,
                now_ms,
                archived_at_ms,
                session_id,
            ),
        )
        return {"sessionId": session_id, "agentId": agent_id, "action": "updated"}

    def touch_directory_session(
        self,
        *,
        session_id: str,
        status: str = "",
        last_preview: str | None = None,
        title: str | None = None,
        touch_recency: bool = True,
    ) -> dict[str, Any] | None:
        existing = self.get(session_id)
        if existing is None:
            return None
        now_ms = _now_ms()
        preview = (
            existing["lastPreview"]
            if last_preview is None
            else _bounded_preview(last_preview)
        )
        self._connection.execute(
            """
            UPDATE sessions
            SET status=?, title=?, last_preview=?, last_preview_at_ms=?,
                recency_at_ms=?, updated_at_ms=?
            WHERE session_id=?
            """,
            (
                str(status or existing["status"]).strip() or existing["status"],
                existing["title"] if title is None else str(title),
                preview,
                now_ms if last_preview is not None else existing.get("lastPreviewAtMs"),
                now_ms if touch_recency else existing["recencyAtMs"],
                now_ms,
                session_id,
            ),
        )
        return {"sessionId": session_id, "action": "touched"}

    def archive(self, session_id: str) -> dict[str, Any] | None:
        existing = self.get(session_id)
        if existing is None:
            return None
        now_ms = _now_ms()
        self._connection.execute(
            """
            UPDATE sessions
            SET archived_at_ms=?, updated_at_ms=?
            WHERE session_id=? AND archived_at_ms IS NULL
            """,
            (now_ms, now_ms, session_id),
        )
        return {"sessionId": session_id, "action": "archived", "archivedAtMs": now_ms}

    def set_pinned(self, session_id: str, *, pinned: bool) -> dict[str, Any] | None:
        """Pin or unpin one directory session for pinned-first list ordering."""

        normalized = str(session_id or "").strip()
        existing = self.get(normalized)
        if existing is None:
            return None
        now_ms = _now_ms()
        pinned_at = now_ms if pinned else None
        self._connection.execute(
            "UPDATE sessions SET pinned_at_ms=? WHERE session_id=?",
            (pinned_at, normalized),
        )
        return {
            "sessionId": normalized,
            "action": "pinned" if pinned else "unpinned",
            "pinnedAtMs": pinned_at,
        }

    def mark_legacy_sessions_discarded(self) -> int:
        return _mark_legacy_sessions_discarded(self._connection)

    def list_for_agent(
        self,
        agent_id: str,
        *,
        limit: int = 50,
        before: tuple[int, str] | None = None,
    ) -> list[dict[str, Any]]:
        page = self.list_directory_page(agent_id=agent_id, limit=limit, before=before)
        return list(page["rows"])

    def list_children(self, parent_session_id: str) -> list[dict[str, Any]]:
        normalized_parent_id = str(parent_session_id or "").strip()
        if not normalized_parent_id:
            return []
        rows = self._connection.execute(
            f"""
            SELECT {_DIRECTORY_SESSION_COLUMNS}
            FROM sessions
            WHERE archived_at_ms IS NULL AND parent_session_id=?
            ORDER BY recency_at_ms DESC, session_id DESC
            """,
            (normalized_parent_id,),
        ).fetchall()
        mapped = [_session_row(row) for row in rows]
        child_ids = _child_session_ids(
            self._connection,
            [item["sessionId"] for item in mapped],
        )
        for item in mapped:
            item["childSessionIds"] = child_ids.get(item["sessionId"], [])
        return mapped

    def list_directory_page(
        self,
        *,
        agent_id: str = "",
        session_kind: str = "",
        status: str = "",
        query: str = "",
        include_hidden: bool = False,
        matching_agent_ids: Sequence[str] = (),
        agent_ids: Sequence[str] = (),
        limit: int = 50,
        before: tuple[int, str] | tuple[int, str, int | None] | None = None,
    ) -> dict[str, Any]:
        bounded_limit = min(200, max(1, int(limit)))
        where = ["archived_at_ms IS NULL"]
        parameters: list[Any] = []
        if not include_hidden:
            where.append("hidden_from_index=0")
        normalized_agent_id = str(agent_id or "").strip()
        if normalized_agent_id:
            where.append("agent_id=?")
            parameters.append(normalized_agent_id)
        # Hard AND-filter for membership-style scopes (e.g. team rosters).
        # Unlike ``matching_agent_ids`` this never ORs with the free-text query.
        scoped_agent_ids = [str(item).strip() for item in agent_ids if str(item).strip()]
        if scoped_agent_ids:
            placeholders = ",".join("?" for _ in scoped_agent_ids)
            where.append(f"agent_id IN ({placeholders})")
            parameters.extend(scoped_agent_ids)
        normalized_kind = str(session_kind or "").strip().lower()
        if normalized_kind:
            where.append("LOWER(session_kind)=?")
            parameters.append(normalized_kind)
        normalized_status = str(status or "").strip().lower()
        if normalized_status:
            where.append("LOWER(status)=?")
            parameters.append(normalized_status)
        normalized_query = str(query or "").strip().lower()
        query_clauses: list[str] = []
        if normalized_query:
            like = _like_contains(normalized_query)
            query_clauses.append(
                "(LOWER(title) LIKE ? ESCAPE '\\' "
                "OR LOWER(last_preview) LIKE ? ESCAPE '\\' "
                "OR LOWER(session_id) LIKE ? ESCAPE '\\')"
            )
            parameters.extend((like, like, like))
        agent_ids = [
            str(item).strip()
            for item in matching_agent_ids
            if str(item).strip()
        ]
        if agent_ids:
            placeholders = ",".join("?" for _ in agent_ids)
            query_clauses.append(f"agent_id IN ({placeholders})")
            parameters.extend(agent_ids)
        if query_clauses:
            where.append("(" + " OR ".join(query_clauses) + ")")
        filter_sql = " AND ".join(where)
        filter_parameters = list(parameters)
        # Keyset pagination over (pinned, recency, session_id). A pinned cursor
        # entry keeps streaming the remaining pinned rows before unpinned rows;
        # an unpinned cursor entry means every pinned row was already emitted,
        # so later pages must exclude pinned rows to avoid duplicates.
        if before is not None:
            before_recency = int(before[0])
            before_session_id = str(before[1])
            before_pinned_at_ms = int(before[2]) if len(before) > 2 and before[2] is not None else None
            if before_pinned_at_ms is None:
                where.append(
                    "(pinned_at_ms IS NULL AND "
                    "(recency_at_ms < ? OR (recency_at_ms = ? AND session_id < ?)))"
                )
                parameters.extend((before_recency, before_recency, before_session_id))
            else:
                where.append(
                    "((pinned_at_ms IS NOT NULL AND "
                    "(pinned_at_ms < ? OR (pinned_at_ms = ? AND "
                    "(recency_at_ms < ? OR (recency_at_ms = ? AND session_id < ?))))) "
                    "OR pinned_at_ms IS NULL)"
                )
                parameters.extend(
                    (
                        before_pinned_at_ms,
                        before_pinned_at_ms,
                        before_recency,
                        before_recency,
                        before_session_id,
                    )
                )
        where_sql = " AND ".join(where)
        total = int(
            self._connection.execute(
                f"SELECT COUNT(*) FROM sessions WHERE {filter_sql}",
                filter_parameters,
            ).fetchone()[0]
        )
        page_parameters = [*parameters, bounded_limit]
        rows = self._connection.execute(
            f"""
            SELECT {_DIRECTORY_SESSION_COLUMNS}
            FROM sessions
            WHERE {where_sql}
            ORDER BY (pinned_at_ms IS NULL) ASC, pinned_at_ms DESC,
                     recency_at_ms DESC, session_id DESC
            LIMIT ?
            """,
            page_parameters,
        ).fetchall()
        mapped = [_session_row(row) for row in rows]
        child_ids = _child_session_ids(
            self._connection,
            [item["sessionId"] for item in mapped],
        )
        for item in mapped:
            item["childSessionIds"] = child_ids.get(item["sessionId"], [])
        next_cursor = ""
        if mapped and len(mapped) == bounded_limit:
            last = mapped[-1]
            next_cursor = directory_cursor_for_row(last)
        return {"rows": mapped, "nextCursor": next_cursor, "total": total}


class SessionEdgeDao:
    """Control-plane-only session lineage; transcript lineage remains journaled."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def link(
        self,
        *,
        source_session_id: str,
        target_session_id: str,
        relation_kind: str,
    ) -> dict[str, Any]:
        normalized_kind = str(relation_kind).strip()
        if normalized_kind not in {"parent", "fork", "handoff"}:
            raise ValueError("Unsupported session edge relation kind.")
        self._connection.execute(
            """
            INSERT INTO session_edges(
              source_session_id, target_session_id, relation_kind, created_at_ms
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(source_session_id, target_session_id, relation_kind) DO NOTHING
            """,
            (source_session_id, target_session_id, normalized_kind, _now_ms()),
        )
        return {
            "sourceSessionId": source_session_id,
            "targetSessionId": target_session_id,
            "relationKind": normalized_kind,
        }


class SessionAdmissionDao:
    """Idempotent submission-control records, never transcript persistence."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def reserve(
        self,
        *,
        session_id: str,
        agent_id: str,
        agent_config_revision_id: str,
        client_submission_id: str,
        turn_id: str,
        expires_at_ms: int | None = None,
    ) -> dict[str, Any]:
        normalized_submission_id = str(client_submission_id).strip()
        normalized_turn_id = str(turn_id).strip()
        if not normalized_submission_id or not normalized_turn_id:
            raise ValueError("Submission admission requires clientSubmissionId and turnId.")
        existing = self._connection.execute(
            """
            SELECT * FROM session_admissions
            WHERE session_id=? AND client_submission_id=?
            """,
            (session_id, normalized_submission_id),
        ).fetchone()
        if existing is not None:
            result = _admission_row(existing)
            result["outcome"] = "reused"
            return result

        bound_session = self._connection.execute(
            """
            SELECT agent_id, agent_config_revision_id
            FROM sessions WHERE session_id=? AND archived_at_ms IS NULL
            """,
            (session_id,),
        ).fetchone()
        if bound_session is None:
            raise sqlite3.IntegrityError("session does not exist or is archived")
        if (
            str(bound_session["agent_id"]) != agent_id
            or str(bound_session["agent_config_revision_id"])
            != agent_config_revision_id
        ):
            raise ValueError("Session admission must use the session's frozen Agent config.")
        now_ms = _now_ms()
        self._connection.execute(
            """
            INSERT INTO session_admissions(
              session_id, client_submission_id, turn_id, agent_id,
              agent_config_revision_id, state, created_at_ms, updated_at_ms,
              expires_at_ms
            ) VALUES (?, ?, ?, ?, ?, 'reserved', ?, ?, ?)
            """,
            (
                session_id,
                normalized_submission_id,
                normalized_turn_id,
                agent_id,
                agent_config_revision_id,
                now_ms,
                now_ms,
                expires_at_ms,
            ),
        )
        return {
            "sessionId": session_id,
            "clientSubmissionId": normalized_submission_id,
            "turnId": normalized_turn_id,
            "agentId": agent_id,
            "agentConfigRevisionId": agent_config_revision_id,
            "state": "reserved",
            "journalSequence": None,
            "journalEventId": "",
            "projectedSequence": None,
            "outcome": "reserved",
        }

    def mark_journaled(
        self,
        *,
        session_id: str,
        client_submission_id: str,
        journal_sequence: int,
        journal_event_id: str,
    ) -> dict[str, Any]:
        row = self._require(session_id, client_submission_id)
        state = str(row["state"])
        if state in {"rejected", "expired"}:
            raise ValueError(f"Cannot journal an admission in {state} state.")
        incoming_sequence = int(journal_sequence)
        if incoming_sequence < 1:
            raise ValueError("Journal sequence must be positive.")
        current_sequence = row["journal_sequence"]
        if current_sequence is not None and incoming_sequence < int(current_sequence):
            return _admission_row(row)
        self._connection.execute(
            """
            UPDATE session_admissions
            SET state=CASE WHEN state='projected' THEN 'projected' ELSE 'journaled' END,
                journal_sequence=?, journal_event_id=?, updated_at_ms=?
            WHERE session_id=? AND client_submission_id=?
            """,
            (
                incoming_sequence,
                str(journal_event_id).strip() or None,
                _now_ms(),
                session_id,
                client_submission_id,
            ),
        )
        return self._get_required(session_id, client_submission_id)

    def mark_projected(
        self,
        *,
        session_id: str,
        client_submission_id: str,
        journal_sequence: int,
    ) -> dict[str, Any]:
        row = self._require(session_id, client_submission_id)
        state = str(row["state"])
        if state not in {"journaled", "projected"}:
            raise ValueError("Only a journaled admission can be projected.")
        incoming_sequence = int(journal_sequence)
        journal_sequence_value = row["journal_sequence"]
        if journal_sequence_value is None or incoming_sequence < int(journal_sequence_value):
            raise ValueError("Projection cannot precede the admitted journal sequence.")
        now_ms = _now_ms()
        self._connection.execute(
            """
            UPDATE session_admissions
            SET state='projected',
                projected_sequence=MAX(COALESCE(projected_sequence, 0), ?),
                updated_at_ms=?
            WHERE session_id=? AND client_submission_id=?
            """,
            (incoming_sequence, now_ms, session_id, client_submission_id),
        )
        self._connection.execute(
            """
            INSERT INTO session_projection_offsets(session_id, journal_sequence, updated_at_ms)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
              journal_sequence=MAX(session_projection_offsets.journal_sequence, excluded.journal_sequence),
              updated_at_ms=excluded.updated_at_ms
            """,
            (session_id, incoming_sequence, now_ms),
        )
        return self._get_required(session_id, client_submission_id)

    def get(
        self,
        *,
        session_id: str,
        client_submission_id: str,
    ) -> dict[str, Any] | None:
        row = self._connection.execute(
            """
            SELECT * FROM session_admissions
            WHERE session_id=? AND client_submission_id=?
            """,
            (session_id, client_submission_id),
        ).fetchone()
        return _admission_row(row) if row is not None else None

    def _require(self, session_id: str, client_submission_id: str) -> Any:
        row = self._connection.execute(
            """
            SELECT * FROM session_admissions
            WHERE session_id=? AND client_submission_id=?
            """,
            (session_id, client_submission_id),
        ).fetchone()
        if row is None:
            raise ValueError("Submission admission does not exist.")
        return row

    def _get_required(self, session_id: str, client_submission_id: str) -> dict[str, Any]:
        result = self.get(
            session_id=session_id,
            client_submission_id=client_submission_id,
        )
        if result is None:
            raise RuntimeError("Submission admission disappeared during the transaction.")
        return result


class SessionProjectionOffsetDao:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, session_id: str) -> int | None:
        row = self._connection.execute(
            "SELECT journal_sequence FROM session_projection_offsets WHERE session_id=?",
            (session_id,),
        ).fetchone()
        return int(row["journal_sequence"]) if row is not None else None


class WorkspaceChatStateDao:
    """Canonical compatibility document backed by normalized SQLite rows."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self) -> dict[str, Any]:
        root = self._connection.execute(
            "SELECT version, active_session_id, state_revision, updated_at, extras_json "
            "FROM workspace_chat_state WHERE id=1"
        ).fetchone()
        if root is None:
            return {}
        try:
            extras = json.loads(str(root["extras_json"] or "{}"))
        except json.JSONDecodeError as exc:
            raise ValueError("SQLite chat state extras are invalid JSON.") from exc
        payload = dict(extras) if isinstance(extras, dict) else {}
        payload.update(
            {
                "version": int(root["version"]),
                "active_conversation_id": str(root["active_session_id"] or ""),
                "state_revision": int(root["state_revision"]),
                "updated_at": str(root["updated_at"] or ""),
            }
        )
        debug_by_session: dict[str, dict[str, Any]] = {}
        for row in self._connection.execute(
            "SELECT session_id, payload_json FROM session_debug_snapshots"
        ).fetchall():
            try:
                decoded = json.loads(str(row["payload_json"] or "{}"))
            except json.JSONDecodeError as exc:
                raise ValueError("SQLite session debug snapshot is invalid JSON.") from exc
            if isinstance(decoded, dict):
                debug_by_session[str(row["session_id"])] = decoded
        conversations: list[dict[str, Any]] = []
        rows = self._connection.execute(
            "SELECT session_id, payload_json FROM session_runtime_state "
            "ORDER BY position ASC"
        ).fetchall()
        for row in rows:
            try:
                decoded = json.loads(str(row["payload_json"] or "{}"))
            except json.JSONDecodeError as exc:
                raise ValueError("SQLite session runtime state is invalid JSON.") from exc
            if not isinstance(decoded, dict):
                raise ValueError("SQLite session runtime state must be an object.")
            decoded.update(debug_by_session.get(str(row["session_id"]), {}))
            conversations.append(decoded)
        payload["conversations"] = conversations
        return payload

    def existing_session_count(self) -> int | None:
        """Check migration completion without decoding any session payloads.

        An absent root differs from an initialized, empty workspace. Read the
        root and count in one statement so the result belongs to one snapshot.
        """
        row = self._connection.execute(
            "SELECT (SELECT COUNT(*) FROM session_runtime_state) AS session_count "
            "FROM workspace_chat_state WHERE id=1"
        ).fetchone()
        return int(row["session_count"]) if row is not None else None

    def list_session_ids(self) -> list[str]:
        rows = self._connection.execute(
            "SELECT session_id FROM session_runtime_state ORDER BY position ASC"
        ).fetchall()
        return [str(row["session_id"] or "").strip() for row in rows if str(row["session_id"] or "").strip()]

    def get_active_session_id(self) -> str:
        root = self._connection.execute(
            "SELECT active_session_id FROM workspace_chat_state WHERE id=1"
        ).fetchone()
        return str(root["active_session_id"] or "").strip() if root is not None else ""

    def get_one(self, session_id: str) -> dict[str, Any] | None:
        normalized = str(session_id or "").strip()
        if not normalized:
            return None
        row = self._connection.execute(
            "SELECT payload_json FROM session_runtime_state WHERE session_id=?",
            (normalized,),
        ).fetchone()
        if row is None:
            return None
        decoded = _decode_json_object(row["payload_json"], label="session runtime state")
        debug_row = self._connection.execute(
            "SELECT payload_json FROM session_debug_snapshots WHERE session_id=?",
            (normalized,),
        ).fetchone()
        if debug_row is not None:
            decoded.update(
                _decode_json_object(debug_row["payload_json"], label="session debug snapshot")
            )
        return decoded

    def terminal_states(self, session_ids: Sequence[str]) -> dict[str, dict[str, str]]:
        """Read only terminal metadata for a directory page, without transcripts."""
        ids = tuple(dict.fromkeys(str(value).strip() for value in session_ids if str(value).strip()))
        if not ids:
            return {}
        rows = self._connection.execute(
            """
            SELECT session_id,
              COALESCE(NULLIF(json_extract(payload_json, '$.last_turn_status'), ''),
                       json_extract(payload_json, '$.lastTurnStatus')) AS last_turn_status,
              COALESCE(NULLIF(json_extract(payload_json, '$.last_turn_terminal_reason'), ''),
                       NULLIF(json_extract(payload_json, '$.lastTurnTerminalReason'), ''),
                       json_extract(payload_json, '$.terminalReason')) AS last_turn_terminal_reason,
              COALESCE(NULLIF(json_extract(payload_json, '$.last_turn_terminal_turn_id'), ''),
                       json_extract(payload_json, '$.lastTurnTerminalTurnId')) AS last_turn_terminal_turn_id
            FROM session_runtime_state
            WHERE session_id IN (SELECT value FROM json_each(?))
            """,
            (json.dumps(ids),),
        ).fetchall()
        fields = ("last_turn_status", "last_turn_terminal_reason", "last_turn_terminal_turn_id")
        return {
            str(row["session_id"]): {
                field: row[field].strip() if isinstance(row[field], str) else ""
                for field in fields
            }
            for row in rows
        }

    def queue_metadata_snapshot(
        self, *, max_rows: int, session_id: str | None = None,
    ) -> dict[str, Any]:
        """Select only bounded queue identity/control scalars, never body columns.

        The caller holds one read transaction. JSON stays inside SQLite; no
        runtime document, queue content, debug snapshot or Journal is hydrated.
        Malformed documents/rows stay visible through invalidCount.
        """
        root = self._connection.execute(
            "SELECT state_revision FROM workspace_chat_state WHERE id=1"
        ).fetchone()
        revision = int(root["state_revision"]) if root is not None else 0
        session_count = int(self._connection.execute(
            "SELECT COUNT(*) FROM session_runtime_state WHERE (? IS NULL OR session_id=?)",
            (session_id, session_id),
        ).fetchone()[0])
        # Even malformed documents and empty queues use a bounded session scan.
        # CASE guards json_each from scalars and malformed JSON, while sentinel
        # rows below distinguish an invalid queue from a valid empty queue.
        rows = self._connection.execute("""
            WITH bounded AS MATERIALIZED (
              SELECT session_id, length(CAST(payload_json AS BLOB)) AS bytes
              FROM session_runtime_state
              WHERE (? IS NULL OR session_id=?)
              ORDER BY session_id LIMIT ?
            ), budgeted AS (
              SELECT session_id,
                SUM(bytes) OVER (ORDER BY session_id) > ? AS over_budget
              FROM bounded
            ), safe AS (
              SELECT b.session_id, b.over_budget,
                CASE WHEN NOT b.over_budget THEN json_valid(r.payload_json) ELSE 0 END AS valid,
                CASE WHEN NOT b.over_budget AND json_valid(r.payload_json)
                  THEN r.payload_json ELSE '{}' END AS doc
              FROM budgeted b JOIN session_runtime_state r ON r.session_id=b.session_id
            ), items AS (
              SELECT s.session_id, s.valid, s.doc, s.over_budget, q.key, q.type AS row_type,
                CASE WHEN q.type='object' THEN q.value ELSE '{}' END AS item
              FROM safe s LEFT JOIN json_each(CASE
                WHEN json_type(doc, '$.queued_turns')='array'
                THEN json_extract(doc, '$.queued_turns') ELSE '[]' END) q
            )
            SELECT CASE WHEN length(i.session_id) <= 160 THEN i.session_id END AS sessionId,
              CASE WHEN i.valid AND json_type(doc)='object' AND
                (json_type(doc, '$.queued_turns') IS NULL OR json_type(doc, '$.queued_turns')='array')
                THEN 1 ELSE 0 END AS documentValid,
              row_type AS rowType, key AS queueIndex, over_budget AS budgetExceeded,
              CASE WHEN json_type(item, '$.id')='text' AND length(json_extract(item, '$.id')) <= 160
                THEN json_extract(item, '$.id') END AS queueId,
              CASE WHEN d.agent_id IS NOT NULL AND (
                  (json_type(doc, '$.agent_id')='text' AND json_extract(doc, '$.agent_id') NOT IN ('', d.agent_id))
                  OR (json_type(doc, '$.agentId')='text' AND json_extract(doc, '$.agentId') NOT IN ('', d.agent_id)))
                THEN ''
                WHEN length(COALESCE(d.agent_id, json_extract(doc, '$.agent_id'),
                    json_extract(doc, '$.agentId'), '')) <= 160
                   AND typeof(COALESCE(d.agent_id, json_extract(doc, '$.agent_id'),
                    json_extract(doc, '$.agentId'), ''))='text'
                THEN COALESCE(d.agent_id, json_extract(doc, '$.agent_id'), json_extract(doc, '$.agentId'), '')
                ELSE '' END AS agentId,
              CASE WHEN json_type(item, '$.kind') IS NULL THEN 'user'
                WHEN json_extract(item, '$.kind') IN ('user','task_notification','subagent_message','control_notice')
                THEN json_extract(item, '$.kind') ELSE 'unknown' END AS queueKind,
              CASE WHEN json_type(item, '$.status') IS NULL THEN 'queued'
                WHEN json_extract(item, '$.status') IN ('queued','starting','paused','blocked')
                THEN json_extract(item, '$.status') ELSE 'unknown' END AS status,
              CASE WHEN json_type(item, '$.branchGeneration')='integer'
                AND typeof(json_extract(item, '$.branchGeneration'))='integer'
                AND json_extract(item, '$.branchGeneration') >= 0
                THEN json_extract(item, '$.branchGeneration') END AS branchGeneration,
              CASE WHEN json_type(doc, '$.branchGeneration')='integer'
                AND typeof(json_extract(doc, '$.branchGeneration'))='integer'
                AND json_extract(doc, '$.branchGeneration') >= 0
                THEN json_extract(doc, '$.branchGeneration') ELSE 0 END AS sessionBranchGeneration,
              CASE WHEN json_type(doc, '$.queued_turn_hold')='object'
                AND EXISTS(SELECT 1 FROM json_each(doc, '$.queued_turn_hold')) THEN 1 ELSE 0 END AS sessionHeld,
              CASE WHEN json_type(item, '$.held')='object'
                AND EXISTS(SELECT 1 FROM json_each(item, '$.held')) THEN 1 ELSE 0 END AS held,
              CASE WHEN json_type(item, '$.sendNow')='true' THEN 1 ELSE 0 END AS sendNow,
              CASE WHEN (json_type(item, '$.sendNow') IS NULL OR json_type(item, '$.sendNow') IN ('true','false'))
                AND (json_type(item, '$.held') IS NULL OR json_type(item, '$.held') IN ('null','object'))
                AND (json_type(doc, '$.queued_turn_hold') IS NULL OR json_type(doc, '$.queued_turn_hold')='object')
                AND (json_type(item, '$.branchGeneration') IS NULL OR json_type(item, '$.branchGeneration')='null'
                     OR (json_type(item, '$.branchGeneration')='integer'
                         AND typeof(json_extract(item, '$.branchGeneration'))='integer'
                         AND json_extract(item, '$.branchGeneration') >= 0))
                AND (json_type(doc, '$.branchGeneration') IS NULL OR
                     (json_type(doc, '$.branchGeneration')='integer'
                      AND typeof(json_extract(doc, '$.branchGeneration'))='integer'
                      AND json_extract(doc, '$.branchGeneration') >= 0))
                AND (json_type(doc, '$.agent_id') IS NULL OR json_type(doc, '$.agent_id') IN ('null','text'))
                AND (json_type(doc, '$.agentId') IS NULL OR json_type(doc, '$.agentId') IN ('null','text'))
                AND length(COALESCE(json_extract(doc, '$.agent_id'), json_extract(doc, '$.agentId'), '')) <= 160
                AND (d.agent_id IS NULL OR (
                     (json_type(doc, '$.agent_id') IS NULL OR json_type(doc, '$.agent_id')='null'
                      OR json_extract(doc, '$.agent_id') IN ('',d.agent_id))
                     AND (json_type(doc, '$.agentId') IS NULL OR json_type(doc, '$.agentId')='null'
                      OR json_extract(doc, '$.agentId') IN ('',d.agent_id))))
                THEN 1 ELSE 0 END AS metadataValid
            FROM items i LEFT JOIN sessions d ON d.session_id=i.session_id
            WHERE row_type IS NOT NULL OR NOT(valid AND json_type(doc)='object' AND
              (json_type(doc, '$.queued_turns') IS NULL OR json_type(doc, '$.queued_turns')='array'))
            ORDER BY i.session_id, key LIMIT ?
        """, (session_id, session_id, max_rows, QUEUE_METADATA_MAX_BYTES, max_rows + 1)).fetchall()
        truncated = session_count > max_rows or len(rows) > max_rows
        invalid = 0
        projected: dict[tuple[str, str], dict[str, Any]] = {}
        seen: set[tuple[str, str]] = set()
        for raw in rows[:max_rows]:
            item = dict(raw)
            if item.pop("budgetExceeded"):
                truncated = True
                continue
            if not item.pop("documentValid") or item.pop("rowType") != "object":
                invalid += 1
                continue
            sid, qid, aid = (item[key] for key in ("sessionId", "queueId", "agentId"))
            if (not all(isinstance(value, str) and re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", value) for value in (sid, qid))):
                invalid += 1
                continue
            if aid and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", aid) is None:
                invalid += 1
                item["agentId"] = ""
            identity = (sid, qid)
            if identity in seen:
                invalid += 1 + int(identity in projected)
                projected.pop(identity, None)
                continue
            seen.add(identity)
            invalid += int(not item.pop("metadataValid") or item["queueKind"] == "unknown" or item["status"] == "unknown")
            item["position"] = item.pop("queueIndex") + 1
            for field in ("sessionHeld", "held", "sendNow"):
                item[field] = bool(item[field])
            projected[identity] = item
        return {"rows": list(projected.values()), "stateRevision": revision,
                "complete": not (invalid or truncated), "truncated": truncated, "invalidCount": invalid}

    def cancel_queued_turn_metadata(
        self, *, session_id: str, queue_id: str, expected_state_revision: int,
        expected_metadata: Mapping[str, Any], updated_at: str,
    ) -> dict[str, Any]:
        """Remove one pre-Turn row inside the existing writer transaction.

        Only the target Session's metadata is selected. SQLite removes the JSON
        element without returning any queue body or decoding sibling Sessions.
        The workspace revision fences every native content/metadata mutation.
        """
        snapshot = self.queue_metadata_snapshot(max_rows=10000, session_id=session_id)
        revision = snapshot["stateRevision"]
        if revision != expected_state_revision:
            raise ChatStateRevisionConflictError(expected=expected_state_revision, current=revision)
        if not snapshot["complete"]:
            raise SessionQueueControlConflictError("queue_metadata_unavailable")
        row = next((item for item in snapshot["rows"] if item["queueId"] == queue_id), None)
        if row is None:
            raise SessionQueueControlConflictError("queue_not_found")
        if row != dict(expected_metadata):
            raise SessionQueueControlConflictError("queue_metadata_changed")
        if row["status"] not in {"queued", "blocked", "paused"}:
            raise SessionQueueControlConflictError("queue_starting")
        path = f"$.queued_turns[{row['position'] - 1}]"
        self._connection.execute(
            "UPDATE session_runtime_state SET payload_json=json_set("
            "json_remove(payload_json, ?), '$.updated_at', ?), updated_at_ms=? "
            "WHERE session_id=?",
            (path, updated_at, _now_ms(), session_id),
        )
        revision = self._bump_workspace_revision(updated_at=updated_at)
        return {"sessionId": session_id, "queueId": queue_id, "agentId": row["agentId"],
                "status": "cancelled", "stateRevision": revision, "queueMetadata": row}

    def upsert_one(
        self,
        session_id: str,
        conversation: Mapping[str, Any],
        *,
        activate: bool = False,
    ) -> dict[str, Any]:
        normalized = str(session_id or "").strip()
        if not normalized:
            raise ValueError("Session runtime state requires a session id.")
        _session_id, payload, debug = _split_runtime_conversation(conversation, index=0)
        if _session_id and _session_id != normalized:
            raise ValueError("Session runtime state id does not match the conversation payload.")
        payload.setdefault("conversation_id", normalized)
        payload.setdefault("conversationId", normalized)
        now_ms = _now_ms()
        existing = self._connection.execute(
            "SELECT position, payload_json, experiment_binding_json "
            "FROM session_runtime_state WHERE session_id=?",
            (normalized,),
        ).fetchone()
        existing_debug = self._connection.execute(
            "SELECT payload_json FROM session_debug_snapshots WHERE session_id=?",
            (normalized,),
        ).fetchone()
        payload_json = _canonical_json(payload)
        binding_json = _experiment_binding_json(payload)
        debug_json = _canonical_json(debug) if debug else ""
        existing_debug_json = str(existing_debug["payload_json"] or "") if existing_debug is not None else ""
        if existing is not None:
            position = int(existing["position"])
            if (
                str(existing["payload_json"] or "") == payload_json
                and str(existing["experiment_binding_json"] or "") == binding_json
                and existing_debug_json == debug_json
            ):
                root = self._connection.execute(
                    "SELECT state_revision, active_session_id FROM workspace_chat_state WHERE id=1"
                ).fetchone()
                current_active = str(root["active_session_id"] or "") if root is not None else ""
                if activate and current_active != normalized:
                    revision = self._bump_workspace_revision(
                        updated_at=str(payload.get("updated_at") or ""),
                        active_session_id=normalized,
                    )
                    return {
                        "stateRevision": revision,
                        "conversationCount": 1,
                        "activeSessionId": normalized,
                        "sessionId": normalized,
                        "changed": True,
                    }
                return {
                    "stateRevision": int(root["state_revision"] if root is not None else 0),
                    "conversationCount": 1,
                    "activeSessionId": current_active,
                    "sessionId": normalized,
                    "changed": False,
                }
        else:
            position_row = self._connection.execute(
                "SELECT COALESCE(MAX(position), -1) AS max_pos FROM session_runtime_state"
            ).fetchone()
            position = int(position_row["max_pos"] if position_row is not None else -1) + 1
        revision = self._bump_workspace_revision(
            updated_at=str(payload.get("updated_at") or ""),
            active_session_id=normalized if activate else None,
        )
        self._upsert_runtime_row(
            session_id=normalized,
            position=position,
            payload_json=payload_json,
            binding_json=binding_json,
            debug=debug,
            now_ms=now_ms,
        )
        root = self._connection.execute(
            "SELECT active_session_id FROM workspace_chat_state WHERE id=1"
        ).fetchone()
        return {
            "stateRevision": revision,
            "conversationCount": 1,
            "activeSessionId": str(root["active_session_id"] or "") if root is not None else "",
            "sessionId": normalized,
            "changed": True,
        }

    def replace(
        self,
        state: Mapping[str, Any],
        *,
        imported_source_sha256: str = "",
        imported_at_ms: int | None = None,
        expected_state_revision: int | None = None,
        imported_legacy_state_revision: int | None = None,
    ) -> dict[str, Any]:
        frozen = dict(state)
        raw_conversations = frozen.get("conversations")
        if raw_conversations is None:
            raw_conversations = []
        if not isinstance(raw_conversations, list):
            raise ValueError("Chat state conversations must be a list.")
        conversations: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        seen: set[str] = set()
        for index, raw in enumerate(raw_conversations):
            if not isinstance(raw, Mapping):
                raise ValueError(f"Chat state conversation at index {index} must be an object.")
            conversation = dict(raw)
            session_id = str(
                conversation.get("conversation_id")
                or conversation.get("conversationId")
                or conversation.get("id")
                or ""
            ).strip()
            if not session_id:
                raise ValueError(f"Chat state conversation at index {index} requires an id.")
            if session_id in seen:
                raise ValueError(f"Chat state contains duplicate conversation id: {session_id}")
            seen.add(session_id)
            debug = {
                key: conversation.pop(key)
                for key in tuple(conversation)
                if key in _CHAT_STATE_DEBUG_KEYS
            }
            conversations.append((session_id, conversation, debug))

        existing = self._connection.execute(
            "SELECT state_revision, imported_source_sha256, imported_at_ms "
            "FROM workspace_chat_state WHERE id=1"
        ).fetchone()
        current_revision = max(
            0, int(existing["state_revision"] if existing is not None else 0)
        )
        if (
            expected_state_revision is not None
            and int(expected_state_revision) != current_revision
        ):
            raise ChatStateRevisionConflictError(
                expected=int(expected_state_revision),
                current=current_revision,
            )
        if existing is None and imported_legacy_state_revision is not None:
            # One-time import: continue the legacy document's revision
            # sequence so CAS callers and catalog freshness stay coherent.
            current_revision = max(
                current_revision, max(0, int(imported_legacy_state_revision))
            )
        revision = current_revision + 1
        now_ms = _now_ms()
        extras = {key: value for key, value in frozen.items() if key not in _CHAT_STATE_ROOT_KEYS}
        source_hash = str(imported_source_sha256 or "").strip()
        if not source_hash and existing is not None:
            source_hash = str(existing["imported_source_sha256"] or "")
        effective_imported_at = imported_at_ms
        if effective_imported_at is None and existing is not None:
            effective_imported_at = existing["imported_at_ms"]
        self._connection.execute(
            """
            INSERT INTO workspace_chat_state(
              id, version, active_session_id, state_revision, updated_at,
              extras_json, imported_source_sha256, imported_at_ms
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              version=excluded.version,
              active_session_id=excluded.active_session_id,
              state_revision=excluded.state_revision,
              updated_at=excluded.updated_at,
              extras_json=excluded.extras_json,
              imported_source_sha256=excluded.imported_source_sha256,
              imported_at_ms=excluded.imported_at_ms
            """,
            (
                max(1, int(frozen.get("version") or 1)),
                str(frozen.get("active_conversation_id") or "").strip(),
                revision,
                str(frozen.get("updated_at") or ""),
                _canonical_json(extras),
                source_hash,
                effective_imported_at,
            ),
        )
        existing_rows = {
            str(row["session_id"]): row
            for row in self._connection.execute(
                "SELECT session_id, position, payload_json, experiment_binding_json "
                "FROM session_runtime_state"
            ).fetchall()
        }
        existing_debug = {
            str(row["session_id"]): str(row["payload_json"] or "")
            for row in self._connection.execute(
                "SELECT session_id, payload_json FROM session_debug_snapshots"
            ).fetchall()
        }
        incoming_ids = {session_id for session_id, _conversation, _debug in conversations}
        for session_id in existing_rows:
            if session_id not in incoming_ids:
                self._connection.execute(
                    "DELETE FROM session_runtime_state WHERE session_id=?",
                    (session_id,),
                )
                self._connection.execute(
                    "DELETE FROM session_debug_snapshots WHERE session_id=?",
                    (session_id,),
                )
        for position, (session_id, conversation, debug) in enumerate(conversations):
            payload_json = _canonical_json(conversation)
            binding_json = _experiment_binding_json(conversation)
            debug_json = _canonical_json(debug) if debug else ""
            existing = existing_rows.get(session_id)
            if (
                existing is not None
                and int(existing["position"]) == position
                and str(existing["payload_json"] or "") == payload_json
                and str(existing["experiment_binding_json"] or "") == binding_json
                and existing_debug.get(session_id, "") == debug_json
            ):
                continue
            self._upsert_runtime_row(
                session_id=session_id,
                position=position,
                payload_json=payload_json,
                binding_json=binding_json,
                debug=debug,
                now_ms=now_ms,
            )
        return {
            "stateRevision": revision,
            "conversationCount": len(conversations),
            "activeSessionId": str(frozen.get("active_conversation_id") or "").strip(),
        }

    def _bump_workspace_revision(
        self,
        *,
        updated_at: str = "",
        active_session_id: str | None = None,
    ) -> int:
        existing = self._connection.execute(
            "SELECT version, active_session_id, state_revision, extras_json, "
            "imported_source_sha256, imported_at_ms FROM workspace_chat_state WHERE id=1"
        ).fetchone()
        current_revision = max(0, int(existing["state_revision"] if existing is not None else 0))
        revision = current_revision + 1
        next_active = (
            str(active_session_id or "").strip()
            if active_session_id is not None
            else (str(existing["active_session_id"] or "") if existing is not None else "")
        )
        self._connection.execute(
            """
            INSERT INTO workspace_chat_state(
              id, version, active_session_id, state_revision, updated_at,
              extras_json, imported_source_sha256, imported_at_ms
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              state_revision=excluded.state_revision,
              updated_at=excluded.updated_at,
              active_session_id=excluded.active_session_id
            """,
            (
                max(1, int(existing["version"] if existing is not None else 1)),
                next_active,
                revision,
                str(updated_at or ""),
                str(existing["extras_json"] or "{}") if existing is not None else "{}",
                str(existing["imported_source_sha256"] or "") if existing is not None else "",
                existing["imported_at_ms"] if existing is not None else None,
            ),
        )
        return revision

    def _upsert_runtime_row(
        self,
        *,
        session_id: str,
        position: int,
        payload_json: str,
        binding_json: str,
        debug: Mapping[str, Any],
        now_ms: int,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO session_runtime_state(
              session_id, position, payload_json, experiment_binding_json, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
              position=excluded.position,
              payload_json=excluded.payload_json,
              experiment_binding_json=excluded.experiment_binding_json,
              updated_at_ms=excluded.updated_at_ms
            """,
            (session_id, position, payload_json, binding_json, now_ms),
        )
        if debug:
            self._connection.execute(
                """
                INSERT INTO session_debug_snapshots(session_id, payload_json, updated_at_ms)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                  payload_json=excluded.payload_json,
                  updated_at_ms=excluded.updated_at_ms
                """,
                (session_id, _canonical_json(debug), now_ms),
            )
            return
        self._connection.execute(
            "DELETE FROM session_debug_snapshots WHERE session_id=?",
            (session_id,),
        )

    def directory_overlay(self) -> tuple[str, dict[str, dict[str, Any]]]:
        root = self._connection.execute(
            "SELECT active_session_id FROM workspace_chat_state WHERE id=1"
        ).fetchone()
        active_id = str(root["active_session_id"] or "") if root is not None else ""
        bindings: dict[str, dict[str, Any]] = {}
        for row in self._connection.execute(
            "SELECT session_id, experiment_binding_json FROM session_runtime_state "
            "WHERE experiment_binding_json <> '{}'"
        ).fetchall():
            try:
                decoded = json.loads(str(row["experiment_binding_json"] or "{}"))
            except json.JSONDecodeError as exc:
                raise ValueError("SQLite experiment binding is invalid JSON.") from exc
            if isinstance(decoded, dict) and decoded:
                bindings[str(row["session_id"])] = decoded
        return active_id, bindings


class ConversationUnitOfWork:
    """One writer-thread transaction with explicit after-commit callbacks."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.agents = AgentDao(connection)
        self.sessions = SessionDao(connection)
        self.session_edges = SessionEdgeDao(connection)
        self.admissions = SessionAdmissionDao(connection)
        self.projection_offsets = SessionProjectionOffsetDao(connection)
        self.chat_state = WorkspaceChatStateDao(connection)
        self._after_commit: list[Callable[[], None]] = []

    def after_commit(self, callback: Callable[[], None]) -> None:
        self._after_commit.append(callback)

    def take_after_commit(self) -> tuple[Callable[[], None], ...]:
        callbacks = tuple(self._after_commit)
        self._after_commit.clear()
        return callbacks


class ConversationRepository:
    """Domain-facing facade; callers never receive a writable connection."""

    def __init__(
        self,
        database: ConversationDatabase,
        writer: ConversationWriter,
    ) -> None:
        self._database = database
        self._writer = writer

    def create_agent(self, **values: Any) -> Future[dict[str, Any]]:
        return self._writer.submit(lambda unit_of_work: unit_of_work.agents.create(**values), model_references=True)

    def import_agent_config_snapshots(
        self,
        snapshots: Sequence[Mapping[str, Any]],
    ) -> Future[list[dict[str, Any]]]:
        """Persist a pre-validated registry snapshot through one writer transaction."""

        frozen_snapshots = tuple(dict(snapshot) for snapshot in snapshots)
        return self._writer.submit(
            lambda unit_of_work: [
                unit_of_work.agents.upsert_config_snapshot(**snapshot)
                for snapshot in frozen_snapshots
            ],
            force_flush=True,
            model_references=True,
        )

    def compare_and_swap_agent_config(self, **values: Any) -> Future[dict[str, Any]]:
        return self._writer.submit(
            lambda unit_of_work: unit_of_work.agents.compare_and_swap_config_snapshot(
                **values
            ),
            force_flush=True,
            model_references=True,
        )

    def create_session(self, **values: Any) -> Future[dict[str, Any]]:
        frozen_values = dict(values)

        def create_with_parent_edge(unit_of_work: ConversationUnitOfWork) -> dict[str, Any]:
            result = unit_of_work.sessions.create(**frozen_values)
            parent_session_id = str(frozen_values.get("parent_session_id") or "").strip()
            if parent_session_id:
                unit_of_work.session_edges.link(
                    source_session_id=parent_session_id,
                    target_session_id=str(result["sessionId"]),
                    relation_kind="parent",
                )
            return result

        return self._writer.submit(create_with_parent_edge, force_flush=True, model_references=True)

    def ensure_session_control_plane(
        self,
        *,
        agent_id: str,
        display_name: str,
        kind: str,
        status: str,
        config: Mapping[str, Any],
        source: str,
        session_id: str,
        title: str,
    ) -> Future[dict[str, Any]]:
        """Create one shadow control record without touching transcript state.

        The caller may invoke this on every enabled submission.  The stored
        session keeps its initial Agent configuration revision, so a later
        operator config edit cannot silently rewrite the admission contract of
        an already existing session.
        """

        frozen_values = {
            "agent_id": str(agent_id).strip(),
            "display_name": str(display_name).strip(),
            "kind": str(kind).strip(),
            "status": str(status).strip(),
            "config": dict(config),
            "source": str(source).strip(),
            "session_id": str(session_id).strip(),
            "title": str(title).strip(),
        }

        def ensure_control_plane(unit_of_work: ConversationUnitOfWork) -> dict[str, Any]:
            agent = unit_of_work.agents.upsert_config_snapshot(
                agent_id=frozen_values["agent_id"],
                display_name=frozen_values["display_name"],
                kind=frozen_values["kind"],
                status=frozen_values["status"],
                config=frozen_values["config"],
                source=frozen_values["source"],
            )
            session = unit_of_work.sessions.get(frozen_values["session_id"])
            if session is None:
                session = unit_of_work.sessions.create(
                    session_id=frozen_values["session_id"],
                    agent_id=frozen_values["agent_id"],
                    agent_config_revision_id=str(agent["configRevisionId"]),
                    title=frozen_values["title"],
                )
                session = unit_of_work.sessions.get(str(session["sessionId"]))
            if session is None:
                raise RuntimeError("Session control record was not created.")
            if str(session["agentId"]) != frozen_values["agent_id"]:
                raise ValueError("Session control record belongs to a different Agent.")
            return {
                "sessionId": str(session["sessionId"]),
                "agentId": str(session["agentId"]),
                "agentConfigRevisionId": str(session["agentConfigRevisionId"]),
                "sessionCreated": bool(session["createdAtMs"] == session["updatedAtMs"]),
            }

        return self._writer.submit(ensure_control_plane, force_flush=True, model_references=True)

    def link_sessions(self, **values: Any) -> Future[dict[str, Any]]:
        return self._writer.submit(
            lambda unit_of_work: unit_of_work.session_edges.link(**values),
            force_flush=True,
        )

    def reserve_submission_admission(self, **values: Any) -> Future[dict[str, Any]]:
        return self._writer.submit(
            lambda unit_of_work: unit_of_work.admissions.reserve(**values),
            force_flush=True,
            model_references=True,
        )

    def mark_submission_journaled(self, **values: Any) -> Future[dict[str, Any]]:
        return self._writer.submit(
            lambda unit_of_work: unit_of_work.admissions.mark_journaled(**values),
            force_flush=True,
        )

    def mark_submission_projected(self, **values: Any) -> Future[dict[str, Any]]:
        return self._writer.submit(
            lambda unit_of_work: unit_of_work.admissions.mark_projected(**values),
            force_flush=True,
        )

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        with self._database.reader() as connection:
            return AgentDao(connection).get(agent_id)

    def get_session(
        self,
        session_id: str,
        *,
        include_archived: bool = False,
    ) -> dict[str, Any] | None:
        with self._database.reader() as connection:
            return SessionDao(connection).get(session_id, include_archived=include_archived)

    def get_current_agent_config(self, agent_id: str) -> dict[str, Any] | None:
        with self._database.reader() as connection:
            return AgentDao(connection).get_current_config(agent_id)

    def get_agent_config_revision(
        self,
        agent_id: str,
        revision_id: str,
    ) -> dict[str, Any] | None:
        with self._database.reader() as connection:
            return AgentDao(connection).get_config_revision(agent_id, revision_id)

    def list_sessions(
        self,
        *,
        agent_id: str,
        limit: int = 50,
        before: tuple[int, str] | None = None,
    ) -> list[dict[str, Any]]:
        with self._database.reader() as connection:
            return SessionDao(connection).list_for_agent(
                agent_id,
                limit=limit,
                before=before,
            )

    def list_directory_page(self, **values: Any) -> dict[str, Any]:
        with self._database.reader() as connection:
            return SessionDao(connection).list_directory_page(**values)

    def list_child_sessions(self, parent_session_id: str) -> list[dict[str, Any]]:
        with self._database.reader() as connection:
            return SessionDao(connection).list_children(parent_session_id)

    def upsert_directory_session(self, **values: Any) -> Future[dict[str, Any]]:
        frozen_values = dict(values)

        def upsert_with_parent_edge(unit_of_work: ConversationUnitOfWork) -> dict[str, Any]:
            result = unit_of_work.sessions.upsert_directory_session(**frozen_values)
            parent_session_id = str(frozen_values.get("parent_session_id") or "").strip()
            if result.get("action") == "created" and parent_session_id:
                unit_of_work.session_edges.link(
                    source_session_id=parent_session_id,
                    target_session_id=str(result["sessionId"]),
                    relation_kind="parent",
                )
            return result

        return self._writer.submit(upsert_with_parent_edge, force_flush=True, model_references=True)

    def repair_archived_directory_owner(self, **values: Any) -> Future[dict[str, str]]:
        """CAS-rebind a sealed legacy session to its payload-proven Agent."""

        from .directory_lifecycle import repair_archived_directory_owner

        frozen = dict(values)
        return self._writer.submit(
            lambda unit_of_work: repair_archived_directory_owner(
                unit_of_work.sessions._connection, **frozen, now_ms=_now_ms(),
            ),
            force_flush=True,
            model_references=True,
        )

    def repair_live_directory_owner(self, **values: Any) -> Future[dict[str, str]]:
        """CAS-rebind a live directory row to its claim-proven Agent."""

        from .directory_lifecycle import repair_live_directory_owner

        frozen = dict(values)
        return self._writer.submit(
            lambda unit_of_work: repair_live_directory_owner(
                unit_of_work.sessions._connection, **frozen, now_ms=_now_ms(),
            ),
            force_flush=True,
            model_references=True,
        )

    def touch_directory_session(self, **values: Any) -> Future[dict[str, Any] | None]:
        return self._writer.submit(
            lambda unit_of_work: unit_of_work.sessions.touch_directory_session(**values),
            force_flush=False,
        )

    def archive_directory_session(self, session_id: str) -> Future[dict[str, Any] | None]:
        normalized = str(session_id or "").strip()
        return self._writer.submit(
            lambda unit_of_work: unit_of_work.sessions.archive(normalized),
            force_flush=True,
        )

    def set_session_pinned(
        self,
        session_id: str,
        *,
        pinned: bool,
    ) -> Future[dict[str, Any] | None]:
        normalized = str(session_id or "").strip()
        return self._writer.submit(
            lambda unit_of_work: unit_of_work.sessions.set_pinned(normalized, pinned=pinned),
            force_flush=True,
        )

    def legacy_sessions_discarded_at_ms(self) -> int | None:
        with self._database.reader() as connection:
            return _legacy_sessions_discarded_at_ms(connection)

    def mark_legacy_sessions_discarded(self) -> Future[int]:
        return self._writer.submit(
            lambda unit_of_work: unit_of_work.sessions.mark_legacy_sessions_discarded(),
            force_flush=True,
        )

    def get_submission_admission(
        self,
        *,
        session_id: str,
        client_submission_id: str,
    ) -> dict[str, Any] | None:
        with self._database.reader() as connection:
            return SessionAdmissionDao(connection).get(
                session_id=session_id,
                client_submission_id=client_submission_id,
            )

    def get_session_projection_offset(self, session_id: str) -> int | None:
        with self._database.reader() as connection:
            return SessionProjectionOffsetDao(connection).get(session_id)

    def get_chat_state(self) -> dict[str, Any]:
        with self._database.reader() as connection:
            return WorkspaceChatStateDao(connection).get()

    def get_existing_chat_state_session_count(self) -> int | None:
        with self._database.reader() as connection:
            return WorkspaceChatStateDao(connection).existing_session_count()

    def get_session_runtime_state(self, session_id: str) -> dict[str, Any] | None:
        with self._database.reader() as connection:
            return WorkspaceChatStateDao(connection).get_one(session_id)

    def read_session_queue_metadata_snapshot(self, *, max_rows: int = 10000) -> dict[str, Any]:
        """Read existing queue metadata in one SQLite snapshot without writes."""
        if type(max_rows) is not int or not 1 <= max_rows <= 10000:
            raise ValueError("Invalid metadata inventory limit")
        with self._database.reader() as connection:
            connection.execute("BEGIN")
            try:
                return WorkspaceChatStateDao(connection).queue_metadata_snapshot(max_rows=max_rows)
            finally:
                connection.execute("ROLLBACK")

    def cancel_session_queued_turn_metadata(
        self, *, session_id: str, queue_id: str, expected_state_revision: int,
        expected_metadata: Mapping[str, Any], updated_at: str,
    ) -> Future[dict[str, Any]]:
        """CAS cancellation through the sole ConversationWriter persistence owner."""
        if type(expected_state_revision) is not int or expected_state_revision < 0:
            raise ValueError("Invalid metadata state revision")
        for identity in (session_id, queue_id):
            if not isinstance(identity, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", identity) is None:
                raise ValueError("Invalid queue identity")
        frozen = dict(expected_metadata)
        if frozen.get("sessionId") != session_id or frozen.get("queueId") != queue_id:
            raise ValueError("Queue metadata identity mismatch")
        return self._writer.submit(
            lambda unit_of_work: unit_of_work.chat_state.cancel_queued_turn_metadata(
                session_id=session_id, queue_id=queue_id,
                expected_state_revision=expected_state_revision,
                expected_metadata=frozen, updated_at=updated_at,
            ),
            force_flush=True,
        )

    def get_session_terminal_states(self, session_ids: Sequence[str]) -> dict[str, dict[str, str]]:
        with self._database.reader() as connection:
            return WorkspaceChatStateDao(connection).terminal_states(session_ids)

    def list_session_runtime_ids(self) -> list[str]:
        with self._database.reader() as connection:
            return WorkspaceChatStateDao(connection).list_session_ids()

    def get_active_session_id(self) -> str:
        with self._database.reader() as connection:
            return WorkspaceChatStateDao(connection).get_active_session_id()

    def upsert_session_runtime_state(
        self,
        session_id: str,
        conversation: Mapping[str, Any],
        *,
        activate: bool = False,
    ) -> Future[dict[str, Any]]:
        frozen = dict(conversation)
        return self._writer.submit(
            lambda unit_of_work: unit_of_work.chat_state.upsert_one(
                session_id,
                frozen,
                activate=activate,
            ),
            force_flush=True,
        )

    def upsert_session_runtime_states(
        self,
        conversations: Sequence[Mapping[str, Any]],
        *,
        activate_session_id: str = "",
    ) -> Future[dict[str, Any]]:
        """Commit related runtime rows in one writer transaction and flush.

        Unlike replacing chat state, this never prunes unmentioned siblings.
        A failed row rolls back every runtime row in the batch.
        """
        frozen = [dict(conversation) for conversation in conversations]
        activate = str(activate_session_id or "").strip()

        def upsert(unit_of_work: ConversationUnitOfWork) -> dict[str, Any]:
            result: dict[str, Any] = {}
            session_ids: list[str] = []
            for conversation in frozen:
                session_id = str(
                    conversation.get("conversation_id") or conversation.get("conversationId") or ""
                ).strip()
                result = unit_of_work.chat_state.upsert_one(
                    session_id, conversation, activate=session_id == activate,
                )
                session_ids.append(session_id)
            return {**result, "sessionIds": session_ids}

        return self._writer.submit(upsert, force_flush=True)

    def get_chat_state_directory_overlay(self) -> tuple[str, dict[str, dict[str, Any]]]:
        with self._database.reader() as connection:
            return WorkspaceChatStateDao(connection).directory_overlay()

    def replace_chat_state(
        self,
        state: Mapping[str, Any],
        *,
        imported_source_sha256: str = "",
        imported_at_ms: int | None = None,
        expected_state_revision: int | None = None,
        imported_legacy_state_revision: int | None = None,
    ) -> Future[dict[str, Any]]:
        frozen = dict(state)
        return self._writer.submit(
            lambda unit_of_work: unit_of_work.chat_state.replace(
                frozen,
                imported_source_sha256=imported_source_sha256,
                imported_at_ms=imported_at_ms,
                expected_state_revision=expected_state_revision,
                imported_legacy_state_revision=imported_legacy_state_revision,
            ),
            force_flush=True,
        )

    def update_chat_state(
        self,
        mutate: Callable[[dict[str, Any]], Any],
        *,
        expected_state_revision: int | None = None,
    ) -> Future[dict[str, Any]]:
        """Atomic read-modify-write of the workspace chat state.

        ``mutate`` runs on the writer thread inside the open transaction:
        it receives the current document and its changes are committed
        together with the replace. The mutator must be deterministic and
        must not submit other store work or block for a long time.
        """

        def mutation(unit_of_work: ConversationUnitOfWork) -> dict[str, Any]:
            current = unit_of_work.chat_state.get()
            current_revision = max(0, int(current.get("state_revision") or 0))
            if (
                expected_state_revision is not None
                and int(expected_state_revision) != current_revision
            ):
                raise ChatStateRevisionConflictError(
                    expected=int(expected_state_revision),
                    current=current_revision,
                )
            payload = dict(current)
            mutate(payload)
            return unit_of_work.chat_state.replace(payload)

        return self._writer.submit(mutation, force_flush=True)

    def archive_session_and_replace_chat_state(
        self,
        *,
        session_id: str,
        state: Mapping[str, Any],
        imported_source_sha256: str = "",
        imported_at_ms: int | None = None,
        expected_state_revision: int | None = None,
    ) -> Future[dict[str, Any]]:
        """Delete one session in a single transaction.

        Replaces the workspace chat state document and archives the matching
        directory session row in the same commit. Either both effects land or
        neither does; callers never observe a half-deleted session.
        """

        frozen = dict(state)
        normalized_session_id = str(session_id or "").strip()

        def mutation(unit_of_work: ConversationUnitOfWork) -> dict[str, Any]:
            chat_state_result = unit_of_work.chat_state.replace(
                frozen,
                imported_source_sha256=imported_source_sha256,
                imported_at_ms=imported_at_ms,
                expected_state_revision=expected_state_revision,
            )
            archive_result = unit_of_work.sessions.archive(normalized_session_id)
            return {
                "archive": archive_result,
                "chatState": chat_state_result,
            }

        return self._writer.submit(mutation, force_flush=True)


def _decode_json_object(raw: Any, *, label: str) -> dict[str, Any]:
    try:
        decoded = json.loads(str(raw or "{}"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"SQLite {label} is invalid JSON.") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"SQLite {label} must be an object.")
    return decoded


def _split_runtime_conversation(
    raw: Mapping[str, Any],
    *,
    index: int,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    conversation = dict(raw)
    session_id = str(
        conversation.get("conversation_id")
        or conversation.get("conversationId")
        or conversation.get("id")
        or ""
    ).strip()
    if not session_id:
        raise ValueError(f"Chat state conversation at index {index} requires an id.")
    debug = {
        key: conversation.pop(key)
        for key in tuple(conversation)
        if key in _CHAT_STATE_DEBUG_KEYS
    }
    return session_id, conversation, debug


def _experiment_binding_json(conversation: Mapping[str, Any]) -> str:
    binding = conversation.get("experimentBinding") or conversation.get("experiment_binding") or {}
    if not isinstance(binding, Mapping):
        binding = {}
    return _canonical_json(binding)


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _config_revision_row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    config = json.loads(str(row["config_json"]))
    if not isinstance(config, dict):
        raise TypeError("Agent configuration revision payload is not an object.")
    return {
        "configRevisionId": str(row["revision_id"]),
        "configHash": str(row["config_hash"]),
        "config": config,
        "source": str(row["source"]),
        "createdAtMs": int(row["created_at_ms"]),
    }


def _admission_row(row: Any) -> dict[str, Any]:
    return {
        "sessionId": str(row["session_id"]),
        "clientSubmissionId": str(row["client_submission_id"]),
        "turnId": str(row["turn_id"]),
        "agentId": str(row["agent_id"]),
        "agentConfigRevisionId": str(row["agent_config_revision_id"]),
        "state": str(row["state"]),
        "journalSequence": (
            int(row["journal_sequence"])
            if row["journal_sequence"] is not None
            else None
        ),
        "journalEventId": str(row["journal_event_id"] or ""),
        "projectedSequence": (
            int(row["projected_sequence"])
            if row["projected_sequence"] is not None
            else None
        ),
    }


def _now_ms() -> int:
    return int(time.time() * 1000)


def parse_directory_cursor(cursor: str) -> tuple[int, str] | None:
    raw = str(cursor or "").strip()
    if ":" not in raw:
        return None
    recency, session_id = raw.split(":", 1)
    normalized_session_id = session_id.strip()
    if not normalized_session_id:
        return None
    try:
        recency_ms = int(recency)
    except ValueError:
        return None
    if recency_ms < 0:
        return None
    return recency_ms, normalized_session_id


def parse_directory_cursor_entry(
    cursor: str,
) -> tuple[int, str, int | None] | None:
    """Parse a directory cursor into ``(recency_at_ms, session_id, pinned_at_ms)``.

    Accepts both cursor shapes: ``"<recency>:<session_id>"`` for unpinned rows
    (``pinned_at_ms`` is ``None``) and ``"p<pinned_at_ms>:<recency>:<session_id>"``
    for rows that were pinned when the page was cut.
    """

    raw = str(cursor or "").strip()
    pinned_at_ms: int | None = None
    if raw.startswith("p") and not raw.startswith("p "):
        first_colon = raw.find(":")
        if first_colon <= 1:
            return None
        try:
            pinned_at_ms = int(raw[1:first_colon])
        except ValueError:
            return None
        if pinned_at_ms < 0:
            return None
        raw = raw[first_colon + 1 :]
    parsed = parse_directory_cursor(raw)
    if parsed is None:
        return None
    recency_ms, session_id = parsed
    return recency_ms, session_id, pinned_at_ms


def directory_cursor_for_row(row: Mapping[str, Any]) -> str:
    recency = row.get("recencyAtMs")
    session_id = str(row.get("sessionId") or "").strip()
    if recency in (None, "") or not session_id:
        return ""
    try:
        recency_ms = int(recency)
    except (TypeError, ValueError):
        return ""
    pinned_at = row.get("pinnedAtMs")
    if pinned_at is None:
        return f"{recency_ms}:{session_id}"
    try:
        pinned_at_ms = int(pinned_at)
    except (TypeError, ValueError):
        return f"{recency_ms}:{session_id}"
    return f"p{pinned_at_ms}:{recency_ms}:{session_id}"


def _like_contains(value: str) -> str:
    escaped = (
        str(value or "")
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return f"%{escaped}%"


def _bounded_preview(value: str) -> str:
    compact = " ".join(str(value or "").split())
    if len(compact) <= LAST_PREVIEW_MAX_CHARS:
        return compact
    return compact[: LAST_PREVIEW_MAX_CHARS - 1].rstrip() + "…"


def _session_row(row: Any) -> dict[str, Any]:
    preview_at = row["last_preview_at_ms"]
    pinned_at = row["pinned_at_ms"]
    return {
        "sessionId": str(row["session_id"]),
        "agentId": str(row["agent_id"]),
        "parentSessionId": str(row["parent_session_id"] or ""),
        "agentConfigRevisionId": str(row["agent_config_revision_id"]),
        "title": str(row["title"]),
        "status": str(row["status"]),
        "recencyAtMs": int(row["recency_at_ms"]),
        "updatedAtMs": int(row["updated_at_ms"]),
        "createdAtMs": int(row["created_at_ms"]),
        "sessionKind": str(row["session_kind"] or "main") or "main",
        "sessionRole": str(row["session_role"] or ""),
        "conversationIndexKind": str(row["conversation_index_kind"] or ""),
        "conversationIndexVisibility": str(row["conversation_index_visibility"] or ""),
        "hiddenFromIndex": bool(int(row["hidden_from_index"] or 0)),
        "teamId": str(row["team_id"] or ""),
        "lastPreview": str(row["last_preview"] or ""),
        "lastPreviewAtMs": int(preview_at) if preview_at is not None else None,
        "pinnedAtMs": int(pinned_at) if pinned_at is not None else None,
        "childSessionIds": [],
    }


def _child_session_ids(
    connection: sqlite3.Connection,
    parent_ids: Sequence[str],
) -> dict[str, list[str]]:
    if not parent_ids:
        return {}
    placeholders = ",".join("?" for _ in parent_ids)
    rows = connection.execute(
        f"""
        SELECT session_id, parent_session_id
        FROM sessions
        WHERE archived_at_ms IS NULL AND parent_session_id IN ({placeholders})
        ORDER BY recency_at_ms DESC, session_id DESC
        """,
        tuple(parent_ids),
    ).fetchall()
    grouped: dict[str, list[str]] = {parent_id: [] for parent_id in parent_ids}
    for row in rows:
        parent_id = str(row["parent_session_id"] or "")
        grouped.setdefault(parent_id, []).append(str(row["session_id"]))
    return grouped


def _legacy_sessions_discarded_at_ms(connection: sqlite3.Connection) -> int | None:
    row = connection.execute(
        "SELECT legacy_sessions_discarded_at_ms FROM conversation_store_meta WHERE id=1"
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return int(row[0])


def _mark_legacy_sessions_discarded(connection: sqlite3.Connection) -> int:
    now_ms = _now_ms()
    connection.execute(
        """
        UPDATE conversation_store_meta
        SET legacy_sessions_discarded_at_ms=?, updated_at_ms=?
        WHERE id=1 AND legacy_sessions_discarded_at_ms IS NULL
        """,
        (now_ms, now_ms),
    )
    return now_ms
