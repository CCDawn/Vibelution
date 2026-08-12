"""T5.1-3 RED: real readiness providers + agent resolvability.

Production RealDomainReadinessContext must query domain authorities without
depending on domain_overrides, return a real domain_revision_vector, and
resolve agents via Agent Directory (not bool(agent_id)).

P1: revision vector and question_snapshot prefer run-scoped authorities.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.web.services.team_workflow.research_runtime.real_readiness_context import (
    RealDomainReadinessContext,
)
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_event_record,
    build_run_record,
)


def test_agent_resolvable_rejects_unknown_nonempty_id(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        ctx = RealDomainReadinessContext(harness.store)
        assert ctx.agent_resolvable("") is False
        assert ctx.agent_resolvable("agent-definitely-missing-t513") is False
    finally:
        harness.close()


def test_domain_revision_vector_is_not_permanently_empty(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        ctx = RealDomainReadinessContext(harness.store)
        vector = dict(ctx.domain_revision_vector("research-team", "run-test"))
        assert vector, "production readiness must expose a real domain revision vector"
        assert all(str(v).strip() for v in vector.values())
    finally:
        harness.close()


def test_candidate_stats_uses_provider_not_only_override(tmp_path: Path) -> None:
    from core.web.services.team_workflow.research_runtime import readiness_providers

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        calls: list[tuple[str, str]] = []

        def fake_stats(team_id: str, run_id: str, **_kwargs):
            calls.append((team_id, run_id))
            return {"record_count": 4}

        original = readiness_providers.fetch_candidate_stats
        readiness_providers.fetch_candidate_stats = fake_stats  # type: ignore[assignment]
        try:
            ctx = RealDomainReadinessContext(harness.store)  # no domain_overrides
            stats = ctx.candidate_stats("research-team", "run-test")
            assert stats == {"record_count": 4}
            assert calls == [("research-team", "run-test")]
        finally:
            readiness_providers.fetch_candidate_stats = original  # type: ignore[assignment]
    finally:
        harness.close()


def test_evidence_cards_stats_provider_wired(tmp_path: Path) -> None:
    from core.web.services.team_workflow.research_runtime import readiness_providers

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        original = readiness_providers.fetch_evidence_cards_stats

        def fake_cards(team_id: str, run_id: str, **_kwargs):
            return {"card_count": 2, "missing_minimal_fields": []}

        readiness_providers.fetch_evidence_cards_stats = fake_cards  # type: ignore[assignment]
        try:
            ctx = RealDomainReadinessContext(harness.store)
            assert ctx.evidence_cards_stats("research-team", "run-test") == {
                "card_count": 2,
                "missing_minimal_fields": [],
            }
        finally:
            readiness_providers.fetch_evidence_cards_stats = original  # type: ignore[assignment]
    finally:
        harness.close()


def test_production_context_does_not_require_domain_overrides_for_revision(
    tmp_path: Path,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        ctx = RealDomainReadinessContext(harness.store, service_overrides=None)
        # Must not crash and must not return empty forever.
        vector = ctx.domain_revision_vector("research-team", "run-test")
        assert isinstance(vector, dict)
        assert len(vector) >= 1
    finally:
        harness.close()


def test_domain_revision_vector_scopes_candidates_and_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import readiness_providers

    snapshot = {
        "snapshotHash": "s" * 64,
        "sourceCollectionRunId": "sc-current",
        "projectId": "proj-1",
    }
    noisy_candidates = [
        {"candidateId": "c-other-sc", "sourceCollectionRunId": "sc-other"},
        {
            "candidateId": "c-current",
            "sourceCollectionRunId": "sc-current",
            "workflowRunId": "run-current",
        },
        {
            "candidateId": "c-other-wf",
            "sourceCollectionRunId": "sc-current",
            "workflowRunId": "run-other",
        },
    ]
    only_current_candidates = [noisy_candidates[1]]
    noisy_evidence = [
        {
            "claimEvidenceId": "e-other-sc",
            "sourceCollectionRunId": "sc-other",
            "workflowRunId": "run-current",
            "quote": "q",
            "sourceId": "src-1",
        },
        {
            "claimEvidenceId": "e-current",
            "sourceCollectionRunId": "sc-current",
            "workflowRunId": "run-current",
            "quote": "q",
            "sourceId": "src-1",
        },
        {
            "claimEvidenceId": "e-other-wf",
            "sourceCollectionRunId": "sc-current",
            "workflowRunId": "run-other",
            "quote": "q",
            "sourceId": "src-1",
        },
    ]
    only_current_evidence = [noisy_evidence[1]]

    candidate_payload = {"candidates": noisy_candidates, "workflowId": "wf-1"}
    evidence_rows = list(noisy_evidence)

    def fake_list_candidates(team_id: str, limit: int = 500):
        _ = (team_id, limit)
        return candidate_payload

    class _FakeEvidenceStore:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def list(self, team_id: str):
            _ = team_id
            return evidence_rows

    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.candidates.list_candidate_store",
        fake_list_candidates,
    )
    monkeypatch.setattr(
        "core.research.evidence.ClaimEvidenceStore",
        _FakeEvidenceStore,
    )

    noisy = readiness_providers.build_domain_revision_vector(
        "research-team",
        "run-current",
        input_snapshot=snapshot,
    )
    candidate_payload = {"candidates": only_current_candidates, "workflowId": "wf-1"}
    evidence_rows = list(only_current_evidence)
    scoped_only = readiness_providers.build_domain_revision_vector(
        "research-team",
        "run-current",
        input_snapshot=snapshot,
    )
    assert noisy["source_collection"] == scoped_only["source_collection"]
    assert noisy["evidence"] == scoped_only["evidence"]
    assert noisy["input_snapshot"] == "s" * 64


def test_unscoped_team_candidates_do_not_unlock_current_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1: historical candidates without run markers must not inflate scoped stats."""
    from core.web.services.team_workflow.research_runtime import readiness_providers

    snapshot = {
        "sourceCollectionRunId": "sc-current",
        "projectId": "proj-1",
    }
    # Team-level history with no SC / workflow markers — previously could unlock.
    unscoped_history = [
        {"candidateId": "c-orphan-1", "title": "legacy orphan"},
        {"candidateId": "c-orphan-2", "metadata": {"note": "also unscoped"}},
    ]
    current_only = [
        {
            "candidateId": "c-current",
            "sourceCollectionRunId": "sc-current",
            "workflowRunId": "run-current",
        }
    ]

    def fake_list(team_id: str, limit: int = 500):
        _ = (team_id, limit)
        return {"candidates": unscoped_history + current_only}

    def fake_summary(team_id: str, *, run_id: str = ""):
        _ = (team_id, run_id)
        # Zero summary so orphan store rows cannot unlock via SC fallback either.
        return {"runSummary": {"recordCount": 0, "candidateCount": 0}}

    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.candidates.list_candidate_store",
        fake_list,
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.runs.get_source_collection_summary",
        fake_summary,
    )
    stats = readiness_providers.fetch_candidate_stats(
        "team-1",
        "run-current",
        input_snapshot=snapshot,
    )
    assert stats is not None
    assert int(stats.get("record_count") or stats.get("candidate_count") or 0) == 1

    scoped = readiness_providers._scope_candidates(  # noqa: SLF001
        unscoped_history + current_only,
        snapshot,
        "run-current",
    )
    assert [item["candidateId"] for item in scoped] == ["c-current"]

    # Only unscoped history: must not unlock (no scoped stats).
    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.candidates.list_candidate_store",
        lambda team_id, limit=500: {"candidates": unscoped_history},
    )
    assert (
        readiness_providers.fetch_candidate_stats(
            "team-1",
            "run-current",
            input_snapshot=snapshot,
        )
        is None
    )
    assert (
        readiness_providers._scope_candidates(  # noqa: SLF001
            unscoped_history,
            snapshot,
            "run-current",
        )
        == []
    )


def test_question_snapshot_prefers_caller_run_id(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_question_run(
            harness.store,
            run_id="run-preferred",
            question="Preferred question",
            created_at_ms=FIXED_NOW_MS,
        )
        _seed_question_run(
            harness.store,
            run_id="run-newer",
            question="Newer competing question",
            created_at_ms=FIXED_NOW_MS + 10_000,
        )
        ctx = RealDomainReadinessContext(harness.store)
        preferred = ctx.question_snapshot(
            "research-team",
            "SCI-096",
            run_id="run-preferred",
        )
        assert preferred is not None
        assert preferred["question"] == "Preferred question"
        assert preferred["runId"] == "run-preferred"

        newest = ctx.question_snapshot("research-team", "SCI-096")
        assert newest is not None
        assert newest["question"] == "Newer competing question"
        assert newest["runId"] == "run-newer"
    finally:
        harness.close()


def _seed_question_run(
    store,
    *,
    run_id: str,
    question: str,
    created_at_ms: int,
) -> None:
    input_snapshot = {
        "questionId": "SCI-096",
        "researchObjectiveContract": {"question": question},
        "snapshotHash": f"hash-{run_id}",
    }
    base = build_run_record(
        run_id=run_id,
        last_event_sequence=1,
        created_at_ms=created_at_ms,
    )
    record = base.__class__(
        run_id=base.run_id,
        team_id=base.team_id,
        workflow_id=base.workflow_id,
        workflow_version_id=base.workflow_version_id,
        thread_id=base.thread_id,
        project_id=base.project_id,
        question_id=base.question_id,
        status=base.status,
        run_version=base.run_version,
        last_event_sequence=base.last_event_sequence,
        input_snapshot_json=json.dumps(input_snapshot, ensure_ascii=False),
        input_snapshot_hash=base.input_snapshot_hash,
        safety_limits_json=base.safety_limits_json,
        binding_snapshot_set_id=base.binding_snapshot_set_id,
        active_node_id=base.active_node_id,
        parent_run_id=base.parent_run_id,
        forked_from_checkpoint_id=base.forked_from_checkpoint_id,
        completion_kind=base.completion_kind,
        terminal_reason=base.terminal_reason,
        blocked_problem_json=base.blocked_problem_json,
        created_at_ms=created_at_ms,
        updated_at_ms=created_at_ms,
        completed_at_ms=base.completed_at_ms,
    )

    def mutate(uow):
        uow.repository.insert_run(record)
        uow.repository.insert_event(
            build_event_record(
                sequence=1,
                run_id=run_id,
                event_type="run_created",
                event_id=f"evt-created-{run_id}",
            )
        )

    store.submit(mutate, force_flush=True).result(timeout=10)
