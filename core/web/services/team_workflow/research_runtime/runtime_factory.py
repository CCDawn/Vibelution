"""Runtime composition root for the formal research workflow (P1-3).

Wires the Workflow Ledger store, LangGraph coordinator, NodeReadinessService,
real DomainReadinessContext, real DomainPorts and the graph/adapter workers so
the production runtime never composes itself inside a worker or route.
"""

from __future__ import annotations

import logging
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


def production_workflow_runtime() -> WorkflowRuntime | None:
    return _PRODUCTION


def wake_production_workflow_runtime() -> bool:
    pump = _PUMP
    if pump is None:
        return False
    pump.wake()
    return True


def start_production_workflow_runtime() -> str:
    """Open the Ledger-backed runtime or fail closed (no JSON fallback)."""
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

    if _PRODUCTION is not None:
        return "ready"
    data_root = research_workflow_data_root()
    data_root.mkdir(parents=True, exist_ok=True)
    if legacy_json_runs_exist(data_root) and not is_activated(data_root):
        mark_migration_required()
        return "migration_required"
    pump = WorkflowOutboxPump()
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


def stop_production_workflow_runtime() -> None:
    global _PRODUCTION, _PUMP
    pump = _PUMP
    _PUMP = None
    if pump is not None:
        pump.stop()
    runtime = _PRODUCTION
    _PRODUCTION = None
    if runtime is not None:
        runtime.close()
