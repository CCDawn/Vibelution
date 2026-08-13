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

    def retry_attempt(self, dispatch: GraphDispatch) -> GraphDispatchResult:
        """Retry: re-enter the target node via input Command(goto=...) with a
        new frozen attempt (never update_state(as_node))."""
        graph, stack = self._compile()
        try:
            result = graph.invoke(
                Command(
                    goto=dispatch.node_id,
                    update={
                        "active_node_id": dispatch.node_id,
                        "active_attempt": dispatch.attempt,
                        "node_attempts": {dispatch.node_id: dispatch.attempt},
                    },
                ),
                self._config(dispatch.run_id),
            )
            return self._dispatch_result(dispatch, result, graph)
        finally:
            stack.close()

    def resume_action(self, dispatch: GraphDispatch) -> GraphDispatchResult:
        if dispatch.receipt is None:
            raise ValueError("resume_action requires an ExecutionReceipt")
        graph, stack = self._compile()
        try:
            command = Command(resume=dispatch.receipt.to_dict())
            if dispatch.state_update:
                command = Command(
                    resume=dispatch.receipt.to_dict(),
                    update=dict(dispatch.state_update),
                )
            result = graph.invoke(command, self._config(dispatch.run_id))
            return self._dispatch_result(dispatch, result, graph)
        finally:
            stack.close()

    def resume_human(self, dispatch: GraphDispatch) -> GraphDispatchResult:
        return self.resume_action(dispatch)

    def restart_attempt(self, dispatch: GraphDispatch) -> GraphDispatchResult:
        """Retry/restart: acknowledge the old interrupt and re-enter the node
        with a new attempt so the node interrupts with a fresh actionId."""
        graph, stack = self._compile()
        try:
            config = self._config(dispatch.run_id)
            state = graph.get_state(config)
            failed_tasks = [task for task in state.tasks if task.error]
            if failed_tasks:
                interrupted_nodes = {
                    str(item.value.get("nodeId") or "")
                    for task in failed_tasks
                    for item in task.interrupts
                    if isinstance(item.value, Mapping)
                }
                if dispatch.node_id not in interrupted_nodes:
                    raise RuntimeError(
                        "failed checkpoint cannot be replayed for requested node: "
                        f"expected {dispatch.node_id}, found {sorted(interrupted_nodes)}"
                    )
                # A failed LangGraph task retains task-scoped ``__resume__``
                # pending writes.  Sending another resume directly makes the
                # first interrupt consume that stale value again.  Replaying
                # the exact checkpoint with ``None`` is LangGraph's supported
                # time-travel path: it drops cached resume writes and re-emits
                # the same side-effect-free interrupt on a clean descendant.
                graph.invoke(None, state.config)
            result = graph.invoke(
                Command(
                    resume={
                        "restart": True,
                        "attempt": dispatch.attempt,
                        "nodeId": dispatch.node_id,
                    }
                ),
                config,
            )
            return self._dispatch_result(dispatch, result, graph)
        finally:
            stack.close()

    def snapshot(self, run_id: str) -> Mapping[str, Any]:
        graph, stack = self._compile()
        try:
            state = graph.get_state(self._config(run_id))
            interrupts = getattr(state, "interrupts", None) or ()
            pending_action = None
            if interrupts:
                pending_action = PendingAction.from_dict(
                    dict(interrupts[-1].value or {})
                ).to_dict()
            return {
                "checkpointId": _checkpoint_id_of(state),
                "nextNodeIds": [str(node) for node in state.next or ()],
                "values": dict(state.values or {}),
                # Persisted interrupts are the execution authority.  A graph
                # recompile can expose an empty ``state.next`` while retaining
                # the interrupt, so callers must not infer the active node from
                # the task queue alone.
                "pendingAction": pending_action,
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
        state = graph.get_state(self._config(dispatch.run_id))
        values = dict(state.values or {})
        next_node_ids = tuple(str(node_id) for node_id in state.next or ())
        pending = None
        interrupts = getattr(state, "interrupts", None) or ()
        if interrupts:
            # checkpoint 中的 interrupt payload 是权威 PendingAction。
            # restart/retry 会先消费旧 interrupt 再写入新 attempt 的 interrupt；
            # 取最后一个（最新写入）作为权威 pending。
            pending = PendingAction.from_dict(dict(interrupts[-1].value or {}))
        return GraphDispatchResult(
            dispatch_kind=dispatch.dispatch_kind,
            pending_action=pending,
            next_node_ids=next_node_ids,
            checkpoint_id=str(_checkpoint_id_of(state) or ""),
            state=values,
            completed=not next_node_ids and not interrupts,
        )


def _checkpoint_id_of(state: Any) -> str | None:
    configurable = (state.config or {}).get("configurable") or {}
    return str(configurable.get("checkpoint_id") or "") or None


def serialize_state_values(values: Mapping[str, Any]) -> str:
    return json.dumps(values, ensure_ascii=False, sort_keys=True, default=str)
