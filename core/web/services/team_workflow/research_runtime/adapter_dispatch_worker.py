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
from core.research.workflow.knowledge_sideflow_definition import (
    KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,
)
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
from .node_execution_support import NodeExecutionError
from .stage_one_closeout import (
    StageOneCloseoutOutcome,
    evaluate_ledger_stage_one_closeout,
)

# Adapter execution may synchronously wait for a canonical Agent turn.  The
# lease must outlive that bounded wait so another Workbench process cannot
# concurrently reclaim the same action while the first execution is live.
DEFAULT_ADAPTER_DISPATCH_LEASE_MS = 150_000


def _task_bundle_contract_deadline_at_ms(action: PendingAction) -> int | None:
    """Read the node's explicit subtask deadline contract (read-only).

    task_bundle_lifecycle owns the UTC-aware ``deadlineAt`` on the task-bundle
    subtask; this module only interprets it.  A missing/unreadable/malformed
    contract returns None so the bounded conservative default window applies --
    the fail-closed semantics never depend on this read succeeding.
    """

    from core.web.services.session.timebase import parse_timestamp_utc

    from .store import WorkflowRunStore
    from .task_bundle_lifecycle import task_bundle_id

    node_run_id = str(getattr(action, "node_run_id", "") or "").strip()
    run_id = str(getattr(action, "run_id", "") or "").strip()
    if not node_run_id or not run_id:
        return None
    try:
        record = WorkflowRunStore().get_run(run_id)
        bundle = next(
            (
                item
                for item in (record or {}).get("taskBundles") or []
                if str(item.get("bundleId") or "") == task_bundle_id(node_run_id)
            ),
            None,
        )
        if bundle is None:
            return None
        subtasks = [
            item for item in bundle.get("subtasks") or [] if isinstance(item, dict)
        ]
        selection_id = str(getattr(action, "selection_id", "") or "").strip()
        candidate_id = str(getattr(action, "candidate_id", "") or "").strip()
        subtask = None
        if selection_id and candidate_id:
            subtask = next(
                (
                    item
                    for item in subtasks
                    if str((item.get("scope") or {}).get("selectionId") or "")
                    == selection_id
                    and str((item.get("scope") or {}).get("candidateId") or "")
                    == candidate_id
                ),
                None,
            )
        if subtask is None and len(subtasks) == 1:
            subtask = subtasks[0]
        if subtask is None:
            return None
        deadline_at = parse_timestamp_utc(subtask.get("deadlineAt"))
        if deadline_at is None:
            return None
        return int(deadline_at.timestamp() * 1000)
    except Exception:  # noqa: BLE001 - contract read is advisory, default applies
        return None


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
            background_workflow_ids=(KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,),
            background_limit=2,
        )
        for action in leased:
            self._handle(action)
        return len(leased) + self.run_repairs_once()

    def run_claim_one(self) -> bool:
        """Lease exactly ONE ready adapter_dispatch action and handle it.

        Parallel pump entry point (claim-as-you-run, no prefetch): the
        outbox lease CAS shards actions between workers, so two threads
        never claim the same action, and the ack/fail commits stay fenced
        by lease owner. Returns True when an action was claimed and
        handled.
        """
        leased = outbox_api.lease_ready_actions(
            self._store,
            owner=self._owner,
            now_ms=self._now(),
            limit=1,
            lease_ms=self._lease_ms,
            action_kinds=("adapter_dispatch",),
            background_workflow_ids=(KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,),
            background_limit=2,
        )
        if not leased:
            return False
        self._handle(leased[0])
        return True

    def run_repairs_once(self, limit: int = 1) -> int:
        """Dead-letter projection sweep, for the serial maintenance loop."""
        return self._repair_terminal_failed_adapter_dispatch(limit=max(1, int(limit)))

    def _repair_terminal_failed_adapter_dispatch(self, *, limit: int = 4) -> int:
        """Project lease-gate dead letters onto their latest active attempt.

        The ledger marks an adapter row ``failed`` after repeated expired
        leases, before this worker can lease it again.  Without this sweep the
        attempt and run remain active forever even though no worker can claim
        the action.  Re-read every identity in the writer transaction so a
        newer retry or live replacement wins and receives no late side effect.
        """

        now_ms = self._now()

        def find_exhausted(uow):
            return uow.repository.execute(
                """
                SELECT o.action_id, o.payload_json, o.last_problem_json
                FROM outbox_actions o
                JOIN workflow_runs r ON r.run_id = o.run_id
                WHERE o.action_kind = 'adapter_dispatch'
                  AND o.status = 'failed'
                  AND INSTR(o.last_problem_json, 'lease_attempt_exhausted') > 0
                  AND r.status IN ('running', 'waiting_human')
                ORDER BY o.updated_at_ms ASC, o.action_id ASC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()

        rows = self._store.submit(find_exhausted, force_flush=True).result(timeout=10)
        repaired = 0
        for row in rows or ():
            action_id = str(row[0] or "")
            try:
                action = PendingAction.from_dict(json.loads(str(row[1] or "{}")))
                recorded_problem = json.loads(str(row[2] or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if (
                not isinstance(recorded_problem, dict)
                or recorded_problem.get("code") != "lease_attempt_exhausted"
            ):
                continue
            problem = dict(recorded_problem)
            problem.setdefault(
                "detail",
                "adapter dispatch lease attempts exhausted before acknowledgement",
            )
            problem["actionId"] = action.action_id

            def mutate(
                uow,
                *,
                expected_action_id=action_id,
                pending=action,
                repair_problem=problem,
            ):
                outbox = uow.repository.get_outbox(expected_action_id)
                run = uow.repository.get_run(pending.run_id)
                latest = uow.repository.latest_attempt(pending.run_id, pending.node_id)
                if outbox is None:
                    return False
                try:
                    current_problem = json.loads(str(outbox.last_problem_json or "{}"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    current_problem = {}
                if (
                    outbox.status != "failed"
                    or not isinstance(current_problem, dict)
                    or current_problem.get("code") != "lease_attempt_exhausted"
                    or run is None
                    or run.status not in {"running", "waiting_human"}
                    or latest is None
                    or latest.node_run_id != pending.node_run_id
                    or latest.status
                    not in {"starting", "dispatching", "running", "waiting_human"}
                ):
                    return False
                live = uow.repository.execute(
                    """
                    SELECT 1 FROM outbox_actions
                    WHERE node_run_id = ?
                      AND action_kind = 'adapter_dispatch'
                      AND status IN ('pending', 'leased')
                    LIMIT 1
                    """,
                    (pending.node_run_id,),
                ).fetchone()
                if live is not None:
                    return False
                self._close_execution_anchor(
                    uow,
                    action=pending,
                    status="failed",
                    problem=repair_problem,
                )
                apply_node_run_failure(
                    uow,
                    run_id=pending.run_id,
                    node_run_id=pending.node_run_id,
                    node_id=pending.node_id,
                    problem=repair_problem,
                    now_ms=now_ms,
                    actor_id=self._owner,
                    correlation_id=expected_action_id,
                )
                return True

            if self._store.submit(mutate, force_flush=True).result(timeout=30):
                _record_scene_event(
                    "adapter_dispatch.terminal_failure_reconciled",
                    outcome="blocked",
                    fields={
                        **_action_identity(action),
                        "outboxActionId": action_id,
                        "problemCode": problem["code"],
                    },
                )
                repaired += 1
        return repaired

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
            from .agent_turn_completion import (
                SourceExtractionContractViolation,
                TurnNotReadyError,
            )
            from .formal_hypothesis_fanout import HypothesisAuthorityUnavailable

            if isinstance(exc, _OutboxLeaseLost):
                return
            if isinstance(exc, ChallengeTaskDeadlineExceeded):
                failed = self._fail_attempt(outbox, action, exc.problem)
                if failed:
                    self._reconcile_stage_task_after_wait_timeout(
                        action,
                        reason=str(
                            exc.problem.get("code")
                            or "challenge_logical_task_deadline_exhausted"
                        ),
                    )
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
                if isinstance(exc, TurnNotReadyError) and _receipt_persistence_pending_terminal(exc):
                    # The turn journal is already terminal but its durable
                    # receipt never became visible (persistence may have
                    # silently failed). Waiting cannot make progress: reuse
                    # the transient budget to fail fast with a dedicated
                    # diagnosable code instead of an empty live-wait.
                    self._requeue_receipt_persistence_pending(
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
            if isinstance(exc, SourceExtractionContractViolation):
                # A fail-closed contract violation surfaced by turn
                # completion carries its own structured problem: record the
                # dedicated diagnosable code (e.g.
                # ``source_extraction_contract_violation`` with the failing
                # path) instead of the generic wrap.  The attempt still fails
                # — the exception is never swallowed.
                self._fail_attempt(outbox, action, exc.problem)
                return
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
            stage_one_closeout = evaluate_ledger_stage_one_closeout(
                self._store,
                action=action,
                current_artifact_receipts=verified.artifact_receipts,
            )
        except NodeExecutionError as exc:
            if str(exc.code or "").startswith("stage_one_"):
                _record_scene_event(
                    "stage_one_closeout.started",
                    outcome="started",
                    fields={**_action_identity(action)},
                )
                _record_scene_event(
                    "stage_one_closeout.blocked",
                    outcome="blocked",
                    fields={
                        **_action_identity(action),
                        "missingCategory": str(exc.code or "stage_one_invalid"),
                    },
                )
            self._void_unused_reservation(
                action, reason="stage_one_closeout_blocked_compensation"
            )
            self._block_attempt(outbox, action, exc.code, str(exc))
            return

        if stage_one_closeout is not None:
            _record_scene_event(
                "stage_one_closeout.started",
                outcome="started",
                fields={
                    **_action_identity(action),
                    "policySha256": stage_one_closeout.policy_sha256,
                    "artifactCount": len(stage_one_closeout.artifact_refs),
                    "receiptCount": len(stage_one_closeout.receipt_refs),
                    "humanGateCount": stage_one_closeout.human_gate_count,
                },
            )

        try:
            committed = False
            if action.actor_kind == ActorKind.HUMAN:
                committed = self._commit_human(outbox, action, verified)
            else:
                committed = self._commit_verified(
                    outbox,
                    action,
                    verified,
                    usage=result.usage,
                    stage_one_closeout=stage_one_closeout,
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
                if stage_one_closeout is not None:
                    completed = stage_one_closeout.accepted
                    _record_scene_event(
                        (
                            "stage_one_closeout.completed"
                            if completed
                            else "stage_one_closeout.blocked"
                        ),
                        outcome="completed" if completed else "blocked",
                        fields={
                            **_action_identity(action),
                            "policySha256": stage_one_closeout.policy_sha256,
                            "artifactCount": len(stage_one_closeout.artifact_refs),
                            "receiptCount": len(stage_one_closeout.receipt_refs),
                            "humanGateCount": stage_one_closeout.human_gate_count,
                            "missingCategory": (
                                "" if completed else "program_review_required"
                            ),
                            "packageSha256": (
                                stage_one_closeout.canonical_package_sha256
                            ),
                            "programOutputId": stage_one_closeout.program_record_id,
                            "programOutputSha256": (
                                stage_one_closeout.program_output_sha256
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
        contract_deadline_at_ms = (
            _task_bundle_contract_deadline_at_ms(action)
            if action.actor_kind == ActorKind.AGENT
            else None
        )
        deadline_scope = (
            challenge_task_deadline_scope(
                int(getattr(outbox, "created_at_ms", 0) or self._now()),
                resume_problem=getattr(outbox, "last_problem_json", ""),
                deadline_at_ms=contract_deadline_at_ms,
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
        self,
        outbox: Any,
        action: PendingAction,
        verified: VerifiedDomainResult,
        *,
        usage: dict[str, Any],
        stage_one_closeout: StageOneCloseoutOutcome | None = None,
    ) -> bool:
        now_ms = self._now()
        anchor_payload = _canonical_anchor_payload(action, verified.anchor)
        anchor_id = new_id("anchor") if anchor_payload else None
        budget_receipt_id = new_id("br") if verified.budget_receipt else None
        handoff_id = new_id("ho")
        event_count = 4 if stage_one_closeout is not None else 3

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
                from .budget_authority_adapter import (
                    settle_budget_authority_in_uow,
                )

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
                settle_budget_authority_in_uow(
                    uow,
                    reservation={
                        **verified.budget_receipt,
                        "reservationId": reservation_id,
                        "runId": action.run_id,
                        "nodeRunId": action.node_run_id,
                    },
                    usage=usage,
                    now_ms=now_ms,
                )

            uow.repository.update_attempt_status(
                action.node_run_id,
                NodeAttemptStatus.SUCCEEDED.value,
                now_ms,
                finished_at_ms=now_ms,
            )

            successors = self._successor_fn(action.node_id)
            if stage_one_closeout is not None:
                if uow.repository.list_pending_human_tasks(action.run_id):
                    raise RuntimeError(
                        "stage-one closeout raced with a pending human task"
                    )
                deferred = set(
                    json.loads(run.input_snapshot_json)
                    .get("stageOneCompletionPolicy", {})
                    .get("deferredNodeIds", [])
                )
                if any(
                    attempt.node_id in deferred
                    for attempt in uow.repository.list_attempts(action.run_id)
                ):
                    raise RuntimeError(
                        "stage-one closeout raced with a phase-two attempt"
                    )
                successors = ()
            branch = branch_decision_from_run(run)
            routed = (
                ()
                if stage_one_closeout is not None
                else routed_successors(action.node_id, branch)
            )
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
            if (
                successors
                or action.node_id == "result_package"
                or (
                    stage_one_closeout is not None
                    and stage_one_closeout.accepted
                )
            ):
                state_update = {"branch_decision": branch} if branch else {}
                if stage_one_closeout is not None:
                    if stage_one_closeout.accepted:
                        state_update["stage_one_completion_state"] = (
                            stage_one_closeout.completion_state
                        )
                    state_update["stage_one_closeout"] = stage_one_closeout.to_dict()
                uow.repository.insert_outbox(
                    _resume_dispatch_record(
                        run=run,
                        attempt=attempt,
                        action=action,
                        receipt=receipt,
                        command_id=outbox.command_id,
                        now_ms=now_ms,
                        state_update=state_update or None,
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
                    payload={
                        "nodeRunId": action.node_run_id,
                        "handoffId": handoff_id if successors else None,
                    },
                    now_ms=now_ms,
                )
            )
            if stage_one_closeout is not None:
                uow.repository.insert_event(
                    _event(
                        run_id=action.run_id,
                        sequence=base_sequence + 4,
                        run_version=run.run_version,
                        event_id=new_id("evt"),
                        event_type=(
                            "stage_one_closeout_completed"
                            if stage_one_closeout.accepted
                            else "stage_one_program_review_required"
                        ),
                        correlation_id=action.action_id,
                        payload={
                            "nodeRunId": action.node_run_id,
                            **stage_one_closeout.to_dict(),
                        },
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

    def _fail_attempt(self, outbox: Any, action: PendingAction, problem: dict) -> bool:
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
                return False
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
            return True

        return bool(self._store.submit(mutate, force_flush=True).result(timeout=30))

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
        contract_deadline_at_ms = _task_bundle_contract_deadline_at_ms(action)
        decision = decide_live_turn_wait(
            now_ms=now_ms,
            created_at_ms=created_at_ms,
            previous_problem=previous_problem,
            snapshot=snapshot,
            deadline_at_ms=contract_deadline_at_ms,
        )
        # The actual derived budget: contract window when present, else the
        # bounded default window from the task start.
        derived_max_wait_ms = max(
            0, int(decision.deadline_at_ms) - int(decision.started_at_ms)
        ) or self._MAX_LIVE_TURN_WAIT_MS
        continuation_chain = [
            str(item or "").strip()
            for item in list(snapshot.get("continuationTurnChain") or [])
            if str(item or "").strip()
        ]
        continuation_root_turn_id = str(
            snapshot.get("continuationRootTurnId") or ""
        ).strip()
        continuation_turn_id = str(
            snapshot.get("continuationTurnId") or ""
        ).strip()
        try:
            continuations_used = max(
                0,
                int(snapshot.get("continuationsUsed") or 0),
            )
        except (TypeError, ValueError):
            continuations_used = 0
        try:
            continuation_no_progress_count = max(
                0,
                int(snapshot.get("continuationNoProgressCount") or 0),
            )
        except (TypeError, ValueError):
            continuation_no_progress_count = 0
        continuation_problem = {}
        if (
            continuation_root_turn_id
            and continuation_turn_id
            and continuations_used > 0
            and len(continuation_chain) == continuations_used + 1
            and continuation_chain[0] == continuation_root_turn_id
            and continuation_chain[-1] == continuation_turn_id
        ):
            continuation_problem = {
                "continuationRootTurnId": continuation_root_turn_id,
                "continuationTurnId": continuation_turn_id,
                "continuationTurnChain": continuation_chain,
                "continuationsUsed": continuations_used,
                "continuationNoProgressCount": continuation_no_progress_count,
            }
        if created_at_ms and decision.should_stop:
            failed = self._fail_attempt(
                outbox,
                action,
                {
                    "code": decision.stop_code,
                    "detail": str(detail)[:400],
                    "waitedMs": decision.waited_ms,
                    "maxWaitMs": derived_max_wait_ms,
                    "noProgressMs": decision.no_progress_ms,
                    "maxNoProgressMs": self._MAX_LIVE_TURN_NO_PROGRESS_MS,
                    "logicalTaskStartedAtMs": decision.started_at_ms,
                    "deadlineAtMs": decision.deadline_at_ms,
                    "deadlineSource": decision.deadline_source,
                    **continuation_problem,
                },
            )
            # The abandoned wait previously skipped the domain-task terminal
            # leg, so its task stayed "running" while the Ledger attempt was
            # already failed. Best-effort reconcile closes that state fork;
            # it must never break the dispatch path.
            if failed:
                self._reconcile_stage_task_after_wait_timeout(
                    action,
                    reason=decision.stop_code,
                )
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
            max_wait_ms=derived_max_wait_ms,
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
                    "maxWaitMs": derived_max_wait_ms,
                    "noProgressMs": decision.no_progress_ms,
                    "maxNoProgressMs": self._MAX_LIVE_TURN_NO_PROGRESS_MS,
                    "logicalTaskStartedAtMs": decision.started_at_ms,
                    "deadlineAtMs": decision.deadline_at_ms,
                    "deadlineSource": decision.deadline_source,
                    "lastProgressAtMs": decision.last_progress_at_ms,
                    "progressFingerprint": decision.progress_fingerprint,
                    **continuation_problem,
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
        max_wait_ms: int | None = None,
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
            "maxWaitMs": int(max_wait_ms or self._MAX_LIVE_TURN_WAIT_MS),
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

    def _reconcile_stage_task_after_wait_timeout(
        self,
        action: PendingAction,
        *,
        reason: str = "live_turn_wait_timeout",
    ) -> None:
        """Close the domain-task writeback window an abandoned live wait left open.

        After the wall-clock cap fails the attempt, the canonical Agent turn may
        still be running (or may have finished unnoticed). Source-collection
        tasks settle through their existing stage writeback reconciler.
        Research-project tasks first run their explicit session reconciler; if
        the task is still active after the workflow deadline, the trusted
        task-status API records ``timed_out``. Idempotent and best-effort: any
        failure is logged and never blocks the dispatch path.
        """
        try:
            from .task_adapter_registry import resolve_agent_task_adapter

            adapter_spec = resolve_agent_task_adapter(action.node_id)
            if adapter_spec is None or adapter_spec.family not in {
                "source_collection",
                "research_project",
            }:
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
                raise RuntimeError("run has no teamId for domain task reconcile")

            normalized_reason = str(reason or "live_turn_wait_timeout").strip()[:120]
            if adapter_spec.family == "research_project":
                project_id = str(
                    (run.project_id if run is not None else "")
                    or input_snapshot.get("projectId")
                    or input_snapshot.get("researchProjectId")
                    or ""
                ).strip()
                if not project_id:
                    raise RuntimeError("run has no projectId for project task reconcile")
                from core.web.services.team_workflow.research_project_agent_tasks import (
                    ACTIVE_STATUSES,
                    _read_research_project_agent_task_record,
                    reconcile_research_project_agent_task_statuses,
                    update_research_project_agent_task_status,
                )

                reconcile_research_project_agent_task_statuses(team_id, project_id)
                task = _read_research_project_agent_task_record(
                    team_id,
                    project_id,
                    task_id,
                )
                if task is None:
                    raise RuntimeError("project Agent task is missing during timeout reconcile")
                task_status = str(task.get("status") or "").strip().lower()
                if task_status in ACTIVE_STATUSES:
                    result = update_research_project_agent_task_status(
                        team_id,
                        project_id,
                        task_id,
                        status="timed_out",
                        result_refs=list(task.get("resultRefs") or []),
                        failure_code=normalized_reason,
                    )
                    task_status = str((result or {}).get("status") or "timed_out")
                _record_scene_event(
                    "adapter_dispatch.live_turn_wait_reconciled",
                    outcome="settled",
                    fields={
                        **_action_identity(action),
                        "taskId": task_id,
                        "projectId": project_id,
                        "taskStatus": task_status,
                        "reason": normalized_reason,
                    },
                )
                return

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
                reason=normalized_reason,
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

    def _requeue_receipt_persistence_pending(
        self,
        outbox: Any,
        action: PendingAction,
        detail: str,
        *,
        snapshot: dict[str, Any] | None = None,
    ) -> None:
        """Bounded fast-fail for a terminal turn whose receipt stays pending.

        Same transient budget semantics as `_requeue_or_fail` — a slow receipt
        worker still gets its bounded 5s retries — but once the budget is
        exhausted the attempt fails with the dedicated
        ``receipt_persistence_pending_terminal`` code instead of a generic
        transient error after a fruitless 10-minute live wait.
        """

        now_ms = self._now()
        if int(getattr(outbox, "attempt_count", 0) or 0) >= self._MAX_TRANSIENT_ATTEMPTS:
            self._fail_attempt(
                outbox,
                action,
                {
                    "code": "receipt_persistence_pending_terminal",
                    "detail": str(detail)[:400],
                    "turnTerminalStatus": str(
                        (dict(snapshot or {}).get("turnTerminalStatus") or "")
                    )[:80],
                },
            )
            return
        _record_scene_event(
            "adapter_dispatch.requeued_receipt_persistence_pending",
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
            problem_json=json.dumps(
                {"code": "receipt_persistence_pending", "detail": str(detail)[:400]}
            ),
        )


def _receipt_persistence_pending_terminal(exc: Exception) -> bool:
    """True when the turn journal is terminal but its durable receipt never
    became visible.

    ``_require_formal_model_invocation_receipt`` overrides the raised snapshot
    with ``terminal=False``/``completionSource=receipt_registry_pending`` even
    when the underlying turn journal already reached a terminal state. If the
    receipt registry never materializes (e.g. persistence silently failed),
    waiting cannot make progress and the node must fail fast instead of
    empty-waiting out the live-turn window.
    """

    snapshot = dict(getattr(exc, "snapshot", None) or {})
    if str(snapshot.get("completionSource") or "").strip() != "receipt_registry_pending":
        return False
    return bool(snapshot.get("turnTerminal"))


def _turn_alive_progressing(exc: Exception) -> bool:
    """True while the logical task has a healthy, bounded wait authority.

    A terminal turn whose durable receipt projection is pending remains live
    work too: re-running its idempotent task must wait for the receipt worker,
    not consume the five-attempt transient budget or rerun the LLM. That only
    holds while the turn itself is still running; a turn that is already
    terminal at the journal level with a still-pending receipt must not keep
    the live wait alive forever.
    """

    if _receipt_persistence_pending_terminal(exc):
        return False
    snapshot = dict(getattr(exc, "snapshot", None) or {})
    if not snapshot:
        return False
    if bool(snapshot.get("terminal")):
        return False
    return str(snapshot.get("completionSource") or "").strip() in {
        "running",
        "receipt_registry_pending",
    }


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
