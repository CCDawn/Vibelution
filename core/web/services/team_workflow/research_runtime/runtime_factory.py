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
from .command_service import WorkflowCommandService
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

    def run_workers_once(self, limit: int = 4) -> int:
        handled = self.graph_worker.run_once(limit=limit)
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

    command_service = WorkflowCommandService(
        store=store,
        readiness_service=readiness,
        readiness_context=lambda: readiness_context,
        clock=clock,
        wake_worker=wake_worker,
    )
    graph_worker = GraphDispatchWorker(
        store=store,
        coordinator=coordinator,
        owner_id="graph-worker",
        readiness_service=readiness,
        readiness_context=lambda: readiness_context,
    )
    adapter_worker = AdapterDispatchWorker(
        store=store,
        registry=registry,
        ports=ports,
        owner_id="adapter-worker",
        successor_fn=lambda node_id: successor_map().get(node_id, ()),
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
    )
