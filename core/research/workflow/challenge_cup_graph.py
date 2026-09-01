"""Challenge Cup v2.1 control graph without business side effects.

Node work is performed by durable Agent/System/Human adapters. Graph node
functions only expose an interrupt if somebody invokes the graph directly;
validated adapters advance checkpoints with ``update_state(..., as_node=...)``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .definition import (
    build_challenge_cup_workflow_definition,
    graph_conditional_targets,
    graph_static_edge_pairs,
)
from .iteration_decisions import (
    ITERATION_ROUTE_TARGETS,
    IterationDecisionError,
    route_target_after_governance,
    route_target_for_decision,
)
from .models import WorkflowDefinition
from .stage_one_completion import route_after_stage_one_closure


class ChallengeCupState(TypedDict, total=False):
    current_node_id: str
    completed_node_ids: list[str]
    # Last-value channel holding ONLY the most recent completed node's
    # artifact ids (overwritten on every node completion).  Cumulative
    # artifact lineage authority lives on the run record's
    # ``artifactManifests``, never here.  Renamed from ``artifact_refs``;
    # checkpoints carrying the old channel are discarded via the
    # CHALLENGE_CUP_CHECKPOINT_VERSION bump (no migration).
    latest_node_artifact_refs: list[str]
    handoff_ids: list[str]
    iteration_decision: dict[str, Any]
    controlled_run_attempt: int
    blocked_reason: str
    pending_fork: bool
    stage_one_completion_state: str
    # Declared last-value channels for fork/state patches.  Declaring them on
    # both graph schemas is intentional (extra channels are harmless): before
    # they were declared, langgraph silently dropped these keys from
    # checkpoint writes, so fork contracts never reached child checkpoints.
    evidence_remediation_contract: dict[str, Any]
    parent_run_id: str
    binding_snapshot_id: str | None
    budget_policy_hash: str


def _node_order(definition: WorkflowDefinition) -> list[str]:
    return [node.nodeId for node in definition.nodes]


def _make_node_fn(
    node_id: str, definition: WorkflowDefinition
) -> Callable[[ChallengeCupState], ChallengeCupState]:
    spec = next(node for node in definition.nodes if node.nodeId == node_id)

    def request_external_execution(state: ChallengeCupState) -> ChallengeCupState:
        interrupt(
            {
                "nodeId": node_id,
                "actorType": spec.actorKind.value,
                "reason": "durable_adapter_execution_required",
            }
        )
        return {**state, "current_node_id": node_id}

    return request_external_execution


def route_after_iteration_decision(
    state: ChallengeCupState,
) -> Literal["controlled_run", "version_governance", "__end__"]:
    if state.get("blocked_reason") == "iteration_budget_exhausted":
        return END  # type: ignore[return-value]
    decision = state.get("iteration_decision") or {}
    kind_raw = decision.get("decisionKind")
    if not kind_raw:
        raise IterationDecisionError(
            "missing decisionKind after iteration_decision",
            code="missing_decision",
        )
    target = route_target_for_decision(kind_raw)
    if target is None:
        return END  # type: ignore[return-value]
    if target not in {"controlled_run", "version_governance"}:
        raise IterationDecisionError(
            f"illegal route target {target}",
            code="illegal_route",
        )
    return target  # type: ignore[return-value]


def route_after_version_governance(
    state: ChallengeCupState,
) -> Literal["candidate_promotion", "result_package", "__end__"]:
    decision = state.get("iteration_decision") or {}
    kind_raw = decision.get("decisionKind")
    if not kind_raw:
        raise IterationDecisionError(
            "missing decisionKind after version_governance",
            code="missing_decision",
        )
    return route_target_after_governance(kind_raw)  # type: ignore[return-value]


def build_challenge_cup_graph(
    definition: WorkflowDefinition | None = None,
) -> StateGraph:
    """Build the control graph for one pinned workflow definition.

    ``definition=None`` keeps the historical behavior of compiling the current
    ``build_challenge_cup_workflow_definition()`` output; run-driven callers
    must pass the definition resolved from the run's version identity instead.
    Decision-node conditional edges and terminal END edges are installed only
    when the pinned definition actually contains those nodes, so reduced
    definitions (knowledge sideflow, main-flow 3.0.0) compile without the
    iteration/governance machinery.
    """
    resolved = definition or build_challenge_cup_workflow_definition()
    order = _node_order(resolved)
    builder: StateGraph = StateGraph(ChallengeCupState)
    for node_id in order:
        builder.add_node(node_id, _make_node_fn(node_id, resolved))
    builder.add_edge(START, order[0])
    for source, target in graph_static_edge_pairs(resolved):
        if source == "hypothesis_design":
            builder.add_conditional_edges(
                source,
                route_after_stage_one_closure(target),
                {target: target, END: END},
            )
            continue
        builder.add_edge(source, target)
    if "iteration_decision" in order:
        iteration_targets = graph_conditional_targets("iteration_decision", resolved)
        builder.add_conditional_edges(
            "iteration_decision",
            route_after_iteration_decision,
            {target: target for target in iteration_targets} | {END: END},
        )
    if "version_governance" in order:
        governance_targets = graph_conditional_targets("version_governance", resolved)
        builder.add_conditional_edges(
            "version_governance",
            route_after_version_governance,
            {target: target for target in governance_targets} | {END: END},
        )
    for terminal_node in _terminal_node_ids(resolved):
        builder.add_edge(terminal_node, END)
    return builder


def _terminal_node_ids(definition: WorkflowDefinition) -> list[str]:
    """Definition nodes without outgoing edges, in canonical order."""
    sources = {edge.fromNodeId for edge in definition.edges}
    return [node.nodeId for node in definition.nodes if node.nodeId not in sources]


def compile_challenge_cup_graph(checkpointer: Any, definition: WorkflowDefinition | None = None):
    return build_challenge_cup_graph(definition).compile(checkpointer=checkpointer)


def compiled_iteration_route_map() -> dict[str, str | None]:
    return {kind.value: target for kind, target in ITERATION_ROUTE_TARGETS.items()}
