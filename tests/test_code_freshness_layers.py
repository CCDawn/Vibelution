"""Layered code freshness: changed-path buckets, restartRequired, layers.

The legacy ``verdict`` (backend_behind / frontend_behind / ...) keeps its
exact semantics for existing consumers; the layered surface is strictly
additive: ``classify_changed_paths`` buckets, backend ``changedPathCounts`` /
``restartRequired`` / ``pathClassification``, the ``desktopShell`` panel,
``layers`` and ``requiredAction``.  A version-projection commit (closeout's
per-merge release bump) moves HEAD without touching runtime code, so the
layered view must stop demanding a restart while ``verdict`` still reports
the backend panel behind.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.web.services import code_freshness


@pytest.fixture(autouse=True)
def _reset_caches() -> None:
    code_freshness.reset_freshness_caches_for_tests()
    yield
    code_freshness.reset_freshness_caches_for_tests()


# --- pure classification ------------------------------------------------------


def test_classify_buckets_each_known_surface() -> None:
    buckets = code_freshness.classify_changed_paths(
        [
            "web/src/app/main.ts",
            "web/package.json",
            "desktop/electron/src/main.ts",
            "core/web/services/code_freshness.py",
            "tests/test_code_freshness_layers.py",
            "docs/standards/development-standard.md",
            ".changelog/codex-something.md",
            ".github/workflows/ci.yml",
            "CHANGELOG.md",
            "VERSION",
            "web/package-lock.json",
            "web/src/app/panel.test.ts",
            "core/web/services/code_freshness.test.py",
        ]
    )
    assert buckets["frontend"] == ["web/src/app/main.ts"]
    assert buckets["version_projection"] == [
        "web/package.json",
        "CHANGELOG.md",
        "VERSION",
        "web/package-lock.json",
    ]
    assert buckets["desktop_shell"] == ["desktop/electron/src/main.ts"]
    assert buckets["backend"] == ["core/web/services/code_freshness.py"]
    assert buckets["non_runtime"] == [
        "tests/test_code_freshness_layers.py",
        "docs/standards/development-standard.md",
        ".changelog/codex-something.md",
        ".github/workflows/ci.yml",
        "web/src/app/panel.test.ts",
        "core/web/services/code_freshness.test.py",
    ]


def test_classify_is_conservative_for_unknown_paths() -> None:
    buckets = code_freshness.classify_changed_paths(
        ["flake.nix", "scripts/task_closeout.py", "desktop/packaging/VibelutionLauncher.iss", "", "./web/keep.ts"]
    )
    assert buckets["backend"] == [
        "flake.nix",
        "scripts/task_closeout.py",
        "desktop/packaging/VibelutionLauncher.iss",
    ]
    assert buckets["frontend"] == ["web/keep.ts"]
    assert buckets["version_projection"] == []
    assert buckets["non_runtime"] == []
    assert buckets["desktop_shell"] == []


def test_classify_handles_windows_separators() -> None:
    buckets = code_freshness.classify_changed_paths(["core\\web\\app.py", "web\\src\\x.ts"])
    assert buckets["backend"] == ["core/web/app.py"]
    assert buckets["frontend"] == ["web/src/x.ts"]


def test_classify_empty_input_gives_empty_buckets() -> None:
    buckets = code_freshness.classify_changed_paths([])
    assert set(buckets.keys()) == set(code_freshness.CHANGED_PATH_BUCKETS)
    assert all(count == [] for count in buckets.values())


# --- backend panel fields -----------------------------------------------------


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


def _isolate_git_env(monkeypatch) -> None:
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"):
        monkeypatch.delenv(name, raising=False)


def _init_repo_with_layered_commits(root: Path) -> tuple[str, str]:
    """Base commit touches backend code; second commit is backend-free."""
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "freshness@example.local")
    _git(root, "config", "user.name", "Freshness Test")
    # The runtime home for an identity-less test checkout is the repo's own
    # .runtime; keep fingerprint writes out of commits and diffs, like the
    # real checkout's .gitignore does.
    (root / ".gitignore").write_text(".runtime/\nweb/.vibelution-builds/\n", encoding="utf-8")
    (root / "core" / "web").mkdir(parents=True)
    (root / "core" / "web" / "svc.py").write_text("print('base')\n", encoding="utf-8")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "base")
    base = _git(root, "rev-parse", "HEAD")

    (root / "web" / "src").mkdir(parents=True)
    (root / "web" / "src" / "main.ts").write_text("export {};\n", encoding="utf-8")
    (root / "web" / "package.json").write_text('{"version": "9.9.9"}\n', encoding="utf-8")
    (root / "web" / "package-lock.json").write_text('{"version": "9.9.9"}\n', encoding="utf-8")
    (root / "VERSION").write_text("9.9.9\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text("## Unreleased\n- x\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "t.py").write_text("def test_t():\n    pass\n", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "d.md").write_text("doc\n", encoding="utf-8")
    (root / "desktop" / "electron" / "src").mkdir(parents=True)
    (root / "desktop" / "electron" / "src" / "main.ts").write_text("export {};\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "version and frontend only")
    return base, _git(root, "rev-parse", "HEAD")


def _write_fingerprint(tmp_path: Path, *, head: str, built_from: str | None = None) -> None:
    path = code_freshness.running_code_fingerprint_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "projectRoot": str(tmp_path),
                "runningHead": head,
                "runningBranch": "main",
                "dirty": False,
                "dirtyTreeDigest": hashlib.sha256(b"").hexdigest(),
                "servingFrontendBuildKey": "key",
                "servingFrontendRelease": "release-test",
                "servingFrontendBuiltFromCommit": built_from or head,
                "startedAt": "2026-01-01T00:00:00+00:00",
                "source": "test",
            }
        ),
        encoding="utf-8",
    )


def _seed_current_frontend(tmp_path: Path, monkeypatch) -> None:
    """Active pointer + inspection that make the frontend panel report current."""
    releases = tmp_path / "web" / ".vibelution-builds"
    releases.mkdir(parents=True, exist_ok=True)
    (releases / "active.json").write_text(
        json.dumps({"schemaVersion": 2, "release": "release-test", "buildKey": "key"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        code_freshness,
        "_inspect_active_frontend_build",
        lambda root: {
            "current": True,
            "reason": "frontend build is current",
            "provenance": {"builtFromCommit": "key", "frontendTree": "tree", "buildKey": "key"},
        },
    )


def test_backend_panel_restart_required_false_for_version_only_drift(tmp_path: Path, monkeypatch) -> None:
    _isolate_git_env(monkeypatch)
    base, second = _init_repo_with_layered_commits(tmp_path)
    _write_fingerprint(tmp_path, head=base)

    result = code_freshness.resolve_backend_freshness(project_root=tmp_path)

    assert result["available"] is True
    assert result["behind"] is True
    assert result["behindCount"] == 1
    assert result["pathClassification"] == "available"
    assert result["restartRequired"] is False
    assert result["changedPathCounts"] == {
        "frontend": 1,
        "desktop_shell": 1,
        "version_projection": 4,
        "non_runtime": 2,
        "backend": 0,
    }


def test_backend_panel_restart_required_true_for_backend_drift(tmp_path: Path, monkeypatch) -> None:
    _isolate_git_env(monkeypatch)
    base, second = _init_repo_with_layered_commits(tmp_path)
    _write_fingerprint(tmp_path, head=base)
    (tmp_path / "core" / "web" / "svc.py").write_text("print('changed')\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "backend change")

    result = code_freshness.resolve_backend_freshness(project_root=tmp_path)

    assert result["behind"] is True
    assert result["pathClassification"] == "available"
    assert result["restartRequired"] is True
    assert result["changedPathCounts"]["backend"] == 1


def test_backend_panel_falls_back_to_behind_count_when_diff_unavailable(tmp_path: Path, monkeypatch) -> None:
    _write_fingerprint(tmp_path, head="oldhead000000")
    real_run_git = code_freshness.run_git

    def fake_run_git(args, **kwargs):
        if args[1:2] == ["diff"]:
            return SimpleNamespace(returncode=128, stdout="")
        return real_run_git(args, **kwargs)

    monkeypatch.setattr(code_freshness, "run_git", fake_run_git)
    monkeypatch.setattr(
        code_freshness,
        "_capture_git_text",
        lambda root, args: (
            "newhead000000"
            if args[:2] == ["rev-parse", "HEAD"]
            else "main"
            if args[:2] == ["branch", "--show-current"]
            else "3"
            if args[:3] == ["rev-list", "--count", "oldhead000000..newhead000000"]
            else ""
        ),
    )

    result = code_freshness.resolve_backend_freshness(project_root=tmp_path)

    assert result["available"] is True
    assert result["behind"] is True
    assert result["behindCount"] == 3
    assert result["pathClassification"] == "unavailable"
    assert result["restartRequired"] is True


def test_changed_path_classification_is_cached_per_commit_pair(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    real = code_freshness._git_changed_paths_between

    def counting(root, *, from_head, to_head):
        calls.append((str(from_head), str(to_head)))
        return real(root, from_head=from_head, to_head=to_head)

    monkeypatch.setattr(code_freshness, "_git_changed_paths_between", counting)
    monkeypatch.setattr(
        code_freshness,
        "_capture_git_text",
        lambda root, args: (
            "newhead000000"
            if args[:2] == ["rev-parse", "HEAD"]
            else "main"
            if args[:2] == ["branch", "--show-current"]
            else "1"
            if args[:3] == ["rev-list", "--count", "oldhead000000..newhead000000"]
            else ""
        ),
    )
    _write_fingerprint(tmp_path, head="oldhead000000")
    first = code_freshness.resolve_backend_freshness(project_root=tmp_path)
    second = code_freshness.resolve_backend_freshness(project_root=tmp_path)
    assert first["changedPathCounts"] == second["changedPathCounts"]
    assert len(calls) == 1, "the same (running, disk) commit pair must not re-run the diff"


# --- desktop shell panel ------------------------------------------------------


def _patch_unpackaged_shell(monkeypatch, *, stale: bool, reason: str, electron_bin: Path) -> list[int]:
    import core.launcher.desktop_shell as desktop_shell
    import core.launcher.desktop_shell_owner as shell_owner

    calls: list[int] = []

    def fake_inspect(root):
        calls.append(1)
        return {
            "schemaVersion": 1,
            "stale": stale,
            "reason": reason,
            "bundledElectronTree": "tree",
            "currentElectronTree": "tree",
            "electronExecutable": str(electron_bin),
            "mainJs": "main.js",
            "sourceNewerThanBundle": False,
        }

    monkeypatch.setattr(desktop_shell, "inspect_unpackaged_electron", fake_inspect)
    monkeypatch.setattr(desktop_shell, "unpackaged_electron_executable", lambda root=None: electron_bin)
    monkeypatch.setattr(desktop_shell, "unpackaged_main_js", lambda root=None: electron_bin.parent / "main.js")
    monkeypatch.setattr(desktop_shell, "packaged_desktop_exe", lambda root=None: Path(root) / "packaged" / "Vibelution.exe")
    monkeypatch.setattr(desktop_shell, "packaged_asar_path", lambda root=None: Path(root) / "packaged" / "resources" / "app.asar")
    monkeypatch.setattr(shell_owner, "read_desktop_shell_owner", lambda root: {"owner": "electron", "pid": 1, "executable": str(electron_bin)})
    return calls


def test_desktop_shell_panel_stale_when_owner_matches(tmp_path: Path, monkeypatch) -> None:
    electron_bin = tmp_path / "electron.exe"
    electron_bin.write_text("bin", encoding="utf-8")
    calls = _patch_unpackaged_shell(
        monkeypatch, stale=True, reason="provenance_mismatch", electron_bin=electron_bin
    )

    panel = code_freshness.resolve_desktop_shell_freshness(project_root=tmp_path)

    assert panel["available"] is True
    assert panel["shellKind"] == "unpackaged"
    assert panel["stale"] is True
    assert panel["current"] is False
    assert panel["reason"] == "provenance_mismatch"
    assert panel["action"] == "replace_shell"
    assert calls == [1]


def test_desktop_shell_panel_not_stale_when_owner_differs(tmp_path: Path, monkeypatch) -> None:
    import core.launcher.desktop_shell as desktop_shell
    import core.launcher.desktop_shell_owner as shell_owner

    electron_bin = tmp_path / "electron.exe"
    electron_bin.write_text("bin", encoding="utf-8")
    _patch_unpackaged_shell(
        monkeypatch, stale=True, reason="provenance_mismatch", electron_bin=electron_bin
    )
    monkeypatch.setattr(
        shell_owner,
        "read_desktop_shell_owner",
        lambda root: {"owner": "electron", "pid": 1, "executable": str(tmp_path / "other.exe")},
    )

    panel = code_freshness.resolve_desktop_shell_freshness(project_root=tmp_path)

    assert panel["stale"] is False
    assert panel["action"] == "none"


def test_desktop_shell_panel_missing_binary_never_prompts(tmp_path: Path, monkeypatch) -> None:
    electron_bin = tmp_path / "electron.exe"
    _patch_unpackaged_shell(
        monkeypatch, stale=True, reason="missing_binary", electron_bin=electron_bin
    )

    panel = code_freshness.resolve_desktop_shell_freshness(project_root=tmp_path)

    assert panel["stale"] is False
    assert panel["reason"] == "missing_binary"


def test_desktop_shell_panel_governs_packaged_shell_when_owner_is_packaged(tmp_path: Path, monkeypatch) -> None:
    import core.launcher.desktop_shell as desktop_shell
    import core.launcher.desktop_shell_owner as shell_owner

    electron_bin = tmp_path / "electron.exe"
    electron_bin.write_text("bin", encoding="utf-8")
    packaged_exe = tmp_path / "packaged" / "Vibelution.exe"
    packaged_exe.parent.mkdir(parents=True)
    packaged_exe.write_text("exe", encoding="utf-8")
    asar = tmp_path / "packaged" / "resources" / "app.asar"
    asar.parent.mkdir(parents=True)
    asar.write_text("asar", encoding="utf-8")
    _patch_unpackaged_shell(monkeypatch, stale=True, reason="provenance_mismatch", electron_bin=electron_bin)
    monkeypatch.setattr(
        desktop_shell, "inspect_desktop_shell", lambda root: {"stale": True, "reason": "electron_source_stale"}
    )
    monkeypatch.setattr(
        shell_owner,
        "read_desktop_shell_owner",
        lambda root: {"owner": "electron", "pid": 1, "executable": str(packaged_exe)},
    )

    panel = code_freshness.resolve_desktop_shell_freshness(project_root=tmp_path)

    assert panel["shellKind"] == "packaged"
    assert panel["available"] is True
    assert panel["stale"] is True
    assert panel["reason"] == "electron_source_stale"


def test_desktop_shell_panel_result_is_cached_by_observation(tmp_path: Path, monkeypatch) -> None:
    electron_bin = tmp_path / "electron.exe"
    electron_bin.write_text("bin", encoding="utf-8")
    calls = _patch_unpackaged_shell(
        monkeypatch, stale=False, reason="current", electron_bin=electron_bin
    )

    first = code_freshness.resolve_desktop_shell_freshness(project_root=tmp_path)
    second = code_freshness.resolve_desktop_shell_freshness(project_root=tmp_path)
    assert calls == [1], "unchanged observation must replay the cached panel"
    assert second == first

    code_freshness.reset_freshness_caches_for_tests()
    third = code_freshness.resolve_desktop_shell_freshness(project_root=tmp_path)
    assert calls == [1, 1], "a dropped cache recomputes instead of replaying"


# --- combined layers and requiredAction ---------------------------------------


def _disk_head_git(tmp_path: Path, *, disk_head: str, running_head: str, behind_count: str = "1"):
    def fake_git(root, args):
        if args[:2] == ["rev-parse", "HEAD"]:
            return disk_head
        if args[:2] == ["branch", "--show-current"]:
            return "main"
        if args[:3] == ["rev-list", "--count", f"{running_head}..{disk_head}"]:
            return behind_count
        return ""

    return fake_git


def test_layers_report_no_restart_for_version_only_drift(tmp_path: Path, monkeypatch) -> None:
    _isolate_git_env(monkeypatch)
    base, second = _init_repo_with_layered_commits(tmp_path)
    _write_fingerprint(tmp_path, head=base)
    _seed_current_frontend(tmp_path, monkeypatch)

    result = code_freshness.resolve_code_freshness(project_root=tmp_path)

    # Legacy verdict keeps its semantics: heads differ, so the combined verdict
    # still reports the backend panel behind for existing consumers.
    assert result["verdict"] == "backend_behind"
    assert result["backend"]["behind"] is True
    assert result["backend"]["restartRequired"] is False
    assert result["layers"]["backend"] == {"current": True, "action": "none"}
    assert result["layers"]["frontend"] == {"current": True, "action": "none"}
    assert result["requiredAction"] == "none"


def test_layers_demand_restart_when_backend_bucket_changed(tmp_path: Path, monkeypatch) -> None:
    _isolate_git_env(monkeypatch)
    base, second = _init_repo_with_layered_commits(tmp_path)
    _write_fingerprint(tmp_path, head=base)
    _seed_current_frontend(tmp_path, monkeypatch)
    (tmp_path / "core" / "web" / "svc.py").write_text("print('changed')\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "backend change")

    result = code_freshness.resolve_code_freshness(project_root=tmp_path)

    assert result["verdict"] == "backend_behind"
    assert result["backend"]["restartRequired"] is True
    assert result["layers"]["backend"] == {"current": False, "action": "restart_backend"}
    assert result["requiredAction"] == "restart_backend"


def test_layers_map_frontend_reload_only_when_switch_is_ready(tmp_path: Path, monkeypatch) -> None:
    _isolate_git_env(monkeypatch)
    base, second = _init_repo_with_layered_commits(tmp_path)
    # Backend layer stays current: the fingerprint head equals disk HEAD, so
    # the only staleness is the frontend release pointer.
    _write_fingerprint(tmp_path, head=second)
    _seed_current_frontend(tmp_path, monkeypatch)
    releases = tmp_path / "web" / ".vibelution-builds"
    (releases / "active.json").write_text(
        json.dumps({"schemaVersion": 2, "release": "release-new", "buildKey": "key2"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        code_freshness,
        "evaluate_frontend_switch",
        lambda **kwargs: {
            "available": True,
            "status": "ready",
            "reason": "",
            "servingRelease": "release-test",
            "activeRelease": "release-new",
        },
    )

    result = code_freshness.resolve_code_freshness(project_root=tmp_path)

    assert result["verdict"] == "frontend_behind"
    assert result["layers"]["backend"] == {"current": True, "action": "none"}
    assert result["layers"]["frontend"] == {"current": False, "action": "reload_page"}
    assert result["requiredAction"] == "reload_page"


def test_layers_keep_restart_when_switch_is_not_ready(tmp_path: Path, monkeypatch) -> None:
    _isolate_git_env(monkeypatch)
    base, second = _init_repo_with_layered_commits(tmp_path)
    _write_fingerprint(tmp_path, head=second)
    _seed_current_frontend(tmp_path, monkeypatch)
    releases = tmp_path / "web" / ".vibelution-builds"
    (releases / "active.json").write_text(
        json.dumps({"schemaVersion": 2, "release": "release-new", "buildKey": "key2"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        code_freshness,
        "evaluate_frontend_switch",
        lambda **kwargs: {
            "available": False,
            "status": "restart_required",
            "reason": "backend_code_changed",
            "servingRelease": "release-test",
            "activeRelease": "release-new",
        },
    )

    result = code_freshness.resolve_code_freshness(project_root=tmp_path)

    assert result["verdict"] == "frontend_behind"
    assert result["layers"]["frontend"] == {"current": False, "action": "restart_backend"}
    assert result["requiredAction"] == "restart_backend"


def test_layers_prefer_replace_shell_over_everything(tmp_path: Path, monkeypatch) -> None:
    _isolate_git_env(monkeypatch)
    base, second = _init_repo_with_layered_commits(tmp_path)
    _write_fingerprint(tmp_path, head=base)
    _seed_current_frontend(tmp_path, monkeypatch)
    (tmp_path / "core" / "web" / "svc.py").write_text("print('changed')\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "backend change")
    releases = tmp_path / "web" / ".vibelution-builds"
    (releases / "active.json").write_text(
        json.dumps({"schemaVersion": 2, "release": "release-new", "buildKey": "key2"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        code_freshness,
        "evaluate_frontend_switch",
        lambda **kwargs: {"available": True, "status": "ready", "reason": "", "servingRelease": "release-test", "activeRelease": "release-new"},
    )
    monkeypatch.setattr(
        code_freshness,
        "resolve_desktop_shell_freshness",
        lambda *, project_root: {
            "schemaVersion": 1,
            "available": True,
            "shellKind": "unpackaged",
            "stale": True,
            "current": False,
            "reason": "provenance_mismatch",
            "action": "replace_shell",
            "unpackaged": {},
            "packaged": {},
        },
    )

    result = code_freshness.resolve_code_freshness(project_root=tmp_path)

    assert result["verdict"] == "backend_and_frontend_behind"
    assert result["layers"]["desktopShell"] == {"current": False, "action": "replace_shell"}
    assert result["requiredAction"] == "replace_shell"


def test_layers_all_current_maps_to_none(tmp_path: Path, monkeypatch) -> None:
    _isolate_git_env(monkeypatch)
    base, second = _init_repo_with_layered_commits(tmp_path)
    _write_fingerprint(tmp_path, head=base)
    _seed_current_frontend(tmp_path, monkeypatch)
    _git(tmp_path, "commit", "--allow-empty", "-m", "no-op")

    result = code_freshness.resolve_code_freshness(project_root=tmp_path)

    assert result["verdict"] == "backend_behind"
    assert result["backend"]["restartRequired"] is False
    assert result["requiredAction"] == "none"


def test_legacy_panel_fields_stay_pinned(tmp_path: Path, monkeypatch) -> None:
    _isolate_git_env(monkeypatch)
    base, second = _init_repo_with_layered_commits(tmp_path)
    _write_fingerprint(tmp_path, head=base)
    _seed_current_frontend(tmp_path, monkeypatch)

    result = code_freshness.resolve_code_freshness(project_root=tmp_path)

    assert set(code_freshness.CHANGED_PATH_BUCKETS) == set(result["backend"]["changedPathCounts"].keys())
    assert set(result["backend"].keys()) == {
        "available",
        "behind",
        "behindCount",
        "changedPathCounts",
        "restartRequired",
        "pathClassification",
        "reason",
        "source",
        "running",
        "disk",
    }
    assert set(result["frontend"].keys()) == {
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
    assert result["schemaVersion"] == 1
    assert result["verdict"] in {
        "backend_behind",
        "frontend_behind",
        "backend_and_frontend_behind",
        "current",
        "unknown",
    }
