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


def test_integration_claim_conflict_skips_quality_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(closeout, "resolve_context", lambda *_args, **_kwargs: context(tmp_path))

    def conflict(*_args, **_kwargs):
        raise closeout.ManagedCloseoutError("integration_claim_conflict")

    monkeypatch.setattr(closeout, "acquire_integration_claim", conflict)
    monkeypatch.setattr(
        gate,
        "run_closeout",
        lambda *_args, **_kwargs: pytest.fail("quality gate must not run without the lease"),
    )

    result = closeout.run_managed_closeout(
        tmp_path / "task",
        claim_id="claim-dev",
        agent_id="agent-test",
    )

    assert result.status == "integration_claim_conflict"
    assert result.exit_code == 1
    assert result.merged is False


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


def test_failed_quality_gate_releases_only_integration_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    monkeypatch.setattr(closeout, "resolve_context", lambda *_args, **_kwargs: context(tmp_path))
    monkeypatch.setattr(closeout, "acquire_integration_claim", lambda *_args, **_kwargs: "claim-int")
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
    assert events == ["claim-int:released"]


def test_integration_release_failure_is_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(closeout, "resolve_context", lambda *_args, **_kwargs: context(tmp_path))
    monkeypatch.setattr(closeout, "acquire_integration_claim", lambda *_args, **_kwargs: "claim-int")
    monkeypatch.setattr(
        gate,
        "run_closeout",
        lambda *_args, **_kwargs: gate.GateResult(outcome="failed", exit_code=1),
    )
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
    assert result.errors == ["failed", "integration_release_pending: registry locked"]


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
        "acquire",
        "closeout",
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
