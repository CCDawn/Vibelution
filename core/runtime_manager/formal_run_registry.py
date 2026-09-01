"""Active-work registry for formal full runs (runtime-manager work-run store).

Formal full runs execute synchronously inside the backend HTTP thread for up
to ``seeds * timeoutSeconds``.  Registering them here makes the run visible to
the runtime-manager daemon and Launcher active-work probes, so destructive
lifecycle commands (stop/restart) cannot silently kill a training run, and it
provides the persistent snapshot source used to enforce exclusive ``outputRoot``
ownership between concurrent formal runs.

The snapshot is deliberately transient: it is created when the run starts and
deleted when the run reaches a terminal state.  Durable audit stays in the
experiment plan store (``fullRunExecutions``); crashed leftovers are reclaimed
by the daemon's force-stop / stale-grace handling.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import work_run_store


FORMAL_RUN_WORK_KIND = "formal_run"


class FormalRunOutputRootConflict(ValueError):
    """Raised when a requested outputRoot overlaps an active formal run."""

    def __init__(
        self,
        *,
        requested_output_root: str,
        conflict_run_id: str,
        conflict_output_root: str,
        relationship: str,
    ) -> None:
        self.requested_output_root = str(requested_output_root or "")
        self.conflict_run_id = str(conflict_run_id or "")
        self.conflict_output_root = str(conflict_output_root or "")
        self.relationship = str(relationship or "")
        super().__init__(
            "Formal run outputRoot conflict: requested outputRoot "
            f"{self.requested_output_root!r} {self.relationship} active formal run "
            f"{self.conflict_run_id!r} outputRoot {self.conflict_output_root!r}. "
            "Formal runs require an exclusive outputRoot."
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store() -> work_run_store.WorkRunStore:
    # Resolve WORK_RUNS_DIR through the module attribute so daemon, launcher,
    # and tests that rebind work_run_store.WORK_RUNS_DIR stay consistent.
    return work_run_store.WorkRunStore(root=work_run_store.WORK_RUNS_DIR)


def register_active_formal_run(
    *,
    run_id: str,
    output_root: str,
    team_id: str = "",
    plan_id: str = "",
    adapter_id: str = "",
    started_at: str = "",
) -> dict[str, Any]:
    """Persist a running work-run snapshot for a formal full run."""

    now = _now_iso()
    snapshot = {
        "runId": str(run_id or "").strip(),
        "runKind": FORMAL_RUN_WORK_KIND,
        "status": "running",
        "teamId": str(team_id or "").strip(),
        "planId": str(plan_id or "").strip(),
        "adapterId": str(adapter_id or "").strip(),
        "outputRoot": str(output_root or "").strip(),
        "startedAt": str(started_at or "").strip() or now,
        "updatedAt": now,
    }
    return _store().persist_snapshot(FORMAL_RUN_WORK_KIND, snapshot, active_run_id=snapshot["runId"])


def complete_formal_run(
    *,
    run_id: str,
    status: str,
    error: str = "",
) -> dict[str, Any]:
    """Clear the active-work snapshot once the run reached a terminal state.

    Deletion failures are contained: the worst case is a stale running snapshot
    that the daemon's stale-grace / force-stop handling reclaims, so a cleanup
    hiccup never fails an already-finished run.
    """

    normalized_run_id = str(run_id or "").strip()
    try:
        return _store().delete_snapshot(FORMAL_RUN_WORK_KIND, normalized_run_id)
    except OSError as exc:
        work_run_store._record_work_run_event(
            "state",
            "work_run.formal_run.snapshot_cleanup_failed",
            run_kind=FORMAL_RUN_WORK_KIND,
            run_id=normalized_run_id,
            status=str(status or "").strip(),
            fields={"errorType": type(exc).__name__, "message": str(exc)},
            message="Formal run work-run snapshot cleanup failed.",
            outcome="failed",
            level="warning",
            lifecycle=True,
        )
        return {"deleted": False, "runId": normalized_run_id, "error": str(exc)}


def active_formal_run_snapshots() -> list[dict[str, Any]]:
    """Return non-terminal formal-run snapshots currently blocking work."""

    snapshots: list[dict[str, Any]] = []
    for payload in _store().list_snapshots(FORMAL_RUN_WORK_KIND):
        if not isinstance(payload, dict):
            continue
        if str(payload.get("finishedAt") or payload.get("endedAt") or "").strip():
            continue
        if not work_run_store.active_work_payload_blocks_lifecycle(payload):
            continue
        snapshots.append(payload)
    return snapshots


def normalized_output_root(value: Any) -> str:
    """Canonical comparison form: resolved, backslash-normalized, case-folded."""

    raw = str(value or "").strip()
    if not raw:
        return ""
    path = Path(raw).expanduser()
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        resolved = path
    return os.path.normcase(str(resolved))


def _path_is_within(child: str, parent: str) -> bool:
    if not child.startswith(parent):
        return False
    remainder = child[len(parent):]
    return remainder[:1] in ("/", "\\")


def output_root_relationship(requested: Any, active: Any) -> str:
    """Return ``same``, ``nested``, or ``""`` between two output roots."""

    requested_key = normalized_output_root(requested)
    active_key = normalized_output_root(active)
    if not requested_key or not active_key:
        return ""
    if requested_key == active_key:
        return "same"
    if _path_is_within(requested_key, active_key) or _path_is_within(active_key, requested_key):
        return "nested"
    return ""


def assert_output_root_is_exclusive(output_root: Any, *, exclude_run_id: str = "") -> None:
    """Fail closed when the requested outputRoot overlaps an active formal run.

    Store read failures propagate as ``OSError`` so callers can reject the run
    instead of assuming an empty (conflict-free) snapshot list.
    """

    requested = str(output_root or "").strip()
    for payload in active_formal_run_snapshots():
        conflict_run_id = str(payload.get("runId") or "").strip()
        if exclude_run_id and conflict_run_id == str(exclude_run_id or "").strip():
            continue
        relationship = output_root_relationship(requested, payload.get("outputRoot"))
        if not relationship:
            continue
        raise FormalRunOutputRootConflict(
            requested_output_root=requested,
            conflict_run_id=conflict_run_id,
            conflict_output_root=str(payload.get("outputRoot") or "").strip(),
            relationship=relationship,
        )
