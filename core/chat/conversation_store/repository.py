"""DAO, repository, and unit-of-work boundaries for conversation storage."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Callable, Mapping
from concurrent.futures import Future
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .database import ConversationDatabase
    from .writer import ConversationWriter


_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "interrupted"}


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


class TurnDao:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def begin(
        self,
        *,
        turn_id: str,
        session_id: str,
        client_submission_id: str | None,
    ) -> dict[str, Any]:
        normalized_submission_id = str(client_submission_id or "").strip() or None
        if normalized_submission_id is not None:
            existing = self._connection.execute(
                """
                SELECT turn_id, sequence, status
                FROM turns
                WHERE session_id=? AND client_submission_id=?
                """,
                (session_id, normalized_submission_id),
            ).fetchone()
            if existing is not None:
                return {
                    "turnId": str(existing["turn_id"]),
                    "sequence": int(existing["sequence"]),
                    "status": str(existing["status"]),
                    "outcome": "reused",
                }
        now_ms = _now_ms()
        sequence_row = self._connection.execute(
            """
            UPDATE sessions
            SET next_turn_sequence=next_turn_sequence+1,
                recency_at_ms=?, updated_at_ms=?, status='running'
            WHERE session_id=? AND archived_at_ms IS NULL
            RETURNING next_turn_sequence
            """,
            (now_ms, now_ms, session_id),
        ).fetchone()
        if sequence_row is None:
            raise sqlite3.IntegrityError("session does not exist or is archived")
        sequence = int(sequence_row[0])
        self._connection.execute(
            """
            INSERT INTO turns(
              turn_id, session_id, client_submission_id, sequence,
              status, started_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, 'running', ?, ?)
            """,
            (
                turn_id,
                session_id,
                normalized_submission_id,
                sequence,
                now_ms,
                now_ms,
            ),
        )
        return {
            "turnId": turn_id,
            "sequence": sequence,
            "status": "running",
            "outcome": "inserted",
        }

    def list_for_session(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT turn_id, session_id, client_submission_id, sequence,
                   status, started_at_ms, completed_at_ms, updated_at_ms
            FROM turns WHERE session_id=? ORDER BY sequence ASC
            """,
            (session_id,),
        ).fetchall()
        return [
            {
                "turnId": str(row["turn_id"]),
                "sessionId": str(row["session_id"]),
                "clientSubmissionId": str(row["client_submission_id"] or ""),
                "sequence": int(row["sequence"]),
                "status": str(row["status"]),
                "startedAtMs": int(row["started_at_ms"]),
                "completedAtMs": (
                    int(row["completed_at_ms"])
                    if row["completed_at_ms"] is not None
                    else None
                ),
                "updatedAtMs": int(row["updated_at_ms"]),
            }
            for row in rows
        ]


class TurnItemDao:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def upsert(
        self,
        *,
        item_id: str,
        turn_id: str,
        call_id: str | None,
        revision: int,
        kind: str,
        status: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        incoming_revision = int(revision)
        if incoming_revision < 1:
            raise ValueError("turn item revision must be at least 1")
        existing = self._connection.execute(
            "SELECT sequence, revision, status FROM turn_items WHERE item_id=?",
            (item_id,),
        ).fetchone()
        if existing is not None:
            current_sequence = int(existing["sequence"])
            current_revision = int(existing["revision"])
            current_status = str(existing["status"])
            if incoming_revision <= current_revision:
                return {
                    "outcome": "stale",
                    "sequence": current_sequence,
                    "revision": current_revision,
                }
            if current_status in _TERMINAL_STATUSES and status not in _TERMINAL_STATUSES:
                return {
                    "outcome": "terminal",
                    "sequence": current_sequence,
                    "revision": current_revision,
                }
            self._connection.execute(
                """
                UPDATE turn_items
                SET call_id=?, revision=?, kind=?, status=?, payload_json=?, updated_at_ms=?
                WHERE item_id=?
                """,
                (
                    str(call_id or "").strip() or None,
                    incoming_revision,
                    kind,
                    status,
                    _canonical_json(payload),
                    _now_ms(),
                    item_id,
                ),
            )
            return {
                "outcome": "updated",
                "sequence": current_sequence,
                "revision": incoming_revision,
            }

        session_row = self._connection.execute(
            "SELECT session_id FROM turns WHERE turn_id=?",
            (turn_id,),
        ).fetchone()
        if session_row is None:
            raise sqlite3.IntegrityError("turn does not exist")
        sequence_row = self._connection.execute(
            """
            UPDATE sessions
            SET next_item_sequence=next_item_sequence+1, updated_at_ms=?
            WHERE session_id=?
            RETURNING next_item_sequence
            """,
            (_now_ms(), str(session_row[0])),
        ).fetchone()
        if sequence_row is None:
            raise sqlite3.IntegrityError("session does not exist")
        sequence = int(sequence_row[0])
        now_ms = _now_ms()
        self._connection.execute(
            """
            INSERT INTO turn_items(
              item_id, turn_id, call_id, sequence, revision,
              kind, status, payload_json, created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                turn_id,
                str(call_id or "").strip() or None,
                sequence,
                incoming_revision,
                kind,
                status,
                _canonical_json(payload),
                now_ms,
                now_ms,
            ),
        )
        return {
            "outcome": "inserted",
            "sequence": sequence,
            "revision": incoming_revision,
        }

    def list_for_turn(self, turn_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT item_id, turn_id, call_id, sequence, revision,
                   kind, status, payload_json, created_at_ms, updated_at_ms
            FROM turn_items WHERE turn_id=? ORDER BY sequence ASC
            """,
            (turn_id,),
        ).fetchall()
        return [
            {
                "itemId": str(row["item_id"]),
                "turnId": str(row["turn_id"]),
                "callId": str(row["call_id"] or ""),
                "sequence": int(row["sequence"]),
                "revision": int(row["revision"]),
                "kind": str(row["kind"]),
                "status": str(row["status"]),
                "payload": json.loads(str(row["payload_json"])),
                "createdAtMs": int(row["created_at_ms"]),
                "updatedAtMs": int(row["updated_at_ms"]),
            }
            for row in rows
        ]


class ConversationUnitOfWork:
    """One writer-thread transaction with explicit after-commit callbacks."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.agents = AgentDao(connection)
        self.sessions = SessionDao(connection)
        self.turns = TurnDao(connection)
        self.items = TurnItemDao(connection)
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

    def create_session(self, **values: Any) -> Future[dict[str, Any]]:
        return self._writer.submit(lambda unit_of_work: unit_of_work.sessions.create(**values))

    def begin_turn(self, **values: Any) -> Future[dict[str, Any]]:
        return self._writer.submit(lambda unit_of_work: unit_of_work.turns.begin(**values))

    def upsert_turn_item(self, **values: Any) -> Future[dict[str, Any]]:
        return self._writer.submit(lambda unit_of_work: unit_of_work.items.upsert(**values))

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        with self._database.reader() as connection:
            return AgentDao(connection).get(agent_id)

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

    def list_turns(self, session_id: str) -> list[dict[str, Any]]:
        with self._database.reader() as connection:
            return TurnDao(connection).list_for_session(session_id)

    def list_turn_items(self, turn_id: str) -> list[dict[str, Any]]:
        with self._database.reader() as connection:
            return TurnItemDao(connection).list_for_turn(turn_id)


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _now_ms() -> int:
    return int(time.time() * 1000)
