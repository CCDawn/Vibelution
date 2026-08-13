"""DAO, repository, and unit-of-work boundaries for conversation storage."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future
from typing import TYPE_CHECKING, Any

from . import runtime as sqlite3

if TYPE_CHECKING:
    from .database import ConversationDatabase
    from .writer import ConversationWriter

LAST_PREVIEW_MAX_CHARS = 240
_DIRECTORY_SESSION_COLUMNS = (
    "session_id, agent_id, parent_session_id, agent_config_revision_id, "
    "title, status, recency_at_ms, updated_at_ms, created_at_ms, archived_at_ms, "
    "session_kind, session_role, conversation_index_kind, "
    "conversation_index_visibility, hidden_from_index, team_id, "
    "last_preview, last_preview_at_ms"
)


class AgentConfigRevisionConflictError(RuntimeError):
    """A config update targeted a revision that is no longer current."""


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
              last_preview, last_preview_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        return {"sessionId": session_id, "agentId": agent_id}

    def get(self, session_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            f"""
            SELECT {_DIRECTORY_SESSION_COLUMNS}
            FROM sessions
            WHERE session_id=? AND archived_at_ms IS NULL
            """,
            (session_id,),
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
            )
            return {"sessionId": session_id, "agentId": agent_id, "action": "created"}
        if str(existing["agent_id"]) != str(agent_id).strip():
            raise ValueError("Session directory record belongs to a different Agent.")
        now_ms = _now_ms()
        preview = _bounded_preview(last_preview)
        recency_at_ms = now_ms if touch_recency else int(existing["recency_at_ms"])
        preview_at = now_ms if preview else existing["last_preview_at_ms"]
        self._connection.execute(
            """
            UPDATE sessions
            SET title=?, status=?, parent_session_id=?,
                session_kind=?, session_role=?, conversation_index_kind=?,
                conversation_index_visibility=?, hidden_from_index=?, team_id=?,
                last_preview=?, last_preview_at_ms=?, recency_at_ms=?,
                updated_at_ms=?, archived_at_ms=NULL
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

    def list_directory_page(
        self,
        *,
        agent_id: str = "",
        session_kind: str = "",
        status: str = "",
        query: str = "",
        include_hidden: bool = False,
        matching_agent_ids: Sequence[str] = (),
        limit: int = 50,
        before: tuple[int, str] | None = None,
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
        if before is not None:
            where.append(
                "(recency_at_ms < ? OR (recency_at_ms = ? AND session_id < ?))"
            )
            parameters.extend((int(before[0]), int(before[0]), str(before[1])))
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
            ORDER BY recency_at_ms DESC, session_id DESC
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
            next_cursor = f"{last['recencyAtMs']}:{last['sessionId']}"
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
        if state == "projected":
            return _admission_row(row)
        incoming_sequence = int(journal_sequence)
        if incoming_sequence < 1:
            raise ValueError("Journal sequence must be positive.")
        current_sequence = row["journal_sequence"]
        if current_sequence is not None and incoming_sequence < int(current_sequence):
            return _admission_row(row)
        self._connection.execute(
            """
            UPDATE session_admissions
            SET state='journaled', journal_sequence=?, journal_event_id=?, updated_at_ms=?
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


class ConversationUnitOfWork:
    """One writer-thread transaction with explicit after-commit callbacks."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.agents = AgentDao(connection)
        self.sessions = SessionDao(connection)
        self.session_edges = SessionEdgeDao(connection)
        self.admissions = SessionAdmissionDao(connection)
        self.projection_offsets = SessionProjectionOffsetDao(connection)
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
        return self._writer.submit(lambda unit_of_work: unit_of_work.agents.create(**values))

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
        )

    def compare_and_swap_agent_config(self, **values: Any) -> Future[dict[str, Any]]:
        return self._writer.submit(
            lambda unit_of_work: unit_of_work.agents.compare_and_swap_config_snapshot(
                **values
            ),
            force_flush=True,
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

        return self._writer.submit(create_with_parent_edge, force_flush=True)

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

        return self._writer.submit(ensure_control_plane, force_flush=True)

    def link_sessions(self, **values: Any) -> Future[dict[str, Any]]:
        return self._writer.submit(
            lambda unit_of_work: unit_of_work.session_edges.link(**values),
            force_flush=True,
        )

    def reserve_submission_admission(self, **values: Any) -> Future[dict[str, Any]]:
        return self._writer.submit(
            lambda unit_of_work: unit_of_work.admissions.reserve(**values),
            force_flush=True,
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

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._database.reader() as connection:
            return SessionDao(connection).get(session_id)

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

        return self._writer.submit(upsert_with_parent_edge, force_flush=True)

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
