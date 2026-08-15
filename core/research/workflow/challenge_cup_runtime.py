"""Formal LangGraph runner — interrupt/resume coordinator (spec 4.2/8.2).

GraphState only carries control references. Node functions are replayable:
they derive a deterministic actionId from (runId, nodeId, attempt), build a
typed PendingAction, and interrupt with it. resume only consumes a typed
ExecutionReceipt whose identity must match the frozen action. Business
advancement never uses update_state(..., as_node=...) in this module.

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

from core.research.workflow.contracts import ExecutionReceipt, PendingAction
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.models import ActorKind


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

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> GraphDispatch:
        receipt_payload = payload.get("receipt")
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
    actor_kind = _actor_kind_for(node_id)
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
    )


def _actor_kind_for(node_id: str) -> ActorKind:
    for node in build_challenge_cup_workflow_definition().nodes:
        if node.nodeId == node_id:
            return node.actorKind
    raise ValueError(f"unknown node {node_id}")


def _action_kind_for(actor_kind: ActorKind, node_id: str) -> str:
    if actor_kind == ActorKind.AGENT:
        return "start_agent_task"
    if actor_kind == ActorKind.SYSTEM:
        return f"system_action:{node_id}"
    return f"human_task:{node_id}"


def _node_order() -> list[str]:
    return [node.nodeId for node in build_challenge_cup_workflow_definition().nodes]


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
            "checkpoint_version": int(state.get("checkpoint_version") or 0) + 1,
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
    if decision == "rerun_same_protocol":
        return "controlled_run"
    if decision == "revise_protocol":
        return END  # type: ignore[return-value]
    if decision in ("promote_candidate", "rollback_candidate", "stop"):
        return "version_governance"
    raise ValueError(f"unknown iteration decision {decision!r}")


def route_after_version_governance(
    state: ChallengeCupGraphState,
) -> Literal["candidate_promotion", "result_package", "__end__"]:
    if state.get("blocked_outcome"):
        return END  # type: ignore[return-value]
    decision = str(state.get("branch_decision") or "")
    if decision == "promote_candidate":
        return "candidate_promotion"
    if decision in ("stop", "rollback_candidate"):
        return "result_package"
    raise ValueError(f"unknown governed decision {decision!r}")


def _route_after_linear(source: str, target: str):
    def route(state: ChallengeCupGraphState) -> Literal["__end__"] | str:
        if state.get("blocked_outcome"):
            return END  # type: ignore[return-value]
        return target

    route.__name__ = f"route_after_{source}"
    return route


def successor_map() -> dict[str, tuple[str, ...]]:
    """Deterministic successor set per node (drives worker attempt injection)."""
    successors: dict[str, tuple[str, ...]] = {
        source: (target,) for source, target in _LINEAR_EDGES
    }
    successors["iteration_decision"] = ("controlled_run", "version_governance")
    successors["version_governance"] = ("candidate_promotion", "result_package")
    successors["candidate_promotion"] = ("result_package",)
    successors["result_package"] = ()
    return successors


_LINEAR_EDGES: tuple[tuple[str, str], ...] = (
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
)


def build_formal_graph() -> StateGraph:
    builder: StateGraph = StateGraph(ChallengeCupGraphState)
    for node_id in _node_order():
        builder.add_node(node_id, _make_node_fn(node_id))
    builder.add_edge(START, _node_order()[0])
    for source, target in _LINEAR_EDGES:
        builder.add_conditional_edges(
            source,
            _route_after_linear(source, target),
            {target: target, END: END},
        )
    builder.add_conditional_edges(
        "iteration_decision",
        route_after_iteration_decision,
        {
            "controlled_run": "controlled_run",
            "version_governance": "version_governance",
            END: END,
        },
    )
    builder.add_conditional_edges(
        "version_governance",
        route_after_version_governance,
        {
            "candidate_promotion": "candidate_promotion",
            "result_package": "result_package",
            END: END,
        },
    )
    builder.add_edge("candidate_promotion", "result_package")
    builder.add_edge("result_package", END)
    return builder


def _is_concurrent_update_error(exc: BaseException) -> bool:
    text = str(exc)
    return (
        type(exc).__name__ == "InvalidUpdateError"
        or "Can receive only one value per step" in text
        or "INVALID_CONCURRENT_GRAPH_UPDATE" in text
    )


def _retry_update(dispatch: GraphDispatch) -> dict[str, Any]:
    """Command.update for retry while an interrupt is still on the thread.

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
    return update


def _enter_update(dispatch: GraphDispatch) -> dict[str, Any]:
    """Values for a prior ``update_state`` superstep before Command.goto.

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
    return update


class ChallengeCupGraphCoordinator:
    """Owns the checkpointer and compiles the formal graph per invocation."""

    def __init__(self, checkpoint_path: Path | str) -> None:
        self._checkpoint_path = Path(checkpoint_path)
        self._checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    def _compile(self):
        from contextlib import ExitStack

        from core.research.workflow.checkpoint_store import open_sqlite_checkpointer

        stack = ExitStack()
        checkpointer = stack.enter_context(
            open_sqlite_checkpointer(str(self._checkpoint_path))
        )
        graph = build_formal_graph().compile(checkpointer=checkpointer)
        return graph, stack

    def _config(self, run_id: str) -> dict[str, dict[str, str]]:
        return {"configurable": {"thread_id": run_id}}

    def start_attempt(self, dispatch: GraphDispatch) -> GraphDispatchResult:
        graph, stack = self._compile()
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
            "checkpoint_version": 1,
        }
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
        """Re-enter a node without writing last-value keys in the goto step.

        Sequence: copy-away colliding writes, clear leftover tasks with
        ``as_node=END`` (checkpoint hygiene, not a workflow node), write
        routing fields in their own superstep, then invoke with thread_id
        only. Command.goto must not share a superstep with ``run_id``.
        """
        thread = self._config(dispatch.run_id)
        self._ensure_readable(graph, dispatch.run_id)
        try:
            graph.update_state(thread, None, as_node=END)
        except Exception as exc:
            if not _is_concurrent_update_error(exc):
                raise
            graph.update_state(thread, None, as_node="__copy__")
            graph.update_state(thread, None, as_node=END)
        values = _enter_update(dispatch)
        try:
            graph.update_state(thread, values)
        except Exception:
            pass
        state = graph.get_state(thread)
        next_ids = {str(node_id) for node_id in (state.next or ())}
        pending = _pending_from_state(state)
        if dispatch.node_id in next_ids or (
            pending is not None and pending.node_id == dispatch.node_id
        ):
            result = graph.invoke(None, thread)
        else:
            result = graph.invoke(Command(goto=dispatch.node_id), thread)
        return self._dispatch_result(dispatch, result, graph)

    def retry_attempt(self, dispatch: GraphDispatch) -> GraphDispatchResult:
        """Retry: re-enter the target node via input Command(goto=...) with a
        new frozen attempt (never update_state(as_node))."""
        graph, stack = self._compile()
        try:
            result = graph.invoke(
                Command(
                    goto=dispatch.node_id,
                    update=_retry_update(dispatch),
                ),
                self._config(dispatch.run_id),
            )
            return self._dispatch_result(dispatch, result, graph)
        finally:
            stack.close()

    def enter_node(self, dispatch: GraphDispatch) -> GraphDispatchResult:
        """Re-enter a node after the thread has no interrupt (routed to END)."""
        graph, stack = self._compile()
        try:
            return self._goto_node(graph, dispatch)
        finally:
            stack.close()

    def resume_action(self, dispatch: GraphDispatch) -> GraphDispatchResult:
        if dispatch.receipt is None:
            raise ValueError("resume_action requires an ExecutionReceipt")
        graph, stack = self._compile()
        try:
            config = self._config(dispatch.run_id)
            receipt_payload = dispatch.receipt.to_dict()
            resume_value: Any = _resume_value_for_state(
                self._read_state(graph, config, heal=True),
                node_id=dispatch.node_id,
                receipt_payload=receipt_payload,
            )
            command = Command(resume=resume_value)
            if dispatch.state_update:
                command = Command(
                    resume=resume_value,
                    update=dict(dispatch.state_update),
                )
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
        graph, stack = self._compile()
        try:
            config = self._config(dispatch.run_id)
            state = self._read_state(graph, config, heal=True)
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
            }
            if dispatch.team_id:
                replay_values["team_id"] = dispatch.team_id
            if dispatch.input_snapshot_hash:
                replay_values["input_snapshot_hash"] = dispatch.input_snapshot_hash
            replay_config = graph.update_state(
                state.config,
                replay_values,
            )
            result = graph.invoke(None, replay_config)
            return self._dispatch_result(dispatch, result, graph)
        finally:
            stack.close()

    def snapshot(self, run_id: str) -> Mapping[str, Any]:
        graph, stack = self._compile()
        try:
            state = self._read_state(graph, self._config(run_id), heal=True)
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
        """
        graph, stack = self._compile()
        try:
            child_config = self._config(child_thread_id)
            existing = graph.get_state(child_config)
            existing_checkpoint_id = _checkpoint_id_of(existing)
            if (existing.values or {}) and existing_checkpoint_id:
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
            # thread_id == runId 契约：child 线程的 run_id 必须指向 child run。
            inherited["run_id"] = child_thread_id
            inherited.update(dict(state_patch or {}))
            saved = graph.update_state(
                child_config,
                inherited,
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


def _resume_value_for_state(
    state: Any, *, node_id: str, receipt_payload: Mapping[str, Any]
) -> Any:
    """Use an interrupt-id map when LangGraph has more than one pending interrupt."""
    interrupts = [
        item
        for item in (getattr(state, "interrupts", None) or ())
        if getattr(item, "id", None)
    ]
    if len(interrupts) <= 1:
        return receipt_payload
    matched: dict[str, Any] = {}
    for item in interrupts:
        value = item.value if isinstance(getattr(item, "value", None), Mapping) else {}
        if str(value.get("nodeId") or "") == node_id:
            matched[str(item.id)] = receipt_payload
    if len(matched) == 1:
        return matched
    raise RuntimeError(
        f"cannot resume {node_id}: {len(interrupts)} interrupts, matched {len(matched)}"
    )


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


def serialize_state_values(values: Mapping[str, Any]) -> str:
    return json.dumps(values, ensure_ascii=False, sort_keys=True, default=str)
