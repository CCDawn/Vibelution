"""Running-code freshness detection.

The workbench backend snapshots the git commit it was started from
(``running-code-fingerprint.json`` under the governed project runtime home).
``resolve_code_freshness`` compares that snapshot with the current disk HEAD
so the UI can tell the user the running instance is behind the repository and
a restart is needed.  Reads fall back to the legacy checkout-relative
``.runtime/`` location so a backend that started before the storage migration
(or an in-flight upgrade) stays visible until its own next snapshot.

Git calls go through ``core.infrastructure.no_console_git`` (CREATE_NO_WINDOW +
GIT_OPTIONAL_LOCKS=0), matching the Windows no-console red line and the
GitHub-Desktop convention of not competing with user git operations.

The combined resolver keeps a short-TTL verdict cache guarded by pure file
observation (``.git/HEAD`` text + fingerprint file stamps), so the 120s UI
polling loop usually spawns no git process at all; dirty-tree walks run on an
independent, longer throttle.  See ``resolve_code_freshness``.  Concurrent
full resolutions for one project root collapse into a single flight (the
startup prewarm and an early frontend poll share one git-backed walk instead
of paying it twice).
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.infrastructure.no_console_git import run_git
from core.runtime_manager.process_identity import capture_process_identity
from vibelution_storage import (
    ProjectStorageMigrationStateError,
    resolve_project_runtime_home,
)

FINGERPRINT_SCHEMA_VERSION = 1
FINGERPRINT_NAME = "running-code-fingerprint.json"
# Pre-governance checkout-relative snapshot location.  Writes go to the active
# runtime home instead; this stays readable for pre-migration instances.
# Kept as a plain forward-slash string: a module-level Path() would dispatch
# WindowsPath during import when a test has patched os.name to "nt" on POSIX,
# which raises NotImplementedError before any test setup can run.
LEGACY_FINGERPRINT_RELATIVE = f".runtime/{FINGERPRINT_NAME}"
GIT_TIMEOUT_SECONDS = 10
# Polling reads never compete with user git operations for the index lock:
# ``--no-optional-locks`` is the argv form of the GIT_OPTIONAL_LOCKS=0 env that
# no_console_git already sets, kept explicit so the polling contract is visible
# in spawn logs and test assertions.
POLL_GIT_GLOBAL_ARGS = ["--no-optional-locks"]
# Fast-path TTL for the combined verdict.  The UI polls every 120s while this
# only bounds staleness of inputs the HEAD/fingerprint observation cannot see
# (frontend provenance files), so 45s (matching git_status_service's snapshot
# TTL) keeps the hot path at zero git processes between unrelated changes.
FRESHNESS_FAST_PATH_TTL_SECONDS = 45.0
# Dirty-tree recheck throttle.  ``status --untracked-files=all`` walks the whole
# tree and dominates the request cost, but the restart banner only needs a
# eventually-consistent dirty flag, so it is refreshed at most every 5 minutes
# and immediately whenever HEAD or the fingerprint file changes.
DIRTY_RECHECK_INTERVAL_SECONDS = 300.0

_freshness_cache_lock = threading.Lock()
# key -> {"at": monotonic, "observation": tuple, "response": dict}
_freshness_cache: dict[str, dict[str, Any]] = {}
# key -> {"at": monotonic, "head_text": str, "fingerprint": str, "dirty": dict}
_dirty_summary_cache: dict[str, dict[str, Any]] = {}

# Per-project-root single-flight gate: same-root concurrent full resolutions
# share one compute.  Modeled on config_service._config_result_cache_single_flight
# (Condition + generation: waiters share a successful compute through the
# normal fast-path cache, a failed compute is never shared and every waiter
# falls through to its own resolution).  The TTL fast-path hit stays entirely
# outside this gate (zero contention on the hot path); only the git-backed
# full-resolution path enters it.  The gate guards only the flight bookkeeping
# below — never the caches themselves — so cache writes stay lock-free.
_FRESHNESS_FLIGHT_WAIT_TIMEOUT_SECONDS = 30.0
_FRESHNESS_FLIGHTS: dict[str, dict[str, Any]] = {}
_FRESHNESS_FLIGHT_LOCK = threading.Condition()


def _monotonic() -> float:
    return time.monotonic()


def reset_freshness_caches_for_tests() -> None:
    """Drop the module-level freshness caches (test isolation helper)."""
    with _freshness_cache_lock:
        _freshness_cache.clear()
        _dirty_summary_cache.clear()
    with _FRESHNESS_FLIGHT_LOCK:
        _FRESHNESS_FLIGHTS.clear()


def _freshness_root_flight_key(project_root: Path | str) -> str:
    try:
        return os.path.normcase(str(Path(project_root).resolve()))
    except OSError:
        return os.path.normcase(str(project_root))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _capture_git_text(project_root: Path | str, args: list[str]) -> str:
    try:
        result = run_git([*POLL_GIT_GLOBAL_ARGS, *args], cwd=str(project_root), timeout=GIT_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return ""
    if int(result.returncode or 0) != 0:
        return ""
    return str(result.stdout or "").strip()


def _dirty_tree_summary(project_root: Path | str) -> dict[str, Any]:
    raw = _capture_git_text(project_root, ["status", "--porcelain=v1", "--untracked-files=all"])
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    return {
        "dirty": bool(normalized),
        "dirtyTreeDigest": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
    }


def _short_sha(value: str) -> str:
    text = str(value or "").strip()
    return text[:12] if text else ""


def _read_git_head_text(project_root: Path | str) -> str:
    """Read the current HEAD text with pure file I/O, spawning no git process.

    Adapted from ``core.external_agent.backend_client._checkout_revision``:
    handles the ``.git`` gitdir pointer file, detached HEAD, and linked
    worktrees (refs resolved against ``commondir`` when the per-worktree path
    misses).  Returns "" on any failure so callers fall back to the full git
    path instead of trusting a partially read state.
    """
    root = Path(project_root)
    git_entry = root / ".git"
    git_dir = git_entry
    try:
        if git_entry.is_file():
            text = git_entry.read_text(encoding="utf-8", errors="replace").strip()
            if not text.lower().startswith("gitdir:"):
                return ""
            git_dir = Path(text.split(":", 1)[1].strip())
            if not git_dir.is_absolute():
                git_dir = (root / git_dir).resolve()
        head_path = git_dir / "HEAD"
        if not head_path.is_file():
            return ""
        head = head_path.read_text(encoding="utf-8", errors="replace").strip()
        if not head.startswith("ref:"):
            return head
        ref = head.split(":", 1)[1].strip()
        candidates = [git_dir / ref]
        common_dir_path = git_dir / "commondir"
        if common_dir_path.is_file():
            common_dir = Path(common_dir_path.read_text(encoding="utf-8").strip())
            if not common_dir.is_absolute():
                common_dir = (git_dir / common_dir).resolve()
            candidates.append(common_dir / ref)
        for candidate in candidates:
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8", errors="replace").strip()
        return ""
    except OSError:
        return ""


def _fingerprint_stamps(project_root: Path | str) -> tuple[tuple[str, int, int], ...]:
    """Cheap (path, mtime_ns, size) stamps for the snapshot read candidates."""
    stamps: list[tuple[str, int, int]] = []
    for path in running_code_fingerprint_read_paths(project_root):
        try:
            stat = path.stat()
        except OSError:
            continue
        stamps.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(stamps)


def _observe_freshness_inputs(project_root: Path | str) -> tuple[str, tuple[tuple[str, int, int], ...]]:
    """Zero-process change observation for the freshness fast path."""
    return _read_git_head_text(project_root), _fingerprint_stamps(project_root)


def _freshness_cache_key(project_root: Path | str, fallback_snapshot: dict[str, Any] | None) -> str:
    root = _freshness_root_flight_key(project_root)
    if isinstance(fallback_snapshot, dict) and fallback_snapshot:
        signature = "|".join(
            [
                str(fallback_snapshot.get("runningHead") or ""),
                str(fallback_snapshot.get("dirtyTreeDigest") or ""),
            ]
        )
    else:
        signature = "none"
    return f"{root}|{signature}"


def running_code_fingerprint_path(project_root: Path | str) -> Path:
    """Governed snapshot write path under the active project runtime home.

    Identity-less or pre-governance instances resolve to the checkout
    ``.runtime`` location because the shared storage resolver owns that
    fallback.  A present-but-invalid migration marker raises
    ``ProjectStorageMigrationStateError`` (fail closed) so callers never route
    this file into storage the boundary rejects.
    """
    return resolve_project_runtime_home(project_root) / FINGERPRINT_NAME


def legacy_running_code_fingerprint_path(project_root: Path | str) -> Path:
    """Pre-governance checkout location, kept readable during migration."""
    return Path(project_root) / LEGACY_FINGERPRINT_RELATIVE


def running_code_fingerprint_read_paths(project_root: Path | str) -> list[Path]:
    """Snapshot locations to inspect: governed first, then the legacy copy."""
    try:
        governed = [resolve_project_runtime_home(project_root) / FINGERPRINT_NAME]
    except ProjectStorageMigrationStateError:
        # A present-but-invalid marker fails closed on reads too; do not
        # quietly redirect this read to checkout storage instead.
        return []
    paths = list(governed)
    # Resolve both sides so Windows short-path aliases (ADMINI~1 vs the long
    # user directory) cannot report the same physical file as two candidates.
    legacy = legacy_running_code_fingerprint_path(project_root).resolve()
    if os.path.normcase(str(legacy)) != os.path.normcase(str(Path(paths[0]).resolve())):
        paths.append(legacy)
    return paths


def serving_frontend_lease_path(project_root: Path | str, *, pid: int, create_time: float) -> Path:
    from core.launcher.frontend_build import serving_frontend_lease_path as _lease_path

    return _lease_path(project_root, pid=pid, create_time=create_time)


def frontend_build_provenance_path(project_root: Path | str) -> Path:
    from core.launcher.frontend_build import resolve_active_frontend_dist

    return resolve_active_frontend_dist(project_root) / ".vibelution-build.json"


def write_running_code_fingerprint(
    *,
    project_root: Path | str,
    source: str = "web_workbench_lifespan",
    serving_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Snapshot the git commit this backend process was started from.

    Best effort: a failed write must never block or crash startup, so the
    payload reports ``written`` and callers treat a missing snapshot as
    ``unknown`` freshness rather than an error.
    """
    root = Path(project_root)
    head = _capture_git_text(root, ["rev-parse", "HEAD"])
    branch = _capture_git_text(root, ["branch", "--show-current"])
    dirty = _dirty_tree_summary(root)
    identity = capture_process_identity(os.getpid())
    frontend_value = serving_metadata.get("frontend") if isinstance(serving_metadata, dict) else {}
    backend_value = serving_metadata.get("backend") if isinstance(serving_metadata, dict) else {}
    frontend = frontend_value if isinstance(frontend_value, dict) else {}
    backend = backend_value if isinstance(backend_value, dict) else {}
    started_at = str((backend or {}).get("startedAt") or _now_iso())
    payload: dict[str, Any] = {
        "schemaVersion": FINGERPRINT_SCHEMA_VERSION,
        "projectRoot": str(root.resolve()),
        "runningHead": head,
        "runningBranch": branch,
        "dirty": bool(dirty["dirty"]),
        "dirtyTreeDigest": str(dirty["dirtyTreeDigest"]),
        "pid": int(os.getpid()),
        "createTime": identity.get("createTime") or (backend or {}).get("createTime"),
        "executable": str(identity.get("executable") or (backend or {}).get("executable") or ""),
        "startedAt": started_at,
        "source": source,
    }
    if isinstance(serving_metadata, dict) and isinstance(frontend_value, dict):
        payload.update(
            {
                "servingFrontendBuildKey": str(frontend.get("buildKey") or ""),
                "servingFrontendRelease": str(frontend.get("release") or ""),
                "servingFrontendDist": str(frontend.get("dist") or ""),
                "servingFrontendBuiltFromCommit": str(frontend.get("builtFromCommit") or ""),
            }
        )
    if isinstance(serving_metadata, dict):
        payload["apiContractVersion"] = str(serving_metadata.get("apiContractVersion") or "v1")
    try:
        path = running_code_fingerprint_path(root)
    except ProjectStorageMigrationStateError as exc:
        # Fail closed: a present-but-invalid migration marker must not route
        # the snapshot (or its lease) back into checkout storage. Best-effort
        # contract: report the failure instead of crashing startup.
        payload["written"] = False
        payload["errorType"] = type(exc).__name__
        payload["errorMessage"] = str(exc)
        return payload
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)
        payload["written"] = True
        payload["path"] = str(path)
        lease_release = str(payload.get("servingFrontendRelease") or "").strip()
        try:
            lease_create_time = float(payload.get("createTime") or 0)
        except (TypeError, ValueError):
            lease_create_time = 0.0
        lease_executable = str(payload.get("executable") or "").strip()
        if lease_release and lease_create_time > 0 and lease_executable:
            try:
                lease_path = serving_frontend_lease_path(
                    root,
                    pid=int(payload["pid"]),
                    create_time=lease_create_time,
                )
                lease_path.parent.mkdir(parents=True, exist_ok=True)
                lease_payload = {
                    "schemaVersion": 1,
                    "projectRoot": str(root.resolve()),
                    "pid": int(payload["pid"]),
                    "createTime": lease_create_time,
                    "executable": lease_executable,
                    "servingFrontendBuildKey": str(payload.get("servingFrontendBuildKey") or ""),
                    "servingFrontendRelease": lease_release,
                    "startedAt": started_at,
                }
                lease_tmp = lease_path.with_suffix(lease_path.suffix + ".tmp")
                lease_tmp.write_text(json.dumps(lease_payload, ensure_ascii=False, indent=2), encoding="utf-8")
                lease_tmp.replace(lease_path)
                payload["servingLeasePath"] = str(lease_path)
            except (OSError, ProjectStorageMigrationStateError) as exc:
                payload["servingLeaseErrorType"] = type(exc).__name__
    except OSError as exc:
        payload["written"] = False
        payload["errorType"] = type(exc).__name__
        payload["errorMessage"] = str(exc)
    return payload


def read_running_code_fingerprint(project_root: Path | str) -> dict[str, Any] | None:
    """Read the governed snapshot first, falling back to the legacy copy."""
    for path in running_code_fingerprint_read_paths(project_root):
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (
            isinstance(parsed, dict)
            and int(parsed.get("schemaVersion") or 0) == FINGERPRINT_SCHEMA_VERSION
        ):
            return parsed
    return None


def read_frontend_build_provenance(project_root: Path | str) -> dict[str, Any] | None:
    """Return provenance from the atomically activated frontend release."""
    from core.launcher.frontend_build import read_active_provenance

    parsed = read_active_provenance(project_root)
    return parsed if parsed else None


def _inspect_active_frontend_build(project_root: Path | str) -> dict[str, Any]:
    from core.launcher.frontend_build import inspect_frontend_build

    return inspect_frontend_build(project_root)


def _parse_behind_count(value: str) -> int | None:
    text = str(value or "").strip()
    if not text.isdigit():
        return None
    parsed = int(text)
    return parsed if parsed >= 0 else None


def fallback_snapshot_from_serving_metadata(serving_metadata: Any) -> dict[str, Any] | None:
    """Map the startup-pinned ``app.state.serving_metadata`` backend identity
    into a fingerprint-shaped snapshot.

    The fingerprint file is the primary freshness input, but its write is
    best-effort (storage fail-closed, migration races, legacy processes), so a
    missing file used to silently downgrade the whole verdict to ``unknown``
    and the UI showed nothing (2026-09-11 SCI-049 incident).  The pinned
    serving metadata in ``app.state`` is the authoritative immutable snapshot
    of the code this process mounted, so it is a safe same-event fallback.
    """

    backend = serving_metadata.get("backend") if isinstance(serving_metadata, dict) else None
    if not isinstance(backend, dict):
        return None
    head = str(backend.get("head") or "").strip()
    digest = str(backend.get("dirtyTreeDigest") or "").strip()
    if not head or not digest:
        return None
    try:
        pid = int(backend.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    return {
        "runningHead": head,
        "runningBranch": "",
        "dirty": bool(backend.get("dirty")),
        "dirtyTreeDigest": digest,
        "pid": pid,
        "createTime": backend.get("createTime"),
        "executable": str(backend.get("executable") or ""),
        "startedAt": str(backend.get("startedAt") or ""),
        "source": "serving_metadata_fallback",
    }


def _throttled_dirty_summary(
    project_root: Path | str,
    *,
    head_text: str,
    fingerprint_stamp: str,
) -> dict[str, Any]:
    """Reuse the last known dirty summary unless HEAD/fingerprint changed.

    ``status --untracked-files=all`` walks the whole worktree and dominates the
    freshness cost, but the restart banner does not need a per-poll dirty flag.
    The digest therefore keeps its last known value and is recomputed only when
    HEAD moved, the fingerprint file changed, or the 5-minute throttle elapsed.
    """
    key = _freshness_cache_key(project_root, None)
    now = _monotonic()
    with _freshness_cache_lock:
        cached = _dirty_summary_cache.get(key)
        if (
            cached
            and now - float(cached["at"]) <= DIRTY_RECHECK_INTERVAL_SECONDS
            and cached["head_text"] == head_text
            and cached["fingerprint"] == fingerprint_stamp
        ):
            return dict(cached["dirty"])
    dirty = _dirty_tree_summary(project_root)
    with _freshness_cache_lock:
        _dirty_summary_cache[key] = {
            "at": now,
            "head_text": head_text,
            "fingerprint": fingerprint_stamp,
            "dirty": dict(dirty),
        }
    return dirty


def resolve_backend_freshness(
    *,
    project_root: Path | str,
    fallback_snapshot: dict[str, Any] | None = None,
    dirty_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare the running snapshot with the current disk HEAD.

    Pure decision inputs keep this function unit-testable; git reads are the
    only side effect and they never lock (--no-optional-locks).
    ``fallback_snapshot`` (from the startup-pinned serving metadata) keeps the
    verdict decidable when the on-disk fingerprint file is missing or unreadable.
    ``dirty_summary`` lets the combined resolver inject the throttled dirty
    summary instead of paying for a fresh ``status`` walk on every call.
    """
    root = Path(project_root)
    running = read_running_code_fingerprint(root)
    snapshot_source = "fingerprint_file"
    if running is None and isinstance(fallback_snapshot, dict) and fallback_snapshot:
        running = fallback_snapshot
        snapshot_source = str(fallback_snapshot.get("source") or "serving_metadata_fallback")
    disk_head = _capture_git_text(root, ["rev-parse", "HEAD"])
    disk_branch = _capture_git_text(root, ["branch", "--show-current"])
    if isinstance(dirty_summary, dict) and dirty_summary:
        disk_dirty = dict(dirty_summary)
    else:
        disk_dirty = _dirty_tree_summary(root)

    running_head = str((running or {}).get("runningHead") or "").strip()
    if not running_head:
        return {
            "available": False,
            "reason": "no_running_fingerprint",
            "running": None,
            "disk": {"head": disk_head, "branch": disk_branch},
        }
    if not disk_head:
        return {
            "available": False,
            "reason": "git_unavailable",
            "running": {
                "head": running_head,
                "branch": str((running or {}).get("runningBranch") or "").strip(),
                "startedAt": str((running or {}).get("startedAt") or "").strip(),
            },
            "disk": {"head": "", "branch": "", **disk_dirty},
        }

    behind_count: int | None = None
    running_dirty_digest = str((running or {}).get("dirtyTreeDigest") or "").strip()
    dirty_differs = bool(running_dirty_digest) and running_dirty_digest != str(disk_dirty["dirtyTreeDigest"])
    if running_head != disk_head:
        behind_count = _parse_behind_count(
            _capture_git_text(root, ["rev-list", "--count", f"{running_head}..{disk_head}"])
        )
    if not running_dirty_digest:
        return {
            "available": False,
            "reason": "running_fingerprint_missing_dirty_digest",
            "running": {
                "head": running_head,
                "branch": str((running or {}).get("runningBranch") or "").strip(),
                "startedAt": str((running or {}).get("startedAt") or "").strip(),
                "pid": int((running or {}).get("pid") or 0),
            },
            "disk": {"head": disk_head, "branch": disk_branch, **disk_dirty},
        }
    return {
        "available": True,
        "reason": "",
        "source": snapshot_source,
        "behind": running_head != disk_head or dirty_differs,
        "behindCount": behind_count,
        "running": {
            "head": running_head,
            "branch": str((running or {}).get("runningBranch") or "").strip(),
            "startedAt": str((running or {}).get("startedAt") or "").strip(),
            "dirty": bool((running or {}).get("dirty")),
            "dirtyTreeDigest": running_dirty_digest,
            "pid": int((running or {}).get("pid") or 0),
            "createTime": (running or {}).get("createTime"),
            "executable": str((running or {}).get("executable") or ""),
        },
        "disk": {"head": disk_head, "branch": disk_branch, **disk_dirty},
    }


def resolve_frontend_freshness(*, project_root: Path | str) -> dict[str, Any]:
    """Compare the active release with the exact inputs that determine its bytes."""
    root = Path(project_root)
    try:
        inspection = _inspect_active_frontend_build(root)
    except OSError:
        inspection = {}
    provenance = inspection.get("provenance") if isinstance(inspection.get("provenance"), dict) else {}
    if not provenance:
        return {
            "available": False,
            "reason": "no_provenance",
            "builtFromCommit": "",
            "frontendTree": "",
            "buildKey": "",
        }
    built_from = str(provenance.get("builtFromCommit") or "").strip()
    frontend_tree = str(provenance.get("frontendTree") or "").strip()
    active_build_key = str(provenance.get("buildKey") or "").strip()
    running = read_running_code_fingerprint(root) or {}
    serving_build_key = str(running.get("servingFrontendBuildKey") or "").strip()
    serving_release = str(running.get("servingFrontendRelease") or "").strip()
    active_release = ""
    try:
        from core.launcher.frontend_build import active_release_path

        pointer = json.loads(active_release_path(root).read_text(encoding="utf-8"))
        if isinstance(pointer, dict):
            active_release = str(pointer.get("release") or "").strip()
    except (OSError, ValueError, TypeError):
        active_release = ""
    serving_metadata_present = bool(
        str(running.get("servingFrontendBuildKey") or "").strip()
        and str(running.get("servingFrontendRelease") or "").strip()
    )
    if not serving_metadata_present:
        return {
            "available": False,
            "reason": "serving_metadata_missing",
            "stale": True,
            "builtFromCommit": built_from,
            "frontendTree": frontend_tree,
            "buildKey": active_build_key,
            "servingBuildKey": serving_build_key,
            "servingRelease": serving_release,
            "activeRelease": active_release,
        }
    serving_mismatch = bool(
        serving_metadata_present
        and (
            not serving_build_key
            or serving_build_key != active_build_key
            or (serving_release and active_release and serving_release != active_release)
        )
    )
    return {
        "available": True,
        "reason": "serving release differs from active release" if serving_mismatch else str(inspection.get("reason") or ""),
        "stale": not bool(inspection.get("current")) or serving_mismatch,
        "builtFromCommit": built_from,
        "frontendTree": frontend_tree,
        "buildKey": active_build_key,
        "servingBuildKey": serving_build_key,
        "servingRelease": serving_release,
        "activeRelease": active_release,
    }


def _freshness_fast_path_hit(
    project_root: Path | str,
    fallback_snapshot: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return the cached verdict when the TTL + file observation still hold.

    Zero git processes, one short lock block, and no flight bookkeeping: this
    is the polling hot path and must never queue behind a full resolution.
    """

    cache_key = _freshness_cache_key(project_root, fallback_snapshot)
    observation = _observe_freshness_inputs(project_root)
    now = _monotonic()
    with _freshness_cache_lock:
        cached = _freshness_cache.get(cache_key)
        if (
            cached
            and now - float(cached["at"]) <= FRESHNESS_FAST_PATH_TTL_SECONDS
            and cached["observation"] == observation
        ):
            return copy.deepcopy(cached["response"])
    return None


def _compute_freshness_response(
    *,
    project_root: Path | str,
    fallback_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    """Run one full git-backed freshness resolution and refresh the cache."""

    cache_key = _freshness_cache_key(project_root, fallback_snapshot)
    # Observe at compute time (not caller arrival): after a single-flight wait
    # the inputs may have moved, and the cache write must key off the inputs
    # of the actual run so the next poll's observation can match it.
    observation = _observe_freshness_inputs(project_root)
    now = _monotonic()

    dirty = _throttled_dirty_summary(
        project_root,
        head_text=observation[0],
        fingerprint_stamp=repr(observation[1]),
    )
    backend = resolve_backend_freshness(
        project_root=project_root,
        fallback_snapshot=fallback_snapshot,
        dirty_summary=dirty,
    )
    frontend = resolve_frontend_freshness(project_root=project_root)

    backend_behind = bool(backend.get("behind"))
    backend_available = bool(backend.get("available"))
    frontend_available = bool(frontend.get("available"))
    frontend_stale_raw = bool(frontend.get("stale"))
    # Only a confirmed frontend verdict may drive the combined verdict; an
    # unavailable frontend panel (e.g. serving_metadata_missing) reports
    # stale=True as "cannot confirm", not as proven behind. The response keeps
    # the raw stale flag so callers can distinguish the two.
    frontend_stale = frontend_available and frontend_stale_raw

    if backend_behind and frontend_stale:
        verdict = "backend_and_frontend_behind"
    elif backend_behind:
        verdict = "backend_behind"
    elif frontend_stale:
        verdict = "frontend_behind"
    elif backend_available and frontend_available:
        verdict = "current"
    else:
        verdict = "unknown"

    response = {
        "schemaVersion": FINGERPRINT_SCHEMA_VERSION,
        "verdict": verdict,
        "backend": {
            "available": backend_available,
            "behind": backend_behind,
            "behindCount": backend.get("behindCount"),
            "reason": backend.get("reason") or "",
            "source": backend.get("source") or "",
            "running": backend.get("running"),
            "disk": backend.get("disk"),
        },
        "frontend": {
            "available": frontend_available,
            "stale": frontend_stale_raw,
            "reason": frontend.get("reason") or "",
            "builtFromCommit": _short_sha(str(frontend.get("builtFromCommit") or "")),
            "frontendTree": str(frontend.get("frontendTree") or ""),
            "buildKey": _short_sha(str(frontend.get("buildKey") or "")),
            "servingBuildKey": _short_sha(str(frontend.get("servingBuildKey") or "")),
            "servingRelease": str(frontend.get("servingRelease") or ""),
            "activeRelease": str(frontend.get("activeRelease") or ""),
        },
    }
    # Only cache when the file-read HEAD agrees with rev-parse: a mismatch means
    # the cheap observation cannot be trusted to guard this verdict (odd refs
    # layouts, packed-refs-only states), so keep paying the full path.
    observed_head = observation[0]
    disk_head = str((backend.get("disk") or {}).get("head") or "")
    if observed_head and observed_head == disk_head:
        with _freshness_cache_lock:
            _freshness_cache[cache_key] = {
                "at": now,
                "observation": observation,
                "response": copy.deepcopy(response),
            }
    return response


def _freshness_resolve_single_flight(
    *,
    project_root: Path | str,
    fallback_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    """Collapse same-root concurrent full resolutions into one compute.

    Modeled on config_service._config_result_cache_single_flight: the first
    full-path miss becomes the flight leader; same-root concurrent callers
    wait (bounded), then replay the leader's verdict through the normal fast
    path so TTL/observation rules still apply.  A leader failure is never
    shared — waiters fall through and compute their own verdict, and the
    leader's exception propagates to the leader only.  A caller whose cache
    key differs from the leader's (different fallback snapshot) also falls
    through: sharing stays keyed by the same verdict inputs, never merged.
    """

    flight_key = _freshness_root_flight_key(project_root)
    with _FRESHNESS_FLIGHT_LOCK:
        flight = _FRESHNESS_FLIGHTS.setdefault(
            flight_key, {"inflight": False, "generation": 0}
        )
        arrival_generation = flight["generation"]
        if flight["inflight"]:
            deadline = _monotonic() + _FRESHNESS_FLIGHT_WAIT_TIMEOUT_SECONDS
            while flight["inflight"]:
                remaining = deadline - _monotonic()
                if remaining <= 0:
                    break
                _FRESHNESS_FLIGHT_LOCK.wait(remaining)
            if flight["generation"] != arrival_generation:
                # The leader finished successfully and refreshed the verdict
                # cache; hand its payload out through the normal fast path so
                # signature/TTL rules still apply.
                shared = _freshness_fast_path_hit(project_root, fallback_snapshot)
                if shared is not None:
                    return shared
            # Leader failed, hit its own timeout window, or its verdict does
            # not cover this caller's cache key: fall through and compute.
        flight["inflight"] = True
    succeeded = False
    try:
        response = _compute_freshness_response(
            project_root=project_root,
            fallback_snapshot=fallback_snapshot,
        )
        succeeded = True
        return response
    finally:
        with _FRESHNESS_FLIGHT_LOCK:
            flight["inflight"] = False
            if succeeded:
                flight["generation"] += 1
            _FRESHNESS_FLIGHT_LOCK.notify_all()


def resolve_code_freshness(
    *,
    project_root: Path | str,
    fallback_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Combine backend + frontend freshness into one verdict for the UI.

    A behind verdict is never suppressed by the other panel being unknown:
    before the 2026-09-11 fix, a missing backend fingerprint forced the whole
    verdict to ``unknown`` even when the frontend panel independently proved
    the serving build was behind, and the UI rendered ``unknown`` as a neutral
    chip with no stale warning at all.

    Hot path (zero git processes): the cached verdict is replayed whenever the
    HEAD text read straight from ``.git/HEAD`` (the VS Code DotGitWatcher
    approach of watching the HEAD file instead of spawning git) and the
    fingerprint file stamps are unchanged and the TTL has not elapsed.  Any
    HEAD/fingerprint/TTL change falls back to the full git-backed verdict and
    refreshes the cache.  Cached responses are deep-copied on the way in and
    out so callers cannot mutate the shared cache.  Concurrent full
    resolutions for one project root (e.g. the startup prewarm racing the
    frontend's first poll) collapse into a single flight instead of each
    paying the full git-backed walk.
    """
    hit = _freshness_fast_path_hit(project_root, fallback_snapshot)
    if hit is not None:
        return hit
    return _freshness_resolve_single_flight(
        project_root=project_root,
        fallback_snapshot=fallback_snapshot,
    )
