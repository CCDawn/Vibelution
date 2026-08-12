"""Graph dispatch worker — drives the formal LangGraph coordinator from the
transactional outbox (spec 7.3 steps 2-4).

- leases graph_dispatch actions atomically;
- re-dispatching after a crash resumes from the checkpoint and re-derives the
  same actionId; the adapter_dispatch outbox keyed by adapter:{actionId} is
  unique so recovery never duplicates work;
- every outcome lands in one Ledger transaction (ack + attempt transition +
  adapter_dispatch outbox + events); no external side effects in the tx.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from core.research.workflow.challenge_cup_runtime import (
    ChallengeCupGraphCoordinator,
    GraphDispatch,
    GraphDispatchResult,
    build_pending_action,
    successor_map,
)
from core.research.workflow.ledger import WorkflowLedgerStore, outbox as outbox_api
from core.research.workflow.transitions import NodeAttemptStatus

from .ids import new_id


class GraphDecisionError(RuntimeError):
    """An iteration decision the graph cannot route (run must block)."""


class GraphDispatchWorker:
    def __init__(
        self,
        *,
        store: WorkflowLedgerStore,
        coordinator: ChallengeCupGraphCoordinator,
        owner_id: str = "graph-worker",
        lease_ms: int = 30_000,
        now_provider: Callable[[], int] | None = None,
        readiness_service: Any | None = None,
        readiness_context: Callable[[], Any] | None = None,
    ) -> None:
        self._store = store
        self._coordinator = coordinator
        self._owner = owner_id
        self._lease_ms = lease_ms
        self._now = now_provider or (lambda: int(time.time() * 1000))
        self._readiness = readiness_service
        self._readiness_context = readiness_context

    def run_once(self, limit: int = 8) -> int:
        leased = outbox_api.lease_ready_actions(
            self._store,
            owner=self._owner,
            now_ms=self._now(),
            limit=limit,
            lease_ms=self._lease_ms,
            action_kinds=("graph_dispatch",),
        )
        for action in leased:
            self._handle(action)
        return len(leased)

    def _handle(self, action: Any) -> None:
        payload = json.loads(action.payload_json)
        dispatch = GraphDispatch.from_payload(payload)
        if (
            dispatch.dispatch_kind in ("resume_action", "resume_human")
            and dispatch.receipt is not None
            and dispatch.receipt.outcome != "succeeded"
        ):
            # 失败/阻塞/取消：不 resume 图（线程停留在中断点，保证
            # checkpoint 与 Ledger 不漂移），只标记 attempt 状态。
            self._mark_attempt_outcome(action, dispatch)
            return

        # Crash recovery: upstream attempt/handoff already committed, but successor
        # attempt was not created. Do not re-invoke LangGraph resume.
        if self._recover_half_advanced_successor(action, dispatch):
            return

        try:
            if dispatch.dispatch_kind == "start":
                result = self._start_or_recover(dispatch)
            else:
                result = self._resume(dispatch)
        except GraphDecisionError as exc:
            self._mark_blocked(action, dispatch, str(exc))
            return
        except Exception as exc:
            self._requeue_or_fail(action, str(exc))
            return

        # T5.1-4: commit upstream success + Handoff accepted FIRST so successor
        # readiness observes accepted handoffs. Domain readiness stays outside
        # the writer transaction.
        pending = result.pending_action
        needs_successor = False
        if pending is not None:
            latest = self._store.latest_attempt(dispatch.run_id, pending.node_id)
            needs_successor = latest is None or latest.attempt != pending.attempt
            pending = self._pending_with_node_binding(pending)

        if (
            dispatch.dispatch_kind in ("resume_action", "resume_human")
            and dispatch.receipt is not None
            and dispatch.receipt.outcome == "succeeded"
            and needs_successor
        ):
            self._commit_upstream_accept(action, dispatch, result)
            readiness_hint = self._precheck_readiness(dispatch, pending)
            try:
                self._commit_successor_dispatch(
                    dispatch, result, pending, readiness_hint, action=action
                )
            except Exception as exc:
                self._requeue_or_fail(action, f"successor_commit_failed:{exc}")
                raise
            return

        readiness_hint = None
        if pending is not None and needs_successor:
            readiness_hint = self._precheck_readiness(dispatch, pending)
        if pending is not None and pending is not result.pending_action:
            from dataclasses import replace as _replace

            result = _replace(result, pending_action=pending)
        self._commit_dispatch(action, dispatch, result, readiness_hint)

    def _recover_half_advanced_successor(self, action: Any, dispatch: GraphDispatch) -> bool:
        """Return True when this action finished recovery without re-resume."""
        if dispatch.dispatch_kind not in ("resume_action", "resume_human"):
            return False
        if dispatch.receipt is None or dispatch.receipt.outcome != "succeeded":
            return False
        attempt = self._store.submit(
            lambda uow: uow.repository.get_attempt(dispatch.node_run_id),
            force_flush=True,
        ).result(timeout=10)
        if attempt is None or attempt.status != NodeAttemptStatus.SUCCEEDED.value:
            return False
        handoff = self._store.submit(
            lambda uow: uow.repository.get_handoff_by_from_node(
                dispatch.run_id, dispatch.node_run_id
            ),
            force_flush=True,
        ).result(timeout=10)
        if handoff is None or str(handoff[8]) != "accepted":
            return False
        successors = successor_map().get(dispatch.node_id, ())
        if not successors:
            # Terminal: just ack the outbox.
            now_ms = self._now()

            def ack_only(uow):
                uow.repository.ack_outbox(action.action_id, self._owner, now_ms)

            self._store.submit(ack_only, force_flush=True).result(timeout=30)
            return True
        successor_id = successors[0]
        latest = self._store.latest_attempt(dispatch.run_id, successor_id)
        if latest is not None:
            # Successor already present — ack and stop.
            now_ms = self._now()

            def ack_only(uow):
                uow.repository.ack_outbox(action.action_id, self._owner, now_ms)

            self._store.submit(ack_only, force_flush=True).result(timeout=30)
            return True

        snapshot = self._coordinator.snapshot(dispatch.run_id)
        values = dict(snapshot.get("values") or {})
        values.setdefault("run_id", dispatch.run_id)
        values.setdefault("input_snapshot_hash", dispatch.input_snapshot_hash)
        values.setdefault("budget_policy_hash", dispatch.budget_policy_hash)
        pending = self._pending_with_node_binding(
            build_pending_action(values, successor_id)
        )
        readiness_hint = self._precheck_readiness(dispatch, pending)
        result = GraphDispatchResult(
            dispatch_kind=dispatch.dispatch_kind,
            pending_action=pending,
            next_node_ids=(successor_id,),
            checkpoint_id=str(snapshot.get("checkpointId") or ""),
            state=values,
        )
        try:
            self._commit_successor_dispatch(
                dispatch, result, pending, readiness_hint, action=action
            )
        except Exception as exc:
            self._requeue_or_fail(action, f"successor_commit_failed:{exc}")
            raise
        return True

    def _pending_with_node_binding(self, pending: Any) -> Any:
        """Force successor PendingAction to use that node's frozen binding."""
        from dataclasses import replace

        from .graph_dispatch_factory import binding_snapshot_id_for_node

        run = self._store.get_run(pending.run_id)
        if run is None or not run.input_snapshot_json:
            return pending
        try:
            input_snapshot = json.loads(run.input_snapshot_json)
        except (TypeError, ValueError):
            return pending
        if not isinstance(input_snapshot, dict):
            return pending
        snap_id = binding_snapshot_id_for_node(input_snapshot, pending.node_id)
        if snap_id == pending.binding_snapshot_id:
            return pending
        return replace(pending, binding_snapshot_id=snap_id)

    def _commit_upstream_accept(
        self,
        action: Any,
        dispatch: GraphDispatch,
        result: GraphDispatchResult,
    ) -> None:
        """Mark attempt succeeded and accept handoff BEFORE successor readiness.

        Intentionally does NOT ack the graph outbox yet: if successor commit
        crashes, lease expiry / requeue can recover without a half-advance.
        """
        _ = (action, result)
        now_ms = self._now()

        def mutate(uow):
            attempt = uow.repository.get_attempt(dispatch.node_run_id)
            if (
                attempt is not None
                and str(attempt.status) != NodeAttemptStatus.SUCCEEDED.value
            ):
                uow.repository.update_attempt_status(
                    dispatch.node_run_id,
                    NodeAttemptStatus.SUCCEEDED.value,
                    now_ms,
                    finished_at_ms=now_ms,
                )
            handoff = uow.repository.get_handoff_by_from_node(
                dispatch.run_id, dispatch.node_run_id
            )
            if handoff is None:
                return
            status = str(handoff[8] or "")
            if status == "accepted":
                return
            if status == "pending":
                uow.repository.update_handoff_status(handoff[0], "ready", now_ms)
                status = "ready"
            if status in {"ready", "waiting_human"}:
                uow.repository.update_handoff_status(
                    handoff[0],
                    "accepted",
                    now_ms,
                    accepted_by_json=json.dumps(
                        {"actorType": "system", "actorId": "graph-worker"}
                    ),
                )

        self._store.submit(mutate, force_flush=True).result(timeout=30)

    def _commit_successor_dispatch(
        self,
        dispatch: GraphDispatch,
        result: GraphDispatchResult,
        pending: Any,
        readiness_hint: tuple[bool, list[Any]] | None,
        *,
        action: Any | None = None,
    ) -> None:
        """Ack graph outbox + create successor attempt / adapter outbox."""
        now_ms = self._now()

        def mutate(uow):
            if action is not None:
                acked = uow.repository.ack_outbox(action.action_id, self._owner, now_ms)
                if not acked:
                    return
            latest = uow.repository.latest_attempt(dispatch.run_id, pending.node_id)
            if latest is not None and latest.attempt == pending.attempt:
                # Already created (crash recovery idempotent path).
                if latest.status == "dispatching":
                    try:
                        uow.repository.insert_outbox(
                            _adapter_dispatch_record(
                                pending=pending,
                                run_id=dispatch.run_id,
                                command_id=(
                                    action.command_id
                                    if action is not None
                                    else dispatch.command_id
                                ),
                                now_ms=now_ms,
                            )
                        )
                    except Exception:
                        pass
                return
            if readiness_hint is None:
                ready, blockers = True, []
            else:
                ready, blockers = readiness_hint
            command_id = (
                (action.command_id if action is not None else None)
                or dispatch.command_id
                or "cmd-recovery"
            )
            if not ready:
                uow.repository.insert_attempt(
                    _attempt_for_pending(
                        pending,
                        command_id=command_id,
                        now_ms=now_ms,
                        status="blocked",
                        problem_json=json.dumps(
                            {
                                "code": "auto_advance_not_ready",
                                "detail": "; ".join(
                                    str(b.get("code") or b) for b in blockers
                                ),
                            },
                            ensure_ascii=False,
                        ),
                    )
                )
                blocked_sequence = uow.repository.advance_last_sequence(
                    dispatch.run_id, 1, now_ms
                )
                if blocked_sequence is not None:
                    blocked_run = uow.repository.get_run(dispatch.run_id)
                    blocked_run_version = blocked_run.run_version if blocked_run else 1
                    uow.repository.insert_event(
                        _event_record_for(
                            run_id=dispatch.run_id,
                            sequence=blocked_sequence,
                            run_version=blocked_run_version,
                            event_id=new_id("evt"),
                            event_type="node_blocked",
                            correlation_id=pending.action_id,
                            payload={
                                "nodeRunId": pending.node_run_id,
                                "nodeId": pending.node_id,
                                "autoAdvanceBlocked": True,
                                "blockers": [
                                    str(b.get("code") or b) for b in blockers
                                ],
                            },
                            now_ms=now_ms,
                        )
                    )
                return
            uow.repository.insert_attempt(
                _attempt_for_pending(
                    pending,
                    command_id=command_id,
                    now_ms=now_ms,
                )
            )
            try:
                uow.repository.insert_outbox(
                    _adapter_dispatch_record(
                        pending=pending,
                        run_id=dispatch.run_id,
                        command_id=command_id,
                        now_ms=now_ms,
                    )
                )
            except Exception:
                pass
            _ = result

        self._store.submit(mutate, force_flush=True).result(timeout=30)

    def _precheck_readiness(self, dispatch: GraphDispatch, pending: Any):
        """Evaluate readiness for an auto-advanced successor OUTSIDE the writer
        transaction (domain context reads the ledger through the writer queue,
        so it must not run inside a writer-thread mutate). Returns
        (ready, blockers) or None when readiness is not wired."""
        if self._readiness is None or self._readiness_context is None:
            return None
        team_id = dispatch.team_id
        if not team_id:
            run = self._store.get_run(dispatch.run_id)
            team_id = run.team_id if run else dispatch.run_id
        try:
            readiness = self._readiness.evaluate(
                team_id=team_id,
                run_id=dispatch.run_id,
                node_id=pending.node_id,
                context=self._readiness_context(),
                use_cache=False,
            )
        except Exception as exc:
            return (False, [{"code": "readiness_unavailable", "detail": str(exc)}])
        blockers = [b.to_dict() for b in readiness.blockers]
        return (bool(readiness.ready), blockers)

    def _mark_attempt_outcome(self, action: Any, dispatch: GraphDispatch) -> None:
        now_ms = self._now()
        outcome = dispatch.receipt.outcome if dispatch.receipt else "failed"
        target_status = {
            "failed": NodeAttemptStatus.FAILED.value,
            "blocked": NodeAttemptStatus.BLOCKED.value,
            "cancelled": NodeAttemptStatus.CANCELLED.value,
        }.get(outcome, NodeAttemptStatus.FAILED.value)

        def mutate(uow):
            uow.repository.ack_outbox(action.action_id, self._owner, now_ms)
            uow.repository.update_attempt_status(
                dispatch.node_run_id,
                target_status,
                now_ms,
                finished_at_ms=now_ms,
            )
            # attempt 已终态：其待执行的 adapter_dispatch 不得再运行
            # （retry 会以新 attempt 重新发起，旧的 adapter 任务必须取消）。
            uow.repository.cancel_outbox_by_node_run(dispatch.node_run_id, now_ms)

        self._store.submit(mutate, force_flush=True).result(timeout=30)

    def _start_or_recover(self, dispatch: GraphDispatch) -> GraphDispatchResult:
        snapshot = self._coordinator.snapshot(dispatch.run_id)
        values = snapshot.get("values") or {}
        node_id = str(values.get("active_node_id") or "")
        next_node_ids = snapshot.get("nextNodeIds") or []
        if not next_node_ids:
            if dispatch.attempt >= 2:
                # 线程已完成（失败结束）：以新 attempt 重入节点。
                return self._coordinator.retry_attempt(dispatch)
            return self._coordinator.start_attempt(dispatch)
        state_attempt = int(values.get("active_attempt") or 1)
        if node_id == dispatch.node_id and state_attempt == dispatch.attempt:
            # 线程已在该节点的中断点：崩溃恢复，重派生同一 actionId；
            # adapter_dispatch 的幂等键保证不会重复建任务。
            pending = build_pending_action(values, node_id)
            return GraphDispatchResult(
                dispatch_kind="start",
                pending_action=pending,
                next_node_ids=tuple(str(item) for item in next_node_ids),
                checkpoint_id=str(snapshot.get("checkpointId") or ""),
                state=values,
            )
        if node_id == dispatch.node_id:
            # retry：以新 attempt 重启节点，产生新的 actionId。
            return self._coordinator.restart_attempt(dispatch)
        raise GraphDecisionError(
            f"thread 中断于 {node_id}，但 dispatch 目标是 {dispatch.node_id}"
        )

    def _resume(self, dispatch: GraphDispatch) -> GraphDispatchResult:
        if dispatch.receipt is None:
            raise ValueError("resume dispatch requires an ExecutionReceipt")
        if dispatch.state_update:
            from dataclasses import replace

            # 为可能的后继节点注入 Ledger 权威的 attempt（rerun 需要 attempt+1）。
            successors = successor_map().get(dispatch.node_id, ())
            node_attempts: dict[str, int] = {}
            for successor in successors:
                latest = self._store.latest_attempt(dispatch.run_id, successor)
                node_attempts[successor] = (latest.attempt + 1) if latest else 1
            if node_attempts:
                merged = dict(dispatch.state_update)
                merged["node_attempts"] = node_attempts
                dispatch = replace(dispatch, state_update=merged)
        try:
            if dispatch.dispatch_kind == "resume_human":
                return self._coordinator.resume_human(dispatch)
            return self._coordinator.resume_action(dispatch)
        except ValueError as exc:
            message = str(exc)
            if "unknown iteration decision" in message or "unknown governed decision" in message:
                raise GraphDecisionError(message) from exc
            raise

    def _commit_dispatch(
        self,
        action: Any,
        dispatch: GraphDispatch,
        result: GraphDispatchResult,
        readiness_hint: tuple[bool, list[Any]] | None = None,
    ) -> None:
        now_ms = self._now()

        def mutate(uow):
            acked = uow.repository.ack_outbox(action.action_id, self._owner, now_ms)
            if not acked:
                return
            if (
                dispatch.dispatch_kind in ("resume_action", "resume_human")
                and dispatch.receipt is not None
                and dispatch.receipt.outcome == "succeeded"
            ):
                # resume 成功：当前 attempt 完成，人工门 Handoff accepted。
                uow.repository.update_attempt_status(
                    dispatch.node_run_id,
                    NodeAttemptStatus.SUCCEEDED.value,
                    now_ms,
                    finished_at_ms=now_ms,
                )
                handoff = uow.repository.get_handoff_by_from_node(
                    dispatch.run_id, dispatch.node_run_id
                )
                if handoff is not None:
                    uow.repository.update_handoff_status(
                        handoff[0],
                        "accepted",
                        now_ms,
                        accepted_by_json=json.dumps(
                            {"actorType": "system", "actorId": "graph-worker"}
                        ),
                    )
            if result.pending_action:
                pending = result.pending_action
                latest = uow.repository.latest_attempt(dispatch.run_id, pending.node_id)
                if latest is not None and latest.attempt == pending.attempt:
                    # 同一节点中断点恢复（命令层已通过 readiness）：直接 dispatching。
                    uow.repository.update_attempt_status(
                        latest.node_run_id,
                        NodeAttemptStatus.DISPATCHING.value,
                        now_ms,
                        pending_action_id=pending.action_id,
                    )
                    try:
                        uow.repository.insert_outbox(
                            _adapter_dispatch_record(
                                pending=pending,
                                run_id=dispatch.run_id,
                                command_id=action.command_id,
                                now_ms=now_ms,
                            )
                        )
                    except Exception:
                        # adapter_dispatch 已存在（崩溃恢复的幂等重放）——合法。
                        pass
                else:
                    # 自动推进的新节点：进入 adapter 前重新执行 NodeReadiness
                    # （spec 9.1/7.3）；不 ready 则不建 adapter outbox，attempt 标 blocked。
                    # readiness_hint 在 writer 事务外预评估（readiness 读 ledger 走
                    # writer 队列，不能在 writer 线程 mutate 内再 submit）。
                    if readiness_hint is None:
                        ready, blockers = True, []
                    else:
                        ready, blockers = readiness_hint
                    if not ready:
                        uow.repository.insert_attempt(
                            _attempt_for_pending(
                                pending,
                                command_id=action.command_id or "cmd-recovery",
                                now_ms=now_ms,
                                status="blocked",
                                problem_json=json.dumps(
                                    {
                                        "code": "auto_advance_not_ready",
                                        "detail": "; ".join(
                                            str(b.get("code") or b) for b in blockers
                                        ),
                                    },
                                    ensure_ascii=False,
                                ),
                            )
                        )
                        blocked_sequence = uow.repository.advance_last_sequence(
                            dispatch.run_id, 1, now_ms
                        )
                        if blocked_sequence is not None:
                            blocked_run = uow.repository.get_run(dispatch.run_id)
                            blocked_run_version = blocked_run.run_version if blocked_run else 1
                            uow.repository.insert_event(
                                _event_record_for(
                                    run_id=dispatch.run_id,
                                    sequence=blocked_sequence,
                                    run_version=blocked_run_version,
                                    event_id=new_id("evt"),
                                    event_type="node_blocked",
                                    correlation_id=pending.action_id,
                                    payload={
                                        "nodeRunId": pending.node_run_id,
                                        "nodeId": pending.node_id,
                                        "autoAdvanceBlocked": True,
                                        "blockers": [
                                            str(b.get("code") or b) for b in blockers
                                        ],
                                    },
                                    now_ms=now_ms,
                                )
                            )
                    else:
                        uow.repository.insert_attempt(
                            _attempt_for_pending(
                                pending,
                                command_id=action.command_id or "cmd-recovery",
                                now_ms=now_ms,
                            )
                        )
                        try:
                            uow.repository.insert_outbox(
                                _adapter_dispatch_record(
                                    pending=pending,
                                    run_id=dispatch.run_id,
                                    command_id=action.command_id,
                                    now_ms=now_ms,
                                )
                            )
                        except Exception:
                            pass
            if result.completed:
                outcome = "succeeded"
                if dispatch.receipt is not None:
                    outcome = dispatch.receipt.outcome
                target_status = {
                    "succeeded": NodeAttemptStatus.SUCCEEDED.value,
                    "failed": NodeAttemptStatus.FAILED.value,
                    "blocked": NodeAttemptStatus.BLOCKED.value,
                    "cancelled": NodeAttemptStatus.CANCELLED.value,
                }.get(outcome, NodeAttemptStatus.FAILED.value)
                uow.repository.update_attempt_status(
                    dispatch.node_run_id,
                    target_status,
                    now_ms,
                    finished_at_ms=now_ms,
                )

        self._store.submit(mutate, force_flush=True).result(timeout=30)

    def _mark_blocked(self, action: Any, dispatch: GraphDispatch, detail: str) -> None:
        now_ms = self._now()
        problem = {"code": "iteration_decision_invalid", "detail": detail}

        def mutate(uow):
            uow.repository.fail_outbox(
                action.action_id, self._owner, now_ms, problem_json=json.dumps(problem)
            )
            uow.repository.update_attempt_status(
                dispatch.node_run_id,
                NodeAttemptStatus.BLOCKED.value,
                now_ms,
                problem_json=json.dumps(problem),
            )

        self._store.submit(mutate, force_flush=True).result(timeout=30)

    def _requeue_or_fail(self, action: Any, detail: str) -> None:
        now_ms = self._now()
        outbox_api.requeue_action(
            self._store,
            action.action_id,
            self._owner,
            now_ms,
            retry_at_ms=now_ms + 5_000,
            problem_json=json.dumps({"code": "transient", "detail": detail}),
        )


def _attempt_for_pending(
    pending: Any,
    *,
    command_id: str,
    now_ms: int,
    status: str = "dispatching",
    problem_json: str | None = None,
):
    from core.research.workflow.ledger import NodeAttemptRecord

    return NodeAttemptRecord(
        node_run_id=pending.node_run_id,
        run_id=pending.run_id,
        node_id=pending.node_id,
        attempt=pending.attempt,
        actor_kind=pending.actor_kind.value,
        status=status,
        command_id=command_id,
        binding_snapshot_id=pending.binding_snapshot_id,
        input_snapshot_hash=pending.input_snapshot_hash,
        pending_action_id=pending.action_id,
        execution_anchor_id=None,
        retry_of_node_run_id=None,
        problem_json=problem_json,
        started_at_ms=now_ms,
        updated_at_ms=now_ms,
        finished_at_ms=now_ms if status != "dispatching" else None,
    )


def _event_record_for(
    *,
    run_id: str,
    sequence: int,
    run_version: int,
    event_id: str,
    event_type: str,
    correlation_id: str,
    payload: dict,
    now_ms: int,
):
    from core.research.workflow.ledger import EventRecord

    return EventRecord(
        run_id=run_id,
        sequence=sequence,
        event_id=event_id,
        run_version=run_version,
        event_type=event_type,
        actor_json=json.dumps({"actorType": "system", "actorId": "graph-worker"}),
        correlation_id=correlation_id,
        causation_id=None,
        payload_json=json.dumps(payload, ensure_ascii=False),
        occurred_at_ms=now_ms,
    )


def _adapter_dispatch_record(*, pending: Any, run_id: str, command_id: str | None, now_ms: int):
    from core.research.workflow.ledger import OutboxRecord

    return OutboxRecord(
        action_id=new_id("act"),
        run_id=run_id,
        command_id=command_id,
        node_run_id=pending.node_run_id,
        action_kind="adapter_dispatch",
        idempotency_key=f"adapter:{pending.action_id}",
        payload_json=json.dumps(pending.to_dict()),
        status="pending",
        attempt_count=0,
        available_at_ms=now_ms,
        lease_owner=None,
        lease_expires_at_ms=None,
        last_problem_json=None,
        created_at_ms=now_ms,
        updated_at_ms=now_ms,
    )
