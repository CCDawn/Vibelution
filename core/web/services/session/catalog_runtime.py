"""Runtime-only setup for the rebuildable session catalog shadow candidate."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from core.chat.conversation_ledger import conversation_ledger_path, latest_ledger_sequence
from core.chat.session_catalog import (
    SessionCatalogStore,
    set_session_catalog_dirty_observer,
    compute_workspace_key,
    resolve_session_catalog_path,
)
from core.infrastructure import developer_sandbox
from core.ui.chat_state import chat_state_path

from . import catalog_bridge
from ..runtime_scene_service import record_runtime_scene_event


_MAX_INCREMENTAL_RECONCILE_ATTEMPTS = 3
_RUNTIME_SUPERVISOR_LOCK = threading.Lock()
_RUNTIME_SUPERVISOR: "_CatalogRuntimeSupervisor | None" = None
_RUNTIME_GENERATION = 0


@dataclass(frozen=True)
class SessionCatalogRuntimeStatus:
    """Bounded startup result; it never includes session content or local paths."""

    status: str
    session_count: int = 0
    error_type: str = ""


class _CatalogRuntimeSupervisor:
    """Debounce catalog rebuilds while keeping dirty reads on the legacy path."""

    def __init__(
        self,
        *,
        project_root: Path,
        store: SessionCatalogStore,
        reconciler: catalog_bridge.CatalogReconciler,
        delay_ms: int,
    ) -> None:
        self._project_root = Path(project_root).resolve()
        self._store = store
        self._reconciler = reconciler
        self._delay_seconds = max(0, int(delay_ms)) / 1000
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._running = False
        self._closed = False
        self._retry_attempt = 0

    def observe(self, observed_root: Path, session_id: str, source_revision: str) -> None:
        if Path(observed_root).resolve() != self._project_root:
            return
        if not self._store.mark_dirty(
            session_id,
            reason="canonical_mutation",
            source_revision=source_revision,
        ):
            self._record("session_catalog.dirty.unavailable", outcome="degraded", level="warning")
            return
        self._record(
            "session_catalog.dirty.observed",
            fields={"dirtyCount": self._dirty_count()},
        )
        self._schedule(reset_retry_budget=True)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            timer = self._timer
            self._timer = None
        if timer is not None:
            timer.cancel()

    def _schedule(self, *, reset_retry_budget: bool = False) -> None:
        with self._lock:
            if self._closed:
                return
            if reset_retry_budget:
                self._retry_attempt = 0
            if self._timer is not None or self._running:
                return
            self._schedule_locked(self._delay_seconds)

    def _schedule_locked(self, delay_seconds: float) -> None:
        timer = threading.Timer(max(0.0, delay_seconds), self._run_reconcile)
        timer.daemon = True
        self._timer = timer
        timer.start()

    def _run_reconcile(self) -> None:
        with self._lock:
            self._timer = None
            if self._closed or self._running:
                return
            self._running = True

        should_retry = False
        try:
            result = self._reconciler.reconcile(
                owner=f"web-incremental-{os.getpid()}",
                now=_utcnow(),
                lease_expires_at=_utcnow(offset_seconds=60),
            )
            fresh = (
                result.status == "complete"
                and not self._store.untrusted_sentinel_path.exists()
                and self._dirty_count() == 0
            )
            if fresh:
                self._record(
                    "session_catalog.incremental.complete",
                    outcome="complete",
                    fields={"sessionCount": result.session_count},
                )
            else:
                should_retry = True
                self._record(
                    "session_catalog.incremental.degraded",
                    outcome="degraded",
                    level="warning",
                    fields={
                        "status": result.status,
                        "sessionCount": result.session_count,
                        "dirtyCount": self._dirty_count(),
                    },
                )
        except Exception as exc:
            self._store.mark_untrusted(type(exc).__name__)
            should_retry = True
            self._record(
                "session_catalog.incremental.failed",
                outcome="failed",
                level="warning",
                fields={"errorType": type(exc).__name__},
            )
        finally:
            with self._lock:
                self._running = False
                if should_retry and not self._closed:
                    self._retry_attempt += 1
                    if self._retry_attempt <= _MAX_INCREMENTAL_RECONCILE_ATTEMPTS:
                        self._schedule_locked(self._delay_seconds)
                elif not should_retry:
                    self._retry_attempt = 0

    def _dirty_count(self) -> int:
        try:
            return self._store.dirty_session_count()
        except Exception:
            return -1

    @staticmethod
    def _record(
        event_code: str,
        *,
        outcome: str = "observed",
        level: str = "info",
        fields: dict[str, Any] | None = None,
    ) -> None:
        try:
            record_runtime_scene_event(
                "session_catalog",
                "reconcile",
                event_code,
                message="Session catalog runtime reconciliation event.",
                outcome=outcome,
                level=level,
                fields=fields or {},
                lifecycle=True,
            )
        except Exception:
            return


def shutdown_session_catalog_runtime() -> None:
    """Detach runtime observers and cancel pending catalog-only work."""

    global _RUNTIME_GENERATION, _RUNTIME_SUPERVISOR
    with _RUNTIME_SUPERVISOR_LOCK:
        _RUNTIME_GENERATION += 1
        supervisor = _RUNTIME_SUPERVISOR
        _RUNTIME_SUPERVISOR = None
        set_session_catalog_dirty_observer(None)
        catalog_bridge.set_session_query_shadow_provider(None)
    if supervisor is not None:
        supervisor.close()


def initialize_session_catalog_runtime(
    *,
    project_root: Path,
    catalog_config: Any,
    summary_loader: Callable[[], Sequence[Mapping[str, Any]]] | None = None,
) -> SessionCatalogRuntimeStatus:
    """Build and install the SQL candidate only for the opt-in shadow mode.

    Any catalog failure removes the candidate provider and leaves the legacy
    query path untouched.  This initializer never writes canonical state.
    """

    global _RUNTIME_SUPERVISOR

    shutdown_session_catalog_runtime()
    with _RUNTIME_SUPERVISOR_LOCK:
        generation = _RUNTIME_GENERATION
    if str(getattr(catalog_config, "mode", "off") or "off").strip().lower() != "shadow":
        return SessionCatalogRuntimeStatus(status="disabled")
    if not bool(getattr(catalog_config, "reconcile_on_startup", True)):
        return SessionCatalogRuntimeStatus(status="disabled")

    try:
        root = Path(project_root).resolve()
        workspace_root = _active_workspace_root(root)
        environment = "developer" if developer_sandbox.is_developer_mode_enabled() else "formal"
        store = SessionCatalogStore(
            resolve_session_catalog_path(
                workspace_root,
                environment=environment,
                project_root=root,
            ),
            workspace_key=compute_workspace_key(workspace_root, environment=environment),
            busy_timeout_ms=int(getattr(catalog_config, "busy_timeout_ms", 5000) or 0),
        )
        store.initialize()
        load_summaries = summary_loader or _load_legacy_session_summaries

        def source_loader() -> catalog_bridge.CatalogSourceSnapshot:
            return build_runtime_catalog_snapshot(
                root,
                workspace_root=workspace_root,
                environment=environment,
                summaries=load_summaries(),
            )

        now = _utcnow()
        reconciler = catalog_bridge.CatalogReconciler(
            store,
            source_loader=source_loader,
        )
        result = reconciler.reconcile(
            owner=f"web-startup-{os.getpid()}",
            now=now,
            lease_expires_at=_utcnow(offset_seconds=60),
        )
        if result.status != "complete":
            _CatalogRuntimeSupervisor._record(
                "session_catalog.startup.degraded",
                outcome="degraded",
                level="warning",
                fields={"status": result.status, "sessionCount": result.session_count},
            )
            return SessionCatalogRuntimeStatus(
                status="degraded",
                session_count=result.session_count,
            )
        if store.untrusted_sentinel_path.exists() or store.dirty_session_count() != 0:
            _CatalogRuntimeSupervisor._record(
                "session_catalog.startup.degraded",
                outcome="degraded",
                level="warning",
                fields={"status": "untrusted_or_dirty", "sessionCount": result.session_count},
            )
            return SessionCatalogRuntimeStatus(
                status="degraded",
                session_count=result.session_count,
            )
        supervisor = _CatalogRuntimeSupervisor(
            project_root=root,
            store=store,
            reconciler=reconciler,
            delay_ms=getattr(catalog_config, "incremental_reconcile_delay_ms", 750),
        )
        with _RUNTIME_SUPERVISOR_LOCK:
            if _RUNTIME_GENERATION != generation:
                supervisor.close()
                return SessionCatalogRuntimeStatus(status="disabled")
            catalog_bridge.set_session_query_shadow_provider(
                catalog_bridge.build_session_catalog_query_provider(store)
            )
            set_session_catalog_dirty_observer(supervisor.observe)
            _RUNTIME_SUPERVISOR = supervisor
        supervisor._record(
            "session_catalog.startup.ready",
            outcome="complete",
            fields={"sessionCount": result.session_count},
        )
        return SessionCatalogRuntimeStatus(
            status="ready",
            session_count=result.session_count,
        )
    except Exception as exc:
        detached_supervisor: _CatalogRuntimeSupervisor | None = None
        with _RUNTIME_SUPERVISOR_LOCK:
            if _RUNTIME_GENERATION == generation:
                detached_supervisor = _RUNTIME_SUPERVISOR
                _RUNTIME_SUPERVISOR = None
                set_session_catalog_dirty_observer(None)
                catalog_bridge.set_session_query_shadow_provider(None)
        if detached_supervisor is not None:
            detached_supervisor.close()
        _CatalogRuntimeSupervisor._record(
            "session_catalog.startup.failed",
            outcome="failed",
            level="warning",
            fields={"errorType": type(exc).__name__},
        )
        return SessionCatalogRuntimeStatus(
            status="degraded",
            error_type=type(exc).__name__,
        )


def build_runtime_catalog_snapshot(
    project_root: Path,
    *,
    workspace_root: Path,
    environment: str,
    summaries: Sequence[Mapping[str, Any]],
) -> catalog_bridge.CatalogSourceSnapshot:
    """Build a source snapshot from current legacy summaries and journal stats."""

    normalized_summaries = tuple(item for item in summaries if isinstance(item, Mapping))
    return catalog_bridge.build_catalog_snapshot(
        normalized_summaries,
        _journal_inventory(project_root, workspace_root, normalized_summaries),
        workspace_key=compute_workspace_key(workspace_root, environment=environment),
        indexed_at=_utcnow(),
    )


def _active_workspace_root(project_root: Path) -> Path:
    return chat_state_path(project_root).parent.parent


def _load_legacy_session_summaries() -> Sequence[Mapping[str, Any]]:
    from core.web.services import session_service

    return session_service.list_sessions(repair_collisions=False)


def _journal_inventory(
    project_root: Path,
    workspace_root: Path,
    summaries: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    inventory: dict[str, dict[str, Any]] = {}
    for summary in summaries:
        session_id = str(summary.get("id") or summary.get("sessionId") or "").strip()
        if not session_id or session_id in inventory:
            continue
        path = conversation_ledger_path(project_root, session_id)
        try:
            stat = path.stat()
        except OSError:
            continue
        try:
            journal_path = path.resolve().relative_to(workspace_root.resolve()).as_posix()
        except ValueError:
            journal_path = ""
        inventory[session_id] = {
            "journal_rel_path": journal_path,
            "journal_size": max(0, int(stat.st_size)),
            "journal_mtime_ns": max(0, int(stat.st_mtime_ns)),
            "latest_sequence": max(0, int(latest_ledger_sequence(project_root, session_id) or 0)),
            "event_count": 0,
            "message_count": 0,
        }
    return inventory


def _utcnow(*, offset_seconds: int = 0) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=max(0, int(offset_seconds)))
    ).isoformat().replace("+00:00", "Z")
