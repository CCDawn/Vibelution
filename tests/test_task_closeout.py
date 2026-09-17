from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from scripts import local_quality_gate as gate
from scripts import task_closeout as closeout

ORIGINAL_VALIDATE_DEVELOPMENT_CLAIM = closeout.validate_development_claim
ORIGINAL_DISCOVER_MANIFEST = closeout.discover_manifest


@pytest.fixture(autouse=True)
def valid_development_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(closeout, "validate_development_claim", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(closeout, "discover_manifest", lambda _context: None)


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


def test_implicit_manifest_reuses_valid_cache_without_rerunning_closeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    manifest = tmp_path / "cached-manifest.json"
    monkeypatch.setattr(closeout, "resolve_context", lambda *_args, **_kwargs: context(tmp_path))
    monkeypatch.setattr(
        closeout,
        "discover_manifest",
        lambda _context: manifest,
        raising=False,
    )
    monkeypatch.setattr(
        gate,
        "run_closeout",
        lambda *_args, **_kwargs: pytest.fail(
            "valid implicit manifest must skip expensive closeout"
        ),
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
    )

    assert result.status == "merged_clean"
    assert result.manifest_path == str(manifest)
    assert events == ["verify", "acquire", "verify", "merge"]


def test_discover_manifest_uses_deterministic_quality_gate_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = tmp_path / "cache" / "quality_gates" / "test-task.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        gate,
        "quality_gate_manifest_path",
        lambda _root, _task_id: manifest,
    )

    assert ORIGINAL_DISCOVER_MANIFEST(context(tmp_path)) == manifest


def test_invalid_implicit_manifest_falls_back_to_fresh_closeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    cached_manifest = tmp_path / "cached-manifest.json"
    fresh_manifest = tmp_path / "fresh-manifest.json"
    monkeypatch.setattr(closeout, "resolve_context", lambda *_args, **_kwargs: context(tmp_path))
    monkeypatch.setattr(
        closeout,
        "discover_manifest",
        lambda _context: cached_manifest,
        raising=False,
    )
    monkeypatch.setattr(
        gate,
        "run_closeout",
        lambda *_args, **_kwargs: events.append("closeout")
        or gate.GateResult(
            outcome="passed",
            exit_code=0,
            manifest_path=fresh_manifest,
        ),
    )

    def verify(path: Path, *_args, **_kwargs) -> gate.GateResult:
        events.append(f"verify:{path.name}")
        if path == cached_manifest:
            return gate.GateResult(
                outcome="failed",
                exit_code=1,
                manifest_path=path,
            )
        return gate.GateResult(
            outcome="passed",
            exit_code=0,
            manifest_path=path,
        )

    monkeypatch.setattr(gate, "verify_manifest", verify)
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
    )

    assert result.status == "merged_clean"
    assert result.manifest_path == str(fresh_manifest)
    assert events == [
        "verify:cached-manifest.json",
        "closeout",
        "verify:fresh-manifest.json",
        "acquire",
        "verify:fresh-manifest.json",
        "merge",
    ]


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
        if argv[:3] == ["git", "worktree", "list"]:
            # The directory is still a registered worktree at this point.
            return closeout.subprocess.CompletedProcess(
                argv,
                0,
                stdout=f"worktree {ctx.main_root}\nworktree {ctx.task_root}\n",
                stderr="",
            )
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


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )


def _init_main_repo(root: Path) -> None:
    """A main repo whose ``codex/test-task`` branch is already merged."""

    root.mkdir(parents=True, exist_ok=True)
    _run_git(root, "init")
    _run_git(root, "config", "user.email", "closeout@example.invalid")
    _run_git(root, "config", "user.name", "Closeout Test")
    (root / ".gitignore").write_text(".worktrees/\n", encoding="utf-8")
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    _run_git(root, "add", ".gitignore", "seed.txt")
    _run_git(root, "commit", "-m", "seed")
    _run_git(root, "branch", "-M", "main")
    _run_git(root, "branch", "codex/test-task")


def _leftover_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> closeout.CloseoutContext:
    """A task directory that Git no longer tracks, as left by a partial removal."""

    main_root = tmp_path / "main"
    _init_main_repo(main_root)
    task_root = main_root / ".worktrees" / "test-task"
    task_root.mkdir(parents=True)
    monkeypatch.setattr(closeout, "_coordination_call", lambda *_args, **_kwargs: {"agents": []})
    monkeypatch.setattr(closeout.time, "sleep", lambda _seconds: None)
    return closeout.CloseoutContext(
        main_root=main_root,
        task_root=task_root,
        branch="codex/test-task",
    )


def test_cleanup_finishes_when_removal_only_left_the_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A half-completed worktree removal is residue, not a failure to report.

    ``git worktree remove`` unregisters the worktree and deletes its contents
    before failing to delete the directory itself, so retrying it reports "is
    not a working tree". That used to surface as pending cleanup the operator
    could not complete, and the documented ``--cleanup-only`` recovery then
    refused the same directory as an unsafe path.
    """

    context = _leftover_context(tmp_path, monkeypatch)

    closeout.cleanup_task_resources(context, agent_id="agent-test")

    assert not context.task_root.exists()
    assert _run_git(context.main_root, "show-ref", "--verify", "--quiet", "refs/heads/codex/test-task").returncode != 0


def test_cleanup_keeps_residue_whose_content_it_cannot_judge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only an empty leftover directory is removed; anything else is reported."""

    context = _leftover_context(tmp_path, monkeypatch)
    notes = context.task_root / "notes.txt"
    notes.write_text("uncommitted work\n", encoding="utf-8")

    with pytest.raises(closeout.ManagedCloseoutError) as raised:
        closeout.cleanup_task_resources(context, agent_id="agent-test")

    assert raised.value.code == "cleanup_residue_present"
    assert notes.read_text(encoding="utf-8") == "uncommitted work\n"


def test_cleanup_only_recovers_a_leftover_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The documented recovery path must complete instead of refusing the path."""

    context = _leftover_context(tmp_path, monkeypatch)

    result = closeout.run_cleanup_only(
        context.task_root,
        branch="codex/test-task",
        agent_id="agent-test",
    )

    assert result.status == "merged_clean"
    assert result.exit_code == 0
    assert not context.task_root.exists()


@pytest.mark.parametrize(
    ("outcome", "expected_action"),
    [
        ("reuse_research_missing", "record_reuse_research_evidence"),
        ("reuse_research_invalid", "fix_reuse_research_evidence"),
    ],
)
def test_reuse_research_failure_names_its_recovery_step(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
    expected_action: str,
) -> None:
    """The record is a gate precondition, so the result must name how to satisfy it.

    This check runs before the expensive commands, so recovery is one specific
    step and then re-running the same closeout -- no rebase, no token. Leaving
    next_action empty made the operator rediscover that from the docs.
    """

    monkeypatch.setattr(closeout, "resolve_context", lambda *_args, **_kwargs: context(tmp_path))
    monkeypatch.setattr(
        gate,
        "run_closeout",
        lambda *_args, **_kwargs: gate.GateResult(outcome=outcome, exit_code=1),
    )
    monkeypatch.setattr(
        closeout,
        "merge_ff_only",
        lambda *_args, **_kwargs: pytest.fail("a failed validation must not merge"),
    )

    result = closeout.run_managed_closeout(
        tmp_path / "task",
        claim_id="claim-dev",
        agent_id="agent-test",
        integration_wait_seconds=0,
    )

    assert result.status == "validation_failed"
    assert result.merged is False
    assert result.retryable is True
    assert result.retry_token_path == ""
    assert result.next_action == expected_action


@pytest.mark.parametrize(
    ("outcome", "expected_action"),
    [
        (
            "validation_node_modules_source_missing",
            "install_node_modules_in_main_checkout",
        ),
        (
            "validation_node_modules_link_failed",
            "create_node_modules_link_manually",
        ),
    ],
)
def test_node_modules_preflight_failure_names_its_recovery_step(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
    expected_action: str,
) -> None:
    """A failed link preflight is one mechanical fix, then re-run closeout.

    The outcome code alone cannot say *which* tree is missing or why creation
    failed, so the gate's bounded detail must survive into ``errors`` next to
    the code instead of replacing it.
    """

    detail = "web/node_modules: no node_modules to link"
    monkeypatch.setattr(closeout, "resolve_context", lambda *_args, **_kwargs: context(tmp_path))
    monkeypatch.setattr(
        gate,
        "run_closeout",
        lambda *_args, **_kwargs: gate.GateResult(
            outcome=outcome,
            exit_code=1,
            detail=detail,
        ),
    )
    monkeypatch.setattr(
        closeout,
        "merge_ff_only",
        lambda *_args, **_kwargs: pytest.fail("a failed validation must not merge"),
    )

    result = closeout.run_managed_closeout(
        tmp_path / "task",
        claim_id="claim-dev",
        agent_id="agent-test",
        integration_wait_seconds=0,
    )

    assert result.status == "validation_failed"
    assert result.merged is False
    assert result.retryable is True
    assert result.retry_token_path == ""
    assert result.next_action == expected_action
    assert result.errors[0] == outcome
    assert detail in result.errors


def test_task_owned_ephemeral_paths_cover_every_linked_node_modules() -> None:
    """The preflight creates exactly the links this cleanup tuple unlinks.

    A node_modules link that cleanup does not know about would make the final
    worktree removal descend into the shared main checkout's real install.
    """

    assert set(closeout.TASK_OWNED_EPHEMERAL_PATHS) == {
        Path(".venv"),
        Path("node_modules"),
        Path("web") / "node_modules",
        Path("desktop") / "electron" / "node_modules",
        Path("挑战杯"),
    }


@pytest.mark.skipif(os.name != "nt", reason="Windows junction lifecycle")
def test_cleanup_unlinks_every_task_owned_ephemeral_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_root = tmp_path / "main"
    task_root = main_root / ".worktrees" / "test-task"
    task_root.mkdir(parents=True)
    ctx = closeout.CloseoutContext(
        main_root=main_root,
        task_root=task_root,
        branch="codex/test-task",
    )
    link_source = tmp_path / "shared-install"
    link_source.mkdir()
    for relative in closeout.TASK_OWNED_EPHEMERAL_PATHS:
        link = task_root / relative
        link.parent.mkdir(parents=True, exist_ok=True)
        gate.create_directory_link(link_source, link)
    monkeypatch.setattr(closeout, "ensure_cleanup_unowned", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gate, "git_lines", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(gate, "rev_parse", lambda root, *_args: "head-sha")
    monkeypatch.setattr(gate, "is_ancestor", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(closeout, "_branch_exists", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(closeout, "invocation_cwd_is_inside_task", lambda *_args: False)
    monkeypatch.setattr(closeout, "_remove_leftover_worktree_dir", lambda *_args: None)
    removed: list[list[bool]] = []

    def fake_remove_worktree(context):
        removed.append(
            [
                not (context.task_root / relative).exists()
                for relative in closeout.TASK_OWNED_EPHEMERAL_PATHS
            ]
        )
        return subprocess.CompletedProcess(["git", "worktree", "remove"], 0)

    monkeypatch.setattr(closeout, "_remove_worktree_with_retry", fake_remove_worktree)

    def process(argv, _cwd):
        if argv[:3] == ["git", "worktree", "list"]:
            # The directory is still a registered worktree, so cleanup takes
            # the unlink-first path instead of treating it as residue.
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=f"worktree {ctx.main_root}\nworktree {ctx.task_root}\n",
                stderr="",
            )
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(gate, "run_process", process)

    closeout.cleanup_task_resources(ctx, agent_id="agent-test")

    assert removed == [[True] * len(closeout.TASK_OWNED_EPHEMERAL_PATHS)]
    for relative in closeout.TASK_OWNED_EPHEMERAL_PATHS:
        assert not (task_root / relative).exists()


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def dirty_main_repo(tmp_path: Path, *, dirty: bool = True) -> Path:
    """A minimal main checkout with one uncommitted ``stray.txt`` edit."""

    main_root = tmp_path / "main"
    main_root.mkdir()
    _git(main_root, "init", "-q")
    _git(main_root, "config", "user.email", "closeout@example.invalid")
    _git(main_root, "config", "user.name", "Closeout Test")
    _git(main_root, "config", "core.autocrlf", "false")
    (main_root / ".gitignore").write_text(".worktrees/\n", encoding="utf-8")
    (main_root / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(main_root, "add", ".")
    _git(main_root, "commit", "-q", "-m", "seed")
    _git(main_root, "branch", "-M", "main")
    if dirty:
        (main_root / "stray.txt").write_text("dirty\n", encoding="utf-8")
    return main_root


def stub_coordination(
    monkeypatch: pytest.MonkeyPatch,
    claims: list[dict[str, object]],
    agents: list[dict[str, object]],
) -> None:
    monkeypatch.setattr(
        closeout,
        "_coordination_call",
        lambda _context, *arguments: (
            pytest.fail(f"unexpected coordination call: {arguments}")
            if arguments[0] != "status"
            else {"claims": claims, "agents": agents}
        ),
    )


def test_describe_dirty_main_names_claim_owner_and_lists_files_with_mtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_root = dirty_main_repo(tmp_path)
    (main_root / "web").mkdir()
    (main_root / "web" / "edit.tsx").write_text("export {};\n", encoding="utf-8")
    context = closeout.CloseoutContext(
        main_root=main_root,
        task_root=tmp_path / "task",
        branch="codex/task",
    )
    stub_coordination(
        monkeypatch,
        claims=[
            {
                "id": "claim-web",
                "status": "active",
                "agentId": "agent-web",
                "scopes": ["web/"],
            },
            {
                "id": "claim-done",
                "status": "completed",
                "agentId": "agent-done",
                "scopes": ["*"],
            },
        ],
        agents=[
            {
                "id": "agent-web",
                "state": "active",
                "branch": "codex/web-task",
                "worktree": str(tmp_path / "wt"),
            }
        ],
    )

    attribution = closeout.describe_dirty_main(context)

    web_line = next(line for line in attribution.file_lines if "web/edit.tsx" in line)
    assert web_line.startswith("dirty_main_file:")
    assert "mtime=" in web_line
    assert "mtime=unavailable" not in web_line
    assert any("stray.txt" in line for line in attribution.file_lines)
    assert len(attribution.owner_lines) == 1
    assert "agent-web" in attribution.owner_lines[0]
    assert "claim-web" in attribution.owner_lines[0]
    assert "claim-done" not in attribution.owner_lines[0]
    assert "agent-web" in attribution.next_action
    assert "codex/web-task" in attribution.next_action


def test_describe_dirty_main_without_matching_claim_gives_generic_guidance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_root = dirty_main_repo(tmp_path)
    context = closeout.CloseoutContext(
        main_root=main_root,
        task_root=tmp_path / "task",
        branch="codex/task",
    )
    stub_coordination(monkeypatch, claims=[], agents=[])

    attribution = closeout.describe_dirty_main(context)

    assert attribution.owner_lines == ()
    assert any("stray.txt" in line for line in attribution.file_lines)
    assert "no active claim covers them" in attribution.next_action


def test_describe_dirty_main_caps_file_listing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_root = dirty_main_repo(tmp_path)
    extra_count = 5
    for index in range(closeout.DIRTY_MAIN_FILE_LIMIT + extra_count):
        (main_root / f"loose-{index:02d}.txt").write_text("x\n", encoding="utf-8")
    context = closeout.CloseoutContext(
        main_root=main_root,
        task_root=tmp_path / "task",
        branch="codex/task",
    )
    stub_coordination(monkeypatch, claims=[], agents=[])

    attribution = closeout.describe_dirty_main(context)

    assert len(attribution.file_lines) == closeout.DIRTY_MAIN_FILE_LIMIT + 1
    assert f"{extra_count + 1} more paths" in attribution.file_lines[-1]


def test_resolve_context_dirty_main_error_carries_attribution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_root = dirty_main_repo(tmp_path)
    task_root = main_root / ".worktrees" / "task"
    _git(main_root, "worktree", "add", str(task_root), "-b", "codex/task")
    stub_coordination(monkeypatch, claims=[], agents=[])

    with pytest.raises(closeout.ManagedCloseoutError) as excinfo:
        closeout.resolve_context(task_root)

    assert excinfo.value.code == "dirty_main"
    assert any("stray.txt" in line for line in excinfo.value.detail_lines)


def test_managed_closeout_reports_dirty_main_attribution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_root = dirty_main_repo(tmp_path)
    task_root = main_root / ".worktrees" / "task"
    _git(main_root, "worktree", "add", str(task_root), "-b", "codex/task")
    stub_coordination(
        monkeypatch,
        claims=[
            {
                "id": "claim-stray",
                "status": "active",
                "agentId": "agent-stray",
                "scopes": ["*"],
            }
        ],
        agents=[{"id": "agent-stray", "state": "active", "branch": "codex/stray"}],
    )

    result = closeout.run_managed_closeout(
        task_root,
        claim_id="claim-dev",
        agent_id="agent-test",
    )

    assert result.status == "failed"
    assert result.exit_code == 1
    assert result.errors[0] == "dirty_main"
    assert any("stray.txt" in line for line in result.errors[1:])
    assert "agent-stray" in result.next_action


def test_merge_stage_dirty_main_reports_attribution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_root = dirty_main_repo(tmp_path, dirty=False)
    task_root = main_root / ".worktrees" / "task"
    _git(main_root, "worktree", "add", str(task_root), "-b", "codex/task")
    stub_coordination(monkeypatch, claims=[], agents=[])
    manifest = tmp_path / "manifest.json"
    monkeypatch.setattr(
        gate,
        "run_closeout",
        lambda *_args, **_kwargs: gate.GateResult(
            outcome="passed",
            exit_code=0,
            manifest_path=manifest,
        ),
    )
    verify_calls = {"count": 0}

    def fake_verify(*_args, **_kwargs):
        verify_calls["count"] += 1
        if verify_calls["count"] == 2:
            # A foreign session dirties main between the two verification
            # passes, so the ff-only merge must refuse with attribution.
            (main_root / "late.txt").write_text("dirty\n", encoding="utf-8")
        return gate.GateResult(outcome="passed", exit_code=0, manifest_path=manifest)

    monkeypatch.setattr(gate, "verify_manifest", fake_verify)
    monkeypatch.setattr(
        closeout,
        "acquire_integration_claim",
        lambda *_args, **_kwargs: "claim-int",
    )
    monkeypatch.setattr(closeout, "release_claim", lambda *_args, **_kwargs: None)

    result = closeout.run_managed_closeout(
        task_root,
        claim_id="claim-dev",
        agent_id="agent-test",
    )

    assert verify_calls["count"] == 2
    assert result.status == "failed"
    assert result.merged is False
    assert result.errors[0] == "dirty_main"
    assert any("late.txt" in line for line in result.errors[1:])


def test_cleanup_only_dirty_main_reports_attribution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_root = dirty_main_repo(tmp_path)
    context = closeout.CloseoutContext(
        main_root=main_root,
        task_root=tmp_path / "task",
        branch="codex/task",
    )
    stub_coordination(monkeypatch, claims=[], agents=[])
    error = closeout.dirty_main_error(context)
    assert error.code == "dirty_main"
    monkeypatch.setattr(
        closeout,
        "resolve_cleanup_context",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )

    result = closeout.run_cleanup_only(
        tmp_path / "task",
        branch="codex/task",
        agent_id="agent-test",
    )

    assert result.status == "merged_cleanup_pending"
    assert result.errors[0] == "dirty_main"
    assert any("stray.txt" in line for line in result.errors[1:])
    assert result.next_action == error.next_action
