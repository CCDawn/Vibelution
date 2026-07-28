"""Runtime-only setup for the rebuildable session catalog shadow candidate."""

from __future__ import annotations

import os
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


@dataclass(frozen=True)
class SessionCatalogRuntimeStatus:
    """Bounded startup result; it never includes session content or local paths."""

    status: str
    session_count: int = 0
    error_type: str = ""


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

    catalog_bridge.set_session_query_shadow_provider(None)
    set_session_catalog_dirty_observer(None)
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
        result = catalog_bridge.CatalogReconciler(
            store,
            source_loader=source_loader,
        ).reconcile(
            owner=f"web-startup-{os.getpid()}",
            now=now,
            lease_expires_at=_utcnow(offset_seconds=60),
        )
        if result.status != "complete":
            return SessionCatalogRuntimeStatus(
                status="degraded",
                session_count=result.session_count,
            )
        if store.untrusted_sentinel_path.exists() or store.dirty_session_count() != 0:
            return SessionCatalogRuntimeStatus(
                status="degraded",
                session_count=result.session_count,
            )
        catalog_bridge.set_session_query_shadow_provider(
            catalog_bridge.build_session_catalog_query_provider(store)
        )
        set_session_catalog_dirty_observer(
            _catalog_dirty_observer(project_root=root, store=store)
        )
        return SessionCatalogRuntimeStatus(
            status="ready",
            session_count=result.session_count,
        )
    except Exception as exc:
        catalog_bridge.set_session_query_shadow_provider(None)
        set_session_catalog_dirty_observer(None)
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


def _catalog_dirty_observer(
    *,
    project_root: Path,
    store: SessionCatalogStore,
) -> Callable[[Path, str, str], None]:
    expected_root = Path(project_root).resolve()

    def observe(observed_root: Path, session_id: str, source_revision: str) -> None:
        if Path(observed_root).resolve() != expected_root:
            return
        store.mark_dirty(
            session_id,
            reason="canonical_mutation",
            source_revision=source_revision,
        )

    return observe


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
