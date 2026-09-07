"""Workflow Ledger public facade (mutation + read-only queries)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .database import WorkflowLedgerDatabase
from .errors import WorkflowLedgerClosedError
from .records import (
    CatalogRunAuthorization,
    EventRecord,
    ExternalBatchRegistration,
    NodeAttemptRecord,
    OutboxRecord,
    RunRecord,
)
from .writer import WorkflowLedgerWriter

_read_tls = threading.local()


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

    def renew_outbox_lease_direct(
        self,
        action_id: str,
        owner: str,
        *,
        now_ms: int,
        lease_ms: int,
    ) -> bool | None:
        """Renew one outbox lease on a dedicated short-lived connection.

        Lease-heartbeat renewals are load-bearing keepalives for in-flight
        graph invokes; funneling them through the single-writer queue means a
        deep or stalled queue delays the keepalive past the lease window and
        another worker reclaims a live action. The renewal is one atomic
        UPDATE, so it runs here on its own WAL connection outside the queue.

        Tri-state result so callers can separate the two failure modes:

        - ``True`` — renewed; the owner still holds the lease;
        - ``False`` — definitive loss: the UPDATE affected 0 rows, so the
          lease was reclaimed or already expired;
        - ``None`` — transient miss (writer contention past the busy
          timeout, connection error, store closed): the lease state is
          unknown and the window outlives several such misses."""
        if self._closed:
            return None
        from .repository import WorkflowLedgerRepository

        connection = self._database.open_writer()
        try:
            repository = WorkflowLedgerRepository(connection)
            return bool(
                repository.renew_outbox_lease(action_id, owner, now_ms, lease_ms)
            )
        except Exception:
            return None
        finally:
            try:
                connection.close()
            except Exception:
                pass

    # ------------------------------------------------------- read-only

    def get_run(self, run_id: str) -> RunRecord | None:
        return self.read(lambda repo: repo.get_run(run_id))

    def list_runs_for_team(self, team_id: str, workflow_id: str) -> list[RunRecord]:
        return self.read(lambda repo: repo.list_runs_for_team(team_id, workflow_id))

    def get_catalog_run_authorization(
        self, authorization_id: str
    ) -> CatalogRunAuthorization | None:
        return self.read(
            lambda repo: repo.get_catalog_run_authorization(authorization_id)
        )

    def find_catalog_run_authorization(
        self,
        *,
        team_id: str,
        plan_id: str,
        scope_hash: str,
        readiness_report_sha256: str,
    ) -> CatalogRunAuthorization | None:
        return self.read(
            lambda repo: repo.find_catalog_run_authorization(
                team_id=team_id,
                plan_id=plan_id,
                scope_hash=scope_hash,
                readiness_report_sha256=readiness_report_sha256,
            )
        )

    def list_catalog_run_authorizations(
        self, team_id: str, plan_id: str | None = None
    ) -> list[CatalogRunAuthorization]:
        return self.read(
            lambda repo: repo.list_catalog_run_authorizations(team_id, plan_id)
        )

    def get_command_by_idempotency(self, run_id: str, idempotency_key: str):
        return self.read(
            lambda repo: repo.find_command_by_idempotency(run_id, idempotency_key)
        )

    def list_events(
        self, run_id: str, after_sequence: int = 0, limit: int = 500
    ) -> list[EventRecord]:
        return self.read(
            lambda repo: repo.list_events(run_id, after_sequence, limit)
        )

    def get_event_by_id(self, event_id: str) -> EventRecord | None:
        return self.read(lambda repo: repo.get_event_by_id(event_id))

    def latest_event_sequence(self, run_id: str) -> int:
        return self.read(lambda repo: repo.latest_event_sequence(run_id))

    def list_attempts(self, run_id: str) -> list[NodeAttemptRecord]:
        return self.read(lambda repo: repo.list_attempts(run_id))

    def latest_attempt(self, run_id: str, node_id: str) -> NodeAttemptRecord | None:
        return self.read(lambda repo: repo.latest_attempt(run_id, node_id))

    def list_attempts_for_all(self, run_ids: list[str]) -> list[NodeAttemptRecord]:
        def load(repo):
            records: list[NodeAttemptRecord] = []
            for run_id in run_ids:
                records.extend(repo.list_attempts(run_id))
            return records

        return self.read(load)

    def list_pending_outbox(
        self, run_id: str | None = None, limit: int = 200
    ) -> list[OutboxRecord]:
        return self.read(lambda repo: repo.list_pending_outbox(run_id, limit))

    # ------------------------------------------------- external batches

    def register_external_batch(
        self, batch: ExternalBatchRegistration
    ) -> tuple[ExternalBatchRegistration, bool]:
        """Register one external batch (idempotent on its manifest hash).

        Returns ``(record, created)``.  When the same
        (plane, layer, manifest_sha256) triple already exists the existing
        row is returned with ``created=False`` — the caller-supplied
        ``batch_id`` is discarded in favour of the registered one.
        """

        def _write(uow):
            repo = uow.repository
            created = repo.insert_external_batch(batch)
            if created:
                return batch, True
            existing = repo.find_external_batch_by_manifest(
                plane=batch.plane,
                layer=batch.layer,
                manifest_sha256=batch.manifest_sha256,
            )
            if existing is None:  # pragma: no cover — conflict implies a row
                raise RuntimeError(
                    "external batch conflict reported but row not found"
                )
            return existing, False

        future = self.submit(_write, force_flush=True)
        return future.result(timeout=30)

    def get_external_batch(
        self, batch_id: str
    ) -> ExternalBatchRegistration | None:
        return self.read(lambda repo: repo.get_external_batch(batch_id))

    def find_external_batch_by_manifest(
        self, *, plane: str, layer: str, manifest_sha256: str
    ) -> ExternalBatchRegistration | None:
        return self.read(
            lambda repo: repo.find_external_batch_by_manifest(
                plane=plane, layer=layer, manifest_sha256=manifest_sha256
            )
        )

    def list_external_batches(
        self,
        *,
        plane: str | None = None,
        layer: str | None = None,
        limit: int = 200,
    ) -> list[ExternalBatchRegistration]:
        return self.read(
            lambda repo: repo.list_external_batches(
                plane=plane, layer=layer, limit=limit
            )
        )

    def read(self, fn: Callable[[Any], Any]) -> Any:
        """Run callback inside one explicit read transaction (SQLite snapshot).

        Nested ``read()`` calls on the same thread reuse the open snapshot instead
        of starting a second transaction on the pooled connection.
        """
        depth = int(getattr(_read_tls, "depth", 0) or 0)
        if depth > 0:
            connection = _read_tls.connection
            return fn(self._repository(connection))

        connection = self._database.acquire_read_connection()
        _read_tls.connection = connection
        _read_tls.depth = 1
        try:
            connection.execute("BEGIN")
            try:
                result = fn(self._repository(connection))
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            else:
                connection.execute("COMMIT")
                return result
        finally:
            _read_tls.depth = 0
            _read_tls.connection = None
            self._database.release_read_connection(connection)

    @staticmethod
    def _repository(connection: Any):
        from .repository import WorkflowLedgerRepository

        return WorkflowLedgerRepository(connection)
