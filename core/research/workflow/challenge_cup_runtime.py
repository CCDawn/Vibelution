"""Formal LangGraph runner — interrupt/resume coordinator (spec 4.2/8.2).

GraphState only carries control references. Node functions are replayable:
they derive a deterministic actionId from (runId, nodeId, attempt), build a
typed PendingAction, and interrupt with it. resume only consumes a typed
ExecutionReceipt whose identity must match the frozen action. Re-entry uses an
explicit predecessor only to schedule a graph task; it never marks a business
node complete through update_state(..., as_node=...).

Thread identity: thread_id == runId (spec 7.3 step 2).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from core.research.workflow.checkpoint_store import (
    ScopeBindingMismatch,
    assert_five_way_scope_binding,
    build_checkpoint_binding_payload,
    canonical_discussion_scope,
)
from core.research.workflow.contracts import ExecutionReceipt, PendingAction
from core.research.workflow.definition import (
    build_challenge_cup_workflow_definition,
    graph_conditional_targets,
    graph_static_edge_pairs,
)
from core.research.workflow.iteration_decisions import (
    IterationDecisionError,
    route_target_after_governance,
    route_target_for_decision,
)
from core.research.workflow.models import ActorKind
from core.research.workflow.stage_one_completion import route_after_stage_one_closure

# Durable checkpoint schema identity for the formal Challenge Cup graph.  A
# checkpoint whose stored version differs from this constant is discarded, not
# migrated: readers must treat the thread as absent and rebuild it from the
# Ledger attempt authority (start/retry/entry paths).  Bump this constant on
# every channel-set change so stale schemas fail closed instead of silently
# dropping writes (langgraph discards input keys that are not declared
# channels).
# v3: renamed the last-value ``artifact_refs`` channel to
# ``latest_node_artifact_refs`` to make its overwrite-only semantics
# explicit (cumulative lineage stays on the run record).
CHALLENGE_CUP_CHECKPOINT_VERSION = 3


def merge_node_attempts(
    current: Mapping[str, int] | None,
    incoming: Mapping[str, int] | None,
) -> dict[str, int]:
    """Merge attempt counters without allowing a checkpoint to move backwards.

    LangGraph may replay the persisted interrupt write and the retry command in
    the same superstep after a crash.  ``node_attempts`` is therefore an
    aggregate channel rather than a last-value scalar.  Each node keeps the
    highest durable attempt observed.
    """

    merged = {str(node_id): int(attempt) for node_id, attempt in (current or {}).items()}
    for node_id, attempt in (incoming or {}).items():
        key = str(node_id)
        merged[key] = max(merged.get(key, 0), int(attempt))
    return merged


class ChallengeCupGraphState(TypedDict, total=False):
    run_id: str
    team_id: str
    workflow_version_id: str
    input_snapshot_hash: str
    active_node_id: str
    active_attempt: int
    node_attempts: Annotated[dict[str, int], merge_node_attempts]
    pending_action_id: str | None
    last_receipt_id: str | None
    branch_decision: str | None
    blocked_outcome: str | None
    checkpoint_version: int
    session_scope: dict[str, Any]
    selection_id: str
    candidate_id: str
    # Discussion scope is the multi-agent room identity.  It intentionally
    # stays separate from ``session_scope`` (which includes agentId).
    discussion_scope: dict[str, Any]
    discussion_scope_ref: Any
    discussion_scope_hash: str
    room_ref: Any
    meeting_ref: Any
    business_checkpoint_ref: Any
    participant_binding_refs: list[Any]
    scope_binding_required: bool
    scope_binding_status: str
    scope_binding_problem: dict[str, Any]
    stage_one_completion_state: str
    # Terminal closeout outcome for a server-authorized stage-one acceptance.
    # Last-value channel, declared so checkpoint writes (the enqueued resume
    # and the direct marker write) persist the outcome instead of silently
    # dropping it as undeclared input.
    stage_one_closeout: dict[str, Any]
    # Declared last-value channels.  Fork/state patches write these keys and
    # they must survive into the persisted checkpoint instead of being dropped
    # as undeclared input.
    parent_run_id: str
    binding_snapshot_id: str | None
    budget_policy_hash: str
    evidence_remediation_contract: dict[str, Any]


@dataclass(frozen=True)
class GraphDispatch:
    action_id: str
    run_id: str
    node_run_id: str
    node_id: str
    attempt: int
    dispatch_kind: Literal["start", "resume_action", "resume_human"]
    input_snapshot_hash: str = ""
    workflow_version_id: str = ""
    team_id: str = ""
    binding_snapshot_id: str | None = None
    budget_policy_hash: str = ""
    receipt: ExecutionReceipt | None = None
    state_update: Mapping[str, Any] | None = None
    # Optional v1 Discussion Scope binding.  All fields are metadata-only;
    # transcripts remain in the scoped Child Session ledger.
    discussion_scope: Mapping[str, Any] | None = None
    scope_ref: Any = None
    scope_hash: str = ""
    room_ref: Any = None
    meeting_ref: Any = None
    business_checkpoint_ref: Any = None
    participant_binding_refs: tuple[Any, ...] = ()
    scope_binding_required: bool = False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> GraphDispatch:
        receipt_payload = payload.get("receipt")
        binding = payload.get("scopeBinding")
        binding = binding if isinstance(binding, Mapping) else {}
        discussion_scope = (
            payload.get("discussionScope")
            or binding.get("scope")
            or payload.get("discussion_scope")
        )
        if not isinstance(discussion_scope, Mapping):
            discussion_scope = None
        participant_refs = (
            payload.get("participantBindingRefs")
            or binding.get("participantBindingRefs")
            or payload.get("participant_binding_refs")
            or ()
        )
        if not isinstance(participant_refs, (list, tuple)):
            participant_refs = ()
        return cls(
            action_id=str(payload.get("actionId") or ""),
            run_id=str(payload.get("runId") or ""),
            node_run_id=str(payload.get("nodeRunId") or ""),
            node_id=str(payload.get("nodeId") or ""),
            attempt=int(payload.get("attempt") or 1),
            dispatch_kind=str(payload.get("dispatchKind") or "start"),
            input_snapshot_hash=str(payload.get("inputSnapshotHash") or ""),
            workflow_version_id=str(payload.get("workflowVersionId") or ""),
            team_id=str(payload.get("teamId") or ""),
            binding_snapshot_id=payload.get("bindingSnapshotId"),
            budget_policy_hash=str(payload.get("budgetPolicyHash") or ""),
            receipt=ExecutionReceipt.from_dict(receipt_payload) if receipt_payload else None,
            state_update=dict(payload.get("stateUpdate") or {}),
            discussion_scope=dict(discussion_scope) if discussion_scope else None,
            scope_ref=(
                payload.get("scopeRef")
                or binding.get("scopeRef")
                or payload.get("scope_ref")
            ),
            scope_hash=str(
                payload.get("scopeHash")
                or binding.get("scopeHash")
                or payload.get("scope_hash")
                or ""
            ),
            room_ref=payload.get("roomRef") or binding.get("roomRef"),
            meeting_ref=payload.get("meetingRef") or binding.get("meetingRef"),
            business_checkpoint_ref=(
                payload.get("businessCheckpointRef")
                or binding.get("businessCheckpointRef")
            ),
            participant_binding_refs=tuple(participant_refs),
            scope_binding_required=bool(
                payload.get("scopeBindingRequired")
                or payload.get("challengeCupScoped")
                or binding.get("required")
                or discussion_scope
            ),
        )

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "actionId": self.action_id,
            "runId": self.run_id,
            "nodeRunId": self.node_run_id,
            "nodeId": self.node_id,
            "attempt": self.attempt,
            "dispatchKind": self.dispatch_kind,
            "inputSnapshotHash": self.input_snapshot_hash,
            "workflowVersionId": self.workflow_version_id,
            "teamId": self.team_id,
            "budgetPolicyHash": self.budget_policy_hash,
        }
        if self.binding_snapshot_id:
            payload["bindingSnapshotId"] = self.binding_snapshot_id
        if self.receipt:
            payload["receipt"] = self.receipt.to_dict()
        if self.state_update:
            payload["stateUpdate"] = dict(self.state_update)
        if self.discussion_scope:
            binding = build_checkpoint_binding_payload(
                self.discussion_scope,
                scope_ref=self.scope_ref,
                room_ref=self.room_ref,
                meeting_ref=self.meeting_ref,
                business_checkpoint_ref=self.business_checkpoint_ref,
                participant_binding_refs=self.participant_binding_refs,
            )
            payload["scopeBinding"] = binding
            payload["discussionScope"] = dict(binding["scope"])
            payload["scopeHash"] = str(binding["scopeHash"])
        if self.scope_binding_required:
            payload["scopeBindingRequired"] = True
        return payload


@dataclass(frozen=True)
class GraphDispatchResult:
    dispatch_kind: str
    pending_action: PendingAction | None
    next_node_ids: tuple[str, ...]
    checkpoint_id: str
    state: Mapping[str, Any]
    completed: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "dispatchKind": self.dispatch_kind,
            "pendingAction": self.pending_action.to_dict() if self.pending_action else None,
            "nextNodeIds": list(self.next_node_ids),
            "checkpointId": self.checkpoint_id,
            "completed": self.completed,
        }


def _dispatch_scope_state(dispatch: GraphDispatch) -> dict[str, Any]:
    """Convert a dispatch's optional binding into checkpoint-safe channels."""

    if dispatch.discussion_scope is None:
        if dispatch.scope_binding_required:
            raise ScopeBindingMismatch(
                "formal challenge dispatch is missing discussion scope",
                field="discussionScope",
            )
        return {}
    binding = build_checkpoint_binding_payload(
        dispatch.discussion_scope,
        scope_ref=dispatch.scope_ref,
        room_ref=dispatch.room_ref,
        meeting_ref=dispatch.meeting_ref,
        business_checkpoint_ref=dispatch.business_checkpoint_ref,
        participant_binding_refs=dispatch.participant_binding_refs,
    )
    supplied_hash = str(dispatch.scope_hash or "").strip().lower()
    expected_hash = str(binding["scopeHash"])
    if supplied_hash and supplied_hash != expected_hash:
        raise ScopeBindingMismatch(
            "dispatch scope hash does not match its identity",
            field="scopeHash",
            expected_scope_hash=expected_hash,
            observed_scope_hash=supplied_hash,
        )
    return {
        "discussion_scope": dict(binding["scope"]),
        "discussion_scope_ref": binding.get("scopeRef"),
        "discussion_scope_hash": expected_hash,
        "room_ref": binding.get("roomRef"),
        "meeting_ref": binding.get("meetingRef"),
        "business_checkpoint_ref": binding.get("businessCheckpointRef"),
        "participant_binding_refs": list(binding.get("participantBindingRefs") or []),
        "scope_binding_required": True,
        "scope_binding_status": "bound",
    }


def _state_discussion_scope(state: Mapping[str, Any]) -> dict[str, Any] | None:
    raw = state.get("discussion_scope")
    if not isinstance(raw, Mapping):
        raw = state.get("discussionScope")
    if not isinstance(raw, Mapping):
        return None
    # The graph stores the identity and hash in separate channels so the scope
    # object remains the canonical V1 payload (additionalProperties=false).
    return canonical_discussion_scope(raw, require_hash=False)


def _validate_state_scope_binding(
    state: Mapping[str, Any],
    dispatch: GraphDispatch | None = None,
) -> dict[str, Any] | None:
    """Validate the graph-side binding without advancing the graph.

    Legacy runs have no ``scope_binding_required`` channel and remain
    compatible.  Once a formal dispatch has a Discussion Scope, a missing or
    changed persisted scope is a hard mismatch rather than a fallback to the
    old shared session.
    """

    persisted = _state_discussion_scope(state)
    # A persisted Discussion Scope is itself evidence that this is a formal
    # scoped run.  Do not let a partially-written/legacy checkpoint bypass
    # the five-way gate merely because its boolean marker is absent.
    required = (
        bool(state.get("scope_binding_required"))
        or bool(dispatch is not None and dispatch.scope_binding_required)
        or persisted is not None
    )
    if not required and persisted is None:
        return None
    if persisted is None:
        raise ScopeBindingMismatch(
            "workflow checkpoint discussion scope is missing",
            field="workflowCheckpoint.discussionScope",
        )
    if dispatch is not None and dispatch.discussion_scope is not None:
        incoming = canonical_discussion_scope(dispatch.discussion_scope, require_hash=False)
        incoming_hash = str(incoming["scopeHash"])
        if incoming_hash != str(persisted["scopeHash"]):
            raise ScopeBindingMismatch(
                "dispatch and workflow checkpoint scopes differ",
                field="workflowCheckpoint.scope",
                expected_scope_hash=str(persisted["scopeHash"]),
                observed_scope_hash=incoming_hash,
            )
    expected_hash = str(persisted["scopeHash"])
    state_hash = str(state.get("discussion_scope_hash") or "").strip().lower()
    if state_hash and state_hash != expected_hash:
        raise ScopeBindingMismatch(
            "workflow checkpoint scopeHash does not match its scope",
            field="workflowCheckpoint.scopeHash",
            expected_scope_hash=expected_hash,
            observed_scope_hash=state_hash,
        )
    # A formal Challenge Cup graph is resumable only when all five durable
    # authorities still point at the same discussion scope.  The checkpoint
    # stores metadata-only refs for these authorities; validate those refs
    # through the canonical facade instead of treating their presence as
    # proof of a binding.  Legacy unscoped graph runs keep the old behavior.
    if required:
        assert_five_way_scope_binding(
            workflow_checkpoint={"scope": persisted},
            business_checkpoint=state.get("business_checkpoint_ref"),
            meeting=state.get("meeting_ref"),
            room=state.get("room_ref"),
            participant_sessions=state.get("participant_binding_refs") or (),
            expected_scope=persisted,
        )
    return persisted


def _scope_update_for_dispatch(dispatch: GraphDispatch) -> dict[str, Any]:
    return _dispatch_scope_state(dispatch)


def action_id_for(run_id: str, node_id: str, attempt: int) -> str:
    identity = f"{run_id}:{node_id}:{attempt}".encode("utf-8")
    return f"act-{hashlib.sha256(identity).hexdigest()[:16]}"


def build_pending_action(state: ChallengeCupGraphState, node_id: str) -> PendingAction:
    run_id = str(state.get("run_id") or "")
    node_attempts = state.get("node_attempts") or {}
    attempt = node_attempts.get(node_id)
    if attempt is None:
        attempt = (
            int(state.get("active_attempt") or 1)
            if str(state.get("active_node_id") or "") == node_id
            else 1
        )
    actor_kind = _actor_kind_for(node_id, str(state.get("workflow_version_id") or ""))
    selection_id = str(state.get("selection_id") or "").strip() or None
    candidate_id = str(state.get("candidate_id") or "").strip() or None
    if bool(selection_id) != bool(candidate_id):
        raise ValueError(
            "candidate-scoped PendingAction requires both selection_id and candidate_id"
        )
    raw_scope = state.get("session_scope")
    scope = (
        dict(raw_scope)
        if isinstance(raw_scope, Mapping)
        else {
            "version": 3,
            "kind": "workflow_candidate" if candidate_id else "workflow_node_root",
            "teamId": str(state.get("team_id") or ""),
            "workflowRunId": run_id,
            "workflowNodeId": node_id,
        }
    )
    if candidate_id:
        scope["selectionId"] = selection_id
        scope["candidateId"] = candidate_id
    return PendingAction(
        action_id=action_id_for(run_id, node_id, attempt),
        run_id=run_id,
        node_run_id=f"nr-{run_id}-{node_id}-a{attempt}",
        node_id=node_id,
        attempt=attempt,
        actor_kind=actor_kind,
        action_kind=_action_kind_for(actor_kind, node_id),
        input_snapshot_hash=str(state.get("input_snapshot_hash") or ""),
        input_artifact_refs=(),
        binding_snapshot_id=state.get("binding_snapshot_id") if state.get("binding_snapshot_id") else None,
        budget_policy_hash=str(state.get("budget_policy_hash") or ""),
        scope=scope,
        selection_id=selection_id,
        candidate_id=candidate_id,
    )


def _actor_kind_for(node_id: str, workflow_version_id: str = "") -> ActorKind:
    definition = resolve_definition_for_version(workflow_version_id)
    for node in definition.nodes:
        if node.nodeId == node_id:
            return node.actorKind
    raise ValueError(f"unknown node {node_id}")


def resolve_definition_for_version(
    workflow_version_id: str = "",
    *,
    definition: Any = None,
) -> Any:
    """Resolve the pinned definition for a run-facing version id.

    Empty version ids keep the legacy behavior: compile the current main
    definition (or the explicitly provided one).  Registered version ids
    (sideflow, main-flow 3.0.0, snapshot-pinned versions) resolve through
    the definition registry; an ambiguous id still fails closed.  A version
    id unknown to the registry can only come from runs created before the
    registry existed (or synthetic test ids) — those keep the historical
    behavior of being driven by the current graph; checkpoint-pinning
    callers remain fail-closed through ``resolve_definition_for_run_record``.
    """
    if definition is not None:
        return definition
    if not str(workflow_version_id or "").strip():
        return build_challenge_cup_workflow_definition()
    from core.research.workflow.definition_registry import (
        UnknownWorkflowDefinitionVersion,
        resolve_definition_by_version_id,
    )

    try:
        return resolve_definition_by_version_id(workflow_version_id)
    except UnknownWorkflowDefinitionVersion:
        return build_challenge_cup_workflow_definition()


def _action_kind_for(actor_kind: ActorKind, node_id: str) -> str:
    if actor_kind == ActorKind.AGENT:
        return "start_agent_task"
    if actor_kind == ActorKind.SYSTEM:
        return f"system_action:{node_id}"
    return f"human_task:{node_id}"


def _node_order(workflow_version_id: str = "") -> list[str]:
    definition = resolve_definition_for_version(workflow_version_id)
    return [node.nodeId for node in definition.nodes]


def _fork_predecessor_for(node_id: str, workflow_version_id: str = "") -> str | None:
    """Unique static predecessor used as ``as_node`` when forking a checkpoint.

    A fresh thread's bare ``update_state`` only schedules the graph entry
    node; resuming a forked child at any other node must attribute the
    inherited values to that node's unique linear predecessor so LangGraph
    schedules the requested resume node.  Returns ``None`` for the entry node
    itself and for conditional-sourced nodes, where static scheduling is not
    determinable.
    """
    order = _node_order(workflow_version_id)
    if node_id == order[0]:
        return None
    definition = resolve_definition_for_version(workflow_version_id)
    predecessors = [
        source for source, target in graph_static_edge_pairs(definition) if target == node_id
    ]
    if len(predecessors) == 1:
        return predecessors[0]
    return None


def _retry_predecessor_for(node_id: str, workflow_version_id: str = "") -> str | None:
    """Return the graph source that schedules ``node_id`` on a retry.

    ``graph.invoke(Command(goto=...))`` is a valid LangGraph input shape, but
    it does not seed a new task when the thread has already reached ``END``.
    Retrying a terminal checkpoint therefore uses the documented
    ``update_state(..., as_node=...)`` + ``invoke(None, ...)`` time-travel
    sequence.  The fixed linear graph has one static predecessor for every
    ordinary node; the two conditional sources are also unambiguous for their
    destinations.  The entry node is scheduled from ``START``.
    """

    order = _node_order(workflow_version_id)
    if node_id not in order:
        return None
    if node_id == order[0]:
        return START
    predecessor = _fork_predecessor_for(node_id, workflow_version_id)
    if predecessor is not None:
        return predecessor
    definition = resolve_definition_for_version(workflow_version_id)
    conditional_predecessors = [
        source
        for source in ("iteration_decision", "version_governance")
        if node_id in graph_conditional_targets(source, definition)
    ]
    if len(conditional_predecessors) == 1:
        return conditional_predecessors[0]
    return None


def _make_node_fn(node_id: str) -> Callable[[ChallengeCupGraphState], ChallengeCupGraphState]:
    def run_node(state: ChallengeCupGraphState) -> ChallengeCupGraphState:
        pending = build_pending_action(state, node_id)
        first_payload = interrupt(pending.to_dict())
        if isinstance(first_payload, dict) and first_payload.get("restart"):
            # retry/restart marker：旧 interrupt 被确认，节点以新 attempt 重新 interrupt。
            restart_attempt = int(first_payload.get("attempt") or pending.attempt)
            restart_state = {
                **state,
                "active_node_id": node_id,
                "active_attempt": restart_attempt,
                "node_attempts": {
                    **dict(state.get("node_attempts") or {}),
                    node_id: restart_attempt,
                },
            }
            pending = build_pending_action(restart_state, node_id)
            receipt_payload = interrupt(pending.to_dict())
        else:
            receipt_payload = first_payload
        if receipt_payload is None:
            raise RuntimeError(f"node {node_id} resumed without an ExecutionReceipt")
        receipt = ExecutionReceipt.from_dict(receipt_payload)
        receipt.assert_matches(pending.action_id, pending.node_run_id)
        updated = {
            **state,
            "active_node_id": node_id,
            "active_attempt": pending.attempt,
            "pending_action_id": pending.action_id,
            "last_receipt_id": receipt.action_id,
            # Schema identity, not a counter: completed nodes stamp the current
            # version so a resumed legacy checkpoint is re-validated everywhere.
            "checkpoint_version": CHALLENGE_CUP_CHECKPOINT_VERSION,
        }
        if receipt.outcome != "succeeded":
            # 失败/阻塞/取消的 receipt 不推进业务：路由见 blocked_outcome
            # 即结束图，由 worker 依据 outcome 标记 attempt 状态（spec 8.2）。
            updated["blocked_outcome"] = receipt.outcome
        return updated

    return run_node


def route_after_iteration_decision(
    state: ChallengeCupGraphState,
) -> Literal["controlled_run", "version_governance", "__end__"]:
    if state.get("blocked_outcome"):
        return END  # type: ignore[return-value]
    decision = str(state.get("branch_decision") or "")
    try:
        target = route_target_for_decision(decision)
    except IterationDecisionError as exc:
        raise ValueError(f"unknown iteration decision {decision!r}") from exc
    if target is None:
        return END  # type: ignore[return-value]
    return target  # type: ignore[return-value]


def route_after_version_governance(
    state: ChallengeCupGraphState,
) -> Literal["candidate_promotion", "result_package", "__end__"]:
    if state.get("blocked_outcome"):
        return END  # type: ignore[return-value]
    decision = str(state.get("branch_decision") or "")
    try:
        return route_target_after_governance(decision)  # type: ignore[return-value]
    except IterationDecisionError as exc:
        raise ValueError(f"unknown governed decision {decision!r}") from exc


def _route_after_linear(source: str, target: str):
    stage_one_route = route_after_stage_one_closure(target)

    def route(state: ChallengeCupGraphState) -> Literal["__end__"] | str:
        if state.get("blocked_outcome"):
            return END  # type: ignore[return-value]
        if source == "hypothesis_design":
            return stage_one_route(state)
        return target

    route.__name__ = f"route_after_{source}"
    return route


def successor_map(workflow_version_id: str = "") -> dict[str, tuple[str, ...]]:
    """Deterministic successor set per node (drives worker attempt injection)."""
    definition = resolve_definition_for_version(workflow_version_id)
    collected: dict[str, list[str]] = {node_id: [] for node_id in _node_order(workflow_version_id)}
    for source, target in graph_static_edge_pairs(definition):
        collected.setdefault(source, []).append(target)
    for source in ("iteration_decision", "version_governance"):
        if source in collected:
            collected[source] = list(graph_conditional_targets(source, definition))
    return {
        node_id: tuple(dict.fromkeys(collected.get(node_id, [])))
        for node_id in _node_order(workflow_version_id)
    }
def build_formal_graph(definition: Any = None) -> StateGraph:
    """Build the formal runtime graph for one pinned workflow definition.

    ``definition=None`` keeps the historical main-definition behavior; the
    coordinator passes the definition resolved from the dispatch's
    workflowVersionId so sideflow / 3.0.0 threads compile their own topology.
    """
    resolved = resolve_definition_for_version("", definition=definition)
    order = [node.nodeId for node in resolved.nodes]
    successors = successor_map_for_definition(resolved)
    builder: StateGraph = StateGraph(ChallengeCupGraphState)
    for node_id in order:
        builder.add_node(node_id, _make_node_fn(node_id))
    builder.add_edge(START, order[0])
    for source, target in graph_static_edge_pairs(resolved):
        if source == "candidate_promotion":
            # Preserve the existing post-promotion terminal packaging step;
            # only the edge identity comes from the definition.
            builder.add_edge(source, target)
            continue
        builder.add_conditional_edges(
            source,
            _route_after_linear(source, target),
            {target: target, END: END},
        )
    if "iteration_decision" in order:
        builder.add_conditional_edges(
            "iteration_decision",
            route_after_iteration_decision,
            {
                "controlled_run": "controlled_run",
                "version_governance": "version_governance",
                END: END,
            },
        )
    if "version_governance" in order:
        builder.add_conditional_edges(
            "version_governance",
            route_after_version_governance,
            {
                "candidate_promotion": "candidate_promotion",
                "result_package": "result_package",
                END: END,
            },
        )
    for node_id in order:
        if not successors.get(node_id):
            builder.add_edge(node_id, END)
    return builder


def successor_map_for_definition(definition: Any) -> dict[str, tuple[str, ...]]:
    """Successor map computed from an explicit definition (no registry lookup)."""
    collected: dict[str, list[str]] = {
        node.nodeId: [] for node in definition.nodes
    }
    for source, target in graph_static_edge_pairs(definition):
        collected.setdefault(source, []).append(target)
    for source in ("iteration_decision", "version_governance"):
        if source in collected:
            collected[source] = list(graph_conditional_targets(source, definition))
    return {
        node_id: tuple(dict.fromkeys(collected.get(node_id, [])))
        for node_id in collected
    }


def _is_concurrent_update_error(exc: BaseException) -> bool:
    text = str(exc)
    return (
        type(exc).__name__ == "InvalidUpdateError"
        or "Can receive only one value per step" in text
        or "INVALID_CONCURRENT_GRAPH_UPDATE" in text
    )


def _retry_update(dispatch: GraphDispatch) -> dict[str, Any]:
    """State values for retry while an interrupt is still on the thread.

    The current interrupt keeps the destination node from running in the
    same superstep, so last-value keys here only split ``active_node_id``
    from the persisted interrupt (SCI-096). Do not reuse this for
    ``enter_node``: an empty next queue would run the destination node
    and raise INVALID_CONCURRENT_GRAPH_UPDATE.
    """
    update: dict[str, Any] = {
        "run_id": dispatch.run_id,
        "active_node_id": dispatch.node_id,
        "active_attempt": dispatch.attempt,
        "node_attempts": {dispatch.node_id: dispatch.attempt},
    }
    if dispatch.team_id:
        update["team_id"] = dispatch.team_id
    if dispatch.input_snapshot_hash:
        update["input_snapshot_hash"] = dispatch.input_snapshot_hash
    if dispatch.state_update:
        update.update(dict(dispatch.state_update))
    update.update(_scope_update_for_dispatch(dispatch))
    return update


def _enter_update(dispatch: GraphDispatch) -> dict[str, Any]:
    """Values for the checkpoint scheduling superstep before ``invoke(None)``.

    ``run_id`` is last-value and already on the thread. Putting it in the
    same superstep as the destination node's ``return {**state}`` raises
    INVALID_CONCURRENT_GRAPH_UPDATE.
    """
    update: dict[str, Any] = {
        "active_node_id": dispatch.node_id,
        "active_attempt": dispatch.attempt,
        "node_attempts": {dispatch.node_id: dispatch.attempt},
    }
    if dispatch.state_update:
        for key, value in dict(dispatch.state_update).items():
            if key in {"run_id", "team_id", "input_snapshot_hash"}:
                continue
            update[key] = value
    update.update(_scope_update_for_dispatch(dispatch))
    return update


class ChallengeCupGraphCoordinator:
    """Owns the checkpointer and compiles the formal graph per invocation."""

    def __init__(self, checkpoint_path: Path | str) -> None:
        self._checkpoint_path = Path(checkpoint_path)
        self._checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    def _compile(self, workflow_version_id: str = ""):
        from contextlib import ExitStack

        from core.research.workflow.checkpoint_store import open_sqlite_checkpointer

        stack = ExitStack()
        checkpointer = stack.enter_context(
            open_sqlite_checkpointer(str(self._checkpoint_path))
        )
        definition = resolve_definition_for_version(workflow_version_id)
        graph = build_formal_graph(definition).compile(checkpointer=checkpointer)
        return graph, stack

    def _config(self, run_id: str) -> dict[str, dict[str, str]]:
        return {"configurable": {"thread_id": run_id}}

    def start_attempt(self, dispatch: GraphDispatch) -> GraphDispatchResult:
        graph, stack = self._compile(dispatch.workflow_version_id)
        try:
            return self._start_attempt_inner(graph, dispatch)
        finally:
            stack.close()

    def _start_attempt_inner(self, graph: Any, dispatch: GraphDispatch) -> GraphDispatchResult:
        state: ChallengeCupGraphState = {
            "run_id": dispatch.run_id,
            "team_id": dispatch.team_id,
            "workflow_version_id": dispatch.workflow_version_id,
            "input_snapshot_hash": dispatch.input_snapshot_hash,
            "active_node_id": dispatch.node_id,
            "active_attempt": dispatch.attempt,
            "node_attempts": {dispatch.node_id: dispatch.attempt},
            "checkpoint_version": CHALLENGE_CUP_CHECKPOINT_VERSION,
        }
        state.update(_scope_update_for_dispatch(dispatch))
        # Validate before the first graph write as well as after every read.
        # This keeps an incomplete formal binding from creating a resumable
        # checkpoint that can only be discovered after the graph has moved.
        _validate_state_scope_binding(state, dispatch)
        if dispatch.binding_snapshot_id:
            state["binding_snapshot_id"] = dispatch.binding_snapshot_id
        if dispatch.budget_policy_hash:
            state["budget_policy_hash"] = dispatch.budget_policy_hash
        result = graph.invoke(state, self._config(dispatch.run_id))
        return self._dispatch_result(dispatch, result, graph)

    def _ensure_readable(self, graph: Any, run_id: str) -> None:
        """Drop colliding pending writes so ``get_state`` can read the thread.

        A failed Command.goto leaves NULL_TASK_ID writes plus the destination
        node's channel writes on the same checkpoint. ``get_state`` applies
        both and raises INVALID_CONCURRENT_GRAPH_UPDATE. Cloning the
        checkpoint (``as_node='__copy__'``) is LangGraph's fork path; it does
        not apply those writes. Not business advancement.
        """
        thread = self._config(run_id)
        try:
            graph.get_state(thread)
        except Exception as exc:
            if not _is_concurrent_update_error(exc):
                raise
            graph.update_state(thread, None, as_node="__copy__")

    def _read_state(
        self, graph: Any, config: dict[str, Any], *, heal: bool = False
    ) -> Any:
        run_id = str((config.get("configurable") or {}).get("thread_id") or "")
        thread = self._config(run_id) if run_id else config
        try:
            return graph.get_state(thread)
        except Exception as exc:
            if not heal or not _is_concurrent_update_error(exc):
                raise
            self._ensure_readable(graph, run_id)
            return graph.get_state(thread)

    def _goto_node(self, graph: Any, dispatch: GraphDispatch) -> GraphDispatchResult:
        """Re-enter a node by scheduling it from its graph predecessor.

        Sequence: copy-away colliding writes, clear leftover tasks with
        ``as_node=END`` (checkpoint hygiene, not a workflow node), write
        routing fields attributed to the predecessor, then invoke the new
        checkpoint with ``None``. This avoids an inert ``Command(goto=...)``
        input after a terminal checkpoint.
        """
        thread = self._config(dispatch.run_id)
        self._ensure_readable(graph, dispatch.run_id)
        current = self._read_state(graph, thread, heal=True)
        _validate_state_scope_binding(dict(current.values or {}), dispatch)
        try:
            graph.update_state(thread, None, as_node=END)
        except Exception as exc:
            if not _is_concurrent_update_error(exc):
                raise
            graph.update_state(thread, None, as_node="__copy__")
            graph.update_state(thread, None, as_node=END)
        values = _enter_update(dispatch)
        values["blocked_outcome"] = None
        predecessor = _retry_predecessor_for(
            dispatch.node_id, dispatch.workflow_version_id
        )
        if predecessor is None:
            raise RuntimeError(
                "cannot schedule graph entry without a unique predecessor: "
                f"{dispatch.node_id}"
            )
        retry_config = graph.update_state(
            thread,
            values,
            as_node=predecessor,
        )
        state = graph.get_state(retry_config)
        next_ids = {str(node_id) for node_id in (state.next or ())}
        if dispatch.node_id not in next_ids:
            raise RuntimeError(
                "graph re-entry scheduled an unexpected node: "
                f"expected {dispatch.node_id}, found {sorted(next_ids)}"
            )
        result = graph.invoke(None, retry_config)
        return self._dispatch_result(dispatch, result, graph)

    def retry_attempt(self, dispatch: GraphDispatch) -> GraphDispatchResult:
        """Retry a terminal checkpoint with one fresh interrupt.

        A ``Command(goto=...)`` input is accepted by LangGraph, but a thread
        whose previous superstep already routed to ``END`` has no runnable
        task for that command.  Fork the current checkpoint at the target's
        predecessor, clear the prior failure marker, and invoke the scheduled
        task with ``None`` instead.
        """
        graph, stack = self._compile(dispatch.workflow_version_id)
        try:
            state = self._read_state(
                graph, self._config(dispatch.run_id), heal=True
            )
            _validate_state_scope_binding(dict(state.values or {}), dispatch)
            predecessor = _retry_predecessor_for(
                dispatch.node_id, dispatch.workflow_version_id
            )
            if predecessor is None:
                raise RuntimeError(
                    "cannot schedule retry for node without a unique predecessor: "
                    f"{dispatch.node_id}"
                )
            update = _retry_update(dispatch)
            # A failed attempt routes the previous graph to END.  It is a
            # terminal marker, not durable business state for the new attempt.
            update["blocked_outcome"] = None
            retry_config = graph.update_state(
                state.config,
                update,
                as_node=predecessor,
            )
            result = graph.invoke(None, retry_config)
            return self._dispatch_result(dispatch, result, graph)
        finally:
            stack.close()

    def enter_node(self, dispatch: GraphDispatch) -> GraphDispatchResult:
        """Re-enter a node after the thread has no interrupt (routed to END)."""
        graph, stack = self._compile(dispatch.workflow_version_id)
        try:
            return self._goto_node(graph, dispatch)
        finally:
            stack.close()

    def resume_action(self, dispatch: GraphDispatch) -> GraphDispatchResult:
        if dispatch.receipt is None:
            raise ValueError("resume_action requires an ExecutionReceipt")
        graph, stack = self._compile(dispatch.workflow_version_id)
        try:
            config = self._config(dispatch.run_id)
            persisted_state = self._read_state(graph, config, heal=True)
            _validate_state_scope_binding(dict(persisted_state.values or {}), dispatch)
            receipt_payload = dispatch.receipt.to_dict()
            # langgraph 1.2.x Command has no ``interrupt_id`` parameter; the
            # supported way to address one of several pending interrupts is a
            # single-entry resume map {interrupt_id: value}.  _resume_value_for_state
            # returns (bare_value, None) for the legacy single-interrupt case.
            resume_value, _ = _resume_value_for_state(
                persisted_state,
                node_id=dispatch.node_id,
                expected_action_id=action_id_for(
                    dispatch.run_id, dispatch.node_id, dispatch.attempt
                ),
                receipt_payload=receipt_payload,
            )
            if dispatch.state_update:
                command = Command(
                    resume=resume_value,
                    update=dict(dispatch.state_update),
                )
            else:
                command = Command(resume=resume_value)
            result = graph.invoke(command, config)
            return self._dispatch_result(dispatch, result, graph)
        finally:
            stack.close()

    def resume_human(self, dispatch: GraphDispatch) -> GraphDispatchResult:
        return self.resume_action(dispatch)

    def restart_attempt(self, dispatch: GraphDispatch) -> GraphDispatchResult:
        """Retry from the persisted checkpoint with one fresh interrupt.

        A retry must not append another ``interrupt()`` position inside the
        same LangGraph task.  A checkpoint can also retain pending writes from
        a failed resume while exposing an empty current task queue.  Invoking
        a state-only ``Command`` on that checkpoint merges those stale writes
        with the retry update and can either replay the old receipt or raise
        ``INVALID_CONCURRENT_GRAPH_UPDATE``.

        Create an explicit time-travel checkpoint with ``update_state`` (never
        ``as_node``), then invoke that new checkpoint with ``None``.  This
        discards cached task resumes/errors and rebuilds exactly one interrupt
        from the Ledger attempt authority.
        """
        graph, stack = self._compile(dispatch.workflow_version_id)
        try:
            config = self._config(dispatch.run_id)
            state = self._read_state(graph, config, heal=True)
            _validate_state_scope_binding(dict(state.values or {}), dispatch)
            interrupted_nodes = {
                str(item.value.get("nodeId") or "")
                for task in state.tasks
                for item in task.interrupts
                if isinstance(item.value, Mapping)
            }
            if not interrupted_nodes:
                for item in getattr(state, "interrupts", None) or ():
                    value = getattr(item, "value", None)
                    if isinstance(value, Mapping) and value.get("nodeId"):
                        interrupted_nodes.add(str(value.get("nodeId") or ""))
            if not interrupted_nodes:
                interrupted_nodes = {
                    str(node_id) for node_id in (state.next or ())
                }
            if dispatch.node_id not in interrupted_nodes:
                raise RuntimeError(
                    "checkpoint cannot be replayed for requested node: "
                    f"expected {dispatch.node_id}, found {sorted(interrupted_nodes)}"
                )
            replay_values: dict[str, Any] = {
                "run_id": dispatch.run_id,
                "active_node_id": dispatch.node_id,
                "active_attempt": dispatch.attempt,
                "node_attempts": {dispatch.node_id: dispatch.attempt},
                # The Ledger replay rebuilds a current-schema checkpoint.
                "checkpoint_version": CHALLENGE_CUP_CHECKPOINT_VERSION,
            }
            if dispatch.team_id:
                replay_values["team_id"] = dispatch.team_id
            if dispatch.input_snapshot_hash:
                replay_values["input_snapshot_hash"] = dispatch.input_snapshot_hash
            replay_values.update(_scope_update_for_dispatch(dispatch))
            replay_config = graph.update_state(
                state.config,
                replay_values,
            )
            result = graph.invoke(None, replay_config)
            return self._dispatch_result(dispatch, result, graph)
        finally:
            stack.close()

    def snapshot(
        self, run_id: str, workflow_version_id: str = ""
    ) -> Mapping[str, Any]:
        graph, stack = self._compile(workflow_version_id)
        try:
            state = self._read_state(graph, self._config(run_id), heal=True)
            _validate_state_scope_binding(dict(state.values or {}))
            values = dict(state.values or {})
            if checkpoint_values_discarded(values):
                # Old-schema checkpoint: discarded by ruling.  Report the
                # thread as absent so callers rebuild from Ledger authority.
                return _discarded_checkpoint_snapshot()
            pending = _pending_from_state(state)
            return {
                "checkpointId": _checkpoint_id_of(state),
                "nextNodeIds": [str(node) for node in state.next or ()],
                "values": dict(state.values or {}),
                # Persisted interrupts are the execution authority.  A graph
                # recompile can expose an empty ``state.next`` while retaining
                # the interrupt, so callers must not infer the active node from
                # the task queue alone.
                "pendingAction": pending.to_dict() if pending is not None else None,
            }
        finally:
            stack.close()

    def apply_state_update(
        self,
        run_id: str,
        workflow_version_id: str = "",
        update: Mapping[str, Any] | None = None,
    ) -> str:
        """Write state values into the thread's current checkpoint (no invoke).

        Direct ``update_state`` WITHOUT ``as_node`` (restart_attempt's
        precedent): it appends values to the current checkpoint without
        scheduling a task or resuming an interrupt.  Used for server-authorized
        terminal markers when the thread has no live interrupt left to resume,
        so the Ledger and the LangGraph checkpoint cannot drift.
        Returns the new checkpoint id ("" when the backend does not expose one).
        """
        graph, stack = self._compile(workflow_version_id)
        try:
            state = self._read_state(graph, self._config(run_id), heal=True)
            _validate_state_scope_binding(dict(state.values or {}))
            saved = graph.update_state(state.config, dict(update or {}))
            configurable = (
                saved.get("configurable") if isinstance(saved, Mapping) else None
            ) or {}
            return str(configurable.get("checkpoint_id") or "")
        finally:
            stack.close()

    def fork_from_checkpoint(
        self,
        *,
        source_thread_id: str,
        source_checkpoint_id: str,
        child_thread_id: str,
        resume_node_id: str,
        state_patch: Mapping[str, Any] | None = None,
    ) -> str:
        """Seed a child thread from a parent checkpoint; returns child checkpointId.

        Checkpoint forking is not business advancement; the child becomes
        runnable only after the Ledger transaction commits (spec 8.4).
        Forks exist only on the main flow today, so the graph compiles from
        the current main definition.
        """
        graph, stack = self._compile()
        try:
            child_config = self._config(child_thread_id)
            existing = graph.get_state(child_config)
            existing_checkpoint_id = _checkpoint_id_of(existing)
            if (existing.values or {}) and existing_checkpoint_id:
                _validate_state_scope_binding(dict(existing.values or {}))
                # Crash-replay idempotency: fork I/O succeeded but Ledger ack
                # may have failed; same child_run_id with matching resume is OK.
                existing_next = [str(node_id) for node_id in existing.next or ()]
                if existing_next == [resume_node_id]:
                    return existing_checkpoint_id
                raise RuntimeError(
                    "child LangGraph thread already exists with a different state"
                )
            source_config = {
                "configurable": {
                    "thread_id": source_thread_id,
                    "checkpoint_ns": "",
                    "checkpoint_id": source_checkpoint_id,
                }
            }
            source_state = graph.get_state(source_config)
            inherited = dict(source_state.values or {})
            if not inherited:
                raise RuntimeError("source checkpoint contains no state")
            _validate_state_scope_binding(inherited)
            # thread_id == runId 契约：child 线程的 run_id 必须指向 child run。
            inherited["run_id"] = child_thread_id
            inherited.update(dict(state_patch or {}))
            if isinstance((state_patch or {}).get("discussion_scope"), Mapping):
                inherited["discussion_scope"] = dict(
                    canonical_discussion_scope(
                        (state_patch or {})["discussion_scope"], require_hash=False
                    )
                )
                inherited["discussion_scope_hash"] = str(
                    inherited["discussion_scope"]["scopeHash"]
                )
                inherited["scope_binding_required"] = True
            _validate_state_scope_binding(inherited)
            predecessor = _fork_predecessor_for(resume_node_id)
            if predecessor is not None:
                # A leftover failure marker would route the linear edge to END.
                inherited.pop("blocked_outcome", None)
            saved = graph.update_state(
                child_config,
                inherited,
                as_node=predecessor,
            )
            child_state = graph.get_state(saved)
            scheduled = [str(node_id) for node_id in child_state.next or ()]
            if scheduled != [resume_node_id]:
                raise RuntimeError(
                    f"fork scheduled {scheduled}, expected {[resume_node_id]}"
                )
            checkpoint_id = _checkpoint_id_of(child_state)
            if not checkpoint_id:
                raise RuntimeError("child checkpoint id missing")
            return checkpoint_id
        finally:
            stack.close()

    def _dispatch_result(
        self,
        dispatch: GraphDispatch,
        invoke_result: Mapping[str, Any] | None,
        graph: Any,
    ) -> GraphDispatchResult:
        state = self._read_state(graph, self._config(dispatch.run_id))
        _validate_state_scope_binding(dict(state.values or {}), dispatch)
        values = dict(state.values or {})
        next_node_ids = tuple(str(node_id) for node_id in state.next or ())
        pending = _pending_from_state(state)
        return GraphDispatchResult(
            dispatch_kind=dispatch.dispatch_kind,
            pending_action=pending,
            next_node_ids=next_node_ids,
            checkpoint_id=str(_checkpoint_id_of(state) or ""),
            state=values,
            completed=not next_node_ids and pending is None,
        )


class AmbiguousInterruptResumeError(RuntimeError):
    """Multiple pending interrupts cannot be narrowed to one dispatch target.

    Raised instead of blindly resuming a possibly-wrong interrupt.  Workers
    must treat this as deterministic (no transient retry): only the heal /
    time-travel path can rebuild a single-interrupt checkpoint.
    """


def _interrupt_diagnostic_summary(state: Any) -> str:
    parts: list[str] = []
    for item in _pending_interrupt_items(state):
        value = getattr(item, "value", None)
        if isinstance(value, Mapping):
            parts.append(
                (
                    f"(id={item.id} nodeId={value.get('nodeId')} "
                    f"attempt={value.get('attempt')} actionId={value.get('actionId')})"
                )
            )
        else:
            parts.append(f"(id={getattr(item, 'id', None)} value={type(value).__name__})")
    return "; ".join(parts)


def _pending_interrupt_items(state: Any) -> list[Any]:
    """Collect pending interrupts from both persisted sources.

    ``state.tasks[].interrupts`` is the per-task authority; a graph recompile
    or Command.goto leftover can additionally surface entries on
    ``state.interrupts`` that the task queue no longer shows.  Entries are
    deduplicated by id so both sources can be merged safely.
    """

    collected: dict[str, Any] = {}
    finished_interrupt_ids: set[str] = set()
    for task in getattr(state, "tasks", None) or ():
        # A completed task can still surface its historical interrupt on
        # ``task.interrupts``; only unfinished tasks are actually pending.
        if getattr(task, "result", None) is not None:
            for item in getattr(task, "interrupts", None) or ():
                item_id = getattr(item, "id", None)
                if item_id:
                    finished_interrupt_ids.add(str(item_id))
            continue
        for item in getattr(task, "interrupts", None) or ():
            item_id = getattr(item, "id", None)
            if item_id:
                collected.setdefault(str(item_id), item)
    for item in getattr(state, "interrupts", None) or ():
        item_id = getattr(item, "id", None)
        # ``state.interrupts`` aggregates across all tasks including ones
        # that already resumed successfully; those entries are stale.
        if item_id and str(item_id) not in finished_interrupt_ids:
            collected.setdefault(str(item_id), item)
    return list(collected.values())


def _resume_value_for_state(
    state: Any,
    *,
    node_id: str,
    expected_action_id: str,
    receipt_payload: Mapping[str, Any],
) -> tuple[Any, str | None]:
    """Pick the resume payload (and target interrupt id) for this dispatch.

    Returns ``(resume_value, interrupt_id)``:

    - At most one pending interrupt: resume it bare (legacy behaviour, keeps
      pre-map checkpoints working).
    - Multiple pending interrupts: LangGraph rejects a bare resume ("you must
      specify the interrupt id"), and resuming the wrong one would confirm an
      unrelated frozen action.  Match interrupts against the dispatch's
      action identity — the same formula that builds PendingAction /
      ExecutionReceipt identities (runId/nodeId/attempt -> actionId) — and
      return a single-entry resume map keyed by that interrupt's id.
    - No interrupt matches: raise AmbiguousInterruptResumeError with the
      pending-interrupt inventory; callers must fall back to heal /
      time-travel (restart_attempt) instead of blind-resuming.
    """
    interrupts = [
        item
        for item in _pending_interrupt_items(state)
        if getattr(item, "id", None)
    ]
    if len(interrupts) <= 1:
        return receipt_payload, None
    same_node: list[Any] = []
    exact: list[Any] = []
    for item in interrupts:
        value = item.value if isinstance(getattr(item, "value", None), Mapping) else {}
        if str(value.get("nodeId") or "") != node_id:
            continue
        same_node.append(item)
        if expected_action_id and str(value.get("actionId") or "") == expected_action_id:
            exact.append(item)
    candidates = exact or same_node
    if len(candidates) != 1:
        # exact==0 with several same-node interrupts means we cannot tell
        # which attempt survived; ambiguous. exact>1 / same_node>1 likewise.
        raise AmbiguousInterruptResumeError(
            f"When there are multiple pending interrupts ({len(interrupts)}), you must "
            f"specify the interrupt id when resuming, but no unique interrupt matches "
            f"dispatch identity nodeId={node_id} actionId={expected_action_id}; "
            f"use restart_attempt/time-travel to rebuild a single-interrupt checkpoint. "
            f"Pending interrupts: {_interrupt_diagnostic_summary(state)}"
        )
    target = candidates[0]
    # Single-entry resume map: langgraph routes this receipt exactly to the
    # identified interrupt instead of raising "must specify the interrupt id".
    return {str(target.id): receipt_payload}, str(target.id)


def _interrupt_payloads(state: Any) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for task in getattr(state, "tasks", None) or ():
        for item in getattr(task, "interrupts", None) or ():
            value = getattr(item, "value", None)
            if isinstance(value, Mapping) and value.get("nodeId"):
                payloads.append(dict(value))
    if payloads:
        return payloads
    for item in getattr(state, "interrupts", None) or ():
        value = getattr(item, "value", None)
        if isinstance(value, Mapping) and value.get("nodeId"):
            payloads.append(dict(value))
    return payloads


def _pending_from_state(state: Any) -> PendingAction | None:
    """Prefer task interrupts with a real runId; ``state.interrupts[-1]`` can
    be a Command.goto leftover that still shows ``source_finding`` with an
    empty runId while ``values.active_node_id`` was overwritten."""
    payloads = _interrupt_payloads(state)
    if not payloads:
        return None
    next_ids = {str(node_id) for node_id in (getattr(state, "next", None) or ())}

    def rank(payload: Mapping[str, Any]) -> tuple[int, int, int]:
        node_id = str(payload.get("nodeId") or "")
        return (
            0 if node_id in next_ids else 1,
            0 if str(payload.get("runId") or "").strip() else 1,
            0 if str(payload.get("actionId") or "").strip() else 1,
        )

    payloads.sort(key=rank)
    try:
        return PendingAction.from_dict(payloads[0])
    except (TypeError, ValueError, KeyError):
        return None


def _checkpoint_id_of(state: Any) -> str | None:
    configurable = (state.config or {}).get("configurable") or {}
    return str(configurable.get("checkpoint_id") or "") or None


def checkpoint_values_discarded(values: Mapping[str, Any]) -> bool:
    """True when persisted values carry a mismatched checkpoint schema version.

    Formal checkpoints written by another ``CHALLENGE_CUP_CHECKPOINT_VERSION``
    are discarded, never migrated.  Callers treat the thread as absent and
    rebuild it from the Ledger attempt authority instead of resuming
    partially-dropped state.  Values without a ``checkpoint_version`` channel
    are not formal-graph checkpoints (e.g. store-side initial checkpoints read
    through the coordinator); they carry no schema identity to invalidate.
    """

    if not values:
        return False
    raw = values.get("checkpoint_version")
    if raw is None:
        return False
    try:
        observed = int(raw)
    except (TypeError, ValueError):
        return True
    return observed != CHALLENGE_CUP_CHECKPOINT_VERSION


def _discarded_checkpoint_snapshot() -> dict[str, Any]:
    """Snapshot payload reporting a discarded thread as absent.

    Consumers (graph dispatch worker decisions, fork validation) already
    handle an absent thread by rebuilding from Ledger authority, so a stale
    checkpoint fails closed without raising to the user.
    """

    return {
        "checkpointId": "",
        "nextNodeIds": [],
        "values": {},
        "pendingAction": None,
        "checkpointDiscarded": True,
    }


def serialize_state_values(values: Mapping[str, Any]) -> str:
    return json.dumps(values, ensure_ascii=False, sort_keys=True, default=str)
