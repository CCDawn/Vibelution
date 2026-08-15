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
from .block_projection import sync_run_succeeded, terminal_facts_for_run
from .domain_ports import DomainPorts
from .failure_projection import apply_node_run_failure
from .ids import new_id
from .iteration_route import branch_decision_from_run, routed_successors


# Adapter execution may synchronously wait for a canonical Agent turn.  The
# lease must outlive that bounded wait so another Workbench process cannot
# concurrently reclaim the same action while the first execution is live.
DEFAULT_ADAPTER_DISPATCH_LEASE_MS = 150_000


class AdapterDispatchWorker:
    def __init__(
        self,
        *,
        store: WorkflowLedgerStore,
        registry: ActionRegistry,
        ports: DomainPorts,
        owner_id: str = "adapter-worker",
        lease_ms: int = DEFAULT_ADAPTER_DISPATCH_LEASE_MS,
        now_provider: Callable[[], int] | None = None,
        successor_fn: Callable[[str], tuple[str, ...]] | None = None,
        commit_hook: Callable[[], None] | None = None,
        after_commit_hook: Callable[[], None] | None = None,
    ) -> None:
        self._store = store
        self._registry = registry
        self._ports = ports
        self._owner = owner_id
        self._lease_ms = lease_ms
        self._now = now_provider or (lambda: int(time.time() * 1000))
        self._successor_fn = successor_fn or (lambda node_id: ())
        self._commit_hook = commit_hook
        self._after_commit_hook = after_commit_hook
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

        try:
            verdict = self._ports.read_back_input(action)
        except Exception as exc:
            self._fail_attempt(
                outbox,
                action,
                {"code": "input_readback_exception", "detail": str(exc)},
            )
            return
        if not verdict.ok:
            self._block_attempt(outbox, action, "input_readback_mismatch", verdict.detail)
            return

        try:
            preflight = adapter.preflight(action)
        except Exception as exc:
            self._fail_attempt(
                outbox,
                action,
                {"code": "adapter_preflight_exception", "detail": str(exc)},
            )
            return
        if not preflight.ready:
            self._block_attempt(
                outbox,
                action,
                "adapter_preflight_failed",
                json.dumps(preflight.blockers, ensure_ascii=False),
            )
            return

        try:
            result = adapter.execute(action)
        except Exception as exc:
            from .agent_turn_completion import TurnNotReadyError

            if isinstance(exc, TurnNotReadyError):
                # Turn still running — requeue without failing the attempt.
                self._requeue_or_fail(outbox, f"turn_not_ready:{exc}")
                return
            # Compensation-void unused reservation if execute reserved then crashed.
            self._void_unused_reservation(
                action, reason="execute_exception_compensation"
            )
            self._fail_attempt(
                outbox,
                action,
                {
                    "code": "adapter_execution_exception",
                    "detail": str(exc),
                    "actionId": action.action_id,
                },
            )
            return
        if result.outcome != "succeeded":
            self._void_unused_reservation(
                action, reason="execute_failed_compensation"
            )
            self._fail_attempt(
                outbox,
                action,
                result.problem or {"code": "adapter_execution_failed"},
            )
            return

        try:
            verified = adapter.verify(action, result)
        except Exception as exc:
            self._void_unused_reservation(
                action, reason="verify_exception_compensation"
            )
            self._fail_attempt(
                outbox,
                action,
                {"code": "adapter_verify_exception", "detail": str(exc)},
            )
            return
        if verified.outcome != "succeeded":
            self._void_unused_reservation(
                action, reason="verify_blocked_compensation"
            )
            self._block_attempt(
                outbox,
                action,
                verified.problem.get("code", "verification_failed")
                if verified.problem
                else "verification_failed",
                json.dumps(verified.problem, ensure_ascii=False),
            )
            return

        try:
            if action.actor_kind == ActorKind.HUMAN:
                self._commit_human(outbox, action, verified)
            else:
                self._commit_verified(outbox, action, verified, usage=result.usage)
            if verified.budget_receipt:
                # ledger 提交后结算领域预算权威；settle 失败不回滚已提交 receipt，
                # 进入 reconciliation_required 供对账（禁止静默吞掉）。
                self._settle_domain_budget(
                    outbox, action, verified.budget_receipt, result.usage
                )
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
            if self._after_commit_hook is not None:
                uow.after_commit(self._after_commit_hook)
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
                reservation_id = str(
                    verified.budget_receipt.get("reservationId")
                    or f"res-{action.action_id}"
                )
                existing = uow.repository.execute(
                    "SELECT receipt_id, status FROM budget_receipts "
                    "WHERE reservation_id = ?",
                    (reservation_id,),
                ).fetchone()
                if existing is None:
                    uow.repository.insert_budget_receipt(
                        receipt_id=budget_receipt_id,
                        run_id=action.run_id,
                        node_run_id=action.node_run_id,
                        reservation_id=reservation_id,
                        stage_id=str(verified.budget_receipt.get("stageId") or ""),
                        policy_hash=action.budget_policy_hash,
                        reserved_json=json.dumps(
                            verified.budget_receipt.get("reserved") or {}
                        ),
                        created_at_ms=now_ms,
                    )
                    receipt_to_settle = budget_receipt_id
                else:
                    receipt_to_settle = str(existing[0])
                if str(existing[1] if existing else "") != "settled":
                    uow.repository.update_budget_receipt(
                        receipt_to_settle,
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
            branch = branch_decision_from_run(run)
            routed = routed_successors(action.node_id, branch)
            if routed:
                successors = routed
            elif action.node_id in {"iteration_decision", "version_governance"}:
                successors = ()
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
            if successors or action.node_id == "result_package":
                uow.repository.insert_outbox(
                    _resume_dispatch_record(
                        run=run,
                        attempt=attempt,
                        action=action,
                        receipt=receipt,
                        command_id=outbox.command_id,
                        now_ms=now_ms,
                        state_update={"branch_decision": branch} if branch else None,
                    )
                )
            if action.node_id == "result_package":
                completion_kind, terminal_reason = terminal_facts_for_run(run)
                sync_run_succeeded(
                    uow,
                    run_id=action.run_id,
                    now_ms=now_ms,
                    completion_kind=completion_kind,
                    terminal_reason=terminal_reason,
                    node_id=action.node_id,
                    actor_id=self._owner,
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
            if self._after_commit_hook is not None:
                uow.after_commit(self._after_commit_hook)
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

    def _void_unused_reservation(self, action: PendingAction, *, reason: str) -> None:
        """Void any still-reserved budget receipt for this attempt (compensation).

        Intentional cancel uses release_budget_reservation -> `released` and is
        not routed through this path. Missing/already-terminal receipts are no-ops.
        """
        try:
            from .budget_authority_adapter import void_budget_reservation

            void_budget_reservation(
                self._store,
                {
                    "reservationId": f"reservation-{action.node_run_id}",
                    "actionId": action.action_id,
                },
                reason=reason,
                correlation_id=action.action_id,
            )
        except Exception:
            pass

    def _settle_domain_budget(
        self,
        outbox: Any,
        action: PendingAction,
        reservation: dict[str, Any],
        usage: dict[str, Any],
    ) -> None:
        """After the ledger receipt commits, settle the domain budget authority.

        A settle failure never rolls back the committed receipt. Mark the run
        (and attempt problem) reconciliation_required and insert an open
        recovery_record — do not only set last_problem.
        """
        try:
            result = self._ports.settle_budget(reservation=reservation, usage=usage)
            if isinstance(result, dict) and result.get("status") not in (None, "settled"):
                raise RuntimeError(
                    f"budget settle returned non-settled status: {result.get('status')}"
                )
        except Exception as exc:
            problem = {
                "code": "budget_settle_failed",
                "detail": str(exc),
                "reservationId": str(reservation.get("reservationId") or ""),
                "actionId": action.action_id,
                "nodeRunId": action.node_run_id,
                "outboxActionId": getattr(outbox, "action_id", None),
            }
            self.last_problem = problem
            self._mark_budget_settle_reconciliation(action, problem)


    def _mark_budget_settle_reconciliation(
        self, action: PendingAction, problem: dict[str, Any]
    ) -> None:
        """Persist settle-failure reconciliation evidence on run + recovery_records."""
        now_ms = self._now()
        problem_json = json.dumps(problem, ensure_ascii=False)
        recovery_id = new_id("rec")

        def mutate(uow):
            run = uow.repository.get_run(action.run_id)
            if run is not None:
                try:
                    from core.research.workflow.transitions import RunStatus

                    if str(run.status) != RunStatus.RECONCILIATION_REQUIRED.value:
                        uow.repository.update_run_status(
                            action.run_id,
                            run.team_id,
                            RunStatus.RECONCILIATION_REQUIRED.value,
                            now_ms,
                            blocked_problem_json=problem_json,
                        )
                    else:
                        uow.repository.execute(
                            "UPDATE workflow_runs SET blocked_problem_json = ?, "
                            "updated_at_ms = ? WHERE run_id = ?",
                            (problem_json, now_ms, action.run_id),
                        )
                except ValueError:
                    # Illegal transition (e.g. already terminal): still record evidence.
                    uow.repository.execute(
                        "UPDATE workflow_runs SET blocked_problem_json = ?, "
                        "updated_at_ms = ? WHERE run_id = ?",
                        (problem_json, now_ms, action.run_id),
                    )

            if uow.repository.get_attempt(action.node_run_id) is not None:
                # Attempt may already be succeeded post-commit; keep status but
                # attach the settle problem for operators / readiness.
                uow.repository.execute(
                    "UPDATE node_attempts SET problem_json = ?, updated_at_ms = ? "
                    "WHERE node_run_id = ?",
                    (problem_json, now_ms, action.node_run_id),
                )

            existing = uow.repository.execute(
                "SELECT recovery_id FROM recovery_records "
                "WHERE run_id = ? AND problem_code = ? AND status = 'open' "
                "AND evidence_json LIKE ?",
                (
                    action.run_id,
                    "budget_settle_failed",
                    f"%{action.node_run_id}%",
                ),
            ).fetchone()
            if existing is None:
                uow.repository.execute(
                    "INSERT INTO recovery_records ("
                    "recovery_id, run_id, problem_code, evidence_json, status, "
                    "resolution_json, created_at_ms, resolved_at_ms"
                    ") VALUES (?, ?, ?, ?, 'open', NULL, ?, NULL)",
                    (
                        recovery_id,
                        action.run_id,
                        "budget_settle_failed",
                        problem_json,
                        now_ms,
                    ),
                )

        self._store.submit(mutate, force_flush=True).result(timeout=30)

    def _block_attempt(self, outbox: Any, action: PendingAction, code: str, detail: str) -> None:
        now_ms = self._now()
        from .block_projection import apply_node_run_block
        from .blocked_reason import parse_problem_json

        parsed = parse_problem_json(detail)
        problem = {
            "code": code,
            "detail": (parsed or {}).get("detail") or detail,
        }
        if parsed and parsed.get("code") and parsed.get("code") != "workflow_blocked":
            problem["code"] = str(parsed.get("code") or code)

        def mutate(uow):
            uow.repository.fail_outbox(
                outbox.action_id, self._owner, now_ms, problem_json=json.dumps(problem)
            )
            apply_node_run_block(
                uow,
                run_id=action.run_id,
                node_run_id=action.node_run_id,
                node_id=action.node_id,
                problem=problem,
                now_ms=now_ms,
                actor_id=self._owner,
                correlation_id=str(action.action_id or outbox.action_id),
            )

        self._store.submit(mutate, force_flush=True).result(timeout=30)

    def _fail_attempt(self, outbox: Any, action: PendingAction, problem: dict) -> None:
        now_ms = self._now()

        def mutate(uow):
            uow.repository.fail_outbox(
                outbox.action_id, self._owner, now_ms, problem_json=json.dumps(problem)
            )
            apply_node_run_failure(
                uow,
                run_id=action.run_id,
                node_run_id=action.node_run_id,
                node_id=action.node_id,
                problem=problem,
                now_ms=now_ms,
                actor_id=self._owner,
                correlation_id=str(action.action_id or outbox.action_id),
            )

        self._store.submit(mutate, force_flush=True).result(timeout=30)

    def _fail_unregistered(self, outbox: Any, action: PendingAction) -> None:
        now_ms = self._now()
        problem = {"code": "adapter_not_registered", "detail": action.action_kind}

        def mutate(uow):
            uow.repository.fail_outbox(
                outbox.action_id, self._owner, now_ms, problem_json=json.dumps(problem)
            )
            apply_node_run_failure(
                uow,
                run_id=action.run_id,
                node_run_id=action.node_run_id,
                node_id=action.node_id,
                problem=problem,
                now_ms=now_ms,
                actor_id=self._owner,
                correlation_id=str(action.action_id or outbox.action_id),
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


def _resume_dispatch_record(*, run: Any, attempt: Any, action: PendingAction, receipt: ExecutionReceipt, command_id: str | None, now_ms: int, state_update: dict[str, Any] | None = None):
    from .graph_dispatch_factory import build_graph_dispatch_record

    return build_graph_dispatch_record(
        run=run,
        attempt=attempt,
        command_id=command_id or "cmd-recovery",
        dispatch_kind="resume_action",
        now_ms=now_ms,
        receipt_payload=receipt.to_dict(),
        state_update=state_update,
    )
