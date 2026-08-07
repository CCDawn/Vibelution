"""Challenge Cup fixed topology as a sequential LangGraph with human interrupts.

v1: linear walk of the 15 definition nodes. Human actorKind nodes use interrupt().
Cross-stage unlock still requires accepted handoff flags in state.
"""

from __future__ import annotations

from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .definition import build_challenge_cup_workflow_definition
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
    return True, ""


def _make_node_fn(node_id: str) -> Callable[[ChallengeCupState], ChallengeCupState]:
    specs = _specs()
    order = _node_order()

    def _fn(state: ChallengeCupState) -> ChallengeCupState:
        ok, reason = _can_enter(node_id, state)
        if not ok:
            # Block without advancing — wait for human correction path.
            interrupt({"prompt": f"Blocked at {node_id}", "reason": reason, "nodeId": node_id})
            return {**state, "current_node_id": node_id}

        spec = specs[node_id]
        completed = list(state.get("completed_node_ids") or [])
        artifacts = dict(state.get("artifacts") or {})
        handoffs = dict(state.get("handoffs") or {})
        side_keys = list(state.get("side_effect_keys") or [])
        key = f"{node_id}:{len(completed)}"
        if key not in side_keys:
            side_keys.append(key)

        patch: ChallengeCupState = {
            "current_node_id": node_id,
            "side_effect_keys": side_keys,
        }

        if spec.actorKind is ActorKind.HUMAN:
            decision = interrupt(
                {
                    "prompt": f"Resolve human gate at {node_id}",
                    "nodeId": node_id,
                    "gateKind": "human",
                }
            )
            accepted = bool((decision or {}).get("accept"))
            patch["last_decision"] = decision or {}
            if not accepted:
                # Stay failed path — mark handoff rejected when applicable
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
                # Do not complete node
                return patch

            if node_id == "knowledge_handoff":
                patch["knowledge_package_accepted"] = True
                artifacts["knowledge_package"] = f"hash:kp:{key}"
                handoffs[_edge_from_to("knowledge_handoff", "hypothesis_design")] = "accepted"
            elif node_id == "protocol_freeze":
                patch["frozen_protocol_accepted"] = True
                artifacts["frozen_protocol"] = f"hash:fp:{key}"
            elif node_id == "smoke_gate":
                patch["smoke_accepted"] = True
                artifacts["smoke_release"] = f"hash:sm:{key}"
                handoffs[_edge_from_to("smoke_gate", "controlled_run")] = "accepted"
            elif node_id == "candidate_promotion":
                patch["promotion_accepted"] = True

        # system/agent nodes: mark artifact kinds produced
        for kind in spec.producesArtifactKinds:
            artifacts.setdefault(kind, f"hash:{kind}:{key}")

        if node_id not in completed:
            completed.append(node_id)
        patch["completed_node_ids"] = completed
        patch["artifacts"] = artifacts
        patch["handoffs"] = handoffs
        return patch

    return _fn


def build_challenge_cup_graph() -> StateGraph:
    order = _node_order()
    builder: StateGraph = StateGraph(ChallengeCupState)
    for node_id in order:
        builder.add_node(node_id, _make_node_fn(node_id))
    builder.add_edge(START, order[0])
    for index in range(len(order) - 1):
        builder.add_edge(order[index], order[index + 1])
    builder.add_edge(order[-1], END)
    return builder


def compile_challenge_cup_graph(checkpointer: Any):
    return build_challenge_cup_graph().compile(checkpointer=checkpointer)
