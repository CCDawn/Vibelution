"""Running-code freshness: snapshot write/read and verdict decisions."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

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
