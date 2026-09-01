"""Self-contained ``web/dist`` placeholder for backend-starting tests.

Git worktrees only check out git-tracked files, so ``web/dist`` (a gitignored
build output) exists only in the root checkout.  The full backend app
(``core.web.app.create_app``) pins a serving frontend directory at construction
time and ``core.web.route_bootstrap.register_spa_routes`` refuses to mount SPA
routes unless that directory exists.  Every route-contract test that boots the
app therefore failed with ``RuntimeError: Pinned serving frontend release is
unavailable`` in a bare worktree.

No pytest consumes real dist *content*: the frontend build suite
(``tests/test_frontend_build.py``) seeds its own tmp_path fixtures, and the
static-cache / route-bootstrap tests provide explicit temporary dists.  A
minimal placeholder directory at the exact path production resolves is enough
to make route-contract tests self-contained in a bare worktree.

Safety properties:

- Real builds are never touched: the placeholder is created only when the
  production resolver (``resolve_active_frontend_dist``) returns a missing
  directory, and cleanup only removes a directory that still carries our
  sentinel file.
- pytest-xdist safe: every session that manages the placeholder registers a
  holder directory before creating/using the placeholder and removes it on
  session finish.  The placeholder itself is only removed when no holders
  remain, so a finishing worker can never delete it under a still-running
  worker.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

PLACEHOLDER_SENTINEL = ".pytest-web-dist-placeholder.json"
_HOLDERS_DIRNAME = ".pytest-holders"
_PLACEHOLDER_INDEX_HTML = "<!doctype html><title>Vibelution pytest placeholder</title>\n"


def resolve_serving_web_dist(project_root: Path) -> Path:
    """Resolve the dist path exactly the way the production backend does.

    ``core.web.app`` serves from ``VIBELUTION_WORKSPACE_ROOT`` when the launcher
    set it, falling back to the checkout root, and resolves the active frontend
    release through ``resolve_active_frontend_dist``.  Mirroring that here keeps
    the placeholder aligned with the path route registration actually checks.
    """

    from core.launcher.frontend_build import resolve_active_frontend_dist

    env_root = str(os.environ.get("VIBELUTION_WORKSPACE_ROOT", "")).strip()
    root = Path(env_root) if env_root else Path(project_root)
    return resolve_active_frontend_dist(root)


def _holders_dir(dist: Path) -> Path:
    return dist / _HOLDERS_DIRNAME


def _is_managed_placeholder(dist: Path) -> bool:
    return (dist / PLACEHOLDER_SENTINEL).is_file()


def acquire_web_dist_placeholder(project_root: Path) -> Path | None:
    """Ensure a serving dist directory exists for this test session.

    Returns the placeholder path when this session manages one (cleanup
    required), or ``None`` when a real dist already exists and nothing was
    created.  Never raises: test infrastructure must not block collection.
    """

    try:
        dist = resolve_serving_web_dist(project_root)
        if dist.is_dir() and not _is_managed_placeholder(dist):
            return None

        # Register this session as a holder before creating/touching the
        # placeholder so a concurrent session cannot remove it under us.
        holders = _holders_dir(dist)
        holders.mkdir(parents=True, exist_ok=True)
        holder = holders / f"{os.getpid()}-{uuid.uuid4().hex}.holder"
        holder.touch()

        if not _is_managed_placeholder(dist):
            (dist / "index.html").write_text(_PLACEHOLDER_INDEX_HTML, encoding="utf-8")
            (dist / PLACEHOLDER_SENTINEL).write_text(
                "Created by tests/helpers/web_dist_placeholder.py; safe to delete.\n",
                encoding="utf-8",
            )
        return dist
    except Exception:  # noqa: BLE001 - best-effort environment provisioning
        return None


def release_web_dist_placeholder(dist: Path | None) -> None:
    """Drop this session's holder and clean the placeholder when orphaned."""

    if dist is None:
        return
    try:
        if not _is_managed_placeholder(dist):
            return
        holders = _holders_dir(dist)
        for holder in holders.glob(f"{os.getpid()}-*.holder"):
            holder.unlink(missing_ok=True)
        try:
            holders.rmdir()
        except OSError:
            # Other sessions still hold the placeholder; keep it.
            return
        # No remaining holders: remove only files this helper owns.
        (dist / PLACEHOLDER_SENTINEL).unlink(missing_ok=True)
        (dist / "index.html").unlink(missing_ok=True)
        for child in dist.iterdir():
            # Unexpected content appeared mid-session (e.g. a real build):
            # keep the directory rather than delete unknown artifacts.
            return
        dist.rmdir()
    except OSError:
        return


__all__ = [
    "PLACEHOLDER_SENTINEL",
    "acquire_web_dist_placeholder",
    "release_web_dist_placeholder",
    "resolve_serving_web_dist",
]
