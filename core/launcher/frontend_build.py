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


def frontend_releases_dir(project_root: Path | str) -> Path:
    return Path(project_root) / "web" / RELEASES_DIR_NAME


def active_release_path(project_root: Path | str) -> Path:
    return frontend_releases_dir(project_root) / ACTIVE_RELEASE_NAME


def frontend_build_lock_path(project_root: Path | str) -> Path:
    return frontend_releases_dir(project_root) / LOCK_DIR_NAME


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


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
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

    def claim_holder() -> bool:
        holder = {"pid": os.getpid(), "startedAt": time.time()}
        try:
            with (path / "holder.json").open("x", encoding="utf-8") as handle:
                json.dump(holder, handle)
        except FileExistsError:
            return False
        return True

    while True:
        try:
            path.mkdir()
        except FileExistsError:
            waited = True
            try:
                holder = json.loads((path / "holder.json").read_text(encoding="utf-8"))
                holder_pid = int(holder.get("pid") or 0) if isinstance(holder, dict) else 0
            except (OSError, ValueError, TypeError):
                holder_pid = 0
            if holder_pid > 0 and not _pid_is_alive(holder_pid):
                try:
                    shutil.rmtree(path)
                except OSError:
                    pass
                continue
            if holder_pid <= 0 and not (path / "holder.json").exists() and claim_holder():
                break
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
            continue
        if claim_holder():
            break
        waited = True
    try:
        yield {"waited": waited, "path": str(path)}
    finally:
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


def validate_staging_release(path: Path) -> None:
    _validate_release_assets(path)


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
        os.replace(staging, release)
    pointer = {"schemaVersion": BUILD_SCHEMA_VERSION, "release": release_name, "buildKey": build_key, "publishedAt": time.time()}
    pointer_path = active_release_path(root)
    temporary = pointer_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(pointer, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, pointer_path)
    return {"release": str(release), "provenance": provenance}


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
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
            check=False,
            **_hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"{label} failed: {type(exc).__name__}: {exc}") from exc
    if int(result.returncode or 0) != 0:
        detail = str(result.stderr or result.stdout or "").strip()[-1200:]
        raise RuntimeError(f"{label} failed with exit code {result.returncode}: {detail}")
    return str(result.stdout or "")


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
            "outputs": outputs,
        }
