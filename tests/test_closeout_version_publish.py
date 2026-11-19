"""Tests for the post-merge version projection automation in task_closeout."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import local_quality_gate as gate
from scripts import task_closeout as closeout


@pytest.fixture(autouse=True)
def valid_development_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(closeout, "validate_development_claim", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(closeout, "discover_manifest", lambda _context: None)


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _init_main_repo(root: Path, *, version: str = "2.0.0") -> None:
    root.mkdir(parents=True, exist_ok=True)
    assert _run_git(root, "init").returncode == 0
    _run_git(root, "config", "user.email", "publish@example.invalid")
    _run_git(root, "config", "user.name", "Publish Test")
    (root / "VERSION").write_text(f"{version}\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## Unreleased\n- feat: pending declared change.\n\n"
        f"## {version} - 2026-11-01\n\n- prior.\n",
        encoding="utf-8",
        newline="\n",
    )
    (root / "web").mkdir(exist_ok=True)
    (root / "web" / "package.json").write_text(
        json.dumps({"name": "fixture", "version": version}, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "web" / "package-lock.json").write_text(
        json.dumps(
            {"name": "fixture", "version": version, "packages": {"": {"version": version}}},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _run_git(root, "add", ".")
    _run_git(root, "commit", "-m", "seed")
    _run_git(root, "branch", "-M", "main")


def _seed_ledger(tmp_path: Path, root: Path, name: str) -> Path:
    from core.platform_version.ledger import VersionEntry, VersionLedger

    ledger_path = tmp_path / f"{name}-ledger.jsonl"
    ledger = VersionLedger(root, ledger_path=ledger_path)
    ledger.append(
        VersionEntry(
            seq=1,
            version="2.0.0",
            build=0,
            head_sha="",
            head_subject="baseline",
            kind="baseline",
            summary="baseline",
            changelog_digest="",
            recorded_at="2026-11-01T00:00:00+00:00",
            anchor="baseline",
        )
    )
    return ledger_path


def _context(main_root: Path, tmp_path: Path) -> closeout.CloseoutContext:
    return closeout.CloseoutContext(
        main_root=main_root,
        task_root=tmp_path / "task",
        branch="codex/test-task",
    )


def test_consistency_warnings_only(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "VERSION").write_text("2.0.0\n", encoding="utf-8")
    (root / "web").mkdir()
    (root / "web" / "package.json").write_text(
        json.dumps({"version": "2.0.1"}), encoding="utf-8"
    )
    warnings = closeout.check_version_projection_consistency(root, ledger_path=tmp_path / "absent.jsonl")
    assert any("version_projection_mismatch" in line for line in warnings)
    # The ledger file is unreadable: no ledger comparison, no crash.
    assert not any("behind_ledger" in line for line in warnings)


def test_consistency_ledger_compare_is_informational(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "VERSION").write_text("2.0.0\n", encoding="utf-8")
    (root / "web").mkdir()
    (root / "web" / "package.json").write_text(json.dumps({"version": "2.0.0"}), encoding="utf-8")
    (root / "web" / "package-lock.json").write_text(
        json.dumps({"version": "2.0.0", "packages": {"": {"version": "2.0.0"}}}), encoding="utf-8"
    )
    ledger_path = _seed_ledger(tmp_path, root, "info")
    from core.platform_version.ledger import VersionEntry, VersionLedger

    VersionLedger(root, ledger_path=ledger_path).append(
        VersionEntry(
            seq=2,
            version="3.0.3",
            build=54,
            head_sha="",
            head_subject="feat",
            kind="feature",
            summary="feat",
            changelog_digest="d" * 64,
            recorded_at="2026-11-02T00:00:00+00:00",
            anchor="settle",
        )
    )

    warnings = closeout.check_version_projection_consistency(root, ledger_path=ledger_path)

    # The three files agree, so there is no mismatch; the ledger lag is
    # reported as informational only and never blocks the merge.
    assert not any("version_projection_mismatch" in line for line in warnings)
    assert any("behind_ledger" in line and "3.0.3" in line for line in warnings)


def test_push_failure_preserves_merge_state(tmp_path: Path) -> None:
    root = tmp_path / "main"
    _init_main_repo(root)
    _seed_ledger(tmp_path, root, "pushfail")
    # An origin that cannot receive anything: push must fail without touching main.
    _run_git(root, "remote", "add", "origin", str(tmp_path / "not-a-repo"))
    head_before = _run_git(root, "rev-parse", "HEAD").stdout.strip()

    payload = closeout.publish_version_projection(
        _context(root, tmp_path),
        integration_claim_id="claim-test",
        push_remote=True,
        ledger_path=tmp_path / "pushfail-ledger.jsonl",
    )

    assert payload["sync"]["ok"] is True
    assert payload["sync"]["committed"] is True
    assert payload["push"]["ok"] is False
    assert payload["push"]["main"]["ok"] is False
    assert payload["ok"] is False
    assert "push_failed" in payload["errors"]
    # The merge (and the local sync commit) stay authoritative and clean.
    assert _run_git(root, "rev-parse", "HEAD").stdout.strip() == payload["sync"]["commitSha"]
    assert head_before != payload["sync"]["commitSha"]
    assert _run_git(root, "status", "--porcelain").stdout.strip() == ""
    assert _run_git(root, "log", "-1", "--format=%s").stdout.strip().startswith(
        "release: record product version"
    )


def test_no_push_skips_network_steps(tmp_path: Path) -> None:
    root = tmp_path / "main"
    _init_main_repo(root)
    _seed_ledger(tmp_path, root, "nopush")

    payload = closeout.publish_version_projection(
        _context(root, tmp_path),
        integration_claim_id="claim-test",
        push_remote=False,
        ledger_path=tmp_path / "nopush-ledger.jsonl",
    )

    assert payload["ok"] is True
    assert payload["push"] == {"ok": True, "skipped": True}
    assert payload["tag"] == {}
    assert payload["release"] == {}
    # The sync commit itself still landed locally.
    assert payload["sync"]["committed"] is True


def test_no_push_skips_boundary_tag(tmp_path: Path) -> None:
    root = tmp_path / "main"
    _init_main_repo(root)
    ledger_path = _seed_ledger(tmp_path, root, "notag")
    from core.platform_version.ledger import VersionEntry, VersionLedger

    VersionLedger(root, ledger_path=ledger_path).append(
        VersionEntry(
            seq=2,
            version="2.9.4",
            build=49,
            head_sha="",
            head_subject="feat",
            kind="feature",
            summary="feat",
            changelog_digest="d" * 64,
            recorded_at="2026-11-02T00:00:00+00:00",
            anchor="settle",
        )
    )

    payload = closeout.publish_version_projection(
        _context(root, tmp_path),
        integration_claim_id="claim-test",
        push_remote=False,
        ledger_path=tmp_path / "notag-ledger.jsonl",
    )

    assert payload["ok"] is True
    assert payload["sync"]["newVersion"] == "3.0.0"
    assert payload["sync"]["boundary"]["tag"] == "v3.0.0"
    assert _run_git(root, "rev-parse", "--verify", "--quiet", "refs/tags/v3.0.0").returncode != 0


def test_boundary_creates_tag_and_release_uses_changelog_notes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "main"
    _init_main_repo(root)
    ledger_path = _seed_ledger(tmp_path, root, "release")
    from core.platform_version.ledger import VersionEntry, VersionLedger

    VersionLedger(root, ledger_path=ledger_path).append(
        VersionEntry(
            seq=2,
            version="2.0.4",
            build=4,
            head_sha="",
            head_subject="feat",
            kind="feature",
            summary="feat",
            changelog_digest="d" * 64,
            recorded_at="2026-11-02T00:00:00+00:00",
            anchor="settle",
        )
    )
    # A real bare origin (local pushes succeed) plus a fake gh CLI: record
    # every invocation.
    origin = tmp_path / "origin.git"
    origin.mkdir()
    assert _run_git(origin, "init", "--bare").returncode == 0
    assert _run_git(root, "remote", "add", "origin", str(origin)).returncode == 0
    fake_gh = tmp_path / "gh.cmd"
    fake_gh.write_text("@echo off\nexit /b 0\n", encoding="utf-8")
    monkeypatch.setattr(closeout.shutil, "which", lambda _name: str(fake_gh))
    calls: list[list[str]] = []
    real_run_process = gate.run_process
    notes_content: dict[str, str] = {}

    def fake_run_process(argv, cwd, **_kwargs):
        calls.append([str(item) for item in argv])
        if argv and argv[0] == "gh":
            notes_file = Path(str(argv[argv.index("--notes-file") + 1]))
            notes_content["body"] = notes_file.read_text(encoding="utf-8")
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")
        return subprocess.run(
            [str(item) for item in argv],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    monkeypatch.setattr(gate, "run_process", fake_run_process)

    payload = closeout.publish_version_projection(
        _context(root, tmp_path),
        integration_claim_id="claim-test",
        push_remote=True,
        ledger_path=tmp_path / "release-ledger.jsonl",
    )

    assert payload["ok"] is True, payload
    assert payload["tag"].get("ok") is True
    assert payload["tag"]["tag"] == "v2.1.0"
    assert _run_git(root, "rev-parse", "--verify", "--quiet", "refs/tags/v2.1.0").returncode == 0
    tag_object = _run_git(root, "cat-file", "-t", "refs/tags/v2.1.0").stdout.strip()
    assert tag_object == "tag", "boundary tags must be annotated"
    assert payload["release"]["ok"] is True
    gh_argv = next(call for call in calls if call[0] == "gh")
    assert "release" in gh_argv and "create" in gh_argv
    assert "--target" in gh_argv
    assert gh_argv[gh_argv.index("--target") + 1] == payload["sync"]["commitSha"]
    assert "crosses" in notes_content["body"] or "feat: pending declared change." in notes_content["body"]
    # main and the tag were both pushed.
    pushed = [call for call in calls if call[:2] == ["git", "push"]]
    assert any("main" in call for call in pushed)
    assert any("refs/tags/v2.1.0" in call for call in pushed)


def test_closeout_maps_push_failure_to_merged_publish_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main_root = tmp_path / "main"
    task_root = tmp_path / "task"
    main_root.mkdir()
    task_root.mkdir()
    manifest = tmp_path / "manifest.json"
    monkeypatch.setattr(
        closeout, "resolve_context", lambda *_args, **_kwargs: _context(main_root, tmp_path),
    )
    monkeypatch.setattr(
        gate,
        "run_closeout",
        lambda *_args, **_kwargs: gate.GateResult(outcome="passed", exit_code=0, manifest_path=manifest),
    )
    monkeypatch.setattr(
        gate,
        "verify_manifest",
        lambda *_args, **_kwargs: gate.GateResult(outcome="passed", exit_code=0, manifest_path=manifest),
    )
    monkeypatch.setattr(closeout, "merge_ff_only", lambda *_args, **_kwargs: "a" * 40)
    monkeypatch.setattr(closeout, "release_claim", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(closeout, "cleanup_task_resources", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(closeout, "complete_agent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(closeout, "prune_coordination", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        closeout,
        "publish_version_projection",
        lambda *_args, **_kwargs: {
            "ok": False,
            "sync": {"ok": True, "newVersion": "2.0.1", "commitSha": "b" * 40, "boundary": None},
            "tag": {},
            "release": {},
            "push": {"ok": False, "main": {"ok": False, "error": "rejected non-fast-forward"}, "tags": {}},
            "errors": ["push_failed"],
        },
    )

    result = closeout.run_managed_closeout(
        task_root,
        claim_id="claim-dev",
        agent_id="agent-test",
        integration_wait_seconds=0,
        publish=True,
    )

    assert result.merged is True
    assert result.status == "merged_publish_pending"
    assert result.exit_code == closeout.MERGED_PUBLISH_PENDING_EXIT_CODE == 3
    assert result.retryable is True
    assert result.next_action == "rerun_cleanup_only_with_publish_from_main"
    assert result.push["ok"] is False
    assert result.push["main"] == {"ok": False, "error": "rejected non-fast-forward"}
    assert result.versionSync["ok"] is False
    assert result.versionSync["newVersion"] == "2.0.1"
    assert result.versionSync["errors"] == ["push_failed"]
    assert any("version_publish_pending" in line for line in result.errors)


def test_closeout_publish_success_and_no_push_keep_merged_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main_root = tmp_path / "main"
    task_root = tmp_path / "task"
    main_root.mkdir()
    task_root.mkdir()
    manifest = tmp_path / "manifest.json"
    monkeypatch.setattr(
        closeout, "resolve_context", lambda *_args, **_kwargs: _context(main_root, tmp_path),
    )
    monkeypatch.setattr(
        gate,
        "run_closeout",
        lambda *_args, **_kwargs: gate.GateResult(outcome="passed", exit_code=0, manifest_path=manifest),
    )
    monkeypatch.setattr(
        gate,
        "verify_manifest",
        lambda *_args, **_kwargs: gate.GateResult(outcome="passed", exit_code=0, manifest_path=manifest),
    )
    monkeypatch.setattr(closeout, "merge_ff_only", lambda *_args, **_kwargs: "a" * 40)
    monkeypatch.setattr(closeout, "release_claim", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(closeout, "cleanup_task_resources", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(closeout, "complete_agent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(closeout, "prune_coordination", lambda *_args, **_kwargs: None)
    attempted: list[dict] = []
    monkeypatch.setattr(
        closeout,
        "publish_version_projection",
        lambda *_args, **kwargs: attempted.append(kwargs)
        or {
            "ok": True,
            "sync": {"ok": True, "newVersion": "2.0.1", "commitSha": "b" * 40, "boundary": None},
            "tag": {},
            "release": {},
            "push": {"ok": True, "skipped": True},
            "errors": [],
        },
    )

    result = closeout.run_managed_closeout(
        task_root,
        claim_id="claim-dev",
        agent_id="agent-test",
        integration_wait_seconds=0,
        publish=True,
        push_remote=False,
    )

    assert result.status == "merged_clean"
    assert result.exit_code == 0
    assert result.versionSync["ok"] is True
    assert result.push == {"ok": True, "skipped": True}
    assert attempted and attempted[0]["push_remote"] is False

    # Without publish, the automation never runs (legacy API default).
    attempted.clear()
    legacy = closeout.run_managed_closeout(
        task_root,
        claim_id="claim-dev",
        agent_id="agent-test",
        integration_wait_seconds=0,
    )
    assert legacy.status == "merged_clean"
    assert attempted == []
    assert legacy.versionSync == {}
    assert legacy.push == {}


def test_cleanup_only_with_publish_finishes_publish_debt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main_root = tmp_path / "main"
    main_root.mkdir()
    assert _run_git(main_root, "init").returncode == 0
    _run_git(main_root, "config", "user.email", "publish@example.invalid")
    _run_git(main_root, "config", "user.name", "Publish Test")
    (main_root / "seed.txt").write_text("seed\n", encoding="utf-8")
    _run_git(main_root, "add", ".")
    _run_git(main_root, "commit", "-m", "seed")
    _run_git(main_root, "branch", "-M", "main")
    task_root = main_root / ".worktrees" / "test-task"
    task_root.mkdir(parents=True)
    monkeypatch.setattr(closeout, "cleanup_task_resources", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(closeout, "prune_coordination", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        closeout,
        "_coordination_call",
        lambda _context, *arguments, **_kwargs: (
            {"claim": {"id": "claim-int"}} if arguments and arguments[0] == "claim" else {"agents": [], "claims": []}
        ),
    )
    monkeypatch.setattr(closeout.time, "sleep", lambda _seconds: None)

    publish_calls: list[dict] = []

    def fake_publish(context, *, integration_claim_id, push_remote):
        publish_calls.append({"claim": integration_claim_id, "push_remote": push_remote})
        return {
            "ok": True,
            "sync": {"ok": True, "newVersion": "2.0.1", "commitSha": "b" * 40, "boundary": None},
            "tag": {},
            "release": {},
            "push": {"ok": True, "main": {"ok": True, "error": ""}, "tags": {}},
            "errors": [],
        }

    monkeypatch.setattr(closeout, "publish_version_projection", fake_publish)

    result = closeout.run_cleanup_only(
        task_root,
        branch="codex/test-task",
        agent_id="agent-test",
        publish=True,
        push_remote=False,
    )

    assert result.status == "merged_clean"
    assert result.exit_code == 0
    assert result.versionSync["ok"] is True
    assert publish_calls and publish_calls[0]["push_remote"] is False

    # A failing publish maps to merged_publish_pending with exit code 3.
    monkeypatch.setattr(
        closeout,
        "publish_version_projection",
        lambda *_args, **_kwargs: {
            "ok": False,
            "sync": {"ok": True, "newVersion": "2.0.1", "commitSha": "b" * 40, "boundary": None},
            "tag": {},
            "release": {},
            "push": {"ok": False, "main": {"ok": False, "error": "network down"}, "tags": {}},
            "errors": ["push_failed"],
        },
    )
    pending = closeout.run_cleanup_only(
        task_root,
        branch="codex/test-task",
        agent_id="agent-test",
        publish=True,
    )
    assert pending.status == "merged_publish_pending"
    assert pending.exit_code == 3
    assert pending.retryable is True
    assert pending.next_action == "rerun_cleanup_only_with_publish_from_main"


def test_publish_failure_does_not_break_the_closeout_contract() -> None:
    # The API default keeps legacy behavior for existing callers.
    import inspect

    signature = inspect.signature(closeout.run_managed_closeout)
    assert signature.parameters["publish"].default is False
    assert signature.parameters["push_remote"].default is True
    cli = closeout.build_parser().parse_args(["--task-worktree", "task"])
    assert cli.no_publish is False
    assert cli.no_push is False
    assert cli.publish is False


LOCKED_DIR_ERROR = "task worktree: empty directory is still locked"


def _stub_merged_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    cleanup_error: str | None,
) -> None:
    """Stub everything around merge/publish/cleanup so the publish contract
    between them can be tested in isolation."""

    main_root = tmp_path / "main"
    task_root = tmp_path / "task"
    main_root.mkdir(exist_ok=True)
    task_root.mkdir(exist_ok=True)
    manifest = tmp_path / "manifest.json"
    monkeypatch.setattr(
        closeout, "resolve_context", lambda *_args, **_kwargs: _context(main_root, tmp_path),
    )
    monkeypatch.setattr(
        gate,
        "run_closeout",
        lambda *_args, **_kwargs: gate.GateResult(outcome="passed", exit_code=0, manifest_path=manifest),
    )
    monkeypatch.setattr(
        gate,
        "verify_manifest",
        lambda *_args, **_kwargs: gate.GateResult(outcome="passed", exit_code=0, manifest_path=manifest),
    )
    monkeypatch.setattr(closeout, "merge_ff_only", lambda *_args, **_kwargs: "a" * 40)
    monkeypatch.setattr(closeout, "release_claim", lambda *_args, **_kwargs: None)
    if cleanup_error:
        def _raise_cleanup(*_args, **_kwargs):
            raise OSError(cleanup_error)

        monkeypatch.setattr(closeout, "cleanup_task_resources", _raise_cleanup)
    else:
        monkeypatch.setattr(closeout, "cleanup_task_resources", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(closeout, "complete_agent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(closeout, "prune_coordination", lambda *_args, **_kwargs: None)


def _ok_publish_payload() -> dict:
    return {
        "ok": True,
        "sync": {"ok": True, "newVersion": "2.0.1", "commitSha": "b" * 40, "boundary": None},
        "tag": {},
        "release": {},
        "push": {"ok": True, "skipped": True},
        "errors": [],
    }


def test_cleanup_failure_keeps_publish_fields_on_pending_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cleanup is the only debt here: publish already ran, so its fields must
    stay on the pending result and the recovery must stay plain cleanup-only."""

    _stub_merged_pipeline(tmp_path, monkeypatch, cleanup_error=LOCKED_DIR_ERROR)
    monkeypatch.setattr(
        closeout,
        "publish_version_projection",
        lambda *_args, **_kwargs: _ok_publish_payload(),
    )

    result = closeout.run_managed_closeout(
        tmp_path / "task",
        claim_id="claim-dev",
        agent_id="agent-test",
        integration_wait_seconds=0,
        publish=True,
        push_remote=False,
    )

    assert result.merged is True
    assert result.status == "merged_cleanup_pending"
    assert result.exit_code == 2
    assert result.errors == [LOCKED_DIR_ERROR]
    assert result.next_action == "run_cleanup_only_from_main"
    assert result.versionSync["ok"] is True
    assert result.versionSync["newVersion"] == "2.0.1"
    assert result.push == {"ok": True, "skipped": True}
    assert not any("version_publish_pending" in line for line in result.errors)


def test_cleanup_failure_with_publish_debt_names_the_publish_rerun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cleanup and publish both owe work: the next action must be the one
    rerun that finishes both instead of a plain cleanup-only recovery."""

    _stub_merged_pipeline(tmp_path, monkeypatch, cleanup_error=LOCKED_DIR_ERROR)
    monkeypatch.setattr(
        closeout,
        "publish_version_projection",
        lambda *_args, **_kwargs: {
            "ok": False,
            "sync": {"ok": True, "newVersion": "2.0.1", "commitSha": "b" * 40, "boundary": None},
            "tag": {},
            "release": {},
            "push": {"ok": False, "main": {"ok": False, "error": "network down"}, "tags": {}},
            "errors": ["push_failed"],
        },
    )

    result = closeout.run_managed_closeout(
        tmp_path / "task",
        claim_id="claim-dev",
        agent_id="agent-test",
        integration_wait_seconds=0,
        publish=True,
    )

    assert result.status == "merged_cleanup_pending"
    assert result.exit_code == 2
    assert result.versionSync["ok"] is False
    assert result.versionSync["errors"] == ["push_failed"]
    assert any("version_publish_pending" in line for line in result.errors)
    assert result.next_action == "rerun_cleanup_only_with_publish_from_main"


def test_publish_not_attempted_is_recorded_explicitly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If publish never produced a payload on a merged run, the pending result
    must say so with a skipped marker and a recoverable debt error."""

    _stub_merged_pipeline(tmp_path, monkeypatch, cleanup_error=None)

    def _raise_publish(*_args, **_kwargs):
        raise RuntimeError("publish hook exploded")

    monkeypatch.setattr(closeout, "publish_version_projection", _raise_publish)

    result = closeout.run_managed_closeout(
        tmp_path / "task",
        claim_id="claim-dev",
        agent_id="agent-test",
        integration_wait_seconds=0,
        publish=True,
    )

    assert result.merged is True
    assert result.status == "merged_cleanup_pending"
    assert result.exit_code == 2
    assert result.versionSync == {"ok": False, "skipped_reason": "publish_not_attempted"}
    assert result.push == {"ok": False, "skipped_reason": "publish_not_attempted"}
    assert any("publish hook exploded" in line for line in result.errors)
    assert "version_publish_pending: publish_not_attempted" in result.errors
    assert result.next_action == "rerun_cleanup_only_with_publish_from_main"


def test_no_publish_pending_result_stays_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pending result without the automation requested must still name the
    skip instead of returning silent empty fields."""

    _stub_merged_pipeline(tmp_path, monkeypatch, cleanup_error=LOCKED_DIR_ERROR)

    result = closeout.run_managed_closeout(
        tmp_path / "task",
        claim_id="claim-dev",
        agent_id="agent-test",
        integration_wait_seconds=0,
    )

    assert result.status == "merged_cleanup_pending"
    assert result.versionSync == {"ok": False, "skipped_reason": "publish_not_requested"}
    assert result.push == {"ok": False, "skipped_reason": "publish_not_requested"}
    assert result.errors == [LOCKED_DIR_ERROR]
    assert result.next_action == "run_cleanup_only_from_main"


def test_cleanup_only_failure_keeps_publish_debt_explicit_and_recoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The documented recovery rerun must keep the publish debt visible when
    cleanup itself fails, and finish it once cleanup succeeds."""

    main_root = tmp_path / "main"
    main_root.mkdir()
    assert _run_git(main_root, "init").returncode == 0
    _run_git(main_root, "config", "user.email", "publish@example.invalid")
    _run_git(main_root, "config", "user.name", "Publish Test")
    (main_root / "seed.txt").write_text("seed\n", encoding="utf-8")
    _run_git(main_root, "add", ".")
    _run_git(main_root, "commit", "-m", "seed")
    _run_git(main_root, "branch", "-M", "main")
    task_root = main_root / ".worktrees" / "test-task"
    task_root.mkdir(parents=True)
    monkeypatch.setattr(closeout, "prune_coordination", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(closeout.time, "sleep", lambda _seconds: None)

    attempts: list[str] = []

    def _flaky_cleanup(*_args, **_kwargs):
        attempts.append("cleanup")
        if len(attempts) == 1:
            raise OSError(LOCKED_DIR_ERROR)

    monkeypatch.setattr(closeout, "cleanup_task_resources", _flaky_cleanup)

    # First cleanup-only --publish attempt: cleanup fails before publish runs,
    # so the pending result must name the skipped publish and the rerun.
    first = closeout.run_cleanup_only(
        task_root,
        branch="codex/test-task",
        agent_id="agent-test",
        publish=True,
        push_remote=False,
    )
    assert first.status == "merged_cleanup_pending"
    assert first.exit_code == 2
    assert first.versionSync == {"ok": False, "skipped_reason": "publish_not_attempted"}
    assert first.push == {"ok": False, "skipped_reason": "publish_not_attempted"}
    assert first.next_action == "rerun_cleanup_only_with_publish_from_main"

    # Recovery rerun finishes cleanup and publish together.
    publish_calls: list[dict] = []

    def _fake_publish(context, *, integration_claim_id, push_remote):
        publish_calls.append({"claim": integration_claim_id, "push_remote": push_remote})
        return _ok_publish_payload() | {"push": {"ok": True, "main": {"ok": True, "error": ""}, "tags": {}}}

    monkeypatch.setattr(closeout, "publish_version_projection", _fake_publish)
    monkeypatch.setattr(
        closeout,
        "_coordination_call",
        lambda _context, *arguments, **_kwargs: (
            {"claim": {"id": "claim-int"}} if arguments and arguments[0] == "claim" else {"agents": [], "claims": []}
        ),
    )

    recovered = closeout.run_cleanup_only(
        task_root,
        branch="codex/test-task",
        agent_id="agent-test",
        publish=True,
        push_remote=False,
    )
    assert recovered.status == "merged_clean"
    assert recovered.exit_code == 0
    assert recovered.versionSync["ok"] is True
    assert publish_calls and publish_calls[0]["push_remote"] is False

    # A plain cleanup-only failure (no --publish) records that publish was
    # never requested instead of returning silent empty fields.
    attempts.clear()

    def _raise_cleanup_only(*_args, **_kwargs):
        raise OSError(LOCKED_DIR_ERROR)

    monkeypatch.setattr(closeout, "cleanup_task_resources", _raise_cleanup_only)
    plain = closeout.run_cleanup_only(
        task_root,
        branch="codex/test-task",
        agent_id="agent-test",
    )
    assert plain.status == "merged_cleanup_pending"
    assert plain.versionSync == {"ok": False, "skipped_reason": "publish_not_requested"}
    assert plain.next_action == "rerun_cleanup_only_from_main"
