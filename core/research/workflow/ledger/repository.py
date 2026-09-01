"""Workflow Ledger repository — SQL only, no domain calls, no network/IO.

Every mutation runs inside a caller-provided transaction (the unit of work).
Status strings are validated by callers through core.research.workflow
transitions before reaching SQL; this module never accepts arbitrary statuses
for domain objects (guarded by transition functions used in service layer).
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from .records import (
    CatalogRunAuthorization,
    CommandRecord,
    EventRecord,
    NodeAttemptRecord,
    OutboxRecord,
    RunRecord,
)

# An action whose worker process dies (or whose lease keeps expiring) never
# reaches the workers' transient-exhaustion branch, so the ledger itself must
# stop re-leasing it. Higher than the workers' transient threshold (5), which
# only covers errors raised inside the worker loop.
MAX_OUTBOX_LEASE_ATTEMPTS = 12

# Sentinel for "leave this nullable column unchanged" in partial updates.
_UNSET = object()

_KNOWLEDGE_INVOCATION_COLUMNS = (
    "invocation_id",
    "parent_run_id",
    "parent_node_id",
    "parent_node_run_id",
    "parent_attempt",
    "question_id",
    "scope_hash",
    "request_hash",
    "search_envelope_hash",
    "requirements_hash",
    "source_policy_version",
    "knowledge_child_run_id",
    "status",
    "knowledge_package_ref",
    "package_content_hash",
    "handoff_state",
    "error_json",
    "created_at_ms",
    "updated_at_ms",
)


def _row_knowledge_invocation(row: Any) -> Any | None:
    if row is None:
        return None
    from .records import KnowledgeInvocationRecord

    data = dict(zip(_KNOWLEDGE_INVOCATION_COLUMNS, row, strict=True))
    return KnowledgeInvocationRecord(
        invocation_id=str(data["invocation_id"]),
        parent_run_id=str(data["parent_run_id"]),
        parent_node_id=str(data["parent_node_id"]),
        parent_node_run_id=str(data["parent_node_run_id"]),
        parent_attempt=int(data["parent_attempt"]),
        question_id=str(data["question_id"]),
        scope_hash=str(data["scope_hash"]),
        request_hash=str(data["request_hash"]),
        search_envelope_hash=str(data["search_envelope_hash"]),
        requirements_hash=str(data["requirements_hash"]),
        source_policy_version=str(data["source_policy_version"]),
        knowledge_child_run_id=data["knowledge_child_run_id"],
        status=str(data["status"]),
        knowledge_package_ref=data["knowledge_package_ref"],
        package_content_hash=data["package_content_hash"],
        handoff_state=str(data["handoff_state"]),
        error_json=data["error_json"],
        created_at_ms=int(data["created_at_ms"]),
        updated_at_ms=int(data["updated_at_ms"]),
    )


def _row_run(row: Any) -> RunRecord | None:
    if row is None:
        return None
    return RunRecord(
        run_id=str(row[0]),
        team_id=str(row[1]),
        workflow_id=str(row[2]),
        workflow_version_id=str(row[3]),
        thread_id=str(row[4]),
        project_id=str(row[5]),
        question_id=str(row[6]),
        status=str(row[7]),
        run_version=int(row[8]),
        last_event_sequence=int(row[9]),
        input_snapshot_json=str(row[10]),
        input_snapshot_hash=str(row[11]),
        safety_limits_json=str(row[12]),
        binding_snapshot_set_id=str(row[13]),
        active_node_id=row[14],
        parent_run_id=row[15],
        forked_from_checkpoint_id=row[16],
        completion_kind=row[17],
        terminal_reason=row[18],
        blocked_problem_json=row[19],
        created_at_ms=int(row[20]),
        updated_at_ms=int(row[21]),
        completed_at_ms=row[22],
        structure_hash=str(row[23] or ""),
    )


def _row_event(row: Any) -> EventRecord | None:
    if row is None:
        return None
    return EventRecord(
        run_id=str(row[0]),
        sequence=int(row[1]),
        event_id=str(row[2]),
        run_version=int(row[3]),
        event_type=str(row[4]),
        actor_json=str(row[5]),
        correlation_id=str(row[6]),
        causation_id=row[7],
        payload_json=str(row[8]),
        occurred_at_ms=int(row[9]),
    )


def _row_catalog_run_authorization(row: Any) -> CatalogRunAuthorization | None:
    if row is None:
        return None
    return CatalogRunAuthorization(
        authorization_id=str(row[0]),
        team_id=str(row[1]),
        plan_id=str(row[2]),
        batch_scope_json=str(row[3]),
        scope_hash=str(row[4]),
        approved_by=str(row[5]),
        approved_at_ms=int(row[6]),
        readiness_report_sha256=str(row[7]),
        record_hash=str(row[8]),
        created_at_ms=int(row[9]),
    )


class WorkflowLedgerRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def execute(self, sql: str, params: tuple = ()) -> Any:
        return self.connection.execute(sql, params)

    def affected(self) -> int:
        row = self.execute('SELECT changes()').fetchone()
        return int(row[0]) if row else 0

    # ---------------------------------------------------------------- runs

    def insert_run(self, run: RunRecord) -> None:
        self.execute(
            """
            INSERT INTO workflow_runs (
              run_id, team_id, workflow_id, workflow_version_id, thread_id,
              project_id, question_id, status, run_version, last_event_sequence,
              input_snapshot_json, input_snapshot_hash, safety_limits_json,
              binding_snapshot_set_id, active_node_id, parent_run_id,
              forked_from_checkpoint_id, completion_kind, terminal_reason,
              blocked_problem_json, created_at_ms, updated_at_ms, completed_at_ms,
              structure_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.run_id,
                run.team_id,
                run.workflow_id,
                run.workflow_version_id,
                run.thread_id,
                run.project_id,
                run.question_id,
                run.status,
                run.run_version,
                run.last_event_sequence,
                run.input_snapshot_json,
                run.input_snapshot_hash,
                run.safety_limits_json,
                run.binding_snapshot_set_id,
                run.active_node_id,
                run.parent_run_id,
                run.forked_from_checkpoint_id,
                run.completion_kind,
                run.terminal_reason,
                run.blocked_problem_json,
                run.created_at_ms,
                run.updated_at_ms,
                run.completed_at_ms,
                run.structure_hash,
            ),
        )

    def get_run(self, run_id: str) -> RunRecord | None:
        row = self.execute(
            """
            SELECT run_id, team_id, workflow_id, workflow_version_id, thread_id,
                   project_id, question_id, status, run_version, last_event_sequence,
                   input_snapshot_json, input_snapshot_hash, safety_limits_json,
                   binding_snapshot_set_id, active_node_id, parent_run_id,
                   forked_from_checkpoint_id, completion_kind, terminal_reason,
                   blocked_problem_json, created_at_ms, updated_at_ms, completed_at_ms,
                   structure_hash
            FROM workflow_runs WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        return _row_run(row)

    def bump_run_version(
        self,
        run_id: str,
        team_id: str,
        expected_version: int,
        event_count: int,
        now_ms: int,
    ) -> tuple[int, int] | None:
        """Conditional version + sequence bump; returns (new_version, last_sequence)."""
        row = self.execute(
            """
            UPDATE workflow_runs
            SET run_version = run_version + 1,
                last_event_sequence = last_event_sequence + :event_count,
                updated_at_ms = :now
            WHERE run_id = :run_id
              AND team_id = :team_id
              AND run_version = :expected_version
            RETURNING run_version, last_event_sequence
            """,
            {
                "event_count": event_count,
                "now": now_ms,
                "run_id": run_id,
                "team_id": team_id,
                "expected_version": expected_version,
            },
        ).fetchone()
        if row is None:
            return None
        return int(row[0]), int(row[1])

    def advance_last_sequence(self, run_id: str, count: int, now_ms: int) -> int | None:
        """Worker-side sequence advancement without a runVersion bump."""
        row = self.execute(
            """
            UPDATE workflow_runs
            SET last_event_sequence = last_event_sequence + ?, updated_at_ms = ?
            WHERE run_id = ?
            RETURNING last_event_sequence
            """,
            (count, now_ms, run_id),
        ).fetchone()
        if row is None:
            return None
        return int(row[0])

    def update_run_status(
        self,
        run_id: str,
        team_id: str,
        status: str,
        now_ms: int,
        *,
        active_node_id: str | None = None,
        completion_kind: str | None = None,
        terminal_reason: str | None = None,
        blocked_problem_json: str | None = None,
    ) -> bool:
        self._require_run_transition(run_id, status)
        cursor = self.execute(
            """
            UPDATE workflow_runs
            SET status = :status,
                active_node_id = COALESCE(:active_node_id, active_node_id),
                completion_kind = :completion_kind,
                terminal_reason = :terminal_reason,
                blocked_problem_json = :blocked_problem_json,
                completed_at_ms = CASE WHEN :terminal = 1 THEN :now ELSE completed_at_ms END,
                updated_at_ms = :now
            WHERE run_id = :run_id AND team_id = :team_id
            """,
            {
                "status": status,
                "active_node_id": active_node_id,
                "completion_kind": completion_kind,
                "terminal_reason": terminal_reason,
                "blocked_problem_json": blocked_problem_json,
                "terminal": 1 if status in ("succeeded", "failed", "cancelled", "archived") else 0,
                "now": now_ms,
                "run_id": run_id,
                "team_id": team_id,
            },
        )
        return self.affected() > 0

    def list_runs_for_team(self, team_id: str, workflow_id: str) -> list[RunRecord]:
        rows = self.execute(
            """
            SELECT run_id, team_id, workflow_id, workflow_version_id, thread_id,
                   project_id, question_id, status, run_version, last_event_sequence,
                   input_snapshot_json, input_snapshot_hash, safety_limits_json,
                   binding_snapshot_set_id, active_node_id, parent_run_id,
                   forked_from_checkpoint_id, completion_kind, terminal_reason,
                   blocked_problem_json, created_at_ms, updated_at_ms, completed_at_ms,
                   structure_hash
            FROM workflow_runs
            WHERE team_id = ? AND workflow_id = ?
            ORDER BY created_at_ms DESC, run_id DESC
            """,
            (team_id, workflow_id),
        ).fetchall()
        return [record for row in rows if (record := _row_run(row)) is not None]

    # --------------------------------------------- catalog authorization

    def insert_catalog_run_authorization(
        self, authorization: CatalogRunAuthorization
    ) -> None:
        """Insert one immutable approval record.

        The scoped uniqueness constraint makes retries safe at the database
        boundary.  Domain callers should read the existing row when the same
        scope/readiness pair has already been approved.
        """
        self.execute(
            """
            INSERT INTO catalog_run_authorizations (
              authorization_id, team_id, plan_id, batch_scope_json, scope_hash,
              approved_by, approved_at_ms, readiness_report_sha256, record_hash,
              created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (team_id, plan_id, scope_hash, readiness_report_sha256)
            DO NOTHING
            """,
            (
                authorization.authorization_id,
                authorization.team_id,
                authorization.plan_id,
                authorization.batch_scope_json,
                authorization.scope_hash,
                authorization.approved_by,
                authorization.approved_at_ms,
                authorization.readiness_report_sha256,
                authorization.record_hash,
                authorization.created_at_ms,
            ),
        )

    def get_catalog_run_authorization(
        self, authorization_id: str
    ) -> CatalogRunAuthorization | None:
        row = self.execute(
            """
            SELECT authorization_id, team_id, plan_id, batch_scope_json, scope_hash,
                   approved_by, approved_at_ms, readiness_report_sha256, record_hash,
                   created_at_ms
            FROM catalog_run_authorizations
            WHERE authorization_id = ?
            """,
            (authorization_id,),
        ).fetchone()
        return _row_catalog_run_authorization(row)

    def find_catalog_run_authorization(
        self,
        *,
        team_id: str,
        plan_id: str,
        scope_hash: str,
        readiness_report_sha256: str,
    ) -> CatalogRunAuthorization | None:
        row = self.execute(
            """
            SELECT authorization_id, team_id, plan_id, batch_scope_json, scope_hash,
                   approved_by, approved_at_ms, readiness_report_sha256, record_hash,
                   created_at_ms
            FROM catalog_run_authorizations
            WHERE team_id = ?
              AND plan_id = ?
              AND scope_hash = ?
              AND readiness_report_sha256 = ?
            ORDER BY approved_at_ms DESC, authorization_id DESC
            LIMIT 1
            """,
            (team_id, plan_id, scope_hash, readiness_report_sha256),
        ).fetchone()
        return _row_catalog_run_authorization(row)

    def list_catalog_run_authorizations(
        self, team_id: str, plan_id: str | None = None
    ) -> list[CatalogRunAuthorization]:
        params: tuple[Any, ...]
        if plan_id is None:
            sql = """
                SELECT authorization_id, team_id, plan_id, batch_scope_json, scope_hash,
                       approved_by, approved_at_ms, readiness_report_sha256, record_hash,
                       created_at_ms
                FROM catalog_run_authorizations
                WHERE team_id = ?
                ORDER BY approved_at_ms DESC, authorization_id DESC
            """
            params = (team_id,)
        else:
            sql = """
                SELECT authorization_id, team_id, plan_id, batch_scope_json, scope_hash,
                       approved_by, approved_at_ms, readiness_report_sha256, record_hash,
                       created_at_ms
                FROM catalog_run_authorizations
                WHERE team_id = ? AND plan_id = ?
                ORDER BY approved_at_ms DESC, authorization_id DESC
            """
            params = (team_id, plan_id)
        rows = self.execute(sql, params).fetchall()
        return [
            record
            for row in rows
            if (record := _row_catalog_run_authorization(row)) is not None
        ]

    def update_run_safety_limits(
        self, run_id: str, team_id: str, safety_limits_json: str, now_ms: int
    ) -> bool:
        cursor = self.execute(
            """
            UPDATE workflow_runs
            SET safety_limits_json = ?, updated_at_ms = ?
            WHERE run_id = ? AND team_id = ?
            """,
            (safety_limits_json, now_ms, run_id, team_id),
        )
        return self.affected() > 0

    def update_run_binding_set(
        self, run_id: str, team_id: str, binding_snapshot_set_id: str, now_ms: int
    ) -> bool:
        cursor = self.execute(
            """
            UPDATE workflow_runs
            SET binding_snapshot_set_id = ?, updated_at_ms = ?
            WHERE run_id = ? AND team_id = ?
            """,
            (binding_snapshot_set_id, now_ms, run_id, team_id),
        )
        return self.affected() > 0

    # ------------------------------------------------------------ commands

    def insert_command(self, command: CommandRecord) -> None:
        self.execute(
            """
            INSERT INTO workflow_commands (
              command_id, run_id, team_id, node_id, command_kind,
              expected_run_version, accepted_run_version, idempotency_key,
              request_hash, request_json, requested_by_json, status,
              result_json, problem_json, created_at_ms, completed_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                command.command_id,
                command.run_id,
                command.team_id,
                command.node_id,
                command.command_kind,
                command.expected_run_version,
                command.accepted_run_version,
                command.idempotency_key,
                command.request_hash,
                command.request_json,
                command.requested_by_json,
                command.status,
                command.result_json,
                command.problem_json,
                command.created_at_ms,
                command.completed_at_ms,
            ),
        )

    def find_command_by_idempotency(self, run_id: str, idempotency_key: str) -> CommandRecord | None:
        row = self.execute(
            """
            SELECT command_id, run_id, team_id, node_id, command_kind,
                   expected_run_version, accepted_run_version, idempotency_key,
                   request_hash, request_json, requested_by_json, status,
                   result_json, problem_json, created_at_ms, completed_at_ms
            FROM workflow_commands
            WHERE run_id = ? AND idempotency_key = ?
            """,
            (run_id, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        return CommandRecord(
            command_id=str(row[0]),
            run_id=str(row[1]),
            team_id=str(row[2]),
            node_id=row[3],
            command_kind=str(row[4]),
            expected_run_version=int(row[5]),
            accepted_run_version=row[6],
            idempotency_key=str(row[7]),
            request_hash=str(row[8]),
            request_json=str(row[9]),
            requested_by_json=str(row[10]),
            status=str(row[11]),
            result_json=row[12],
            problem_json=row[13],
            created_at_ms=int(row[14]),
            completed_at_ms=row[15],
        )

    def get_command(self, command_id: str) -> CommandRecord | None:
        row = self.execute(
            """
            SELECT command_id, run_id, team_id, node_id, command_kind,
                   expected_run_version, accepted_run_version, idempotency_key,
                   request_hash, request_json, requested_by_json, status,
                   result_json, problem_json, created_at_ms, completed_at_ms
            FROM workflow_commands WHERE command_id = ?
            """,
            (command_id,),
        ).fetchone()
        if row is None:
            return None
        return CommandRecord(
            command_id=str(row[0]),
            run_id=str(row[1]),
            team_id=str(row[2]),
            node_id=row[3],
            command_kind=str(row[4]),
            expected_run_version=int(row[5]),
            accepted_run_version=row[6],
            idempotency_key=str(row[7]),
            request_hash=str(row[8]),
            request_json=str(row[9]),
            requested_by_json=str(row[10]),
            status=str(row[11]),
            result_json=row[12],
            problem_json=row[13],
            created_at_ms=int(row[14]),
            completed_at_ms=row[15],
        )

    def complete_command(
        self,
        command_id: str,
        status: str,
        now_ms: int,
        *,
        result_json: str | None = None,
        problem_json: str | None = None,
    ) -> bool:
        cursor = self.execute(
            """
            UPDATE workflow_commands
            SET status = ?, result_json = COALESCE(?, result_json),
                problem_json = COALESCE(?, problem_json),
                completed_at_ms = ?
            WHERE command_id = ?
            """,
            (status, result_json, problem_json, now_ms, command_id),
        )
        return self.affected() > 0

    # ------------------------------------------------------------ attempts

    def insert_attempt(self, attempt: NodeAttemptRecord) -> None:
        self.execute(
            """
            INSERT INTO node_attempts (
              node_run_id, run_id, node_id, attempt, actor_kind, status,
              command_id, binding_snapshot_id, input_snapshot_hash,
              pending_action_id, execution_anchor_id, retry_of_node_run_id,
              problem_json, started_at_ms, updated_at_ms, finished_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt.node_run_id,
                attempt.run_id,
                attempt.node_id,
                attempt.attempt,
                attempt.actor_kind,
                attempt.status,
                attempt.command_id,
                attempt.binding_snapshot_id,
                attempt.input_snapshot_hash,
                attempt.pending_action_id,
                attempt.execution_anchor_id,
                attempt.retry_of_node_run_id,
                attempt.problem_json,
                attempt.started_at_ms,
                attempt.updated_at_ms,
                attempt.finished_at_ms,
            ),
        )

    def get_attempt(self, node_run_id: str) -> NodeAttemptRecord | None:
        row = self.execute(
            """
            SELECT node_run_id, run_id, node_id, attempt, actor_kind, status,
                   command_id, binding_snapshot_id, input_snapshot_hash,
                   pending_action_id, execution_anchor_id, retry_of_node_run_id,
                   problem_json, started_at_ms, updated_at_ms, finished_at_ms
            FROM node_attempts WHERE node_run_id = ?
            """,
            (node_run_id,),
        ).fetchone()
        return self._row_attempt(row)

    def latest_attempt(self, run_id: str, node_id: str) -> NodeAttemptRecord | None:
        row = self.execute(
            """
            SELECT node_run_id, run_id, node_id, attempt, actor_kind, status,
                   command_id, binding_snapshot_id, input_snapshot_hash,
                   pending_action_id, execution_anchor_id, retry_of_node_run_id,
                   problem_json, started_at_ms, updated_at_ms, finished_at_ms
            FROM node_attempts
            WHERE run_id = ? AND node_id = ?
            ORDER BY attempt DESC LIMIT 1
            """,
            (run_id, node_id),
        ).fetchone()
        return self._row_attempt(row)

    def list_attempts(self, run_id: str) -> list[NodeAttemptRecord]:
        rows = self.execute(
            """
            SELECT node_run_id, run_id, node_id, attempt, actor_kind, status,
                   command_id, binding_snapshot_id, input_snapshot_hash,
                   pending_action_id, execution_anchor_id, retry_of_node_run_id,
                   problem_json, started_at_ms, updated_at_ms, finished_at_ms
            FROM node_attempts
            WHERE run_id = ?
            ORDER BY attempt, node_id
            """,
            (run_id,),
        ).fetchall()
        return [record for row in rows if (record := self._row_attempt(row)) is not None]

    def update_attempt_status(
        self,
        node_run_id: str,
        status: str,
        now_ms: int,
        *,
        pending_action_id: str | None = None,
        execution_anchor_id: str | None = None,
        problem_json: str | None = None,
        finished_at_ms: int | None = None,
    ) -> bool:
        self._require_attempt_transition(node_run_id, status)
        cursor = self.execute(
            """
            UPDATE node_attempts
            SET status = ?,
                pending_action_id = COALESCE(?, pending_action_id),
                execution_anchor_id = COALESCE(?, execution_anchor_id),
                problem_json = COALESCE(?, problem_json),
                finished_at_ms = CASE WHEN ? IS NOT NULL THEN ? ELSE finished_at_ms END,
                updated_at_ms = ?
            WHERE node_run_id = ?
            """,
            (
                status,
                pending_action_id,
                execution_anchor_id,
                problem_json,
                finished_at_ms,
                finished_at_ms,
                now_ms,
                node_run_id,
            ),
        )
        return self.affected() > 0

    @staticmethod
    def _row_attempt(row: Any) -> NodeAttemptRecord | None:
        if row is None:
            return None
        return NodeAttemptRecord(
            node_run_id=str(row[0]),
            run_id=str(row[1]),
            node_id=str(row[2]),
            attempt=int(row[3]),
            actor_kind=str(row[4]),
            status=str(row[5]),
            command_id=str(row[6]),
            binding_snapshot_id=row[7],
            input_snapshot_hash=str(row[8]),
            pending_action_id=row[9],
            execution_anchor_id=row[10],
            retry_of_node_run_id=row[11],
            problem_json=row[12],
            started_at_ms=int(row[13]),
            updated_at_ms=int(row[14]),
            finished_at_ms=row[15],
        )

    # ------------------------------------------------------------- events

    def insert_event(self, event: EventRecord) -> None:
        self.execute(
            """
            INSERT INTO workflow_events (
              run_id, sequence, event_id, run_version, event_type, actor_json,
              correlation_id, causation_id, payload_json, occurred_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.run_id,
                event.sequence,
                event.event_id,
                event.run_version,
                event.event_type,
                event.actor_json,
                event.correlation_id,
                event.causation_id,
                event.payload_json,
                event.occurred_at_ms,
            ),
        )

    def event_exists(self, event_id: str) -> bool:
        return self.get_event_by_id(event_id) is not None

    def get_event_by_id(self, event_id: str) -> EventRecord | None:
        row = self.execute(
            """
            SELECT run_id, sequence, event_id, run_version, event_type, actor_json,
                   correlation_id, causation_id, payload_json, occurred_at_ms
            FROM workflow_events WHERE event_id = ? LIMIT 1
            """,
            (event_id,),
        ).fetchone()
        return _row_event(row)

    def list_events(self, run_id: str, after_sequence: int = 0, limit: int = 500) -> list[EventRecord]:
        rows = self.execute(
            """
            SELECT run_id, sequence, event_id, run_version, event_type, actor_json,
                   correlation_id, causation_id, payload_json, occurred_at_ms
            FROM workflow_events
            WHERE run_id = ? AND sequence > ?
            ORDER BY sequence ASC LIMIT ?
            """,
            (run_id, after_sequence, limit),
        ).fetchall()
        return [_row_event(row) for row in rows if row is not None]

    def list_knowledge_delivery_event_payloads(self, run_id: str) -> list[str]:
        rows = self.execute(
            """
            SELECT payload_json
            FROM workflow_events
            WHERE run_id = ?
              AND event_type IN (
                'knowledge_result_absorbed',
                'knowledge_invocation_reused'
              )
            ORDER BY sequence ASC
            """,
            (run_id,),
        ).fetchall()
        return [str(row[0] or "") for row in rows]

    def latest_event_sequence(self, run_id: str) -> int:
        row = self.execute(
            "SELECT COALESCE(MAX(sequence), 0) FROM workflow_events WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return int(row[0]) if row else 0

    # ------------------------------------------------------------- outbox

    def insert_outbox(self, outbox: OutboxRecord) -> None:
        self.execute(
            """
            INSERT INTO outbox_actions (
              action_id, run_id, command_id, node_run_id, action_kind,
              idempotency_key, payload_json, status, attempt_count,
              available_at_ms, lease_owner, lease_expires_at_ms,
              last_problem_json, created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                outbox.action_id,
                outbox.run_id,
                outbox.command_id,
                outbox.node_run_id,
                outbox.action_kind,
                outbox.idempotency_key,
                outbox.payload_json,
                outbox.status,
                outbox.attempt_count,
                outbox.available_at_ms,
                outbox.lease_owner,
                outbox.lease_expires_at_ms,
                outbox.last_problem_json,
                outbox.created_at_ms,
                outbox.updated_at_ms,
            ),
        )

    def lease_outbox_actions(
        self,
        *,
        owner: str,
        now_ms: int,
        limit: int = 8,
        lease_ms: int = 30_000,
        action_kinds: tuple[str, ...] | None = None,
        idempotency_prefix: str | None = None,
        background_workflow_ids: tuple[str, ...] | None = None,
        background_limit: int | None = None,
        max_attempts: int = MAX_OUTBOX_LEASE_ATTEMPTS,
    ) -> list[OutboxRecord]:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if background_limit is not None and background_limit < 0:
            raise ValueError("background_limit must be >= 0")
        self._fail_leases_over_attempt_gate(
            now_ms=now_ms,
            max_attempts=max_attempts,
            action_kinds=action_kinds,
            idempotency_prefix=idempotency_prefix,
        )
        kind_filter = ""
        params: list[Any] = [now_ms]
        if action_kinds:
            placeholders = ",".join("?" for _ in action_kinds)
            kind_filter = f"AND action_kind IN ({placeholders})"
            params.extend(action_kinds)
        if idempotency_prefix:
            # ``LIKE`` treats ``_`` and ``%`` in the caller prefix as
            # wildcards.  Use a length-bounded substring comparison so lease
            # ownership remains literal even for namespaced keys such as
            # ``cancel_run_cleanup:``.
            kind_filter += " AND SUBSTR(idempotency_key, 1, ?) = ?"
            params.extend([len(idempotency_prefix), idempotency_prefix])
        normalized_background = tuple(
            str(item).strip()
            for item in (background_workflow_ids or ())
            if str(item).strip()
        )
        background_order = ""
        fetch_limit = limit
        params.append(now_ms)
        if normalized_background:
            placeholders = ",".join("?" for _ in normalized_background)
            background_order = (
                f"CASE WHEN r.workflow_id IN ({placeholders}) THEN 1 ELSE 0 END,"
            )
            params.extend(normalized_background)
            if background_limit is not None:
                fetch_limit = limit + max(0, int(background_limit))
        params.append(fetch_limit)
        rows = self.execute(
            f"""
            SELECT o.action_id, o.run_id, o.command_id, o.node_run_id, o.action_kind,
                   o.idempotency_key, o.payload_json, o.status, o.attempt_count,
                   o.available_at_ms, o.lease_owner, o.lease_expires_at_ms,
                   o.last_problem_json, o.created_at_ms, o.updated_at_ms,
                   r.workflow_id
            FROM outbox_actions o
            JOIN workflow_runs r ON r.run_id = o.run_id
            WHERE o.status IN ('pending', 'leased')
              AND o.available_at_ms <= ?
              {kind_filter}
              AND (o.lease_expires_at_ms IS NULL OR o.lease_expires_at_ms <= ?)
            ORDER BY {background_order} o.available_at_ms ASC, o.action_id ASC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
        background_remaining: int | None = None
        if normalized_background and background_limit is not None:
            placeholders = ",".join("?" for _ in normalized_background)
            active_background = self.execute(
                f"""
                SELECT COUNT(*)
                FROM outbox_actions o
                JOIN workflow_runs r ON r.run_id = o.run_id
                WHERE o.status = 'leased'
                  AND o.lease_expires_at_ms IS NOT NULL
                  AND o.lease_expires_at_ms > ?
                  AND o.action_kind IN ('graph_dispatch', 'adapter_dispatch')
                  AND r.workflow_id IN ({placeholders})
                """,
                (now_ms, *normalized_background),
            ).fetchone()
            background_remaining = max(
                0,
                int(background_limit) - int(active_background[0] if active_background else 0),
            )
        leased: list[OutboxRecord] = []
        for row in rows:
            if len(leased) >= limit:
                break
            is_background = str(row[15] or "") in normalized_background
            if is_background and background_remaining is not None:
                if background_remaining <= 0:
                    continue
                background_remaining -= 1
            action_id = str(row[0])
            updated = self.execute(
                """
                UPDATE outbox_actions
                SET status = 'leased', lease_owner = ?, lease_expires_at_ms = ?,
                    attempt_count = attempt_count + 1, updated_at_ms = ?
                WHERE action_id = ? AND status IN ('pending', 'leased')
                  AND (lease_expires_at_ms IS NULL OR lease_expires_at_ms <= ?)
                """,
                (owner, now_ms + lease_ms, now_ms, action_id, now_ms),
            )
            if self.affected() != 1:
                continue
            record = self._row_outbox(row)
            if record is None:
                continue
            leased.append(
                replace(
                    record,
                    status="leased",
                    attempt_count=record.attempt_count + 1,
                    lease_owner=owner,
                    lease_expires_at_ms=now_ms + lease_ms,
                    updated_at_ms=now_ms,
                )
            )
        return leased

    def _fail_leases_over_attempt_gate(
        self,
        *,
        now_ms: int,
        max_attempts: int,
        action_kinds: tuple[str, ...] | None,
        idempotency_prefix: str | None,
    ) -> None:
        """Sweep actions at/over the lease-attempt gate to terminal failed in
        the caller's unit of work. Scope and eligibility mirror the lease scan;
        conditioning on the non-terminal statuses makes the failure marker land
        exactly once per action even under competing sweeps."""
        problem_json = json.dumps(
            {"code": "lease_attempt_exhausted", "maxLeaseAttempts": int(max_attempts)}
        )
        params: list[Any] = [problem_json, now_ms, max_attempts, now_ms]
        kind_filter = ""
        if action_kinds:
            placeholders = ",".join("?" for _ in action_kinds)
            kind_filter = f"AND action_kind IN ({placeholders})"
            params.extend(action_kinds)
        if idempotency_prefix:
            kind_filter += " AND SUBSTR(idempotency_key, 1, ?) = ?"
            params.extend([len(idempotency_prefix), idempotency_prefix])
        params.append(now_ms)
        self.execute(
            f"""
            UPDATE outbox_actions
            SET status = 'failed', lease_owner = NULL, lease_expires_at_ms = NULL,
                last_problem_json = ?, updated_at_ms = ?
            WHERE status IN ('pending', 'leased')
              AND attempt_count >= ?
              AND available_at_ms <= ?
              {kind_filter}
              AND (lease_expires_at_ms IS NULL OR lease_expires_at_ms <= ?)
            """,
            tuple(params),
        )

    def get_outbox(self, action_id: str) -> OutboxRecord | None:
        row = self.execute(
            """
            SELECT action_id, run_id, command_id, node_run_id, action_kind,
                   idempotency_key, payload_json, status, attempt_count,
                   available_at_ms, lease_owner, lease_expires_at_ms,
                   last_problem_json, created_at_ms, updated_at_ms
            FROM outbox_actions WHERE action_id = ?
            """,
            (action_id,),
        ).fetchone()
        return self._row_outbox(row)

    def ack_outbox(
        self,
        action_id: str,
        owner: str,
        now_ms: int,
        *,
        status: str = "succeeded",
        problem_json: str | None = None,
    ) -> bool:
        cursor = self.execute(
            """
            UPDATE outbox_actions
            SET status = ?, lease_owner = NULL, lease_expires_at_ms = NULL,
                last_problem_json = COALESCE(?, last_problem_json),
                updated_at_ms = ?
            WHERE action_id = ? AND status = 'leased' AND lease_owner = ?
              AND lease_expires_at_ms > ?
            """,
            (status, problem_json, now_ms, action_id, owner, now_ms),
        )
        return self.affected() > 0

    def renew_outbox_lease(
        self,
        action_id: str,
        owner: str,
        now_ms: int,
        lease_ms: int,
    ) -> bool:
        """Extend a live lease only while its current owner still holds it."""

        self.execute(
            """
            UPDATE outbox_actions
            SET lease_expires_at_ms = ?, updated_at_ms = ?
            WHERE action_id = ? AND status = 'leased' AND lease_owner = ?
              AND lease_expires_at_ms IS NOT NULL
              AND lease_expires_at_ms > ?
            """,
            (now_ms + lease_ms, now_ms, action_id, owner, now_ms),
        )
        return self.affected() > 0

    def requeue_outbox(
        self,
        action_id: str,
        owner: str,
        now_ms: int,
        *,
        retry_at_ms: int,
        problem_json: str,
        reset_attempts: bool = False,
    ) -> bool:
        cursor = self.execute(
            """
            UPDATE outbox_actions
            SET status = 'pending', lease_owner = NULL, lease_expires_at_ms = NULL,
                available_at_ms = ?, last_problem_json = ?, updated_at_ms = ?,
                attempt_count = CASE WHEN ? THEN 0 ELSE attempt_count END
            WHERE action_id = ? AND status = 'leased' AND lease_owner = ?
              AND lease_expires_at_ms > ?
            """,
            (retry_at_ms, problem_json, now_ms, 1 if reset_attempts else 0, action_id, owner, now_ms),
        )
        return self.affected() > 0

    def fail_outbox(self, action_id: str, owner: str, now_ms: int, problem_json: str) -> bool:
        cursor = self.execute(
            """
            UPDATE outbox_actions
            SET status = 'failed', lease_owner = NULL, lease_expires_at_ms = NULL,
                last_problem_json = ?, updated_at_ms = ?
            WHERE action_id = ? AND status = 'leased' AND lease_owner = ?
              AND lease_expires_at_ms > ?
            """,
            (problem_json, now_ms, action_id, owner, now_ms),
        )
        return self.affected() > 0

    def cancel_outbox_by_node_run(self, node_run_id: str, now_ms: int) -> int:
        """Cancel pending adapter/graph outbox for a node run whose attempt is
        already terminal (a retry supersedes it and must not run twice)."""
        cursor = self.execute(
            """
            UPDATE outbox_actions
            SET status = 'cancelled', lease_owner = NULL, lease_expires_at_ms = NULL,
                updated_at_ms = ?
            WHERE node_run_id = ? AND status IN ('pending', 'leased')
            """,
            (now_ms, node_run_id),
        )
        return self.affected()

    def list_pending_outbox(self, run_id: str | None = None, limit: int = 200) -> list[OutboxRecord]:
        if run_id is None:
            rows = self.execute(
                """
                SELECT action_id, run_id, command_id, node_run_id, action_kind,
                       idempotency_key, payload_json, status, attempt_count,
                       available_at_ms, lease_owner, lease_expires_at_ms,
                       last_problem_json, created_at_ms, updated_at_ms
                FROM outbox_actions
                WHERE status = 'pending' ORDER BY available_at_ms ASC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        else:
            rows = self.execute(
                """
                SELECT action_id, run_id, command_id, node_run_id, action_kind,
                       idempotency_key, payload_json, status, attempt_count,
                       available_at_ms, lease_owner, lease_expires_at_ms,
                       last_problem_json, created_at_ms, updated_at_ms
                FROM outbox_actions
                WHERE run_id = ? AND status = 'pending'
                ORDER BY available_at_ms ASC LIMIT ?
                """,
                (run_id, limit),
            ).fetchall()
        return [record for row in rows if (record := self._row_outbox(row)) is not None]

    @staticmethod
    def _row_outbox(row: Any) -> OutboxRecord | None:
        if row is None:
            return None
        return OutboxRecord(
            action_id=str(row[0]),
            run_id=str(row[1]),
            command_id=row[2],
            node_run_id=row[3],
            action_kind=str(row[4]),
            idempotency_key=str(row[5]),
            payload_json=str(row[6]),
            status=str(row[7]),
            attempt_count=int(row[8]),
            available_at_ms=int(row[9]),
            lease_owner=row[10],
            lease_expires_at_ms=row[11],
            last_problem_json=row[12],
            created_at_ms=int(row[13]),
            updated_at_ms=int(row[14]),
        )

    # -------------------------------------------------------- human tasks

    def insert_human_task(
        self,
        *,
        task_id: str,
        run_id: str,
        node_run_id: str,
        handoff_id: str | None,
        task_kind: str,
        prompt_json: str,
        created_at_ms: int,
    ) -> None:
        self.execute(
            """
            INSERT INTO human_tasks (
              task_id, run_id, node_run_id, handoff_id, task_kind, prompt_json,
              status, decision_json, created_at_ms, resolved_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending', NULL, ?, NULL)
            """,
            (task_id, run_id, node_run_id, handoff_id, task_kind, prompt_json, created_at_ms),
        )

    def get_human_task(self, task_id: str) -> tuple | None:
        return self.execute(
            """
            SELECT task_id, run_id, node_run_id, handoff_id, task_kind,
                   prompt_json, status, decision_json, created_at_ms, resolved_at_ms
            FROM human_tasks WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()

    def list_pending_human_tasks(self, run_id: str) -> list[tuple]:
        return self.execute(
            """
            SELECT task_id, run_id, node_run_id, handoff_id, task_kind,
                   prompt_json, status, decision_json, created_at_ms, resolved_at_ms
            FROM human_tasks
            WHERE run_id = ? AND status = 'pending'
            ORDER BY created_at_ms ASC
            """,
            (run_id,),
        ).fetchall()

    def update_human_task_decision(
        self,
        task_id: str,
        status: str,
        now_ms: int,
        *,
        decision_json: str | None = None,
    ) -> bool:
        cursor = self.execute(
            """
            UPDATE human_tasks
            SET status = ?, decision_json = COALESCE(?, decision_json), resolved_at_ms = ?
            WHERE task_id = ? AND status = 'pending'
            """,
            (status, decision_json, now_ms, task_id),
        )
        return self.affected() > 0

    # --------------------------------------------------- anchors/receipts

    def insert_anchor(
        self,
        *,
        anchor_id: str,
        node_run_id: str,
        actor_kind: str,
        anchor_json: str,
        created_at_ms: int,
        agent_id: str | None = None,
        role_key: str | None = None,
        session_id: str | None = None,
        session_attempt: int | None = None,
        task_id: str | None = None,
        turn_id: str | None = None,
        system_action_id: str | None = None,
        human_task_id: str | None = None,
        checkpoint_id: str | None = None,
        status: str = "bound",
        revision: int = 0,
    ) -> None:
        self.execute(
            """
            INSERT INTO execution_anchors (
              anchor_id, node_run_id, actor_kind, agent_id, role_key,
              session_id, session_attempt, task_id, turn_id,
              system_action_id, human_task_id, checkpoint_id, status,
              anchor_json, created_at_ms, revision
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                anchor_id,
                node_run_id,
                actor_kind,
                agent_id,
                role_key,
                session_id,
                session_attempt,
                task_id,
                turn_id,
                system_action_id,
                human_task_id,
                checkpoint_id,
                status,
                anchor_json,
                created_at_ms,
                int(revision),
            ),
        )

    def get_anchor_by_node_run(self, node_run_id: str) -> tuple | None:
        return self.execute(
            """
            SELECT anchor_id, node_run_id, actor_kind, agent_id, role_key,
                   session_id, session_attempt, task_id, turn_id,
                   system_action_id, human_task_id, checkpoint_id, status,
                   anchor_json, created_at_ms, revision
            FROM execution_anchors WHERE node_run_id = ?
            """,
            (node_run_id,),
        ).fetchone()

    def update_anchor_by_node_run(
        self,
        *,
        node_run_id: str,
        anchor_json: str,
        status: str,
        agent_id: str | None = None,
        role_key: str | None = None,
        session_id: str | None = None,
        session_attempt: int | None = None,
        task_id: str | None = None,
        turn_id: str | None = None,
        system_action_id: str | None = None,
    ) -> bool:
        self.execute(
            """
            UPDATE execution_anchors
            SET agent_id = COALESCE(?, agent_id),
                role_key = COALESCE(?, role_key),
                session_id = COALESCE(?, session_id),
                session_attempt = COALESCE(?, session_attempt),
                task_id = COALESCE(?, task_id),
                turn_id = COALESCE(?, turn_id),
                system_action_id = COALESCE(?, system_action_id), status = ?,
                anchor_json = ?, revision = revision + 1
            WHERE node_run_id = ?
            """,
            (
                agent_id,
                role_key,
                session_id,
                session_attempt,
                task_id,
                turn_id,
                system_action_id,
                status,
                anchor_json,
                node_run_id,
            ),
        )
        return self.affected() > 0

    def update_anchor_by_node_run_cas(
        self,
        *,
        node_run_id: str,
        expected_revision: int,
        anchor_json: str,
        status: str,
        agent_id: str | None = None,
        role_key: str | None = None,
        session_id: str | None = None,
        session_attempt: int | None = None,
        task_id: str | None = None,
        turn_id: str | None = None,
        system_action_id: str | None = None,
    ) -> bool:
        """Update an execution anchor only if its revision is unchanged."""

        self.execute(
            """
            UPDATE execution_anchors
            SET agent_id = COALESCE(?, agent_id),
                role_key = COALESCE(?, role_key),
                session_id = COALESCE(?, session_id),
                session_attempt = COALESCE(?, session_attempt),
                task_id = COALESCE(?, task_id),
                turn_id = COALESCE(?, turn_id),
                system_action_id = COALESCE(?, system_action_id),
                status = ?, anchor_json = ?, revision = revision + 1
            WHERE node_run_id = ? AND revision = ?
            """,
            (
                agent_id,
                role_key,
                session_id,
                session_attempt,
                task_id,
                turn_id,
                system_action_id,
                status,
                anchor_json,
                node_run_id,
                int(expected_revision),
            ),
        )
        return self.affected() > 0

    def insert_artifact_receipt(
        self,
        *,
        receipt_id: str,
        run_id: str,
        node_run_id: str,
        team_id: str,
        artifact_kind: str,
        canonical_ref_json: str,
        artifact_version: str,
        sha256: str,
        domain_revision: str,
        materialized: int,
        verified_at_ms: int,
    ) -> None:
        self.execute(
            """
            INSERT INTO artifact_receipts (
              receipt_id, run_id, node_run_id, team_id, artifact_kind,
              canonical_ref_json, artifact_version, sha256, domain_revision,
              materialized, verified_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt_id,
                run_id,
                node_run_id,
                team_id,
                artifact_kind,
                canonical_ref_json,
                artifact_version,
                sha256,
                domain_revision,
                materialized,
                verified_at_ms,
            ),
        )

    def get_artifact_receipt(self, receipt_id: str) -> tuple | None:
        return self.execute(
            """
            SELECT receipt_id, run_id, node_run_id, team_id, artifact_kind,
                   canonical_ref_json, artifact_version, sha256, domain_revision,
                   materialized, verified_at_ms
            FROM artifact_receipts WHERE receipt_id = ?
            """,
            (receipt_id,),
        ).fetchone()

    def list_receipts_for_node_run(self, node_run_id: str) -> list[tuple]:
        return self.execute(
            """
            SELECT receipt_id, run_id, node_run_id, team_id, artifact_kind,
                   canonical_ref_json, artifact_version, sha256, domain_revision,
                   materialized, verified_at_ms
            FROM artifact_receipts WHERE node_run_id = ?
            ORDER BY verified_at_ms ASC
            """,
            (node_run_id,),
        ).fetchall()

    def list_artifact_receipts_for_run(self, run_id: str) -> list[tuple]:
        return self.execute(
            """
            SELECT receipt_id, run_id, node_run_id, team_id, artifact_kind,
                   canonical_ref_json, artifact_version, sha256, domain_revision,
                   materialized, verified_at_ms
            FROM artifact_receipts WHERE run_id = ?
            ORDER BY verified_at_ms ASC
            """,
            (run_id,),
        ).fetchall()

    def insert_budget_receipt(
        self,
        *,
        receipt_id: str,
        run_id: str,
        node_run_id: str,
        reservation_id: str,
        stage_id: str,
        policy_hash: str,
        reserved_json: str,
        created_at_ms: int,
    ) -> None:
        self.execute(
            """
            INSERT INTO budget_receipts (
              receipt_id, run_id, node_run_id, reservation_id, stage_id,
              policy_hash, reserved_json, settled_json, status,
              created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'reserved', ?, ?)
            """,
            (
                receipt_id,
                run_id,
                node_run_id,
                reservation_id,
                stage_id,
                policy_hash,
                reserved_json,
                created_at_ms,
                created_at_ms,
            ),
        )

    def update_budget_receipt(
        self,
        receipt_id: str,
        *,
        status: str,
        now_ms: int,
        settled_json: str | None = None,
    ) -> bool:
        cursor = self.execute(
            """
            UPDATE budget_receipts
            SET status = ?, settled_json = COALESCE(?, settled_json), updated_at_ms = ?
            WHERE receipt_id = ?
            """,
            (status, settled_json, now_ms, receipt_id),
        )
        return self.affected() > 0

    def get_budget_receipt(self, receipt_id: str) -> tuple | None:
        return self.execute(
            """
            SELECT receipt_id, run_id, node_run_id, reservation_id, stage_id,
                   policy_hash, reserved_json, settled_json, status,
                   created_at_ms, updated_at_ms
            FROM budget_receipts WHERE receipt_id = ?
            """,
            (receipt_id,),
        ).fetchone()

    # ---------------------------------------------------------- handoffs

    def insert_handoff(
        self,
        *,
        handoff_id: str,
        run_id: str,
        edge_id: str,
        from_node_run_id: str,
        to_node_id: str,
        to_node_run_id: str | None,
        gate_kind: str,
        input_snapshot_hash: str,
        offered_at_ms: int,
    ) -> None:
        self.execute(
            """
            INSERT INTO handoffs (
              handoff_id, run_id, edge_id, from_node_run_id, to_node_id,
              to_node_run_id, gate_kind, input_snapshot_hash, status,
              accepted_by_json, rejection_problem_json, supersedes_handoff_id,
              offered_at_ms, accepted_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, NULL, NULL, ?, NULL)
            """,
            (
                handoff_id,
                run_id,
                edge_id,
                from_node_run_id,
                to_node_id,
                to_node_run_id,
                gate_kind,
                input_snapshot_hash,
                offered_at_ms,
            ),
        )

    def get_handoff(self, handoff_id: str) -> tuple | None:
        return self.execute(
            """
            SELECT handoff_id, run_id, edge_id, from_node_run_id, to_node_id,
                   to_node_run_id, gate_kind, input_snapshot_hash, status,
                   accepted_by_json, rejection_problem_json, supersedes_handoff_id,
                   offered_at_ms, accepted_at_ms
            FROM handoffs WHERE handoff_id = ?
            """,
            (handoff_id,),
        ).fetchone()

    def list_handoffs_for_node(self, run_id: str, to_node_id: str) -> list[tuple]:
        return self.execute(
            """
            SELECT handoff_id, run_id, edge_id, from_node_run_id, to_node_id,
                   to_node_run_id, gate_kind, input_snapshot_hash, status,
                   accepted_by_json, rejection_problem_json, supersedes_handoff_id,
                   offered_at_ms, accepted_at_ms
            FROM handoffs
            WHERE run_id = ? AND to_node_id = ?
            ORDER BY offered_at_ms ASC
            """,
            (run_id, to_node_id),
        ).fetchall()

    def list_handoffs_for_run(self, run_id: str) -> list[tuple]:
        return self.execute(
            """
            SELECT handoff_id, run_id, edge_id, from_node_run_id, to_node_id,
                   to_node_run_id, gate_kind, input_snapshot_hash, status,
                   accepted_by_json, rejection_problem_json, supersedes_handoff_id,
                   offered_at_ms, accepted_at_ms
            FROM handoffs
            WHERE run_id = ?
            ORDER BY offered_at_ms ASC, handoff_id ASC
            """,
            (run_id,),
        ).fetchall()

    def list_budget_receipts_for_run(self, run_id: str) -> list[tuple]:
        return self.execute(
            """
            SELECT receipt_id, run_id, node_run_id, reservation_id, stage_id,
                   policy_hash, reserved_json, settled_json, status,
                   created_at_ms, updated_at_ms
            FROM budget_receipts
            WHERE run_id = ?
            ORDER BY created_at_ms ASC, receipt_id ASC
            """,
            (run_id,),
        ).fetchall()

    def get_handoff_by_from_node(self, run_id: str, from_node_run_id: str) -> tuple | None:
        return self.execute(
            """
            SELECT handoff_id, run_id, edge_id, from_node_run_id, to_node_id,
                   to_node_run_id, gate_kind, input_snapshot_hash, status,
                   accepted_by_json, rejection_problem_json, supersedes_handoff_id,
                   offered_at_ms, accepted_at_ms
            FROM handoffs
            WHERE run_id = ? AND from_node_run_id = ?
            ORDER BY offered_at_ms DESC LIMIT 1
            """,
            (run_id, from_node_run_id),
        ).fetchone()

    def update_handoff_status(
        self,
        handoff_id: str,
        status: str,
        now_ms: int,
        *,
        accepted_by_json: str | None = None,
        rejection_problem_json: str | None = None,
        accepted_at_ms: int | None = None,
    ) -> bool:
        self._require_handoff_transition(handoff_id, status)
        if accepted_at_ms is None and status == "accepted":
            accepted_at_ms = now_ms
        cursor = self.execute(
            """
            UPDATE handoffs
            SET status = ?,
                accepted_by_json = COALESCE(?, accepted_by_json),
                rejection_problem_json = COALESCE(?, rejection_problem_json),
                accepted_at_ms = COALESCE(?, accepted_at_ms)
            WHERE handoff_id = ?
            """,
            (status, accepted_by_json, rejection_problem_json, accepted_at_ms, handoff_id),
        )
        return self.affected() > 0

    def insert_handoff_receipt(self, handoff_id: str, receipt_id: str, ordinal: int) -> None:
        self.execute(
            """
            INSERT INTO handoff_receipts (handoff_id, receipt_id, ordinal)
            VALUES (?, ?, ?)
            """,
            (handoff_id, receipt_id, ordinal),
        )

    def list_handoff_artifact_refs_for_run(self, run_id: str) -> list[tuple]:
        return self.execute(
            """
            SELECT hr.handoff_id, ar.receipt_id, ar.artifact_kind,
                   ar.canonical_ref_json, ar.artifact_version, ar.sha256
            FROM handoff_receipts hr
            JOIN artifact_receipts ar ON ar.receipt_id = hr.receipt_id
            JOIN handoffs h ON h.handoff_id = hr.handoff_id
            WHERE h.run_id = ?
            ORDER BY hr.handoff_id ASC, hr.ordinal ASC
            """,
            (run_id,),
        ).fetchall()

    def list_handoff_receipts(self, handoff_id: str) -> list[str]:
        rows = self.execute(
            """
            SELECT receipt_id FROM handoff_receipts
            WHERE handoff_id = ? ORDER BY ordinal ASC
            """,
            (handoff_id,),
        ).fetchall()
        return [str(row[0]) for row in rows]


    # ------------------------------------------------- knowledge_invocations

    def insert_knowledge_invocation(self, invocation: Any) -> None:
        columns = ",".join(_KNOWLEDGE_INVOCATION_COLUMNS)
        placeholders = ",".join("?" for _ in _KNOWLEDGE_INVOCATION_COLUMNS)
        self.execute(
            f"INSERT INTO knowledge_invocations ({columns}) VALUES ({placeholders})",
            (
                invocation.invocation_id,
                invocation.parent_run_id,
                invocation.parent_node_id,
                invocation.parent_node_run_id,
                invocation.parent_attempt,
                invocation.question_id,
                invocation.scope_hash,
                invocation.request_hash,
                invocation.search_envelope_hash,
                invocation.requirements_hash,
                invocation.source_policy_version,
                invocation.knowledge_child_run_id,
                invocation.status,
                invocation.knowledge_package_ref,
                invocation.package_content_hash,
                invocation.handoff_state,
                invocation.error_json,
                invocation.created_at_ms,
                invocation.updated_at_ms,
            ),
        )

    def get_knowledge_invocation(self, invocation_id: str) -> Any | None:
        row = self.execute(
            "SELECT * FROM knowledge_invocations WHERE invocation_id = ?",
            (invocation_id,),
        ).fetchone()
        return _row_knowledge_invocation(row)

    def find_knowledge_invocation_by_request(
        self, parent_run_id: str, parent_node_id: str, request_hash: str
    ) -> Any | None:
        row = self.execute(
            """
            SELECT * FROM knowledge_invocations
            WHERE parent_run_id = ? AND parent_node_id = ? AND request_hash = ?
            """,
            (parent_run_id, parent_node_id, request_hash),
        ).fetchone()
        return _row_knowledge_invocation(row)

    def find_knowledge_invocation_by_child_run(self, child_run_id: str) -> Any | None:
        row = self.execute(
            """
            SELECT * FROM knowledge_invocations
            WHERE knowledge_child_run_id = ?
            ORDER BY created_at_ms DESC, invocation_id DESC
            LIMIT 1
            """,
            (child_run_id,),
        ).fetchone()
        return _row_knowledge_invocation(row)

    def find_reusable_knowledge_invocation(
        self,
        *,
        scope_hash: str,
        search_envelope_hash: str,
        requirements_hash: str,
        source_policy_version: str,
    ) -> Any | None:
        """Latest completed invocation whose package is still consumable.

        Reuse requires the full envelope fingerprint tuple to match AND the
        source invocation to be ``completed`` with an accepted, non-revoked
        package reference.  failed/cancelled invocations never satisfy reuse.
        """
        row = self.execute(
            """
            SELECT * FROM knowledge_invocations
            WHERE scope_hash = ?
              AND search_envelope_hash = ?
              AND requirements_hash = ?
              AND source_policy_version = ?
              AND status = 'completed'
              AND handoff_state = 'accepted'
              AND knowledge_package_ref IS NOT NULL
              AND knowledge_package_ref != ''
              AND package_content_hash IS NOT NULL
              AND package_content_hash != ''
            ORDER BY updated_at_ms DESC, invocation_id DESC
            LIMIT 1
            """,
            (
                scope_hash,
                search_envelope_hash,
                requirements_hash,
                source_policy_version,
            ),
        ).fetchone()
        return _row_knowledge_invocation(row)

    def list_knowledge_invocations_for_parent(self, parent_run_id: str) -> list[Any]:
        rows = self.execute(
            """
            SELECT * FROM knowledge_invocations
            WHERE parent_run_id = ?
            ORDER BY created_at_ms ASC, invocation_id ASC
            """,
            (parent_run_id,),
        ).fetchall()
        records = [_row_knowledge_invocation(row) for row in rows]
        return [record for record in records if record is not None]

    def update_knowledge_invocation(
        self,
        invocation_id: str,
        now_ms: int,
        *,
        status: str | None = None,
        knowledge_child_run_id: Any = _UNSET,
        knowledge_package_ref: Any = _UNSET,
        package_content_hash: Any = _UNSET,
        handoff_state: str | None = None,
        error_json: Any = _UNSET,
    ) -> bool:
        """Guarded partial update; ``_UNSET`` leaves a nullable column alone."""
        assignments: list[str] = []
        params: list[Any] = []
        if status is not None:
            assignments.append("status = ?")
            params.append(status)
        if knowledge_child_run_id is not _UNSET:
            assignments.append("knowledge_child_run_id = ?")
            params.append(knowledge_child_run_id)
        if knowledge_package_ref is not _UNSET:
            assignments.append("knowledge_package_ref = ?")
            params.append(knowledge_package_ref)
        if package_content_hash is not _UNSET:
            assignments.append("package_content_hash = ?")
            params.append(package_content_hash)
        if handoff_state is not None:
            assignments.append("handoff_state = ?")
            params.append(handoff_state)
        if error_json is not _UNSET:
            assignments.append("error_json = ?")
            params.append(error_json)
        if not assignments:
            return False
        assignments.append("updated_at_ms = ?")
        params.append(now_ms)
        params.append(invocation_id)
        cursor = self.execute(
            "UPDATE knowledge_invocations SET "
            + ", ".join(assignments)
            + " WHERE invocation_id = ?",
            tuple(params),
        )
        rowcount = getattr(cursor, "rowcount", None)
        if rowcount in (None, -1):
            rowcount = 0
        return int(rowcount or 0) > 0

    # ------------------------------------------------- transition guards


    def _require_run_transition(self, run_id: str, target_status: str) -> None:
        """Enforce the frozen run transition graph (P1-5b); SQL never accepts
        an arbitrary status on its own."""
        from core.research.workflow.transitions import (
            RunStatus,
            require_run_transition,
        )

        row = self.execute(
            "SELECT status FROM workflow_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return
        current = str(row[0])
        try:
            require_run_transition(RunStatus(current), RunStatus(target_status))
        except ValueError as exc:
            raise ValueError(
                f"illegal run transition {current} -> {target_status} for {run_id}"
            ) from exc

    def _require_attempt_transition(self, node_run_id: str, target_status: str) -> None:
        """Enforce the frozen node-attempt transition graph (P1-5b)."""
        from core.research.workflow.transitions import (
            NodeAttemptStatus,
            require_node_attempt_transition,
        )

        row = self.execute(
            "SELECT status FROM node_attempts WHERE node_run_id = ?",
            (node_run_id,),
        ).fetchone()
        if row is None:
            return
        current = str(row[0])
        try:
            require_node_attempt_transition(
                NodeAttemptStatus(current), NodeAttemptStatus(target_status)
            )
        except ValueError as exc:
            raise ValueError(
                f"illegal node attempt transition {current} -> {target_status} "
                f"for {node_run_id}"
            ) from exc

    def _require_handoff_transition(self, handoff_id: str, target_status: str) -> None:
        """Enforce the frozen handoff transition graph (P1-5b)."""
        from core.research.workflow.transitions import (
            HandoffStatus,
            require_handoff_transition,
        )

        row = self.execute(
            "SELECT status FROM handoffs WHERE handoff_id = ?",
            (handoff_id,),
        ).fetchone()
        if row is None:
            return
        current = str(row[0])
        try:
            require_handoff_transition(HandoffStatus(current), HandoffStatus(target_status))
        except ValueError as exc:
            raise ValueError(
                f"illegal handoff transition {current} -> {target_status} "
                f"for {handoff_id}"
            ) from exc
