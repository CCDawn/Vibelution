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
    ) -> dict[str, Any]:
        now_ms = _now_ms()
        self._connection.execute(
            """
            INSERT INTO sessions(
              session_id, agent_id, parent_session_id,
              agent_config_revision_id, title, status,
              recency_at_ms, updated_at_ms, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, 'ready', ?, ?, ?)
            """,
            (
                session_id,
                agent_id,
                parent_session_id or None,
                agent_config_revision_id,
                title,
                now_ms,
                now_ms,
                now_ms,
            ),
        )
        return {"sessionId": session_id, "agentId": agent_id}

    def get(self, session_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            """
            SELECT session_id, agent_id, parent_session_id,
                   agent_config_revision_id, title, status,
                   recency_at_ms, updated_at_ms, created_at_ms, archived_at_ms
            FROM sessions
            WHERE session_id=? AND archived_at_ms IS NULL
            """,
            (session_id,),
        ).fetchone()
        if row is None:
            return None
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
        }

    def list_for_agent(
        self,
        agent_id: str,
        *,
        limit: int = 50,
        before: tuple[int, str] | None = None,
    ) -> list[dict[str, Any]]:
        bounded_limit = min(200, max(1, int(limit)))
        parameters: list[Any] = [agent_id]
        cursor_clause = ""
        if before is not None:
            cursor_clause = (
                "AND (recency_at_ms < ? OR "
                "(recency_at_ms = ? AND session_id < ?))"
            )
            parameters.extend((int(before[0]), int(before[0]), str(before[1])))
        parameters.append(bounded_limit)
        rows = self._connection.execute(
            f"""
            SELECT session_id, agent_id, parent_session_id,
                   agent_config_revision_id, title, status,
                   recency_at_ms, updated_at_ms, created_at_ms, archived_at_ms
            FROM sessions
            WHERE agent_id=? AND archived_at_ms IS NULL {cursor_clause}
            ORDER BY recency_at_ms DESC, session_id DESC
            LIMIT ?
            """,
            parameters,
        ).fetchall()
        return [
            {
                "sessionId": str(row["session_id"]),
                "agentId": str(row["agent_id"]),
                "parentSessionId": str(row["parent_session_id"] or ""),
                "agentConfigRevisionId": str(row["agent_config_revision_id"]),
                "title": str(row["title"]),
                "status": str(row["status"]),
                "recencyAtMs": int(row["recency_at_ms"]),
                "updatedAtMs": int(row["updated_at_ms"]),
                "createdAtMs": int(row["created_at_ms"]),
            }
            for row in rows
        ]


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
