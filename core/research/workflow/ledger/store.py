"""Workflow Ledger public facade (mutation + read-only queries)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .database import WorkflowLedgerDatabase
from .errors import WorkflowLedgerClosedError
from .records import EventRecord, NodeAttemptRecord, OutboxRecord, RunRecord
from .writer import WorkflowLedgerWriter


class WorkflowLedgerStore:
    """Single-writer mutation facade plus pooled read-only queries."""

    def __init__(
        self,
        path: Path,
        *,
        busy_timeout_ms: int = 5000,
        read_pool_capacity: int = 4,
        queue_size: int = 2048,
        enqueue_timeout_ms: int = 250,
    ) -> None:
        self._database = WorkflowLedgerDatabase(
            Path(path),
            busy_timeout_ms=busy_timeout_ms,
            read_pool_capacity=read_pool_capacity,
        )
        self._writer: WorkflowLedgerWriter | None = None
        self._queue_size = queue_size
        self._enqueue_timeout_ms = enqueue_timeout_ms
        self._closed = False

    @property
    def path(self) -> Path:
        return self._database.path

    def initialize(self) -> dict[str, object]:
        return self._database.initialize()

    def open(self) -> None:
        self.initialize()
        self._writer = WorkflowLedgerWriter(
            self._database,
            queue_size=self._queue_size,
            enqueue_timeout_ms=self._enqueue_timeout_ms,
        )
        self._writer.start()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        writer = self._writer
        if writer is not None:
            writer.close()
            self._writer = None
        self._database.close()

    def submit(self, fn: Callable[[Any], Any], *, force_flush: bool = False) -> Any:
        if self._writer is None or self._closed:
            raise WorkflowLedgerClosedError("workflow ledger store is not open")
        return self._writer.submit(fn, force_flush=force_flush)

    # ------------------------------------------------------- read-only

    def get_run(self, run_id: str) -> RunRecord | None:
        connection = self._database.acquire_read_connection()
        try:
            return self._repository(connection).get_run(run_id)
        finally:
            self._database.release_read_connection(connection)

    def get_command_by_idempotency(self, run_id: str, idempotency_key: str):
        from .repository import WorkflowLedgerRepository

        connection = self._database.acquire_read_connection()
        try:
            return WorkflowLedgerRepository(connection).find_command_by_idempotency(
                run_id, idempotency_key
            )
        finally:
            self._database.release_read_connection(connection)

    def list_events(self, run_id: str, after_sequence: int = 0, limit: int = 500) -> list[EventRecord]:
        connection = self._database.acquire_read_connection()
        try:
            return self._repository(connection).list_events(run_id, after_sequence, limit)
        finally:
            self._database.release_read_connection(connection)

    def latest_event_sequence(self, run_id: str) -> int:
        connection = self._database.acquire_read_connection()
        try:
            return self._repository(connection).latest_event_sequence(run_id)
        finally:
            self._database.release_read_connection(connection)

    def list_attempts(self, run_id: str) -> list[NodeAttemptRecord]:
        connection = self._database.acquire_read_connection()
        try:
            return self._repository(connection).list_attempts(run_id)
        finally:
            self._database.release_read_connection(connection)

    def latest_attempt(self, run_id: str, node_id: str) -> NodeAttemptRecord | None:
        connection = self._database.acquire_read_connection()
        try:
            return self._repository(connection).latest_attempt(run_id, node_id)
        finally:
            self._database.release_read_connection(connection)

    def list_pending_outbox(self, run_id: str | None = None, limit: int = 200) -> list[OutboxRecord]:
        connection = self._database.acquire_read_connection()
        try:
            return self._repository(connection).list_pending_outbox(run_id, limit)
        finally:
            self._database.release_read_connection(connection)

    @staticmethod
    def _repository(connection: Any):
        from .repository import WorkflowLedgerRepository

        return WorkflowLedgerRepository(connection)
