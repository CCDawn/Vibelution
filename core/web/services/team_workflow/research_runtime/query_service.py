"""Workflow Query Service — scoped read orchestration over the Ledger.

Zero writes. No route/HTTP objects enter this layer. Ledger unavailability
fails closed; legacy JSON stores are never consulted.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from core.research.workflow.contracts import ResearchWorkflowSnapshot
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.ledger import WorkflowLedgerStore
from core.research.workflow.ledger.errors import (
    WorkflowLedgerClosedError,
    WorkflowLedgerUnavailableError,
)
from core.research.workflow.ledger.repository import WorkflowLedgerRepository

from .command_offer_builder import build_command_offers
from .projection_builder import ProjectionInputs, build_research_workflow_snapshot
from .readiness import NodeReadinessService
from .readiness.common import DomainReadinessContext


class WorkflowQueryError(RuntimeError):
    code = "workflow_query_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class TeamScopeMismatchError(WorkflowQueryError):
    code = "team_scope_mismatch"

    def __init__(self, detail: str = "teamId does not match run scope") -> None:
        super().__init__(detail, code="team_scope_mismatch")


class RunNotFoundError(WorkflowQueryError):
    code = "run_not_found"

    def __init__(self, run_id: str) -> None:
        super().__init__(f"run not found: {run_id}", code="run_not_found")


class WorkflowLedgerUnavailable(WorkflowQueryError):
    code = "workflow_ledger_unavailable"

    def __init__(self, detail: str = "workflow ledger unavailable") -> None:
        super().__init__(detail, code="workflow_ledger_unavailable")


class WorkflowQueryService:
    def __init__(
        self,
        *,
        store: WorkflowLedgerStore,
        readiness_service: NodeReadinessService,
        readiness_context: Callable[[], DomainReadinessContext],
        clock_iso: Callable[[], str] | None = None,
        evaluated_at_ms: Callable[[], int] | None = None,
        definition: Any | None = None,
    ) -> None:
        self._store = store
        self._readiness = readiness_service
        self._readiness_context = readiness_context
        self._clock_iso = clock_iso or _default_iso_clock
        self._evaluated_at_ms = evaluated_at_ms
        self._definition = definition or build_challenge_cup_workflow_definition()

    def get_snapshot(self, *, team_id: str, run_id: str) -> ResearchWorkflowSnapshot:
        scoped_team = _require_team_id(team_id)
        try:
            bundle = self._read_bundle(run_id)
        except (WorkflowLedgerUnavailableError, WorkflowLedgerClosedError) as exc:
            raise WorkflowLedgerUnavailable(str(exc)) from exc
        except WorkflowLedgerUnavailable:
            raise
        if bundle is None:
            # Distinguish missing run vs wrong team without leaking cross-team existence.
            try:
                bare = self._store.get_run(run_id)
            except (WorkflowLedgerUnavailableError, WorkflowLedgerClosedError) as exc:
                raise WorkflowLedgerUnavailable(str(exc)) from exc
            if bare is None:
                raise RunNotFoundError(run_id)
            raise TeamScopeMismatchError()

        run, attempts, human_tasks, handoffs, budget_receipts, latest_seq = bundle
        if run.team_id != scoped_team:
            raise TeamScopeMismatchError()

        offers = build_command_offers(
            readiness_service=self._readiness,
            context=self._readiness_context(),
            team_id=scoped_team,
            run_id=run.run_id,
            run_version=run.run_version,
            definition=self._definition,
            pending_human_tasks=human_tasks,
            evaluated_at_ms=(
                self._evaluated_at_ms() if self._evaluated_at_ms is not None else None
            ),
        )
        return build_research_workflow_snapshot(
            ProjectionInputs(
                run=run,
                definition=self._definition,
                attempts=tuple(attempts),
                pending_human_tasks=tuple(human_tasks),
                handoffs=tuple(handoffs),
                budget_receipts=tuple(budget_receipts),
                command_offers=tuple(offers),
                latest_event_sequence=latest_seq,
                generated_at=self._clock_iso(),
            )
        )

    def get_node_detail(
        self, *, team_id: str, run_id: str, node_id: str
    ) -> dict[str, Any]:
        snap = self.get_snapshot(team_id=team_id, run_id=run_id)
        attempts = list(snap.node_attempts.get(node_id, ()))
        offers = [
            offer.to_dict()
            for offer in snap.command_offers
            if offer.node_id == node_id
        ]
        return {
            "runId": run_id,
            "teamId": team_id,
            "nodeId": node_id,
            "runVersion": snap.run["runVersion"],
            "attempts": attempts,
            "commandOffers": offers,
            "latestEventSequence": snap.latest_event_sequence,
            "generatedAt": snap.generated_at,
        }

    def _read_bundle(self, run_id: str):
        def load(repo: WorkflowLedgerRepository):
            run = repo.get_run(run_id)
            if run is None:
                return None
            attempts = repo.list_attempts(run_id)
            human_rows = repo.list_pending_human_tasks(run_id)
            attempt_by_id = {item.node_run_id: item for item in attempts}
            human_tasks = [
                _human_task_summary(row, attempt_by_id) for row in human_rows
            ]
            handoffs = [
                _handoff_summary(row) for row in repo.list_handoffs_for_run(run_id)
            ]
            budget_receipts = [
                _budget_receipt_summary(row)
                for row in repo.list_budget_receipts_for_run(run_id)
            ]
            latest_seq = repo.latest_event_sequence(run_id)
            return (
                run,
                attempts,
                human_tasks,
                handoffs,
                budget_receipts,
                latest_seq,
            )

        if hasattr(self._store, "read"):
            return self._store.read(load)
        # Narrow test doubles may raise WorkflowLedgerUnavailable directly.
        return load(self._store)  # type: ignore[arg-type]


def _require_team_id(team_id: str) -> str:
    normalized = str(team_id or "").strip()
    if not normalized:
        raise TeamScopeMismatchError("teamId is required")
    return normalized


def _default_iso_clock() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _human_task_summary(row: tuple, attempt_by_id: dict[str, Any]) -> dict[str, Any]:
    (
        task_id,
        run_id,
        node_run_id,
        handoff_id,
        task_kind,
        _prompt_json,
        status,
        _decision_json,
        created_at_ms,
        resolved_at_ms,
    ) = row
    attempt = attempt_by_id.get(node_run_id)
    return {
        "taskId": task_id,
        "runId": run_id,
        "nodeRunId": node_run_id,
        "nodeId": attempt.node_id if attempt is not None else None,
        "handoffId": handoff_id,
        "taskKind": task_kind,
        "status": status,
        "createdAtMs": created_at_ms,
        "resolvedAtMs": resolved_at_ms,
    }


def _handoff_summary(row: tuple) -> dict[str, Any]:
    return {
        "handoffId": row[0],
        "runId": row[1],
        "edgeId": row[2],
        "fromNodeRunId": row[3],
        "toNodeId": row[4],
        "toNodeRunId": row[5],
        "gateKind": row[6],
        "inputSnapshotHash": row[7],
        "status": row[8],
        "offeredAtMs": row[12],
        "acceptedAtMs": row[13],
    }


def _budget_receipt_summary(row: tuple) -> dict[str, Any]:
    return {
        "receiptId": row[0],
        "runId": row[1],
        "nodeRunId": row[2],
        "reservationId": row[3],
        "stageId": row[4],
        "policyHash": row[5],
        "status": row[8],
        "createdAtMs": row[9],
        "updatedAtMs": row[10],
    }
