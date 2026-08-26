from __future__ import annotations

from pathlib import Path

import pytest

from scripts import local_quality_gate as gate
from scripts import task_closeout as closeout

ORIGINAL_VALIDATE_DEVELOPMENT_CLAIM = closeout.validate_development_claim


@pytest.fixture(autouse=True)
def valid_development_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(closeout, "validate_development_claim", lambda *_args, **_kwargs: None)


def context(tmp_path: Path) -> closeout.CloseoutContext:
    return closeout.CloseoutContext(
        main_root=tmp_path / "main",
        task_root=tmp_path / "task",
        branch="codex/test-task",
    )


def test_integration_claim_conflict_preserves_prevalidated_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    manifest = tmp_path / "manifest.json"
    monkeypatch.setattr(closeout, "resolve_context", lambda *_args, **_kwargs: context(tmp_path))

    def conflict(*_args, **_kwargs):
        events.append("acquire")
        raise closeout.ManagedCloseoutError("integration_claim_conflict")

    monkeypatch.setattr(closeout, "acquire_integration_claim", conflict)
    monkeypatch.setattr(
        gate,
        "run_closeout",
        lambda *_args, **_kwargs: events.append("closeout")
        or gate.GateResult(outcome="passed", exit_code=0, manifest_path=manifest),
    )
    monkeypatch.setattr(
        gate,
        "verify_manifest",
        lambda *_args, **_kwargs: events.append("verify")
        or gate.GateResult(outcome="passed", exit_code=0, manifest_path=manifest),
    )

    result = closeout.run_managed_closeout(
        tmp_path / "task",
        claim_id="claim-dev",
        agent_id="agent-test",
        integration_wait_seconds=0,
    )

    assert result.status == "integration_claim_conflict"
    assert result.exit_code == 1
    assert result.merged is False
    assert result.manifest_path == str(manifest)
    assert result.retryable is True
    assert result.next_action == "retry_with_manifest"
    assert events == ["closeout", "verify", "acquire"]


def test_integration_claim_wait_reuses_manifest_without_rerunning_closeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    attempts = 0
    manifest = tmp_path / "manifest.json"
    monkeypatch.setattr(closeout, "resolve_context", lambda *_args, **_kwargs: context(tmp_path))
    monkeypatch.setattr(
        gate,
        "run_closeout",
        lambda *_args, **_kwargs: events.append("closeout")
        or gate.GateResult(outcome="passed", exit_code=0, manifest_path=manifest),
    )
    monkeypatch.setattr(
        gate,
        "verify_manifest",
        lambda *_args, **_kwargs: events.append("verify")
        or gate.GateResult(outcome="passed", exit_code=0, manifest_path=manifest),
    )

    def acquire(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        events.append(f"acquire:{attempts}")
        if attempts < 3:
            raise closeout.ManagedCloseoutError("integration_claim_conflict")
        return "claim-int"

    monkeypatch.setattr(closeout, "acquire_integration_claim", acquire)
    monkeypatch.setattr(closeout.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(closeout, "merge_ff_only", lambda *_args, **_kwargs: "head-sha")
    monkeypatch.setattr(closeout, "release_claim", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(closeout, "cleanup_task_resources", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(closeout, "complete_agent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(closeout, "prune_coordination", lambda *_args, **_kwargs: None)

    result = closeout.run_managed_closeout(
        tmp_path / "task",
        claim_id="claim-dev",
        agent_id="agent-test",
        integration_wait_seconds=1,
    )

    assert result.status == "merged_clean"
    assert events.count("closeout") == 1
    assert attempts == 3


def test_reserved_integration_claim_uses_bounded_validation_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []

    def coordination(_context, *arguments):
        captured.extend(arguments)
        return {"claim": {"id": "claim-int"}}

    monkeypatch.setattr(closeout, "_coordination_call", coordination)

    claim_id = closeout.acquire_integration_claim(
        context(tmp_path),
        agent_id="agent-test",
        reserve_validation=True,
    )

    assert claim_id == "claim-int"
    assert captured[captured.index("--ttl-minutes") + 1] == "15"
    assert "starvation fallback" in captured[captured.index("--note") + 1]


@pytest.mark.parametrize("failure", ["unsafe_worktree_path", "dirty_main", "dirty_worktree"])
def test_invalid_context_skips_claim_and_quality_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    def reject(*_args, **_kwargs):
        raise closeout.ManagedCloseoutError(failure)

    monkeypatch.setattr(closeout, "resolve_context", reject)
    monkeypatch.setattr(
        closeout,
        "acquire_integration_claim",
        lambda *_args, **_kwargs: pytest.fail("invalid context must not acquire a claim"),
    )
    monkeypatch.setattr(
        gate,
        "run_closeout",
        lambda *_args, **_kwargs: pytest.fail("invalid context must not run the quality gate"),
    )

    result = closeout.run_managed_closeout(
        tmp_path / "task",
        claim_id="claim-dev",
        agent_id="agent-test",
    )

    assert result.status == "failed"
    assert result.exit_code == 1
    assert result.errors == [failure]


def test_development_claim_must_belong_to_requested_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        closeout,
        "_coordination_call",
        lambda *_args, **_kwargs: {
            "claims": [
                {
                    "id": "claim-dev",
                    "agentId": "agent-other",
                    "status": "active",
                }
            ]
        },
    )

    with pytest.raises(closeout.ManagedCloseoutError) as caught:
        ORIGINAL_VALIDATE_DEVELOPMENT_CLAIM(
            context(tmp_path),
            claim_id="claim-dev",
            agent_id="agent-test",
        )

    assert caught.value.code == "invalid_claim_owner"


def test_cleanup_rejects_another_active_agent_owning_task_resources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        closeout,
        "_coordination_call",
        lambda *_args, **_kwargs: {
            "agents": [
                {
                    "id": "agent-other",
                    "state": "active",
                    "branch": "codex/test-task",
                    "worktree": "",
                }
            ]
        },
    )

    with pytest.raises(closeout.ManagedCloseoutError) as caught:
        closeout.ensure_cleanup_unowned(context(tmp_path), agent_id="agent-test")

    assert caught.value.code == "task_resources_still_owned"


def test_agent_completion_rejects_other_live_claims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def coordination(_context, *arguments: str):
        calls.append(arguments)
        return {
            "claims": [
                {
                    "id": "claim-other",
                    "agentId": "agent-test",
                    "status": "active",
                }
            ]
        }

    monkeypatch.setattr(closeout, "_coordination_call", coordination)

    with pytest.raises(closeout.ManagedCloseoutError) as caught:
        closeout.complete_agent(context(tmp_path), agent_id="agent-test", merge_sha="head-sha")

    assert caught.value.code == "agent_has_other_active_claims"
    assert calls == [("status",)]


def test_resolve_context_rejects_worktree_outside_managed_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_root = tmp_path / "main"
    task_root = tmp_path / "elsewhere" / "task"
    monkeypatch.setattr(gate, "repository_root", lambda _path: task_root)
    monkeypatch.setattr(
        gate,
        "current_branch",
        lambda root: "main" if Path(root) == main_root else "codex/test-task",
    )
    monkeypatch.setattr(gate, "main_worktree", lambda *_args: main_root)
    monkeypatch.setattr(gate, "git_lines", lambda *_args: [])

    with pytest.raises(closeout.ManagedCloseoutError, match="managed cleanup requires") as caught:
        closeout.resolve_context(task_root)

    assert caught.value.code == "unsafe_worktree_path"


def test_failed_quality_gate_never_acquires_integration_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    monkeypatch.setattr(closeout, "resolve_context", lambda *_args, **_kwargs: context(tmp_path))
    monkeypatch.setattr(
        closeout,
        "acquire_integration_claim",
        lambda *_args, **_kwargs: pytest.fail("failed validation must not acquire integration claim"),
    )
    monkeypatch.setattr(
        gate,
        "run_closeout",
        lambda *_args, **_kwargs: gate.GateResult(outcome="failed", exit_code=1),
    )
    monkeypatch.setattr(
        closeout,
        "release_claim",
        lambda _ctx, claim_id, *, status, reason: events.append(f"{claim_id}:{status}"),
    )
    monkeypatch.setattr(
        closeout,
        "merge_ff_only",
        lambda *_args, **_kwargs: pytest.fail("failed validation must not merge"),
    )

    result = closeout.run_managed_closeout(
        tmp_path / "task",
        claim_id="claim-dev",
        agent_id="agent-test",
    )

    assert result.status == "validation_failed"
    assert result.merged is False
    assert events == []


def test_reserved_retry_acquires_before_validation_and_releases_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    monkeypatch.setattr(closeout, "resolve_context", lambda *_args, **_kwargs: context(tmp_path))
    monkeypatch.setattr(
        closeout,
        "validate_stale_retry_token",
        lambda *_args, **_kwargs: tmp_path / "retry-token.json",
    )
    monkeypatch.setattr(closeout, "consume_stale_retry_token", lambda *_args, **_kwargs: None)

    def acquire(*_args, **kwargs):
        assert kwargs["reserve_validation"] is True
        events.append("acquire")
        return "claim-int"

    monkeypatch.setattr(closeout, "acquire_integration_claim", acquire)
    monkeypatch.setattr(
        gate,
        "run_closeout",
        lambda *_args, **_kwargs: events.append("closeout")
        or gate.GateResult(outcome="failed", exit_code=1),
    )
    monkeypatch.setattr(
        closeout,
        "release_claim",
        lambda _ctx, claim_id, *, status, reason: events.append(f"release:{claim_id}:{status}"),
    )
    monkeypatch.setattr(
        closeout,
        "merge_ff_only",
        lambda *_args, **_kwargs: pytest.fail("failed reserved validation must not merge"),
    )

    result = closeout.run_managed_closeout(
        tmp_path / "task",
        claim_id="claim-dev",
        agent_id="agent-test",
        reserve_integration=True,
        stale_retry_token=tmp_path / "retry-token.json",
    )

    assert result.status == "validation_failed"
    assert result.merged is False
    assert events == ["acquire", "closeout", "release:claim-int:released"]


def test_integration_release_failure_is_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(closeout, "resolve_context", lambda *_args, **_kwargs: context(tmp_path))
    monkeypatch.setattr(closeout, "acquire_integration_claim", lambda *_args, **_kwargs: "claim-int")
    manifest = tmp_path / "manifest.json"
    monkeypatch.setattr(
        gate,
        "run_closeout",
        lambda *_args, **_kwargs: gate.GateResult(
            outcome="passed", exit_code=0, manifest_path=manifest
        ),
    )
    verify_calls = 0

    def verify(*_args, **_kwargs):
        nonlocal verify_calls
        verify_calls += 1
        return gate.GateResult(
            outcome="passed" if verify_calls == 1 else "stale_main",
            exit_code=0 if verify_calls == 1 else 1,
            manifest_path=manifest,
        )

    monkeypatch.setattr(gate, "verify_manifest", verify)
    monkeypatch.setattr(
        closeout,
        "release_claim",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("registry locked")),
    )

    result = closeout.run_managed_closeout(
        tmp_path / "task",
        claim_id="claim-dev",
        agent_id="agent-test",
    )

    assert result.status == "failed"
    assert result.errors == ["stale_main", "integration_release_pending: registry locked"]


def test_successful_closeout_merges_then_releases_and_cleans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    manifest = tmp_path / "manifest.json"
    monkeypatch.setattr(closeout, "resolve_context", lambda *_args, **_kwargs: context(tmp_path))
    monkeypatch.setattr(
        closeout,
        "acquire_integration_claim",
        lambda *_args, **_kwargs: events.append("acquire") or "claim-int",
    )
    monkeypatch.setattr(
        gate,
        "run_closeout",
        lambda *_args, **_kwargs: events.append("closeout")
        or gate.GateResult(outcome="passed", exit_code=0, manifest_path=manifest),
    )
    monkeypatch.setattr(
        gate,
        "verify_manifest",
        lambda *_args, **_kwargs: events.append("verify")
        or gate.GateResult(outcome="passed", exit_code=0, manifest_path=manifest),
    )
    monkeypatch.setattr(
        closeout,
        "merge_ff_only",
        lambda *_args, **_kwargs: events.append("merge") or "head-sha",
    )
    monkeypatch.setattr(
        closeout,
        "release_claim",
        lambda _ctx, claim_id, *, status, reason: events.append(f"release:{claim_id}:{status}"),
    )
    monkeypatch.setattr(
        closeout,
        "cleanup_task_resources",
        lambda *_args, **_kwargs: events.append("cleanup"),
    )
    monkeypatch.setattr(
        closeout,
        "complete_agent",
        lambda *_args, **_kwargs: events.append("complete"),
    )
    monkeypatch.setattr(
        closeout,
        "prune_coordination",
        lambda *_args, **_kwargs: events.append("prune"),
    )

    result = closeout.run_managed_closeout(
        tmp_path / "task",
        claim_id="claim-dev",
        agent_id="agent-test",
    )

    assert result.status == "merged_clean"
    assert result.exit_code == 0
    assert result.merged is True
    assert result.merge_sha == "head-sha"
    assert events == [
        "closeout",
        "verify",
        "acquire",
        "verify",
        "merge",
        "release:claim-dev:completed",
        "release:claim-int:completed",
        "cleanup",
        "complete",
        "prune",
    ]


def test_cleanup_failure_preserves_merged_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = tmp_path / "manifest.json"
    monkeypatch.setattr(closeout, "resolve_context", lambda *_args, **_kwargs: context(tmp_path))
    monkeypatch.setattr(closeout, "acquire_integration_claim", lambda *_args, **_kwargs: "claim-int")
    monkeypatch.setattr(
        gate,
        "run_closeout",
        lambda *_args, **_kwargs: gate.GateResult(
            outcome="passed", exit_code=0, manifest_path=manifest
        ),
    )
    monkeypatch.setattr(
        gate,
        "verify_manifest",
        lambda *_args, **_kwargs: gate.GateResult(
            outcome="passed", exit_code=0, manifest_path=manifest
        ),
    )
    monkeypatch.setattr(closeout, "merge_ff_only", lambda *_args, **_kwargs: "head-sha")
    monkeypatch.setattr(closeout, "release_claim", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        closeout,
        "cleanup_task_resources",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("worktree busy")),
    )
    completed: list[str] = []
    monkeypatch.setattr(
        closeout,
        "complete_agent",
        lambda *_args, **_kwargs: completed.append("complete"),
    )
    monkeypatch.setattr(closeout, "prune_coordination", lambda *_args, **_kwargs: None)

    result = closeout.run_managed_closeout(
        tmp_path / "task",
        claim_id="claim-dev",
        agent_id="agent-test",
    )

    assert result.status == "merged_cleanup_pending"
    assert result.exit_code == 2
    assert result.merged is True
    assert result.merge_sha == "head-sha"
    assert result.errors == ["worktree busy"]
    assert completed == ["complete"]
    assert result.retryable is True
    assert result.next_action == "run_cleanup_only_from_main"


def test_existing_manifest_skips_expensive_closeout_but_is_verified_inside_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    manifest = tmp_path / "manifest.json"
    monkeypatch.setattr(closeout, "resolve_context", lambda *_args, **_kwargs: context(tmp_path))
    monkeypatch.setattr(
        gate,
        "run_closeout",
        lambda *_args, **_kwargs: pytest.fail("provided manifest must skip expensive closeout"),
    )
    monkeypatch.setattr(
        gate,
        "verify_manifest",
        lambda *_args, **_kwargs: events.append("verify")
        or gate.GateResult(outcome="passed", exit_code=0, manifest_path=manifest),
    )
    monkeypatch.setattr(
        closeout,
        "acquire_integration_claim",
        lambda *_args, **_kwargs: events.append("acquire") or "claim-int",
    )
    monkeypatch.setattr(
        closeout,
        "merge_ff_only",
        lambda *_args, **_kwargs: events.append("merge") or "head-sha",
    )
    monkeypatch.setattr(closeout, "release_claim", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(closeout, "cleanup_task_resources", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(closeout, "complete_agent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(closeout, "prune_coordination", lambda *_args, **_kwargs: None)

    result = closeout.run_managed_closeout(
        tmp_path / "task",
        claim_id="claim-dev",
        agent_id="agent-test",
        manifest_path=manifest,
    )

    assert result.status == "merged_clean"
    assert result.manifest_path == str(manifest)
    assert events == ["verify", "acquire", "verify", "merge"]


def test_stale_retry_token_is_bound_and_consumed_once(
    tmp_path: Path,
) -> None:
    ctx = context(tmp_path)
    ctx.main_root.mkdir()
    ctx.task_root.mkdir()
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")

    token = closeout.issue_stale_retry_token(manifest, ctx, agent_id="agent-test")

    assert closeout.validate_stale_retry_token(token, ctx, agent_id="agent-test") == token
    closeout.consume_stale_retry_token(token)
    with pytest.raises(closeout.ManagedCloseoutError) as caught:
        closeout.validate_stale_retry_token(token, ctx, agent_id="agent-test")
    assert caught.value.code == "invalid_stale_retry_token"


def test_cleanup_moves_own_cwd_and_retries_transient_worktree_remove(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_root = tmp_path / "main"
    task_root = main_root / ".worktrees" / "test-task"
    ctx = closeout.CloseoutContext(
        main_root=main_root,
        task_root=task_root,
        branch="codex/test-task",
    )
    ctx.main_root.mkdir()
    ctx.task_root.mkdir(parents=True)
    events: list[str] = []
    remove_attempts = 0
    monkeypatch.setattr(closeout, "ensure_cleanup_unowned", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gate, "git_lines", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(gate, "rev_parse", lambda root, *_args: "head-sha")
    monkeypatch.setattr(gate, "is_ancestor", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(closeout, "_branch_exists", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(closeout, "_remove_link_or_junction", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(closeout, "invocation_cwd_is_inside_task", lambda *_args: True)
    monkeypatch.setattr(closeout.os, "chdir", lambda path: events.append(f"chdir:{path}"))
    monkeypatch.setattr(closeout.time, "sleep", lambda _seconds: None)

    def process(argv, _cwd):
        nonlocal remove_attempts
        if argv[:3] == ["git", "worktree", "remove"]:
            remove_attempts += 1
            if remove_attempts == 1:
                return closeout.subprocess.CompletedProcess(
                    argv,
                    1,
                    stdout="",
                    stderr="Access is denied",
                )
        events.append(" ".join(argv))
        return closeout.subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(gate, "run_process", process)

    closeout.cleanup_task_resources(ctx, agent_id="agent-test")

    assert events[0] == f"chdir:{ctx.main_root}"
    assert remove_attempts == 2


def test_cleanup_only_never_validates_or_merges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        closeout,
        "resolve_cleanup_context",
        lambda *_args, **_kwargs: context(tmp_path),
    )
    monkeypatch.setattr(closeout, "cleanup_task_resources", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(closeout, "prune_coordination", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        gate,
        "run_closeout",
        lambda *_args, **_kwargs: pytest.fail("cleanup-only must not validate"),
    )
    monkeypatch.setattr(
        closeout,
        "merge_ff_only",
        lambda *_args, **_kwargs: pytest.fail("cleanup-only must not merge"),
    )

    result = closeout.run_cleanup_only(
        tmp_path / "task",
        branch="codex/test-task",
        agent_id="agent-test",
    )

    assert result.status == "merged_clean"
    assert result.exit_code == 0


def test_cli_refuses_managed_closeout_from_task_worktree_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(closeout, "invocation_cwd_is_inside_task", lambda *_args: True)
    monkeypatch.setattr(
        closeout,
        "run_managed_closeout",
        lambda *_args, **_kwargs: pytest.fail("must fail before managed closeout"),
    )

    exit_code = closeout.main(
        [
            "--task-worktree",
            str(tmp_path / "task"),
            "--claim-id",
            "claim-test",
            "--agent-id",
            "agent-test",
        ]
    )
    payload = closeout.json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["next_action"] == "rerun_from_main"
