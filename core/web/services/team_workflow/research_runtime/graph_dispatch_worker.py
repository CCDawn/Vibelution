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
from collections.abc import Callable, Mapping
from typing import Any

from core.logging import debug
from core.research.workflow.challenge_cup_runtime import (
    ChallengeCupGraphCoordinator,
    GraphDispatch,
    GraphDispatchResult,
    PendingAction,
    action_id_for,
    build_pending_action,
    successor_map,
)
from core.research.workflow.contracts import ExecutionReceipt
from core.research.workflow.knowledge_sideflow_definition import (
    KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,
)
from core.research.workflow.ledger import WorkflowLedgerStore
from core.research.workflow.ledger import outbox as outbox_api
from core.research.workflow.transitions import (
    NodeAttemptStatus,
    can_transition_node_attempt,
)

from .block_projection import (
    apply_node_run_block,
    mark_run_reconciliation_required,
    sync_run_blocked,
    sync_run_succeeded,
    terminal_facts_for_run,
)
from .blocked_reason import format_blocked_reason, problem_from_graph_error
from .ids import new_id
from .iteration_route import branch_decision_from_run, routed_successors
from .stage_one_closeout import stage_one_terminal_facts

# A run is created before START_NODE is accepted so the request can be made
# idempotent.  That window must nevertheless be bounded: after this deadline
# a run with no durable node attempt is a failed dispatch, not an indefinitely
# pending job.  Command/outbox rows alone do not prove that dispatch started.
DEFAULT_START_DEADLINE_MS = 60_000
DEFAULT_KNOWLEDGE_BACKGROUND_LIVE_LIMIT = 2


def _record_scene_event(event_code: str, *, outcome: str, fields: dict[str, Any]) -> None:
    """Best-effort worker observability; never breaks the dispatch path."""
    from core.web.services.runtime_scene_service import (
        record_runtime_scene_event_quietly,
    )

    record_runtime_scene_event_quietly(
        "team_workflow_orchestration",
        "graph_dispatch_worker",
        event_code,
        level="info"
        if outcome in {"committed", "settled", "deferred", "recovered"}
        else "warning",
        outcome=outcome,
        fields=fields,
    )


def _is_hypothesis_first_prelude(run: Any) -> bool:
    """Return whether a created run legitimately awaits hypothesis review."""

    try:
        snapshot = json.loads(str(getattr(run, "input_snapshot_json", "") or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(snapshot, Mapping):
        return False
    objective = snapshot.get("researchObjectiveContract")
    return isinstance(objective, Mapping) and objective.get("hypothesisFirst") is True


def _record_repair_skip(run_id: str, stage: str, exc: BaseException) -> None:
    """Surface a skipped repair step with a structured signal, never silently.

    A skipped repair is not swallowed: the debug line keeps the old log
    shape, and the scene event carries run/stage/cause so operators can
    attribute why a stranded run was left untouched.
    """
    debug.warning(
        f"graph repair skipped run={run_id} stage={stage} "
        f"error={type(exc).__name__}: {exc}"
    )
    _record_scene_event(
        "graph_dispatch.repair_skipped",
        outcome="repair_skipped",
        fields={
            "runId": run_id,
            "stage": stage,
            "errorType": type(exc).__name__,
            "detail": str(exc)[:200],
        },
    )


class GraphDecisionError(RuntimeError):
    """An iteration decision the graph cannot route (run must block)."""


class GraphRecoverStepError(RuntimeError):
    """A named heal step failed; the whole recovery aborts with that name.

    The SCI-096 heal chain used to swallow exceptions (``except Exception:
    pass``) and fall through to later fallback layers, so a half-applied
    heal only surfaced later as an aggregated decision error and operators
    could not tell which layer corrupted the checkpoint.  The rebuild and
    resume steps now raise this error with the step name and the original
    exception chain, and no blind fallback layer runs after them.  The only
    designed handoff left is a failed ``resume_live_interrupt`` degrading to
    ``rebuild_interrupt`` (goto-split shapes); that handoff emits a
    structured ``heal_step_degraded`` signal instead of staying silent.
    """

    def __init__(
        self, step: str, run_id: str, node_id: str, exc: BaseException
    ) -> None:
        self.step = step
        self.code = "graph_recover_step_failed"
        self.problem = {
            "code": self.code,
            "detail": (
                f"graph heal step '{step}' failed for run={run_id} "
                f"node={node_id}: {type(exc).__name__}: {exc}"
            ),
        }
        super().__init__(self.problem["detail"])


class GraphDispatchWorker:
    def __init__(
        self,
        *,
        store: WorkflowLedgerStore,
        coordinator: ChallengeCupGraphCoordinator,
        owner_id: str = "graph-worker",
        lease_ms: int = 30_000,
        start_deadline_ms: int = DEFAULT_START_DEADLINE_MS,
        created_start_deadline_ms: int | None = None,
        now_provider: Callable[[], int] | None = None,
        readiness_service: Any | None = None,
        readiness_context: Callable[[], Any] | None = None,
        commit_hook: Callable[[], None] | None = None,
        node_success_hook: Callable[..., Any] | None = None,
    ) -> None:
        self._store = store
        self._coordinator = coordinator
        self._owner = owner_id
        self._lease_ms = lease_ms
        # ``created_start_deadline_ms`` is an explicit compatibility alias for
        # callers that name the state being reconciled.  Both values are kept
        # local to the worker; no path or global clock is assumed.
        deadline = (
            created_start_deadline_ms
            if created_start_deadline_ms is not None
            else start_deadline_ms
        )
        self._start_deadline_ms = max(0, int(deadline))
        self._now = now_provider or (lambda: int(time.time() * 1000))
        self._readiness = readiness_service
        self._readiness_context = readiness_context
        self._commit_hook = commit_hook
        self._node_success_hook = node_success_hook

    def _submit(self, mutate, *, force_flush: bool = True):
        hook = self._commit_hook

        def wrapped(uow):
            if hook is not None:
                uow.after_commit(hook)
            return mutate(uow)

        return self._store.submit(wrapped, force_flush=force_flush)

    def run_once(self, limit: int = 8) -> int:
        # Retained sweeps, each with the failure it defends against (every
        # action emits a structured scene event so repairs stay auditable):
        # - created_without_start / terminal_failed_dispatch: dead-letter
        #   crash recovery with no other observer (no live dispatch exists).
        # - dispatching_without_adapter / starting_without_progress: commit
        #   gaps left by a process crash; a crash emits no failure event, so
        #   there is nothing to hook a trigger onto.
        # - stranded_terminal_package: terminal-fact alignment for rows whose
        #   dispatch chain is already gone; no live signal can fire for them.
        # The state-rewriting iteration-route repair is deliberately NOT on
        # this cycle: its only observable signal is a failed
        # iteration_decision dispatch, which triggers
        # _repair_stranded_iteration_route_after_failure directly.
        # Terminalize stale created runs before leasing their dispatch actions.
        # Otherwise this worker could lease an action for a run that the same
        # reconciliation pass is supposed to dead-letter.
        repaired = self._repair_created_without_start()
        leased = outbox_api.lease_ready_actions(
            self._store,
            owner=self._owner,
            now_ms=self._now(),
            limit=limit,
            lease_ms=self._lease_ms,
            action_kinds=("graph_dispatch",),
            background_workflow_ids=(KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,),
            background_limit=DEFAULT_KNOWLEDGE_BACKGROUND_LIVE_LIMIT,
        )
        for action in leased:
            self._handle(action)
        repaired += self._repair_dispatching_without_adapter()
        repaired += self._repair_starting_without_progress()
        repaired += self._repair_stranded_terminal_package()
        repaired += self._repair_terminal_failed_dispatch()
        return len(leased) + repaired

    def _repair_created_without_start(self) -> int:
        """Fail runs that were created but never accepted by START_NODE.

        ``run_created`` is intentionally committed before command acceptance,
        so a process crash can leave a perfectly valid ``created`` row.  The
        only evidence that a run actually started is a durable node attempt;
        command rows and graph-dispatch outbox rows can be stale, partially
        committed, or replayable and therefore do not extend the deadline.
        Hypothesis-first parent runs are a deliberate exception: their
        prelude awaits candidate review and later submits the formal start
        through its existing command path. Everything else past the deadline
        is closed atomically with a deterministic ``run_failed`` event and any
        still-live graph dispatch is cancelled in the same transaction.
        """
        now_ms = self._now()
        cutoff_ms = now_ms - self._start_deadline_ms

        def mutate(uow):
            def cancel_live_dispatch(run_id: str, reason: str) -> None:
                uow.repository.execute(
                    """
                    UPDATE outbox_actions
                    SET status = 'cancelled',
                        lease_owner = NULL,
                        lease_expires_at_ms = NULL,
                        last_problem_json = ?,
                        updated_at_ms = ?
                    WHERE run_id = ?
                      AND action_kind = 'graph_dispatch'
                      AND status IN ('pending', 'leased')
                    """,
                    (
                        json.dumps(
                            {
                                "code": "dispatch_never_started",
                                "reason": reason,
                                "reconciliation": "created_without_start",
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        now_ms,
                        run_id,
                    ),
                )

            rows = uow.repository.execute(
                """
                SELECT run_id, team_id, run_version
                FROM workflow_runs
                WHERE status = 'created' AND created_at_ms <= ?
                ORDER BY created_at_ms ASC, run_id ASC
                """,
                (cutoff_ms,),
            ).fetchall()
            repaired_runs: list[str] = []
            for row in rows:
                run_id = str(row[0] or "")
                team_id = str(row[1] or "")
                if not run_id or not team_id:
                    continue
                # A node attempt is the durable proof that dispatch started.
                # Do not treat command acceptance or an outbox row as proof:
                # either can survive a crash before the worker begins work.
                attempt = uow.repository.execute(
                    "SELECT 1 FROM node_attempts WHERE run_id = ? LIMIT 1",
                    (run_id,),
                ).fetchone()
                if attempt is not None:
                    continue
                run = uow.repository.get_run(run_id)
                if run is None or run.status != "created":
                    continue
                if _is_hypothesis_first_prelude(run):
                    continue
                event_id = f"evt-dispatch-never-started-{run_id}"
                event_payload = {
                    "terminalReason": "dispatch_never_started",
                    "reason": (
                        "created run exceeded START_NODE deadline without an attempt"
                    ),
                    "reconciliation": "created_without_start",
                }
                latest_sequence = uow.repository.latest_event_sequence(run_id)
                if latest_sequence != run.last_event_sequence:
                    raise RuntimeError(
                        "created-run reconciliation sequence conflict for "
                        f"{run_id}: run expects {run.last_event_sequence}, "
                        f"ledger has {latest_sequence}"
                    )
                # A prior attempt may have committed the deterministic event
                # before a process stopped.  Reconcile the row without
                # advancing its sequence a second time; otherwise an old
                # partial repair would create a sequence hole.
                existing_event = uow.repository.get_event_by_id(event_id)
                if existing_event is not None:
                    expected_event = _event_record_for(
                        run_id=run_id,
                        sequence=run.last_event_sequence,
                        run_version=run.run_version,
                        event_id=event_id,
                        event_type="run_failed",
                        correlation_id=run_id,
                        payload=event_payload,
                        now_ms=now_ms,
                    )
                    exact_replay = _event_replay_identity(
                        existing_event
                    ) == _event_replay_identity(expected_event)
                    legacy_replay = _is_legacy_graph_repair_replay(
                        existing_event,
                        run_id=run_id,
                        sequence=run.last_event_sequence,
                        run_version=run.run_version,
                        event_id=event_id,
                    )
                    if not exact_replay and not legacy_replay:
                        raise RuntimeError(
                            "created-run reconciliation event ID conflict for "
                            f"{event_id}: conflicts with dispatch_never_started"
                        )
                    if not uow.repository.update_run_status(
                        run_id,
                        team_id,
                        "failed",
                        now_ms,
                        active_node_id="",
                        completion_kind=None,
                        terminal_reason="dispatch_never_started",
                        blocked_problem_json=None,
                    ):
                        continue
                    cancel_live_dispatch(run_id, event_payload["reason"])
                    repaired_runs.append(run_id)
                    continue
                expected_sequence = run.last_event_sequence + 1
                if not uow.repository.update_run_status(
                    run_id,
                    team_id,
                    "failed",
                    now_ms,
                    active_node_id="",
                    completion_kind=None,
                    terminal_reason="dispatch_never_started",
                    blocked_problem_json=None,
                ):
                    continue
                cancel_live_dispatch(run_id, event_payload["reason"])
                sequence = uow.repository.advance_last_sequence(run_id, 1, now_ms)
                if sequence is None:
                    raise RuntimeError(
                        f"created-run reconciliation lost run {run_id} while advancing the event sequence"
                    )
                if sequence != expected_sequence:
                    raise RuntimeError(
                        "created-run reconciliation sequence conflict for "
                        f"{run_id}: expected {expected_sequence}, got {sequence}"
                    )
                # The status transition and event are one transaction.  A
                # duplicate event is allowed to raise and roll back the whole
                # mutation rather than committing a status/sequence mismatch.
                uow.repository.insert_event(
                    _event_record_for(
                        run_id=run_id,
                        sequence=sequence,
                        run_version=int(row[2] or 1),
                        event_id=event_id,
                        event_type="run_failed",
                        correlation_id=run_id,
                        payload=event_payload,
                        now_ms=now_ms,
                    )
                )
                repaired_runs.append(run_id)
            return repaired_runs

        dead_lettered = list(
            self._submit(mutate, force_flush=True).result(timeout=30) or ()
        )
        for dead_run_id in dead_lettered:
            _record_scene_event(
                "graph_dispatch.created_run_deadlettered",
                outcome="recovered",
                fields={
                    "runId": dead_run_id,
                    "terminalReason": "dispatch_never_started",
                    "sweep": "created_without_start",
                },
            )
        return len(dead_lettered)

    def _handle(self, action: Any) -> None:
        payload = json.loads(action.payload_json)
        dispatch = GraphDispatch.from_payload(payload)
        from .challenge_cup_maintenance_fence import (
            ChallengeCupMaintenanceError,
            assert_writes_allowed,
        )

        # A graph dispatch accepted before the fence belongs to the drain set;
        # a dispatch created afterwards is deferred without invoking the graph
        # or mutating its node attempt.
        try:
            assert_writes_allowed(
                dispatch.team_id,
                operation="workflow_dispatch",
                created_at_ms=getattr(action, "created_at_ms", None),
            )
        except ChallengeCupMaintenanceError as exc:
            self._defer_for_maintenance(action, dispatch, str(exc))
            return
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
            self._repair_stranded_iteration_route_after_failure(dispatch)
            return
        except GraphRecoverStepError as exc:
            self._mark_blocked(action, dispatch, str(exc), problem=exc.problem)
            self._repair_stranded_iteration_route_after_failure(dispatch)
            return
        except Exception as exc:
            if _is_deterministic_resume_error(exc):
                # Deterministic: retrying the same receipt against the same
                # checkpoint can never succeed (SCI-096 style ledger/checkpoint
                # drift, or an ambiguous multi-interrupt checkpoint).  Skip the
                # transient budget and surface the diagnosis immediately instead
                # of live-looping five identical attempts.
                self._mark_blocked(action, dispatch, str(exc))
                self._repair_stranded_iteration_route_after_failure(dispatch)
                return
            self._requeue_or_fail(action, dispatch, str(exc))
            return

        pending = result.pending_action
        if (
            dispatch.dispatch_kind == "start"
            and pending is not None
            and pending.node_id != dispatch.node_id
        ):
            self._mark_blocked(
                action,
                dispatch,
                f"thread 中断于 {pending.node_id}，但 dispatch 目标是 {dispatch.node_id}",
            )
            return
        if (
            dispatch.dispatch_kind == "start"
            and pending is None
            and not result.completed
        ):
            self._mark_blocked(
                action,
                dispatch,
                f"thread 中断于 {dispatch.node_id} 之外，graph_dispatch 没有 pending action",
            )
            return

        # T5.1-4: commit upstream success + Handoff accepted FIRST so successor
        # readiness observes accepted handoffs. Domain readiness stays outside
        # the writer transaction.
        needs_successor = False
        if pending is not None:
            latest = self._store.latest_attempt(dispatch.run_id, pending.node_id)
            needs_successor = latest is None or latest.attempt != pending.attempt
            pending = self._pending_with_node_binding(pending)

        if pending is not None and needs_successor:
            # The graph may have been entered by a pre-fence action, but its
            # successor is a new dispatch and must not be created during the
            # reset drain.
            try:
                assert_writes_allowed(
                    dispatch.team_id,
                    operation="workflow_dispatch_successor",
                )
            except ChallengeCupMaintenanceError as exc:
                self._defer_for_maintenance(action, dispatch, str(exc))
                return

        if (
            dispatch.dispatch_kind in ("resume_action", "resume_human")
            and dispatch.receipt is not None
            and dispatch.receipt.outcome == "succeeded"
            and needs_successor
        ):
            if not self._commit_upstream_accept(action, dispatch, result):
                return
            readiness_hint = self._precheck_readiness(dispatch, pending)
            try:
                self._commit_successor_dispatch(
                    dispatch, result, pending, readiness_hint, action=action
                )
            except Exception as exc:
                self._requeue_or_fail(action, dispatch, f"successor_commit_failed:{exc}")
                raise
            self._notify_node_succeeded(dispatch)
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
        attempt = self._submit(
            lambda uow: uow.repository.get_attempt(dispatch.node_run_id),
            force_flush=True,
        ).result(timeout=10)
        if attempt is None or attempt.status != NodeAttemptStatus.SUCCEEDED.value:
            return False
        handoff = self._submit(
            lambda uow: uow.repository.get_handoff_by_from_node(
                dispatch.run_id, dispatch.node_run_id
            ),
            force_flush=True,
        ).result(timeout=10)
        if handoff is None or str(handoff[8]) != "accepted":
            return False
        successors = successor_map(dispatch.workflow_version_id).get(dispatch.node_id, ())
        run = self._store.get_run(dispatch.run_id)
        branch = branch_decision_from_run(run)
        routed = routed_successors(dispatch.node_id, branch)
        if routed:
            successors = routed
        elif dispatch.node_id in {"iteration_decision", "version_governance"}:
            successors = ()
        if not successors:
            # Terminal node (result_package / sideflow knowledge_handoff):
            # ack and close the run.
            now_ms = self._now()
            run = self._store.get_run(dispatch.run_id)

            def ack_only(uow):
                acked = uow.repository.ack_outbox(
                    action.action_id, self._owner, now_ms
                )
                if not acked:
                    return
                if run is None:
                    return
                if not _run_terminal_close_applies(run, dispatch.node_id):
                    return
                completion_kind, terminal_reason = _terminal_facts_for_close(run)
                sync_run_succeeded(
                    uow,
                    run_id=dispatch.run_id,
                    now_ms=now_ms,
                    completion_kind=completion_kind,
                    terminal_reason=terminal_reason,
                    node_id=dispatch.node_id,
                    actor_id=self._owner,
                )
                _sideflow_child_succeeded(uow, run_id=dispatch.run_id, now_ms=now_ms)

            self._submit(ack_only, force_flush=True).result(timeout=30)
            self._notify_node_succeeded(dispatch)
            return True
        successor_id = successors[0]
        snapshot = self._coordinator.snapshot(dispatch.run_id, dispatch.workflow_version_id)
        if not _graph_at_node(snapshot, successor_id):
            # Ledger advanced (handoff accepted) but LangGraph is still at the
            # predecessor interrupt — resume instead of forging a successor.
            return False
        latest = self._store.latest_attempt(dispatch.run_id, successor_id)
        if latest is not None:
            # Successor already present — ack and stop.
            now_ms = self._now()

            def ack_only(uow):
                if not uow.repository.ack_outbox(
                    action.action_id, self._owner, now_ms
                ):
                    return

            self._submit(ack_only, force_flush=True).result(timeout=30)
            self._notify_node_succeeded(dispatch)
            return True

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
            self._requeue_or_fail(action, dispatch, f"successor_commit_failed:{exc}")
            raise
        self._notify_node_succeeded(dispatch)
        return True

    def _pending_with_node_binding(
        self, pending: Any, *, run: Any | None = None
    ) -> Any:
        """Restore frozen node binding and budget authority onto PendingAction."""
        from dataclasses import replace

        from .graph_dispatch_factory import (
            binding_snapshot_id_for_node,
            budget_policy_hash_from_input_snapshot,
        )

        run = run or self._store.get_run(pending.run_id)
        if run is None or not run.input_snapshot_json:
            return pending
        try:
            input_snapshot = json.loads(run.input_snapshot_json)
        except (TypeError, ValueError):
            return pending
        if not isinstance(input_snapshot, dict):
            return pending
        snap_id = binding_snapshot_id_for_node(input_snapshot, pending.node_id)
        budget_policy_hash = budget_policy_hash_from_input_snapshot(input_snapshot)
        resolved_budget_policy_hash = (
            budget_policy_hash or pending.budget_policy_hash
        )
        if (
            snap_id == pending.binding_snapshot_id
            and resolved_budget_policy_hash == pending.budget_policy_hash
        ):
            return pending
        return replace(
            pending,
            binding_snapshot_id=snap_id,
            budget_policy_hash=resolved_budget_policy_hash,
        )

    def _commit_upstream_accept(
        self,
        action: Any,
        dispatch: GraphDispatch,
        result: GraphDispatchResult,
    ) -> bool:
        """Mark attempt succeeded and accept handoff BEFORE successor readiness.

        Intentionally does NOT ack the graph outbox yet: if successor commit
        crashes, lease expiry / requeue can recover without a half-advance.
        Renewing the current lease is the transaction's fencing CAS: a stale
        worker must not mutate the attempt or handoff after another owner has
        reclaimed the graph action.
        """
        _ = result
        now_ms = self._now()

        def mutate(uow):
            if not uow.repository.renew_outbox_lease(
                action.action_id,
                self._owner,
                now_ms,
                self._lease_ms,
            ):
                return False
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
                return True
            status = str(handoff[8] or "")
            if status == "accepted":
                return True
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
            return True

        return bool(self._submit(mutate, force_flush=True).result(timeout=30))

    def _commit_successor_dispatch(
        self,
        dispatch: GraphDispatch,
        result: GraphDispatchResult,
        pending: Any,
        readiness_hint: tuple[bool, list[Any]] | None,
        *,
        action: Any | None = None,
        fallback_command_id: str | None = None,
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
                    _ensure_adapter_dispatch(
                        uow,
                        pending=pending,
                        run_id=dispatch.run_id,
                        command_id=(
                            (action.command_id if action is not None else None)
                            or latest.command_id
                        ),
                        node_run_id=latest.node_run_id,
                        now_ms=now_ms,
                    )
                return
            if readiness_hint is None:
                ready, blockers = True, []
            else:
                ready, blockers = readiness_hint
            command_id = (
                (action.command_id if action is not None else None)
                or getattr(dispatch, "command_id", None)
                or fallback_command_id
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
                problem = {
                    "code": "auto_advance_not_ready",
                    "detail": "; ".join(str(b.get("code") or b) for b in blockers),
                }
                sync_run_blocked(
                    uow,
                    run_id=dispatch.run_id,
                    node_id=pending.node_id,
                    problem=problem,
                    now_ms=now_ms,
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
                                "code": problem["code"],
                                "detail": problem["detail"],
                                "reason": format_blocked_reason(problem),
                                "blockers": [
                                    str(b.get("code") or b) for b in blockers
                                ],
                            },
                            now_ms=now_ms,
                        )
                    )
                return
            created = _attempt_for_pending(
                pending,
                command_id=command_id,
                now_ms=now_ms,
            )
            uow.repository.insert_attempt(created)
            _ensure_adapter_dispatch(
                uow,
                pending=pending,
                run_id=dispatch.run_id,
                command_id=command_id,
                node_run_id=created.node_run_id,
                now_ms=now_ms,
            )
            _ = result

        self._submit(mutate, force_flush=True).result(timeout=30)
        if result.completed:
            outcome = (
                dispatch.receipt.outcome
                if dispatch.receipt is not None
                else "succeeded"
            )
            if outcome == "succeeded":
                self._notify_node_succeeded(dispatch)

    def _notify_node_succeeded(self, dispatch: GraphDispatch) -> None:
        hook = self._node_success_hook
        if hook is None:
            return
        try:
            hook(
                run_id=dispatch.run_id,
                node_id=dispatch.node_id,
                node_run_id=dispatch.node_run_id,
            )
        except Exception as exc:  # post-commit sideflow cannot fail the main run
            _record_scene_event(
                "graph_dispatch.node_success_hook_failed",
                outcome="failed",
                fields={
                    "runId": dispatch.run_id,
                    "nodeId": dispatch.node_id,
                    "nodeRunId": dispatch.node_run_id,
                    "errorType": type(exc).__name__,
                },
            )

    def _defer_for_maintenance(
        self, action: Any, dispatch: GraphDispatch, detail: str
    ) -> None:
        """Leave a leased dispatch pending while a governed reset drains.

        This is intentionally not ``_mark_blocked``: the maintenance fence
        must not turn an already-running research object into a failed run.
        The next worker pass can resume it after the fence is released.
        """

        now_ms = self._now()
        # A process can die between the guard and this requeue.  Re-checking
        # the fence here turns an expired/orphaned marker into an immediate
        # retry instead of another fixed 60-second defer.  Unknown/corrupt
        # state remains fail-closed and keeps the bounded maintenance delay.
        from .challenge_cup_maintenance_fence import inspect_fence

        fence_status = "unknown"
        retry_at_ms = now_ms + 60_000
        try:
            fence_state = inspect_fence(
                str(dispatch.team_id or ""),
                now_ms=now_ms,
            )
            fence_status = str(fence_state.get("status") or "unknown")
            if fence_state.get("activeFence") is None and fence_status in {
                "absent",
                "expired",
                "orphaned",
            }:
                retry_at_ms = now_ms
                _record_scene_event(
                    "graph_dispatch.maintenance_recovered",
                    outcome="recovered",
                    fields={
                        "teamId": str(dispatch.team_id or ""),
                        "runId": str(dispatch.run_id or ""),
                        "nodeId": str(dispatch.node_id or ""),
                        "actionId": str(getattr(action, "action_id", "") or ""),
                        "fenceStatus": fence_status,
                    },
                )
        except Exception as exc:
            # The original maintenance error is the useful user-facing
            # problem.  Keep this diagnostic probe best-effort so a corrupt
            # marker cannot accidentally turn the write guard fail-open.
            fence_status = (
                "corrupt"
                if getattr(exc, "code", "") == "challenge_cup_maintenance_corrupt"
                else "unknown"
            )
        _record_scene_event(
            "graph_dispatch.deferred",
            outcome="deferred",
            fields={
                "teamId": str(dispatch.team_id or ""),
                "runId": str(dispatch.run_id or ""),
                "nodeId": str(dispatch.node_id or ""),
                "actionId": str(getattr(action, "action_id", "") or ""),
                "fenceStatus": fence_status,
                "retryAtMs": retry_at_ms,
                "detail": str(detail or ""),
            },
        )
        outbox_api.requeue_action(
            self._store,
            action.action_id,
            self._owner,
            now_ms,
            retry_at_ms=retry_at_ms,
            problem_json=json.dumps(
                {
                    "code": "challenge_cup_maintenance_active",
                    "detail": "workflow dispatch deferred by Challenge Cup maintenance",
                    "reason": str(detail or ""),
                    "fenceStatus": fence_status,
                },
                ensure_ascii=False,
            ),
        )

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
        _record_scene_event(
            "graph_dispatch.attempt_terminal",
            outcome=str(outcome),
            fields={
                "teamId": str(dispatch.team_id or ""),
                "runId": str(dispatch.run_id or ""),
                "nodeId": str(dispatch.node_id or ""),
                "dispatchKind": str(dispatch.dispatch_kind or ""),
                "receiptOutcome": str(outcome),
            },
        )
        target_status = {
            "failed": NodeAttemptStatus.FAILED.value,
            "blocked": NodeAttemptStatus.BLOCKED.value,
            "cancelled": NodeAttemptStatus.CANCELLED.value,
        }.get(outcome, NodeAttemptStatus.FAILED.value)

        def mutate(uow):
            acked = uow.repository.ack_outbox(action.action_id, self._owner, now_ms)
            if not acked:
                return
            uow.repository.update_attempt_status(
                dispatch.node_run_id,
                target_status,
                now_ms,
                finished_at_ms=now_ms,
            )
            # attempt 已终态：其待执行的 adapter_dispatch 不得再运行
            # （retry 会以新 attempt 重新发起，旧的 adapter 任务必须取消）。
            uow.repository.cancel_outbox_by_node_run(dispatch.node_run_id, now_ms)
            _sideflow_child_failed(
                uow,
                run_id=dispatch.run_id,
                outcome=outcome,
                now_ms=now_ms,
            )

        self._submit(mutate, force_flush=True).result(timeout=30)

    def _start_or_recover(self, dispatch: GraphDispatch) -> GraphDispatchResult:
        snapshot = self._coordinator.snapshot(dispatch.run_id, dispatch.workflow_version_id)
        values = snapshot.get("values") or {}
        persisted_pending = snapshot.get("pendingAction") or {}
        node_id = str(
            persisted_pending.get("nodeId") or values.get("active_node_id") or ""
        )
        next_node_ids = snapshot.get("nextNodeIds") or []
        state_attempt = int(
            persisted_pending.get("attempt") or values.get("active_attempt") or 1
        )
        if node_id == dispatch.node_id and state_attempt == dispatch.attempt:
            # 线程已在该节点的中断点：崩溃恢复，重派生同一 actionId；
            # adapter_dispatch 的幂等键保证不会重复建任务。
            pending = (
                PendingAction.from_dict(dict(persisted_pending))
                if persisted_pending
                else build_pending_action(values, node_id)
            )
            return GraphDispatchResult(
                dispatch_kind="start",
                pending_action=pending,
                next_node_ids=tuple(str(item) for item in next_node_ids)
                or (node_id,),
                checkpoint_id=str(snapshot.get("checkpointId") or ""),
                state=values,
            )
        if node_id == dispatch.node_id:
            # retry：以新 attempt 重启节点，产生新的 actionId。
            return self._coordinator.restart_attempt(dispatch)
        advanced = self._advance_lagging_checkpoint(dispatch, interrupt_node_id=node_id)
        if advanced is not None:
            return advanced
        if not next_node_ids:
            has_live_thread = bool(
                values.get("active_node_id")
                or values.get("checkpoint_version")
                or persisted_pending
            )
            if has_live_thread and dispatch.node_id != node_id:
                from dataclasses import replace

                run = self._store.get_run(dispatch.run_id)
                branch = branch_decision_from_run(run)
                extra = dict(dispatch.state_update or {})
                if branch and not extra.get("branch_decision"):
                    extra["branch_decision"] = branch
                if extra:
                    dispatch = replace(dispatch, state_update=extra)
                return self._coordinator.enter_node(dispatch)
            if dispatch.attempt >= 2:
                # Thread already finished (failed end): re-enter the node.
                return self._coordinator.retry_attempt(dispatch)
            return self._coordinator.start_attempt(dispatch)
        if (
            node_id
            and dispatch.node_id != node_id
            and dispatch.attempt >= 2
        ):
            return self._pending_from_ledger_dispatch(dispatch, snapshot)
        raise GraphDecisionError(
            f"thread 中断于 {node_id}，但 dispatch 目标是 {dispatch.node_id}"
        )

    def _pending_from_ledger_dispatch(
        self, dispatch: GraphDispatch, snapshot: dict[str, Any]
    ) -> GraphDispatchResult:
        """Lag-walk failed, but ledger already owns the retry target.

        SCI-096: thread stays interrupted at ``source_finding`` (so
        ``nextNodeIds`` is non-empty) while ``retry_node`` targets
        ``controlled_run`` attempt >= 2. Synthesize pending from ledger
        identity instead of raising ``checkpoint_node_mismatch``.
        """
        from dataclasses import replace

        values = dict(snapshot.get("values") or {})
        values["run_id"] = dispatch.run_id
        values["active_node_id"] = dispatch.node_id
        values["active_attempt"] = dispatch.attempt
        node_attempts = dict(values.get("node_attempts") or {})
        node_attempts[dispatch.node_id] = dispatch.attempt
        values["node_attempts"] = node_attempts
        if dispatch.input_snapshot_hash:
            values["input_snapshot_hash"] = dispatch.input_snapshot_hash
        if dispatch.budget_policy_hash:
            values["budget_policy_hash"] = dispatch.budget_policy_hash
        pending = build_pending_action(values, dispatch.node_id)
        node_run_id = str(dispatch.node_run_id or "").strip() or pending.node_run_id
        expected_action_id = action_id_for(
            dispatch.run_id, dispatch.node_id, dispatch.attempt
        )
        if (
            pending.run_id != dispatch.run_id
            or pending.node_run_id != node_run_id
            or pending.action_id != expected_action_id
            or pending.attempt != dispatch.attempt
        ):
            pending = replace(
                pending,
                run_id=dispatch.run_id,
                node_run_id=node_run_id,
                action_id=expected_action_id,
                attempt=dispatch.attempt,
            )
        return GraphDispatchResult(
            dispatch_kind="start",
            pending_action=pending,
            next_node_ids=tuple(
                str(item) for item in (snapshot.get("nextNodeIds") or [])
            )
            or (dispatch.node_id,),
            checkpoint_id=str(snapshot.get("checkpointId") or ""),
            state=values,
        )

    def _result_at_target(
        self, dispatch: GraphDispatch, snapshot: dict[str, Any]
    ) -> GraphDispatchResult:
        values = dict(snapshot.get("values") or {})
        interrupt = snapshot.get("pendingAction") or {}
        if str(interrupt.get("nodeId") or "") == dispatch.node_id:
            pending_target = PendingAction.from_dict(dict(interrupt))
        else:
            pending_target = build_pending_action(values, dispatch.node_id)
        if pending_target.attempt != dispatch.attempt:
            return self._coordinator.restart_attempt(dispatch)
        return GraphDispatchResult(
            dispatch_kind="start",
            pending_action=pending_target,
            next_node_ids=tuple(
                str(item) for item in (snapshot.get("nextNodeIds") or [])
            ),
            checkpoint_id=str(snapshot.get("checkpointId") or ""),
            state=values,
        )

    def _advance_lagging_checkpoint(
        self, dispatch: GraphDispatch, *, interrupt_node_id: str
    ) -> GraphDispatchResult | None:
        """Resume succeeded predecessors so retry can enter the target node.

        Ledger may already be many hops ahead of LangGraph (SCI-096: thread
        still at ``source_finding`` while retrying ``controlled_run``). Walk
        the unique linear path, resuming each succeeded + accepted hop.
        """
        path = _linear_successor_path(
            interrupt_node_id, dispatch.node_id, dispatch.workflow_version_id
        )
        if path is None or len(path) < 2:
            return None
        for predecessor_id, successor_id in zip(path[:-1], path[1:]):
            snapshot = self._coordinator.snapshot(dispatch.run_id, dispatch.workflow_version_id)
            if _graph_at_node(snapshot, dispatch.node_id):
                break
            if not _graph_at_node(snapshot, predecessor_id):
                return None
            if not self._resume_lagging_predecessor(
                dispatch, predecessor_node_id=predecessor_id
            ):
                return None
            snapshot = self._coordinator.snapshot(dispatch.run_id, dispatch.workflow_version_id)
            if not (
                _graph_at_node(snapshot, successor_id)
                or _graph_at_node(snapshot, dispatch.node_id)
            ):
                return None
        snapshot = self._coordinator.snapshot(dispatch.run_id, dispatch.workflow_version_id)
        if not _graph_at_node(snapshot, dispatch.node_id):
            return None
        # Re-enter the target interrupt with the ledger attempt. Never
        # Command.goto a different node — that overwrites active_node_id
        # while leaving the stale source_finding interrupt in place.
        return self._result_at_target(dispatch, snapshot)

    def _resume_lagging_predecessor(
        self, dispatch: GraphDispatch, *, predecessor_node_id: str
    ) -> bool:
        """Consume the current interrupt so retry can walk toward the target.

        SCI-096: Command.goto split ``values.active_node_id`` from the persisted
        interrupt, then a later replay rebuilt that interrupt with an empty
        ``runId`` (``nr--source_finding-a1``). Ledger may already be many hops
        ahead, and compact snapshots can omit accepted handoffs, so this hop
        does not wait on handoff rows. It still refuses to fake-succeed a
        predecessor that is mid-flight unless the dispatch is a downstream
        retry (attempt >= 2). Restore ``run_id`` in the same Command as a
        Ledger-identity receipt — LangGraph applies ``update`` before matching
        ``resume``, so the empty interrupt heals and the hop advances.
        """
        from dataclasses import replace

        snapshot = self._coordinator.snapshot(dispatch.run_id, dispatch.workflow_version_id)
        if not _graph_at_node(snapshot, predecessor_node_id):
            return False
        predecessor = self._store.latest_attempt(dispatch.run_id, predecessor_node_id)
        predecessor_done = (
            predecessor is not None
            and predecessor.status == NodeAttemptStatus.SUCCEEDED.value
        )
        downstream_retry = (
            dispatch.node_id != predecessor_node_id and dispatch.attempt >= 2
        )
        if not predecessor_done and not downstream_retry:
            return False
        values = dict(snapshot.get("values") or {})
        interrupt = snapshot.get("pendingAction") or {}
        attempt = int(
            interrupt.get("attempt")
            or (predecessor.attempt if predecessor is not None else 0)
            or 1
        )
        # After restoring run_id, build_pending_action uses this formula.
        # Do not mix in a Ledger node_run_id that can disagree with the healed interrupt.
        node_run_id = f"nr-{dispatch.run_id}-{predecessor_node_id}-a{attempt}"
        receipts: list[Any] = []
        if predecessor is not None:
            receipts = self._submit(
                lambda uow: uow.repository.list_receipts_for_node_run(
                    predecessor.node_run_id
                ),
                force_flush=True,
            ).result(timeout=10)
        ledger_receipt = ExecutionReceipt(
            action_id=action_id_for(dispatch.run_id, predecessor_node_id, attempt),
            node_run_id=node_run_id,
            outcome="succeeded",
            artifact_receipt_ids=tuple(str(row[0]) for row in receipts),
            execution_anchor_id=(
                predecessor.execution_anchor_id if predecessor is not None else None
            ),
            budget_receipt_id=None,
            problem=None,
            completed_at_ms=int(
                (
                    predecessor.finished_at_ms
                    or predecessor.updated_at_ms
                    or 0
                )
                if predecessor is not None
                else 0
            ),
        )
        node_attempts = dict(values.get("node_attempts") or {})
        node_attempts[predecessor_node_id] = attempt
        node_attempts[dispatch.node_id] = dispatch.attempt
        heal_update: dict[str, Any] = {
            "run_id": dispatch.run_id,
            "node_attempts": node_attempts,
        }
        if dispatch.team_id:
            heal_update["team_id"] = dispatch.team_id
        if dispatch.input_snapshot_hash:
            heal_update["input_snapshot_hash"] = dispatch.input_snapshot_hash
        heal_dispatch = replace(
            dispatch,
            action_id=action_id_for(dispatch.run_id, predecessor_node_id, attempt),
            node_run_id=node_run_id,
            node_id=predecessor_node_id,
            attempt=attempt,
            dispatch_kind="start",
            receipt=None,
            state_update=None,
        )
        interrupt_receipt = _receipt_for_interrupt_identity(
            interrupt,
            predecessor_node_id=predecessor_node_id,
            attempt=attempt,
            artifact_receipt_ids=ledger_receipt.artifact_receipt_ids,
            execution_anchor_id=ledger_receipt.execution_anchor_id,
            completed_at_ms=ledger_receipt.completed_at_ms,
        )
        visible_run_id = str(interrupt.get("runId") or "").strip()
        visible_action_id = str(interrupt.get("actionId") or "").strip()
        if (
            visible_run_id
            and visible_action_id
            and str(interrupt.get("nodeId") or "") == predecessor_node_id
        ):
            # Live SCI-096 interrupt already has formula identity. Resume it
            # before restart_attempt — time-travel on a dirty checkpoint can
            # leave the hop at source_finding and look like success.
            try:
                self._coordinator.resume_action(
                    replace(
                        heal_dispatch,
                        action_id=interrupt_receipt.action_id,
                        node_run_id=interrupt_receipt.node_run_id,
                        dispatch_kind="resume_action",
                        receipt=interrupt_receipt,
                        binding_snapshot_id=(
                            predecessor.binding_snapshot_id
                            if predecessor is not None
                            else None
                        ),
                        state_update=heal_update,
                    )
                )
                after = self._coordinator.snapshot(dispatch.run_id, dispatch.workflow_version_id)
                if not _graph_at_node(after, predecessor_node_id):
                    return True
            except Exception as exc:
                # The live interrupt can carry goto-split pending writes, so
                # this first resume failing is exactly the shape
                # ``rebuild_interrupt`` exists for (SCI-096 live shape). The
                # handoff to rebuild is designed control flow, not a silent
                # swallow: the degraded step is recorded with its cause, and
                # rebuild itself must succeed or the whole recovery aborts
                # with the step name.
                _record_scene_event(
                    "graph_dispatch.heal_step_degraded",
                    outcome="heal_degraded",
                    fields={
                        "runId": dispatch.run_id,
                        "nodeId": predecessor_node_id,
                        "step": "resume_live_interrupt",
                        "errorType": type(exc).__name__,
                        "detail": str(exc)[:200],
                    },
                )
        try:
            # Command.goto leaves pending writes that get_state.interrupts
            # does not show. A bare Command(resume=receipt) then raises
            # "multiple pending interrupts". Time-travel rebuilds one
            # interrupt with the real run_id before we resume.
            self._coordinator.restart_attempt(heal_dispatch)
        except Exception as exc:
            raise GraphRecoverStepError(
                "rebuild_interrupt",
                dispatch.run_id,
                predecessor_node_id,
                exc,
            ) from exc
        predecessor_dispatch = replace(
            heal_dispatch,
            dispatch_kind="resume_action",
            receipt=ledger_receipt,
            binding_snapshot_id=(
                predecessor.binding_snapshot_id if predecessor is not None else None
            ),
            state_update=heal_update,
        )
        try:
            # Call the coordinator directly: worker._resume() overwrites
            # node_attempts with successor latest+1, which skips the retry
            # attempt already inserted by the command layer.
            self._coordinator.resume_action(predecessor_dispatch)
        except Exception as exc:
            raise GraphRecoverStepError(
                "resume_predecessor",
                dispatch.run_id,
                predecessor_node_id,
                exc,
            ) from exc
        after = self._coordinator.snapshot(dispatch.run_id, dispatch.workflow_version_id)
        if not _graph_at_node(after, predecessor_node_id):
            return True
        raise GraphRecoverStepError(
            "resume_predecessor",
            dispatch.run_id,
            predecessor_node_id,
            RuntimeError(
                "resume returned but the thread still interrupts at the predecessor"
            ),
        )

    def _resume(self, dispatch: GraphDispatch) -> GraphDispatchResult:
        if dispatch.receipt is None:
            raise ValueError("resume dispatch requires an ExecutionReceipt")
        from dataclasses import replace

        run = self._store.get_run(dispatch.run_id)
        branch = branch_decision_from_run(run)
        merged = dict(dispatch.state_update or {})
        if (
            dispatch.node_id in {"iteration_decision", "version_governance"}
            and branch
            and not merged.get("branch_decision")
        ):
            merged["branch_decision"] = branch
        branch_for_route = str(merged.get("branch_decision") or branch or "")
        routed = routed_successors(dispatch.node_id, branch_for_route)
        if routed:
            successors = routed
        elif dispatch.node_id in {"iteration_decision", "version_governance"}:
            successors = ()
        else:
            successors = successor_map(dispatch.workflow_version_id).get(dispatch.node_id, ())
        node_attempts: dict[str, int] = {}
        for successor in successors:
            latest = self._store.latest_attempt(dispatch.run_id, successor)
            node_attempts[successor] = (latest.attempt + 1) if latest else 1
        if node_attempts:
            merged["node_attempts"] = node_attempts
        if merged:
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
        pending_node = getattr(result.pending_action, "node_id", "") or ""
        _record_scene_event(
            "graph_dispatch.committed",
            outcome="committed",
            fields={
                "teamId": str(dispatch.team_id or ""),
                "runId": str(dispatch.run_id or ""),
                "nodeId": str(dispatch.node_id or ""),
                "dispatchKind": str(dispatch.dispatch_kind or ""),
                "pendingNodeId": str(pending_node),
                "completed": bool(getattr(result, "completed", False)),
            },
        )

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
                    # 已终态的 attempt 不得倒回 dispatching（SCI-096 泵曾把
                    # source_finding succeeded → dispatching 打爆）。
                    try:
                        current_status = NodeAttemptStatus(latest.status)
                    except ValueError:
                        current_status = None
                    if (
                        current_status is not None
                        and current_status != NodeAttemptStatus.DISPATCHING
                        and not can_transition_node_attempt(
                            current_status, NodeAttemptStatus.DISPATCHING
                        )
                    ):
                        return
                    uow.repository.update_attempt_status(
                        latest.node_run_id,
                        NodeAttemptStatus.DISPATCHING.value,
                        now_ms,
                        pending_action_id=pending.action_id,
                    )
                    _ensure_adapter_dispatch(
                        uow,
                        pending=pending,
                        run_id=dispatch.run_id,
                        command_id=action.command_id or latest.command_id,
                        node_run_id=latest.node_run_id,
                        now_ms=now_ms,
                    )
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
                        problem = {
                            "code": "auto_advance_not_ready",
                            "detail": "; ".join(
                                str(b.get("code") or b) for b in blockers
                            ),
                        }
                        sync_run_blocked(
                            uow,
                            run_id=dispatch.run_id,
                            node_id=pending.node_id,
                            problem=problem,
                            now_ms=now_ms,
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
                                        "code": problem["code"],
                                        "detail": problem["detail"],
                                        "reason": format_blocked_reason(problem),
                                        "blockers": [
                                            str(b.get("code") or b) for b in blockers
                                        ],
                                    },
                                    now_ms=now_ms,
                                )
                            )
                    else:
                        created = _attempt_for_pending(
                            pending,
                            command_id=action.command_id or "cmd-recovery",
                            now_ms=now_ms,
                        )
                        uow.repository.insert_attempt(created)
                        _ensure_adapter_dispatch(
                            uow,
                            pending=pending,
                            run_id=dispatch.run_id,
                            command_id=created.command_id,
                            node_run_id=created.node_run_id,
                            now_ms=now_ms,
                        )
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
                closed_run = uow.repository.get_run(dispatch.run_id)
                if (
                    outcome == "succeeded"
                    and result.pending_action is None
                    and closed_run is not None
                    and _run_terminal_close_applies(
                        closed_run,
                        dispatch.node_id,
                        dispatch.state_update,
                    )
                ):
                    completion_kind, terminal_reason = _terminal_facts_for_close(
                        closed_run,
                        node_id=dispatch.node_id,
                        state_update=dispatch.state_update,
                    )
                    sync_run_succeeded(
                        uow,
                        run_id=dispatch.run_id,
                        now_ms=now_ms,
                        completion_kind=completion_kind,
                        terminal_reason=terminal_reason,
                        node_id=dispatch.node_id,
                        actor_id=self._owner,
                    )
                    _sideflow_child_succeeded(
                        uow, run_id=dispatch.run_id, now_ms=now_ms
                    )
                elif outcome != "succeeded":
                    _sideflow_child_failed(
                        uow,
                        run_id=dispatch.run_id,
                        outcome=outcome,
                        now_ms=now_ms,
                    )

        self._submit(mutate, force_flush=True).result(timeout=30)

    def _repair_dispatching_without_adapter(self) -> int:
        """Re-insert adapter_dispatch after a swallowed graph/adapter commit gap."""
        now_ms = self._now()

        def mutate(uow):
            rows = uow.repository.execute(
                """
                SELECT node_run_id, run_id, node_id, attempt, actor_kind,
                       command_id, binding_snapshot_id, input_snapshot_hash,
                       pending_action_id
                FROM node_attempts
                WHERE status = 'dispatching'
                  AND pending_action_id IS NOT NULL
                  AND pending_action_id != ''
                """
            ).fetchall()
            repaired_rows: list[tuple[str, str]] = []
            for row in rows:
                pending = _pending_from_dispatching_row(row)
                if pending is None:
                    continue
                pending = self._pending_with_node_binding(
                    pending,
                    run=uow.repository.get_run(pending.run_id),
                )
                if _ensure_adapter_dispatch(
                    uow,
                    pending=pending,
                    run_id=str(row[1]),
                    command_id=str(row[5] or ""),
                    node_run_id=str(row[0]),
                    now_ms=now_ms,
                ):
                    repaired_rows.append((str(row[0]), str(row[1])))
            return repaired_rows

        revived = list(self._submit(mutate, force_flush=True).result(timeout=30) or ())
        for node_run_id, run_id in revived:
            _record_scene_event(
                "graph_dispatch.adapter_dispatch_revived",
                outcome="recovered",
                fields={
                    "runId": run_id,
                    "nodeRunId": node_run_id,
                    "sweep": "dispatching_without_adapter",
                },
            )
        return len(revived)

    def _repair_starting_without_progress(self) -> int:
        """Re-enqueue graph_dispatch when start was acked but attempt stayed starting."""
        from .graph_dispatch_factory import build_graph_dispatch_record

        now_ms = self._now()

        def mutate(uow):
            rows = uow.repository.execute(
                """
                SELECT node_run_id, run_id, command_id
                FROM node_attempts
                WHERE status = 'starting'
                """
            ).fetchall()
            repaired_rows: list[tuple[str, str]] = []
            for row in rows:
                node_run_id = str(row[0] or "")
                run_id = str(row[1] or "")
                command_id = str(row[2] or "")
                if not node_run_id or not run_id or not command_id:
                    continue
                inflight = uow.repository.execute(
                    """
                    SELECT 1 FROM outbox_actions
                    WHERE node_run_id = ?
                      AND action_kind = 'graph_dispatch'
                      AND status IN ('pending', 'leased')
                    LIMIT 1
                    """,
                    (node_run_id,),
                ).fetchone()
                if inflight is not None:
                    continue
                run = uow.repository.get_run(run_id)
                attempt = uow.repository.get_attempt(node_run_id)
                if run is None or attempt is None:
                    continue
                key = f"graph:repair:{node_run_id}"
                existing = uow.repository.execute(
                    "SELECT action_id, status FROM outbox_actions WHERE idempotency_key = ?",
                    (key,),
                ).fetchone()
                if existing is not None:
                    status = str(existing[1] or "")
                    if status in {"pending", "leased"}:
                        continue
                    uow.repository.execute(
                        """
                        UPDATE outbox_actions
                        SET status = 'pending',
                            lease_owner = NULL,
                            lease_expires_at_ms = NULL,
                            available_at_ms = ?,
                            updated_at_ms = ?,
                            last_problem_json = NULL
                        WHERE action_id = ?
                        """,
                        (now_ms, now_ms, existing[0]),
                    )
                    repaired_rows.append((node_run_id, run_id))
                    continue
                uow.repository.insert_outbox(
                    build_graph_dispatch_record(
                        run=run,
                        attempt=attempt,
                        command_id=command_id,
                        dispatch_kind="start",
                        now_ms=now_ms,
                        idempotency_key=key,
                    )
                )
                repaired_rows.append((node_run_id, run_id))
            return repaired_rows

        requeued = list(self._submit(mutate, force_flush=True).result(timeout=30) or ())
        for node_run_id, run_id in requeued:
            _record_scene_event(
                "graph_dispatch.starting_dispatch_requeued",
                outcome="recovered",
                fields={
                    "runId": run_id,
                    "nodeRunId": node_run_id,
                    "sweep": "starting_without_progress",
                },
            )
        return len(requeued)

    def repair_stranded_iteration_route_for_run(self, run_id: str) -> bool:
        """Repair one run stranded at the iteration gate; event-triggered only.

        Stranded shape: ``iteration_decision`` already succeeded in the ledger
        (the decision lives only in the artifact store after a compact
        restore) while the LangGraph thread never reached
        ``version_governance``.  ``run_once`` used to rescan every
        running/blocked run each cycle; now the dispatch failure path calls
        this explicitly, because a failed ``iteration_decision`` dispatch is
        the observable signal of the strand.  Returns True when
        ``version_governance`` was created.
        """
        if not run_id:
            return False
        try:
            snapshot = self._coordinator.snapshot(run_id)
        except Exception as exc:
            _record_repair_skip(run_id, "snapshot", exc)
            return False
        pending_payload = (
            snapshot.get("pendingAction")
            if isinstance(snapshot.get("pendingAction"), dict)
            else None
        )
        pending_node = str((pending_payload or {}).get("nodeId") or "")
        next_ids = [str(item) for item in (snapshot.get("nextNodeIds") or [])]
        if pending_node and pending_node != "iteration_decision":
            return False
        if next_ids and pending_node != "iteration_decision":
            return False
        latest_iter = self._store.latest_attempt(run_id, "iteration_decision")
        if (
            latest_iter is None
            or latest_iter.status != NodeAttemptStatus.SUCCEEDED.value
        ):
            return False
        if self._store.latest_attempt(run_id, "version_governance") is not None:
            return False
        run = self._store.get_run(run_id)
        branch = branch_decision_from_run(run)
        if branch not in {
            "stop",
            "promote_candidate",
            "rollback_candidate",
            "rerun_same_protocol",
        }:
            return False
        inflight = self._submit(
            lambda uow: uow.repository.execute(
                """
                SELECT 1 FROM outbox_actions
                WHERE run_id = ?
                  AND action_kind = 'graph_dispatch'
                  AND status IN ('pending', 'leased')
                LIMIT 1
                """,
                (run_id,),
            ).fetchone(),
            force_flush=True,
        ).result(timeout=10)
        if inflight is not None:
            return False
        mode: str
        if pending_node == "iteration_decision":
            action_id = str((pending_payload or {}).get("actionId") or "")
            node_run_id = str(
                (pending_payload or {}).get("nodeRunId") or latest_iter.node_run_id
            )
            if not action_id:
                return False
            dispatch = GraphDispatch(
                action_id=action_id,
                run_id=run_id,
                node_run_id=node_run_id,
                node_id="iteration_decision",
                attempt=int(
                    (pending_payload or {}).get("attempt") or latest_iter.attempt
                ),
                dispatch_kind="resume_action",
                input_snapshot_hash=str(getattr(run, "input_snapshot_hash", "") or ""),
                workflow_version_id=str(getattr(run, "workflow_version_id", "") or ""),
                team_id=str(getattr(run, "team_id", "") or ""),
                receipt=ExecutionReceipt(
                    action_id=action_id,
                    node_run_id=node_run_id,
                    outcome="succeeded",
                    artifact_receipt_ids=(),
                    execution_anchor_id=latest_iter.execution_anchor_id,
                    budget_receipt_id=None,
                    problem=None,
                    completed_at_ms=int(latest_iter.finished_at_ms or self._now()),
                ),
                state_update={"branch_decision": branch},
            )
            try:
                result = self._resume(dispatch)
            except Exception as exc:
                _record_repair_skip(run_id, "resume_iteration", exc)
                return False
            mode = "resume_iteration"
        else:
            dispatch = GraphDispatch(
                action_id=new_id("act"),
                run_id=run_id,
                node_run_id=f"nr-{run_id}-version_governance-a1",
                node_id="version_governance",
                attempt=1,
                dispatch_kind="start",
                input_snapshot_hash=str(getattr(run, "input_snapshot_hash", "") or ""),
                workflow_version_id=str(getattr(run, "workflow_version_id", "") or ""),
                team_id=str(getattr(run, "team_id", "") or ""),
                state_update={"branch_decision": branch},
            )
            try:
                result = self._coordinator.enter_node(dispatch)
            except Exception as exc:
                _record_repair_skip(run_id, "enter_governance", exc)
                return False
            mode = "enter_governance"
        pending = result.pending_action
        if pending is None or pending.node_id != "version_governance":
            return False
        pending = self._pending_with_node_binding(pending)
        readiness_hint = self._precheck_readiness(dispatch, pending)
        from .challenge_cup_maintenance_fence import (
            ChallengeCupMaintenanceError,
            assert_writes_allowed,
        )

        try:
            assert_writes_allowed(
                dispatch.team_id,
                operation="workflow_dispatch_successor",
            )
        except ChallengeCupMaintenanceError:
            # Keep the pre-fence run visible to the reset drain; do not
            # synthesize a successor while maintenance is active.
            return False
        self._commit_successor_dispatch(
            dispatch,
            result,
            pending,
            readiness_hint,
            action=None,
            fallback_command_id=str(latest_iter.command_id or ""),
        )
        _record_scene_event(
            "graph_dispatch.stranded_iteration_route_repaired",
            outcome="recovered",
            fields={
                "runId": run_id,
                "nodeId": "version_governance",
                "mode": mode,
                "branch": branch,
            },
        )
        return True

    def _repair_stranded_iteration_route_after_failure(
        self, dispatch: GraphDispatch
    ) -> None:
        """Event hook: an ``iteration_decision`` dispatch just failed.

        This is the only observable signal of a stranded iteration route, so
        the repair is attempted here instead of by a periodic full-table
        sweep.  The primary failure is already durably blocked at this point,
        so a repair error must not mask it: it surfaces as a structured
        ``repair_skipped`` signal rather than escaping into ``run_once``.
        """
        if str(dispatch.node_id or "") != "iteration_decision":
            return
        run_id = str(dispatch.run_id or "")
        if not run_id:
            return
        try:
            self.repair_stranded_iteration_route_for_run(run_id)
        except Exception as exc:
            _record_repair_skip(run_id, "stranded_iteration_route", exc)

    def _repair_stranded_terminal_package(self) -> int:
        """Close a run whose result_package already succeeded but the ledger stayed running.

        Adapter used to skip graph resume when ``successors`` is empty, so STOP
        packaging never wrote ``run.status=succeeded`` / ``terminalReason``.
        """
        rows = self._submit(
            lambda uow: uow.repository.execute(
                "SELECT run_id FROM workflow_runs WHERE status IN ('running', 'blocked')"
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
        closed_runs: list[tuple[str, str]] = []
        now_ms = self._now()
        for row in rows or ():
            run_id = str(row[0] or "")
            if not run_id:
                continue
            latest = self._store.latest_attempt(run_id, "result_package")
            if latest is None or latest.status != NodeAttemptStatus.SUCCEEDED.value:
                continue
            run = self._store.get_run(run_id)
            if run is None:
                continue
            completion_kind, terminal_reason = terminal_facts_for_run(run)

            def mutate(uow, rid=run_id, kind=completion_kind, reason=terminal_reason):
                return sync_run_succeeded(
                    uow,
                    run_id=rid,
                    now_ms=now_ms,
                    completion_kind=kind,
                    terminal_reason=reason,
                    node_id="result_package",
                    actor_id=self._owner,
                )

            if self._submit(mutate, force_flush=True).result(timeout=30):
                closed_runs.append((run_id, terminal_reason))
        for closed_run_id, closed_reason in closed_runs:
            _record_scene_event(
                "graph_dispatch.stranded_terminal_package_closed",
                outcome="recovered",
                fields={
                    "runId": closed_run_id,
                    "terminalReason": closed_reason,
                    "sweep": "stranded_terminal_package",
                },
            )
        return len(closed_runs)

    def _repair_terminal_failed_dispatch(self) -> int:
        """Translate stranded runs that a terminal-failed graph dispatch left behind.

        Historical rows (written before the `_mark_blocked` reconciliation
        translation existed, or swept by the lease-attempt gate while the
        worker was down) can keep a run in ``running``/``waiting_human`` with
        no pending or leased graph_dispatch: nothing will ever advance it.
        This repair surfaces exactly those rows as ``reconciliation_required``
        so the reconcile_run offer reappears. Rows still being worked on are
        excluded via the inflight check; BLOCKED runs already have their own
        operator entry and are not touched.
        """
        now_ms = self._now()

        def find_stranded(uow):
            return uow.repository.execute(
                """
                SELECT o.action_id, o.node_run_id, o.last_problem_json, r.run_id
                FROM workflow_runs r
                JOIN outbox_actions o
                  ON o.run_id = r.run_id
                 AND o.action_kind = 'graph_dispatch'
                 AND o.status = 'failed'
                WHERE r.status IN ('running', 'waiting_human')
                  AND NOT EXISTS (
                    SELECT 1 FROM outbox_actions live
                    WHERE live.run_id = r.run_id
                      AND live.action_kind = 'graph_dispatch'
                      AND live.status IN ('pending', 'leased')
                  )
                ORDER BY o.updated_at_ms DESC, o.action_id DESC
                """,
            ).fetchall()

        rows = self._submit(find_stranded, force_flush=True).result(timeout=10)
        seen_runs: set[str] = set()
        repaired = 0
        for row in rows or ():
            action_id = str(row[0] or "")
            node_run_id = str(row[1] or "") or None
            problem_raw = str(row[2] or "")
            run_id = str(row[3] or "")
            if not action_id or not run_id or run_id in seen_runs:
                continue
            seen_runs.add(run_id)
            try:
                problem = json.loads(problem_raw) if problem_raw else {}
            except (TypeError, ValueError, json.JSONDecodeError):
                problem = {"code": "workflow_blocked", "detail": problem_raw}
            if not isinstance(problem, dict) or not problem:
                problem = {"code": "graph_dispatch_failed", "detail": ""}
            elif not problem.get("code"):
                problem["code"] = "graph_dispatch_failed"

            def mutate(uow, rid=run_id, prob=problem, nid=node_run_id, aid=action_id):
                return mark_run_reconciliation_required(
                    uow,
                    run_id=rid,
                    problem=prob,
                    now_ms=now_ms,
                    actor_id=self._owner,
                    correlation_id=aid,
                    node_run_id=nid,
                    action_id=aid,
                    extra_payload={"repair": "terminal_failed_dispatch"},
                )

            # The mark helper is status-guarded, so a run that became live
            # between the scan and this transaction stays untouched.
            if self._submit(mutate, force_flush=True).result(timeout=30):
                _record_scene_event(
                    "graph_dispatch.terminal_failure_reconciled",
                    outcome="recovered",
                    fields={
                        "runId": run_id,
                        "actionId": action_id,
                        "nodeRunId": node_run_id or "",
                        "problemCode": str(problem.get("code") or ""),
                    },
                )
                repaired += 1
        return repaired

    def _mark_blocked(
        self,
        action: Any,
        dispatch: GraphDispatch,
        detail: str,
        *,
        problem: dict[str, Any] | None = None,
    ) -> None:
        now_ms = self._now()
        problem = problem or problem_from_graph_error(detail)
        _record_scene_event(
            "graph_dispatch.blocked",
            outcome="blocked",
            fields={
                "teamId": str(dispatch.team_id or ""),
                "runId": str(dispatch.run_id or ""),
                "nodeId": str(dispatch.node_id or ""),
                "problemCode": str(problem.get("code") or ""),
            },
        )

        def mutate(uow):
            failed = uow.repository.fail_outbox(
                action.action_id, self._owner, now_ms, problem_json=json.dumps(problem)
            )
            if not failed:
                return
            attempt = uow.repository.get_attempt(dispatch.node_run_id)
            if attempt is not None:
                try:
                    current = NodeAttemptStatus(str(attempt.status))
                except ValueError:
                    current = None
                if current in {
                    NodeAttemptStatus.SUCCEEDED,
                    NodeAttemptStatus.FAILED,
                    NodeAttemptStatus.CANCELLED,
                    NodeAttemptStatus.STALE,
                } or (
                    current is not None
                    and not can_transition_node_attempt(
                        current, NodeAttemptStatus.BLOCKED
                    )
                ):
                    # Adapter already finished this attempt. Rewinding
                    # succeeded → blocked is illegal and would strand STOP.
                    # The dispatch itself is still terminal-failed though: an
                    # outbox failure with no live successor leaves the run
                    # advancing nowhere, so surface it as reconciliation
                    # instead of a silent stranded running run.
                    mark_run_reconciliation_required(
                        uow,
                        run_id=dispatch.run_id,
                        problem=problem,
                        now_ms=now_ms,
                        actor_id=self._owner,
                        correlation_id=str(action.action_id or dispatch.node_run_id),
                        node_run_id=dispatch.node_run_id,
                        action_id=str(getattr(action, "action_id", "") or ""),
                    )
                    return
            apply_node_run_block(
                uow,
                run_id=dispatch.run_id,
                node_run_id=dispatch.node_run_id,
                node_id=dispatch.node_id,
                problem=problem,
                now_ms=now_ms,
                actor_id=self._owner,
                correlation_id=str(action.action_id or dispatch.node_run_id),
            )

        self._submit(mutate, force_flush=True).result(timeout=30)

    _MAX_TRANSIENT_ATTEMPTS = 5

    def _requeue_or_fail(self, action: Any, dispatch: Any, detail: str) -> None:
        now_ms = self._now()
        if int(getattr(action, "attempt_count", 0) or 0) >= self._MAX_TRANSIENT_ATTEMPTS:
            # Deterministic failures must not retry forever; mark the dispatch
            # blocked so the run surfaces a diagnosis instead of live-locking.
            self._mark_blocked(
                action,
                dispatch,
                f"transient_exhausted: {str(detail)[:400]}",
            )
            return
        _record_scene_event(
            "graph_dispatch.requeued",
            outcome="requeued",
            fields={
                "teamId": str(getattr(dispatch, "team_id", "") or ""),
                "runId": str(getattr(dispatch, "run_id", "") or ""),
                "nodeId": str(getattr(dispatch, "node_id", "") or ""),
                "attemptCount": int(getattr(action, "attempt_count", 0) or 0),
                "errorType": type(detail).__name__ if not isinstance(detail, str) else "",
                "detail": str(detail)[:160],
            },
        )
        outbox_api.requeue_action(
            self._store,
            action.action_id,
            self._owner,
            now_ms,
            retry_at_ms=now_ms + 5_000,
            problem_json=json.dumps({"code": "transient", "detail": detail}),
        )


def _terminal_facts_for_close(
    run: Any,
    *,
    node_id: str = "",
    state_update: Mapping[str, Any] | None = None,
) -> tuple[str, str]:
    """Terminal facts for a closing run.

    Main-flow runs keep the package/governance-derived facts; knowledge
    sideflow children close with their own acceptance semantics.
    """
    if _is_sideflow_run(run):
        return "knowledge_sideflow", "knowledge_package_accepted"
    stage_one = stage_one_terminal_facts(
        run,
        node_id=node_id,
        state_update=state_update,
    )
    if stage_one is not None:
        return stage_one
    return terminal_facts_for_run(run)


def _run_terminal_close_applies(
    run: Any,
    node_id: str,
    state_update: Mapping[str, Any] | None = None,
) -> bool:
    """Whether a completed dispatch on this run closes it as succeeded.

    Main-flow runs close only on ``result_package`` (historical behavior).
    Knowledge sideflow child runs close on their terminal
    ``knowledge_handoff`` node, which has no outgoing edge in the pinned
    sideflow definition.
    """
    if _is_sideflow_run(run):
        return True
    if (
        stage_one_terminal_facts(
            run,
            node_id=node_id,
            state_update=state_update,
        )
        is not None
    ):
        return True
    return str(node_id or "") == "result_package"


def _is_sideflow_run(run: Any) -> bool:
    from core.research.workflow.knowledge_sideflow_definition import (
        KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,
    )

    return (
        str(getattr(run, "workflow_id", "") or "") == KNOWLEDGE_SIDEFLOW_WORKFLOW_ID
    )


def _sideflow_child_succeeded(uow: Any, *, run_id: str, now_ms: int) -> None:
    """Producer hook: sideflow child reached its accepted handoff terminal.

    Runs inside the SAME ledger transaction that committed the child run's
    terminal facts: the knowledge_invocations row is closed with package
    evidence and the ``event_publish`` outbox row is inserted atomically.
    A child without package evidence never fakes a handoff.
    """
    from .knowledge_sideflow_service import (
        record_knowledge_sideflow_child_success,
    )

    record_knowledge_sideflow_child_success(uow, run_id=run_id, now_ms=now_ms)


def _sideflow_child_failed(
    uow: Any,
    *,
    run_id: str,
    outcome: str,
    now_ms: int,
) -> None:
    """Producer hook: sideflow child failed/blocked/cancelled — no handoff."""
    from .knowledge_sideflow_service import record_knowledge_sideflow_child_failure

    record_knowledge_sideflow_child_failure(
        uow, run_id=run_id, outcome=outcome, now_ms=now_ms
    )


def _linear_successor_path(
    start_node_id: str,
    target_node_id: str,
    workflow_version_id: str = "",
) -> list[str] | None:
    """Unique linear path from an interrupt node to a downstream retry target."""
    start = str(start_node_id or "").strip()
    target = str(target_node_id or "").strip()
    if not start or not target:
        return None
    if start == target:
        return [start]
    path = [start]
    current = start
    seen = {start}
    while current != target:
        successors = successor_map(workflow_version_id).get(current, ())
        if target in successors:
            path.append(target)
            return path
        if len(successors) != 1:
            return None
        nxt = successors[0]
        if nxt in seen:
            return None
        seen.add(nxt)
        path.append(nxt)
        current = nxt
        if len(path) > 32:
            return None
    return path


def _receipt_for_interrupt_identity(
    interrupt: Mapping[str, Any] | dict[str, Any],
    *,
    predecessor_node_id: str,
    attempt: int,
    artifact_receipt_ids: tuple[str, ...],
    execution_anchor_id: str | None,
    completed_at_ms: int,
) -> ExecutionReceipt:
    """Build a succeeded receipt that matches the visible interrupt payload."""
    run_id = str(interrupt.get("runId") or "")
    action_id = str(interrupt.get("actionId") or "") or action_id_for(
        run_id, predecessor_node_id, attempt
    )
    node_run_id = str(interrupt.get("nodeRunId") or "") or (
        f"nr-{run_id}-{predecessor_node_id}-a{attempt}"
    )
    return ExecutionReceipt(
        action_id=action_id,
        node_run_id=node_run_id,
        outcome="succeeded",
        artifact_receipt_ids=artifact_receipt_ids,
        execution_anchor_id=execution_anchor_id,
        budget_receipt_id=None,
        problem=None,
        completed_at_ms=completed_at_ms,
    )


def _is_deterministic_resume_error(exc: BaseException) -> bool:
    """True when retrying this graph dispatch can never succeed.

    Covers: receipt/checkpoint identity drift, and multi-interrupt
    checkpoints where the resume could not be narrowed to one interrupt id
    (langgraph's "multiple pending interrupts" rejection or the coordinator's
    AmbiguousInterruptResumeError).  These are deterministic programming /
    state errors — they must terminate on the first pass instead of burning
    the transient budget; recovery goes through heal / time-travel
    (restart_attempt) and reconcile_run.
    """
    text = str(exc).lower()
    return (
        "execution receipt identity mismatch" in text
        or "multiple pending interrupts" in text
    )


def _graph_at_node(snapshot: dict[str, Any], node_id: str) -> bool:
    """True only when the thread is interrupted at ``node_id``.

    ``values.active_node_id`` is not enough: Command.goto can write it while
    the persisted interrupt stays on an upstream node.
    """
    wanted = str(node_id or "").strip()
    if not wanted:
        return False
    next_ids = [str(item) for item in (snapshot.get("nextNodeIds") or [])]
    pending = snapshot.get("pendingAction") or {}
    interrupt_node = str(pending.get("nodeId") or "")
    return wanted in next_ids or interrupt_node == wanted


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


def _canonical_json_text(value: str) -> str:
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return str(value)
    return json.dumps(
        decoded,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _event_replay_identity(event: Any) -> tuple[Any, ...]:
    """Semantic identity required before a deterministic event replay."""

    return (
        event.run_id,
        event.sequence,
        event.event_id,
        event.run_version,
        event.event_type,
        _canonical_json_text(event.actor_json),
        event.correlation_id,
        # Historical writers may have persisted an explicit empty string.
        # Keep those rows readable, but never equate that value with None,
        # which records that no causation identity was supplied.
        event.causation_id,
        _canonical_json_text(event.payload_json),
    )


def _is_legacy_graph_repair_replay(
    event: Any,
    *,
    run_id: str,
    sequence: int,
    run_version: int,
    event_id: str,
) -> bool:
    """Accept only the two known pre-replay graph-repair event shapes.

    Older ledger writers used the generic ``ledger`` actor and ``corr-1``
    correlation marker.  They persisted either the sequence-only fixture
    payload or the earlier terminal marker.  This compatibility path is
    intentionally narrower than the normal semantic replay guard: every
    identity field is still fixed, causation remains strictly absent, and
    the payload must be one of the historical canonical objects.
    """

    if (
        event.run_id != run_id
        or event.sequence != sequence
        or event.event_id != event_id
        or event.run_version != run_version
        or event.event_type != "run_failed"
        or event.correlation_id != "corr-1"
        or event.causation_id is not None
    ):
        return False
    try:
        actor = json.loads(event.actor_json)
        payload = json.loads(event.payload_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    return (
        actor == {"actorType": "system", "actorId": "ledger"}
        and payload
        in (
            {"sequence": sequence},
            {"terminalReason": "dispatch_never_started"},
        )
    )


def _adapter_dispatch_record(
    *,
    pending: Any,
    run_id: str,
    command_id: str | None,
    now_ms: int,
    node_run_id: str | None = None,
):
    from core.research.workflow.ledger import OutboxRecord

    return OutboxRecord(
        action_id=new_id("act"),
        run_id=run_id,
        command_id=command_id,
        node_run_id=str(node_run_id or pending.node_run_id),
        action_kind="adapter_dispatch",
        idempotency_key=f"adapter:{pending.action_id}",
        payload_json=json.dumps(pending.to_dict(), ensure_ascii=False),
        status="pending",
        attempt_count=0,
        available_at_ms=now_ms,
        lease_owner=None,
        lease_expires_at_ms=None,
        last_problem_json=None,
        created_at_ms=now_ms,
        updated_at_ms=now_ms,
    )


def _ensure_adapter_dispatch(
    uow: Any,
    *,
    pending: Any,
    run_id: str,
    command_id: str | None,
    node_run_id: str,
    now_ms: int,
) -> bool:
    """Insert or revive adapter_dispatch. True when a row was written/revived."""
    resolved_command_id = str(command_id or "").strip()
    if not resolved_command_id:
        raise RuntimeError("adapter_dispatch requires command_id")
    key = f"adapter:{pending.action_id}"
    existing = uow.repository.execute(
        "SELECT action_id, status FROM outbox_actions WHERE idempotency_key = ?",
        (key,),
    ).fetchone()
    if existing is not None:
        status = str(existing[1] or "")
        if status in {"pending", "leased", "succeeded"}:
            return False
        uow.repository.execute(
            """
            UPDATE outbox_actions
            SET status = 'pending',
                lease_owner = NULL,
                lease_expires_at_ms = NULL,
                available_at_ms = ?,
                updated_at_ms = ?,
                last_problem_json = NULL,
                command_id = ?,
                node_run_id = ?
            WHERE action_id = ?
            """,
            (now_ms, now_ms, resolved_command_id, node_run_id, existing[0]),
        )
        return True
    uow.repository.insert_outbox(
        _adapter_dispatch_record(
            pending=pending,
            run_id=run_id,
            command_id=resolved_command_id,
            now_ms=now_ms,
            node_run_id=node_run_id,
        )
    )
    return True


def _pending_from_dispatching_row(row: Any) -> PendingAction | None:
    from core.research.workflow.models import ActorKind

    action_id = str(row[8] or "").strip()
    node_id = str(row[2] or "").strip()
    actor_kind_raw = str(row[4] or "").strip()
    if not action_id or not node_id or not actor_kind_raw:
        return None
    actor_kind = ActorKind(actor_kind_raw)
    if actor_kind is ActorKind.AGENT:
        action_kind = "start_agent_task"
    elif actor_kind is ActorKind.SYSTEM:
        action_kind = f"system_action:{node_id}"
    else:
        action_kind = f"human_task:{node_id}"
    return PendingAction(
        action_id=action_id,
        run_id=str(row[1]),
        node_run_id=str(row[0]),
        node_id=node_id,
        attempt=int(row[3] or 0),
        actor_kind=actor_kind,
        action_kind=action_kind,
        input_snapshot_hash=str(row[7] or ""),
        input_artifact_refs=(),
        binding_snapshot_id=row[6],
        budget_policy_hash="",
        scope={
            "version": 3,
            "kind": "workflow_node_root",
            "workflowRunId": str(row[1]),
            "workflowNodeId": node_id,
        },
    )
