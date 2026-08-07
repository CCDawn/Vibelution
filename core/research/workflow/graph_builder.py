"""Minimal vertical-slice graph: start -> human gate -> finish.

Full challenge-cup topology is expanded in later tasks; this slice proves
checkpoint, interrupt/resume, handoff fields, and restart recovery.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt


class VerticalSliceState(TypedDict, total=False):
    step: str
    upstream_artifact: str
    handoff_status: str
    input_snapshot_hash: str
    accepted: bool
    side_effect_count: int
    idempotency_key: str


def _start_node(state: VerticalSliceState) -> VerticalSliceState:
    # Upstream artifact + handoff offer (not yet accepted).
    key = state.get("idempotency_key") or "default"
    # Idempotent side effect: only increment once per key on first visit.
    count = int(state.get("side_effect_count") or 0)
    if count == 0:
        count = 1
    return {
        "step": "start",
        "upstream_artifact": f"artifact:{key}:v1",
        "input_snapshot_hash": f"hash:{key}:v1",
        "handoff_status": "pending",
        "side_effect_count": count,
        "idempotency_key": key,
    }


def _gate_node(state: VerticalSliceState) -> VerticalSliceState:
    decision = interrupt(
        {
            "prompt": "Accept upstream handoff?",
            "artifact": state.get("upstream_artifact"),
            "inputSnapshotHash": state.get("input_snapshot_hash"),
            "gateKind": "human",
        }
    )
    accepted = bool((decision or {}).get("accept"))
    return {
        "accepted": accepted,
        "step": "gate",
        "handoff_status": "accepted" if accepted else "rejected",
        # Downstream may only read accepted snapshot hash.
        "input_snapshot_hash": state.get("input_snapshot_hash") or "",
    }


def _finish_node(state: VerticalSliceState) -> VerticalSliceState:
    if state.get("handoff_status") != "accepted":
        return {"step": "blocked", "handoff_status": state.get("handoff_status") or "rejected"}
    return {"step": "done"}


def build_vertical_slice_graph() -> StateGraph:
    builder: StateGraph = StateGraph(VerticalSliceState)
    builder.add_node("start", _start_node)
    builder.add_node("gate", _gate_node)
    builder.add_node("finish", _finish_node)
    builder.add_edge(START, "start")
    builder.add_edge("start", "gate")
    builder.add_edge("gate", "finish")
    builder.add_edge("finish", END)
    return builder


def compile_vertical_slice(checkpointer: Any):
    return build_vertical_slice_graph().compile(checkpointer=checkpointer)
