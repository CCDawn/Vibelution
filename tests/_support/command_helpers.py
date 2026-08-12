"""Shared harness for T3 command-service tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.research.workflow.contracts import ActorRef, CommandRequest, WorkflowCommandKind
from core.research.workflow.ledger import WorkflowLedgerStore

from core.web.services.team_workflow.research_runtime.command_service import WorkflowCommandService
from core.web.services.team_workflow.research_runtime.readiness import NodeReadinessService
from core.web.services.team_workflow.research_runtime.readiness.common import RunSnapshot

from tests._support.readiness_fakes import FakeDomainContext
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_event_record,
    build_run_record,
    open_ledger_store,
)


class CommandHarness:
    def __init__(self, path: Path, *, context: FakeDomainContext | None = None) -> None:
        self.store = open_ledger_store(path)
        self.context = context or FakeDomainContext()
        self.wake_count = 0

        def wake() -> None:
            self.wake_count += 1

        def run_source(run_id: str) -> RunSnapshot | None:
            record = self.store.get_run(run_id)
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
            latest = self.store.latest_attempt(run_id, node_id)
            if latest is not None and latest.status in (
                "starting",
                "dispatching",
                "running",
                "waiting_human",
            ):
                return 1
            return 0

        self.readiness = NodeReadinessService(
            run_source=run_source,
            attempt_count_source=attempt_count_source,
        )
        self.service = WorkflowCommandService(
            store=self.store,
            readiness_service=self.readiness,
            readiness_context=lambda: self.context,
            clock=lambda: FIXED_NOW_MS + 1000,
            wake_worker=wake,
        )

    def close(self) -> None:
        self.store.close()

    def seed_run(self, run_id: str = "run-test", **overrides: Any) -> None:
        record = build_run_record(run_id=run_id, last_event_sequence=1, **overrides)
        store = self.store

        def mutate(uow):
            uow.repository.insert_run(record)
            uow.repository.insert_event(
                build_event_record(
                    sequence=1,
                    run_id=run_id,
                    event_type="run_created",
                    event_id=f"evt-created-{run_id}",
                )
            )

        store.submit(mutate, force_flush=True).result(timeout=10)

    def request(
        self,
        *,
        command: WorkflowCommandKind = WorkflowCommandKind.START_NODE,
        node_id: str | None = "source_finding",
        run_id: str = "run-test",
        team_id: str = "research-team",
        expected_run_version: int = 1,
        idempotency_key: str = "ui:key-1",
        payload: dict[str, Any] | None = None,
    ) -> CommandRequest:
        return CommandRequest(
            command_id="cmd-client-placeholder",
            run_id=run_id,
            team_id=team_id,
            command=command,
            node_id=node_id,
            expected_run_version=expected_run_version,
            idempotency_key=idempotency_key,
            payload=payload or {},
            requested_by=ActorRef("user", "u-1"),
            requested_at_ms=FIXED_NOW_MS,
        )
