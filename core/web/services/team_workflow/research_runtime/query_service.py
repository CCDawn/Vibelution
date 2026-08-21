"""Workflow Query Service — scoped read orchestration over the Ledger.

Zero writes. No route/HTTP objects enter this layer. Ledger unavailability
fails closed; legacy JSON stores are never consulted.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
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

from .blocked_reason import format_blocked_reason
from .command_offer_builder import build_command_offers
from .node_scoped_session_projection import project_ledger_scoped_sessions
from .projection_builder import ProjectionInputs, build_research_workflow_snapshot
from .readiness import NodeReadinessService
from .readiness.common import DomainReadinessContext
from .run_catalog import catalog_dict_from_run


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
        revise_checkpoint_resolver: Callable[[str], str] | None = None,
        session_detail_reader: Callable[[str], Mapping[str, Any] | None] | None = None,
    ) -> None:
        self._store = store
        self._readiness = readiness_service
        self._readiness_context = readiness_context
        self._clock_iso = clock_iso or _default_iso_clock
        self._evaluated_at_ms = evaluated_at_ms
        self._definition = definition or build_challenge_cup_workflow_definition()
        self._revise_checkpoint_resolver = revise_checkpoint_resolver
        self._session_detail_reader = session_detail_reader

    def _resolve_revise_checkpoint_id(self, run: Any) -> str | None:
        """Revision offers need a fork base checkpoint.

        Root runs never carry ``forked_from_checkpoint_id``; resolve the
        thread's latest durable checkpoint instead (fail soft to unavailable).
        """
        if str(run.forked_from_checkpoint_id or "").strip():
            return None
        if self._revise_checkpoint_resolver is None:
            return None
        try:
            return str(self._revise_checkpoint_resolver(run.thread_id) or "").strip() or None
        except Exception:  # noqa: BLE001 - snapshot reads must fail soft
            return None

    def list_runs(self, *, team_id: str, workflow_id: str) -> dict[str, Any]:
        scoped_team = _require_team_id(team_id)
        try:
            records = self._store.list_runs_for_team(scoped_team, workflow_id)
        except (WorkflowLedgerUnavailableError, WorkflowLedgerClosedError) as exc:
            raise WorkflowLedgerUnavailable(str(exc)) from exc
        return {
            "workflowId": workflow_id,
            "runs": [catalog_dict_from_run(item) for item in records],
        }

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
            revise_checkpoint_id=self._resolve_revise_checkpoint_id(run),
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
        frozen = _frozen_binding_for(snap, node_id)
        session = _session_fields(
            anchor,
            actor_kind=node.actorKind.value,
            frozen=frozen,
        )
        scoped_session_projection = project_ledger_scoped_sessions(
            anchor,
            team_id=team_id,
            run_id=run_id,
            node_id=node_id,
            node_run_id=latest.node_run_id if latest is not None else None,
            node_status=latest.status if latest is not None else snap.run.status,
            session_detail_reader=self._session_detail_reader,
        )
        formal_projection = bool(
            scoped_session_projection.get("_formalProjection")
        )
        formal_root = scoped_session_projection.get("rootSession")
        if formal_projection:
            formal_root_healthy = bool(
                isinstance(formal_root, Mapping)
                and not formal_root.get("sessionAnchorDegraded")
            )
            if formal_root_healthy:
                projected_session_id = _optional_session_scalar(
                    formal_root.get("sessionId")
                )
                projected_task_id = _optional_session_scalar(
                    formal_root.get("taskId")
                )
                projected_turn_id = _optional_session_scalar(
                    formal_root.get("turnId")
                )
                projected_session_attempt = formal_root.get("sessionAttempt")
                projected_chat_deep_link = _optional_session_scalar(
                    formal_root.get("chatDeepLink")
                )
                projected_session_degraded = False
            else:
                # A formal payload is authoritative even when its root is
                # absent or damaged. Do not fall back to the ledger row's
                # scalar session fields, which may point at a candidate child.
                projected_session_id = None
                projected_task_id = None
                projected_turn_id = None
                projected_session_attempt = None
                projected_chat_deep_link = None
                projected_session_degraded = True
        else:
            projected_session_id = session["session_id"]
            projected_task_id = session["task_id"]
            projected_turn_id = session["turn_id"]
            projected_session_attempt = session["session_attempt"]
            projected_chat_deep_link = _chat_deep_link(
                team_id=team_id,
                run_id=run_id,
                node_id=node_id,
                session_id=projected_session_id,
                task_id=projected_task_id,
                turn_id=projected_turn_id,
            )
            projected_session_degraded = session["degraded"]
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
                (latest.binding_snapshot_id if latest is not None else None)
                or (frozen.snapshot_id if frozen is not None and frozen.snapshot_id else None)
            ),
            latest_attempt=latest,
            attempts=attempts,
            command_offers=offers,
            latest_event_sequence=snap.latest_event_sequence,
            generated_at=snap.generated_at,
            agent_id=session["agent_id"],
            display_name=session["display_name"],
            resolved_from=session["resolved_from"],
            session_id=projected_session_id,
            task_id=projected_task_id,
            turn_id=projected_turn_id,
            session_attempt=projected_session_attempt,
            chat_deep_link=projected_chat_deep_link,
            session_anchor_degraded=projected_session_degraded,
            root_session=scoped_session_projection["rootSession"],
            scoped_sessions=tuple(scoped_session_projection["scopedSessions"]),
            blocked_reason=_node_blocked_reason(latest, snap.run.blocked_reason),
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
            refs_by_handoff: dict[str, list[dict[str, Any]]] = {}
            for row in repo.list_handoff_artifact_refs_for_run(run_id):
                refs_by_handoff.setdefault(str(row[0]), []).append(
                    _artifact_ref_from_receipt(row)
                )
            handoffs = [
                _handoff_summary(row, attempt_by_id, refs_by_handoff)
                for row in repo.list_handoffs_for_run(run_id)
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


def _handoff_summary(
    row: tuple,
    attempt_by_id: dict[str, Any],
    refs_by_handoff: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    from_node_run_id = str(row[3] or "")
    attempt = attempt_by_id.get(from_node_run_id)
    edge_id = str(row[2] or "")
    from_node_id = ""
    if attempt is not None:
        from_node_id = str(attempt.node_id or "")
    elif "->" in edge_id:
        from_node_id = edge_id.split("->", 1)[0]
    return {
        "handoffId": row[0],
        "runId": row[1],
        "edgeId": edge_id,
        "fromNodeId": from_node_id,
        "fromNodeRunId": from_node_run_id,
        "toNodeId": row[4],
        "toNodeRunId": row[5],
        "gateKind": row[6],
        "inputSnapshotHash": row[7],
        "status": row[8],
        "outputArtifactRefs": list(refs_by_handoff.get(str(row[0]), [])),
        "offeredAtMs": row[12],
        "acceptedAtMs": row[13],
    }


def _artifact_ref_from_receipt(row: tuple) -> dict[str, Any]:
    canonical_ref = ""
    try:
        payload = json.loads(row[3] or "{}")
        if isinstance(payload, dict):
            canonical_ref = str(payload.get("canonicalRef") or "")
    except (TypeError, ValueError):
        canonical_ref = ""
    return {
        "artifactId": str(row[1] or ""),
        "kind": str(row[2] or ""),
        "version": str(row[4] or "1.0.0"),
        "contentHash": str(row[5] or ""),
        "uri": canonical_ref,
    }


def _node_blocked_reason(latest: Any, run_blocked_reason: str | None) -> str:
    if latest is None or str(getattr(latest, "status", "") or "") != "blocked":
        return ""
    problem = getattr(latest, "problem", None)
    if isinstance(problem, dict):
        formatted = format_blocked_reason(problem)
        if formatted:
            return formatted
    return str(run_blocked_reason or "")


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


def _frozen_binding_for(snap: ResearchWorkflowSnapshot, node_id: str):
    for item in snap.agent_binding_summary.bindings:
        if item.node_id == node_id:
            return item
    return None


def _agent_display_name(agent_id: str) -> str:
    if not agent_id:
        return ""
    try:
        from core.web.services.team_service import lookup_agent_display_name_map

        name = str(lookup_agent_display_name_map().get(agent_id) or "").strip()
        if name:
            return name
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError):
        return agent_id
    return agent_id


def _session_fields(
    anchor: tuple | None,
    *,
    actor_kind: str,
    frozen: Any | None = None,
) -> dict[str, Any]:
    agent_id = str(anchor[3] or "").strip() if anchor is not None else ""
    resolved_from = "workflow_default" if agent_id else "unbound"
    if not agent_id and frozen is not None:
        agent_id = str(getattr(frozen, "agent_id", "") or "").strip()
        if agent_id:
            resolved_from = str(getattr(frozen, "resolved_from", "") or "").strip() or "workflow_default"
    session_id = str(anchor[5] or "").strip() if anchor is not None else ""
    session_attempt = anchor[6] if anchor is not None else None
    task_id = str(anchor[7] or "").strip() if anchor is not None else ""
    turn_id = str(anchor[8] or "").strip() if anchor is not None else ""
    complete = bool(session_id and task_id and turn_id)
    display_name = _agent_display_name(agent_id) if agent_id else ""
    return {
        "agent_id": agent_id or None,
        "display_name": display_name or agent_id,
        "resolved_from": resolved_from,
        "session_id": session_id or None,
        "task_id": task_id or None,
        "turn_id": turn_id or None,
        "session_attempt": int(session_attempt) if session_attempt is not None else None,
        "degraded": actor_kind == "agent" and not complete,
    }


def _optional_session_scalar(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


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
