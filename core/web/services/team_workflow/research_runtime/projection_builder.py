"""Pure Snapshot projection builder — no route/request, no writes."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from core.research.workflow.contracts import CommandOffer, ResearchWorkflowSnapshot
from core.research.workflow.contracts.workflow_snapshot import (
    AgentBindingRef,
    AgentBindingSummary,
    BudgetReceiptRef,
    BudgetSummary,
    CommandOfferAuthorization,
    HandoffRefSummary,
    HandoffSummary,
    HumanTaskSummary,
    KnowledgeInvocationBadge,
    KnowledgeInvocationRecentSummary,
    NodeAttemptSummary,
    WorkflowRunSummary,
)
from core.research.workflow.ledger.records import NodeAttemptRecord, RunRecord
from core.research.workflow.models import WorkflowDefinition

from ..active_discussion_anchor import project_active_discussion_anchor
from .blocked_reason import format_blocked_reason, parse_problem_json
from .command_offers.retry_node import (
    succeeded_node_rerun_available,
    succeeded_node_rerun_target,
)
from .knowledge_invocation_projection import project_knowledge_invocation_badges
from .knowledge_rollout import knowledge_sideflow_mode
from .offer_authorization import build_offer_authorizations


@dataclass(frozen=True, slots=True)
class ProjectionInputs:
    run: RunRecord
    definition: WorkflowDefinition
    attempts: tuple[NodeAttemptRecord, ...]
    pending_human_tasks: tuple[HumanTaskSummary | Mapping[str, Any], ...]
    handoffs: tuple[Mapping[str, Any], ...]
    budget_receipts: tuple[Mapping[str, Any], ...]
    command_offers: tuple[CommandOffer, ...]
    latest_event_sequence: int
    generated_at: str
    artifact_receipts: tuple[Mapping[str, Any] | Sequence[Any], ...] = ()
    delivery_status: str | None = None
    delivery_artifact: Mapping[str, Any] | None = None
    launch_context: Mapping[str, Any] | None = None
    # Discussion authority is deliberately supplied as already-loaded
    # projections.  The builder never reaches into meeting/chat stores and
    # therefore remains a pure read-model function.
    discussion_projection: Mapping[str, Any] | None = None
    discussion_meetings: Any = None
    discussion_rooms: Any = None
    # Execution anchors for the latest attempt per node (already normalized to
    # mappings by the query layer).  They let currentTask surface the live
    # Agent task identity during dispatch instead of only after final commit.
    execution_anchors: tuple[Mapping[str, Any], ...] = ()
    # Knowledge-sideflow invocation rows for this run (already loaded by the
    # query layer; the builder stays a pure function over its inputs).
    knowledge_invocations: tuple[Any, ...] = ()
    # Real per-child-run node states (childRunId → sideflow nodeId → status),
    # loaded by the query layer from the child run's node attempts.  These
    # give the five-node progress card its true middle-node facts.
    knowledge_child_node_states: Mapping[str, Mapping[str, str]] = field(
        default_factory=dict
    )
    # Offer authorization signing: explicit key/now keep the builder
    # deterministic for tests; ``None`` resolves the server control secret and
    # wall clock.
    authorization_key: str | None = None
    now_ms: int | None = None
    # Definition resolution diagnostic from the query layer ("pinned" |
    # "legacy_default" | "degraded"); surfaced verbatim in the snapshot.
    definition_resolution: str = "pinned"


def build_research_workflow_snapshot(inputs: ProjectionInputs) -> ResearchWorkflowSnapshot:
    run = inputs.run
    node_attempts: dict[str, list[NodeAttemptSummary]] = {}
    for attempt in inputs.attempts:
        node_attempts.setdefault(attempt.node_id, []).append(_attempt_summary(attempt))

    active_ids = _active_node_ids(run, inputs.attempts)
    canonical_active_node_id = active_ids[0] if active_ids else None
    run_summary = _run_summary_with_active_block(
        run,
        inputs.attempts,
        active_node_id=canonical_active_node_id,
    )
    if run_summary.active_node_id != canonical_active_node_id:
        run_summary = replace(
            run_summary,
            active_node_id=canonical_active_node_id,
        )

    binding_refs = tuple(
        sorted(
            {
                attempt.binding_snapshot_id
                for attempt in inputs.attempts
                if attempt.binding_snapshot_id
            }
        )
    )
    frozen_bindings = frozen_agent_bindings(run.input_snapshot_json)
    binding_ids = tuple(
        dict.fromkeys(
            [
                *binding_refs,
                *(item.snapshot_id for item in frozen_bindings if item.snapshot_id),
            ]
        )
    )

    safety_limits = _loads(run.safety_limits_json)
    current_task = _current_task(
        run=run,
        definition=inputs.definition,
        attempts=inputs.attempts,
        pending_human_tasks=inputs.pending_human_tasks,
        active_node_ids=active_ids,
        command_offers=inputs.command_offers,
        safety_limits=safety_limits,
        execution_anchors=inputs.execution_anchors,
    )
    retry = _retry_summary(
        run=run,
        attempts=inputs.attempts,
        current_task=current_task,
        command_offers=inputs.command_offers,
    )
    recovery = _recovery_summary(
        run=run,
        attempts=inputs.attempts,
        current_task=current_task,
        retry=retry,
    )
    if current_task is not None:
        current_task = {**current_task, "recovery": dict(recovery)}
    progress = _progress_summary(
        run=run,
        run_summary=run_summary,
        definition=inputs.definition,
        attempts=inputs.attempts,
        active_node_ids=active_ids,
        current_task=current_task,
        command_offers=inputs.command_offers,
    )
    launch_context = _normalize_launch_context(inputs.launch_context, run)
    discussion_anchor = _discussion_anchor(
        inputs,
        launch_context=launch_context,
    )
    if discussion_anchor is not None:
        # ``launchContext`` is an existing additive projection envelope.  Keep
        # the formal snapshot DTO stable while making the server-authored
        # anchor available to current clients.  A route may promote this
        # value to a top-level response field without creating another rule.
        launch_context["activeDiscussionAnchor"] = discussion_anchor

    invocation_badges = _invocation_badges(inputs)
    command_authorizations = _offer_authorizations(inputs)

    sideflow_mode = knowledge_sideflow_mode()
    return ResearchWorkflowSnapshot(
        run=run_summary,
        definition=inputs.definition.to_dict(),
        node_attempts={
            node_id: tuple(items) for node_id, items in node_attempts.items()
        },
        active_node_ids=active_ids,
        pending_human_tasks=tuple(
            _coerce_human_task(item) for item in inputs.pending_human_tasks
        ),
        command_offers=inputs.command_offers,
        handoff_summary=_handoff_summary(inputs.handoffs),
        agent_binding_summary=AgentBindingSummary(
            binding_snapshot_set_id=run.binding_snapshot_set_id,
            binding_snapshot_ids=binding_ids,
            count=len(binding_ids),
            bindings=frozen_bindings,
        ),
        budget_summary=BudgetSummary(
            safety_limits=safety_limits,
            receipt_refs=tuple(
                BudgetReceiptRef(
                    receipt_id=_as_optional_str(item.get("receiptId")),
                    node_run_id=_as_optional_str(item.get("nodeRunId")),
                    status=_as_optional_str(item.get("status")),
                    policy_hash=_as_optional_str(item.get("policyHash")),
                )
                for item in inputs.budget_receipts
            ),
            receipt_count=len(inputs.budget_receipts),
        ),
        latest_event_sequence=int(inputs.latest_event_sequence),
        generated_at=inputs.generated_at,
        schema_version=2,
        current_task=current_task,
        progress=progress,
        retry=retry,
        recovery=recovery,
        artifact_summary=_artifact_summary(
            inputs.artifact_receipts,
            delivery_artifact=inputs.delivery_artifact,
        ),
        delivery_status=_normalize_delivery_status(inputs.delivery_status),
        launch_context=launch_context,
        invocation_badges=invocation_badges,
        command_authorizations=command_authorizations,
        definition_resolution=str(inputs.definition_resolution or "pinned"),
        knowledge_sideflow_mode=sideflow_mode,
        stage_one=_stage_one_projection(inputs, sideflow_mode=sideflow_mode),
    )


def _stage_one_projection(
    inputs: ProjectionInputs,
    *,
    sideflow_mode: str,
) -> dict[str, Any]:
    """Describe Stage 1 surfaces from pinned server facts only."""

    node_ids = {
        str(getattr(node, "node_id", "") or "")
        for node in inputs.definition.nodes
    }
    knowledge_topology = "embedded" if "knowledge_handoff" in node_ids else "child_workflow"
    accepted = (
        str(inputs.run.completion_kind or "") == "stage_one_g1_accepted"
        and str(inputs.run.terminal_reason or "") == "STAGE1_G1_ACCEPTED"
    )
    return {
        "authority": "challenge_program",
        "completionState": "STAGE1_G1_ACCEPTED" if accepted else "pending",
        "formalTopology": {
            "workflowId": str(inputs.run.workflow_id or ""),
            "workflowVersionId": str(inputs.run.workflow_version_id or ""),
            "definitionResolution": str(inputs.definition_resolution or "pinned"),
            "role": "execution_authority",
        },
        "hypothesisView": {
            "nodePrefix": "hf_",
            "role": "operator_projection",
        },
        "knowledgeFlow": {
            "topology": knowledge_topology,
            "rolloutMode": str(sideflow_mode or "off"),
            "role": (
                "formal_graph_nodes"
                if knowledge_topology == "embedded"
                else "optional_child_workflow"
            ),
        },
    }


def _invocation_badges(
    inputs: ProjectionInputs,
) -> dict[str, KnowledgeInvocationBadge]:
    """Knowledge invocation aggregates keyed by parent node id (additive)."""
    if not inputs.knowledge_invocations:
        return {}
    raw_badges = project_knowledge_invocation_badges(inputs.knowledge_invocations)
    badges: dict[str, KnowledgeInvocationBadge] = {}
    for node_id, payload in raw_badges.items():
        latest_row = payload.get("latest")
        latest = (
            KnowledgeInvocationRecentSummary(
                invocation_id=str(latest_row.get("invocationId") or ""),
                parent_node_id=str(latest_row.get("parentNode_id") or node_id),
                status=latest_row.get("status"),
                handoff_state=latest_row.get("handoffState"),
                current_knowledge_node_id=latest_row.get("currentKnowledgeNodeId"),
                knowledge_child_run_id=latest_row.get("knowledgeChildRunId"),
                knowledge_package_ref=latest_row.get("knowledgePackageRef"),
                package_content_hash=latest_row.get("packageContentHash"),
                error_summary=latest_row.get("errorSummary"),
                created_at_ms=int(latest_row.get("createdAtMs") or 0),
                updated_at_ms=int(latest_row.get("updatedAtMs") or 0),
                child_node_states=dict(
                    inputs.knowledge_child_node_states.get(
                        str(latest_row.get("knowledgeChildRunId") or ""), {}
                    )
                ),
            )
            if isinstance(latest_row, Mapping)
            else None
        )
        badges[node_id] = KnowledgeInvocationBadge(
            node_id=node_id,
            total_count=int(payload.get("totalCount") or 0),
            running_count=int(payload.get("runningCount") or 0),
            awaiting_handoff_count=int(payload.get("awaitingHandoffCount") or 0),
            absorbed_count=int(payload.get("absorbedCount") or 0),
            failed_count=int(payload.get("failedCount") or 0),
            latest=latest,
        )
    return badges


def _offer_authorizations(
    inputs: ProjectionInputs,
) -> tuple[CommandOfferAuthorization, ...]:
    """Server-signed executability envelopes for the canonical offers.

    ``signedAt`` anchors to the snapshot's own ``generated_at`` so identical
    inputs rebuild byte-identical snapshots (deterministic read model); the
    wall clock is only the fallback when the stamp cannot be parsed.
    """
    if not inputs.command_offers:
        return ()
    envelopes = build_offer_authorizations(
        run_id=inputs.run.run_id,
        run_version=inputs.run.run_version,
        offers=inputs.command_offers,
        now_ms=inputs.now_ms if inputs.now_ms is not None else _ms_from_iso(
            inputs.generated_at
        ),
        key=inputs.authorization_key,
    )
    return tuple(
        CommandOfferAuthorization(
            idempotency_key=str(item.get("idempotencyKey") or ""),
            command=str(item.get("command") or ""),
            node_id=item.get("nodeId"),
            requires_operator=bool(item.get("requiresOperator")),
            authorization_status=str(item.get("authorizationStatus") or ""),
            authorization_reason=str(item.get("authorizationReason") or ""),
            signed_at_ms=int(item.get("signedAt") or 0),
            expires_at_ms=int(item.get("expiresAt") or 0),
            expected_run_version=int(item.get("expectedRunVersion") or 0),
            signature=str(item.get("signature") or ""),
        )
        for item in envelopes
    )


def _ms_from_iso(value: str) -> int | None:
    from datetime import datetime

    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
    except (TypeError, ValueError):
        return None


_LIVE_ATTEMPT_STATUS = frozenset(
    {"starting", "dispatching", "running", "waiting_human"}
)


def _active_node_ids(
    run: RunRecord,
    attempts: Sequence[NodeAttemptRecord],
) -> tuple[str, ...]:
    """Project one canonical active-node set from durable attempt state.

    A successor can become live before the run row's convenience pointer is
    updated.  Live attempts are the stronger fact; the pointer is used only
    while no live attempt exists (for example, a newly created or failed run).
    """
    live_ids = tuple(
        dict.fromkeys(
            attempt.node_id
            for attempt in attempts
            if attempt.status in _LIVE_ATTEMPT_STATUS
        )
    )
    if live_ids:
        active = str(run.active_node_id or "").strip()
        if active in live_ids:
            return (active, *(node_id for node_id in live_ids if node_id != active))
        return live_ids
    active = str(run.active_node_id or "").strip()
    return (active,) if active else ()


_TERMINAL_RUN_STATUS = frozenset(
    {"succeeded", "failed", "cancelled", "archived"}
)


def _run_summary_with_active_block(
    run: RunRecord,
    attempts: Sequence[NodeAttemptRecord],
    *,
    active_node_id: str | None = None,
) -> WorkflowRunSummary:
    """Surface active-node blocks even when ledger run.status is still running."""
    summary = _run_summary(run)
    if run.status in _TERMINAL_RUN_STATUS:
        return summary
    active = str(active_node_id or run.active_node_id or "")
    if not active:
        return summary
    latest: NodeAttemptRecord | None = None
    for attempt in attempts:
        if attempt.node_id != active:
            continue
        if latest is None or int(attempt.attempt) >= int(latest.attempt):
            latest = attempt
    if latest is None or latest.status != "blocked":
        return summary
    reason = format_blocked_reason(
        parse_problem_json(latest.problem_json),
        fallback=summary.blocked_reason,
    ) or summary.blocked_reason
    return replace(summary, status="blocked", blocked_reason=reason)


def _latest_attempt_by_node(
    attempts: Sequence[NodeAttemptRecord],
) -> dict[str, NodeAttemptRecord]:
    latest: dict[str, NodeAttemptRecord] = {}
    for attempt in attempts:
        prior = latest.get(attempt.node_id)
        if prior is None or int(attempt.attempt) >= int(prior.attempt):
            latest[attempt.node_id] = attempt
    return latest


def _definition_node(definition: WorkflowDefinition, node_id: str | None) -> Any | None:
    wanted = str(node_id or "").strip()
    if not wanted:
        return None
    return next((node for node in definition.nodes if node.nodeId == wanted), None)


def _human_task_for_node(
    pending_human_tasks: Sequence[HumanTaskSummary | Mapping[str, Any]],
    *,
    node_id: str | None,
    node_run_id: str | None,
) -> HumanTaskSummary | Mapping[str, Any] | None:
    current_node_run_id = str(node_run_id or "").strip()
    for item in pending_human_tasks:
        item_node_id = (
            item.node_id if isinstance(item, HumanTaskSummary) else item.get("nodeId")
        )
        item_node_run_id = (
            item.node_run_id
            if isinstance(item, HumanTaskSummary)
            else item.get("nodeRunId")
        )
        if current_node_run_id:
            if str(item_node_run_id or "").strip() == current_node_run_id:
                return item
            # A known attempt identity is authoritative. Do not fall back to
            # nodeId and accidentally attach an older pending human task.
            continue
        if node_id and str(item_node_id or "").strip() == node_id:
            return item
    return None


def _task_id(item: HumanTaskSummary | Mapping[str, Any] | None) -> str | None:
    if item is None:
        return None
    value = item.task_id if isinstance(item, HumanTaskSummary) else item.get("taskId")
    return _as_optional_str(value)


def _execution_anchor_by_node_run(
    execution_anchors: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    by_node_run: dict[str, Mapping[str, Any]] = {}
    for item in execution_anchors:
        if not isinstance(item, Mapping):
            continue
        node_run_id = _as_optional_str(item.get("nodeRunId"))
        if node_run_id:
            by_node_run[node_run_id] = item
    return by_node_run


def _current_task(
    *,
    run: RunRecord,
    definition: WorkflowDefinition,
    attempts: Sequence[NodeAttemptRecord],
    pending_human_tasks: Sequence[HumanTaskSummary | Mapping[str, Any]],
    active_node_ids: Sequence[str],
    command_offers: Sequence[CommandOffer],
    safety_limits: Mapping[str, Any],
    execution_anchors: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any] | None:
    latest_by_node = _latest_attempt_by_node(attempts)
    anchor_by_node_run = _execution_anchor_by_node_run(execution_anchors)

    def anchor_for(node_attempt: NodeAttemptRecord | None) -> Mapping[str, Any] | None:
        if node_attempt is None:
            return None
        return anchor_by_node_run.get(node_attempt.node_run_id)

    active_node_id = str(
        active_node_ids[0] if active_node_ids else run.active_node_id or ""
    ).strip()
    node_id = active_node_id or None
    latest = latest_by_node.get(node_id) if node_id else None
    task = _human_task_for_node(
        pending_human_tasks,
        node_id=node_id,
        node_run_id=latest.node_run_id if latest is not None else None,
    )
    start_offer = _available_offer(
        command_offers,
        command="start_node",
        node_id=node_id,
        expected_run_version=run.run_version,
    )
    rerun_target = succeeded_node_rerun_target(run)
    if rerun_target and rerun_target != node_id:
        rerun_latest = latest_by_node.get(rerun_target)
        if succeeded_node_rerun_available(
            node_id=rerun_target, latest=rerun_latest, run=run
        ):
            # The run is blocked because this idempotent upstream node
            # "succeeded" without materializing its artifacts; re-running it
            # owns the recovery, so it — not the wedged successor — is the
            # user-facing current task.
            node_id = rerun_target
            latest = rerun_latest
            task = None
            start_offer = _available_offer(
                command_offers,
                command="start_node",
                node_id=node_id,
                expected_run_version=run.run_version,
            )
    if (
        run.status in {"created", "running"}
        and start_offer is None
        and latest is None
        and task is None
    ):
        # A created/running run can have no accepted attempt yet. In that
        # window the only authoritative current task is an executable
        # start_node offer scoped to this run version.
        start_offer = _available_offer(
            command_offers,
            command="start_node",
            node_id=None,
            expected_run_version=run.run_version,
        )
        if start_offer is not None:
            node_id = _as_optional_str(start_offer.node_id)
            latest = latest_by_node.get(node_id or "")
            task = _human_task_for_node(
                pending_human_tasks,
                node_id=node_id,
                node_run_id=latest.node_run_id if latest is not None else None,
            )

    if run.status == "succeeded":
        latest = _latest_terminal_attempt(attempts)
        node_id = latest.node_id if latest is not None else None
        task = _human_task_for_node(
            pending_human_tasks,
            node_id=node_id,
            node_run_id=latest.node_run_id if latest is not None else None,
        )
        return _task_projection(
            run=run,
            definition=definition,
            node_id=node_id,
            latest=latest,
            task=task,
            state="completed",
            safety_limits=safety_limits,
            identity_offer=None,
            problem={},
            status="succeeded",
            anchor=anchor_for(latest),
        )

    if run.status in _TERMINAL_RUN_STATUS:
        problem = _problem_mapping(
            latest.problem_json if latest is not None else None,
            run.blocked_problem_json,
        )
        return _task_projection(
            run=run,
            definition=definition,
            node_id=node_id,
            latest=latest,
            task=task,
            state="blocked_terminal",
            safety_limits=safety_limits,
            identity_offer=None,
            problem=problem,
            status=run.status,
            anchor=anchor_for(latest),
        )

    if latest is None and task is None and start_offer is None:
        if run.status not in {"blocked", "reconciliation_required"}:
            # No formal runtime attempt and no executable offer means there is
            # no authority for a CTA/current task projection.
            return None
        return _task_projection(
            run=run,
            definition=definition,
            node_id=node_id,
            latest=None,
            task=None,
            state="blocked_terminal",
            safety_limits=safety_limits,
            identity_offer=None,
            problem=_problem_mapping(run.blocked_problem_json),
            status=run.status,
        )

    problem = _problem_mapping(
        latest.problem_json if latest is not None else None,
        run.blocked_problem_json,
    )
    retry_offer = _available_offer(
        command_offers,
        command="retry_node",
        node_id=node_id,
        expected_run_version=run.run_version,
    )
    state = _task_state(
        run=run,
        latest=latest,
        task=task,
        start_offer=start_offer,
        retry_offer=retry_offer,
        problem=problem,
    )
    if state is None:
        # A succeeded attempt with no successor authority is not a current
        # task while the run itself is still live.
        return None
    identity_offer = (
        retry_offer
        if state == "blocked_retryable" and retry_offer is not None
        else start_offer or retry_offer
    )
    return _task_projection(
        run=run,
        definition=definition,
        node_id=node_id,
        latest=latest,
        task=task,
        state=state,
        safety_limits=safety_limits,
        identity_offer=identity_offer,
        problem=problem,
        status=latest.status if latest is not None else run.status,
        anchor=anchor_for(latest),
    )


def _available_offer(
    offers: Sequence[CommandOffer],
    *,
    command: str,
    node_id: str | None,
    expected_run_version: int,
) -> CommandOffer | None:
    for offer in offers:
        if _offer_command_value(offer) != command or not offer.available:
            continue
        if int(offer.expected_run_version) != int(expected_run_version):
            continue
        if node_id is not None and str(offer.node_id or "") != node_id:
            continue
        if node_id is None and not str(offer.node_id or "").strip():
            continue
        return offer
    return None


def _latest_terminal_attempt(
    attempts: Sequence[NodeAttemptRecord],
) -> NodeAttemptRecord | None:
    if not attempts:
        return None
    return max(
        attempts,
        key=lambda item: (int(item.updated_at_ms), int(item.attempt), item.node_run_id),
    )


def _task_state(
    *,
    run: RunRecord,
    latest: NodeAttemptRecord | None,
    task: HumanTaskSummary | Mapping[str, Any] | None,
    start_offer: CommandOffer | None,
    retry_offer: CommandOffer | None,
    problem: Mapping[str, Any],
) -> str | None:
    if run.status == "waiting_human" or (
        latest is not None and latest.status == "waiting_human"
    ) or task is not None:
        return "waiting_user"
    if run.status in {"blocked", "reconciliation_required"} or (
        latest is not None and latest.status in {"blocked", "failed", "cancelled"}
    ):
        explicitly_unavailable = (
            "retryable" in problem and not bool(problem.get("retryable"))
        )
        return (
            "blocked_retryable"
            if retry_offer is not None and not explicitly_unavailable
            else "blocked_terminal"
        )
    if latest is not None and latest.status in {
        "starting",
        "dispatching",
        "running",
    }:
        return "auto_running"
    # An executable start offer is a user-facing command, not evidence that
    # the node is already executing. Only a live attempt above may claim
    # system-owned auto-running state.
    if start_offer is not None:
        return "waiting_user"
    return None


def _task_projection(
    *,
    run: RunRecord,
    definition: WorkflowDefinition,
    node_id: str | None,
    latest: NodeAttemptRecord | None,
    task: HumanTaskSummary | Mapping[str, Any] | None,
    state: str,
    safety_limits: Mapping[str, Any],
    identity_offer: CommandOffer | None,
    problem: Mapping[str, Any],
    status: str,
    anchor: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    node = _definition_node(definition, node_id)
    actor_kind = latest.actor_kind if latest is not None else (
        node.actorKind.value if node is not None else None
    )
    stage_id = node.stageId.value if node is not None else None
    scoped_retry_blocker_ids = (
        identity_offer.blocker_ids
        if identity_offer is not None
        and _offer_command_value(identity_offer) == "retry_node"
        else ()
    )
    blocked_reason = _structured_blocked_reason(
        problem,
        terminal_reason=run.terminal_reason if state == "blocked_terminal" else None,
        retryable=state == "blocked_retryable",
        offer_blocker_ids=scoped_retry_blocker_ids,
    )
    task_id = _task_id(task)
    node_run_id = latest.node_run_id if latest is not None else None
    anchor_payload = anchor if isinstance(anchor, Mapping) else {}
    anchor_id = _as_optional_str(anchor_payload.get("anchorId")) or (
        latest.execution_anchor_id if latest is not None else None
    )
    anchor_task_id = _as_optional_str(anchor_payload.get("taskId"))
    anchor_session_id = _as_optional_str(anchor_payload.get("sessionId"))
    anchor_turn_id = _as_optional_str(anchor_payload.get("turnId"))
    offer_idempotency_key = (
        _as_optional_str(identity_offer.idempotency_key)
        if identity_offer is not None
        else None
    )
    return {
        "key": task_id or anchor_task_id or node_run_id or offer_idempotency_key or f"{run.run_id}:{state}",
        "nodeId": node_id,
        "stageId": stage_id,
        "nodeRunId": node_run_id,
        "attempt": latest.attempt if latest is not None else None,
        "actorKind": actor_kind,
        "taskId": task_id or anchor_task_id,
        "sessionId": anchor_session_id,
        "turnId": anchor_turn_id,
        "executionAnchorId": anchor_id,
        "status": "blocked" if state in {"blocked_retryable", "blocked_terminal"} else status,
        "state": state,
        "kind": (
            "human_gate"
            if actor_kind == "human"
            else "node"
            if node is not None
            else "run"
        ),
        "label": node.label if node is not None else None,
        "detail": format_blocked_reason(problem) or None,
        "responsibility": _task_responsibility(state),
        "maxAttempts": _max_attempts(safety_limits, node_id),
        # No durable effect contract currently exists for automatic successor
        # execution. CommandOffer is a user-submitted mutation, not an effect.
        "automaticNextStep": None,
        "blockedReason": blocked_reason,
        "recovery": {
            "status": "terminal" if state == "blocked_terminal" else (
                "retryable" if state == "blocked_retryable" else "none"
            ),
            "retryable": state == "blocked_retryable",
            "code": blocked_reason.get("code") if blocked_reason else None,
            "detail": blocked_reason.get("detail") if blocked_reason else None,
            "retryScope": "none",
            "recoveryPoint": None,
            "nextRetryAt": None,
            "requiresOperator": state == "blocked_terminal",
            "afterSubmit": None,
        },
        "authority": "formal_runtime",
    }


def _structured_blocked_reason(
    problem: Mapping[str, Any],
    *,
    terminal_reason: str | None,
    retryable: bool,
    offer_blocker_ids: Sequence[str] = (),
) -> dict[str, Any] | None:
    code = str(problem.get("code") or terminal_reason or "").strip()
    detail = problem.get("detail")
    failure_class = _as_optional_str(problem.get("failureClass"))
    message = _as_optional_str(problem.get("message"))
    blocker_ids = tuple(
        dict.fromkeys(
            [
                *_explicit_blocker_ids(problem.get("blockerIds")),
                *(
                    str(value).strip()
                    for value in offer_blocker_ids
                    if str(value).strip()
                ),
            ]
        )
    )
    if not code and detail is None and failure_class is None and message is None and not blocker_ids:
        return None
    return {
        "code": code or None,
        "detail": None if detail is None else str(detail),
        "retryable": bool(problem.get("retryable"))
        if "retryable" in problem
        else bool(retryable),
        "failureClass": failure_class,
        "message": message,
        "blockerIds": list(blocker_ids),
    }


def _explicit_blocker_ids(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(
        dict.fromkeys(str(item).strip() for item in value if str(item).strip())
    )


def _task_responsibility(state: str) -> str:
    if state in {"auto_running", "completed"}:
        return "system"
    if state in {"waiting_user", "blocked_retryable"}:
        return "user"
    return "operator"


def _max_attempts(safety_limits: Mapping[str, Any], node_id: str | None) -> int | None:
    candidates: list[Any] = []
    if node_id:
        for key in ("maxAttemptsByNode", "max_attempts_by_node"):
            by_node = safety_limits.get(key)
            if isinstance(by_node, Mapping):
                candidates.append(by_node.get(node_id))
    candidates.extend(
        safety_limits.get(key)
        for key in ("maxAttempts", "max_attempts")
    )
    for value in candidates:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return None


def _progress_summary(
    *,
    run: RunRecord,
    run_summary: WorkflowRunSummary,
    definition: WorkflowDefinition,
    attempts: Sequence[NodeAttemptRecord],
    active_node_ids: Sequence[str],
    current_task: Mapping[str, Any] | None,
    command_offers: Sequence[CommandOffer],
) -> dict[str, Any]:
    latest = _latest_attempt_by_node(attempts)
    all_node_ids = tuple(node.nodeId for node in definition.nodes)
    completed = (
        all_node_ids
        if run.status == "succeeded"
        else tuple(
            node.nodeId
            for node in definition.nodes
            if latest.get(node.nodeId) is not None
            and latest[node.nodeId].status == "succeeded"
        )
    )
    blocked = tuple(
        node.nodeId
        for node in definition.nodes
        if latest.get(node.nodeId) is not None
        and latest[node.nodeId].status in {"blocked", "failed", "cancelled"}
    )
    total = len(definition.nodes)
    percent = 100 if run.status == "succeeded" else (
        round((len(completed) / total) * 100) if total else 0
    )
    status = str(current_task.get("state") or "") if current_task else ""
    if not status:
        status = _task_state(
            run=run,
            latest=latest.get(active_node_ids[0]) if active_node_ids else None,
            task=None,
            start_offer=_available_offer(
                command_offers,
                command="start_node",
                node_id=active_node_ids[0] if active_node_ids else None,
                expected_run_version=run.run_version,
            ),
            retry_offer=None,
            problem=_problem_mapping(run.blocked_problem_json),
        ) or (
            "not_started"
            if run.status == "created" and not attempts
            else "unknown"
        )
    current_stage_id = _stage_id_for_node(definition, (
        current_task.get("nodeId") if current_task else (
            active_node_ids[0] if active_node_ids else None
        )
    ))
    if run_summary.status == "succeeded":
        status = "completed"
    stages: list[dict[str, Any]] = []
    for stage in definition.stages:
        stage_nodes = set(stage.nodeIds)
        stage_completed = sum(1 for node_id in completed if node_id in stage_nodes)
        stage_blocked = sum(1 for node_id in blocked if node_id in stage_nodes)
        if stage_completed == len(stage_nodes) and stage_nodes:
            stage_state = "completed"
        elif stage_blocked:
            stage_state = "blocked"
        elif current_stage_id == stage.stageId.value:
            stage_state = "current"
        else:
            stage_state = "upcoming"
        stages.append(
            {
                "id": stage.stageId.value,
                "completed": stage_completed,
                "total": len(stage_nodes),
                "blocked": stage_blocked,
                "state": stage_state,
            }
        )
    return {
        "completedNodes": len(completed),
        "totalNodes": total,
        "blockedNodes": len(blocked),
        "currentStageId": current_stage_id,
        "stages": stages,
        "completedNodeIds": list(completed),
        "blockedNodeIds": list(blocked),
        "completed": len(completed),
        "total": total,
        "percent": percent,
        "currentNodeId": str(active_node_ids[0]).strip() if active_node_ids else None,
        "status": status,
    }


def _stage_id_for_node(
    definition: WorkflowDefinition,
    node_id: str | None,
) -> str | None:
    node = _definition_node(definition, node_id)
    return node.stageId.value if node is not None else None


def _offer_command_value(offer: CommandOffer) -> str:
    command = getattr(offer.command, "value", offer.command)
    return str(command or "").strip()


def _retry_summary(
    *,
    run: RunRecord,
    attempts: Sequence[NodeAttemptRecord],
    current_task: Mapping[str, Any] | None,
    command_offers: Sequence[CommandOffer],
) -> dict[str, Any]:
    node_id = _as_optional_str(current_task.get("nodeId")) if current_task else None
    offer = _available_offer(
        command_offers,
        command="retry_node",
        node_id=node_id,
        expected_run_version=run.run_version,
    )
    latest = _latest_attempt_by_node(attempts).get(node_id or "")
    problem = _problem_mapping(
        latest.problem_json if latest is not None else None,
        run.blocked_problem_json,
    )
    explicitly_unavailable = "retryable" in problem and not bool(problem.get("retryable"))
    available = bool(
        offer is not None
        and offer.available
        and run.status not in _TERMINAL_RUN_STATUS
        and not explicitly_unavailable
    )
    return {
        "available": available,
        "command": _offer_command_value(offer) if offer is not None else None,
        "nodeId": node_id,
        "reasonCode": (
            str(offer.reason_code or "retry_not_available")
            if offer is not None
            else "retry_not_available"
        ),
        "idempotencyKey": offer.idempotency_key if offer is not None else None,
        "expectedRunVersion": (
            int(offer.expected_run_version) if offer is not None else None
        ),
    }


def _recovery_summary(
    *,
    run: RunRecord,
    attempts: Sequence[NodeAttemptRecord],
    current_task: Mapping[str, Any] | None,
    retry: Mapping[str, Any],
) -> dict[str, Any]:
    node_id = _as_optional_str(current_task.get("nodeId")) if current_task else None
    latest = _latest_attempt_by_node(attempts).get(node_id or "")
    problem = _problem_mapping(
        latest.problem_json if latest is not None else None,
        run.blocked_problem_json,
    )
    blocked = run.status in {
        "blocked",
        "failed",
        "cancelled",
        "archived",
        "reconciliation_required",
    }
    if current_task is not None and current_task.get("state") in {
        "blocked_retryable",
        "blocked_terminal",
    }:
        blocked = True
    if not blocked:
        return {
            "status": "none",
            "retryable": False,
            "code": None,
            "detail": None,
            "retryScope": "none",
            "recoveryPoint": None,
            "nextRetryAt": None,
            "requiresOperator": False,
            "afterSubmit": None,
        }
    is_retryable = bool(retry.get("available"))
    retry_node_id = _as_optional_str(retry.get("nodeId")) if is_retryable else None
    return {
        "status": "retryable" if is_retryable else "terminal",
        "retryable": is_retryable,
        "code": str(problem.get("code") or "") or None,
        "detail": str(problem.get("detail") or "") or None,
        "retryScope": "task" if retry_node_id else "none",
        "recoveryPoint": retry_node_id,
        "nextRetryAt": None,
        "requiresOperator": bool(
            current_task is not None
            and current_task.get("state") == "blocked_terminal"
        ),
        "afterSubmit": None,
    }


def _problem_mapping(*raw_values: str | None) -> dict[str, Any]:
    for raw in raw_values:
        parsed = parse_problem_json(raw)
        if parsed:
            return parsed
    return {}


def _artifact_summary(
    receipts: Sequence[Mapping[str, Any] | Sequence[Any]],
    *,
    delivery_artifact: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    refs: list[dict[str, Any]] = []
    kinds: list[str] = []
    for item in receipts:
        if isinstance(item, Mapping):
            canonical = item.get("canonicalRef")
            if canonical is None:
                canonical = item.get("uri")
            if canonical is None:
                canonical = _canonical_ref(item.get("canonicalRefJson"))
            kind = str(item.get("artifactKind") or item.get("kind") or "")
            ref = {
                "receiptId": _as_optional_str(item.get("receiptId")),
                "nodeRunId": _as_optional_str(item.get("nodeRunId")),
                "kind": kind,
                "version": str(
                    item.get("artifactVersion") or item.get("version") or ""
                ),
                "canonicalRef": _as_optional_str(canonical),
                "sha256": str(item.get("sha256") or item.get("contentHash") or ""),
                "domainRevision": str(item.get("domainRevision") or ""),
                "materialized": bool(item.get("materialized")),
                "verifiedAtMs": int(item.get("verifiedAtMs") or 0),
            }
        else:
            row = list(item)
            raw_ref = row[5] if len(row) > 5 else None
            kind = str(row[4] or "") if len(row) > 4 else ""
            ref = {
                "receiptId": _as_optional_str(row[0] if len(row) > 0 else None),
                "nodeRunId": _as_optional_str(row[2] if len(row) > 2 else None),
                "kind": kind,
                "version": str(row[6] or "") if len(row) > 6 else "",
                "canonicalRef": _as_optional_str(_canonical_ref(raw_ref)),
                "sha256": str(row[7] or "") if len(row) > 7 else "",
                "domainRevision": str(row[8] or "") if len(row) > 8 else "",
                "materialized": bool(row[9]) if len(row) > 9 else False,
                "verifiedAtMs": int(row[10] or 0) if len(row) > 10 else 0,
            }
        if kind and kind not in kinds:
            kinds.append(kind)
        refs.append(ref)
    final_artifact_id: str | None = None
    final_artifact_locator: str | None = None
    if isinstance(delivery_artifact, Mapping):
        final_artifact_locator = _as_optional_str(
            delivery_artifact.get("artifactRef")
            or delivery_artifact.get("canonicalRef")
        )
        event_artifact_id = _as_optional_str(
            delivery_artifact.get("artifactId")
        )
        if event_artifact_id:
            final_artifact_id = event_artifact_id
        elif final_artifact_locator:
            matching = next(
                (
                    item
                    for item in refs
                    if item.get("canonicalRef") == final_artifact_locator
                ),
                None,
            )
            if matching is not None:
                final_artifact_id = _as_optional_str(matching.get("receiptId"))
    if final_artifact_locator is None:
        # A receipt is only a final-artifact authority when its kind is the
        # dedicated delivery result. Never select an arbitrary last receipt.
        delivery_refs = [
            item
            for item in refs
            if item.get("kind") == "delivery_orchestration_result"
        ]
        if len(delivery_refs) == 1:
            final_artifact_locator = _as_optional_str(
                delivery_refs[0].get("canonicalRef")
            )
            final_artifact_id = _as_optional_str(delivery_refs[0].get("receiptId"))
    return {
        "count": len(refs),
        "materializedCount": sum(1 for item in refs if item["materialized"]),
        "kinds": kinds,
        "refs": refs,
        "finalArtifactId": final_artifact_id,
        "finalArtifactLocator": final_artifact_locator,
    }


def _canonical_ref(raw: Any) -> str:
    if isinstance(raw, Mapping):
        return str(raw.get("canonicalRef") or "").strip()
    try:
        payload = json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        return ""
    return str(payload.get("canonicalRef") or "") if isinstance(payload, Mapping) else ""


def _launch_context(run: RunRecord) -> dict[str, Any]:
    snapshot = _loads(run.input_snapshot_json)
    constraint = snapshot.get("constraintSnapshot")
    constraint = constraint if isinstance(constraint, Mapping) else {}
    source = str(
        snapshot.get("launchSource")
        or constraint.get("launchSource")
        or ("catalog" if snapshot.get("competitionRuleRef") else "")
    ).strip() or None
    return {
        "source": source,
        "sourceCollectionRunId": _as_optional_str(snapshot.get("sourceCollectionRunId")),
        "authorizationId": _as_optional_str(
            snapshot.get("authorizationId")
            or snapshot.get("catalogAuthorizationId")
        ),
        "planId": _as_optional_str(snapshot.get("planId")),
        "questionId": _as_optional_str(
            snapshot.get("questionId") or run.question_id
        ),
        "hypothesisSelectionId": _as_optional_str(
            snapshot.get("hypothesisSelectionId")
            or snapshot.get("selectionId")
        ),
        "catalogAuthorizationId": _as_optional_str(
            snapshot.get("catalogAuthorizationId")
            or snapshot.get("authorizationId")
        ),
        "readinessReportSha256": _as_optional_str(
            snapshot.get("readinessReportSha256")
        ),
        "chainCorrelationId": _as_optional_str(
            snapshot.get("chainCorrelationId")
        ),
        "inputSnapshotHash": _as_optional_str(run.input_snapshot_hash),
    }


def _normalize_launch_context(
    value: Mapping[str, Any] | None,
    run: RunRecord,
) -> dict[str, Any]:
    context = _launch_context(run)
    if value is not None:
        context.update(dict(value))
    # Keep the exact v2 names populated from their legacy aliases when a
    # narrow test double or older caller supplies only the v1 spelling.
    context["questionId"] = _as_optional_str(
        context.get("questionId") or run.question_id
    )
    context["catalogAuthorizationId"] = _as_optional_str(
        context.get("catalogAuthorizationId") or context.get("authorizationId")
    )
    context["authorizationId"] = _as_optional_str(
        context.get("authorizationId") or context.get("catalogAuthorizationId")
    )
    context["hypothesisSelectionId"] = _as_optional_str(
        context.get("hypothesisSelectionId") or context.get("selectionId")
    )
    context["readinessReportSha256"] = _as_optional_str(
        context.get("readinessReportSha256")
    )
    context["chainCorrelationId"] = _as_optional_str(
        context.get("chainCorrelationId")
    )
    return context


def _discussion_anchor(
    inputs: ProjectionInputs,
    *,
    launch_context: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Project the one server-authored discussion anchor for a snapshot.

    ``active_discussion_anchor`` owns all identity matching and degraded
    reasons.  This adapter only decides whether the caller supplied enough
    authority to invoke it and adapts the immutable run input when a caller
    has not supplied a richer workflow projection.  In particular, it never
    derives a room from ``linkedChatRoomId`` or from an array position.
    """

    supplied_authority = (
        inputs.discussion_projection is not None
        or inputs.discussion_meetings is not None
        or inputs.discussion_rooms is not None
    )
    existing = launch_context.get("activeDiscussionAnchor")
    if not supplied_authority and isinstance(existing, Mapping):
        # A query adapter may already have projected the canonical anchor.  It
        # is an input fact, not a second selection algorithm; preserve it for
        # compatibility with the additive launch-context envelope.
        return dict(existing)
    if not supplied_authority:
        return None

    workflow_projection: Mapping[str, Any] = (
        inputs.discussion_projection
        if isinstance(inputs.discussion_projection, Mapping)
        else {}
    )
    return project_active_discussion_anchor(
        workflow_projection,
        inputs.discussion_meetings,
        inputs.discussion_rooms,
    )


def _normalize_delivery_status(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized or None


def _run_summary(run: RunRecord) -> WorkflowRunSummary:
    return WorkflowRunSummary(
        run_id=run.run_id,
        team_id=run.team_id,
        workflow_id=run.workflow_id,
        workflow_version_id=run.workflow_version_id,
        thread_id=run.thread_id,
        project_id=run.project_id,
        question_id=run.question_id,
        status=run.status,
        run_version=run.run_version,
        input_snapshot_hash=run.input_snapshot_hash,
        binding_snapshot_set_id=run.binding_snapshot_set_id,
        active_node_id=run.active_node_id,
        parent_run_id=run.parent_run_id,
        forked_from_checkpoint_id=run.forked_from_checkpoint_id,
        completion_kind=run.completion_kind,
        terminal_reason=run.terminal_reason,
        created_at_ms=run.created_at_ms,
        updated_at_ms=run.updated_at_ms,
        completed_at_ms=run.completed_at_ms,
        blocked_reason=format_blocked_reason(
            parse_problem_json(run.blocked_problem_json),
            fallback=run.terminal_reason,
        )
        or None,
    )


def _attempt_summary(attempt: NodeAttemptRecord) -> NodeAttemptSummary:
    return NodeAttemptSummary(
        node_run_id=attempt.node_run_id,
        node_id=attempt.node_id,
        attempt=attempt.attempt,
        actor_kind=attempt.actor_kind,
        status=attempt.status,
        command_id=attempt.command_id,
        binding_snapshot_id=attempt.binding_snapshot_id,
        input_snapshot_hash=attempt.input_snapshot_hash,
        execution_anchor_id=attempt.execution_anchor_id,
        started_at_ms=attempt.started_at_ms,
        updated_at_ms=attempt.updated_at_ms,
        finished_at_ms=attempt.finished_at_ms,
        problem=parse_problem_json(attempt.problem_json),
    )


def _coerce_human_task(item: HumanTaskSummary | Mapping[str, Any]) -> HumanTaskSummary:
    if isinstance(item, HumanTaskSummary):
        return item
    return HumanTaskSummary(
        task_id=str(item.get("taskId") or ""),
        run_id=str(item.get("runId") or ""),
        node_run_id=str(item.get("nodeRunId") or ""),
        node_id=_as_optional_str(item.get("nodeId")),
        handoff_id=_as_optional_str(item.get("handoffId")),
        task_kind=str(item.get("taskKind") or ""),
        status=str(item.get("status") or ""),
        created_at_ms=int(item.get("createdAtMs") or 0),
        resolved_at_ms=(
            None
            if item.get("resolvedAtMs") is None
            else int(item.get("resolvedAtMs") or 0)
        ),
    )


def _handoff_summary(handoffs: Sequence[Mapping[str, Any]]) -> HandoffSummary:
    by_status: dict[str, int] = {}
    refs: list[HandoffRefSummary] = []
    for item in handoffs:
        status = str(item.get("status") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        refs.append(
            HandoffRefSummary(
                handoff_id=_as_optional_str(item.get("handoffId")),
                to_node_id=_as_optional_str(item.get("toNodeId")),
                from_node_id=_as_optional_str(item.get("fromNodeId")),
                from_node_run_id=_as_optional_str(item.get("fromNodeRunId")),
                status=status,
                input_snapshot_hash=_as_optional_str(item.get("inputSnapshotHash")),
                output_artifact_refs=tuple(
                    ref
                    for ref in (item.get("outputArtifactRefs") or ())
                    if isinstance(ref, Mapping)
                ),
                offered_at_ms=_as_optional_int(item.get("offeredAtMs")),
                accepted_at_ms=_as_optional_int(item.get("acceptedAtMs")),
            )
        )
    return HandoffSummary(
        counts_by_status=by_status,
        refs=tuple(refs),
        count=len(refs),
    )


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def frozen_agent_bindings(input_snapshot_json: str | None) -> tuple[AgentBindingRef, ...]:
    payload = _loads(input_snapshot_json or "")
    if not isinstance(payload, dict):
        return ()
    refs: list[AgentBindingRef] = []
    seen: set[str] = set()
    for item in payload.get("agentBindingSnapshot") or []:
        if not isinstance(item, Mapping):
            continue
        node_id = str(item.get("nodeId") or "").strip()
        agent_id = str(item.get("agentId") or "").strip()
        if not node_id or not agent_id or node_id in seen:
            continue
        seen.add(node_id)
        resolved = str(item.get("resolvedFrom") or "").strip() or "workflow_default"
        refs.append(
            AgentBindingRef(
                node_id=node_id,
                agent_id=agent_id,
                role_key=str(item.get("roleKey") or "").strip(),
                resolved_from=resolved,
                snapshot_id=str(item.get("snapshotId") or "").strip(),
            )
        )
    return tuple(refs)


def _loads(raw: str) -> Any:
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
