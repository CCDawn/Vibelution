"""WorkflowCommandService — the single write entry (spec 7.1/7.2).

Synchronous acceptance flow:
  1. teamId non-empty and exactly equal to the run's teamId;
  2. canonical requestHash;
  3. idempotency lookup FIRST: same hash replays the original receipt,
     different hash raises idempotency_conflict;
  4. expectedRunVersion check;
  5. NodeReadiness recomputed (never cached) for attempt-creating commands;
  6. not ready -> NodeNotReadyError, zero side effects;
  7. ready -> one BEGIN IMMEDIATE transaction: conditional version bump,
     accepted command, NodeAttempt(starting), graph_dispatch outbox,
     command_accepted + node_starting events;
  8. commit -> CommandReceipt; after-commit wakes the graph worker.

No network / model / agent / budget / domain writes happen inside the
transaction.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from core.research.workflow.contracts import (
    CommandReceipt,
    CommandRequest,
    WorkflowCommandKind,
)
from core.research.workflow.ledger import (
    CommandNotAllowedError,
    IdempotencyConflictError,
    RunVersionConflictError,
    WorkflowLedgerStore,
)
from core.research.workflow.transitions import (
    HumanTaskStatus,
    NodeAttemptStatus,
    RunStatus,
    require_human_task_transition,
    require_run_transition,
)
from core.web.services.team_workflow.research_runtime.readiness import (
    NodeReadinessService,
)
from core.web.services.team_workflow.research_runtime.readiness.common import (
    DomainReadinessContext,
)

from .ids import new_id


class WorkflowCommandError(RuntimeError):
    """Base for typed command failures."""


class RunNotFoundError(WorkflowCommandError):
    def __init__(self, run_id: str) -> None:
        super().__init__(f"run {run_id} not found")
        self.run_id = run_id


class TeamScopeMismatchError(WorkflowCommandError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class CommandForbiddenError(WorkflowCommandError):
    def __init__(self, detail: str = "operator lacks permission for this command") -> None:
        super().__init__(detail)
        self.detail = detail


class NodeNotReadyError(WorkflowCommandError):
    def __init__(self, readiness: Any, run_version: int) -> None:
        super().__init__("node_not_ready")
        self.readiness = readiness
        self.run_version = run_version


_ATTEMPT_CREATING_COMMANDS = frozenset(
    {WorkflowCommandKind.START_NODE, WorkflowCommandKind.RETRY_NODE}
)

# 高影响命令：必须由服务端可验证的 operator 身份执行（P1-6）。
_OPERATOR_ONLY_COMMANDS = frozenset(
    {
        WorkflowCommandKind.CANCEL_NODE,
        WorkflowCommandKind.CANCEL_RUN,
        WorkflowCommandKind.REBIND_NODE,
        WorkflowCommandKind.EXTEND_BUDGET,
        WorkflowCommandKind.RESOLVE_HUMAN_TASK,
        WorkflowCommandKind.FORK_REVISION,
        WorkflowCommandKind.RECONCILE_RUN,
    }
)


class WorkflowCommandService:
    def __init__(
        self,
        *,
        store: WorkflowLedgerStore,
        readiness_service: NodeReadinessService,
        readiness_context: Callable[[], DomainReadinessContext],
        clock: Callable[[], int] | None = None,
        wake_worker: Callable[[], None] | None = None,
    ) -> None:
        self._store = store
        self._readiness = readiness_service
        self._readiness_context = readiness_context
        self._clock = clock or (lambda: int(time.time() * 1000))
        self._wake_worker = wake_worker or (lambda: None)
        self._handlers: dict[WorkflowCommandKind, Callable] = {
            WorkflowCommandKind.START_NODE: self._handle_start_node,
            WorkflowCommandKind.RETRY_NODE: self._handle_retry_node,
            WorkflowCommandKind.CANCEL_NODE: self._handle_cancel_node,
            WorkflowCommandKind.CANCEL_RUN: self._handle_cancel_run,
            WorkflowCommandKind.RESOLVE_HUMAN_TASK: self._handle_resolve_human_task,
            WorkflowCommandKind.EXTEND_BUDGET: self._handle_extend_budget,
            WorkflowCommandKind.RECONCILE_RUN: self._handle_reconcile_run,
            WorkflowCommandKind.REBIND_NODE: self._handle_rebind_node,
            WorkflowCommandKind.FORK_REVISION: self._handle_fork_revision,
        }

    # ------------------------------------------------------------ public

    def submit(self, request: CommandRequest) -> CommandReceipt:
        if not request.team_id:
            raise TeamScopeMismatchError("teamId 缺失")
        if not request.idempotency_key:
            raise WorkflowCommandError("idempotencyKey 缺失")

        run = self._store.get_run(request.run_id)
        if run is None:
            raise RunNotFoundError(request.run_id)
        if run.team_id != request.team_id:
            raise TeamScopeMismatchError(
                f"run {request.run_id} 属于 {run.team_id}，请求 teamId={request.team_id}"
            )

        request_hash = request.request_hash()
        existing = self._store.get_command_by_idempotency(request.run_id, request.idempotency_key)
        if existing is not None:
            return self._replay(existing, request_hash)

        if request.expected_run_version != run.run_version:
            raise RunVersionConflictError(
                f"expected {request.expected_run_version}, current {run.run_version}"
            )

        if request.command in _OPERATOR_ONLY_COMMANDS:
            self._authorize_operator(request)

        handler = self._handlers.get(request.command)
        if handler is None:
            raise WorkflowCommandError(
                f"command {request.command.value} 尚未接入"
            )

        if request.command in _ATTEMPT_CREATING_COMMANDS:
            if not request.node_id:
                raise WorkflowCommandError(f"{request.command.value} 需要 nodeId")
            readiness = self._readiness.evaluate(
                team_id=request.team_id,
                run_id=request.run_id,
                node_id=request.node_id,
                context=self._readiness_context(),
                use_cache=False,
            )
            if not readiness.ready:
                raise NodeNotReadyError(readiness, run.run_version)

        future = self._store.submit(
            lambda uow: handler(uow, request, request_hash),
            force_flush=True,
        )
        return future.result(timeout=30)

    def _authorize_operator(self, request: CommandRequest) -> None:
        """Server-side operator authorization for high-impact commands.

        The request must carry a verifiable operator identity; the frozen
        command contract never trusts a raw client string for control actions.
        """
        actor = request.requested_by
        actor_type = str(getattr(actor, "actor_type", "") or "").lower()
        actor_id = str(getattr(actor, "actor_id", "") or "").strip()
        if actor_type not in ("operator", "user"):
            raise CommandForbiddenError("command requires an operator identity")
        if not actor_id:
            raise CommandForbiddenError("command requires a non-empty operator id")

    def _replay(self, existing: Any, request_hash: str) -> CommandReceipt:
        if existing.request_hash != request_hash:
            raise IdempotencyConflictError()
        if existing.result_json:
            payload = json.loads(existing.result_json)
            return CommandReceipt(
                command_id=str(payload.get("commandId") or ""),
                run_id=str(payload.get("runId") or ""),
                status=str(payload.get("status") or ""),
                accepted_run_version=payload.get("acceptedRunVersion"),
                idempotency_key=str(payload.get("idempotencyKey") or ""),
                latest_event_sequence=int(payload.get("latestEventSequence") or 0),
            )
        return CommandReceipt(
            command_id=existing.command_id,
            run_id=existing.run_id,
            status=existing.status,
            accepted_run_version=existing.accepted_run_version,
            idempotency_key=existing.idempotency_key,
            latest_event_sequence=0,
        )

    # ------------------------------------------------------- handlers

    def _handle_start_node(
        self, uow, request: CommandRequest, request_hash: str
    ) -> CommandReceipt:
        node_id = request.node_id
        now_ms = self._clock()
        latest = uow.repository.latest_attempt(request.run_id, node_id)
        if latest is not None and latest.status in (
            NodeAttemptStatus.STARTING.value,
            NodeAttemptStatus.DISPATCHING.value,
            NodeAttemptStatus.RUNNING.value,
            NodeAttemptStatus.WAITING_HUMAN.value,
        ):
            raise CommandNotAllowedError("该节点已有进行中的 attempt")
        attempt = (latest.attempt + 1) if latest is not None else 1
        node_run_id = f"nr-{request.run_id}-{node_id}-a{attempt}"
        command_id = new_id("cmd")

        bumped = _bump(uow, request, event_count=2, now_ms=now_ms)
        accepted_version, sequence = bumped

        run = uow.repository.get_run(request.run_id)
        binding_snapshot_id = _binding_snapshot_id(uow, request.run_id, node_id)
        uow.repository.insert_command(
            _command_record(
                command_id=command_id,
                request=request,
                request_hash=request_hash,
                accepted_run_version=accepted_version,
                now_ms=now_ms,
            )
        )
        uow.repository.insert_attempt(
            _attempt_record(
                node_run_id=node_run_id,
                run_id=request.run_id,
                node_id=node_id,
                attempt=attempt,
                status=NodeAttemptStatus.STARTING.value,
                command_id=command_id,
                input_snapshot_hash=_input_snapshot_hash(uow, request.run_id),
                started_at_ms=now_ms,
                retry_of_node_run_id=latest.node_run_id if latest else None,
                binding_snapshot_id=binding_snapshot_id,
            )
        )
        uow.repository.insert_outbox(
            _graph_dispatch_record(
                uow=uow,
                run=run,
                attempt=_node_attempt_for_dispatch(
                    node_run_id=node_run_id,
                    run_id=request.run_id,
                    node_id=node_id,
                    attempt=attempt,
                    binding_snapshot_id=binding_snapshot_id,
                ),
                command_id=command_id,
                now_ms=now_ms,
            )
        )
        uow.repository.insert_event(
            _event_record(
                run_id=request.run_id,
                sequence=sequence - 1,
                event_id=new_id("evt"),
                run_version=accepted_version,
                event_type="command_accepted",
                correlation_id=request.idempotency_key,
                payload={
                    "commandId": command_id,
                    "nodeId": node_id,
                    "expectedRunVersion": request.expected_run_version,
                    "acceptedRunVersion": accepted_version,
                },
                now_ms=now_ms,
            )
        )
        uow.repository.insert_event(
            _event_record(
                run_id=request.run_id,
                sequence=sequence,
                event_id=new_id("evt"),
                run_version=accepted_version,
                event_type="node_starting",
                correlation_id=request.idempotency_key,
                payload={"nodeRunId": node_run_id, "nodeId": node_id, "attempt": attempt},
                now_ms=now_ms,
            )
        )
        uow.repository.update_run_status(
            request.run_id,
            request.team_id,
            RunStatus.RUNNING.value,
            now_ms,
            active_node_id=node_id,
        )
        uow.after_commit(self._wake_worker)
        return _receipt(uow, request, command_id, accepted_version, sequence, now_ms)

    def _handle_retry_node(self, uow, request: CommandRequest, request_hash: str) -> CommandReceipt:
        node_id = request.node_id
        latest = uow.repository.latest_attempt(request.run_id, node_id)
        if latest is None:
            raise CommandNotAllowedError("该节点没有可重试的 attempt")
        if latest.status not in (
            NodeAttemptStatus.FAILED.value,
            NodeAttemptStatus.BLOCKED.value,
            NodeAttemptStatus.CANCELLED.value,
        ):
            raise CommandNotAllowedError(f"attempt {latest.status} 不可重试")
        receipt = self._handle_start_node(uow, request, request_hash)
        uow.repository.update_attempt_status(
            latest.node_run_id,
            NodeAttemptStatus.STALE.value,
            self._clock(),
        )
        return receipt

    def _handle_cancel_node(self, uow, request: CommandRequest, request_hash: str) -> CommandReceipt:
        node_id = request.node_id
        latest = uow.repository.latest_attempt(request.run_id, node_id)
        if latest is None or latest.status not in (
            NodeAttemptStatus.STARTING.value,
            NodeAttemptStatus.DISPATCHING.value,
            NodeAttemptStatus.RUNNING.value,
            NodeAttemptStatus.WAITING_HUMAN.value,
            NodeAttemptStatus.BLOCKED.value,
        ):
            raise CommandNotAllowedError("该节点没有可取消的 attempt")
        now_ms = self._clock()
        command_id = new_id("cmd")
        bumped = _bump(uow, request, event_count=1, now_ms=now_ms)
        accepted_version, sequence = bumped
        uow.repository.insert_command(
            _command_record(
                command_id=command_id,
                request=request,
                request_hash=request_hash,
                accepted_run_version=accepted_version,
                now_ms=now_ms,
            )
        )
        uow.repository.update_attempt_status(
            latest.node_run_id,
            NodeAttemptStatus.CANCELLED.value,
            now_ms,
            finished_at_ms=now_ms,
        )
        uow.repository.insert_event(
            _event_record(
                run_id=request.run_id,
                sequence=sequence,
                event_id=new_id("evt"),
                run_version=accepted_version,
                event_type="node_blocked",
                correlation_id=request.idempotency_key,
                payload={"nodeRunId": latest.node_run_id, "nodeId": node_id, "cancelled": True},
                now_ms=now_ms,
            )
        )
        return _receipt(uow, request, command_id, accepted_version, sequence, now_ms)

    def _handle_cancel_run(self, uow, request: CommandRequest, request_hash: str) -> CommandReceipt:
        now_ms = self._clock()
        run = uow.repository.get_run(request.run_id)
        require_run_transition(RunStatus(run.status), RunStatus.CANCELLED)
        command_id = new_id("cmd")
        bumped = _bump(uow, request, event_count=1, now_ms=now_ms)
        accepted_version, sequence = bumped
        uow.repository.insert_command(
            _command_record(
                command_id=command_id,
                request=request,
                request_hash=request_hash,
                accepted_run_version=accepted_version,
                now_ms=now_ms,
            )
        )
        uow.repository.update_run_status(
            request.run_id,
            request.team_id,
            RunStatus.CANCELLED.value,
            now_ms,
            completion_kind="cancelled",
            terminal_reason=str(request.payload.get("reason") or "operator cancelled"),
        )
        uow.repository.insert_event(
            _event_record(
                run_id=request.run_id,
                sequence=sequence,
                event_id=new_id("evt"),
                run_version=accepted_version,
                event_type="run_blocked",
                correlation_id=request.idempotency_key,
                payload={"cancelled": True, "reason": str(request.payload.get("reason") or "")},
                now_ms=now_ms,
            )
        )
        return _receipt(uow, request, command_id, accepted_version, sequence, now_ms)

    def _handle_resolve_human_task(
        self, uow, request: CommandRequest, request_hash: str
    ) -> CommandReceipt:
        task_id = str(request.payload.get("taskId") or "")
        decision = str(request.payload.get("decision") or "")
        if not task_id or decision not in ("accept", "reject", "revise"):
            raise WorkflowCommandError("resolve_human_task 需要 taskId 和 decision(accept/reject/revise)")
        row = uow.repository.get_human_task(task_id)
        if row is None:
            raise RunNotFoundError(task_id)
        if str(row[1]) != request.run_id:
            raise TeamScopeMismatchError("human task 不属于该 run")
        now_ms = self._clock()
        target = {
            "accept": HumanTaskStatus.ACCEPTED.value,
            "reject": HumanTaskStatus.REJECTED.value,
            "revise": HumanTaskStatus.REVISED.value,
        }[decision]
        require_human_task_transition(HumanTaskStatus.PENDING, HumanTaskStatus(target))
        command_id = new_id("cmd")
        bumped = _bump(uow, request, event_count=1, now_ms=now_ms)
        accepted_version, sequence = bumped
        uow.repository.insert_command(
            _command_record(
                command_id=command_id,
                request=request,
                request_hash=request_hash,
                accepted_run_version=accepted_version,
                now_ms=now_ms,
            )
        )
        decision_json = json.dumps(
            {
                "decision": decision,
                "reason": str(request.payload.get("reason") or ""),
                "requestedBy": request.requested_by.to_dict(),
            },
            ensure_ascii=False,
        )
        uow.repository.update_human_task_decision(
            task_id, target, now_ms, decision_json=decision_json
        )
        # 人工决策后通过正式 graph resume 推进（T5 契约：Human 节点可恢复）。
        attempt = uow.repository.get_attempt(str(row[2]))
        pending_action_id = attempt.pending_action_id if attempt else None
        if decision == "revise":
            # revise：不把决策压成 failed receipt，而是 fork 新 Run
            # （spec 8.4 revision fork；父 Run 保持 lineage）。
            parent_run = uow.repository.get_run(request.run_id)
            from_node_id = str(
                request.payload.get("fromNodeId") or request.node_id or ""
            )
            if parent_run is None or not from_node_id:
                raise WorkflowCommandError(
                    "revise 决策需要 fromNodeId 且父 run 存在"
                )
            self._create_revision_fork(
                uow,
                parent=parent_run,
                from_node_id=from_node_id,
                reason=str(request.payload.get("reason") or "revise protocol"),
                checkpoint_id=str(request.payload.get("checkpointId") or ""),
                requested_by=request.requested_by,
                command_id=command_id,
                now_ms=now_ms,
            )
        elif pending_action_id:
            from core.research.workflow.contracts import ExecutionReceipt

            receipt = ExecutionReceipt(
                action_id=pending_action_id,
                node_run_id=str(row[2]),
                outcome="succeeded" if decision == "accept" else "failed",
                artifact_receipt_ids=(),
                execution_anchor_id=None,
                budget_receipt_id=None,
                problem=None,
                completed_at_ms=now_ms,
            )
            uow.repository.insert_outbox(
                _human_resume_dispatch(uow, request, str(row[2]), receipt, command_id, now_ms)
            )
        uow.repository.insert_event(
            _event_record(
                run_id=request.run_id,
                sequence=sequence,
                event_id=new_id("evt"),
                run_version=accepted_version,
                event_type="handoff_accepted" if decision == "accept" else "handoff_rejected",
                correlation_id=request.idempotency_key,
                payload={
                    "taskId": task_id,
                    "decision": decision,
                    "nodeRunId": str(row[2]),
                },
                now_ms=now_ms,
            )
        )
        return _receipt(uow, request, command_id, accepted_version, sequence, now_ms)

    def _handle_extend_budget(self, uow, request: CommandRequest, request_hash: str) -> CommandReceipt:
        now_ms = self._clock()
        run = uow.repository.get_run(request.run_id)
        limits = json.loads(run.safety_limits_json)
        limits.update(dict(request.payload.get("limits") or {}))
        command_id = new_id("cmd")
        bumped = _bump(uow, request, event_count=1, now_ms=now_ms)
        accepted_version, sequence = bumped
        uow.repository.insert_command(
            _command_record(
                command_id=command_id,
                request=request,
                request_hash=request_hash,
                accepted_run_version=accepted_version,
                now_ms=now_ms,
            )
        )
        uow.repository.update_run_safety_limits(
            request.run_id, request.team_id, json.dumps(limits), now_ms
        )
        uow.repository.insert_event(
            _event_record(
                run_id=request.run_id,
                sequence=sequence,
                event_id=new_id("evt"),
                run_version=accepted_version,
                event_type="budget_settled",
                correlation_id=request.idempotency_key,
                payload={"limits": limits},
                now_ms=now_ms,
            )
        )
        return _receipt(uow, request, command_id, accepted_version, sequence, now_ms)

    def _handle_reconcile_run(self, uow, request: CommandRequest, request_hash: str) -> CommandReceipt:
        now_ms = self._clock()
        run = uow.repository.get_run(request.run_id)
        require_run_transition(RunStatus(run.status), RunStatus.RUNNING)
        command_id = new_id("cmd")
        bumped = _bump(uow, request, event_count=1, now_ms=now_ms)
        accepted_version, sequence = bumped
        uow.repository.insert_command(
            _command_record(
                command_id=command_id,
                request=request,
                request_hash=request_hash,
                accepted_run_version=accepted_version,
                now_ms=now_ms,
            )
        )
        uow.repository.update_run_status(request.run_id, request.team_id, RunStatus.RUNNING.value, now_ms)
        uow.repository.insert_event(
            _event_record(
                run_id=request.run_id,
                sequence=sequence,
                event_id=new_id("evt"),
                run_version=accepted_version,
                event_type="run_blocked",
                correlation_id=request.idempotency_key,
                payload={"reconciled": True},
                now_ms=now_ms,
            )
        )
        return _receipt(uow, request, command_id, accepted_version, sequence, now_ms)

    def _handle_rebind_node(self, uow, request: CommandRequest, request_hash: str) -> CommandReceipt:
        node_id = request.node_id
        if not node_id:
            raise WorkflowCommandError("rebind_node 需要 nodeId")
        now_ms = self._clock()
        command_id = new_id("cmd")
        bumped = _bump(uow, request, event_count=1, now_ms=now_ms)
        accepted_version, sequence = bumped
        uow.repository.insert_command(
            _command_record(
                command_id=command_id,
                request=request,
                request_hash=request_hash,
                accepted_run_version=accepted_version,
                now_ms=now_ms,
            )
        )
        uow.repository.update_run_binding_set(
            request.run_id,
            request.team_id,
            str(request.payload.get("bindingSnapshotSetId") or "rebound"),
            now_ms,
        )
        uow.repository.insert_event(
            _event_record(
                run_id=request.run_id,
                sequence=sequence,
                event_id=new_id("evt"),
                run_version=accepted_version,
                event_type="execution_anchor_bound",
                correlation_id=request.idempotency_key,
                payload={"nodeId": node_id, "rebound": True},
                now_ms=now_ms,
            )
        )
        return _receipt(uow, request, command_id, accepted_version, sequence, now_ms)

    def _handle_fork_revision(
        self, uow, request: CommandRequest, request_hash: str
    ) -> CommandReceipt:
        from_node_id = str(request.payload.get("fromNodeId") or "")
        reason = str(request.payload.get("reason") or "")
        if not from_node_id:
            raise WorkflowCommandError("fork_revision 需要 fromNodeId（实验设计节点）")
        if not reason:
            raise WorkflowCommandError("fork_revision 需要 reason")
        # fromNodeId 必须属于实验设计阶段（revision 只从实验设计分支）。
        from core.research.workflow.definition import (
            build_challenge_cup_workflow_definition,
        )
        from core.research.workflow.models import WorkflowStageId

        definition = build_challenge_cup_workflow_definition()
        node_spec = next(
            (n for n in definition.nodes if n.nodeId == from_node_id), None
        )
        if node_spec is None:
            raise WorkflowCommandError(f"unknown fromNodeId: {from_node_id}")
        if node_spec.stageId not in (
            WorkflowStageId.EXPERIMENT_DESIGN,
            WorkflowStageId.KNOWLEDGE_COLLECTION,
        ):
            raise WorkflowCommandError("fork_revision 只能从知识/实验设计节点分支")

        parent = uow.repository.get_run(request.run_id)
        if parent is None:
            raise RunNotFoundError(request.run_id)
        if parent.status in ("succeeded", "failed", "cancelled", "archived"):
            raise WorkflowCommandError("terminal run 不能 fork revision")

        now_ms = self._clock()
        command_id = new_id("cmd")
        event_count = 2
        bumped = _bump(uow, request, event_count=event_count, now_ms=now_ms)
        accepted_version, sequence = bumped

        # 新 command 属于父 run（谱系：revision fork 的驱动命令挂在父上）。
        # 必须先插入 command，child attempt/outbox 才能引用它（FK）。
        uow.repository.insert_command(
            _command_record(
                command_id=command_id,
                request=request,
                request_hash=request_hash,
                accepted_run_version=accepted_version,
                now_ms=now_ms,
            )
        )

        child_run_id = self._create_revision_fork(
            uow,
            parent=parent,
            from_node_id=from_node_id,
            reason=reason,
            checkpoint_id=str(request.payload.get("checkpointId") or ""),
            requested_by=request.requested_by,
            command_id=command_id,
            now_ms=now_ms,
        )

        uow.repository.insert_event(
            _event_record(
                run_id=request.run_id,
                sequence=sequence - 1,
                event_id=new_id("evt"),
                run_version=accepted_version,
                event_type="revision_forked",
                correlation_id=request.idempotency_key,
                payload={
                    "commandId": command_id,
                    "childRunId": child_run_id,
                    "fromNodeId": from_node_id,
                    "reason": reason,
                    "requestedBy": request.requested_by.to_dict(),
                },
                now_ms=now_ms,
            )
        )
        uow.repository.insert_event(
            _event_record(
                run_id=request.run_id,
                sequence=sequence,
                event_id=new_id("evt"),
                run_version=accepted_version,
                event_type="command_accepted",
                correlation_id=request.idempotency_key,
                payload={
                    "commandId": command_id,
                    "nodeId": from_node_id,
                    "expectedRunVersion": request.expected_run_version,
                    "acceptedRunVersion": accepted_version,
                    "forkOf": request.run_id,
                },
                now_ms=now_ms,
            )
        )
        uow.after_commit(self._wake_worker)
        return _receipt(uow, request, command_id, accepted_version, sequence, now_ms)

    def _create_revision_fork(
        self,
        uow,
        *,
        parent: Any,
        from_node_id: str,
        reason: str,
        checkpoint_id: str,
        requested_by: Any,
        command_id: str,
        now_ms: int,
    ) -> str:
        """Create the child revision run (parent lineage) in the same transaction.

        Pure child creation: no runVersion bump, no command, no event — the
        caller owns those. Used by fork_revision and by human revise decisions.
        """
        from core.research.workflow.ledger import RunRecord

        child_run_id = new_id("run")
        child_thread_id = f"thread-{child_run_id}"
        input_snapshot = {}
        if parent.input_snapshot_json:
            try:
                input_snapshot = json.loads(parent.input_snapshot_json)
            except (TypeError, ValueError):
                input_snapshot = {}
        input_snapshot = dict(input_snapshot)

        child = RunRecord(
            run_id=child_run_id,
            team_id=parent.team_id,
            workflow_id=parent.workflow_id,
            workflow_version_id=parent.workflow_version_id,
            thread_id=child_thread_id,
            project_id=parent.project_id,
            question_id=parent.question_id,
            status="created",
            run_version=1,
            last_event_sequence=0,
            input_snapshot_json=json.dumps(input_snapshot, ensure_ascii=False),
            input_snapshot_hash=parent.input_snapshot_hash,
            safety_limits_json=parent.safety_limits_json,
            binding_snapshot_set_id=parent.binding_snapshot_set_id,
            active_node_id=from_node_id,
            parent_run_id=parent.run_id,
            forked_from_checkpoint_id=checkpoint_id or None,
            completion_kind="revision_fork",
            terminal_reason=reason,
            blocked_problem_json=None,
            created_at_ms=now_ms,
            updated_at_ms=now_ms,
            completed_at_ms=None,
        )
        uow.repository.insert_run(child)

        node_run_id = f"nr-{child_run_id}-{from_node_id}-a1"
        child_attempt = _node_attempt_for_dispatch(
            node_run_id=node_run_id,
            run_id=child_run_id,
            node_id=from_node_id,
            attempt=1,
            binding_snapshot_id=None,
        )
        uow.repository.insert_attempt(
            _attempt_record(
                node_run_id=node_run_id,
                run_id=child_run_id,
                node_id=from_node_id,
                attempt=1,
                status=NodeAttemptStatus.STARTING.value,
                command_id=command_id,
                input_snapshot_hash=parent.input_snapshot_hash,
                started_at_ms=now_ms,
            )
        )
        uow.repository.insert_outbox(
            _graph_dispatch_record(
                uow=uow,
                run=child,
                attempt=child_attempt,
                command_id=command_id,
                now_ms=now_ms,
            )
        )
        return child_run_id


def _bump(uow, request: CommandRequest, *, event_count: int, now_ms: int) -> tuple[int, int]:
    bumped = uow.repository.bump_run_version(
        request.run_id,
        request.team_id,
        request.expected_run_version,
        event_count,
        now_ms,
    )
    if bumped is None:
        raise RunVersionConflictError()
    return bumped


def _command_record(
    *,
    command_id: str,
    request: CommandRequest,
    request_hash: str,
    accepted_run_version: int,
    now_ms: int,
) -> Any:
    from core.research.workflow.ledger import CommandRecord

    return CommandRecord(
        command_id=command_id,
        run_id=request.run_id,
        team_id=request.team_id,
        node_id=request.node_id,
        command_kind=request.command.value,
        expected_run_version=request.expected_run_version,
        accepted_run_version=accepted_run_version,
        idempotency_key=request.idempotency_key,
        request_hash=request_hash,
        request_json=json.dumps(
            {
                "teamId": request.team_id,
                "runId": request.run_id,
                "nodeId": request.node_id,
                "command": request.command.value,
                "expectedRunVersion": request.expected_run_version,
                "idempotencyKey": request.idempotency_key,
                "payload": dict(request.payload),
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        requested_by_json=json.dumps(request.requested_by.to_dict()),
        status="accepted",
        result_json=None,
        problem_json=None,
        created_at_ms=now_ms,
        completed_at_ms=None,
    )


def _attempt_record(
    *,
    node_run_id: str,
    run_id: str,
    node_id: str,
    attempt: int,
    status: str,
    command_id: str,
    input_snapshot_hash: str,
    started_at_ms: int,
    retry_of_node_run_id: str | None = None,
    binding_snapshot_id: str | None = None,
) -> Any:
    from core.research.workflow.ledger import NodeAttemptRecord

    return NodeAttemptRecord(
        node_run_id=node_run_id,
        run_id=run_id,
        node_id=node_id,
        attempt=attempt,
        actor_kind="agent",
        status=status,
        command_id=command_id,
        binding_snapshot_id=binding_snapshot_id,
        input_snapshot_hash=input_snapshot_hash,
        pending_action_id=None,
        execution_anchor_id=None,
        retry_of_node_run_id=retry_of_node_run_id,
        problem_json=None,
        started_at_ms=started_at_ms,
        updated_at_ms=started_at_ms,
        finished_at_ms=None,
    )


def _node_attempt_for_dispatch(
    *,
    node_run_id: str,
    run_id: str,
    node_id: str,
    attempt: int,
    binding_snapshot_id: str | None = None,
) -> Any:
    from core.research.workflow.ledger import NodeAttemptRecord

    return NodeAttemptRecord(
        node_run_id=node_run_id,
        run_id=run_id,
        node_id=node_id,
        attempt=attempt,
        actor_kind="agent",
        status="starting",
        command_id="",
        binding_snapshot_id=binding_snapshot_id,
        input_snapshot_hash="",
        pending_action_id=None,
        execution_anchor_id=None,
        retry_of_node_run_id=None,
        problem_json=None,
        started_at_ms=0,
        updated_at_ms=0,
        finished_at_ms=None,
    )


def _graph_dispatch_record(*, uow, run: Any, attempt: Any, command_id: str, now_ms: int) -> Any:
    from .graph_dispatch_factory import build_graph_dispatch_record

    return build_graph_dispatch_record(
        run=run,
        attempt=attempt,
        command_id=command_id,
        dispatch_kind="start",
        now_ms=now_ms,
    )


def _binding_snapshot_id(uow, run_id: str, node_id: str) -> str | None:
    from .graph_dispatch_factory import binding_snapshot_id_for_node

    run = uow.repository.get_run(run_id)
    if run is None or not run.input_snapshot_json:
        return None
    import json

    try:
        input_snapshot = json.loads(run.input_snapshot_json)
    except (TypeError, ValueError):
        return None
    return binding_snapshot_id_for_node(input_snapshot, node_id)


def _event_record(
    *,
    run_id: str,
    sequence: int,
    event_id: str,
    run_version: int,
    event_type: str,
    correlation_id: str,
    payload: dict[str, Any],
    now_ms: int,
) -> Any:
    from core.research.workflow.ledger import EventRecord

    return EventRecord(
        run_id=run_id,
        sequence=sequence,
        event_id=event_id,
        run_version=run_version,
        event_type=event_type,
        actor_json=json.dumps({"actorType": "system", "actorId": "workflow-command-service"}),
        correlation_id=correlation_id,
        causation_id=None,
        payload_json=json.dumps(payload, ensure_ascii=False),
        occurred_at_ms=now_ms,
    )


def _receipt(
    uow,
    request: CommandRequest,
    command_id: str,
    accepted_version: int,
    sequence: int,
    now_ms: int,
) -> CommandReceipt:
    receipt = CommandReceipt(
        command_id=command_id,
        run_id=request.run_id,
        status="accepted",
        accepted_run_version=accepted_version,
        idempotency_key=request.idempotency_key,
        latest_event_sequence=sequence,
    )
    uow.repository.complete_command(
        command_id, "accepted", now_ms, result_json=json.dumps(receipt.to_dict())
    )
    return receipt


def _input_snapshot_hash(uow, run_id: str) -> str:
    run = uow.repository.get_run(run_id)
    return run.input_snapshot_hash if run else ""


def _human_resume_dispatch(uow, request: CommandRequest, node_run_id: str, receipt: Any, command_id: str, now_ms: int):
    from .graph_dispatch_factory import build_graph_dispatch_record

    run = uow.repository.get_run(request.run_id)
    attempt = uow.repository.get_attempt(node_run_id)
    if run is None or attempt is None:
        raise WorkflowCommandError(f"resume dispatch 缺少 run/attempt: {node_run_id}")
    return build_graph_dispatch_record(
        run=run,
        attempt=attempt,
        command_id=command_id,
        dispatch_kind="resume_human",
        now_ms=now_ms,
        receipt_payload=receipt.to_dict(),
    )
