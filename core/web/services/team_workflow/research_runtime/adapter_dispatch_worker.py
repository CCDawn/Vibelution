"""Adapter dispatch worker (spec 7.3 steps 5-15).

Order is strict and crash-safe:
  1. read-back input refs/hash (mismatch -> attempt blocked, no budget);
  2. adapter preflight;
  3. budget reservation (idempotent by actionId) BEFORE any task creation;
  4. adapter execute (TaskBundle/Session/Turn or system action or human task);
  5. domain read-back + version/hash verification;
  6. one Ledger transaction: ack, anchor, artifact receipts, budget receipt,
     attempt running->succeeded, handoff, events, graph resume outbox.
Any crash point re-runs idempotently through stable actionIds.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from core.research.workflow.contracts import (
    ExecutionReceipt,
    PendingAction,
)
from core.research.workflow.ledger import WorkflowLedgerStore, outbox as outbox_api
from core.research.workflow.models import ActorKind
from core.research.workflow.transitions import NodeAttemptStatus

from .action_registry import ActionRegistry, VerifiedDomainResult
from .domain_ports import DomainPorts
from .ids import new_id


class AdapterDispatchWorker:
    def __init__(
        self,
        *,
        store: WorkflowLedgerStore,
        registry: ActionRegistry,
        ports: DomainPorts,
        owner_id: str = "adapter-worker",
        lease_ms: int = 30_000,
        now_provider: Callable[[], int] | None = None,
        successor_fn: Callable[[str], tuple[str, ...]] | None = None,
        commit_hook: Callable[[], None] | None = None,
    ) -> None:
        self._store = store
        self._registry = registry
        self._ports = ports
        self._owner = owner_id
        self._lease_ms = lease_ms
        self._now = now_provider or (lambda: int(time.time() * 1000))
        self._successor_fn = successor_fn or (lambda node_id: ())
        self._commit_hook = commit_hook
        self.last_problem: dict[str, Any] | None = None

    def run_once(self, limit: int = 4) -> int:
        leased = outbox_api.lease_ready_actions(
            self._store,
            owner=self._owner,
            now_ms=self._now(),
            limit=limit,
            lease_ms=self._lease_ms,
            action_kinds=("adapter_dispatch",),
        )
        for action in leased:
            self._handle(action)
        return len(leased)

    def _handle(self, outbox: Any) -> None:
        action = PendingAction.from_dict(json.loads(outbox.payload_json))
        adapter = self._registry.get(action.action_kind)
        if adapter is None:
            self._fail_unregistered(outbox, action)
            return

        verdict = self._ports.read_back_input(action)
        if not verdict.ok:
            self._block_attempt(outbox, action, "input_readback_mismatch", verdict.detail)
            return

        preflight = adapter.preflight(action)
        if not preflight.ready:
            self._block_attempt(outbox, action, "adapter_preflight_failed", json.dumps(preflight.blockers, ensure_ascii=False))
            return

        result = adapter.execute(action)
        if result.outcome != "succeeded":
            self._fail_attempt(outbox, action, result.problem or {"code": "adapter_execution_failed"})
            return

        verified = adapter.verify(action, result)
        if verified.outcome != "succeeded":
            self._block_attempt(outbox, action, verified.problem.get("code", "verification_failed") if verified.problem else "verification_failed", json.dumps(verified.problem, ensure_ascii=False))
            return

        try:
            if action.actor_kind == ActorKind.HUMAN:
                self._commit_human(outbox, action, verified)
            else:
                self._commit_verified(outbox, action, verified, usage=result.usage)
            if verified.budget_receipt:
                # ledger 提交后结算领域预算权威；settle 失败不回滚已提交 receipt，
                # 由领域侧保留 reservation 供对账。
                self._settle_domain_budget(verified.budget_receipt, result.usage)
        except Exception as exc:
            # commit 前 crash：outbox 保留 pending（可重领取），领域侧幂等。
            self._requeue_or_fail(outbox, str(exc))

    # ------------------------------------------------------------ commits

    def _commit_verified(
        self, outbox: Any, action: PendingAction, verified: VerifiedDomainResult, *, usage: dict[str, Any]
    ) -> None:
        now_ms = self._now()
        anchor_id = new_id("anchor") if verified.anchor else None
        budget_receipt_id = new_id("br") if verified.budget_receipt else None
        handoff_id = new_id("ho")
        event_count = 3

        receipt_id_by_index: list[str] = []
        for index in range(len(verified.artifact_receipts)):
            receipt_id_by_index.append(new_id("ar"))

        def mutate(uow):
            if self._commit_hook is not None:
                self._commit_hook()
            acked = uow.repository.ack_outbox(outbox.action_id, self._owner, now_ms)
            if not acked:
                return
            run = uow.repository.get_run(action.run_id)
            if run is None:
                return
            last_sequence = uow.repository.advance_last_sequence(
                action.run_id, event_count, now_ms
            )
            if last_sequence is None:
                return
            base_sequence = last_sequence - event_count

            if anchor_id and verified.anchor:
                uow.repository.insert_anchor(
                    anchor_id=anchor_id,
                    node_run_id=action.node_run_id,
                    actor_kind=action.actor_kind.value,
                    anchor_json=json.dumps(verified.anchor, ensure_ascii=False),
                    created_at_ms=now_ms,
                    agent_id=verified.anchor.get("agentId"),
                    session_id=verified.anchor.get("sessionId"),
                    session_attempt=verified.anchor.get("sessionAttempt"),
                    task_id=verified.anchor.get("taskId"),
                    turn_id=verified.anchor.get("turnId"),
                    system_action_id=verified.anchor.get("systemActionId"),
                )
                uow.repository.update_attempt_status(
                    action.node_run_id,
                    NodeAttemptStatus.RUNNING.value,
                    now_ms,
                    execution_anchor_id=anchor_id,
                )

            for index, receipt in enumerate(verified.artifact_receipts):
                uow.repository.insert_artifact_receipt(
                    receipt_id=receipt_id_by_index[index],
                    run_id=action.run_id,
                    node_run_id=action.node_run_id,
                    team_id=run.team_id,
                    artifact_kind=str(receipt.get("artifactType") or ""),
                    canonical_ref_json=json.dumps({"canonicalRef": receipt.get("canonicalRef")}),
                    artifact_version=str(receipt.get("version") or ""),
                    sha256=str(receipt.get("sha256") or ""),
                    domain_revision=str(receipt.get("domainRevision") or ""),
                    materialized=1,
                    verified_at_ms=now_ms,
                )

            if budget_receipt_id and verified.budget_receipt:
                uow.repository.insert_budget_receipt(
                    receipt_id=budget_receipt_id,
                    run_id=action.run_id,
                    node_run_id=action.node_run_id,
                    reservation_id=str(verified.budget_receipt.get("reservationId") or f"res-{action.action_id}"),
                    stage_id=str(verified.budget_receipt.get("stageId") or ""),
                    policy_hash=action.budget_policy_hash,
                    reserved_json=json.dumps(verified.budget_receipt.get("reserved") or {}),
                    created_at_ms=now_ms,
                )
                uow.repository.update_budget_receipt(
                    budget_receipt_id,
                    status="settled",
                    now_ms=now_ms,
                    settled_json=json.dumps({"usage": usage}),
                )

            uow.repository.update_attempt_status(
                action.node_run_id,
                NodeAttemptStatus.SUCCEEDED.value,
                now_ms,
                finished_at_ms=now_ms,
            )

            successors = self._successor_fn(action.node_id)
            if successors:
                uow.repository.insert_handoff(
                    handoff_id=handoff_id,
                    run_id=action.run_id,
                    edge_id=f"{action.node_id}->{successors[0]}",
                    from_node_run_id=action.node_run_id,
                    to_node_id=successors[0],
                    to_node_run_id=None,
                    gate_kind="auto",
                    input_snapshot_hash=action.input_snapshot_hash,
                    offered_at_ms=now_ms,
                )
                uow.repository.update_handoff_status(
                    handoff_id,
                    "ready",
                    now_ms,
                )
                for index, receipt_id in enumerate(receipt_id_by_index):
                    uow.repository.insert_handoff_receipt(handoff_id, receipt_id, index)

                receipt = ExecutionReceipt(
                    action_id=action.action_id,
                    node_run_id=action.node_run_id,
                    outcome="succeeded",
                    artifact_receipt_ids=tuple(receipt_id_by_index),
                    execution_anchor_id=anchor_id,
                    budget_receipt_id=budget_receipt_id,
                    problem=None,
                    completed_at_ms=now_ms,
                )
                attempt = uow.repository.get_attempt(action.node_run_id)
                if attempt is None:
                    return
                uow.repository.insert_outbox(
                    _resume_dispatch_record(
                        run=run,
                        attempt=attempt,
                        action=action,
                        receipt=receipt,
                        command_id=outbox.command_id,
                        now_ms=now_ms,
                    )
                )

            uow.repository.insert_event(
                _event(
                    run_id=action.run_id,
                    sequence=base_sequence + 1,
                    run_version=run.run_version,
                    event_id=new_id("evt"),
                    event_type="execution_anchor_bound" if anchor_id else "node_running",
                    correlation_id=action.action_id,
                    payload={"nodeRunId": action.node_run_id, "anchorId": anchor_id},
                    now_ms=now_ms,
                )
            )
            uow.repository.insert_event(
                _event(
                    run_id=action.run_id,
                    sequence=base_sequence + 2,
                    run_version=run.run_version,
                    event_id=new_id("evt"),
                    event_type="artifact_verified",
                    correlation_id=action.action_id,
                    payload={"nodeRunId": action.node_run_id, "receiptIds": receipt_id_by_index},
                    now_ms=now_ms,
                )
            )
            uow.repository.insert_event(
                _event(
                    run_id=action.run_id,
                    sequence=base_sequence + 3,
                    run_version=run.run_version,
                    event_id=new_id("evt"),
                    event_type="node_succeeded",
                    correlation_id=action.action_id,
                    payload={"nodeRunId": action.node_run_id, "handoffId": handoff_id},
                    now_ms=now_ms,
                )
            )

        self._store.submit(mutate, force_flush=True).result(timeout=30)

    def _commit_human(
        self, outbox: Any, action: PendingAction, verified: VerifiedDomainResult
    ) -> None:
        now_ms = self._now()
        anchor_id = new_id("anchor")
        task_id = str((verified.anchor or {}).get("humanTaskId") or new_id("ht"))
        handoff_id = new_id("ho")

        def mutate(uow):
            acked = uow.repository.ack_outbox(outbox.action_id, self._owner, now_ms)
            if not acked:
                return
            run = uow.repository.get_run(action.run_id)
            if run is None:
                return
            last_sequence = uow.repository.advance_last_sequence(
                action.run_id, 1, now_ms
            )
            if last_sequence is None:
                return
            uow.repository.insert_anchor(
                anchor_id=anchor_id,
                node_run_id=action.node_run_id,
                actor_kind=action.actor_kind.value,
                anchor_json=json.dumps(verified.anchor or {}, ensure_ascii=False),
                created_at_ms=now_ms,
                human_task_id=task_id,
            )
            successors = self._successor_fn(action.node_id)
            if successors:
                uow.repository.insert_handoff(
                    handoff_id=handoff_id,
                    run_id=action.run_id,
                    edge_id=f"{action.node_id}->{successors[0]}",
                    from_node_run_id=action.node_run_id,
                    to_node_id=successors[0],
                    to_node_run_id=None,
                    gate_kind="human",
                    input_snapshot_hash=action.input_snapshot_hash,
                    offered_at_ms=now_ms,
                )
                uow.repository.update_handoff_status(handoff_id, "waiting_human", now_ms)
            uow.repository.insert_human_task(
                task_id=task_id,
                run_id=action.run_id,
                node_run_id=action.node_run_id,
                handoff_id=handoff_id if successors else None,
                task_kind=f"gate:{action.node_id}",
                prompt_json=json.dumps({"nodeId": action.node_id}),
                created_at_ms=now_ms,
            )
            uow.repository.update_attempt_status(
                action.node_run_id,
                NodeAttemptStatus.WAITING_HUMAN.value,
                now_ms,
                execution_anchor_id=anchor_id,
            )
            uow.repository.insert_event(
                _event(
                    run_id=action.run_id,
                    sequence=last_sequence,
                    run_version=run.run_version,
                    event_id=new_id("evt"),
                    event_type="node_waiting_human",
                    correlation_id=action.action_id,
                    payload={"nodeRunId": action.node_run_id, "taskId": task_id},
                    now_ms=now_ms,
                )
            )

        self._store.submit(mutate, force_flush=True).result(timeout=30)

    # ------------------------------------------------------------ failures

    def _settle_domain_budget(self, reservation: dict[str, Any], usage: dict[str, Any]) -> None:
        """After the ledger receipt commits, settle the domain budget authority.
        A settle failure never rolls back the committed receipt; the domain
        authority keeps the reservation for later reconciliation."""
        try:
            self._ports.settle_budget(reservation=reservation, usage=usage)
        except Exception:
            return

    def _block_attempt(self, outbox: Any, action: PendingAction, code: str, detail: str) -> None:
        now_ms = self._now()
        problem = {"code": code, "detail": detail}

        def mutate(uow):
            uow.repository.fail_outbox(
                outbox.action_id, self._owner, now_ms, problem_json=json.dumps(problem)
            )
            uow.repository.update_attempt_status(
                action.node_run_id,
                NodeAttemptStatus.BLOCKED.value,
                now_ms,
                problem_json=json.dumps(problem),
            )

        self._store.submit(mutate, force_flush=True).result(timeout=30)

    def _fail_attempt(self, outbox: Any, action: PendingAction, problem: dict) -> None:
        now_ms = self._now()

        def mutate(uow):
            uow.repository.fail_outbox(
                outbox.action_id, self._owner, now_ms, problem_json=json.dumps(problem)
            )
            uow.repository.update_attempt_status(
                action.node_run_id,
                NodeAttemptStatus.FAILED.value,
                now_ms,
                problem_json=json.dumps(problem),
                finished_at_ms=now_ms,
            )

        self._store.submit(mutate, force_flush=True).result(timeout=30)

    def _fail_unregistered(self, outbox: Any, action: PendingAction) -> None:
        now_ms = self._now()
        problem = {"code": "adapter_not_registered", "detail": action.action_kind}

        def mutate(uow):
            uow.repository.fail_outbox(
                outbox.action_id, self._owner, now_ms, problem_json=json.dumps(problem)
            )
            uow.repository.update_attempt_status(
                action.node_run_id,
                NodeAttemptStatus.FAILED.value,
                now_ms,
                problem_json=json.dumps(problem),
                finished_at_ms=now_ms,
            )

        self._store.submit(mutate, force_flush=True).result(timeout=30)

    def _requeue_or_fail(self, outbox: Any, detail: str) -> None:
        now_ms = self._now()
        outbox_api.requeue_action(
            self._store,
            outbox.action_id,
            self._owner,
            now_ms,
            retry_at_ms=now_ms + 5_000,
            problem_json=json.dumps({"code": "transient", "detail": detail}),
        )


def _event(*, run_id: str, sequence: int, run_version: int, event_id: str, event_type: str, correlation_id: str, payload: dict, now_ms: int):
    from core.research.workflow.ledger import EventRecord

    return EventRecord(
        run_id=run_id,
        sequence=sequence,
        event_id=event_id,
        run_version=run_version,
        event_type=event_type,
        actor_json=json.dumps({"actorType": "system", "actorId": "adapter-worker"}),
        correlation_id=correlation_id,
        causation_id=None,
        payload_json=json.dumps(payload, ensure_ascii=False),
        occurred_at_ms=now_ms,
    )


def _resume_dispatch_record(*, run: Any, attempt: Any, action: PendingAction, receipt: ExecutionReceipt, command_id: str | None, now_ms: int):
    from .graph_dispatch_factory import build_graph_dispatch_record

    return build_graph_dispatch_record(
        run=run,
        attempt=attempt,
        command_id=command_id or "cmd-recovery",
        dispatch_kind="resume_action",
        now_ms=now_ms,
        receipt_payload=receipt.to_dict(),
    )
