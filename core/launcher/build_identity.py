"""Read built Launcher identities without repeating update admission.

``ready`` means required build metadata, runtime entry points and the native
fast freshness checks passed. It does not claim a full runtime-content proof
or authorize replacement; native update preparation remains unchanged.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from core.launcher import desktop_shell

_GIT_HASH = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_UNKNOWN_REASONS = {
    "current_electron_tree_unavailable",
    "current_frontend_tree_unavailable",
    "frontend_inspection_failed",
}


def inspect_available_launcher_build(
    project_root: Path | str, *, shell_kind: str,
) -> dict[str, Any]:
    """Project a same-kind replacement without building or promoting anything.

    Match update preparation's live-first selection. Git HEAD is only a source
    check, never an identity for an unbuilt artifact. Full package verification
    remains owned by update preparation rather than this status projection.
    """

    if shell_kind not in {"packaged", "unpackaged"}:
        return {"availableBuild": None, "availableBuildState": "unknown"}
    root = Path(project_root)
    if shell_kind == "unpackaged":
        try:
            binary = desktop_shell.unpackaged_electron_executable(root)
        except OSError:
            return {"availableBuild": None, "availableBuildState": "unknown"}
        if binary is None:
            return {"availableBuild": None, "availableBuildState": "not_built"}
        candidates = (
            desktop_shell.unpackaged_main_js(root).parent,
            root / desktop_shell.UNPACKAGED_STAGING_RELATIVE,
        )
    else:
        candidates = (
            desktop_shell.packaged_desktop_exe(root).parent,
            root / desktop_shell.STAGING_WIN_UNPACKED_RELATIVE,
        )
    for index, candidate in enumerate(candidates):
        try:
            if not candidate.is_dir():
                continue
            native_status = None
            if index == 0:
                native_status = (
                    desktop_shell.inspect_unpackaged_electron(root) if shell_kind == "unpackaged"
                    else desktop_shell._inspect_desktop_shell_package(root, candidate, for_reuse=False)
                )
                if native_status.get("reason") in _UNKNOWN_REASONS:
                    raise RuntimeError("Launcher source inspection is unavailable")
                if native_status.get("stale") is not False:
                    continue
            if shell_kind == "unpackaged":
                build = _unpackaged_build(root, candidate, staged=index == 1, native_status=native_status)
            else:
                build = _packaged_build(root, candidate, staged=index == 1, native_status=native_status)
            if build is not None:
                return {"availableBuild": build, "availableBuildState": "ready"}
            if index == 0:
                # Native preparation will retain this live build. An incomplete
                # identity cannot make an unrelated staging build the target.
                return {"availableBuild": None, "availableBuildState": "not_built"}
        except Exception:
            # This is a read-only status boundary: an inspection failure must
            # neither claim a replacement exists nor break the freshness API.
            return {"availableBuild": None, "availableBuildState": "unknown"}
    return {"availableBuild": None, "availableBuildState": "not_built"}


def _read_provenance(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_metadata(kind: str, build_id: str, provenance: dict[str, Any]) -> dict[str, str] | None:
    tree = provenance.get("electronTreeHash")
    if not isinstance(tree, str) or not _GIT_HASH.fullmatch(tree):
        return None
    build = {"kind": kind, "id": build_id, "electronTree": tree}
    commit = provenance.get("sourceCommit")
    if isinstance(commit, str) and _GIT_HASH.fullmatch(commit):
        build["sourceCommit"] = commit
    built_at = provenance.get("builtAt")
    if isinstance(built_at, str) and built_at.strip():
        build["builtAt"] = built_at
    return build


def _unpackaged_build(root: Path, dist: Path, *, staged: bool, native_status: dict[str, Any] | None = None) -> dict[str, str] | None:
    provenance_path = dist / "unpackaged-provenance.json"
    provenance = _read_provenance(provenance_path)
    if not _build_metadata("unpackaged", "", provenance):
        return None
    if not desktop_shell._unpackaged_electron_dist_is_complete(dist):
        return None
    if staged:
        current_tree = desktop_shell._git_tree_hash(root, "HEAD:desktop/electron")
        if not isinstance(current_tree, str) or not _GIT_HASH.fullmatch(current_tree):
            raise RuntimeError("Launcher source tree is unavailable")
        if not desktop_shell._prepared_unpackaged_electron_is_current(root):
            return None
    else:
        status = native_status or desktop_shell.inspect_unpackaged_electron(root)
        if status.get("reason") in _UNKNOWN_REASONS:
            raise RuntimeError("Launcher source inspection is unavailable")
        if status.get("stale") is not False:
            return None
        current_tree = status.get("currentElectronTree")
    if not isinstance(current_tree, str) or not _GIT_HASH.fullmatch(current_tree):
        raise RuntimeError("Launcher source tree is unavailable")
    if provenance["electronTreeHash"] != current_tree:
        return None
    build_id = desktop_shell._frontend_directory_content_sha256(dist)
    if not _SHA256.fullmatch(build_id):
        return None
    if _read_provenance(provenance_path) != provenance:
        raise RuntimeError("Launcher build changed during inspection")
    return _build_metadata("unpackaged", build_id, provenance)


def _packaged_build(root: Path, package: Path, *, staged: bool, native_status: dict[str, Any] | None = None) -> dict[str, str] | None:
    provenance_path = package / "resources/app.asar.unpacked/package-provenance.json"
    provenance = _read_provenance(provenance_path)
    if not _build_metadata("packaged", "", provenance):
        return None
    if staged:
        source_commit = provenance.get("sourceCommit")
        if not isinstance(source_commit, str) or not _GIT_HASH.fullmatch(source_commit):
            return None
        current_commit = desktop_shell._git_tree_hash(root, "HEAD")
        if not isinstance(current_commit, str) or not _GIT_HASH.fullmatch(current_commit):
            raise RuntimeError("Launcher source commit is unavailable")
        if source_commit != current_commit or not desktop_shell._electron_package_sources_clean(root):
            return None
    assistant_root = package / "resources/launcher-assistant"
    if not (
        (assistant_root / "source").is_dir()
        and (assistant_root / "source/scripts/assistant_host.py").is_file()
        and (assistant_root / "python/pythonw.exe").is_file()
    ):
        return None
    status = native_status or desktop_shell._inspect_desktop_shell_package(root, package, for_reuse=False)
    if status.get("reason") in _UNKNOWN_REASONS:
        raise RuntimeError("Launcher package inspection is unavailable")
    if status.get("stale") is not False:
        return None
    if staged:
        active_dist = desktop_shell.resolve_active_frontend_dist(root)
        active = _read_provenance(active_dist / ".vibelution-build.json")
        build_key = status.get("currentFrontendBuildKey")
        frontend_tree = status.get("currentFrontendTree")
        frontend_commit = active.get("sourceCommit")
        if (
            not desktop_shell._usable_active_frontend_release(root)
            or not status.get("currentFrontendDist")
            or Path(status["currentFrontendDist"]).resolve() != active_dist.resolve()
            or not isinstance(build_key, str) or not _SHA256.fullmatch(build_key)
            or provenance.get("frontendBuildKey") != build_key or active.get("buildKey") != build_key
            or not isinstance(frontend_tree, str) or not _GIT_HASH.fullmatch(frontend_tree)
            or active.get("frontendTree") != frontend_tree
            or not isinstance(frontend_commit, str) or not _GIT_HASH.fullmatch(frontend_commit)
            or provenance.get("frontendSourceCommit") != frontend_commit
        ):
            return None
    assistant = provenance.get("assistant")
    hashes = [
        provenance.get("mainBundleSha256"),
        provenance.get("preloadBundleSha256"),
        provenance.get("frontendContentSha256"),
        assistant.get("contentSha256") if isinstance(assistant, dict) else None,
    ]
    if any(not isinstance(value, str) or not _SHA256.fullmatch(value) for value in hashes):
        return None
    with (package / "resources/app.asar").open("rb") as archive:
        archive_hash = hashlib.file_digest(archive, "sha256").hexdigest()
    identity = ["packaged", provenance["electronTreeHash"], *hashes, archive_hash]
    build_id = hashlib.sha256(
        json.dumps(identity, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if _read_provenance(provenance_path) != provenance:
        raise RuntimeError("Launcher package changed during inspection")
    return _build_metadata("packaged", build_id, provenance)
