from __future__ import annotations

import importlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from core.launcher import frontend_build
from core.web.services import serving_version


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

    # Simulate a later publish.  The already-created app must keep serving the
    # immutable release selected at startup.
    second = tmp_path / "release-second"
    second.mkdir()
    (tmp_path / "active.json").write_text(json.dumps({"release": second.name, "buildKey": "key-second"}), encoding="utf-8")

    with TestClient(app) as client:
        payload = client.get("/api/health").json()

    assert payload["apiContractVersion"] == "v1"
    assert payload["serving"]["frontend"]["release"] == "release-first"
    assert payload["servingBuildKey"] == "key-first"
    assert payload["backendCodeFingerprint"]["dirtyTreeDigest"] == "digest-first"
