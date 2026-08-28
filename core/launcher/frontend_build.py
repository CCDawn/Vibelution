"""Content-addressed frontend build releases for local source workspaces.

``web/dist`` is retained as a compatibility fallback for packaged and older
workflows.  Source-workspace launchers publish verified builds below
``web/.vibelution-builds`` and atomically switch a small active-release record.
This keeps a running backend from observing a half-written Vite output.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from core.infrastructure.codex_sandbox.process import terminate_process_tree
from core.runtime_manager.process_identity import inspect_process_identity
from vibelution_storage import (
    ProjectStorageMigrationStateError,
    resolve_project_runtime_home,
)

BUILD_SCHEMA_VERSION = 2
RELEASES_DIR_NAME = ".vibelution-builds"
ACTIVE_RELEASE_NAME = "active.json"
LOCK_DIR_NAME = "frontend-build.lockdir"
LOCK_INITIALIZATION_GRACE_SECONDS = 5.0
_BUILD_INPUT_FILES = (
    "index.html",
    "package.json",
    "package-lock.json",
    "tsconfig.json",
    "tsconfig.app.json",
    "tsconfig.node.json",
    "vite.config.ts",
    "vite.config.js",
    "scripts/parallelBuild.mjs",
    ".env",
    ".env.local",
    ".env.production",
    ".env.production.local",
)
_BUILD_ENV_NAMES = ("VIBELUTION_PROBE_BUILD", "NODE_ENV")
_VITE_ENV_PREFIX = "VITE_"
_AUDIT_INPUT_NAMES = frozenset(("sourceCommit", "frontendTree"))
_TRANSIENT_INPUT_NAMES = frozenset(("productionInputStateDigest",))
FRONTEND_PACKAGE_MANAGER_ENV = "VIBELUTION_FRONTEND_PM"
FRONTEND_RELEASE_RETENTION_SECONDS = 7 * 24 * 60 * 60
FRONTEND_STAGE_RETENTION_SECONDS = 60 * 60
FRONTEND_RELEASE_KEEP_COUNT = 5
SERVING_FRONTEND_LEASES_DIR_NAME = "serving-frontend-leases"
SERVING_FRONTEND_LEASE_SCHEMA_VERSION = 1
FRONTEND_PUBLISH_RETRY_TIMEOUT_SECONDS = 5.0
_FRONTEND_PUBLISH_RETRY_INITIAL_DELAY_SECONDS = 0.05
_FRONTEND_PUBLISH_RETRY_MAX_DELAY_SECONDS = 0.25


def frontend_releases_dir(project_root: Path | str) -> Path:
    return Path(project_root) / "web" / RELEASES_DIR_NAME


def active_release_path(project_root: Path | str) -> Path:
    return frontend_releases_dir(project_root) / ACTIVE_RELEASE_NAME


def frontend_build_lock_path(project_root: Path | str) -> Path:
    return frontend_releases_dir(project_root) / LOCK_DIR_NAME


def serving_frontend_leases_dir(project_root: Path | str) -> Path:
    """Governed lease write path under the active project runtime home.

    Identity-less or pre-governance instances resolve to checkout ``.runtime``
    because the shared storage resolver owns that fallback.  A present-but-
    invalid migration marker raises ``ProjectStorageMigrationStateError`` so
    lease writes fail closed instead of bypassing the boundary.
    """
    return resolve_project_runtime_home(project_root) / SERVING_FRONTEND_LEASES_DIR_NAME


def serving_frontend_leases_read_dirs(project_root: Path | str) -> list[Path]:
    """Lease directories to scan: governed first, plus pre-migration fallback."""
    try:
        governed = [resolve_project_runtime_home(project_root) / SERVING_FRONTEND_LEASES_DIR_NAME]
    except ProjectStorageMigrationStateError:
        # Fail-closed marker boundary: do not route this read to checkout
        # storage either; the caller's "unknown" handling stays conservative.
        return []
    dirs = list(governed)
    # Resolve both sides so Windows short-path aliases (ADMINI~1 vs the long
    # user directory) cannot report the same physical directory as two homes.
    legacy = Path(project_root).resolve() / ".runtime" / SERVING_FRONTEND_LEASES_DIR_NAME
    if os.path.normcase(str(legacy)) != os.path.normcase(str(Path(dirs[0]).resolve())):
        dirs.append(legacy)
    return dirs


def serving_frontend_lease_path(
    project_root: Path | str,
    *,
    pid: int,
    create_time: float,
) -> Path:
    # The stable identity is part of the filename so a reused PID cannot
    # overwrite a previous generation's lease.
    identity_key = f"{int(round(float(create_time) * 1000))}"
    return serving_frontend_leases_dir(project_root) / f"lease-{int(pid)}-{identity_key}.json"


def legacy_frontend_dist(project_root: Path | str) -> Path:
    return Path(project_root) / "web" / "dist"


def _validate_release_assets(path: Path) -> None:
    index = path / "index.html"
    if not index.is_file() or index.stat().st_size <= 0:
        raise RuntimeError("Frontend release did not produce a usable index.html.")
    content = index.read_text(encoding="utf-8", errors="replace")
    assets = re.findall(r"(?:src|href)=[\"']/assets/([^\"']+)[\"']", content)
    for asset in assets:
        candidate = path / "assets" / asset
        if not candidate.is_file():
            raise RuntimeError("Frontend release references a missing asset.")


def _is_complete_release(path: Path, *, build_key: str | None = None) -> bool:
    try:
        _validate_release_assets(path)
        provenance = json.loads((path / ".vibelution-build.json").read_text(encoding="utf-8"))
    except (OSError, RuntimeError, ValueError, TypeError):
        return False
    if not isinstance(provenance, dict) or int(provenance.get("schemaVersion") or 0) != BUILD_SCHEMA_VERSION:
        return False
    return build_key is None or str(provenance.get("buildKey") or "") == build_key


def frontend_package_manager(package_manager: str | None = None) -> str:
    value = str(package_manager or os.environ.get(FRONTEND_PACKAGE_MANAGER_ENV) or "").strip().lower()
    return "bun" if value == "bun" else "npm"


def resolve_active_frontend_dist(project_root: Path | str) -> Path:
    """Resolve the verified active release, falling back to legacy ``web/dist``.

    The pointer stores only a release directory name, never an arbitrary path.
    A malformed/incomplete pointer is ignored so it cannot redirect file serving
    outside the workspace.
    """

    root = Path(project_root)
    releases = frontend_releases_dir(root)
    try:
        payload = json.loads(active_release_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        payload = {}
    release_name = str(payload.get("release") or "").strip() if isinstance(payload, dict) else ""
    build_key = str(payload.get("buildKey") or "").strip() if isinstance(payload, dict) else ""
    if release_name and Path(release_name).name == release_name and release_name.startswith("release-"):
        candidate = releases / release_name
        try:
            if (
                candidate.resolve().is_relative_to(releases.resolve())
                and _is_complete_release(candidate, build_key=build_key or None)
            ):
                return candidate
        except OSError:
            pass
    return legacy_frontend_dist(root)


def _is_test_path(relative: Path) -> bool:
    parts = {part.lower() for part in relative.parts}
    name = relative.name.lower()
    return "__tests__" in parts or "__mocks__" in parts or name.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx"))


def _production_input_paths(web_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for relative_root in (Path("src"), Path("public")):
        root = web_dir / relative_root
        if root.is_dir():
            paths.extend(path for path in root.rglob("*") if path.is_file() and not _is_test_path(path.relative_to(web_dir)))
    for relative in _BUILD_INPUT_FILES:
        candidate = web_dir / relative
        if candidate.is_file():
            paths.append(candidate)
    return sorted({path.resolve() for path in paths}, key=lambda item: item.as_posix().lower())


def _digest_inputs(web_dir: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    for path in _production_input_paths(web_dir):
        relative = path.relative_to(web_dir.resolve()).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
        count += 1
    return digest.hexdigest(), count


def _input_state_digest(web_dir: Path) -> str:
    """Capture ordinary source mutations that return to the same content mid-build.

    This value does not participate in the content-addressed BuildKey.  It is
    compared only before publication so an edit-save-revert while Vite is
    reading inputs cannot activate a release compiled from the transient state.
    """

    digest = hashlib.sha256()
    for path in _production_input_paths(web_dir):
        stat = path.stat()
        relative = path.relative_to(web_dir.resolve()).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _build_environment_inputs() -> dict[str, Any]:
    values = {name: str(os.environ.get(name) or "") for name in _BUILD_ENV_NAMES}
    values.update(
        {
            name: str(value)
            for name, value in os.environ.items()
            if name.startswith(_VITE_ENV_PREFIX)
        }
    )
    canonical = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {"names": sorted(values), "digest": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}


def _run_version_command(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
            **_hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    if int(result.returncode or 0) != 0:
        return "unavailable"
    return str(result.stdout or result.stderr or "").strip() or "unavailable"


def _run_version(command: str) -> str:
    return _run_version_command([command, "--version"])


def _hidden_subprocess_kwargs() -> dict[str, object]:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {"creationflags": subprocess.CREATE_NO_WINDOW, "startupinfo": startupinfo}


def _capture_git(root: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
            **_hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return str(result.stdout or "").strip() if int(result.returncode or 0) == 0 else ""


def build_inputs(project_root: Path | str, *, package_manager: str | None = None) -> dict[str, Any]:
    root = Path(project_root).resolve()
    web_dir = root / "web"
    manager = frontend_package_manager(package_manager)
    command = shutil.which("bun" if manager == "bun" else ("node.exe" if os.name == "nt" else "node")) or (
        "bun" if manager == "bun" else ("node.exe" if os.name == "nt" else "node")
    )
    source_digest, input_count = _digest_inputs(web_dir)
    inputs = {
        "productionInputDigest": source_digest,
        "productionInputCount": input_count,
        "productionInputStateDigest": _input_state_digest(web_dir),
        "nodeVersion": _run_version(command),
        "packageManager": manager,
        "buildCommand": (
            "bun x tsc -b && bun x vite build --outDir <staging>"
            if manager == "bun"
            else "node tsc -b && node vite build --outDir <staging>"
        ),
        "environment": _build_environment_inputs(),
        "sourceCommit": _capture_git(root, ["rev-parse", "HEAD"]),
        "frontendTree": _capture_git(root, ["rev-parse", "HEAD:web"]),
    }
    if manager == "bun":
        inputs["packageManagerVersion"] = _run_version("bun")
    else:
        try:
            inputs["packageManagerVersion"] = _run_version_command([command, _npm_cli(command), "--version"])
        except RuntimeError:
            inputs["packageManagerVersion"] = "unavailable"
    return inputs


def compute_build_key(inputs: dict[str, Any]) -> str:
    excluded = _AUDIT_INPUT_NAMES | _TRANSIENT_INPUT_NAMES
    key_inputs = {name: value for name, value in inputs.items() if name not in excluded}
    canonical = json.dumps(key_inputs, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def read_active_provenance(project_root: Path | str) -> dict[str, Any]:
    dist = resolve_active_frontend_dist(project_root)
    try:
        payload = json.loads((dist / ".vibelution-build.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def inspect_frontend_build(project_root: Path | str, *, package_manager: str | None = None) -> dict[str, Any]:
    inputs = build_inputs(project_root, package_manager=package_manager)
    key = compute_build_key(inputs)
    dist = resolve_active_frontend_dist(project_root)
    provenance = read_active_provenance(project_root)
    current = _is_complete_release(dist, build_key=key)
    return {
        "current": current,
        "reason": "frontend build is current" if current else "frontend build key differs from active release",
        "buildKey": key,
        "buildInputs": inputs,
        "dist": str(dist),
        "provenance": provenance,
    }


_WINDOWS_KERNEL32: Any = None
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_ACCESS_DENIED = 5
_STILL_ACTIVE_EXIT_CODE = 259


def _windows_kernel32() -> Any:
    """Lazy kernel32 binding with 64-bit-safe signatures for liveness probes."""
    global _WINDOWS_KERNEL32
    if _WINDOWS_KERNEL32 is None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD))
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        _WINDOWS_KERNEL32 = kernel32
    return _WINDOWS_KERNEL32


def _pid_is_alive_windows(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel32 = _windows_kernel32()
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # ERROR_ACCESS_DENIED means something owns this pid; treating it as
        # alive is conservative because stealing its lock would be worse than
        # waiting one more poll cycle.
        return ctypes.get_last_error() == _ERROR_ACCESS_DENIED
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            # The handle was just opened, so a failed query is ambiguous:
            # keep the lock rather than reclaim it on inconclusive evidence.
            return True
        return int(exit_code.value) == _STILL_ACTIVE_EXIT_CODE
    finally:
        kernel32.CloseHandle(handle)


def _pid_is_alive(pid: int) -> bool:
    """Report whether a build-lock holder pid still owns a live process.

    Windows cannot use ``os.kill(pid, 0)`` for this: with signal 0 it maps to
    ``GenerateConsoleCtrlEvent``, which raises ``OSError`` (WinError 87/6) for
    dead and live pids alike inside the console-less runtime process.  The
    kernel API answers authoritatively instead.
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        return _pid_is_alive_windows(int(pid))
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextmanager
def frontend_build_lock(project_root: Path | str, *, timeout_seconds: float = 180.0) -> Iterator[dict[str, Any]]:
    path = frontend_build_lock_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(1.0, timeout_seconds)
    waited = False

    def claim_holder() -> dict[str, Any] | None:
        holder = {"pid": os.getpid(), "startedAt": time.time(), "token": uuid.uuid4().hex}
        staging = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            staging.mkdir()
            with (staging / "holder.json").open("x", encoding="utf-8") as handle:
                json.dump(holder, handle)
            try:
                # Publish only after the holder is complete.  A waiter can
                # observe either no lockdir or a fully described lockdir.
                staging.rename(path)
            except FileExistsError:
                return None
            return holder
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

    def read_holder() -> dict[str, Any] | None:
        try:
            holder = json.loads((path / "holder.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        if not isinstance(holder, dict):
            return None
        try:
            holder_pid = int(holder.get("pid") or 0)
        except (TypeError, ValueError):
            return None
        if holder_pid <= 0:
            return None
        return holder

    owned_holder: dict[str, Any] | None = None

    while True:
        claimed = claim_holder()
        if claimed is not None:
            owned_holder = claimed
            break

        waited = True
        holder = read_holder()
        holder_pid = int(holder.get("pid") or 0) if holder else 0
        if holder_pid > 0 and not _pid_is_alive(holder_pid):
            try:
                shutil.rmtree(path)
            except OSError:
                pass
            continue
        if holder_pid <= 0:
            try:
                lock_age = max(0.0, time.time() - path.stat().st_mtime)
            except OSError:
                lock_age = 0.0
            if lock_age >= LOCK_INITIALIZATION_GRACE_SECONDS:
                try:
                    shutil.rmtree(path)
                except OSError:
                    pass
                continue

        if time.monotonic() >= deadline:
            raise TimeoutError("Timed out waiting for the frontend build lock.")
        time.sleep(0.1)
    try:
        yield {"waited": waited, "path": str(path), "token": owned_holder["token"]}
    finally:
        current = read_holder()
        if owned_holder is not None and current and current.get("token") == owned_holder.get("token"):
            try:
                shutil.rmtree(path)
            except OSError:
                pass


def create_staging_release(project_root: Path | str) -> Path:
    releases = frontend_releases_dir(project_root)
    releases.mkdir(parents=True, exist_ok=True)
    path = releases / f"stage-{uuid.uuid4().hex}"
    path.mkdir()
    return path


def _serving_frontend_release_leases(project_root: Path | str) -> dict[str, Any]:
    """Read all serving leases and verify their process identities.

    A single ``running-code-fingerprint.json`` cannot represent two isolated
    backends.  Newer processes write one identity-bound lease per generation
    under the governed runtime home.  Both lease directories (governed and the
    pre-governance checkout ``.runtime`` copy) are scanned, and both fingerprint
    copies are still inspected, so an older live process never becomes invisible
    to GC across the storage migration.  Unknown or mismatched identity is
    deliberately conservative: no release is deleted in that scan.
    """

    from core.web.services.code_freshness import running_code_fingerprint_read_paths

    root = Path(project_root).resolve()
    lease_paths: list[Path] = []
    for lease_dir in serving_frontend_leases_read_dirs(root):
        try:
            lease_paths.extend(path for path in lease_dir.iterdir() if path.is_file() and path.name.endswith(".json"))
        except OSError:
            pass
    # Fingerprints double as legacy-style leases but are never unlinked here:
    # freshness owns their lifecycle and a stale-but-dead snapshot is rewritten
    # by the next backend start anyway.
    protected_lease_keys: set[str] = set()
    for fingerprint_path in running_code_fingerprint_read_paths(root):
        if fingerprint_path.is_file():
            lease_paths.append(fingerprint_path)
            protected_lease_keys.add(str(fingerprint_path.resolve()).lower())

    releases: set[str] = set()
    unknown = False
    active: list[dict[str, Any]] = []
    stale: list[str] = []
    seen_paths: set[str] = set()
    for path in lease_paths:
        key = str(path.resolve()).lower()
        if key in seen_paths:
            continue
        seen_paths.add(key)
        is_protected_fingerprint = key in protected_lease_keys
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            unknown = True
            continue
        if not isinstance(payload, dict):
            unknown = True
            continue
        if not is_protected_fingerprint:
            try:
                lease_schema = int(payload.get("schemaVersion") or 0)
            except (TypeError, ValueError):
                lease_schema = 0
            if lease_schema != SERVING_FRONTEND_LEASE_SCHEMA_VERSION:
                unknown = True
                continue
        release = str(payload.get("servingFrontendRelease") or payload.get("release") or "").strip()
        try:
            pid = int(payload.get("pid") or 0)
            create_time = float(payload.get("createTime") or 0)
        except (TypeError, ValueError):
            pid = 0
            create_time = 0.0
        executable = str(payload.get("executable") or "").strip()
        if not release or pid <= 0 or create_time <= 0 or not executable:
            unknown = True
            continue
        identity = {"pid": pid, "createTime": create_time, "executable": executable}
        status = inspect_process_identity(identity)
        status_name = str(status.get("status") or "unknown")
        if status_name == "match":
            releases.add(release)
            active.append({"path": str(path), "release": release, "pid": pid})
            continue
        if status_name == "dead":
            stale.append(str(path))
            if not is_protected_fingerprint:
                try:
                    path.unlink()
                except OSError:
                    pass
            continue
        # PID reuse, permission errors and unavailable identity are all
        # ambiguous from GC's perspective. Keep every release this pass.
        unknown = True

    return {
        "releases": sorted(releases),
        "unknown": unknown,
        "active": active,
        "stale": stale,
    }


def gc_frontend_releases(
    project_root: Path | str,
    *,
    now: float | None = None,
    release_retention_seconds: float = FRONTEND_RELEASE_RETENTION_SECONDS,
    stage_retention_seconds: float = FRONTEND_STAGE_RETENTION_SECONDS,
    keep_release_count: int = FRONTEND_RELEASE_KEEP_COUNT,
) -> dict[str, Any]:
    """Bound frontend build storage without deleting a live serving release.

    ``active.json`` and the running backend fingerprint are both treated as
    leases.  A release is eligible only when it is old enough, outside the
    recent keep window, and not named by either lease.  Staging directories
    are disposable only after the grace period, so a concurrent build gets a
    full window to publish or clean itself up.
    """

    root = Path(project_root).resolve()
    releases_dir = frontend_releases_dir(root)
    if not releases_dir.is_dir():
        return {"removed": [], "skipped": [], "active": "", "serving": ""}
    current_time = time.time() if now is None else float(now)

    def safe_mtime_ns(path: Path) -> int:
        # A concurrent cleanup/build may remove an entry between directory
        # enumeration and sorting.  Treat that entry as oldest instead of
        # allowing a harmless GC race to fail the publish path.
        try:
            return int(path.stat().st_mtime_ns)
        except OSError:
            return -1

    active_release = ""
    try:
        pointer = json.loads(active_release_path(root).read_text(encoding="utf-8"))
        if isinstance(pointer, dict):
            active_release = str(pointer.get("release") or "").strip()
    except (OSError, ValueError, TypeError):
        pass
    serving_leases = _serving_frontend_release_leases(root)
    serving_releases = set(str(item).strip() for item in serving_leases.get("releases") or [] if str(item).strip())
    serving_release = sorted(serving_releases)[0] if serving_releases else ""

    try:
        release_children = list(releases_dir.iterdir())
    except OSError:
        return {"removed": [], "skipped": [], "active": active_release, "serving": serving_release}
    release_entries = sorted(
        (path for path in release_children if path.is_dir() and path.name.startswith("release-")),
        key=safe_mtime_ns,
        reverse=True,
    )
    # If any lease cannot be tied to a live process identity, preserve every
    # release for this scan.  A false negative here can break a backend that is
    # still serving an immutable directory, while retaining one extra release
    # is recoverable by the next verified GC pass.
    if bool(serving_leases.get("unknown")):
        return {
            "removed": [],
            "skipped": [path.name for path in release_entries],
            "active": active_release,
            "serving": serving_release,
            "servingReleases": sorted(serving_releases),
            "leaseStatus": "unknown",
            "servingLeases": serving_leases.get("active") or [],
        }
    keep_names = {name for name in ({active_release} | serving_releases) if name}
    keep_names.update(path.name for path in release_entries[: max(0, int(keep_release_count))])
    removed: list[str] = []
    skipped: list[str] = []
    for path in release_entries:
        if path.name in keep_names:
            skipped.append(path.name)
            continue
        try:
            age = max(0.0, current_time - path.stat().st_mtime)
        except OSError:
            skipped.append(path.name)
            continue
        if age < max(0.0, float(release_retention_seconds)):
            skipped.append(path.name)
            continue
        try:
            shutil.rmtree(path)
            removed.append(path.name)
        except OSError:
            skipped.append(path.name)

    stage_paths = sorted(
        (path for path in release_children if path.is_dir() and path.name.startswith("stage-")),
        key=lambda path: path.name,
    )
    for path in stage_paths:
        try:
            age = max(0.0, current_time - path.stat().st_mtime)
        except OSError:
            skipped.append(path.name)
            continue
        if age < max(0.0, float(stage_retention_seconds)):
            skipped.append(path.name)
            continue
        try:
            shutil.rmtree(path)
            removed.append(path.name)
        except OSError:
            skipped.append(path.name)
    return {
        "removed": removed,
        "skipped": skipped,
        "active": active_release,
        "serving": serving_release,
        "servingReleases": sorted(serving_releases),
        "leaseStatus": "verified",
        "servingLeases": serving_leases.get("active") or [],
    }


def validate_staging_release(path: Path) -> None:
    _validate_release_assets(path)


def _retryable_frontend_publish_error(error: PermissionError) -> bool:
    """Return whether Windows reported a transient sharing/access conflict."""
    return getattr(error, "winerror", None) in {None, 5, 32}


def _publish_staging_directory(staging: Path, release: Path) -> None:
    """Atomically publish a completed staging directory without a fallback path."""
    deadline = time.monotonic() + FRONTEND_PUBLISH_RETRY_TIMEOUT_SECONDS
    delay = _FRONTEND_PUBLISH_RETRY_INITIAL_DELAY_SECONDS
    while True:
        try:
            os.replace(staging, release)
            return
        except PermissionError as exc:
            if not _retryable_frontend_publish_error(exc) or time.monotonic() >= deadline:
                raise
            time.sleep(delay)
            delay = min(delay * 2, _FRONTEND_PUBLISH_RETRY_MAX_DELAY_SECONDS)


def _copy_staging_release(staging: Path, releases: Path, *, build_key: str) -> tuple[str, Path]:
    """Copy a verified staging release to an unreferenced immutable entry."""
    while True:
        release_name = f"release-{build_key}-{uuid.uuid4().hex}"
        release = releases / release_name
        if release.exists():
            continue
        try:
            shutil.copytree(staging, release)
        except FileExistsError:
            # Another writer won this random name before copytree created it.
            continue
        except Exception:
            if release.exists():
                shutil.rmtree(release, ignore_errors=True)
            raise
        else:
            break
    try:
        validate_staging_release(release)
        if not _is_complete_release(release, build_key=build_key):
            raise RuntimeError("Copied frontend release failed validation.")
        shutil.rmtree(staging)
        return release_name, release
    except Exception:
        if release.exists():
            shutil.rmtree(release, ignore_errors=True)
        raise


def publish_staging_release(project_root: Path | str, staging: Path, *, build_key: str, build_inputs_value: dict[str, Any]) -> dict[str, Any]:
    root = Path(project_root).resolve()
    validate_staging_release(staging)
    release_name = f"release-{build_key}"
    release = frontend_releases_dir(root) / release_name
    provenance = {
        "schemaVersion": BUILD_SCHEMA_VERSION,
        "buildKey": build_key,
        "buildInputs": build_inputs_value,
        "sourceCommit": build_inputs_value.get("sourceCommit") or "",
        "frontendTree": build_inputs_value.get("frontendTree") or "",
        "builtFromCommit": build_inputs_value.get("sourceCommit") or "",
        "publishedAt": time.time(),
    }
    (staging / ".vibelution-build.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
    if release.exists() and not _is_complete_release(release, build_key=build_key):
        # Preserve the damaged immutable entry for running readers; publish the
        # repaired bytes under a distinct release name before switching active.
        release_name = f"release-{build_key}-{uuid.uuid4().hex}"
        release = frontend_releases_dir(root) / release_name
    if release.exists():
        shutil.rmtree(staging)
    else:
        try:
            _publish_staging_directory(staging, release)
        except PermissionError as error:
            if not _retryable_frontend_publish_error(error):
                raise
            release_name, release = _copy_staging_release(staging, frontend_releases_dir(root), build_key=build_key)
    pointer = {"schemaVersion": BUILD_SCHEMA_VERSION, "release": release_name, "buildKey": build_key, "publishedAt": time.time()}
    pointer_path = active_release_path(root)
    temporary = pointer_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(pointer, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, pointer_path)
    gc = gc_frontend_releases(root)
    return {"release": str(release), "provenance": provenance, "gc": gc}


def _node_command() -> str:
    resolved = shutil.which("node.exe" if os.name == "nt" else "node")
    if resolved:
        return resolved
    if os.name == "nt":
        candidates: list[Path] = []
        for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
            root = str(os.environ.get(env_name) or "").strip()
            if root:
                candidates.append(Path(root) / "nodejs" / "node.exe")
        local_app_data = str(os.environ.get("LOCALAPPDATA") or "").strip()
        if local_app_data:
            candidates.append(Path(local_app_data) / "Programs" / "nodejs" / "node.exe")
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
    return "node.exe" if os.name == "nt" else "node"


def _npm_cli(node_command: str) -> str:
    candidates: list[Path] = []
    for name in (("npm.cmd", "npm") if os.name == "nt" else ("npm",)):
        resolved = shutil.which(name)
        if resolved:
            npm_path = Path(resolved)
            resolved_path = npm_path.resolve()
            if resolved_path.is_file() and resolved_path.name == "npm-cli.js":
                return str(resolved_path)
            candidates.extend((npm_path.parent, npm_path.parent.parent, resolved_path.parent, resolved_path.parent.parent))
    node_path = Path(node_command)
    candidates.extend((node_path.parent, node_path.parent.parent))
    for parent in candidates:
        for relative in (
            Path("node_modules") / "npm" / "bin" / "npm-cli.js",
            Path("lib") / "node_modules" / "npm" / "bin" / "npm-cli.js",
        ):
            candidate = parent / relative
            if candidate.is_file():
                return str(candidate)
    raise RuntimeError("npm-cli.js was not found next to Node.js/npm.")


def _run_checked(command: list[str], *, cwd: Path, label: str) -> str:
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_hidden_subprocess_kwargs(),
        )
        stdout, stderr = process.communicate(timeout=900)
    except subprocess.TimeoutExpired as exc:
        # `subprocess.run(..., timeout=...)` only owns the direct process.
        # This builder owns a live Popen handle, so reuse the project helper
        # to terminate descendants before the root and keep Windows hidden.
        if process is not None:
            try:
                terminate_process_tree(process)
            except (OSError, RuntimeError, subprocess.SubprocessError) as terminate_error:
                raise RuntimeError(
                    f"{label} timed out and its process tree could not be retired: "
                    f"{type(terminate_error).__name__}: {terminate_error}"
                ) from exc
        raise RuntimeError(f"{label} failed: {type(exc).__name__}: {exc}") from exc
    except OSError as exc:
        raise RuntimeError(f"{label} failed: {type(exc).__name__}: {exc}") from exc
    if int(process.returncode or 0) != 0:
        detail = str(stderr or stdout or "").strip()[-1200:]
        raise RuntimeError(f"{label} failed with exit code {process.returncode}: {detail}")
    return str(stdout or "")


def ensure_frontend_build(
    project_root: Path | str,
    *,
    package_manager: str | None = None,
    lock_timeout_seconds: float = 180.0,
) -> dict[str, Any]:
    """Build a verified release only when its complete BuildKey is not active.

    The old active pointer is deliberately left intact until both TypeScript and
    Vite complete and the staging output passes validation.
    """

    root = Path(project_root).resolve()
    web_dir = root / "web"
    manager = frontend_package_manager(package_manager)
    with frontend_build_lock(root, timeout_seconds=lock_timeout_seconds) as lock:
        inspection = inspect_frontend_build(root, package_manager=manager)
        if bool(inspection["current"]):
            return {"rebuilt": False, "skipped": True, "lock": lock, **inspection}

        if manager == "bun":
            bun = shutil.which("bun") or "bun"
            if (
                not (web_dir / "node_modules").is_dir()
                or not (web_dir / "node_modules" / ".bin" / "tsc").exists()
                or not (web_dir / "node_modules" / ".bin" / "vite").exists()
            ):
                _run_checked([bun, "install"], cwd=web_dir, label="bun install")
            stage = create_staging_release(root)
            commands = [
                ("tsc -b", [bun, "x", "tsc", "-b"]),
                ("vite build", [bun, "x", "vite", "build", "--outDir", str(stage)]),
            ]
        else:
            node = _node_command()
            if (
                not (web_dir / "node_modules").is_dir()
                or not (web_dir / "node_modules" / "typescript" / "bin" / "tsc").is_file()
                or not (web_dir / "node_modules" / "vite" / "bin" / "vite.js").is_file()
            ):
                _run_checked([node, _npm_cli(node), "ci"], cwd=web_dir, label="node npm-cli.js ci")
            stage = create_staging_release(root)
            commands = [
                ("tsc -b", [node, str(web_dir / "node_modules" / "typescript" / "bin" / "tsc"), "-b"]),
                ("vite build", [node, str(web_dir / "node_modules" / "vite" / "bin" / "vite.js"), "build", "--outDir", str(stage)]),
            ]
        try:
            outputs = {label: _run_checked(command, cwd=web_dir, label=label) for label, command in commands}
            # Recompute after build: toolchain/source drift must not be stamped as current.
            final = inspect_frontend_build(root, package_manager=manager)
            if (
                str(final["buildKey"]) != str(inspection["buildKey"])
                or str(final["buildInputs"].get("productionInputStateDigest") or "")
                != str(inspection["buildInputs"].get("productionInputStateDigest") or "")
            ):
                raise RuntimeError("Frontend inputs changed while building; refusing to publish a mixed release.")
            published = publish_staging_release(root, stage, build_key=str(final["buildKey"]), build_inputs_value=dict(final["buildInputs"]))
        except Exception:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)
            raise
        return {
            "rebuilt": True,
            "skipped": False,
            "lock": lock,
            "buildKey": final["buildKey"],
            "buildInputs": final["buildInputs"],
            "dist": published["release"],
            "provenance": published["provenance"],
            "gc": published.get("gc") or {},
            "outputs": outputs,
        }
