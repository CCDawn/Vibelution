"""Runtime composition root for the formal research workflow (P1-3).

Wires the Workflow Ledger store, LangGraph coordinator, NodeReadinessService,
real DomainReadinessContext, real DomainPorts and the graph/adapter workers so
the production runtime never composes itself inside a worker or route.
"""

from __future__ import annotations

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
from .command_service import WorkflowCommandService
from .formal_read_runtime import configure_formal_read_runtime, wake_stream_readers
from .formal_write_runtime import configure_formal_write_runtime
from .graph_dispatch_worker import GraphDispatchWorker
from .real_domain_ports import RealDomainPorts
from .real_readiness_context import RealDomainReadinessContext
from .readiness import NodeReadinessService
from .readiness.common import RunSnapshot


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

    def run_workers_once(self, limit: int = 4) -> int:
        handled = self.fork_worker.run_once(limit=limit)
        handled += self.graph_worker.run_once(limit=limit)
        handled += self.adapter_worker.run_once(limit=limit)
        return handled

    def close(self) -> None:
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
    graph_worker = GraphDispatchWorker(
        store=store,
        coordinator=coordinator,
        owner_id="graph-worker",
        readiness_service=readiness,
        readiness_context=lambda: readiness_context,
        commit_hook=wake_stream_readers,
    )
    adapter_worker = AdapterDispatchWorker(
        store=store,
        registry=registry,
        ports=ports,
        owner_id="adapter-worker",
        successor_fn=lambda node_id: successor_map().get(node_id, ()),
        after_commit_hook=wake_stream_readers,
    )
    fork_worker = CheckpointForkWorker(
        store=store,
        coordinator=coordinator,
        owner_id="checkpoint-fork-worker",
        commit_hook=wake_stream_readers,
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
    )


_PRODUCTION: WorkflowRuntime | None = None


def start_production_workflow_runtime() -> str:
    """Open the Ledger-backed runtime or fail closed (no JSON fallback)."""
    global _PRODUCTION
    from core.research.workflow.migration.manifest import is_activated

    from .formal_write_runtime import mark_migration_required, reset_formal_write_runtime_for_tests
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
    try:
        _PRODUCTION = build_workflow_runtime(workflow_ledger_path(data_root))
    except Exception:
        reset_formal_write_runtime_for_tests()
        return "unavailable"
    return "ready"


def stop_production_workflow_runtime() -> None:
    global _PRODUCTION
    runtime = _PRODUCTION
    _PRODUCTION = None
    if runtime is not None:
        runtime.close()
