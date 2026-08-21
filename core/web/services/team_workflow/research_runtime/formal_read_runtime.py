"""Process-local formal read runtime (Query / Event / SSE).

Routes depend on this facade. When unset, reads fail closed with
workflow_ledger_unavailable — never fall back to legacy JSON stores.
"""

from __future__ import annotations

import threading
from typing import Any

from core.research.workflow.ledger import WorkflowLedgerStore

from .event_replay_service import WorkflowEventReplayService
from .event_stream_service import LocalStreamNotifier, WorkflowEventStreamService
from .query_service import WorkflowQueryService
from .readiness import NodeReadinessService

_LOCK = threading.Lock()
_QUERY: WorkflowQueryService | None = None
_REPLAY: WorkflowEventReplayService | None = None
_STREAM: WorkflowEventStreamService | None = None
_STORE: WorkflowLedgerStore | None = None


class FormalReadRuntimeUnavailable(RuntimeError):
    code = "workflow_ledger_unavailable"

    def __init__(self, detail: str = "formal workflow read runtime is not configured") -> None:
        super().__init__(detail)
        self.code = "workflow_ledger_unavailable"


def configure_formal_read_runtime(
    *,
    store: WorkflowLedgerStore,
    readiness_service: NodeReadinessService,
    readiness_context: Any,
    clock_iso: Any | None = None,
    evaluated_at_ms: Any | None = None,
    revise_checkpoint_resolver: Any | None = None,
) -> None:
    global _QUERY, _REPLAY, _STREAM, _STORE
    with _LOCK:
        _STORE = store
        _QUERY = WorkflowQueryService(
            store=store,
            readiness_service=readiness_service,
            readiness_context=readiness_context,
            clock_iso=clock_iso,
            evaluated_at_ms=evaluated_at_ms,
            revise_checkpoint_resolver=revise_checkpoint_resolver,
        )
        _REPLAY = WorkflowEventReplayService(store=store)
        _STREAM = WorkflowEventStreamService(store=store, notifier=LocalStreamNotifier())


def reset_formal_read_runtime_for_tests(
    *,
    store: WorkflowLedgerStore | None = None,
    readiness_service: NodeReadinessService | None = None,
    readiness_context: Any | None = None,
) -> None:
    global _QUERY, _REPLAY, _STREAM, _STORE
    with _LOCK:
        _QUERY = None
        _REPLAY = None
        _STREAM = None
        _STORE = None
    if store is not None and readiness_service is not None and readiness_context is not None:
        configure_formal_read_runtime(
            store=store,
            readiness_service=readiness_service,
            readiness_context=readiness_context,
        )


def get_query_service() -> WorkflowQueryService:
    from .formal_write_runtime import WorkflowMigrationRequired, is_migration_required

    with _LOCK:
        if is_migration_required():
            raise WorkflowMigrationRequired()
        if _QUERY is None:
            raise FormalReadRuntimeUnavailable()
        return _QUERY


def get_event_replay_service() -> WorkflowEventReplayService:
    with _LOCK:
        if _REPLAY is None:
            raise FormalReadRuntimeUnavailable()
        return _REPLAY


def get_event_stream_service() -> WorkflowEventStreamService:
    with _LOCK:
        if _STREAM is None:
            raise FormalReadRuntimeUnavailable()
        return _STREAM


def wake_stream_readers() -> None:
    """Wake Formal Read SSE waiters after a Ledger commit that may publish events.

    Safe no-op when formal read runtime is not configured.
    """
    with _LOCK:
        stream = _STREAM
    if stream is None:
        return
    stream.notifier.notify()
