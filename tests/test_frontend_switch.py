"""Hot frontend release switch: safety gates, atomic apply, old-release safety.

The switch moves the backend's pinned serving release to the active one only
when zero ``backend``-bucket paths changed between the running commit and the
target release's build source commit.  These tests exercise the real gate
chain against a real git repository and real published release directories,
including the endpoint contract and the retained-asset fallback that keeps
open tabs working after a switch.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.services import code_freshness, frontend_switch


@pytest.fixture(autouse=True)
def _reset_caches() -> None:
    code_freshness.reset_freshness_caches_for_tests()
    yield
    code_freshness.reset_freshness_caches_for_tests()


@pytest.fixture(autouse=True)
def _isolate_git_env(monkeypatch):
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"):
        monkeypatch.delenv(name, raising=False)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"git {args} failed: {result.stderr or result.stdout}")
    return result.stdout.strip()


def _write_release(path: Path, *, build_key: str, built_from: str, asset_name: str, asset_body: str) -> None:
    (path / "assets").mkdir(parents=True, exist_ok=True)
    (path / "assets" / asset_name).write_text(asset_body, encoding="utf-8")
    (path / "index.html").write_text(
        f'<!doctype html><html><head><script src="/assets/{asset_name}"></script></head>'
        f"<body>build {build_key}</body></html>\n",
        encoding="utf-8",
    )
    (path / ".vibelution-build.json").write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "buildKey": build_key,
                "builtFromCommit": built_from,
                "sourceCommit": built_from,
                "frontendTree": f"tree-{build_key}",
                "publishedAt": 1.0,
            }
        ),
        encoding="utf-8",
    )


def _make_repo_with_releases(tmp_path: Path, *, backend_change: bool = False) -> tuple[Path, str, str, str, str]:
    """Base commit (backend code) + frontend-only commit; two published releases."""
    root = tmp_path / "checkout"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "switch@example.local")
    _git(root, "config", "user.name", "Switch Test")
    # Keep the checkout .runtime runtime home out of commits and diffs, like
    # the real checkout's .gitignore does.
    (root / ".gitignore").write_text(".runtime/\nweb/.vibelution-builds/\n", encoding="utf-8")
    (root / "core" / "web").mkdir(parents=True)
    (root / "core" / "web" / "svc.py").write_text("print('base')\n", encoding="utf-8")
    (root / "web" / "src").mkdir(parents=True)
    (root / "web" / "src" / "main.ts").write_text("export const a = 1;\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "base")
    base = _git(root, "rev-parse", "HEAD")

    if backend_change:
        (root / "core" / "web" / "svc.py").write_text("print('changed')\n", encoding="utf-8")
    (root / "web" / "src" / "main.ts").write_text("export const a = 2;\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "frontend build inputs")
    frontend_commit = _git(root, "rev-parse", "HEAD")

    releases = root / "web" / ".vibelution-builds"
    _write_release(
        releases / "release-old",
        build_key="key-old",
        built_from=base,
        asset_name="old.js",
        asset_body="old-bundle",
    )
    _write_release(
        releases / "release-new",
        build_key="key-new",
        built_from=frontend_commit,
        asset_name="new.js",
        asset_body="new-bundle",
    )
    return root, base, frontend_commit, "release-old", "release-new"


def _write_fingerprint(root: Path, *, head: str, release: str, build_key: str, built_from: str) -> None:
    path = code_freshness.running_code_fingerprint_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "projectRoot": str(root),
                "runningHead": head,
                "runningBranch": "main",
                "dirty": False,
                "dirtyTreeDigest": hashlib.sha256(b"").hexdigest(),
                "pid": 1234,
                "createTime": 1000.0,
                "executable": "python.exe",
                "servingFrontendBuildKey": build_key,
                "servingFrontendRelease": release,
                "servingFrontendDist": str(root / "web" / ".vibelution-builds" / release),
                "servingFrontendBuiltFromCommit": built_from,
                "startedAt": "2026-01-01T00:00:00+00:00",
                "source": "test",
            }
        ),
        encoding="utf-8",
    )


def _set_active_pointer(root: Path, release: str, build_key: str) -> None:
    pointer_path = root / "web" / ".vibelution-builds" / "active.json"
    pointer_path.write_text(
        json.dumps({"schemaVersion": 2, "release": release, "buildKey": build_key}),
        encoding="utf-8",
    )


def _page(response) -> str:
    """Normalize Windows CRLF so assertions compare logical content."""
    return response.text.replace("\r\n", "\n")


def _make_app(root: Path, base: str, release_old: str) -> FastAPI:
    from core.web.routes.runtime import router as runtime_router
    from core.web.route_bootstrap import register_spa_routes

    app = FastAPI()
    app.include_router(runtime_router)
    release_old_dir = root / "web" / ".vibelution-builds" / release_old
    app.state.serving_metadata = {
        "schemaVersion": 1,
        "apiContractVersion": "v1",
        "frontend": {
            "schemaVersion": 1,
            "buildKey": "key-old",
            "release": release_old,
            "dist": str(release_old_dir),
            "builtFromCommit": base,
            "source": "release",
            "fallbackReason": "",
        },
        "backend": {
            "schemaVersion": 1,
            "head": base,
            "dirty": False,
            "dirtyTreeDigest": hashlib.sha256(b"").hexdigest(),
            "pid": 1234,
            "createTime": 1000.0,
            "executable": "python.exe",
            "startedAt": "2026-01-01T00:00:00+00:00",
        },
    }
    app.state.serving_frontend_dist = str(release_old_dir)
    register_spa_routes(app, web_dist=release_old_dir)
    return app


# --- decision (evaluate_frontend_switch) --------------------------------------


def test_evaluate_reports_already_current_when_serving_equals_active(tmp_path: Path) -> None:
    root, base, frontend_commit, release_old, release_new = _make_repo_with_releases(tmp_path)
    _write_fingerprint(root, head=base, release=release_old, build_key="key-old", built_from=base)
    _set_active_pointer(root, release_old, "key-old")

    decision = code_freshness.evaluate_frontend_switch(project_root=root)

    assert decision["status"] == "already_current"
    assert decision["available"] is True
    assert decision["servingRelease"] == release_old


def test_evaluate_unavailable_when_serving_release_unrecorded(tmp_path: Path) -> None:
    root, base, frontend_commit, release_old, release_new = _make_repo_with_releases(tmp_path)
    _set_active_pointer(root, release_new, "key-new")

    decision = code_freshness.evaluate_frontend_switch(project_root=root)

    assert decision["status"] == "unavailable"
    assert decision["reason"] == "serving_release_unrecorded"


def test_evaluate_unavailable_when_active_pointer_missing(tmp_path: Path) -> None:
    root, base, frontend_commit, release_old, release_new = _make_repo_with_releases(tmp_path)
    _write_fingerprint(root, head=base, release=release_old, build_key="key-old", built_from=base)

    decision = code_freshness.evaluate_frontend_switch(project_root=root)

    assert decision["status"] == "unavailable"
    assert decision["reason"] == "active_release_missing"


def test_evaluate_rejects_incomplete_target_release(tmp_path: Path) -> None:
    root, base, frontend_commit, release_old, release_new = _make_repo_with_releases(tmp_path)
    _write_fingerprint(root, head=base, release=release_old, build_key="key-old", built_from=base)
    _set_active_pointer(root, release_new, "key-new")
    (root / "web" / ".vibelution-builds" / release_new / "assets" / "new.js").unlink()

    decision = code_freshness.evaluate_frontend_switch(project_root=root)

    assert decision["status"] == "restart_required"
    assert decision["reason"] == "target_release_incomplete"


def test_evaluate_rejects_when_build_source_commit_missing(tmp_path: Path) -> None:
    root, base, frontend_commit, release_old, release_new = _make_repo_with_releases(tmp_path)
    _write_fingerprint(root, head=base, release=release_old, build_key="key-old", built_from="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef")
    _set_active_pointer(root, release_new, "key-new")

    decision = code_freshness.evaluate_frontend_switch(project_root=root)

    assert decision["status"] == "restart_required"
    assert decision["reason"] == "build_source_commit_missing"


def test_evaluate_rejects_when_backend_paths_changed(tmp_path: Path) -> None:
    root, base, frontend_commit, release_old, release_new = _make_repo_with_releases(tmp_path, backend_change=True)
    _write_fingerprint(root, head=base, release=release_old, build_key="key-old", built_from=base)
    _set_active_pointer(root, release_new, "key-new")

    decision = code_freshness.evaluate_frontend_switch(project_root=root)

    assert decision["status"] == "restart_required"
    assert decision["reason"] == "backend_code_changed"


def test_evaluate_ready_for_frontend_only_change(tmp_path: Path) -> None:
    root, base, frontend_commit, release_old, release_new = _make_repo_with_releases(tmp_path)
    _write_fingerprint(root, head=base, release=release_old, build_key="key-old", built_from=base)
    _set_active_pointer(root, release_new, "key-new")

    decision = code_freshness.evaluate_frontend_switch(project_root=root)

    assert decision["status"] == "ready"
    assert decision["available"] is True
    assert decision["servingRelease"] == release_old
    assert decision["activeRelease"] == release_new


# --- switch execution ----------------------------------------------------------


def test_switch_moves_serving_to_active_and_new_requests_hit_new_dist(tmp_path: Path) -> None:
    root, base, frontend_commit, release_old, release_new = _make_repo_with_releases(tmp_path)
    _write_fingerprint(root, head=base, release=release_old, build_key="key-old", built_from=base)
    _set_active_pointer(root, release_new, "key-new")
    app = _make_app(root, base, release_old)
    client = TestClient(app)

    assert _page(client.get("/")).endswith("build key-old</body></html>\n")

    result = frontend_switch.switch_frontend_to_active_release(app=app, project_root=root)

    assert result["status"] == "switched"
    assert result["servingRelease"] == release_new
    assert result["activeRelease"] == release_new
    assert result["switchedFrom"] == release_old
    # New page and SPA fallback requests land on the new release bytes.
    assert _page(client.get("/")).endswith("build key-new</body></html>\n")
    assert _page(client.get("/some/spa/route")).endswith("build key-new</body></html>\n")
    # The pinned in-memory serving identity moved, so /api/health-style readers
    # of app.state report the new release immediately.
    assert app.state.serving_metadata["frontend"]["release"] == release_new
    assert app.state.serving_metadata["frontend"]["buildKey"] == "key-new"
    assert app.state.serving_frontend_dist == str(root / "web" / ".vibelution-builds" / release_new)
    fingerprint = code_freshness.read_running_code_fingerprint(root) or {}
    assert fingerprint.get("servingFrontendRelease") == release_new
    assert fingerprint.get("runningHead") == base, "the process did not restart; running HEAD must stay"
    assert fingerprint.get("servingFrontendBuiltFromCommit") == frontend_commit


def test_switch_endpoint_contract_over_http(tmp_path: Path, monkeypatch) -> None:
    root, base, frontend_commit, release_old, release_new = _make_repo_with_releases(tmp_path)
    _write_fingerprint(root, head=base, release=release_old, build_key="key-old", built_from=base)
    _set_active_pointer(root, release_new, "key-new")
    from core.web.routes import runtime as runtime_routes

    monkeypatch.setattr(runtime_routes, "PROJECT_ROOT", root)
    app = _make_app(root, base, release_old)
    client = TestClient(app)

    response = client.post("/runtime/frontend/switch")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "switched"
    assert payload["servingRelease"] == release_new
    assert payload["activeRelease"] == release_new
    assert payload["reason"] == ""

    again = client.post("/runtime/frontend/switch")
    assert again.status_code == 200
    assert again.json()["status"] == "already_current"
    assert again.json()["servingRelease"] == release_new


def test_switch_rejects_backend_change_and_keeps_serving_old_dist(tmp_path: Path) -> None:
    root, base, frontend_commit, release_old, release_new = _make_repo_with_releases(tmp_path, backend_change=True)
    _write_fingerprint(root, head=base, release=release_old, build_key="key-old", built_from=base)
    _set_active_pointer(root, release_new, "key-new")
    app = _make_app(root, base, release_old)
    client = TestClient(app)

    result = frontend_switch.switch_frontend_to_active_release(app=app, project_root=root)

    assert result["status"] == "restart_required"
    assert result["reason"] == "backend_code_changed"
    assert result["servingRelease"] == release_old
    assert _page(client.get("/")).endswith("build key-old</body></html>\n")
    assert app.state.serving_metadata["frontend"]["release"] == release_old


def test_switch_unavailable_when_serving_record_missing(tmp_path: Path) -> None:
    root, base, frontend_commit, release_old, release_new = _make_repo_with_releases(tmp_path)
    _set_active_pointer(root, release_new, "key-new")
    app = _make_app(root, base, release_old)
    app.state.serving_metadata["frontend"]["release"] = ""

    result = frontend_switch.switch_frontend_to_active_release(app=app, project_root=root)

    assert result["status"] == "unavailable"
    assert result["reason"] == "serving_release_unrecorded"


def test_previous_release_assets_still_load_after_switch(tmp_path: Path) -> None:
    root, base, frontend_commit, release_old, release_new = _make_repo_with_releases(tmp_path)
    _write_fingerprint(root, head=base, release=release_old, build_key="key-old", built_from=base)
    _set_active_pointer(root, release_new, "key-new")
    app = _make_app(root, base, release_old)
    client = TestClient(app)

    result = frontend_switch.switch_frontend_to_active_release(app=app, project_root=root)
    assert result["status"] == "switched"

    # Open tabs keep requesting hashed chunks of the release they started on;
    # the retained-release fallback must keep answering from the previous
    # release after the switch (GC still protects it via the process lease).
    old_asset = client.get("/assets/old.js")
    assert old_asset.status_code == 200
    assert old_asset.text == "old-bundle"
    new_asset = client.get("/assets/new.js")
    assert new_asset.status_code == 200
    assert new_asset.text == "new-bundle"


def test_switch_leaves_previous_release_directory_on_disk(tmp_path: Path) -> None:
    root, base, frontend_commit, release_old, release_new = _make_repo_with_releases(tmp_path)
    _write_fingerprint(root, head=base, release=release_old, build_key="key-old", built_from=base)
    _set_active_pointer(root, release_new, "key-new")
    app = _make_app(root, base, release_old)

    result = frontend_switch.switch_frontend_to_active_release(app=app, project_root=root)
    assert result["status"] == "switched"
    assert (root / "web" / ".vibelution-builds" / release_old / "index.html").is_file()


# --- fingerprint persistence ----------------------------------------------------


def test_update_serving_frontend_release_preserves_running_identity(tmp_path: Path) -> None:
    root, base, frontend_commit, release_old, release_new = _make_repo_with_releases(tmp_path)
    _write_fingerprint(root, head=base, release=release_old, build_key="key-old", built_from=base)

    result = code_freshness.update_serving_frontend_release(
        root,
        release=release_new,
        build_key="key-new",
        dist=str(root / "web" / ".vibelution-builds" / release_new),
        built_from_commit=frontend_commit,
    )

    assert result["updated"] is True
    fingerprint = code_freshness.read_running_code_fingerprint(root) or {}
    assert fingerprint["runningHead"] == base
    assert fingerprint["runningBranch"] == "main"
    assert fingerprint["servingFrontendRelease"] == release_new
    assert fingerprint["servingFrontendBuildKey"] == "key-new"
    assert fingerprint["servingFrontendBuiltFromCommit"] == frontend_commit


def test_update_serving_frontend_release_report_missing_fingerprint(tmp_path: Path) -> None:
    root, base, frontend_commit, release_old, release_new = _make_repo_with_releases(tmp_path)
    result = code_freshness.update_serving_frontend_release(
        root,
        release=release_new,
        build_key="key-new",
        dist="nowhere",
        built_from_commit=frontend_commit,
    )
    assert result["updated"] is False
    assert result["reason"] == "no_fingerprint"


# --- rollback on shell repin failure (R1) + fingerprintPersisted (R6) ----------


def test_switch_rolls_back_when_new_release_fails_shell_validation(tmp_path: Path, monkeypatch) -> None:
    """A repin that lands on an invalid dist must restore the old serving state.

    register_spa_routes swallows shell-validation failures into
    ``web_shell_ready=False`` instead of raising, so the rollback must trigger
    on the silent mode as well as on exceptions; afterwards the page shell and
    the pinned serving identity are exactly what they were before the switch.
    """
    import core.web.route_bootstrap as route_bootstrap

    root, base, frontend_commit, release_old, release_new = _make_repo_with_releases(tmp_path)
    _write_fingerprint(root, head=base, release=release_old, build_key="key-old", built_from=base)
    _set_active_pointer(root, release_new, "key-new")
    app = _make_app(root, base, release_old)
    client = TestClient(app)
    real_repin = route_bootstrap.repin_web_shell
    old_dir = root / "web" / ".vibelution-builds" / release_old
    new_dir = root / "web" / ".vibelution-builds" / release_new

    def failing_repin(app_, web_dist):
        if Path(web_dist) == new_dir:
            # Simulate register_spa_routes failing shell validation silently.
            app_.state.web_shell_ready = False
            app_.state.web_shell_error = "Frontend release references a missing asset."
            return {
                "repinned": True,
                "dist": str(web_dist),
                "shellReady": False,
                "shellError": app_.state.web_shell_error,
            }
        return real_repin(app_, web_dist)

    monkeypatch.setattr(route_bootstrap, "repin_web_shell", failing_repin)

    result = frontend_switch.switch_frontend_to_active_release(app=app, project_root=root)

    assert result["status"] == "unavailable"
    assert result["reason"] == "shell_repin_failed"
    assert "missing asset" in result.get("detail", "")
    # Serving state restored to the pre-switch snapshot.
    assert app.state.serving_metadata["frontend"]["release"] == release_old
    assert app.state.serving_metadata["frontend"]["buildKey"] == "key-old"
    assert app.state.serving_frontend_dist == str(old_dir)
    # Shell routes are pinned back to the old dist and actually usable.
    assert app.state.web_shell_ready is True
    assert _page(client.get("/")).endswith("build key-old</body></html>\n")
    # The on-disk fingerprint never moved.
    fingerprint = code_freshness.read_running_code_fingerprint(root) or {}
    assert fingerprint.get("servingFrontendRelease") == release_old


def test_switch_rolls_back_when_repin_raises(tmp_path: Path, monkeypatch) -> None:
    import core.web.route_bootstrap as route_bootstrap

    root, base, frontend_commit, release_old, release_new = _make_repo_with_releases(tmp_path)
    _write_fingerprint(root, head=base, release=release_old, build_key="key-old", built_from=base)
    _set_active_pointer(root, release_new, "key-new")
    app = _make_app(root, base, release_old)
    client = TestClient(app)
    old_dir = root / "web" / ".vibelution-builds" / release_old

    real_repin = route_bootstrap.repin_web_shell
    new_dir = root / "web" / ".vibelution-builds" / release_new

    def exploding_repin(app_, web_dist):
        if Path(web_dist) == new_dir:
            raise RuntimeError(f"repin boom for {web_dist}")
        return real_repin(app_, web_dist)

    monkeypatch.setattr(route_bootstrap, "repin_web_shell", exploding_repin)

    result = frontend_switch.switch_frontend_to_active_release(app=app, project_root=root)

    assert result["status"] == "unavailable"
    assert result["reason"] == "shell_repin_failed"
    assert "repin boom" in result.get("detail", "")
    assert app.state.serving_frontend_dist == str(old_dir)
    assert app.state.serving_metadata["frontend"]["release"] == release_old
    assert _page(client.get("/")).endswith("build key-old</body></html>\n")


def test_switch_reports_rollback_failure_when_old_dist_repin_also_fails(tmp_path: Path, monkeypatch) -> None:
    import core.web.route_bootstrap as route_bootstrap

    root, base, frontend_commit, release_old, release_new = _make_repo_with_releases(tmp_path)
    _write_fingerprint(root, head=base, release=release_old, build_key="key-old", built_from=base)
    _set_active_pointer(root, release_new, "key-new")
    app = _make_app(root, base, release_old)
    client = TestClient(app)

    def always_failing_repin(_app, _web_dist):
        raise RuntimeError("rollback repin boom")

    monkeypatch.setattr(route_bootstrap, "repin_web_shell", always_failing_repin)

    result = frontend_switch.switch_frontend_to_active_release(app=app, project_root=root)

    assert result["status"] == "unavailable"
    assert result["reason"].startswith("shell_rollback_failed_restart_required")
    # The exception detail must reach the caller verbatim, not be swallowed.
    assert "rollback repin boom" in result["reason"]


def test_switched_response_marks_failed_fingerprint_persistence(tmp_path: Path, monkeypatch) -> None:
    root, base, frontend_commit, release_old, release_new = _make_repo_with_releases(tmp_path)
    _write_fingerprint(root, head=base, release=release_old, build_key="key-old", built_from=base)
    _set_active_pointer(root, release_new, "key-new")
    app = _make_app(root, base, release_old)
    client = TestClient(app)

    def failing_persistence(*_args, **_kwargs):
        return {"updated": False, "reason": "no_fingerprint"}

    monkeypatch.setattr(frontend_switch, "update_serving_frontend_release", failing_persistence)

    result = frontend_switch.switch_frontend_to_active_release(app=app, project_root=root)

    # The switch itself is the user-visible success; the failed persistence is
    # surfaced through the flag instead of failing the whole switch.
    assert result["status"] == "switched"
    assert result["fingerprintPersisted"] is False
    assert app.state.serving_frontend_dist == str(root / "web" / ".vibelution-builds" / release_new)
    assert _page(client.get("/")).endswith("build key-new</body></html>\n")
