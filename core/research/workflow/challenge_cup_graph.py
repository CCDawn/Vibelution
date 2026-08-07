"""Challenge Cup fixed topology as LangGraph with human interrupts + conditional iteration.

Linear knowledge/experiment stages; execution_iteration uses conditional edges from
iteration_decision (see iteration_decisions.ITERATION_ROUTE_TARGETS).
"""

from __future__ import annotations

from typing import Any, Callable, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .definition import build_challenge_cup_workflow_definition
from .iteration_decisions import (
    DEFAULT_ITERATION_BUDGET,
    IterationDecisionError,
    IterationDecisionKind,
    normalize_decision_dict,
    parse_decision_kind,
    route_target_for_decision,
)
from .models import ActorKind


class ChallengeCupState(TypedDict, total=False):
    current_node_id: str
    completed_node_ids: list[str]
    handoffs: dict[str, str]  # edgeId -> accepted|rejected|pending
    knowledge_package_accepted: bool
    frozen_protocol_accepted: bool
    smoke_accepted: bool
    promotion_accepted: bool
    artifacts: dict[str, str]  # kind -> hash
    side_effect_keys: list[str]
    last_decision: dict[str, Any]
    # Iteration / attempt lineage (graph-visible; durable details in run store)
    iteration_decision: dict[str, Any]
    controlled_run_attempt: int
    node_attempts: dict[str, int]
    iteration_budget_max: int
    official_candidate_ref: str
    baseline_candidate_ref: str
    promotion_operation: str
    terminal_reason: str
    completion_kind: str
    blocked_reason: str
    pending_fork: bool  # set when revise_protocol chosen; parent ends after decision


def _node_order() -> list[str]:
    return [n.nodeId for n in build_challenge_cup_workflow_definition().nodes]


def _specs() -> dict[str, Any]:
    return {n.nodeId: n for n in build_challenge_cup_workflow_definition().nodes}


def _edge_from_to(from_id: str, to_id: str) -> str:
    for edge in build_challenge_cup_workflow_definition().edges:
        if edge.fromNodeId == from_id and edge.toNodeId == to_id:
            return edge.edgeId
    return f"{from_id}->{to_id}"


def _can_enter(node_id: str, state: ChallengeCupState) -> tuple[bool, str]:
    if node_id == "hypothesis_design" and not state.get("knowledge_package_accepted"):
        return False, "requires_accepted_knowledge_package"
    if node_id == "controlled_run":
        if not state.get("frozen_protocol_accepted"):
            return False, "requires_frozen_protocol"
        if not state.get("smoke_accepted"):
            return False, "requires_smoke_accept"
    if node_id == "result_package":
        # Must not package while a human promotion task is unresolved (service enforces too).
        if state.get("promotion_operation") and state.get("promotion_accepted") is False:
            return False, "promotion_rejected"
    return True, ""


def _make_node_fn(node_id: str) -> Callable[[ChallengeCupState], ChallengeCupState]:
    specs = _specs()

    def _fn(state: ChallengeCupState) -> ChallengeCupState:
        ok, reason = _can_enter(node_id, state)
        if not ok:
            interrupt({"prompt": f"Blocked at {node_id}", "reason": reason, "nodeId": node_id})
            return {**state, "current_node_id": node_id, "blocked_reason": reason}

        spec = specs[node_id]
        completed = list(state.get("completed_node_ids") or [])
        artifacts = dict(state.get("artifacts") or {})
        handoffs = dict(state.get("handoffs") or {})
        side_keys = list(state.get("side_effect_keys") or [])
        node_attempts = dict(state.get("node_attempts") or {})
        attempt = int(node_attempts.get(node_id) or 0)
        key = f"{node_id}:{attempt + 1}:{len(completed)}"
        if key not in side_keys:
            side_keys.append(key)

        patch: ChallengeCupState = {
            "current_node_id": node_id,
            "side_effect_keys": side_keys,
        }

        # --- iteration_decision: always interrupt for a FRESH structured decision ---
        # Do not reuse state.iteration_decision or rerun would infinite-loop on the same kind.
        if node_id == "iteration_decision":
            incoming = interrupt(
                {
                    "prompt": "Provide structured iteration decision",
                    "nodeId": node_id,
                    "gateKind": "iteration_decision",
                    "allowedKinds": [k.value for k in IterationDecisionKind],
                    "controlled_run_attempt": int(state.get("controlled_run_attempt") or 0),
                    "budgetMax": int(state.get("iteration_budget_max") or DEFAULT_ITERATION_BUDGET),
                }
            )
            try:
                decision = normalize_decision_dict(incoming or {})
            except IterationDecisionError as exc:
                # Surface diagnostic via interrupt re-raise path: store blocked reason and fail route
                patch["blocked_reason"] = str(exc)
                patch["last_decision"] = {"error": str(exc), "code": exc.code}
                # Re-interrupt with error so unknown kinds never silently route
                interrupt(
                    {
                        "prompt": "Invalid iteration decision",
                        "nodeId": node_id,
                        "error": str(exc),
                        "code": exc.code,
                    }
                )
                return patch

            kind = parse_decision_kind(decision["decisionKind"])
            # Budget gate for rerun (graph-level fail-fast; service also checks).
            # Prefer decision.budgetMax so service can enforce frozen-protocol limits.
            if kind is IterationDecisionKind.RERUN_SAME_PROTOCOL:
                current_attempt = int(state.get("controlled_run_attempt") or 0)
                budget = int(
                    decision.get("budgetMax")
                    or state.get("iteration_budget_max")
                    or DEFAULT_ITERATION_BUDGET
                )
                patch["iteration_budget_max"] = budget
                if current_attempt >= budget:
                    patch["blocked_reason"] = "iteration_budget_exhausted"
                    patch["iteration_decision"] = decision
                    # Do not route — end branch with blocked marker (no further node)
                    # Returning without completing a route target: mark decision but raise via END
                    # by using a dedicated blocked path — store decision and force END via revise-like flag
                    patch["pending_fork"] = False
                    patch["completion_kind"] = ""
                    # Leave node incomplete for budget block: still record decision for audit
                    completed = list(state.get("completed_node_ids") or [])
                    if node_id not in completed:
                        completed.append(node_id)
                    patch["completed_node_ids"] = completed
                    # Signal router via special kind override
                    blocked_decision = {**decision, "decisionKind": "stop", "_budgetBlocked": True}
                    # Keep original kind for audit
                    patch["iteration_decision"] = decision
                    patch["last_decision"] = decision
                    patch["artifacts"] = {
                        **dict(state.get("artifacts") or {}),
                        "iteration_decision": f"hash:decision:budget_blocked:{key}",
                    }
                    # Use END by setting a synthetic flag read by router
                    patch["_budget_block_end"] = True
                    return patch

            if kind is IterationDecisionKind.REVISE_PROTOCOL:
                patch["pending_fork"] = True
                patch["completion_kind"] = "branched_revision"
            if kind is IterationDecisionKind.STOP:
                patch["terminal_reason"] = str(
                    decision.get("terminalReason") or decision.get("reason") or ""
                )
            if kind is IterationDecisionKind.PROMOTE_CANDIDATE:
                patch["promotion_operation"] = "promote"
                patch["promotion_accepted"] = False  # pending human
            if kind is IterationDecisionKind.ROLLBACK_CANDIDATE:
                patch["promotion_operation"] = "rollback"
                patch["promotion_accepted"] = False

            artifacts["iteration_decision"] = f"hash:decision:{decision.get('decisionId') or key}"
            if node_id not in completed:
                completed.append(node_id)
            patch["iteration_decision"] = decision
            patch["last_decision"] = decision
            patch["completed_node_ids"] = completed
            patch["artifacts"] = artifacts
            patch["handoffs"] = handoffs
            patch["node_attempts"] = node_attempts
            return patch

        if spec.actorKind is ActorKind.HUMAN:
            decision = interrupt(
                {
                    "prompt": f"Resolve human gate at {node_id}",
                    "nodeId": node_id,
                    "gateKind": "human",
                    "promotionOperation": state.get("promotion_operation") or "",
                }
            )
            accepted = bool((decision or {}).get("accept"))
            patch["last_decision"] = decision or {}
            if not accepted:
                if node_id == "knowledge_handoff":
                    patch["knowledge_package_accepted"] = False
                    handoffs[_edge_from_to("knowledge_handoff", "hypothesis_design")] = "rejected"
                elif node_id == "protocol_freeze":
                    patch["frozen_protocol_accepted"] = False
                elif node_id == "smoke_gate":
                    patch["smoke_accepted"] = False
                elif node_id == "candidate_promotion":
                    patch["promotion_accepted"] = False
                patch["handoffs"] = handoffs
                return patch

            if node_id == "knowledge_handoff":
                patch["knowledge_package_accepted"] = True
                artifacts["knowledge_package"] = f"hash:kp:{key}"
                handoffs[_edge_from_to("knowledge_handoff", "hypothesis_design")] = "accepted"
            elif node_id == "protocol_freeze":
                patch["frozen_protocol_accepted"] = True
                # Stable frozen protocol hash for the run (must not change on controlled_run reruns)
                prior = str(
                    (state.get("artifacts") or {}).get("frozen_protocol")
                    or artifacts.get("frozen_protocol")
                    or ""
                )
                artifacts["frozen_protocol"] = prior or "hash:fp:frozen:v1"
            elif node_id == "smoke_gate":
                patch["smoke_accepted"] = True
                artifacts["smoke_release"] = f"hash:sm:{key}"
                handoffs[_edge_from_to("smoke_gate", "controlled_run")] = "accepted"
            elif node_id == "candidate_promotion":
                patch["promotion_accepted"] = True
                op = str(state.get("promotion_operation") or "promote")
                artifacts["promotion_proposal"] = f"hash:promo:{op}:{key}"
                if op == "promote":
                    # Official candidate becomes selected from decision or new hash
                    decision_rec = state.get("iteration_decision") or {}
                    cand = str(decision_rec.get("selectedCandidateRef") or f"candidate:{key}")
                    patch["official_candidate_ref"] = cand
                elif op == "rollback":
                    decision_rec = state.get("iteration_decision") or {}
                    target = str(
                        decision_rec.get("selectedCandidateRef")
                        or decision_rec.get("baselineRef")
                        or state.get("baseline_candidate_ref")
                        or ""
                    )
                    if target:
                        patch["official_candidate_ref"] = target

        # controlled_run: bump attempt; keep frozen protocol hash identical
        if node_id == "controlled_run":
            attempt = attempt + 1
            node_attempts[node_id] = attempt
            patch["controlled_run_attempt"] = attempt
            patch["node_attempts"] = node_attempts
            # Per-attempt artifact; do not overwrite prior attempt keys
            artifacts[f"run_artifacts:attempt:{attempt}"] = f"hash:run:a{attempt}:{key}"
            artifacts["run_artifacts"] = artifacts[f"run_artifacts:attempt:{attempt}"]
            # frozen protocol must remain the freeze-time hash
            if "frozen_protocol" not in artifacts:
                artifacts["frozen_protocol"] = str(
                    (state.get("artifacts") or {}).get("frozen_protocol") or "hash:fp:missing"
                )

        # system/agent nodes: mark artifact kinds produced (except handled above)
        if node_id not in {"iteration_decision", "controlled_run"}:
            for kind in spec.producesArtifactKinds:
                artifacts.setdefault(kind, f"hash:{kind}:{key}")
        elif node_id == "controlled_run":
            for kind in spec.producesArtifactKinds:
                if kind != "run_artifacts":
                    artifacts.setdefault(kind, f"hash:{kind}:{key}")

        if node_id == "result_package":
            term = str(state.get("terminal_reason") or "")
            if not term and not state.get("promotion_accepted"):
                # stop path should have terminal_reason; promote path uses accepted promo
                pass
            artifacts["research_result_package"] = f"hash:rrp:{key}"
            if state.get("completion_kind") != "branched_revision":
                if state.get("promotion_operation") == "promote" and state.get("promotion_accepted"):
                    patch["completion_kind"] = "promoted"
                elif state.get("promotion_operation") == "rollback" and state.get("promotion_accepted"):
                    patch["completion_kind"] = "rolled_back"
                elif term:
                    patch["completion_kind"] = "stopped"

        if node_id not in completed or node_id == "controlled_run":
            # Allow re-entry listing for attempts: track last completion presence
            if node_id not in completed:
                completed.append(node_id)
        patch["completed_node_ids"] = completed
        patch["artifacts"] = artifacts
        patch["handoffs"] = handoffs
        if "node_attempts" not in patch:
            patch["node_attempts"] = node_attempts
        return patch

    return _fn


def route_after_iteration_decision(
    state: ChallengeCupState,
) -> Literal["controlled_run", "candidate_promotion", "result_package", "__end__"]:
    """Conditional router — unknown kinds raise (must never default to promotion)."""
    if state.get("_budget_block_end") or state.get("blocked_reason") == "iteration_budget_exhausted":
        return END  # type: ignore[return-value]
    decision = state.get("iteration_decision") or {}
    kind_raw = decision.get("decisionKind")
    if not kind_raw:
        raise IterationDecisionError("missing decisionKind after iteration_decision", code="missing_decision")
    kind = parse_decision_kind(kind_raw)
    if kind is IterationDecisionKind.REVISE_PROTOCOL:
        return END  # type: ignore[return-value]
    target = route_target_for_decision(kind)
    if target is None:
        raise IterationDecisionError(f"no route for {kind.value}", code="no_route")
    if target not in {"controlled_run", "candidate_promotion", "result_package"}:
        raise IterationDecisionError(f"illegal route target {target}", code="illegal_route")
    return target  # type: ignore[return-value]


# Linear prefix ends at result_evaluation -> iteration_decision; then conditional.
_LINEAR_EDGES: list[tuple[str, str]] = [
    ("source_finding", "source_extraction"),
    ("source_extraction", "evidence_relations"),
    ("evidence_relations", "knowledge_ingestion"),
    ("knowledge_ingestion", "knowledge_handoff"),
    ("knowledge_handoff", "hypothesis_design"),
    ("hypothesis_design", "protocol_design"),
    ("protocol_design", "protocol_review"),
    ("protocol_review", "protocol_freeze"),
    ("protocol_freeze", "smoke_gate"),
    ("smoke_gate", "controlled_run"),
    ("controlled_run", "result_evaluation"),
    ("result_evaluation", "iteration_decision"),
    ("candidate_promotion", "result_package"),
]


def build_challenge_cup_graph() -> StateGraph:
    order = _node_order()
    builder: StateGraph = StateGraph(ChallengeCupState)
    for node_id in order:
        builder.add_node(node_id, _make_node_fn(node_id))
    builder.add_edge(START, order[0])
    for src, dst in _LINEAR_EDGES:
        builder.add_edge(src, dst)
    builder.add_conditional_edges(
        "iteration_decision",
        route_after_iteration_decision,
        {
            "controlled_run": "controlled_run",
            "candidate_promotion": "candidate_promotion",
            "result_package": "result_package",
            END: END,
        },
    )
    builder.add_edge("result_package", END)
    return builder


def compile_challenge_cup_graph(checkpointer: Any):
    return build_challenge_cup_graph().compile(checkpointer=checkpointer)


def compiled_iteration_route_map() -> dict[str, str | None]:
    """Expose expected kind -> target for definition parity tests."""
    return {k.value: v for k, v in {
        IterationDecisionKind.RERUN_SAME_PROTOCOL: "controlled_run",
        IterationDecisionKind.REVISE_PROTOCOL: None,
        IterationDecisionKind.PROMOTE_CANDIDATE: "candidate_promotion",
        IterationDecisionKind.ROLLBACK_CANDIDATE: "candidate_promotion",
        IterationDecisionKind.STOP: "result_package",
    }.items()}
