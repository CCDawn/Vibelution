"""Runtime composition root for the formal research workflow (P1-3).

Wires the Workflow Ledger store, LangGraph coordinator, NodeReadinessService,
real DomainReadinessContext, real DomainPorts and the graph/adapter workers so
the production runtime never composes itself inside a worker or route.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.research.workflow.challenge_cup_runtime import (
    ChallengeCupGraphCoordinator,
    successor_map,
)
from core.research.workflow.ledger import WorkflowLedgerStore

from .action_registry import ActionRegistry
from .adapter_dispatch_worker import AdapterDispatchWorker
from .adapters.domain_adapters import register_default_adapters
from .checkpoint_fork_worker import CheckpointForkWorker
from .checkpoint_lifecycle import latest_checkpoint_id
from .cancel_run_cleanup import CancelRunCleanupWorker
from .command_service import WorkflowCommandService
from .delivery_worker import DeliveryOrchestrationWorker
from .event_publish_worker import EventPublishWorker
from .formal_read_runtime import configure_formal_read_runtime, wake_stream_readers
from .formal_write_runtime import configure_formal_write_runtime
from .graph_dispatch_worker import GraphDispatchWorker
from .outbox_pump import WorkflowOutboxPump
from .readiness import NodeReadinessService
from .readiness.common import RunSnapshot
from .readiness.knowledge_recheck import build_knowledge_readiness_recheck
from .real_domain_ports import RealDomainPorts
from .real_readiness_context import RealDomainReadinessContext
from .receipt_persistence import ReceiptPersistenceWorker

logger = logging.getLogger(__name__)

# Challenge Cup 10-concurrency plan (B3): the production outbox pump drives
# dispatch with this many parallel worker threads (Temporal-style fixed
# task-queue pollers). ``VIBELUTION_WORKFLOW_WORKERS`` overrides it.
DEFAULT_WORKFLOW_WORKERS = 10
WORKFLOW_WORKERS_ENV = "VIBELUTION_WORKFLOW_WORKERS"

# Budget-exhaustion auto-advance sweep cadence: the maintenance tick runs far
# more often than the scan needs to (same self-throttle pattern as the stuck
# digest watchdog in meeting_driver_work).
AUTO_ADVANCE_SWEEP_INTERVAL_MS = 30_000
AUTO_ADVANCE_SWEEP_INTERVAL_ENV = "VIBELUTION_AUTO_ADVANCE_SWEEP_INTERVAL_MS"
_LAST_AUTO_ADVANCE_SWEEP_MS: int | None = None
_AUTO_ADVANCE_SWEEP_LOCK = threading.Lock()


def _auto_advance_sweep_interval_ms() -> int:
    raw = str(os.environ.get(AUTO_ADVANCE_SWEEP_INTERVAL_ENV) or "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError:
            return AUTO_ADVANCE_SWEEP_INTERVAL_MS
        if value > 0:
            return max(value, 1000)
    return AUTO_ADVANCE_SWEEP_INTERVAL_MS


def _auto_advance_sweep_due(now_ms: int) -> bool:
    global _LAST_AUTO_ADVANCE_SWEEP_MS
    with _AUTO_ADVANCE_SWEEP_LOCK:
        last = _LAST_AUTO_ADVANCE_SWEEP_MS
        if last is not None and now_ms - last < _auto_advance_sweep_interval_ms():
            return False
        _LAST_AUTO_ADVANCE_SWEEP_MS = now_ms
        return True


def reset_auto_advance_sweep_throttle_for_tests() -> None:
    """Test seam: forget the last sweep run so the next tick executes."""
    global _LAST_AUTO_ADVANCE_SWEEP_MS
    with _AUTO_ADVANCE_SWEEP_LOCK:
        _LAST_AUTO_ADVANCE_SWEEP_MS = None


def workflow_worker_count() -> int:
    """Pump dispatch parallelism: env override, clamped to >= 1."""
    raw = os.environ.get(WORKFLOW_WORKERS_ENV, "")
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_WORKFLOW_WORKERS
    return max(1, value)


@dataclass(frozen=True)
class WorkflowRuntime:
    store: WorkflowLedgerStore
    coordinator: ChallengeCupGraphCoordinator
    readiness: NodeReadinessService
    readiness_context: RealDomainReadinessContext
    ports: RealDomainPorts
    registry: ActionRegistry
    command_service: WorkflowCommandService
    graph_worker: GraphDispatchWorker
    adapter_worker: AdapterDispatchWorker
    fork_worker: CheckpointForkWorker
    cancel_run_cleanup_worker: CancelRunCleanupWorker
    receipt_persistence_worker: ReceiptPersistenceWorker
    delivery_worker: DeliveryOrchestrationWorker
    event_publish_worker: EventPublishWorker

    def run_workers_once(self, limit: int = 4) -> int:
        handled = self.fork_worker.run_once(limit=limit)
        handled += self.cancel_run_cleanup_worker.run_once(limit=limit)
        handled += self.receipt_persistence_worker.run_once(limit=limit)
        handled += self.graph_worker.run_once(limit=limit)
        handled += self.adapter_worker.run_once(limit=limit)
        handled += self.event_publish_worker.run_once(limit=limit)
        handled += self.delivery_worker.run_once(limit=limit)
        self._reconcile_expired_task_bundles_best_effort()
        return handled

    def claim_and_run_one(self) -> bool:
        """Claim-and-run exactly ONE dispatch action (parallel worker entry).

        Tries graph_dispatch first, then adapter_dispatch. Claiming is the
        outbox lease CAS inside the single ``BEGIN IMMEDIATE`` writer, so
        two workers can never claim the same action, and all ledger writes
        stay funneled through the one writer queue. Deliberately excludes
        the repair sweeps and the non-dispatch workers: they run on the
        serial maintenance loop (``run_maintenance_once``) because their
        sequence-conflict checks are not designed for concurrent rewrites
        of the same run. Returns True when work was claimed and executed.
        """
        if self.graph_worker.run_claim_one():
            return True
        return self.adapter_worker.run_claim_one()

    def run_maintenance_once(self, limit: int = 4) -> int:
        """Serial driver for the non-dispatch workers + retention sweeps.

        One maintenance thread runs this loop (Challenge Cup 10-concurrency
        B3): fork stays serial because it writes the LangGraph checkpoint
        store that the B4 checkpoint-parallelization task owns; receipt /
        delivery / event / cancel-cleanup are low-frequency with run-level
        side effects; the graph/adapter sweeps rewrite states behind
        sequence-conflict checks.
        """
        handled = self.fork_worker.run_once(limit=limit)
        handled += self.cancel_run_cleanup_worker.run_once(limit=limit)
        handled += self.receipt_persistence_worker.run_once(limit=limit)
        handled += self.event_publish_worker.run_once(limit=limit)
        handled += self.delivery_worker.run_once(limit=limit)
        handled += self.graph_worker.run_repairs_once()
        handled += self.adapter_worker.run_repairs_once(limit=limit)
        self._reconcile_expired_task_bundles_best_effort()
        self._sweep_stuck_digest_works_best_effort()
        self._refresh_queued_meeting_activity_best_effort()
        self._sweep_auto_advance_closure_best_effort()
        return handled

    def _reconcile_expired_task_bundles_best_effort(self) -> None:
        """Enforce task-bundle ``deadlineSeconds`` from the resident tick.

        ``reconcile_task_bundles`` had no periodic caller, so bundle deadlines
        never fired. ``run_workers_once`` is the one loop the production pump
        (WorkflowOutboxPump) and every test drain already drive, so it is the
        minimal-intrusion host: no worker constructor or recently changed
        adapter/graph worker changes hands. The domain service is peeked (not
        created) so runtimes composed without it stay inert, and any reconcile
        failure is swallowed after logging — deadline enforcement must never
        break dispatch.
        """
        try:
            from .service import peek_research_workflow_runtime_service

            service = peek_research_workflow_runtime_service()
            if service is not None:
                service.reconcile_all_expired_task_bundles()
        except Exception:  # noqa: BLE001 - deadline repair is best-effort
            logger.exception("task bundle deadline reconciliation failed")

    def _sweep_stuck_digest_works_best_effort(self) -> None:
        """Fail stuck in-process digest intents from the serial maintenance tick.

        The 2026-09 ghost-lock incident left ``run_digest`` work running
        forever with only a backend restart to recover it.  The maintenance
        loop is the resident serial host (same minimal-intrusion pattern as
        the task-bundle reconcile): the meeting-driver watchdog is peeked
        (not created), self-throttled, and never re-drives — it only fences
        digest work whose bounded fence has passed and exposes the meeting's
        retry entry.  Any failure is swallowed after logging.
        """
        try:
            from core.web.services.team_workflow import meeting_driver_work

            meeting_driver_work.sweep_stuck_digest_works()
        except Exception:  # noqa: BLE001 - watchdog must never break maintenance
            logger.exception("stuck digest work sweep failed")

    def _refresh_queued_meeting_activity_best_effort(self) -> None:
        """Renew queued discussion drivers' meeting activity from this tick.

        The 4-worker meeting executor queues scheduled discussion drivers with
        no activity by design, and a multi-question fan-out can hold a driver
        there far past the 15-minute execution-heartbeat window the V2
        projection uses to flag zombie meetings and expose ``reopen_review``
        for a healthy meeting.  The queue sweep is peeked (not created),
        self-throttled, and only stamps meeting activity for meetings whose
        driver intent is still ``pending`` — a wedged RUNNING driver keeps
        going stale.  Same discipline as the digest watchdog: never re-drives,
        any failure is swallowed after logging.
        """
        try:
            from core.web.services.team_workflow import meeting_driver_work

            meeting_driver_work.refresh_queued_meeting_activity()
        except Exception:  # noqa: BLE001 - queue sweep must never break maintenance
            logger.exception("queued meeting activity refresh failed")

    def _sweep_auto_advance_closure_best_effort(self) -> None:
        """Auto-advance budget-exhausted hypothesis chains from this tick.

        Backlog recovery: chains that exhausted the review-round budget before
        the in-place close hook existed (or whose process died between closure
        and advance) are picked up here — the sweep reuses the chain's own
        idempotent helpers (adjudicate accepted, then create + auto-start the
        formal run), so replays converge instead of duplicating.  Hosted on
        the serial maintenance tick with the same peek + self-throttle
        discipline as the digest watchdog; never raises, never re-drives.
        """
        now_ms = int(time.time() * 1000)
        if not _auto_advance_sweep_due(now_ms):
            return
        try:
            from . import hypothesis_first_chain

            summary = hypothesis_first_chain.sweep_auto_advance_closure()
            if int(summary.get("adjudicated") or 0) or int(
                summary.get("formalRuns") or 0
            ):
                logger.info(
                    "auto-advance closure sweep advanced %s adjudication(s) "
                    "and %s formal run(s)",
                    summary.get("adjudicated"),
                    summary.get("formalRuns"),
                )
        except Exception:  # noqa: BLE001 - sweep must never break maintenance
            logger.exception("auto-advance closure sweep failed")

    def close(self) -> None:
        from .budget_window_resolver import (
            release_budget_window_resolver_for_store,
        )

        release_budget_window_resolver_for_store(self.store)
        self.store.close()


def build_workflow_runtime(
    ledger_path: Path,
    *,
    checkpoint_path: Path | str | None = None,
    read_pool_capacity: int = 4,
    domain_overrides: dict[str, Any] | None = None,
    agent_task_factory: Any | None = None,
    clock: Callable[[], int] | None = None,
    wake_worker: Callable[[], None] | None = None,
) -> WorkflowRuntime:
    """Assemble the production runtime from the Ledger and LangGraph pieces."""
    checkpoint = Path(checkpoint_path) if checkpoint_path else (
        ledger_path.parent / "checkpoints.sqlite"
    )
    coordinator = ChallengeCupGraphCoordinator(checkpoint)

    store = WorkflowLedgerStore(
        ledger_path,
        queue_size=2048,
        enqueue_timeout_ms=250,
        read_pool_capacity=read_pool_capacity,
    )
    store.open()

    def run_source(run_id: str) -> RunSnapshot | None:
        record = store.get_run(run_id)
        if record is None:
            return None
        return RunSnapshot(
            run_id=record.run_id,
            team_id=record.team_id,
            workflow_id=record.workflow_id,
            workflow_version_id=record.workflow_version_id,
            project_id=record.project_id,
            question_id=record.question_id,
            status=record.status,
            run_version=record.run_version,
            input_snapshot_hash=record.input_snapshot_hash,
        )

    def attempt_count_source(run_id: str, node_id: str) -> int:
        latest = store.latest_attempt(run_id, node_id)
        if latest is not None and latest.status in (
            "starting",
            "dispatching",
            "running",
            "waiting_human",
        ):
            return 1
        return 0

    readiness = NodeReadinessService(
        run_source=run_source,
        attempt_count_source=attempt_count_source,
    )

    registry = ActionRegistry()
    ports = RealDomainPorts(
        store,
        agent_task_factory=agent_task_factory,
        budget_policy_hash="",
    )
    register_default_adapters(registry, ports)
    # Dependency inversion for the session-side budget preflight: inject a
    # resolver bound to THIS runtime's Ledger store so embedded runtimes
    # (tests, tooling) resolve the budget authority without registering the
    # production singleton. The production startup path also assembles through
    # this function, so the injection covers both. The most recently assembled
    # runtime wins; close() releases the injection when it is still current.
    from .budget_authority_adapter import read_node_budget_window
    from .budget_window_resolver import configure_budget_window_resolver

    def owned_budget_window_resolver(
        run_id: str, node_run_id: str, reservation_id: str
    ) -> dict[str, Any]:
        return read_node_budget_window(
            store, run_id, node_run_id, reservation_id
        )

    configure_budget_window_resolver(
        owned_budget_window_resolver,
        store=store,
    )
    readiness_context = RealDomainReadinessContext(
        store,
        adapter_registry=registry,
        service_overrides=domain_overrides,
    )

    # Formal read must be configured before wake paths reference the stream notifier.
    configure_formal_read_runtime(
        store=store,
        readiness_service=readiness,
        readiness_context=lambda: readiness_context,
        revise_checkpoint_resolver=lambda thread_id: latest_checkpoint_id(
            str(checkpoint), thread_id
        ),
    )

    def combined_wake() -> None:
        if wake_worker is not None:
            wake_worker()
        wake_stream_readers()

    command_service = WorkflowCommandService(
        store=store,
        readiness_service=readiness,
        readiness_context=lambda: readiness_context,
        clock=clock,
        wake_worker=combined_wake,
        coordinator_factory=lambda: coordinator,
    )
    configure_formal_write_runtime(store=store, command_service=command_service)
    from .knowledge_sideflow_trigger import KnowledgeSideflowTrigger

    knowledge_sideflow_trigger = KnowledgeSideflowTrigger(
        store=store,
        command_service=command_service,
        now_provider=clock,
    )
    graph_worker = GraphDispatchWorker(
        store=store,
        coordinator=coordinator,
        owner_id="graph-worker",
        readiness_service=readiness,
        readiness_context=lambda: readiness_context,
        commit_hook=combined_wake,
        node_success_hook=knowledge_sideflow_trigger.on_node_succeeded,
    )
    adapter_worker = AdapterDispatchWorker(
        store=store,
        registry=registry,
        ports=ports,
        owner_id="adapter-worker",
        successor_fn=lambda node_id: successor_map().get(node_id, ()),
        after_commit_hook=combined_wake,
    )
    fork_worker = CheckpointForkWorker(
        store=store,
        coordinator=coordinator,
        owner_id="checkpoint-fork-worker",
        commit_hook=combined_wake,
    )
    cancel_run_cleanup_worker = CancelRunCleanupWorker(
        store=store,
        owner_id="cancel-run-cleanup-worker",
        now_provider=clock,
    )
    receipt_persistence_worker = ReceiptPersistenceWorker(
        store=store,
        owner_id="receipt-persistence-worker",
        now_provider=clock,
    )
    delivery_worker = DeliveryOrchestrationWorker(
        store=store,
        owner_id="delivery-worker",
        commit_hook=combined_wake,
    )
    event_publish_worker = EventPublishWorker(
        store=store,
        owner_id="event-publish-worker",
        commit_hook=combined_wake,
        readiness_recheck=build_knowledge_readiness_recheck(
            store=store,
            command_service=command_service,
            readiness_invalidate=readiness.invalidate,
            now_provider=clock,
        ),
    )
    return WorkflowRuntime(
        store=store,
        coordinator=coordinator,
        readiness=readiness,
        readiness_context=readiness_context,
        ports=ports,
        registry=registry,
        command_service=command_service,
        graph_worker=graph_worker,
        adapter_worker=adapter_worker,
        fork_worker=fork_worker,
        cancel_run_cleanup_worker=cancel_run_cleanup_worker,
        receipt_persistence_worker=receipt_persistence_worker,
        delivery_worker=delivery_worker,
        event_publish_worker=event_publish_worker,
    )


_PRODUCTION: WorkflowRuntime | None = None
_PUMP: WorkflowOutboxPump | None = None
# Serializes the whole start/stop sequence (check → build → assign → close).
# The singleton check-then-act used to be lock-free, so concurrent starts
# could build two WorkflowLedgerStores plus two pump threads on the same
# ledger file, and a start×stop interleave could leave an old pump draining
# a store another thread had already closed (WorkflowLedgerClosedError).
_LIFECYCLE_LOCK = threading.Lock()


class ProductionRuntimeBusyError(RuntimeError):
    """A concurrent start collided with an in-flight start/stop sequence.

    Fail-closed on purpose: the caller must not assume a runtime came up on
    this thread while another thread is mid-start or mid-stop. Retry after
    the in-flight transition settles.
    """

    code = "production_workflow_runtime_busy"

    def __init__(self) -> None:
        super().__init__(
            "production workflow runtime start collided with an in-flight "
            "start/stop on another thread"
        )


def production_workflow_runtime() -> WorkflowRuntime | None:
    return _PRODUCTION


def wake_production_workflow_runtime() -> bool:
    pump = _PUMP
    if pump is None:
        return False
    pump.wake()
    return True


def start_production_workflow_runtime() -> str:
    """Open the Ledger-backed runtime or fail closed (no JSON fallback).

    The singleton build is serialized behind ``_LIFECYCLE_LOCK``. A start
    that races an in-flight start/stop fails closed with
    ``ProductionRuntimeBusyError`` instead of blocking; a start against an
    already-ready runtime stays idempotent and returns ``"ready"``.
    """
    global _PRODUCTION, _PUMP
    from core.research.workflow.migration.manifest import is_activated

    from .formal_write_runtime import (
        mark_migration_required,
        reset_formal_write_runtime_for_tests,
    )
    from .paths import (
        legacy_json_runs_exist,
        research_workflow_data_root,
        workflow_ledger_path,
    )

    if not _LIFECYCLE_LOCK.acquire(blocking=False):
        raise ProductionRuntimeBusyError()
    try:
        if _PRODUCTION is not None:
            return "ready"
        data_root = research_workflow_data_root()
        data_root.mkdir(parents=True, exist_ok=True)
        if legacy_json_runs_exist(data_root) and not is_activated(data_root):
            mark_migration_required()
            return "migration_required"
        pump = WorkflowOutboxPump(workers=workflow_worker_count())
        try:
            _PRODUCTION = build_workflow_runtime(
                workflow_ledger_path(data_root),
                wake_worker=pump.wake,
            )
        except Exception:
            reset_formal_write_runtime_for_tests()
            return "unavailable"
        pump.attach(_PRODUCTION)
        _PUMP = pump
        return "ready"
    finally:
        _LIFECYCLE_LOCK.release()


def stop_production_workflow_runtime() -> None:
    global _PRODUCTION, _PUMP
    with _LIFECYCLE_LOCK:
        pump = _PUMP
        _PUMP = None
        if pump is not None:
            # Drain the pump while still holding the lock: a start racing
            # this stop must not build a new runtime until the old pump
            # thread is joined, so no pump can outlive its store's close().
            pump.stop()
        runtime = _PRODUCTION
        _PRODUCTION = None
        if runtime is not None:
            runtime.close()
