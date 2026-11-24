"""Hot frontend release switch: repoint the running backend at the active release.

A frontend-only change (empty ``backend`` bucket in
:func:`core.web.services.code_freshness.classify_changed_paths`) does not need
the backend process to restart — the pinned serving release can be moved to
the freshly published active release and new requests pick it up immediately.
This module owns that one sanctioned mutation of the startup pin:

1. Decide via ``evaluate_frontend_switch`` (three safety checks; see there).
2. Repin in-memory state (``serving_metadata`` + ``serving_frontend_dist``).
3. Rebuild the SPA shell routes onto the new dist (``repin_web_shell``).  A
   raised or silently-failed repin rolls the whole switch back: serving state
   is restored and the previous dist is repinned, then the caller gets
   ``unavailable`` with ``shell_repin_failed`` — or
   ``shell_rollback_failed_restart_required`` when even the rollback fails.
4. Persist the serving identity in the fingerprint file (best effort; the
   switched response carries ``fingerprintPersisted`` so a failed rewrite
   stays visible).

Old-release protection is inherited, not invented: the per-process serving
lease written at startup still names the release this process switched away
from, and ``gc_frontend_releases`` treats every lease named by a live process
identity as undeletable.  Open tabs therefore keep loading hashed chunks from
the previous release (and the retained-release asset fallback in
``static_spa`` keeps answering) until this process exits and the lease goes
stale.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from core.runtime_manager.process_identity import capture_process_identity
from core.web.services.code_freshness import (
    evaluate_frontend_switch,
    invalidate_freshness_for_serving_change,
    read_running_code_fingerprint,
    update_serving_frontend_release,
)

SWITCH_STATUS_SWITCHED = "switched"
SWITCH_STATUS_ALREADY_CURRENT = "already_current"
SWITCH_STATUS_RESTART_REQUIRED = "restart_required"
SWITCH_STATUS_UNAVAILABLE = "unavailable"

# Apply-failure reasons.  ``shell_repin_failed`` means the switch was fully
# rolled back to the previous release; ``shell_rollback_failed_restart_required``
# means even the rollback failed and only a backend restart restores a working
# shell, so the exception detail must reach the caller verbatim.
REASON_SHELL_REPIN_FAILED = "shell_repin_failed"
REASON_SHELL_ROLLBACK_FAILED = "shell_rollback_failed_restart_required"


class _RollbackFailed(Exception):
    """The shell repin failed AND restoring the previous release also failed."""

    def __init__(self, repin_error: str, rollback_error: str) -> None:
        super().__init__(f"repin_error={repin_error}; rollback_error={rollback_error}")
        self.repin_error = repin_error
        self.rollback_error = rollback_error


def _serving_frontend_from_app(app: Any) -> dict[str, Any]:
    serving_metadata = getattr(app.state, "serving_metadata", None)
    frontend = serving_metadata.get("frontend") if isinstance(serving_metadata, dict) else None
    return frontend if isinstance(frontend, dict) else {}


def _running_head_from_app(app: Any, project_root: Path) -> str:
    serving_metadata = getattr(app.state, "serving_metadata", None)
    backend = serving_metadata.get("backend") if isinstance(serving_metadata, dict) else None
    head = str(backend.get("head") or "").strip() if isinstance(backend, dict) else ""
    if head:
        return head
    fingerprint = read_running_code_fingerprint(project_root) or {}
    return str(fingerprint.get("runningHead") or "").strip()


def switch_frontend_to_active_release(
    *,
    app: Any,
    project_root: Path | str,
) -> dict[str, Any]:
    """Switch the serving frontend release to the active one, with validation.

    Response contract (mirrored by ``RuntimeFrontendSwitchResponse``):
    ``status`` (switched | already_current | restart_required | unavailable),
    ``servingRelease``, ``activeRelease``, ``reason``, plus ``switchedFrom``
    when a switch actually happened.
    """
    root = Path(project_root)
    serving_frontend = _serving_frontend_from_app(app)
    running_head = _running_head_from_app(app, root)
    decision = evaluate_frontend_switch(
        project_root=root,
        running_head=running_head,
        serving_frontend=serving_frontend,
    )
    status = str(decision.get("status") or "")
    base = {
        "status": status if status in {
            SWITCH_STATUS_ALREADY_CURRENT,
            SWITCH_STATUS_RESTART_REQUIRED,
            SWITCH_STATUS_UNAVAILABLE,
        } else SWITCH_STATUS_UNAVAILABLE,
        "servingRelease": str(decision.get("servingRelease") or ""),
        "activeRelease": str(decision.get("activeRelease") or ""),
        "reason": str(decision.get("reason") or ""),
    }
    if not bool(decision.get("available")) or status == SWITCH_STATUS_ALREADY_CURRENT:
        # already_current is "available" (the capability exists) but there is
        # nothing to move; only a genuinely ready decision reaches apply.
        return base
    previous_release = base["servingRelease"]
    target_release = base["activeRelease"]
    try:
        applied = _apply_release_switch(
            app=app,
            project_root=root,
            target_release=target_release,
            previous_release=previous_release,
            serving_frontend=serving_frontend,
        )
    except _RollbackFailed as exc:
        # The switch repinned into a broken shell AND the rollback repin also
        # failed. Serving state is left restored in memory but the shell may
        # still be broken; only a backend restart reliably recovers, so the
        # exception detail surfaces verbatim instead of being swallowed.
        invalidate_freshness_for_serving_change(root)
        return {
            **base,
            "status": SWITCH_STATUS_UNAVAILABLE,
            "reason": f"{REASON_SHELL_ROLLBACK_FAILED} ({exc})",
        }
    except (OSError, RuntimeError, ValueError, ImportError) as exc:
        return {
            **base,
            "status": SWITCH_STATUS_UNAVAILABLE,
            "reason": f"switch_apply_failed: {type(exc).__name__}: {exc}",
        }
    invalidate_freshness_for_serving_change(root)
    if not bool(applied.get("ok")):
        # Fully rolled back to the previous release; report the repin failure
        # detail so an operator can see why the hot switch was refused.
        return {
            **base,
            "status": SWITCH_STATUS_UNAVAILABLE,
            "reason": REASON_SHELL_REPIN_FAILED,
            "detail": str(applied.get("repinError") or ""),
        }
    return {
        "status": SWITCH_STATUS_SWITCHED,
        "servingRelease": target_release,
        "activeRelease": target_release,
        "reason": "",
        "switchedFrom": previous_release,
        "shell": applied.get("shell") or {},
        # The switch itself succeeded even when the best-effort fingerprint
        # rewrite failed; this flag is how the caller sees that gap.
        "fingerprintPersisted": bool((applied.get("fingerprint") or {}).get("updated")),
    }


def _apply_release_switch(
    *,
    app: Any,
    project_root: Path,
    target_release: str,
    previous_release: str,
    serving_frontend: dict[str, Any],
) -> dict[str, Any]:
    from core.launcher.frontend_build import (
        active_release_path,
        frontend_releases_dir,
    )

    pointer: dict[str, Any] = {}
    try:
        decoded = json.loads(active_release_path(project_root).read_text(encoding="utf-8"))
        if isinstance(decoded, dict):
            pointer = decoded
    except (OSError, ValueError, TypeError):
        pointer = {}
    target_build_key = str(pointer.get("buildKey") or "").strip()
    target_dir = frontend_releases_dir(project_root) / target_release
    provenance: dict[str, Any] = {}
    try:
        decoded = json.loads((target_dir / ".vibelution-build.json").read_text(encoding="utf-8"))
        if isinstance(decoded, dict):
            provenance = decoded
    except (OSError, ValueError, TypeError):
        provenance = {}
    target_built_from = str(provenance.get("builtFromCommit") or provenance.get("sourceCommit") or "").strip()

    # Snapshot the exact pre-switch serving state so a failed shell repin can
    # put every mutated field back before reporting failure.
    serving_metadata = getattr(app.state, "serving_metadata", None)
    frontend_dict = (
        serving_metadata.get("frontend")
        if isinstance(serving_metadata, dict) and isinstance(serving_metadata.get("frontend"), dict)
        else None
    )
    previous_frontend_snapshot = copy.deepcopy(frontend_dict) if isinstance(frontend_dict, dict) else None
    previous_dist = str(getattr(app.state, "serving_frontend_dist", "") or "")

    # 1. Pin in-memory serving state. The /api/health payload reads this dict
    #    at request time, so the very next health poll reports the new release.
    if isinstance(frontend_dict, dict):
        frontend_dict.update(
            {
                "buildKey": target_build_key,
                "release": target_release,
                "dist": str(target_dir),
                "builtFromCommit": target_built_from,
                "source": "release",
                "fallbackReason": "",
            }
        )
    app.state.serving_frontend_dist = str(target_dir)

    # 2. Rebuild the pinned SPA shell routes so new requests hit the new dist.
    #    register_spa_routes does not raise on a release that fails shell
    #    validation — it records web_shell_ready=False — so both the raised and
    #    the silent failure mode roll the whole switch back here.  A half-
    #    switched backend whose SPA routes point at an invalid dist would leave
    #    the workbench screen blank.
    shell = _repin_with_rollback(
        app,
        target_dir=target_dir,
        previous_frontend_snapshot=previous_frontend_snapshot,
        previous_dist=previous_dist,
    )
    if not bool(shell.get("ok", True)):
        # The repin failed and the switch was fully rolled back.  Persistence
        # must not run for a switch that did not stick: the on-disk fingerprint
        # must keep naming the release this process still serves.
        return {
            "ok": False,
            "repinError": str(shell.get("repinError") or ""),
            "shell": shell,
        }

    # 3. Persist the serving identity. The per-process lease is intentionally
    #    left naming the previous release (see module docstring).
    persistence = update_serving_frontend_release(
        project_root,
        release=target_release,
        build_key=target_build_key,
        dist=str(target_dir),
        built_from_commit=target_built_from,
    )
    return {
        "ok": True,
        "shell": shell,
        "fingerprint": persistence,
        "identity": capture_process_identity(os.getpid()),
        "previousRelease": previous_release,
        "previousServingRecorded": bool(serving_frontend),
    }


def _repin_with_rollback(
    app: Any,
    *,
    target_dir: Path,
    previous_frontend_snapshot: dict[str, Any] | None,
    previous_dist: str,
) -> dict[str, Any]:
    """Repin the SPA shell onto ``target_dir``, or fully undo the switch.

    Returns the repin payload on success.  On a raised or silently-failed
    repin this restores ``serving_metadata.frontend`` and
    ``serving_frontend_dist`` to their pre-switch values and repins the old
    dist back; it then returns ``{"ok": False, ...}`` (rollback worked,
    caller reports ``shell_repin_failed``) or raises :class:`_RollbackFailed`
    (even the rollback repin failed; caller reports
    ``shell_rollback_failed_restart_required``).
    """
    from core.web.route_bootstrap import repin_web_shell

    repin_error = ""
    try:
        shell = repin_web_shell(app, target_dir)
        if not bool(shell.get("shellReady")):
            repin_error = (
                f"repinned dist failed shell validation: "
                f"{str(shell.get('shellError') or 'shell not ready')}"
            )
    except Exception as exc:  # noqa: BLE001 - every failure mode must roll back
        repin_error = f"{type(exc).__name__}: {exc}"
    if not repin_error:
        return dict(shell)

    _restore_previous_serving_state(app, previous_frontend_snapshot, previous_dist)
    rollback_error = ""
    try:
        rollback_shell = repin_web_shell(app, Path(previous_dist))
        if not bool(rollback_shell.get("shellReady")):
            rollback_error = (
                f"rollback dist failed shell validation: "
                f"{str(rollback_shell.get('shellError') or 'shell not ready')}"
            )
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed
        rollback_error = f"{type(exc).__name__}: {exc}"
    if rollback_error:
        raise _RollbackFailed(repin_error=repin_error, rollback_error=rollback_error)
    return {"ok": False, "repinError": repin_error, "rolledBack": True}


def _restore_previous_serving_state(
    app: Any,
    previous_frontend_snapshot: dict[str, Any] | None,
    previous_dist: str,
) -> None:
    serving_metadata = getattr(app.state, "serving_metadata", None)
    if (
        isinstance(serving_metadata, dict)
        and isinstance(serving_metadata.get("frontend"), dict)
        and isinstance(previous_frontend_snapshot, dict)
    ):
        serving_metadata["frontend"] = copy.deepcopy(previous_frontend_snapshot)
    if previous_dist:
        app.state.serving_frontend_dist = previous_dist


__all__ = [
    "REASON_SHELL_REPIN_FAILED",
    "REASON_SHELL_ROLLBACK_FAILED",
    "SWITCH_STATUS_ALREADY_CURRENT",
    "SWITCH_STATUS_RESTART_REQUIRED",
    "SWITCH_STATUS_SWITCHED",
    "SWITCH_STATUS_UNAVAILABLE",
    "switch_frontend_to_active_release",
]
