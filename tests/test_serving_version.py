from __future__ import annotations

import importlib
import json
import subprocess
from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from core.launcher import frontend_build
from core.web.services import serving_version


@pytest.mark.parametrize("failure", ["error", "timeout"])
def test_failed_status_is_not_a_clean_startup_proof(tmp_path, monkeypatch, failure):
    def failed(*_args, **_kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired("git", 1)
        return subprocess.CompletedProcess([], 128, "", "unavailable")
    monkeypatch.setattr(serving_version, "run_git", failed)
    summary = serving_version.git_dirty_tree_summary(tmp_path)
    assert summary["dirtyStateVerified"] is False
    assert serving_version.build_backend_code_fingerprint(tmp_path)["dirtyStateVerified"] is False


def test_head_change_during_startup_cannot_prove_clean_sources(tmp_path, monkeypatch):
    heads = iter(["a" * 40, "b" * 40])
    monkeypatch.setattr(serving_version, "_git_text", lambda _root, args: next(heads) if args == ["rev-parse", "HEAD"] else "")
    result = serving_version.build_backend_code_fingerprint(tmp_path)
    assert result["head"] == "a" * 40
    assert result["dirtyStateVerified"] is False


def _write_release(root: Path, name: str, build_key: str) -> Path:
    release = frontend_build.frontend_releases_dir(root) / name
    (release / "assets").mkdir(parents=True, exist_ok=True)
    (release / "index.html").write_text('<script src="/assets/app.js"></script>', encoding="utf-8")
    (release / "assets" / "app.js").write_text("ok", encoding="utf-8")
    (release / ".vibelution-build.json").write_text(
        json.dumps(
            {
                "schemaVersion": frontend_build.BUILD_SCHEMA_VERSION,
                "buildKey": build_key,
                "builtFromCommit": "head",
            }
        ),
        encoding="utf-8",
    )
    return release


def _activate(root: Path, release: Path, build_key: str) -> None:
    pointer = frontend_build.active_release_path(root)
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(
        json.dumps(
            {
                "schemaVersion": frontend_build.BUILD_SCHEMA_VERSION,
                "release": release.name,
                "buildKey": build_key,
            }
        ),
        encoding="utf-8",
    )


def test_resolve_serving_frontend_tracks_active_release_until_process_pins_it(tmp_path: Path) -> None:
    first = _write_release(tmp_path, "release-first", "key-first")
    second = _write_release(tmp_path, "release-second", "key-second")
    _activate(tmp_path, first, "key-first")

    captured = serving_version.resolve_serving_frontend(tmp_path)
    assert captured["release"] == first.name
    assert captured["buildKey"] == "key-first"

    _activate(tmp_path, second, "key-second")
    current = serving_version.resolve_serving_frontend(tmp_path)
    assert current["release"] == second.name
    assert current["buildKey"] == "key-second"
    # The backend must retain the earlier value in app.state after startup;
    # the app test below covers that process-level pin.


def test_build_backend_code_fingerprint_contains_identity_and_dirty_digest(monkeypatch, tmp_path: Path) -> None:
    def fake_git(_root: Path, args: list[str]) -> str:
        if args == ["rev-parse", "HEAD"]:
            return "head-123"
        if args == ["status", "--porcelain=v1", "--untracked-files=all"]:
            return " M core/web/app.py\n"
        return ""

    monkeypatch.setattr(serving_version, "_git_text", fake_git)
    monkeypatch.setattr(
        serving_version,
        "capture_process_identity",
        lambda pid: {"pid": pid, "createTime": 123.5, "executable": "python.exe"},
    )

    result = serving_version.build_backend_code_fingerprint(tmp_path, pid=4321, started_at="started")

    assert result["head"] == "head-123"
    assert result["dirty"] is True
    assert result["dirtyTreeDigest"]
    assert result["pid"] == 4321
    assert result["createTime"] == 123.5
    assert result["executable"] == "python.exe"
    assert result["startedAt"] == "started"


def test_health_reports_pinned_serving_metadata_after_active_pointer_switch(monkeypatch, tmp_path: Path) -> None:
    app_module = importlib.import_module("core.web.app")
    first_metadata = {
        "schemaVersion": 1,
        "apiContractVersion": "v1",
        "frontend": {
            "buildKey": "key-first",
            "release": "release-first",
            "dist": str(tmp_path / "release-first"),
            "builtFromCommit": "head-first",
        },
        "backend": {
            "schemaVersion": 1,
            "head": "head-first",
            "dirty": False,
            "dirtyTreeDigest": "digest-first",
            "pid": 123,
            "createTime": 123.5,
            "executable": "python.exe",
            "startedAt": "started-first",
        },
    }
    monkeypatch.setattr(app_module, "_health_workspace_root", lambda: str(tmp_path))
    monkeypatch.setattr(app_module, "build_serving_metadata", lambda _root: json.loads(json.dumps(first_metadata)))
    app = app_module.create_app()

    with TestClient(app) as client:
        # Nothing is published yet, so the pointer has nothing to disagree with.
        before = client.get("/api/health").json()

        # Simulate a later publish.  The already-created app must keep serving the
        # immutable release selected at startup.
        second = tmp_path / "release-second"
        second.mkdir()
        pointer = frontend_build.active_release_path(tmp_path)
        pointer.parent.mkdir(parents=True, exist_ok=True)
        pointer.write_text(
            json.dumps({"release": second.name, "buildKey": "key-second"}),
            encoding="utf-8",
        )
        payload = client.get("/api/health").json()

    assert before["activeRelease"] == ""
    assert before["releaseStale"] is False
    assert payload["apiContractVersion"] == "v1"
    assert payload["serving"]["frontend"]["release"] == "release-first"
    assert payload["servingBuildKey"] == "key-first"
    # The pointer moved but this process still serves its pinned release.  Health
    # has to say so, otherwise "why does my change not show up" stays invisible
    # and the only remaining signal is an empty servingRelease field.
    assert payload["activeRelease"] == "release-second"
    assert payload["releaseStale"] is True
    assert payload["backendCodeFingerprint"]["dirtyTreeDigest"] == "digest-first"


def test_serving_frontend_names_the_release_source_for_a_published_tree(tmp_path: Path) -> None:
    release = _write_release(tmp_path, "release-live", "key-live")
    _activate(tmp_path, release, "key-live")

    captured = serving_version.resolve_serving_frontend(tmp_path)

    assert captured["release"] == "release-live"
    assert captured["source"] == frontend_build.SERVING_SOURCE_RELEASE
    assert captured["fallbackReason"] == ""


def test_serving_frontend_names_the_legacy_tree_instead_of_hiding_it(tmp_path: Path) -> None:
    legacy = frontend_build.legacy_frontend_dist(tmp_path)
    (legacy / "assets").mkdir(parents=True, exist_ok=True)
    (legacy / "index.html").write_text("<html></html>", encoding="utf-8")

    captured = serving_version.resolve_serving_frontend(tmp_path)

    assert captured["source"] == frontend_build.SERVING_SOURCE_LEGACY_DIST
    assert captured["fallbackReason"] == "active_release_missing"
    assert captured["release"] == ""
