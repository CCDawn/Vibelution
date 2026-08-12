"""Workflow Query Service — scoped read orchestration over the Ledger.

Zero writes. No route/HTTP objects enter this layer. Ledger unavailability
fails closed; legacy JSON stores are never consulted.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from core.research.workflow.contracts import ResearchWorkflowSnapshot
from core.research.workflow.contracts.workflow_snapshot import (
    HumanTaskSummary,
    ResearchWorkflowNodeDetail,
)
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


class NodeNotFoundError(WorkflowQueryError):
    code = "unknown_node"

    def __init__(self, node_id: str) -> None:
        super().__init__(f"unknown nodeId: {node_id}", code="unknown_node")


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
            run=run,
            definition=self._definition,
            pending_human_tasks=human_tasks,
            attempts=attempts,
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
    ) -> ResearchWorkflowNodeDetail:
        node = next(
            (item for item in self._definition.nodes if item.nodeId == node_id),
            None,
        )
        if node is None:
            raise NodeNotFoundError(node_id)

        def load(_repo: WorkflowLedgerRepository):
            snap = self.get_snapshot(team_id=team_id, run_id=run_id)
            attempts = snap.node_attempts.get(node_id, ())
            latest = attempts[-1] if attempts else None
            anchor = _load_anchor(
                self._store,
                latest.node_run_id if latest is not None else None,
            )
            return snap, latest, anchor

        if hasattr(self._store, "read"):
            snap, latest, anchor = self._store.read(load)
        else:
            snap, latest, anchor = load(self._store)  # type: ignore[arg-type]
        attempts = snap.node_attempts.get(node_id, ())
        offers = tuple(
            offer for offer in snap.command_offers if offer.node_id == node_id
        )
        session = _session_fields(anchor, actor_kind=node.actorKind.value)
        return ResearchWorkflowNodeDetail(
            run_id=run_id,
            team_id=team_id,
            node_id=node_id,
            run_version=snap.run.run_version,
            actor_kind=node.actorKind.value,
            primary_role_key=node.primaryRoleKey,
            label=node.label,
            runtime_current=node_id in snap.active_node_ids,
            status=latest.status if latest is not None else snap.run.status,
            binding_snapshot_id=(
                latest.binding_snapshot_id if latest is not None else None
            ),
            latest_attempt=latest,
            attempts=attempts,
            command_offers=offers,
            latest_event_sequence=snap.latest_event_sequence,
            generated_at=snap.generated_at,
            agent_id=session["agent_id"],
            display_name=session["display_name"],
            resolved_from=session["resolved_from"],
            session_id=session["session_id"],
            task_id=session["task_id"],
            turn_id=session["turn_id"],
            session_attempt=session["session_attempt"],
            chat_deep_link=_chat_deep_link(
                team_id=team_id,
                run_id=run_id,
                node_id=node_id,
                session_id=session["session_id"],
                task_id=session["task_id"],
                turn_id=session["turn_id"],
            ),
            session_anchor_degraded=session["degraded"],
            blocked_reason=(
                str(snap.run.terminal_reason or "")
                if latest is not None and latest.status == "blocked"
                else ""
            ),
        )

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


def _human_task_summary(row: tuple, attempt_by_id: dict[str, Any]) -> HumanTaskSummary:
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
    return HumanTaskSummary(
        task_id=task_id,
        run_id=run_id,
        node_run_id=node_run_id,
        node_id=attempt.node_id if attempt is not None else None,
        handoff_id=handoff_id,
        task_kind=task_kind,
        status=status,
        created_at_ms=created_at_ms,
        resolved_at_ms=resolved_at_ms,
    )


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


def _load_anchor(store: Any, node_run_id: str | None) -> tuple | None:
    if not node_run_id:
        return None

    def load(repo: WorkflowLedgerRepository):
        return repo.get_anchor_by_node_run(node_run_id)

    if hasattr(store, "read"):
        return store.read(load)
    return load(store)


def _session_fields(anchor: tuple | None, *, actor_kind: str) -> dict[str, Any]:
    agent_id = str(anchor[3] or "").strip() if anchor is not None else ""
    session_id = str(anchor[5] or "").strip() if anchor is not None else ""
    session_attempt = anchor[6] if anchor is not None else None
    task_id = str(anchor[7] or "").strip() if anchor is not None else ""
    turn_id = str(anchor[8] or "").strip() if anchor is not None else ""
    complete = bool(session_id and task_id and turn_id)
    display_name = ""
    if agent_id:
        try:
            from core.web.services.agent_directory_service import get_agent

            agent = get_agent(agent_id)
            if isinstance(agent, dict):
                display_name = str(
                    agent.get("displayName") or agent.get("agentName") or agent_id
                )
        except (ImportError, KeyError, OSError, TypeError, ValueError):
            display_name = agent_id
    return {
        "agent_id": agent_id or None,
        "display_name": display_name or agent_id,
        "resolved_from": "workflow_default" if agent_id else "unbound",
        "session_id": session_id or None,
        "task_id": task_id or None,
        "turn_id": turn_id or None,
        "session_attempt": int(session_attempt) if session_attempt is not None else None,
        "degraded": actor_kind == "agent" and not complete,
    }


def _chat_deep_link(
    *,
    team_id: str,
    run_id: str,
    node_id: str,
    session_id: str | None,
    task_id: str | None,
    turn_id: str | None,
) -> str | None:
    if not (session_id and task_id and turn_id):
        return None
    return_to = "/teams?" + urlencode(
        {
            "teamId": team_id,
            "researchView": "workflow",
            "runId": run_id,
            "node": node_id,
        }
    )
    return "/chat?" + urlencode(
        {
            "session": session_id,
            "focusTask": task_id,
            "focusTurn": turn_id,
            "returnTo": return_to,
            "returnLabel": "返回科研流程",
        }
    )
