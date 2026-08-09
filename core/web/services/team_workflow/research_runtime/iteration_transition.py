"""Apply iteration decisions at the service boundary (durable side effects).

Graph nodes only transition state; this module owns:
- decision record append + idempotency
- controlled_run attempt lineage / handoffs
- revision fork orchestration hooks
- promotion/rollback proposal + HumanTask
- stop terminal package guards
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from core.research.workflow.iteration_decisions import (
    DEFAULT_ITERATION_BUDGET,
    IterationDecisionError,
    IterationDecisionKind,
    check_rerun_budget,
    normalize_decision_dict,
    parse_decision_kind,
    promotion_operation_for,
)
from core.web.services.team_workflow.research_runtime.handoff_builder import (
    build_handoff_record,
)
from core.web.services.team_workflow.research_runtime.handoff_lineage import (
    append_handoff_attempt,
)
from core.web.services.team_workflow.research_runtime.run_fork import (
    build_child_run_skeleton,
    link_parent_after_fork,
)


def _utc_now_default() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_decision_ids(
    decision: dict[str, Any],
    *,
    run_id: str,
    utc_now: Callable[[], str] | None = None,
) -> dict[str, Any]:
    now = (utc_now or _utc_now_default)()
    out = dict(decision)
    out.setdefault("decisionId", f"dec-{uuid.uuid4().hex[:10]}")
    out.setdefault("runId", run_id)
    out.setdefault("nodeRunId", f"nr-iteration_decision-{out['decisionId']}")
    out.setdefault("decidedAt", now)
    out.setdefault("iterationAttempt", int(out.get("iterationAttempt") or 1))
    return out


def find_decision_by_idempotency(
    record: dict[str, Any], idempotency_key: str
) -> dict[str, Any] | None:
    if not idempotency_key:
        return None
    for item in record.get("iterationDecisions") or []:
        if str(item.get("idempotencyKey") or "") == idempotency_key:
            return dict(item)
    return None


def build_promotion_proposal(
    *,
    run_id: str,
    decision: dict[str, Any],
    operation: str,
    utc_now: Callable[[], str] | None = None,
) -> dict[str, Any]:
    now = (utc_now or _utc_now_default)()
    target = str(
        decision.get("selectedCandidateRef")
        or decision.get("baselineRef")
        or ""
    )
    return {
        "proposalId": f"pp-{uuid.uuid4().hex[:10]}",
        "runId": run_id,
        "operation": operation,
        "decisionId": decision.get("decisionId") or "",
        "targetCandidateRef": target,
        "selectedCandidateRef": str(decision.get("selectedCandidateRef") or ""),
        "baselineRef": str(decision.get("baselineRef") or ""),
        "status": "pending_human",
        "reason": str(decision.get("reason") or ""),
        "createdAt": now,
    }


def apply_iteration_decision_side_effects(
    *,
    record: dict[str, Any],
    decision_raw: dict[str, Any],
    graph_state: dict[str, Any],
    checkpoint_id: str,
    workflow_id: str,
    workflow_version_id: str,
    utc_now: Callable[[], str] | None = None,
    create_child_run: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return patch fields + optional child run for the store layer.

    Returns dict with keys:
      decision, patch, handoffs_to_append, human_task, child_run, error
    """
    now_fn = utc_now or _utc_now_default
    run_id = str(record.get("runId") or "")
    decision = ensure_decision_ids(
        normalize_decision_dict(decision_raw),
        run_id=run_id,
        utc_now=now_fn,
    )
    kind = parse_decision_kind(decision["decisionKind"])
    artifacts = dict(graph_state.get("artifacts") or (record.get("langGraph") or {}).get("artifacts") or {})
    decision.setdefault("frozenProtocolRef", artifacts.get("frozen_protocol") or "")
    decision.setdefault("evaluationReportRef", artifacts.get("evaluation_report") or "")

    patch: dict[str, Any] = {}
    human_task: dict[str, Any] | None = None
    child_run: dict[str, Any] | None = None

    controlled_attempt = int(
        graph_state.get("controlled_run_attempt")
        or (record.get("nodeAttempts") or {}).get("controlled_run")
        or 0
    )
    budget = int(
        decision.get("budgetMax")
        or record.get("iterationBudgetMax")
        or graph_state.get("iteration_budget_max")
        or DEFAULT_ITERATION_BUDGET
    )

    if kind is IterationDecisionKind.RERUN_SAME_PROTOCOL:
        blocked = str(graph_state.get("blocked_reason") or record.get("blockedReason") or "")
        # Graph already advanced attempt on successful rerun; use post-resume value.
        new_attempt = int(graph_state.get("controlled_run_attempt") or 0)
        if blocked == "iteration_budget_exhausted" or (
            new_attempt == 0 and controlled_attempt >= budget
        ):
            try:
                check_rerun_budget(current_attempt=max(controlled_attempt, new_attempt), budget_max=budget)
            except IterationDecisionError as exc:
                return {
                    "decision": decision,
                    "patch": {
                        "status": "blocked",
                        "blockedReason": "iteration_budget_exhausted",
                        "runtimeCurrentNodeIds": ["iteration_decision"],
                    },
                    "handoffs_to_append": [],
                    "human_task": None,
                    "child_run": None,
                    "error": {"code": exc.code, "message": str(exc)},
                }
        if new_attempt <= 0:
            # Graph did not advance (budget interrupt) — treat as blocked
            if controlled_attempt >= budget:
                return {
                    "decision": decision,
                    "patch": {
                        "status": "blocked",
                        "blockedReason": "iteration_budget_exhausted",
                        "runtimeCurrentNodeIds": ["iteration_decision"],
                    },
                    "handoffs_to_append": [],
                    "human_task": None,
                    "child_run": None,
                    "error": {
                        "code": "iteration_budget_exhausted",
                        "message": f"iteration budget exhausted: attempt={controlled_attempt}",
                    },
                }
            new_attempt = controlled_attempt + 1
        node_attempts = dict(record.get("nodeAttempts") or {})
        node_attempts["controlled_run"] = new_attempt
        node_run_id = f"nr-controlled_run-a{new_attempt}"
        # Handoff lineage iteration_decision -> controlled_run
        handoff = build_handoff_record(
            run_id=run_id,
            workflow_id=workflow_id,
            workflow_version_id=workflow_version_id,
            from_node_id="iteration_decision",
            to_node_id="controlled_run",
            status="accepted",
            artifacts=artifacts,
            accepted_by=str(decision.get("decidedBy") or "iteration_planner"),
        )
        handoff["edgeId"] = "e_decision_rerun"
        handoff["nodeAttempt"] = new_attempt
        handoff["toNodeRunId"] = node_run_id
        existing = list(record.get("handoffs") or [])
        _, lineage = append_handoff_attempt(existing, handoff)
        # After graph auto-continues to next iteration_decision interrupt, surface that.
        runtime = ["iteration_decision"] if new_attempt >= 1 else ["controlled_run"]
        patch = {
            "nodeAttempts": node_attempts,
            "status": "waiting_human" if runtime == ["iteration_decision"] else "running",
            "runtimeCurrentNodeIds": runtime,
            "handoffs": lineage,
            "officialCandidateRef": record.get("officialCandidateRef") or "",
        }
        return {
            "decision": decision,
            "patch": patch,
            "handoffs_to_append": [],
            "human_task": None,
            "child_run": None,
            "error": None,
            "replace_handoffs": lineage,
            "controlled_run_attempt": new_attempt,
            "frozen_protocol_hash": artifacts.get("frozen_protocol"),
        }

    if kind is IterationDecisionKind.REVISE_PROTOCOL:
        if create_child_run is None:
            raise IterationDecisionError("create_child_run callback required", code="missing_fork_callback")
        # Idempotent fork by decision idempotency
        existing_children = list(record.get("childRunIds") or [])
        if decision.get("idempotencyKey"):
            for cid in existing_children:
                # caller should check index; here we just avoid double-create if lastForkDecisionId matches
                if str(record.get("lastForkDecisionId") or "") == str(decision.get("decisionId") or ""):
                    return {
                        "decision": decision,
                        "patch": link_parent_after_fork(
                            record,
                            child_run_id=existing_children[-1],
                            decision_id=str(decision.get("decisionId") or ""),
                            checkpoint_id=checkpoint_id,
                        ),
                        "handoffs_to_append": [],
                        "human_task": None,
                        "child_run": None,
                        "error": None,
                        "existing_child_run_id": existing_children[-1],
                    }
        skeleton = build_child_run_skeleton(
            parent=record,
            decision=decision,
            fork_checkpoint_id=checkpoint_id,
            utc_now=now_fn,
        )
        child_run = create_child_run(skeleton)
        child_id = str(child_run.get("runId") or skeleton["runId"])
        patch = link_parent_after_fork(
            record,
            child_run_id=child_id,
            decision_id=str(decision.get("decisionId") or ""),
            checkpoint_id=checkpoint_id,
        )
        # Parent frozen protocol must remain
        parent_fp = artifacts.get("frozen_protocol")
        lg = dict(record.get("langGraph") or {})
        lg_artifacts = dict(lg.get("artifacts") or {})
        if parent_fp:
            lg_artifacts["frozen_protocol"] = parent_fp
        lg["artifacts"] = lg_artifacts
        patch["langGraph"] = {**lg, **(patch.get("langGraph") or {})}
        return {
            "decision": decision,
            "patch": patch,
            "handoffs_to_append": [],
            "human_task": None,
            "child_run": child_run,
            "error": None,
        }

    if kind in (IterationDecisionKind.PROMOTE_CANDIDATE, IterationDecisionKind.ROLLBACK_CANDIDATE):
        op = promotion_operation_for(kind) or "promote"
        target = str(decision.get("selectedCandidateRef") or decision.get("baselineRef") or "")
        if kind is IterationDecisionKind.ROLLBACK_CANDIDATE and not target:
            raise IterationDecisionError(
                "rollback requires existing candidate/baseline ref",
                code="missing_rollback_target",
            )
        governance_handoff = build_handoff_record(
            run_id=run_id,
            workflow_id=workflow_id,
            workflow_version_id=workflow_version_id,
            from_node_id="iteration_decision",
            to_node_id="version_governance",
            status="accepted",
            artifacts=artifacts,
            accepted_by=str(decision.get("decidedBy") or "iteration_planner"),
        )
        existing = list(record.get("handoffs") or [])
        _, lineage = append_handoff_attempt(existing, governance_handoff)

        if kind is IterationDecisionKind.ROLLBACK_CANDIDATE:
            patch = {
                "status": "succeeded",
                "completionKind": "rolled_back",
                "runtimeCurrentNodeIds": [],
                "promotionOperation": "rollback",
                "officialCandidateRef": target,
                "handoffs": lineage,
            }
            return {
                "decision": decision,
                "patch": patch,
                "handoffs_to_append": [],
                "human_task": None,
                "child_run": None,
                "error": None,
                "replace_handoffs": lineage,
            }

        proposal = build_promotion_proposal(
            run_id=run_id, decision=decision, operation=op, utc_now=now_fn
        )
        human_task = {
            "taskId": f"ht-{uuid.uuid4().hex[:10]}",
            "runId": run_id,
            "nodeId": "candidate_promotion",
            "nodeRunId": f"nr-candidate_promotion-{proposal['proposalId']}",
            "status": "pending",
            "prompt": f"Resolve {op} promotion proposal",
            "proposalId": proposal["proposalId"],
            "promotionOperation": op,
            "createdAt": now_fn(),
            "resolvedAt": "",
            "resolvedBy": "",
            "checkpointId": checkpoint_id,
        }
        proposals = list(record.get("promotionProposals") or [])
        proposals.append(proposal)
        promotion_handoff = build_handoff_record(
            run_id=run_id,
            workflow_id=workflow_id,
            workflow_version_id=workflow_version_id,
            from_node_id="version_governance",
            to_node_id="candidate_promotion",
            status="waiting_human",
            artifacts={**artifacts, "version_governance_record": proposal["proposalId"]},
            human_task_id=human_task["taskId"],
        )
        _, lineage = append_handoff_attempt(lineage, promotion_handoff)
        patch = {
            "status": "waiting_human",
            "runtimeCurrentNodeIds": ["candidate_promotion"],
            "promotionProposals": proposals,
            "promotionOperation": op,
            "handoffs": lineage,
        }
        return {
            "decision": decision,
            "patch": patch,
            "handoffs_to_append": [],
            "human_task": human_task,
            "child_run": None,
            "error": None,
            "replace_handoffs": lineage,
            "proposal": proposal,
        }

    if kind is IterationDecisionKind.STOP:
        terminal = str(decision.get("terminalReason") or decision.get("reason") or "")
        pending = [
            t
            for t in (record.get("humanTasks") or [])
            if str(t.get("status") or "") == "pending"
        ]
        if pending:
            raise IterationDecisionError(
                "result_package requires no pending human tasks",
                code="pending_human_tasks",
            )
        if not terminal:
            raise IterationDecisionError("stop requires terminalReason", code="missing_terminal_reason")
        governance_handoff = build_handoff_record(
            run_id=run_id,
            workflow_id=workflow_id,
            workflow_version_id=workflow_version_id,
            from_node_id="iteration_decision",
            to_node_id="version_governance",
            status="accepted",
            artifacts=artifacts,
            accepted_by=str(decision.get("decidedBy") or "iteration_planner"),
        )
        existing = list(record.get("handoffs") or [])
        _, lineage = append_handoff_attempt(existing, governance_handoff)
        package_handoff = build_handoff_record(
            run_id=run_id,
            workflow_id=workflow_id,
            workflow_version_id=workflow_version_id,
            from_node_id="version_governance",
            to_node_id="result_package",
            status="accepted",
            artifacts=artifacts,
            accepted_by="iteration_versioning",
        )
        _, lineage = append_handoff_attempt(lineage, package_handoff)
        # Official candidate unchanged
        official = record.get("officialCandidateRef") or ""
        patch = {
            "status": "succeeded",
            "completionKind": "stopped",
            "terminalReason": terminal,
            "runtimeCurrentNodeIds": [],
            "officialCandidateRef": official,
            "handoffs": lineage,
            "resultPackageRef": f"rrp:{run_id}:{decision.get('decisionId')}",
        }
        return {
            "decision": decision,
            "patch": patch,
            "handoffs_to_append": [],
            "human_task": None,
            "child_run": None,
            "error": None,
            "replace_handoffs": lineage,
            "official_candidate_unchanged": True,
        }

    raise IterationDecisionError(f"unhandled kind {kind}", code="unhandled_kind")
