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
import threading
import time
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import replace
from typing import Any

from core.research.workflow.contracts import (
    ExecutionReceipt,
    PendingAction,
)
from core.research.workflow.ledger import WorkflowLedgerStore
from core.research.workflow.ledger import outbox as outbox_api
from core.research.workflow.models import ActorKind
from core.research.workflow.transitions import NodeAttemptStatus

from .action_registry import ActionRegistry, VerifiedDomainResult
from .block_projection import (
    sync_run_blocked,
    sync_run_succeeded,
    terminal_facts_for_run,
)
from .challenge_turn_policy import (
    CHALLENGE_LOGICAL_TASK_TIMEOUT_MS,
    CHALLENGE_NO_PROGRESS_TIMEOUT_MS,
    ChallengeTaskDeadlineExceeded,
    challenge_task_deadline_scope,
    decide_live_turn_wait,
)
from .domain_ports import DomainPorts
from .failure_projection import apply_node_run_failure
from .ids import new_id
from .iteration_route import branch_decision_from_run, routed_successors

# Adapter execution may synchronously wait for a canonical Agent turn.  The
# lease must outlive that bounded wait so another Workbench process cannot
# concurrently reclaim the same action while the first execution is live.
DEFAULT_ADAPTER_DISPATCH_LEASE_MS = 150_000


def _record_scene_event(event_code: str, *, outcome: str, fields: dict[str, Any]) -> None:
    """Best-effort worker observability; never breaks the dispatch path."""
    from core.web.services.runtime_scene_service import (
        record_runtime_scene_event_quietly,
    )

    record_runtime_scene_event_quietly(
        "team_workflow_orchestration",
        "adapter_dispatch_worker",
        event_code,
        level="info" if outcome in {"committed", "settled"} else "warning",
        outcome=outcome,
        fields=fields,
    )


def _action_identity(action: PendingAction) -> dict[str, Any]:
    return {
        "runId": str(getattr(action, "run_id", "") or ""),
        "nodeId": str(getattr(action, "node_id", "") or ""),
        "actionKind": str(getattr(action, "action_kind", "") or ""),
        "actionId": str(getattr(action, "action_id", "") or ""),
    }


class _OutboxLeaseLost(RuntimeError):
    """The worker must stop projecting after its outbox lease is lost."""


def _canonical_anchor_payload(
    action: PendingAction, anchor: dict[str, Any] | None
) -> dict[str, Any] | None:
    if not anchor:
        return None
    payload = dict(anchor)
    raw_scoped = payload.get("scopedSessions")
    if not isinstance(raw_scoped, list):
        return payload
    root = payload.get("rootSession")
    if not isinstance(root, dict):
        raise TypeError("v3 scoped execution anchor requires rootSession")
    root_session_id = str(root.get("sessionId") or "").strip()
    if not root_session_id:
        raise RuntimeError("v3 scoped execution anchor has no root session")
    scoped: list[dict[str, Any]] = []
    for raw in raw_scoped:
        if not isinstance(raw, dict):
            raise TypeError("v3 scoped execution anchor contains a non-object child")
        item = dict(raw)
        required = {
            "selectionId": str(item.get("selectionId") or "").strip(),
            "candidateId": str(item.get("candidateId") or "").strip(),
            "sessionId": str(item.get("sessionId") or "").strip(),
            "taskId": str(item.get("taskId") or "").strip(),
            "turnId": str(item.get("turnId") or "").strip(),
        }
        if not all(required.values()):
            raise RuntimeError("v3 candidate execution anchor is incomplete")
        if (
            str(item.get("parentSessionId") or "").strip() != root_session_id
            or str(item.get("rootSessionId") or "").strip() != root_session_id
        ):
            raise RuntimeError("v3 candidate execution anchor has invalid lineage")
        fragment_refs = item.get("fragmentRefs")
        if not isinstance(fragment_refs, list):
            raise TypeError("v3 candidate execution anchor requires fragmentRefs")
        if not fragment_refs or any(
            not str(fragment_ref or "").strip() for fragment_ref in fragment_refs
        ):
            raise RuntimeError(
                "v3 candidate execution anchor has no canonical fragment ref"
            )
        item["scopeKind"] = "workflow_candidate"
        scoped.append(item)
    selection_ids = {
        str(item.get("selectionId") or "").strip() for item in scoped
    }
    candidate_ids = [
        str(item.get("candidateId") or "").strip() for item in scoped
    ]
    if len(selection_ids) != 1 or len(set(candidate_ids)) != len(candidate_ids):
        raise RuntimeError("v3 candidate execution anchors have conflicting scopes")
    if action.selection_id and any(
        str(item.get("selectionId") or "") != action.selection_id for item in scoped
    ):
        raise RuntimeError("candidate anchor selection does not match PendingAction")
    if action.candidate_id:
        matching_candidates = [
            str(item.get("candidateId") or "").strip()
            for item in scoped
            if str(item.get("candidateId") or "").strip() == action.candidate_id
        ]
        if len(scoped) != 1 or not matching_candidates:
            raise RuntimeError("candidate anchor does not match PendingAction")
    raw_selected = (action.scope or {}).get("selectedCandidateIds")
    if isinstance(raw_selected, (list, tuple)):
        selected = {
            str(item).strip() for item in raw_selected if str(item).strip()
        }
        if selected and any(
            str(item.get("candidateId") or "").strip() not in selected
            for item in scoped
        ):
            raise RuntimeError("candidate anchor is outside PendingAction selection")
    root = {
        **root,
        "scopeKind": "workflow_node_root",
        "sessionId": root_session_id,
        "taskId": root.get("taskId") or None,
        "turnId": root.get("turnId") or None,
    }
    payload.update(
        {
            "schemaVersion": 3,
            "sessionId": root_session_id,
            "sessionAttempt": root.get("sessionAttempt"),
            "taskId": root.get("taskId"),
            "turnId": root.get("turnId"),
            "rootSession": root,
            "scopedSessions": scoped,
        }
    )
    return payload


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
        action = _heal_pending_action_identity(outbox, action)
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
            result = self._execute_with_lease_heartbeat(adapter, action, outbox)
        except Exception as exc:
            from .agent_turn_completion import TurnNotReadyError
            from .formal_hypothesis_fanout import HypothesisAuthorityUnavailable

            if isinstance(exc, _OutboxLeaseLost):
                return
            if isinstance(exc, ChallengeTaskDeadlineExceeded):
                self._fail_attempt(outbox, action, exc.problem)
                self._reconcile_stage_task_after_wait_timeout(action)
                return
            if isinstance(exc, (TurnNotReadyError, HypothesisAuthorityUnavailable)):
                # Transient turn/authority state — requeue without failing the attempt.
                if isinstance(exc, TurnNotReadyError) and _turn_alive_progressing(exc):
                    # A live, progressing turn is not a transient failure: the
                    # collection stage legitimately runs past one wait window.
                    # Keep waiting (heartbeat) without consuming the transient
                    # budget; wall-clock bounds the wait.
                    self._requeue_live_turn_wait(
                        outbox,
                        action,
                        str(exc),
                        snapshot=dict(getattr(exc, "snapshot", None) or {}),
                    )
                    return
                prefix = (
                    "turn_not_ready"
                    if isinstance(exc, TurnNotReadyError)
                    else "hypothesis_authority_unavailable"
                )
                self._requeue_or_fail(outbox, action, f"{prefix}:{exc}")
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
            committed = False
            if action.actor_kind == ActorKind.HUMAN:
                committed = self._commit_human(outbox, action, verified)
            else:
                committed = self._commit_verified(
                    outbox, action, verified, usage=result.usage
                )
            if committed and verified.budget_receipt:
                # ledger 提交后结算领域预算权威；settle 失败不回滚已提交 receipt，
                # 进入 reconciliation_required 供对账（禁止静默吞掉）。
                self._settle_domain_budget(
                    outbox, action, verified.budget_receipt, result.usage
                )
            if committed:
                actor_kind = getattr(action, "actor_kind", None)
                _record_scene_event(
                    "adapter_dispatch.committed",
                    outcome="committed",
                    fields={
                        **_action_identity(action),
                        "actorKind": str(
                            getattr(actor_kind, "value", actor_kind) or ""
                        ),
                        "budgetSettled": bool(
                            committed and verified.budget_receipt
                        ),
                    },
                )
        except Exception as exc:
            # commit 前 crash：outbox 保留 pending（可重领取），领域侧幂等。
            self._requeue_or_fail(outbox, action, str(exc))

    def _execute_with_lease_heartbeat(
        self, adapter: Any, action: PendingAction, outbox: Any
    ) -> Any:
        """Run a potentially long adapter turn while renewing its outbox lease."""

        stop = threading.Event()
        lost = threading.Event()
        interval_seconds = max(0.001, float(self._lease_ms) / 3000.0)

        def heartbeat() -> None:
            while not stop.wait(interval_seconds):
                try:
                    renewed = outbox_api.renew_lease(
                        self._store,
                        outbox.action_id,
                        self._owner,
                        now_ms=self._now(),
                        lease_ms=self._lease_ms,
                    )
                except Exception:
                    renewed = False
                if not renewed:
                    lost.set()
                    return

        thread = threading.Thread(
            target=heartbeat,
            name=f"outbox-lease-heartbeat:{outbox.action_id}",
            daemon=True,
        )
        thread.start()
        deadline_scope = (
            challenge_task_deadline_scope(
                int(getattr(outbox, "created_at_ms", 0) or self._now())
            )
            if action.actor_kind == ActorKind.AGENT
            else nullcontext()
        )
        try:
            with deadline_scope:
                result = adapter.execute(action)
        except Exception as exc:
            if lost.is_set():
                raise _OutboxLeaseLost("adapter outbox lease was lost") from exc
            raise
        finally:
            stop.set()
            thread.join(timeout=max(1.0, interval_seconds * 2.0))
        if lost.is_set():
            raise _OutboxLeaseLost("adapter outbox lease was lost")
        return result

    # ------------------------------------------------------------ commits

    def _commit_verified(
        self, outbox: Any, action: PendingAction, verified: VerifiedDomainResult, *, usage: dict[str, Any]
    ) -> bool:
        now_ms = self._now()
        anchor_payload = _canonical_anchor_payload(action, verified.anchor)
        anchor_id = new_id("anchor") if anchor_payload else None
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
                return False
            run = uow.repository.get_run(action.run_id)
            if run is None:
                return False
            last_sequence = uow.repository.advance_last_sequence(
                action.run_id, event_count, now_ms
            )
            if last_sequence is None:
                return False
            base_sequence = last_sequence - event_count
            bound_anchor_id = anchor_id

            if anchor_id and anchor_payload:
                existing_anchor = uow.repository.get_anchor_by_node_run(
                    action.node_run_id
                )
                if existing_anchor is None:
                    uow.repository.insert_anchor(
                        anchor_id=anchor_id,
                        node_run_id=action.node_run_id,
                        actor_kind=action.actor_kind.value,
                        anchor_json=json.dumps(anchor_payload, ensure_ascii=False),
                        created_at_ms=now_ms,
                        agent_id=anchor_payload.get("agentId"),
                        role_key=anchor_payload.get("roleKey"),
                        session_id=anchor_payload.get("sessionId"),
                        session_attempt=anchor_payload.get("sessionAttempt"),
                        task_id=anchor_payload.get("taskId"),
                        turn_id=anchor_payload.get("turnId"),
                        system_action_id=anchor_payload.get("systemActionId"),
                    )
                else:
                    bound_anchor_id = str(existing_anchor[0])
                    uow.repository.update_anchor_by_node_run(
                        node_run_id=action.node_run_id,
                        anchor_json=json.dumps(anchor_payload, ensure_ascii=False),
                        status="bound",
                        agent_id=anchor_payload.get("agentId"),
                        role_key=anchor_payload.get("roleKey"),
                        session_id=anchor_payload.get("sessionId"),
                        session_attempt=anchor_payload.get("sessionAttempt"),
                        task_id=anchor_payload.get("taskId"),
                        turn_id=anchor_payload.get("turnId"),
                        system_action_id=anchor_payload.get("systemActionId"),
                    )
                uow.repository.update_attempt_status(
                    action.node_run_id,
                    NodeAttemptStatus.RUNNING.value,
                    now_ms,
                    execution_anchor_id=bound_anchor_id,
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
                if not branch:
                    # Unreadable decision artifact: record the block instead of
                    # stranding the run as a silent no-successor "success".
                    sync_run_blocked(
                        uow,
                        run_id=action.run_id,
                        node_id=action.node_id,
                        problem={
                            "code": "iteration_branch_unreadable",
                            "detail": "iteration decision artifact could not be read; manual repair required",
                        },
                        now_ms=now_ms,
                    )
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
                execution_anchor_id=bound_anchor_id,
                budget_receipt_id=budget_receipt_id,
                problem=None,
                completed_at_ms=now_ms,
            )
            attempt = uow.repository.get_attempt(action.node_run_id)
            if attempt is None:
                return False
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
                    event_type=(
                        "execution_anchor_bound" if bound_anchor_id else "node_running"
                    ),
                    correlation_id=action.action_id,
                    payload={
                        "nodeRunId": action.node_run_id,
                        "anchorId": bound_anchor_id,
                    },
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
            return True

        return bool(self._store.submit(mutate, force_flush=True).result(timeout=30))

    def _commit_human(
        self, outbox: Any, action: PendingAction, verified: VerifiedDomainResult
    ) -> bool:
        now_ms = self._now()
        anchor_id = new_id("anchor")
        task_id = str((verified.anchor or {}).get("humanTaskId") or new_id("ht"))
        handoff_id = new_id("ho")

        def mutate(uow):
            if self._after_commit_hook is not None:
                uow.after_commit(self._after_commit_hook)
            acked = uow.repository.ack_outbox(outbox.action_id, self._owner, now_ms)
            if not acked:
                return False
            run = uow.repository.get_run(action.run_id)
            if run is None:
                return False
            last_sequence = uow.repository.advance_last_sequence(
                action.run_id, 1, now_ms
            )
            if last_sequence is None:
                return False
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
            return True

        return bool(self._store.submit(mutate, force_flush=True).result(timeout=30))

    # ------------------------------------------------------------ failures

    @staticmethod
    def _close_execution_anchor(
        uow: Any,
        *,
        action: PendingAction,
        status: str,
        problem: dict[str, Any],
    ) -> None:
        """Close a live root/candidate anchor in the same failure transaction."""

        row = uow.repository.get_anchor_by_node_run(action.node_run_id)
        if row is None:
            return
        try:
            payload = json.loads(row[13] or "{}")
        except (TypeError, ValueError, IndexError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        root = payload.get("rootSession")
        if not isinstance(root, dict):
            root = {}
        root["status"] = status
        payload["rootSession"] = root
        payload["status"] = status
        scoped = payload.get("scopedSessions")
        if isinstance(scoped, list):
            for item in scoped:
                if isinstance(item, dict):
                    item["status"] = status
        payload["closure"] = {
            "code": str(problem.get("code") or "execution_failed")[:120],
            "detail": str(problem.get("detail") or "")[:400],
            "status": status,
        }
        uow.repository.update_anchor_by_node_run(
            node_run_id=action.node_run_id,
            anchor_json=json.dumps(payload, ensure_ascii=False),
            status=status,
        )

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
            return
        _record_scene_event(
            "adapter_dispatch.budget_settled",
            outcome="settled",
            fields={
                **_action_identity(action),
                "reservationId": str(reservation.get("reservationId") or ""),
            },
        )


    def _mark_budget_settle_reconciliation(
        self, action: PendingAction, problem: dict[str, Any]
    ) -> None:
        """Persist settle-failure reconciliation evidence on run + recovery_records."""
        now_ms = self._now()
        problem_json = json.dumps(problem, ensure_ascii=False)
        recovery_id = new_id("rec")
        _record_scene_event(
            "adapter_dispatch.budget_settle_reconciliation",
            outcome="reconciliation_required",
            fields={
                **_action_identity(action),
                "reservationId": str(problem.get("reservationId") or ""),
                "errorType": "BudgetSettleFailed",
            },
        )

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
        _record_scene_event(
            "adapter_dispatch.attempt_blocked",
            outcome="blocked",
            fields={
                **_action_identity(action),
                "problemCode": str(problem.get("code") or ""),
            },
        )

        def mutate(uow):
            failed = uow.repository.fail_outbox(
                outbox.action_id, self._owner, now_ms, problem_json=json.dumps(problem)
            )
            if not failed:
                return
            self._close_execution_anchor(
                uow,
                action=action,
                status="blocked",
                problem=problem,
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
        _record_scene_event(
            "adapter_dispatch.attempt_failed",
            outcome="failed",
            fields={
                **_action_identity(action),
                "problemCode": str(problem.get("code") or ""),
            },
        )

        def mutate(uow):
            failed = uow.repository.fail_outbox(
                outbox.action_id, self._owner, now_ms, problem_json=json.dumps(problem)
            )
            if not failed:
                return
            self._close_execution_anchor(
                uow,
                action=action,
                status="failed",
                problem=problem,
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
            failed = uow.repository.fail_outbox(
                outbox.action_id, self._owner, now_ms, problem_json=json.dumps(problem)
            )
            if not failed:
                return
            self._close_execution_anchor(
                uow,
                action=action,
                status="failed",
                problem=problem,
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

    _MAX_TRANSIENT_ATTEMPTS = 5

    # Challenge Cup live waits are bounded independently from the provider's
    # 600s transport insurance.  The outbox created_at clock persists across
    # worker requeues, and unchanged state does not get extended by heartbeat.
    _MAX_LIVE_TURN_WAIT_MS = CHALLENGE_LOGICAL_TASK_TIMEOUT_MS
    _MAX_LIVE_TURN_NO_PROGRESS_MS = CHALLENGE_NO_PROGRESS_TIMEOUT_MS

    def _requeue_live_turn_wait(
        self,
        outbox: Any,
        action: PendingAction,
        detail: str,
        *,
        snapshot: dict[str, Any] | None = None,
    ) -> None:
        now_ms = self._now()
        snapshot = dict(snapshot or {})
        try:
            previous_problem = json.loads(
                str(getattr(outbox, "last_problem_json", "") or "{}")
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            previous_problem = {}
        if not isinstance(previous_problem, dict):
            previous_problem = {}
        start_candidates = (
            int(previous_problem.get("logicalTaskStartedAtMs") or 0),
            int(getattr(outbox, "created_at_ms", 0) or 0),
            int(snapshot.get("challengeTaskStartedAtMs") or 0),
        )
        created_at_ms = min(
            (value for value in start_candidates if value > 0),
            default=now_ms,
        )
        decision = decide_live_turn_wait(
            now_ms=now_ms,
            created_at_ms=created_at_ms,
            previous_problem=previous_problem,
            snapshot=snapshot,
        )
        if created_at_ms and decision.should_stop:
            self._fail_attempt(
                outbox,
                action,
                {
                    "code": decision.stop_code,
                    "detail": str(detail)[:400],
                    "waitedMs": decision.waited_ms,
                    "maxWaitMs": self._MAX_LIVE_TURN_WAIT_MS,
                    "noProgressMs": decision.no_progress_ms,
                    "maxNoProgressMs": self._MAX_LIVE_TURN_NO_PROGRESS_MS,
                    "logicalTaskStartedAtMs": decision.started_at_ms,
                },
            )
            # The abandoned wait previously skipped the pushed-writeback leg
            # (reconcile_source_collection_stage_session_task_after_turn), so
            # the stage task stayed "running" in its store while the ledger
            # attempt was already failed. Best-effort reconcile closes that
            # state fork; it must never break the dispatch path.
            self._reconcile_stage_task_after_wait_timeout(action)
            return
        _record_scene_event(
            "adapter_dispatch.live_turn_wait",
            outcome="requeued",
            fields={
                **_action_identity(action),
                "attemptCount": int(getattr(outbox, "attempt_count", 0) or 0),
                "waitedMs": decision.waited_ms,
                "noProgressMs": decision.no_progress_ms,
                "progressAdvanced": decision.progress_advanced,
                "detail": str(detail)[:160],
            },
        )
        # The wait window itself is silent in workflow_events (~125s requeues
        # only touch outbox rows); emit one heartbeat event per requeue so a
        # wedged turn is observable in the run's event stream.
        self._record_live_turn_wait_heartbeat(
            action,
            attempt_count=int(getattr(outbox, "attempt_count", 0) or 0),
            waited_ms=decision.waited_ms,
            no_progress_ms=decision.no_progress_ms,
            progress_advanced=decision.progress_advanced,
        )
        outbox_api.requeue_action(
            self._store,
            outbox.action_id,
            self._owner,
            now_ms,
            retry_at_ms=now_ms + 5_000,
            problem_json=json.dumps(
                {
                    "code": "live_turn_wait",
                    "detail": str(detail)[:400],
                    "waitedMs": decision.waited_ms,
                    "maxWaitMs": self._MAX_LIVE_TURN_WAIT_MS,
                    "noProgressMs": decision.no_progress_ms,
                    "maxNoProgressMs": self._MAX_LIVE_TURN_NO_PROGRESS_MS,
                    "logicalTaskStartedAtMs": decision.started_at_ms,
                    "lastProgressAtMs": decision.last_progress_at_ms,
                    "progressFingerprint": decision.progress_fingerprint,
                }
            ),
            reset_attempts=True,
        )

    def _record_live_turn_wait_heartbeat(
        self,
        action: PendingAction,
        *,
        attempt_count: int,
        waited_ms: int,
        no_progress_ms: int,
        progress_advanced: bool,
    ) -> None:
        """Append one workflow event per live-turn wait requeue (observability).

        The outbox requeue itself never touches workflow_events, so a turn
        that waits for hours used to be invisible in the run's event stream.
        Pure diagnostics: any failure is swallowed after a scene event.
        """
        now_ms = self._now()
        payload = {
            **_action_identity(action),
            "attemptCount": int(attempt_count or 0),
            "waitedMs": int(waited_ms or 0),
            "maxWaitMs": self._MAX_LIVE_TURN_WAIT_MS,
            "noProgressMs": int(no_progress_ms or 0),
            "maxNoProgressMs": self._MAX_LIVE_TURN_NO_PROGRESS_MS,
            "progressAdvanced": bool(progress_advanced),
        }

        def mutate(uow):
            run = uow.repository.get_run(action.run_id)
            if run is None:
                return False
            sequence = uow.repository.advance_last_sequence(action.run_id, 1, now_ms)
            if sequence is None:
                return False
            uow.repository.insert_event(
                _event(
                    run_id=action.run_id,
                    sequence=sequence,
                    run_version=run.run_version,
                    event_id=new_id("evt"),
                    event_type="adapter_dispatch_live_turn_wait_heartbeat",
                    correlation_id=action.action_id,
                    payload=payload,
                    now_ms=now_ms,
                )
            )
            return True

        try:
            self._store.submit(mutate, force_flush=True).result(timeout=30)
        except Exception as exc:  # noqa: BLE001 - heartbeat must never break requeue
            _record_scene_event(
                "adapter_dispatch.live_turn_wait_heartbeat_failed",
                outcome="failed",
                fields={
                    **_action_identity(action),
                    "waitedMs": int(waited_ms or 0),
                    "errorType": type(exc).__name__,
                    "error": str(exc)[:200],
                },
            )

    def _reconcile_stage_task_after_wait_timeout(self, action: PendingAction) -> None:
        """Close the stage-task writeback window an abandoned live wait left open.

        After the wall-clock cap fails the attempt, the canonical Agent turn may
        still be running (or may have finished unnoticed). The stage session
        task only settles through
        ``reconcile_source_collection_stage_session_task_after_turn`` — normally
        invoked by ``complete_agent_turn_outputs`` at turn terminal, which the
        abandoned wait never reaches. Locate the dispatch anchor (the same
        taskId/sessionId/turnId the writeback leg would have used), read the
        current completion snapshot, and reconcile; a non-terminal snapshot
        reconciles under ``interrupted`` semantics. Idempotent and best-effort:
        any failure is logged and never blocks the dispatch path.
        """
        try:
            from .task_adapter_registry import resolve_agent_task_adapter

            adapter_spec = resolve_agent_task_adapter(action.node_id)
            if adapter_spec is None or adapter_spec.family != "source_collection":
                return

            anchor = self._store.read(
                lambda repo: repo.get_anchor_by_node_run(action.node_run_id)
            )
            payload: dict[str, Any] = {}
            if anchor is not None and len(anchor) > 13:
                try:
                    raw = json.loads(anchor[13] or "{}")
                    if isinstance(raw, dict):
                        payload = raw
                except (TypeError, ValueError):
                    payload = {}
            def scalar(index: int, key: str) -> str:
                column = ""
                if anchor is not None and len(anchor) > index:
                    column = str(anchor[index] or "")
                return str(column or payload.get(key) or "").strip()
            session_id = scalar(5, "sessionId")
            task_id = scalar(7, "taskId")
            turn_id = scalar(8, "turnId")
            if not task_id:
                _record_scene_event(
                    "adapter_dispatch.live_turn_wait_reconcile_skipped",
                    outcome="skipped",
                    fields={
                        **_action_identity(action),
                        "reason": "no_anchor_task_identity",
                    },
                )
                return

            run = self._store.get_run(action.run_id)
            input_snapshot: dict[str, Any] = {}
            if run is not None and run.input_snapshot_json:
                try:
                    raw = json.loads(run.input_snapshot_json)
                    if isinstance(raw, dict):
                        input_snapshot = raw
                except (TypeError, ValueError):
                    input_snapshot = {}
            team_id = str(
                (run.team_id if run is not None else "")
                or input_snapshot.get("teamId")
                or ""
            ).strip()
            source_collection_run_id = (
                str(input_snapshot.get("sourceCollectionRunId") or "").strip()
                or str(action.run_id or "").strip()
            )
            if not team_id:
                raise RuntimeError("run has no teamId for stage task reconcile")

            final_status = ""
            if session_id:
                from core.web.services.session.turn_diagnostics import (
                    get_session_turn_completion_snapshot,
                )

                snapshot = get_session_turn_completion_snapshot(session_id, turn_id)
                if bool(snapshot.get("terminal")):
                    final_status = str(snapshot.get("terminalStatus") or "").strip()
            if not final_status:
                # Wait abandoned before a terminal snapshot: fall to the
                # interrupted/block semantics instead of leaving running.
                final_status = "interrupted"

            from core.web.services.team_workflow.source_collection.stage_writeback import (
                reconcile_source_collection_stage_session_task_after_turn,
            )

            result = reconcile_source_collection_stage_session_task_after_turn(
                team_id,
                task_id,
                run_id=source_collection_run_id,
                session_id=session_id,
                turn_id=turn_id,
                final_status=final_status,
                reason="live_turn_wait_timeout",
            )
            _record_scene_event(
                "adapter_dispatch.live_turn_wait_reconciled",
                outcome="settled",
                fields={
                    **_action_identity(action),
                    "taskId": task_id,
                    "finalStatus": final_status,
                    "reconcileStatus": str(
                        (result or {}).get("status") or ""
                    )[:80],
                    "taskStatus": str(
                        (result or {}).get("taskStatus") or ""
                    )[:80],
                },
            )
        except Exception as exc:  # noqa: BLE001 - writeback repair is best-effort
            _record_scene_event(
                "adapter_dispatch.live_turn_wait_reconcile_failed",
                outcome="failed",
                fields={
                    **_action_identity(action),
                    "errorType": type(exc).__name__,
                    "error": str(exc)[:200],
                },
            )

    def _requeue_or_fail(self, outbox: Any, action: PendingAction, detail: str) -> None:
        now_ms = self._now()
        if int(getattr(outbox, "attempt_count", 0) or 0) >= self._MAX_TRANSIENT_ATTEMPTS:
            # Deterministic failures must not retry forever: surface a failed
            # attempt instead of an endless 5s live-lock with no diagnosis.
            self._fail_attempt(
                outbox,
                action,
                {"code": "transient_exhausted", "detail": str(detail)[:400]},
            )
            return
        _record_scene_event(
            "adapter_dispatch.requeued",
            outcome="requeued",
            fields={
                **_action_identity(action),
                "attemptCount": int(getattr(outbox, "attempt_count", 0) or 0),
                "detail": str(detail)[:160],
            },
        )
        outbox_api.requeue_action(
            self._store,
            outbox.action_id,
            self._owner,
            now_ms,
            retry_at_ms=now_ms + 5_000,
            problem_json=json.dumps({"code": "transient", "detail": detail}),
        )


def _turn_alive_progressing(exc: Exception) -> bool:
    """True only when the wait timed out while the turn was still running.

    Anything else (missing anchor, unknown session, ambiguous completion
    source) stays on the transient path so genuinely broken dispatches keep
    the bounded retry budget.
    """

    snapshot = dict(getattr(exc, "snapshot", None) or {})
    if not snapshot:
        return False
    if bool(snapshot.get("terminal")):
        return False
    return str(snapshot.get("completionSource") or "").strip() == "running"


def _heal_pending_action_identity(outbox: Any, action: PendingAction) -> PendingAction:
    """Ledger outbox columns are authoritative when lag-walk payload omitted runId."""
    column_run_id = str(getattr(outbox, "run_id", "") or "").strip()
    column_node_run_id = str(getattr(outbox, "node_run_id", "") or "").strip()
    payload_run_id = str(action.run_id or "").strip()
    payload_node_run_id = str(action.node_run_id or "").strip()
    run_id = payload_run_id or column_run_id
    node_run_id = payload_node_run_id
    if node_run_id.startswith("nr--") or not node_run_id:
        node_run_id = column_node_run_id
    if run_id and (node_run_id.startswith("nr--") or not node_run_id):
        node_run_id = f"nr-{run_id}-{action.node_id}-a{action.attempt}"
    if run_id == payload_run_id and node_run_id == payload_node_run_id:
        return action
    return replace(action, run_id=run_id, node_run_id=node_run_id)


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
