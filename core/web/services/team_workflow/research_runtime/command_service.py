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
from collections.abc import Callable, Mapping
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

from .human_acceptance_artifact import (
    KnowledgeAcceptanceArtifactError,
    PreparedHumanAcceptanceArtifact,
    persist_prepared_human_acceptance_artifact,
    prepare_command_human_acceptance_artifact,
)
from .ids import new_id
from .reconcile_authority import plan_ledger_authority


def formal_node_order() -> tuple[str, ...]:
    """Canonical node order of the fixed formal workflow definition.

    Imported lazily through this accessor so the command service module can be
    imported without pulling the definition builder into every consumer; the
    order is the only structural fact reconcile_authority needs.
    """
    from core.research.workflow.definition import build_challenge_cup_workflow_definition

    return tuple(
        node.nodeId for node in build_challenge_cup_workflow_definition().nodes
    )

_ARTIFACT_HUMAN_GATES = frozenset(
    {
        "gate:knowledge_handoff",
        "gate:protocol_freeze",
        "gate:smoke_gate",
    }
)


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


class InvalidHumanTaskStateError(WorkflowCommandError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class HumanTaskNotFoundError(WorkflowCommandError):
    def __init__(self, task_id: str) -> None:
        super().__init__(f"human task {task_id} not found")
        self.task_id = task_id


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
        WorkflowCommandKind.ARCHIVE_RUN,
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
        coordinator_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._store = store
        self._readiness = readiness_service
        self._readiness_context = readiness_context
        self._clock = clock or (lambda: int(time.time() * 1000))
        self._wake_worker = wake_worker or (lambda: None)
        self._coordinator_factory = coordinator_factory
        self._handlers: dict[WorkflowCommandKind, Callable] = {
            WorkflowCommandKind.START_NODE: self._handle_start_node,
            WorkflowCommandKind.RETRY_NODE: self._handle_retry_node,
            WorkflowCommandKind.CANCEL_NODE: self._handle_cancel_node,
            WorkflowCommandKind.CANCEL_RUN: self._handle_cancel_run,
            WorkflowCommandKind.RESOLVE_HUMAN_TASK: self._handle_resolve_human_task,
            WorkflowCommandKind.EXTEND_BUDGET: self._handle_extend_budget,
            WorkflowCommandKind.RECONCILE_RUN: self._handle_reconcile_run,
            WorkflowCommandKind.ARCHIVE_RUN: self._handle_archive_run,
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

        # Recovery artifacts are materialized before a fresh readiness read so
        # the same visible retry command can repair an old accepted handoff and
        # immediately evaluate the successor against the canonical authority.
        try:
            prepared_artifact = prepare_command_human_acceptance_artifact(
                store=self._store,
                run=run,
                request=request,
            )
        except KnowledgeAcceptanceArtifactError as exc:
            raise WorkflowCommandError(str(exc)) from exc

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
        if request.command is WorkflowCommandKind.RESOLVE_HUMAN_TASK:
            future = self._store.submit(
                lambda uow: self._handle_resolve_human_task(
                    uow,
                    request,
                    request_hash,
                    prepared_artifact,
                ),
                force_flush=True,
            )
        elif request.command is WorkflowCommandKind.RETRY_NODE:
            future = self._store.submit(
                lambda uow: self._handle_retry_node(
                    uow,
                    request,
                    request_hash,
                    prepared_artifact,
                ),
                force_flush=True,
            )
        elif request.command is WorkflowCommandKind.RECONCILE_RUN:
            future = self._store.submit(
                lambda uow: self._handle_reconcile_run(
                    uow,
                    request,
                    request_hash,
                    prepared_artifact,
                ),
                force_flush=True,
            )
        else:
            future = self._store.submit(
                lambda uow: handler(uow, request, request_hash),
                force_flush=True,
            )
        return future.result(timeout=30)

    def _authorize_operator(self, request: CommandRequest) -> None:
        """Authorize high-impact commands from server request context only.

        Client body ``requestedBy`` must never self-declare operator authority.
        Privileged roles are required for high-impact commands.
        """
        from .operator_authorization import current_server_operator
        from .operator_permissions import (
            operator_has_privileged_role,
            require_operator_permission,
        )

        context = current_server_operator()
        if context is None or not context.operator_id:
            raise CommandForbiddenError("command_forbidden")
        # Body may carry a display actor, but a forged operator id that disagrees
        # with the server context is rejected.
        actor = request.requested_by
        body_type = str(getattr(actor, "actor_type", "") or "").lower()
        body_id = str(getattr(actor, "actor_id", "") or "").strip()
        if body_type in {"operator", "user"} and body_id and body_id != context.operator_id:
            raise CommandForbiddenError("command_forbidden")
        try:
            require_operator_permission(
                operator_id=context.operator_id,
                roles=context.roles,
                command=request.command.value,
            )
        except PermissionError as exc:
            raise CommandForbiddenError("command_forbidden") from exc
        if (
            request.command is WorkflowCommandKind.ARCHIVE_RUN
            and not operator_has_privileged_role(context.roles)
        ):
            raise CommandForbiddenError("command_forbidden")

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

    def _handle_retry_node(
        self,
        uow,
        request: CommandRequest,
        request_hash: str,
        prepared_artifact: PreparedHumanAcceptanceArtifact | None = None,
    ) -> CommandReceipt:
        from .command_offers.retry_node import succeeded_node_rerun_available

        node_id = request.node_id
        latest = uow.repository.latest_attempt(request.run_id, node_id)
        if latest is None:
            raise CommandNotAllowedError("该节点没有可重试的 attempt")
        run = uow.repository.get_run(request.run_id)
        if run is None:
            raise RunNotFoundError(request.run_id)
        if latest.status not in (
            NodeAttemptStatus.FAILED.value,
            NodeAttemptStatus.BLOCKED.value,
            NodeAttemptStatus.CANCELLED.value,
        ) and not succeeded_node_rerun_available(
            node_id=node_id, latest=latest, run=run
        ):
            raise CommandNotAllowedError(f"attempt {latest.status} 不可重试")
        persist_prepared_human_acceptance_artifact(
            uow,
            run=run,
            prepared=prepared_artifact,
            now_ms=self._clock(),
        )
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
        self,
        uow,
        request: CommandRequest,
        request_hash: str,
        prepared_artifact: PreparedHumanAcceptanceArtifact | None = None,
    ) -> CommandReceipt:
        task_id = str(request.payload.get("taskId") or "")
        decision = str(request.payload.get("decision") or "")
        if not task_id or decision not in ("accept", "reject", "revise"):
            raise WorkflowCommandError("resolve_human_task 需要 taskId 和 decision(accept/reject/revise)")
        row = uow.repository.get_human_task(task_id)
        if row is None:
            raise HumanTaskNotFoundError(task_id)
        if str(row[1]) != request.run_id:
            raise TeamScopeMismatchError("human task 不属于该 run")
        now_ms = self._clock()
        target = {
            "accept": HumanTaskStatus.ACCEPTED.value,
            "reject": HumanTaskStatus.REJECTED.value,
            "revise": HumanTaskStatus.REVISED.value,
        }[decision]
        current_status = HumanTaskStatus(str(row[6] or HumanTaskStatus.PENDING.value))
        if current_status is not HumanTaskStatus.PENDING:
            raise InvalidHumanTaskStateError(
                f"human task {task_id} 已处于 {current_status.value} 状态，不能重复决策"
            )
        require_human_task_transition(current_status, HumanTaskStatus(target))
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
        if not uow.repository.update_human_task_decision(
            task_id, target, now_ms, decision_json=decision_json
        ):
            # 守卫 UPDATE（WHERE status='pending'）未命中：并发下任务已被解决。
            raise InvalidHumanTaskStateError(
                f"human task {task_id} 已被并发决策，本次决策未生效"
            )
        # 人工决策后通过正式 graph resume 推进（T5 契约：Human 节点可恢复）。
        attempt = uow.repository.get_attempt(str(row[2]))
        pending_action_id = attempt.pending_action_id if attempt else None
        task_kind = str(row[4] or "")
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
        else:
            from core.research.workflow.contracts import ExecutionReceipt

            run = uow.repository.get_run(request.run_id)
            if run is None:
                raise RunNotFoundError(request.run_id)
            artifact_receipt_ids = persist_prepared_human_acceptance_artifact(
                uow,
                run=run,
                prepared=prepared_artifact,
                now_ms=now_ms,
            )
            if (
                decision == "accept"
                and task_kind in _ARTIFACT_HUMAN_GATES
                and not artifact_receipt_ids
            ):
                raise WorkflowCommandError(
                    f"{task_kind} accept requires a materialized artifact receipt"
                )
            if pending_action_id:
                receipt = ExecutionReceipt(
                    action_id=pending_action_id,
                    node_run_id=str(row[2]),
                    outcome="succeeded" if decision == "accept" else "failed",
                    artifact_receipt_ids=artifact_receipt_ids,
                    execution_anchor_id=None,
                    budget_receipt_id=None,
                    problem=None,
                    completed_at_ms=now_ms,
                )
                uow.repository.insert_outbox(
                    _human_resume_dispatch(
                        uow, request, str(row[2]), receipt, command_id, now_ms
                    )
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

    def _handle_reconcile_run(
        self,
        uow,
        request: CommandRequest,
        request_hash: str,
        prepared_artifact: PreparedHumanAcceptanceArtifact | None = None,
    ) -> CommandReceipt:
        now_ms = self._clock()
        run = uow.repository.get_run(request.run_id)
        attempts = uow.repository.list_attempts(request.run_id)
        # Reconciliation resets the run projection to ledger authority BEFORE
        # any dispatch is revived. Incident blocked attempts covered by an
        # earlier successful advance (operator-misassigned retries whose
        # nodeId conflicts with the chain frontier) would otherwise pin
        # active_node_id and re-derive the same failing dispatch forever.
        plan = plan_ledger_authority(attempts, node_order=formal_node_order())
        target_status = (
            RunStatus.BLOCKED if plan.lands_blocked else RunStatus.RUNNING
        )
        require_run_transition(RunStatus(run.status), target_status)
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
        artifact_receipt_ids = persist_prepared_human_acceptance_artifact(
            uow,
            run=run,
            prepared=prepared_artifact,
            now_ms=now_ms,
        )
        for node_run_id in plan.superseded_node_run_ids:
            uow.repository.update_attempt_status(
                node_run_id,
                NodeAttemptStatus.STALE.value,
                now_ms,
                finished_at_ms=now_ms,
            )
            uow.repository.execute(
                """
                UPDATE outbox_actions
                SET status = 'cancelled',
                    lease_owner = NULL,
                    lease_expires_at_ms = NULL,
                    updated_at_ms = ?
                WHERE node_run_id = ?
                  AND action_kind = 'graph_dispatch'
                  AND status IN ('failed', 'pending', 'leased')
                """,
                (now_ms, node_run_id),
            )
        if plan.lands_blocked:
            # The landing verdict is copied verbatim from the deepest readiness
            # verdict the pipeline itself wrote beyond every success —
            # reconcile only re-projects ledger truth onto the run record,
            # never hand-authors a state. The V2 rerun mapping keys off
            # exactly this projection (blocked + auto_advance_not_ready).
            uow.repository.update_run_status(
                request.run_id,
                request.team_id,
                RunStatus.BLOCKED.value,
                now_ms,
                active_node_id=str(plan.active_node_id or ""),
                blocked_problem_json=json.dumps(
                    dict(plan.landing_problem), ensure_ascii=False
                ),
            )
        else:
            uow.repository.update_run_status(
                request.run_id, request.team_id, RunStatus.RUNNING.value, now_ms
            )
        # Reconciliation re-derives execution from the durable ledger.  A
        # blocked run usually got there via a terminal-failed graph_dispatch
        # (e.g. checkpoint_node_mismatch); reviving only the run status would
        # strand it as running with nothing left to advance, until the sweep
        # flips it back to reconciliation_required.  Give the worker a fresh
        # routing decision by re-arming failed dispatch rows in this same
        # transaction (same repair shape as _repair_starting_without_progress);
        # live or deliberately cancelled rows stay untouched. Rows whose node's
        # latest attempt holds a readiness-pipeline verdict stay dead: replay
        # them would deterministically re-fail and overwrite that verdict,
        # which both the landing above and the V2 rerun mapping depend on.
        uow.repository.execute(
            """
            UPDATE outbox_actions
            SET status = 'pending',
                lease_owner = NULL,
                lease_expires_at_ms = NULL,
                available_at_ms = ?,
                attempt_count = 0,
                last_problem_json = NULL,
                updated_at_ms = ?
            WHERE run_id = ?
              AND action_kind = 'graph_dispatch'
              AND status = 'failed'
              AND NOT EXISTS (
                SELECT 1 FROM node_attempts na
                WHERE na.node_run_id = outbox_actions.node_run_id
                  AND na.status = 'blocked'
                  AND INSTR(na.problem_json, 'auto_advance_not_ready') > 0
              )
            """,
            (now_ms, now_ms, request.run_id),
        )
        revived = int(uow.repository.affected() or 0)
        uow.repository.insert_event(
            _event_record(
                run_id=request.run_id,
                sequence=sequence,
                event_id=new_id("evt"),
                run_version=accepted_version,
                event_type="run_blocked",
                correlation_id=request.idempotency_key,
                payload={
                    "reconciled": True,
                    "revivedDispatchCount": revived,
                    "artifactReceiptIds": list(artifact_receipt_ids),
                    "staleAttemptIds": list(plan.superseded_node_run_ids),
                    "recomputedActiveNodeId": plan.active_node_id,
                    "landingProblemCode": (
                        str(plan.landing_problem.get("code") or "")
                        if plan.landing_problem
                        else None
                    ),
                    "landingProblemDetail": (
                        str(plan.landing_problem.get("detail") or "")
                        if plan.landing_problem
                        else None
                    ),
                },
                now_ms=now_ms,
            )
        )
        if revived > 0:
            uow.after_commit(self._wake_worker)
        return _receipt(uow, request, command_id, accepted_version, sequence, now_ms)

    def _handle_archive_run(
        self, uow, request: CommandRequest, request_hash: str
    ) -> CommandReceipt:
        """Archive a terminal run without reviving its execution state."""

        now_ms = self._clock()
        run = uow.repository.get_run(request.run_id)
        if run is None:
            raise RunNotFoundError(request.run_id)
        try:
            current = RunStatus(run.status)
        except ValueError as exc:
            raise WorkflowCommandError("archive_run 的当前 run 状态无效") from exc
        if current not in {
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.RECONCILIATION_REQUIRED,
        }:
            raise WorkflowCommandError(
                f"archive_run 不能归档 {current.value} 状态的 run"
            )
        require_run_transition(current, RunStatus.ARCHIVED)
        reason = str(request.payload.get("reason") or "operator archived").strip()
        if not reason:
            reason = "operator archived"

        cancelled_outbox_count = 0
        for attempt in uow.repository.list_attempts(request.run_id):
            cancelled_outbox_count += uow.repository.cancel_outbox_by_node_run(
                attempt.node_run_id, now_ms
            )

        command_id = new_id("cmd")
        accepted_version, sequence = _bump(
            uow, request, event_count=1, now_ms=now_ms
        )
        uow.repository.insert_command(
            _command_record(
                command_id=command_id,
                request=request,
                request_hash=request_hash,
                accepted_run_version=accepted_version,
                now_ms=now_ms,
            )
        )
        if not uow.repository.update_run_status(
            request.run_id,
            request.team_id,
            RunStatus.ARCHIVED.value,
            now_ms,
            completion_kind=run.completion_kind,
            terminal_reason=run.terminal_reason,
            blocked_problem_json=run.blocked_problem_json,
        ):
            raise WorkflowCommandError("archive_run 未能更新目标 run")
        uow.repository.insert_event(
            _event_record(
                run_id=request.run_id,
                sequence=sequence,
                event_id=new_id("evt"),
                run_version=accepted_version,
                event_type="run_archived",
                correlation_id=request.idempotency_key,
                payload={
                    "commandId": command_id,
                    "archivedFromStatus": current.value,
                    "terminalReason": run.terminal_reason,
                    "previousCompletedAtMs": run.completed_at_ms,
                    "archiveReason": reason,
                    "reason": reason,
                    "cancelledOutboxCount": cancelled_outbox_count,
                    "requestedBy": request.requested_by.to_dict(),
                },
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
        if parent.status in ("failed", "cancelled", "archived"):
            raise WorkflowCommandError("failed/cancelled/archived run 不能 fork revision")
        if parent.status == "succeeded":
            self._assert_post_approval_revision_authorized(parent, request.payload)

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

    @staticmethod
    def _assert_post_approval_revision_authorized(
        parent: Any,
        payload: Mapping[str, Any],
    ) -> None:
        """Authorize a terminal-run fork from durable Challenge review state.

        ``postApprovalRevision`` is only a declaration used by the internal V2
        adapter; it is never authority because the legacy formal command route
        can carry arbitrary payload fields.  The registered output and its
        H1-H4 decisions are the server-owned authorization source.
        """

        output_record_id = str(payload.get("outputRecordId") or "").strip()
        if payload.get("postApprovalRevision") is not True or not output_record_id:
            raise WorkflowCommandError(
                "succeeded run 只能通过正式审核修订入口 fork revision"
            )
        from core.web.services.team_workflow.challenge_question_runs import (
            get_challenge_question_run_detail,
        )

        try:
            detail = get_challenge_question_run_detail(
                str(parent.team_id or ""),
                str(parent.question_id or ""),
                run_id=str(parent.run_id or ""),
            )
        except (TypeError, ValueError) as exc:
            raise WorkflowCommandError(
                "正式审核修订授权记录不可用"
            ) from exc
        record = detail.get("record") if isinstance(detail, Mapping) else None
        record = record if isinstance(record, Mapping) else {}
        gates = record.get("humanGates")
        gates = gates if isinstance(gates, Mapping) else {}
        decisions = gates.get("decisions")
        decisions = decisions if isinstance(decisions, Mapping) else {}
        authorized = (
            str(record.get("recordId") or "") == output_record_id
            and str(record.get("questionId") or "").strip().upper()
            == str(parent.question_id or "").strip().upper()
            and str(record.get("runId") or "") == str(parent.run_id or "")
            and str(record.get("status") or "") == "needs_revision"
            and any(
                str(decision or "") == "revision_requested"
                for decision in decisions.values()
            )
        )
        if not authorized:
            raise WorkflowCommandError(
                "正式审核未授权当前 succeeded run 创建修订"
            )

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
        child_thread_id = child_run_id  # threadId == runId (ADR / spec 7.3)
        if not str(checkpoint_id or "").strip():
            raise WorkflowCommandError("fork_revision 需要 checkpointId")
        input_snapshot: dict[str, Any] = {}
        if parent.input_snapshot_json:
            try:
                loaded_snapshot = json.loads(parent.input_snapshot_json)
            except (TypeError, ValueError) as exc:
                raise WorkflowCommandError(
                    "父 run input snapshot 不可解析，已阻断修订分支创建: "
                    f"parentRunId={parent.run_id} error={exc}"
                ) from exc
            if not isinstance(loaded_snapshot, dict):
                raise WorkflowCommandError(
                    "父 run input snapshot 不是对象，已阻断修订分支创建: "
                    f"parentRunId={parent.run_id}"
                )
            input_snapshot = loaded_snapshot
        input_snapshot = dict(input_snapshot)
        input_snapshot["parentRunId"] = parent.run_id
        input_snapshot["forkedFromCheckpointId"] = checkpoint_id
        input_snapshot["forkCorrelationId"] = command_id

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
            forked_from_checkpoint_id=checkpoint_id,
            completion_kind="revision_fork",
            terminal_reason=reason,
            blocked_problem_json=None,
            created_at_ms=now_ms,
            updated_at_ms=now_ms,
            completed_at_ms=None,
            structure_hash=parent.structure_hash,
        )
        uow.repository.insert_run(child)

        node_run_id = f"nr-{child_run_id}-{from_node_id}-a1"
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
        # Durable checkpoint fork outbox — child graph_dispatch is inserted only
        # after CheckpointForkWorker succeeds (crash-safe; no after_commit/daemon).
        uow.repository.insert_outbox(
            _checkpoint_fork_record(
                run_id=child_run_id,
                command_id=command_id,
                node_run_id=node_run_id,
                parent_run_id=parent.run_id,
                checkpoint_id=checkpoint_id,
                resume_node_id=from_node_id,
                now_ms=now_ms,
            )
        )
        return child_run_id


def _checkpoint_fork_record(
    *,
    run_id: str,
    command_id: str,
    node_run_id: str,
    parent_run_id: str,
    checkpoint_id: str,
    resume_node_id: str,
    now_ms: int,
) -> Any:
    from core.research.workflow.ledger import OutboxRecord

    from .ids import new_id

    payload = {
        "parentRunId": parent_run_id,
        "checkpointId": checkpoint_id,
        "childRunId": run_id,
        "resumeNodeId": resume_node_id,
        "commandId": command_id,
        "nodeRunId": node_run_id,
    }
    return OutboxRecord(
        action_id=new_id("act"),
        run_id=run_id,
        command_id=command_id,
        node_run_id=node_run_id,
        action_kind="checkpoint_fork",
        idempotency_key=f"checkpoint_fork:{run_id}:{checkpoint_id}",
        payload_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        status="pending",
        attempt_count=0,
        available_at_ms=now_ms,
        lease_owner=None,
        lease_expires_at_ms=None,
        last_problem_json=None,
        created_at_ms=now_ms,
        updated_at_ms=now_ms,
    )


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


def _actor_kind_for_node(node_id: str) -> str:
    from core.research.workflow.definition import (
        build_challenge_cup_workflow_definition,
    )

    for node in build_challenge_cup_workflow_definition().nodes:
        if node.nodeId == node_id:
            return node.actorKind.value
    raise WorkflowCommandError(f"unknown node {node_id}")


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
    actor_kind: str | None = None,
) -> Any:
    from core.research.workflow.ledger import NodeAttemptRecord

    return NodeAttemptRecord(
        node_run_id=node_run_id,
        run_id=run_id,
        node_id=node_id,
        attempt=attempt,
        actor_kind=actor_kind or _actor_kind_for_node(node_id),
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
        actor_kind=_actor_kind_for_node(node_id),
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
