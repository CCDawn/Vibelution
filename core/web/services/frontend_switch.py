"""Hot frontend release switch: repoint the running backend at the active release.

A frontend-only change (empty ``backend`` bucket in
:func:`core.web.services.code_freshness.classify_changed_paths`) does not need
the backend process to restart — the pinned serving release can be moved to
the freshly published active release and new requests pick it up immediately.
This module owns that one sanctioned mutation of the startup pin:

1. Decide via ``evaluate_frontend_switch`` (three safety checks; see there).
2. Repin in-memory state (``serving_metadata`` + ``serving_frontend_dist``).
3. Rebuild the SPA shell routes onto the new dist (``repin_web_shell``).
4. Persist the serving identity in the fingerprint file.

Old-release protection is inherited, not invented: the per-process serving
lease written at startup still names the release this process switched away
from, and ``gc_frontend_releases`` treats every lease named by a live process
identity as undeletable.  Open tabs therefore keep loading hashed chunks from
the previous release (and the retained-release asset fallback in
``static_spa`` keeps answering) until this process exits and the lease goes
stale.
"""

from __future__ import annotations

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
    except (OSError, RuntimeError, ImportError) as exc:
        return {
            **base,
            "status": SWITCH_STATUS_UNAVAILABLE,
            "reason": f"switch_apply_failed: {type(exc).__name__}",
        }
    invalidate_freshness_for_serving_change(root)
    return {
        "status": SWITCH_STATUS_SWITCHED,
        "servingRelease": target_release,
        "activeRelease": target_release,
        "reason": "",
        "switchedFrom": previous_release,
        "shell": applied.get("shell") or {},
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
    from core.web.route_bootstrap import repin_web_shell

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

    # 1. Pin in-memory serving state. The /api/health payload reads this dict
    #    at request time, so the very next health poll reports the new release.
    serving_metadata = getattr(app.state, "serving_metadata", None)
    if isinstance(serving_metadata, dict) and isinstance(serving_metadata.get("frontend"), dict):
        serving_metadata["frontend"].update(
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
    shell = repin_web_shell(app, target_dir)

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
        "shell": shell,
        "fingerprint": persistence,
        "identity": capture_process_identity(os.getpid()),
        "previousRelease": previous_release,
        "previousServingRecorded": bool(serving_frontend),
    }


__all__ = [
    "SWITCH_STATUS_ALREADY_CURRENT",
    "SWITCH_STATUS_RESTART_REQUIRED",
    "SWITCH_STATUS_SWITCHED",
    "SWITCH_STATUS_UNAVAILABLE",
    "switch_frontend_to_active_release",
]
