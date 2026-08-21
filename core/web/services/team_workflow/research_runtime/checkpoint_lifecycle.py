"""LangGraph checkpoint lifecycle without executing workflow nodes."""

from __future__ import annotations

from typing import Any

from langgraph.graph import START

from core.research.workflow.challenge_cup_graph import compile_challenge_cup_graph
from core.research.workflow.checkpoint_store import open_sqlite_checkpointer


def prepare_initial_checkpoint(checkpoint_path: str, thread_id: str) -> str:
    """Create a durable initial checkpoint with source_finding scheduled."""
    with open_sqlite_checkpointer(checkpoint_path) as checkpointer:
        graph = compile_challenge_cup_graph(checkpointer)
        config = {"configurable": {"thread_id": thread_id}}
        saved = graph.update_state(config, {}, as_node=START)
    configurable = saved.get("configurable") or {}
    checkpoint_id = str(configurable.get("checkpoint_id") or "")
    if not checkpoint_id:
        raise RuntimeError("LangGraph did not return an initial checkpointId")
    return checkpoint_id


def latest_checkpoint_id(checkpoint_path: str, thread_id: str) -> str:
    """Latest durable checkpoint id for a thread; empty string when unavailable.

    Offer building must fail soft: an unreadable or missing checkpoint store
    keeps the revise offer unavailable instead of failing the snapshot read.
    """
    try:
        with open_sqlite_checkpointer(checkpoint_path) as checkpointer:
            graph = compile_challenge_cup_graph(checkpointer)
            state = graph.get_state({"configurable": {"thread_id": thread_id}})
        configurable = state.config.get("configurable") or {}
        return str(configurable.get("checkpoint_id") or "").strip()
    except Exception:  # noqa: BLE001 - offer building must fail soft
        return ""


def advance_checkpoint(
    checkpoint_path: str,
    *,
    thread_id: str,
    checkpoint_id: str,
    completed_node_id: str,
    state_patch: dict[str, Any],
) -> tuple[str, list[str]]:
    """Commit a validated node result and return the scheduled successors."""
    with open_sqlite_checkpointer(checkpoint_path) as checkpointer:
        graph = compile_challenge_cup_graph(checkpointer)
        config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": "",
                "checkpoint_id": checkpoint_id,
            }
        }
        saved = graph.update_state(config, state_patch, as_node=completed_node_id)
        state = graph.get_state(saved)
    configurable = saved.get("configurable") or {}
    next_checkpoint_id = str(configurable.get("checkpoint_id") or "")
    if not next_checkpoint_id:
        raise RuntimeError("LangGraph did not return the advanced checkpointId")
    return next_checkpoint_id, [str(node_id) for node_id in state.next or ()]


def fork_checkpoint_at_node(
    checkpoint_path: str,
    *,
    source_thread_id: str,
    source_checkpoint_id: str,
    child_thread_id: str,
    predecessor_node_id: str,
    resume_node_id: str,
    state_patch: dict[str, Any] | None = None,
) -> str:
    """Clone source values into a new thread and schedule one correction node."""
    with open_sqlite_checkpointer(checkpoint_path) as checkpointer:
        graph = compile_challenge_cup_graph(checkpointer)
        child_config = {"configurable": {"thread_id": child_thread_id}}
        existing = graph.get_state(child_config)
        existing_values = dict(existing.values or {})
        if existing_values:
            existing_next = [str(node_id) for node_id in existing.next or ()]
            existing_cfg = existing.config.get("configurable") or {}
            existing_checkpoint_id = str(existing_cfg.get("checkpoint_id") or "")
            if existing_next == [resume_node_id] and existing_checkpoint_id:
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
            raise RuntimeError("source checkpoint does not contain workflow state")
        inherited.update(state_patch or {})
        inherited["current_node_id"] = predecessor_node_id
        inherited.pop("blocked_reason", None)
        inherited.pop("pending_fork", None)
        saved = graph.update_state(
            child_config,
            inherited,
            as_node=predecessor_node_id,
        )
        child_state = graph.get_state(saved)
    scheduled = [str(node_id) for node_id in child_state.next or ()]
    if scheduled != [resume_node_id]:
        raise RuntimeError(
            f"checkpoint fork scheduled {scheduled}, expected {[resume_node_id]}"
        )
    configurable = saved.get("configurable") or {}
    checkpoint_id = str(configurable.get("checkpoint_id") or "")
    if not checkpoint_id:
        raise RuntimeError("LangGraph did not return a child checkpointId")
    return checkpoint_id
