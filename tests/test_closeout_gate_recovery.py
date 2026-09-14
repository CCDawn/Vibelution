from __future__ import annotations

import pytest

from scripts import task_closeout as closeout


def _context(tmp_path):
    return closeout.CloseoutContext(
        main_root=tmp_path / "main",
        task_root=tmp_path / "task",
        branch="codex/test-task",
    )


def _manifest_fields(fields: dict):
    return lambda _path, field: fields.get(field)


def test_stale_main_on_stale_branch_asks_to_merge_main(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(closeout.gate, "rev_parse", lambda *_a, **_k: "task-head")
    monkeypatch.setattr(closeout.gate, "main_revision_sha", lambda *_a, **_k: "new-main-sha-123456")
    monkeypatch.setattr(closeout.gate, "is_ancestor", lambda *_a, **_k: False)

    action, detail = closeout.classify_stale_main_recovery(_context(tmp_path), base="main")

    assert action == "merge_main_into_task_branch"
    assert "main" in detail


def test_stale_main_after_foreign_advance_reuses_manifest_under_token(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(closeout.gate, "rev_parse", lambda *_a, **_k: "task-head")
    monkeypatch.setattr(closeout.gate, "main_revision_sha", lambda *_a, **_k: "new-main-sha-123456")
    monkeypatch.setattr(closeout.gate, "is_ancestor", lambda *_a, **_k: True)
    monkeypatch.setattr(closeout.gate, "main_advance_skips_files", lambda *_a, **_k: True)
    monkeypatch.setattr(
        closeout,
        "_manifest_field",
        _manifest_fields({"validatedMainSha": "old-main", "changedFiles": ["web/a.ts"]}),
    )

    action, detail = closeout.classify_stale_main_recovery(
        _context(tmp_path),
        base="main",
        manifest_path=tmp_path / "manifest.json",
    )

    assert action == "sync_main_then_reserve_with_token"
    assert detail == ""


def test_stale_main_over_validated_paths_asks_to_rerun_validation(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(closeout.gate, "rev_parse", lambda *_a, **_k: "task-head")
    monkeypatch.setattr(closeout.gate, "main_revision_sha", lambda *_a, **_k: "new-main-sha-123456")
    monkeypatch.setattr(closeout.gate, "is_ancestor", lambda *_a, **_k: True)
    monkeypatch.setattr(closeout.gate, "main_advance_skips_files", lambda *_a, **_k: False)
    monkeypatch.setattr(
        closeout,
        "_manifest_field",
        _manifest_fields({"validatedMainSha": "old-main", "changedFiles": ["web/a.ts"]}),
    )

    action, _detail = closeout.classify_stale_main_recovery(
        _context(tmp_path),
        base="main",
        manifest_path=tmp_path / "manifest.json",
    )

    assert action == "rerun_validation"


def test_expired_development_claim_asks_to_refresh(tmp_path, monkeypatch) -> None:
    def reject(*_args, **_kwargs):
        raise closeout.ManagedCloseoutError("invalid_development_claim")

    monkeypatch.setattr(closeout, "resolve_context", lambda *_a, **_k: _context(tmp_path))
    monkeypatch.setattr(
        closeout,
        "resolve_claim_identity",
        lambda _context, claim_id="", agent_id="": (claim_id or "claim-dev", agent_id or "agent-test"),
    )
    monkeypatch.setattr(closeout, "validate_development_claim", reject)

    result = closeout.run_managed_closeout(
        tmp_path / "task",
        claim_id="claim-dev",
        agent_id="agent-test",
    )

    assert result.status == "failed"
    assert result.retryable is True
    assert result.next_action == "refresh_development_claim"


def test_missing_claim_for_unrelated_error_stays_non_retryable(tmp_path, monkeypatch) -> None:
    def reject(*_args, **_kwargs):
        raise closeout.ManagedCloseoutError("unsafe_worktree_path")

    monkeypatch.setattr(closeout, "resolve_context", lambda *_a, **_k: _context(tmp_path))
    monkeypatch.setattr(
        closeout,
        "resolve_claim_identity",
        lambda _context, claim_id="", agent_id="": (claim_id or "claim-dev", agent_id or "agent-test"),
    )
    monkeypatch.setattr(closeout, "validate_development_claim", reject)

    result = closeout.run_managed_closeout(
        tmp_path / "task",
        claim_id="claim-dev",
        agent_id="agent-test",
    )

    assert result.retryable is False
    assert result.next_action == ""
