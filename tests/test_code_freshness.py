"""Running-code freshness: snapshot write/read and verdict decisions."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
from pathlib import Path

import pytest

from core.web.services import code_freshness


def _write_snapshot(
    tmp_path: Path,
    *,
    head: str,
    branch: str = "main",
    started_at: str = "2026-08-09T00:35:54+00:00",
    dirty_status: str = "",
) -> None:
    path = code_freshness.running_code_fingerprint_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "projectRoot": str(tmp_path),
                "runningHead": head,
                "runningBranch": branch,
                "dirty": bool(dirty_status),
                "dirtyTreeDigest": hashlib.sha256(dirty_status.encode("utf-8")).hexdigest(),
                "servingFrontendBuildKey": "key",
                "servingFrontendRelease": "release-test",
                "startedAt": started_at,
                "source": "test",
            }
        ),
        encoding="utf-8",
    )


def _write_provenance(tmp_path: Path, *, built_from: str, tree: str) -> None:
    path = code_freshness.frontend_build_provenance_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "projectRoot": str(tmp_path),
                "sourceCommit": built_from,
                "builtFromCommit": built_from,
                "frontendTree": tree,
                "lastValidatedCommit": built_from,
                "lastValidatedFrontendTree": tree,
                "rebuilt": True,
            }
        ),
        encoding="utf-8",
    )


def test_write_and_read_running_fingerprint_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        code_freshness,
        "_capture_git_text",
        lambda root, args: "abc123def456" if args[:2] == ["rev-parse", "HEAD"] else "main",
    )
    result = code_freshness.write_running_code_fingerprint(project_root=tmp_path, source="test")
    assert result["written"] is True
    path = code_freshness.running_code_fingerprint_path(tmp_path)
    assert path.exists()
    parsed = code_freshness.read_running_code_fingerprint(tmp_path)
    assert parsed is not None
    assert parsed["schemaVersion"] == 1
    assert parsed["runningHead"] == "abc123def456"
    assert parsed["source"] == "test"
    # written payload matches the on-disk snapshot
    assert parsed["startedAt"] == result["startedAt"]


def test_write_running_fingerprint_publishes_identity_bound_serving_lease(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        code_freshness,
        "_capture_git_text",
        lambda root, args: "abc123def456" if args[:2] == ["rev-parse", "HEAD"] else "main",
    )
    monkeypatch.setattr(
        code_freshness,
        "capture_process_identity",
        lambda pid: {"pid": pid, "createTime": 456.5, "executable": "python.exe"},
    )
    result = code_freshness.write_running_code_fingerprint(
        project_root=tmp_path,
        source="test",
        serving_metadata={
            "apiContractVersion": "v1",
            "frontend": {
                "buildKey": "build-key",
                "release": "release-build-key",
            },
            "backend": {"startedAt": "started"},
        },
    )

    lease_path = code_freshness.serving_frontend_lease_path(
        tmp_path,
        pid=os.getpid(),
        create_time=456.5,
    )
    assert result["servingLeasePath"] == str(lease_path)
    assert json.loads(lease_path.read_text(encoding="utf-8"))["servingFrontendRelease"] == "release-build-key"


def test_read_missing_fingerprint_returns_none(tmp_path: Path) -> None:
    assert code_freshness.read_running_code_fingerprint(tmp_path) is None


def test_read_bad_schema_version_returns_none(tmp_path: Path) -> None:
    path = code_freshness.running_code_fingerprint_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schemaVersion": 99, "runningHead": "abc"}), encoding="utf-8")
    assert code_freshness.read_running_code_fingerprint(tmp_path) is None


def test_resolve_backend_current_when_snapshot_matches_disk(tmp_path: Path, monkeypatch) -> None:
    _write_snapshot(tmp_path, head="c269dafb9")
    monkeypatch.setattr(
        code_freshness,
        "_capture_git_text",
        lambda root, args: (
            "c269dafb9"
            if args[:2] == ["rev-parse", "HEAD"]
            else "main"
            if args[:2] == ["branch", "--show-current"]
            else ""
        ),
    )
    result = code_freshness.resolve_backend_freshness(project_root=tmp_path)
    assert result["available"] is True
    assert result["behind"] is False
    assert result["reason"] == ""


def test_resolve_backend_behind_reports_count(tmp_path: Path, monkeypatch) -> None:
    _write_snapshot(tmp_path, head="oldhead000000")
    calls: list[list[str]] = []

    def fake_git(root, args):
        calls.append(args)
        if args[:2] == ["rev-parse", "HEAD"]:
            return "newhead000000"
        if args[:2] == ["branch", "--show-current"]:
            return "main"
        if args[:3] == ["rev-list", "--count", "oldhead000000..newhead000000"]:
            return "3"
        return ""

    monkeypatch.setattr(code_freshness, "_capture_git_text", fake_git)
    result = code_freshness.resolve_backend_freshness(project_root=tmp_path)
    assert result["available"] is True
    assert result["behind"] is True
    assert result["behindCount"] == 3
    assert any(args[:3] == ["rev-list", "--count", "oldhead000000..newhead000000"] for args in calls)


def test_resolve_backend_behind_when_dirty_tree_digest_changes(tmp_path: Path, monkeypatch) -> None:
    _write_snapshot(tmp_path, head="same-head")

    def fake_git(root, args):
        if args[:2] == ["rev-parse", "HEAD"]:
            return "same-head"
        if args[:2] == ["branch", "--show-current"]:
            return "main"
        if args[:2] == ["status", "--porcelain=v1"]:
            return " M core/web/app.py"
        return ""

    monkeypatch.setattr(code_freshness, "_capture_git_text", fake_git)
    result = code_freshness.resolve_backend_freshness(project_root=tmp_path)

    assert result["available"] is True
    assert result["behind"] is True
    assert result["behindCount"] is None


def test_resolve_backend_missing_dirty_digest_is_unknown(tmp_path: Path, monkeypatch) -> None:
    path = code_freshness.running_code_fingerprint_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schemaVersion": 1, "runningHead": "same-head", "runningBranch": "main"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        code_freshness,
        "_capture_git_text",
        lambda root, args: "same-head" if args[:2] == ["rev-parse", "HEAD"] else "",
    )

    result = code_freshness.resolve_backend_freshness(project_root=tmp_path)

    assert result["available"] is False
    assert result["reason"] == "running_fingerprint_missing_dirty_digest"


def test_resolve_backend_missing_snapshot_is_unknown(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        code_freshness,
        "_capture_git_text",
        lambda root, args: "diskhead0000" if args[:2] == ["rev-parse", "HEAD"] else "main",
    )
    result = code_freshness.resolve_backend_freshness(project_root=tmp_path)
    assert result["available"] is False
    assert result["reason"] == "no_running_fingerprint"


def test_resolve_frontend_stale_when_tree_differs(tmp_path: Path, monkeypatch) -> None:
    _write_snapshot(tmp_path, head="oldhead000000")
    monkeypatch.setattr(
        code_freshness,
        "_inspect_active_frontend_build",
        lambda root: {
            "current": False,
            "reason": "frontend build key differs from active release",
            "provenance": {"builtFromCommit": "oldhead000000", "frontendTree": "oldtree000000"},
        },
    )
    result = code_freshness.resolve_frontend_freshness(project_root=tmp_path)
    assert result["available"] is True
    assert result["stale"] is True
    assert result["builtFromCommit"] == "oldhead000000"


def test_resolve_frontend_current_when_tree_matches(tmp_path: Path, monkeypatch) -> None:
    _write_snapshot(tmp_path, head="newhead000000")
    monkeypatch.setattr(
        code_freshness,
        "_inspect_active_frontend_build",
        lambda root: {
            "current": True,
            "reason": "frontend build is current",
            "provenance": {"builtFromCommit": "newhead000000", "frontendTree": "same-tree-000", "buildKey": "key"},
        },
    )
    result = code_freshness.resolve_frontend_freshness(project_root=tmp_path)
    assert result["available"] is True
    assert result["stale"] is False


def test_resolve_frontend_missing_serving_metadata_is_unknown(tmp_path: Path, monkeypatch) -> None:
    _write_snapshot(tmp_path, head="head00000000")
    path = code_freshness.running_code_fingerprint_path(tmp_path)
    parsed = json.loads(path.read_text(encoding="utf-8"))
    parsed.pop("servingFrontendBuildKey", None)
    parsed.pop("servingFrontendRelease", None)
    path.write_text(json.dumps(parsed), encoding="utf-8")
    monkeypatch.setattr(
        code_freshness,
        "_inspect_active_frontend_build",
        lambda root: {
            "current": True,
            "reason": "frontend build is current",
            "provenance": {"builtFromCommit": "head00000000", "frontendTree": "tree", "buildKey": "key"},
        },
    )

    result = code_freshness.resolve_frontend_freshness(project_root=tmp_path)

    assert result["available"] is False
    assert result["stale"] is True
    assert result["reason"] == "serving_metadata_missing"


def test_resolve_freshness_verdict_combinations(tmp_path: Path, monkeypatch) -> None:
    # current: backend matches + frontend matches
    _write_snapshot(tmp_path, head="head00000000")
    monkeypatch.setattr(
        code_freshness,
        "_inspect_active_frontend_build",
        lambda root: {
            "current": True,
            "reason": "frontend build is current",
            "provenance": {"builtFromCommit": "head00000000", "frontendTree": "tree00000000", "buildKey": "key"},
        },
    )

    def fake_git(root, args):
        if args[:2] == ["rev-parse", "HEAD"]:
            return "head00000000"
        if args[:2] == ["branch", "--show-current"]:
            return "main"
        if args == ["rev-parse", "HEAD:web"]:
            return "tree00000000"
        return ""

    monkeypatch.setattr(code_freshness, "_capture_git_text", fake_git)
    result = code_freshness.resolve_code_freshness(project_root=tmp_path)
    assert result["verdict"] == "current"

    # backend behind + frontend stale
    _write_snapshot(tmp_path, head="oldhead00000")
    monkeypatch.setattr(
        code_freshness,
        "_inspect_active_frontend_build",
        lambda root: {
            "current": False,
            "reason": "frontend build key differs from active release",
            "provenance": {"builtFromCommit": "oldhead00000", "frontendTree": "oldtree00000", "buildKey": "key"},
        },
    )

    def fake_git_behind(root, args):
        if args[:2] == ["rev-parse", "HEAD"]:
            return "newhead00000"
        if args[:2] == ["branch", "--show-current"]:
            return "main"
        if args[:3] == ["rev-list", "--count", "oldhead00000..newhead00000"]:
            return "2"
        if args == ["rev-parse", "HEAD:web"]:
            return "newtree00000"
        return ""

    monkeypatch.setattr(code_freshness, "_capture_git_text", fake_git_behind)
    result = code_freshness.resolve_code_freshness(project_root=tmp_path)
    assert result["verdict"] == "backend_and_frontend_behind"
    assert result["backend"]["behindCount"] == 2

    # missing snapshot → unknown
    monkeypatch.setattr(code_freshness, "_capture_git_text", fake_git)
    code_freshness.running_code_fingerprint_path(tmp_path).unlink(missing_ok=True)
    result = code_freshness.resolve_code_freshness(project_root=tmp_path)
    assert result["verdict"] == "unknown"
    assert result["backend"]["reason"] == "no_running_fingerprint"


# --- governed runtime home migration (write to governed, read with fallback) ---

def _governed_project(tmp_path: Path, monkeypatch, *, project_id: str = "freshness-project"):
    """Create a fully migrated governed project; return (root, runtime_home)."""
    from vibelution_storage import (
        PROJECTS_HOME_ENV,
        resolve_project_storage_paths,
        storage_migration_state_path,
    )

    projects_home = tmp_path / "projects-home"
    project_root = tmp_path / "checkout"
    project_root.mkdir()
    identity = project_root / ".vibelution" / "project.json"
    identity.parent.mkdir(parents=True)
    identity.write_text(json.dumps({"schemaVersion": 1, "projectId": project_id}), encoding="utf-8")
    monkeypatch.setenv(PROJECTS_HOME_ENV, str(projects_home))
    target = resolve_project_storage_paths(project_root, projects_home=projects_home)
    marker = storage_migration_state_path(target)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "status": "completed",
                "projectId": target.project_id,
                "instanceId": target.instance_id,
            }
        ),
        encoding="utf-8",
    )
    return project_root, target.runtime


def test_write_running_fingerprint_targets_governed_runtime_home(tmp_path: Path, monkeypatch) -> None:
    project_root, runtime_home = _governed_project(tmp_path, monkeypatch)
    monkeypatch.setattr(
        code_freshness,
        "_capture_git_text",
        lambda root, args: "govhead000001" if args[:2] == ["rev-parse", "HEAD"] else "main",
    )

    result = code_freshness.write_running_code_fingerprint(project_root=project_root, source="test")

    governed_path = runtime_home / "running-code-fingerprint.json"
    assert result["written"] is True
    assert result["path"] == str(governed_path)
    assert governed_path.is_file()
    assert not (project_root / ".runtime" / "running-code-fingerprint.json").exists()
    parsed = code_freshness.read_running_code_fingerprint(project_root)
    assert parsed is not None
    assert parsed["runningHead"] == "govhead000001"


def test_read_running_fingerprint_prefers_governed_over_legacy_copy(tmp_path: Path, monkeypatch) -> None:
    project_root, runtime_home = _governed_project(tmp_path, monkeypatch)

    def _snapshot(head: str) -> str:
        return json.dumps({"schemaVersion": 1, "runningHead": head})

    legacy_path = code_freshness.legacy_running_code_fingerprint_path(project_root)
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_text(_snapshot("legacyhead0001"), encoding="utf-8")
    # No governed copy yet: the pre-migration backend stays visible.
    parsed = code_freshness.read_running_code_fingerprint(project_root)
    assert parsed is not None
    assert parsed["runningHead"] == "legacyhead0001"

    governed_path = runtime_home / "running-code-fingerprint.json"
    governed_path.parent.mkdir(parents=True, exist_ok=True)
    governed_path.write_text(_snapshot("govhead000002"), encoding="utf-8")
    parsed = code_freshness.read_running_code_fingerprint(project_root)
    assert parsed is not None
    assert parsed["runningHead"] == "govhead000002"
    # Legacy copy remains readable in place; reads never migrate or delete.
    assert legacy_path.is_file()


def test_invalid_migration_marker_blocks_fingerprint_read_and_write(tmp_path: Path, monkeypatch) -> None:
    from vibelution_storage import ProjectStorageMigrationStateError
    from vibelution_storage import resolve_project_storage_paths, storage_migration_state_path

    project_root, _runtime_home = _governed_project(tmp_path, monkeypatch)
    target = resolve_project_storage_paths(project_root)
    storage_migration_state_path(target).write_text(
        json.dumps({"schemaVersion": 1, "status": "pending"}),
        encoding="utf-8",
    )
    # A legal snapshot in the legacy location must NOT be consulted once the
    # present marker fails closed.
    legacy_path = code_freshness.legacy_running_code_fingerprint_path(project_root)
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_text(
        json.dumps({"schemaVersion": 1, "runningHead": "legacyhead0002"}),
        encoding="utf-8",
    )
    assert code_freshness.read_running_code_fingerprint(project_root) is None

    monkeypatch.setattr(code_freshness, "_capture_git_text", lambda root, args: "x" if args[:2] == ["rev-parse", "HEAD"] else "main")
    with pytest.raises(ProjectStorageMigrationStateError):
        code_freshness.running_code_fingerprint_path(project_root)

    result = code_freshness.write_running_code_fingerprint(project_root=project_root, source="test")
    assert result["written"] is False
    assert result["errorType"] == ProjectStorageMigrationStateError.__name__


# --- 2026-09-11 freshness-gate incident regressions ---
# Incident: the serving backend was a 09-09 build while checkout main was two
# days ahead. The on-disk running-code fingerprint was missing, so the whole
# verdict collapsed to "unknown" and the UI rendered a neutral chip with no
# stale warning. The startup-pinned serving metadata is the same-event
# fallback, and a behind verdict must never be suppressed by an unknown panel.

def test_backend_falls_back_to_serving_metadata_when_snapshot_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Event anchor: checkout main moved ahead of the running 09-09 build while
    # the fingerprint file was unreadable; verdict must still be behind.
    monkeypatch.setattr(code_freshness, "read_running_code_fingerprint", lambda root: None)

    def fake_git(root, args):
        if args[:2] == ["rev-parse", "HEAD"]:
            return "freshhead0000"
        if args[:2] == ["branch", "--show-current"]:
            return "main"
        if args[:3] == ["rev-list", "--count", "oldhead00000..freshhead0000"]:
            return "189"
        return ""

    monkeypatch.setattr(code_freshness, "_capture_git_text", fake_git)
    fallback = {
        "runningHead": "oldhead00000",
        "runningBranch": "main",
        "dirty": False,
        "dirtyTreeDigest": hashlib.sha256(b"").hexdigest(),
        "pid": 33076,
        "createTime": 1788923484.7,
        "executable": "pythonw.exe",
        "startedAt": "2026-09-09T03:11:25+00:00",
        "source": "serving_metadata_fallback",
    }
    result = code_freshness.resolve_backend_freshness(
        project_root=tmp_path,
        fallback_snapshot=fallback,
    )
    assert result["available"] is True
    assert result["behind"] is True
    assert result["behindCount"] == 189
    assert result["source"] == "serving_metadata_fallback"

    verdict = code_freshness.resolve_code_freshness(
        project_root=tmp_path,
        fallback_snapshot=fallback,
    )
    assert verdict["verdict"] in {"backend_behind", "backend_and_frontend_behind"}


def test_verdict_backend_unknown_with_stale_frontend_reports_frontend_behind(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # A pre-digest snapshot (written by an older backend) leaves the backend
    # panel unavailable, but the frontend panel still proves the serving build
    # is behind. The combined verdict must surface that instead of collapsing
    # to "unknown" (which the old UI rendered as a neutral chip).
    path = code_freshness.running_code_fingerprint_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "runningHead": "oldhead00000",
                "runningBranch": "main",
                "servingFrontendBuildKey": "key",
                "servingFrontendRelease": "release-test",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        code_freshness,
        "_capture_git_text",
        lambda root, args: "diskhead00000" if args[:2] == ["rev-parse", "HEAD"] else "main",
    )
    monkeypatch.setattr(
        code_freshness,
        "_inspect_active_frontend_build",
        lambda root: {
            "current": False,
            "reason": "frontend build key differs from active release",
            "provenance": {"builtFromCommit": "oldhead00000", "frontendTree": "oldtree", "buildKey": "key"},
        },
    )
    result = code_freshness.resolve_code_freshness(project_root=tmp_path)
    assert result["backend"]["available"] is False
    assert result["frontend"]["available"] is True
    assert result["frontend"]["stale"] is True
    assert result["verdict"] == "frontend_behind"

    # An unavailable frontend panel is "cannot confirm", not proven behind:
    # with the backend panel unknown too, the verdict stays unknown.
    code_freshness.running_code_fingerprint_path(tmp_path).unlink()
    result = code_freshness.resolve_code_freshness(project_root=tmp_path)
    assert result["backend"]["available"] is False
    assert result["frontend"]["available"] is False
    assert result["verdict"] == "unknown"


def test_fallback_snapshot_from_serving_metadata_mapping() -> None:
    from core.web.services.code_freshness import fallback_snapshot_from_serving_metadata

    metadata = {
        "backend": {
            "head": "oldhead00000",
            "dirty": False,
            "dirtyTreeDigest": "digest",
            "pid": 12,
            "createTime": 34.5,
            "executable": "pythonw.exe",
            "startedAt": "started",
        }
    }
    snapshot = fallback_snapshot_from_serving_metadata(metadata)
    assert snapshot is not None
    assert snapshot["runningHead"] == "oldhead00000"
    assert snapshot["dirtyTreeDigest"] == "digest"
    assert snapshot["pid"] == 12
    assert snapshot["source"] == "serving_metadata_fallback"

    # Missing head or digest cannot support a behind decision: no fallback.
    assert fallback_snapshot_from_serving_metadata({"backend": {"head": "x"}}) is None
    assert fallback_snapshot_from_serving_metadata({"backend": {"dirtyTreeDigest": "d"}}) is None
    assert fallback_snapshot_from_serving_metadata(None) is None
    assert fallback_snapshot_from_serving_metadata({}) is None


def test_runtime_route_passes_pinned_serving_metadata_fallback(tmp_path: Path, monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.web.routes import runtime as runtime_routes

    pinned = {
        "schemaVersion": 1,
        "apiContractVersion": "v1",
        "frontend": {"buildKey": "k", "release": "release-k", "dist": "", "builtFromCommit": "oldhead00000"},
        "backend": {
            "schemaVersion": 1,
            "head": "oldhead00000",
            "dirty": False,
            "dirtyTreeDigest": hashlib.sha256(b"").hexdigest(),
            "pid": os.getpid(),
            "createTime": 123.5,
            "executable": "pythonw.exe",
            "startedAt": "started",
        },
    }
    captured: dict[str, object] = {}

    def fake_resolve(*, project_root, fallback_snapshot=None):
        captured["project_root"] = str(project_root)
        captured["fallback_snapshot"] = fallback_snapshot
        return {
            "schemaVersion": 1,
            "verdict": "backend_behind",
            "backend": {"available": True, "behind": True, "behindCount": 189, "reason": "", "source": "serving_metadata_fallback"},
            "frontend": {"available": True, "stale": False, "reason": "", "builtFromCommit": "", "frontendTree": "", "buildKey": "", "servingBuildKey": "", "servingRelease": "", "activeRelease": ""},
        }

    monkeypatch.setattr(runtime_routes, "resolve_code_freshness", fake_resolve)
    app = FastAPI()
    app.include_router(runtime_routes.router, prefix="/api")
    app.state.serving_metadata = json.loads(json.dumps(pinned))
    with TestClient(app) as client:
        payload = client.get("/api/runtime/code-freshness").json()

    assert payload["verdict"] == "backend_behind"
    fallback = captured["fallback_snapshot"]
    assert isinstance(fallback, dict)
    assert fallback["runningHead"] == "oldhead00000"
    assert fallback["dirtyTreeDigest"] == pinned["backend"]["dirtyTreeDigest"]
    assert captured["project_root"] == str(runtime_routes.PROJECT_ROOT)


# --- hot-path verdict cache (HEAD-file observation, no git process) ---

def _write_git_dir(tmp_path: Path, *, head: str, symref: str = "refs/heads/main") -> Path:
    """Fabricate a readable .git layout without spawning git (pure files)."""
    git_dir = tmp_path / ".git"
    ref_path = git_dir / symref
    ref_path.parent.mkdir(parents=True, exist_ok=True)
    (git_dir / "HEAD").write_text(f"ref: {symref}\n", encoding="utf-8")
    ref_path.write_text(f"{head}\n", encoding="utf-8")
    return git_dir


def _freshness_git_fake(holder: dict, calls: list):
    def fake_git(root, args):
        calls.append(list(args))
        if args[:2] == ["rev-parse", "HEAD"]:
            return holder["head"]
        if args[:2] == ["branch", "--show-current"]:
            return "main"
        if args[:3] == ["rev-list", "--count", f"{holder.get('running', '')}..{holder['head']}"]:
            return str(holder.get("behindCount", ""))
        return ""

    return fake_git


def _current_frontend_mock(built_from: str):
    return lambda root: {
        "current": True,
        "reason": "frontend build is current",
        "provenance": {
            "builtFromCommit": built_from,
            "frontendTree": f"{built_from}-tree",
            "buildKey": "key",
        },
    }


def test_resolve_code_freshness_fast_path_replays_cache_without_git(tmp_path: Path, monkeypatch) -> None:
    code_freshness.reset_freshness_caches_for_tests()
    _write_snapshot(tmp_path, head="head00000000")
    _write_git_dir(tmp_path, head="head00000000")
    holder = {"head": "head00000000"}
    calls: list[list[str]] = []
    monkeypatch.setattr(code_freshness, "_capture_git_text", _freshness_git_fake(holder, calls))
    monkeypatch.setattr(code_freshness, "_inspect_active_frontend_build", _current_frontend_mock("head00000000"))

    first = code_freshness.resolve_code_freshness(project_root=tmp_path)
    assert first["verdict"] == "current"
    assert calls, "first call must take the full path"
    calls_after_first = len(calls)

    second = code_freshness.resolve_code_freshness(project_root=tmp_path)
    assert len(calls) == calls_after_first, "unchanged HEAD+fingerprint must replay the cache with zero git calls"
    assert second == first

    # schema must stay identically shaped on the replayed payload
    assert set(second) == {"schemaVersion", "verdict", "backend", "frontend"}
    assert set(second["backend"]) == {"available", "behind", "behindCount", "reason", "source", "running", "disk"}
    assert set(second["backend"]["running"]) == {
        "head",
        "branch",
        "startedAt",
        "dirty",
        "dirtyTreeDigest",
        "pid",
        "createTime",
        "executable",
    }
    assert set(second["frontend"]) == {
        "available",
        "stale",
        "reason",
        "builtFromCommit",
        "frontendTree",
        "buildKey",
        "servingBuildKey",
        "servingRelease",
        "activeRelease",
    }

    # deep-copy isolation: a caller mutating the returned payload must not
    # corrupt the shared cache for the next poll
    second["verdict"] = "tampered"
    second["backend"]["disk"]["head"] = "tampered"
    third = code_freshness.resolve_code_freshness(project_root=tmp_path)
    assert third == first


def test_resolve_code_freshness_head_change_reruns_full_path_and_refreshes_cache(tmp_path: Path, monkeypatch) -> None:
    code_freshness.reset_freshness_caches_for_tests()
    _write_snapshot(tmp_path, head="oldhead00000")
    git_dir = _write_git_dir(tmp_path, head="oldhead00000")
    holder = {"head": "oldhead00000", "running": "oldhead00000", "behindCount": 2}
    calls: list[list[str]] = []
    monkeypatch.setattr(code_freshness, "_capture_git_text", _freshness_git_fake(holder, calls))
    monkeypatch.setattr(code_freshness, "_inspect_active_frontend_build", _current_frontend_mock("oldhead00000"))

    first = code_freshness.resolve_code_freshness(project_root=tmp_path)
    assert first["verdict"] == "current"
    calls_after_first = len(calls)

    # HEAD moves on disk: the file observation must notice without any help.
    holder["head"] = "newhead00000"
    (git_dir / "refs" / "heads" / "main").write_text("newhead00000\n", encoding="utf-8")
    second = code_freshness.resolve_code_freshness(project_root=tmp_path)
    assert len(calls) > calls_after_first
    assert second["verdict"] == "backend_behind"
    assert second["backend"]["behindCount"] == 2
    assert second["backend"]["disk"]["head"] == "newhead00000"

    # The refreshed behind verdict itself is cached: further polls stay free.
    calls_after_second = len(calls)
    third = code_freshness.resolve_code_freshness(project_root=tmp_path)
    assert len(calls) == calls_after_second
    assert third == second


def test_resolve_code_freshness_fingerprint_change_reruns_full_path(tmp_path: Path, monkeypatch) -> None:
    code_freshness.reset_freshness_caches_for_tests()
    _write_snapshot(tmp_path, head="head00000000")
    _write_git_dir(tmp_path, head="head00000000")
    holder = {"head": "head00000000"}
    calls: list[list[str]] = []
    monkeypatch.setattr(code_freshness, "_capture_git_text", _freshness_git_fake(holder, calls))
    monkeypatch.setattr(code_freshness, "_inspect_active_frontend_build", _current_frontend_mock("head00000000"))

    first = code_freshness.resolve_code_freshness(project_root=tmp_path)
    assert first["verdict"] == "current"
    calls_after_first = len(calls)

    # A rewritten snapshot (new running branch + new file stamps) must
    # invalidate the cache even though disk HEAD did not move.
    _write_snapshot(tmp_path, head="head00000000", branch="feature", started_at="2026-10-02T00:00:00+00:00")
    second = code_freshness.resolve_code_freshness(project_root=tmp_path)
    assert len(calls) > calls_after_first
    assert second["backend"]["running"]["branch"] == "feature"


def test_resolve_code_freshness_ttl_expiry_rereads_head_file(tmp_path: Path, monkeypatch) -> None:
    code_freshness.reset_freshness_caches_for_tests()
    _write_snapshot(tmp_path, head="head00000000")
    _write_git_dir(tmp_path, head="head00000000")
    holder = {"head": "head00000000"}
    calls: list[list[str]] = []
    monkeypatch.setattr(code_freshness, "_capture_git_text", _freshness_git_fake(holder, calls))
    monkeypatch.setattr(code_freshness, "_inspect_active_frontend_build", _current_frontend_mock("head00000000"))

    code_freshness.resolve_code_freshness(project_root=tmp_path)
    calls_after_first = len(calls)

    real_monotonic = code_freshness._monotonic
    shift = {"delta": 0.0}

    def shifted_monotonic() -> float:
        return real_monotonic() + shift["delta"]

    monkeypatch.setattr(code_freshness, "_monotonic", shifted_monotonic)
    shift["delta"] = code_freshness.FRESHNESS_FAST_PATH_TTL_SECONDS + 1.0

    second = code_freshness.resolve_code_freshness(project_root=tmp_path)
    assert len(calls) > calls_after_first, "TTL expiry must leave the fast path and re-read inputs"
    assert any(args[:2] == ["rev-parse", "HEAD"] for args in calls[calls_after_first:])
    assert second["verdict"] == "current"


def test_backend_freshness_polling_git_calls_carry_no_optional_locks(tmp_path: Path, monkeypatch) -> None:
    _write_snapshot(tmp_path, head="head00000000")
    captured: list[list[str]] = []

    def fake_run_git(args, *, cwd, timeout=15.0, env=None):
        captured.append([str(part) for part in args])
        stdout = ""
        if args[-2:] == ["rev-parse", "HEAD"]:
            stdout = "head00000000"
        elif args[-2:] == ["branch", "--show-current"]:
            stdout = "main"
        return subprocess.CompletedProcess(args=list(args), returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(code_freshness, "run_git", fake_run_git)

    result = code_freshness.resolve_backend_freshness(project_root=tmp_path)

    assert result["available"] is True
    assert captured
    assert all(args[0] == "--no-optional-locks" for args in captured), captured


def test_dirty_summary_keeps_last_known_value_within_throttle(tmp_path: Path, monkeypatch) -> None:
    code_freshness.reset_freshness_caches_for_tests()
    _write_snapshot(tmp_path, head="same-head")
    _write_git_dir(tmp_path, head="same-head")
    holder = {"head": "same-head"}
    status_calls: list[list[str]] = []

    def fake_git(root, args):
        # _capture_git_text sees the raw subcommand argv (the --no-optional-locks
        # prefix is added inside the real helper when spawning).
        if args[:1] == ["status"]:
            status_calls.append(list(args))
            return " M core/web/app.py"
        if args[:2] == ["rev-parse", "HEAD"]:
            return holder["head"]
        if args[:2] == ["branch", "--show-current"]:
            return "main"
        return ""

    monkeypatch.setattr(code_freshness, "_capture_git_text", fake_git)
    monkeypatch.setattr(code_freshness, "_inspect_active_frontend_build", _current_frontend_mock("same-head"))

    first = code_freshness.resolve_code_freshness(project_root=tmp_path)
    assert first["backend"]["behind"] is True  # dirty digest differs from the clean snapshot
    assert len(status_calls) == 1
    calls_after_first = len(status_calls)

    # Same HEAD + fingerprint: the dirty walk stays throttled out of the hot
    # path and the last known dirty value is replayed from cache.
    second = code_freshness.resolve_code_freshness(project_root=tmp_path)
    assert len(status_calls) == calls_after_first
    assert second == first


# --- concurrent full resolutions: per-root single flight ---

def test_resolve_code_freshness_single_flight_shares_one_full_resolution(
    tmp_path: Path, monkeypatch
) -> None:
    """并发 full resolution 必须合并为一个 flight：follower 等待并共享 leader 的 verdict。"""

    code_freshness.reset_freshness_caches_for_tests()
    _write_snapshot(tmp_path, head="head00000000")
    _write_git_dir(tmp_path, head="head00000000")
    holder = {"head": "head00000000"}
    calls: list[list[str]] = []
    monkeypatch.setattr(code_freshness, "_capture_git_text", _freshness_git_fake(holder, calls))
    monkeypatch.setattr(code_freshness, "_inspect_active_frontend_build", _current_frontend_mock("head00000000"))

    entered_frontend = threading.Event()
    release_frontend = threading.Event()
    frontend_entries: list[int] = []
    real_frontend = code_freshness.resolve_frontend_freshness

    def slow_frontend(*, project_root):
        frontend_entries.append(1)
        entered_frontend.set()
        assert release_frontend.wait(timeout=5)
        return real_frontend(project_root=project_root)

    monkeypatch.setattr(code_freshness, "resolve_frontend_freshness", slow_frontend)

    # 打点 flight 锁的 wait：follower 真正进入 flight 等待队列后再放行 leader，
    # 避免 join 先于 release 造成测试自身死锁。
    follower_waiting = threading.Event()
    flight_lock = code_freshness._FRESHNESS_FLIGHT_LOCK
    original_wait = flight_lock.wait

    def tracked_wait(timeout=None):
        follower_waiting.set()
        return original_wait(timeout)

    monkeypatch.setattr(flight_lock, "wait", tracked_wait)

    results: list[dict] = []

    def worker():
        results.append(code_freshness.resolve_code_freshness(project_root=tmp_path))

    leader = threading.Thread(target=worker)
    leader.start()
    assert entered_frontend.wait(timeout=5), "leader must enter the full resolution"
    follower = threading.Thread(target=worker)
    follower.start()
    assert follower_waiting.wait(timeout=5), "follower must wait inside the flight gate"
    # follower 在 leader 完成前只等待，不再自己全价解析。
    assert frontend_entries == [1]

    release_frontend.set()
    leader.join(timeout=5)
    follower.join(timeout=5)

    assert not leader.is_alive()
    assert not follower.is_alive()
    assert len(results) == 2
    assert results[0] == results[1]
    assert results[0]["verdict"] == "current"
    assert frontend_entries == [1], "leader + waiter must share exactly one full resolution"


def test_resolve_code_freshness_leader_failure_is_not_shared(tmp_path: Path, monkeypatch) -> None:
    """leader 失败不共享：waiter 落回并自己算，异常只打在 leader 上。"""

    code_freshness.reset_freshness_caches_for_tests()
    _write_snapshot(tmp_path, head="head00000000")
    _write_git_dir(tmp_path, head="head00000000")
    holder = {"head": "head00000000"}
    calls: list[list[str]] = []
    monkeypatch.setattr(code_freshness, "_capture_git_text", _freshness_git_fake(holder, calls))
    monkeypatch.setattr(code_freshness, "_inspect_active_frontend_build", _current_frontend_mock("head00000000"))

    entered_frontend = threading.Event()
    release_frontend = threading.Event()
    frontend_attempts: list[int] = []
    real_frontend = code_freshness.resolve_frontend_freshness

    def flaky_frontend(*, project_root):
        frontend_attempts.append(1)
        if len(frontend_attempts) == 1:
            entered_frontend.set()
            assert release_frontend.wait(timeout=5)
            raise RuntimeError("injected leader failure")
        return real_frontend(project_root=project_root)

    monkeypatch.setattr(code_freshness, "resolve_frontend_freshness", flaky_frontend)

    outcomes: dict[str, object] = {}

    def leader_worker():
        try:
            outcomes["leader"] = code_freshness.resolve_code_freshness(project_root=tmp_path)
        except Exception as exc:  # noqa: BLE001 - test probes the leader failure path
            outcomes["leader"] = exc

    def follower_worker():
        try:
            outcomes["follower"] = code_freshness.resolve_code_freshness(project_root=tmp_path)
        except Exception as exc:  # noqa: BLE001 - a shared failure would surface here
            outcomes["follower"] = exc

    leader = threading.Thread(target=leader_worker)
    leader.start()
    assert entered_frontend.wait(timeout=5)
    follower = threading.Thread(target=follower_worker)
    follower.start()
    release_frontend.set()
    leader.join(timeout=5)
    follower.join(timeout=5)

    assert not leader.is_alive() and not follower.is_alive()
    assert isinstance(outcomes["leader"], RuntimeError), outcomes["leader"]
    # waiter 未继承 leader 的失败：自己重算并成功返回。
    assert isinstance(outcomes["follower"], dict), outcomes["follower"]
    assert outcomes["follower"]["verdict"] == "current"
    assert len(frontend_attempts) == 2


def test_resolve_code_freshness_fast_path_stays_outside_flight_gate(
    tmp_path: Path, monkeypatch
) -> None:
    """TTL 快路径命中不得进 flight 锁：缓存命中不创建/触碰 flight 记录。"""

    code_freshness.reset_freshness_caches_for_tests()
    _write_snapshot(tmp_path, head="head00000000")
    _write_git_dir(tmp_path, head="head00000000")
    holder = {"head": "head00000000"}
    calls: list[list[str]] = []
    monkeypatch.setattr(code_freshness, "_capture_git_text", _freshness_git_fake(holder, calls))
    monkeypatch.setattr(code_freshness, "_inspect_active_frontend_build", _current_frontend_mock("head00000000"))

    first = code_freshness.resolve_code_freshness(project_root=tmp_path)
    assert first["verdict"] == "current"

    # 全价路径已结束（flight 不再 inflight）；清掉 flight 记录后，缓存命中
    # 必须原样返回且不重建任何 flight 状态。
    with code_freshness._FRESHNESS_FLIGHT_LOCK:
        assert all(
            not flight["inflight"] for flight in code_freshness._FRESHNESS_FLIGHTS.values()
        )
        code_freshness._FRESHNESS_FLIGHTS.clear()

    second = code_freshness.resolve_code_freshness(project_root=tmp_path)
    assert second == first
    assert code_freshness._FRESHNESS_FLIGHTS == {}, "fast-path hit must not touch the flight gate"
