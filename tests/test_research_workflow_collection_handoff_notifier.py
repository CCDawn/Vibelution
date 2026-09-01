"""Source-collection completed → hypothesis-first handoff notifier."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain as chain,
)
from core.web.services.team_workflow.research_runtime.operator_authorization import (
    server_operator_scope,
)
from core.web.services.team_workflow.source_collection import residual
from core.web.services.team_workflow.source_collection import runs as collection_runs
from core.web.services.team_workflow.source_collection import search_execution

from tests.test_research_workflow_hypothesis_first_chain import (
    _ROLES,
    _build_runtime,
    _close_first_meeting_with_envelope,
    _fake_collection_runs,
    _hf_env,
    _open_first_meeting,
    _patch_approved_question,
    _seed_parent_run,
)


def _closed_collection_request(tmp_path, monkeypatch):
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    _fake_collection_runs(monkeypatch)
    runtime = _build_runtime(tmp_path)
    _seed_parent_run(runtime, team_id, agents["experiment_planner"])
    agent_ids = [agents[role] for role in _ROLES]
    recorded = _open_first_meeting(team_id, agent_ids)
    meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]
    closed = _close_first_meeting_with_envelope(
        team_id, agent_ids, meeting_id, runtime
    )
    request = closed["collection"]["requests"][0]
    return team_id, agents, runtime, request


def test_completed_collection_handoffs_and_opens_next_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with server_operator_scope("u-1", roles=("operator",)):
        team_id, _agents, runtime, request = _closed_collection_request(
            tmp_path, monkeypatch
        )
        try:
            first = chain.notify_collection_run_terminal(
                team_id, request["collectionRunId"], "completed"
            )
            assert first["status"] == "handed_off"
            assert first["request"]["status"] == "handed_off"
            assert first["request"]["handoffRef"].startswith("source_collection_run:")
            next_meeting = first["nextMeeting"]
            assert next_meeting["status"] in {"opened", "reused", "budget_exhausted"}
            if next_meeting["status"] != "budget_exhausted":
                assert next_meeting["meetingRound"]["meetingRoundId"]

            repeated = chain.notify_collection_run_terminal(
                team_id, request["collectionRunId"], "completed"
            )
            assert repeated["status"] == "reused"
            if next_meeting["status"] != "budget_exhausted":
                assert (
                    repeated["nextMeeting"]["meetingRound"]["meetingRoundId"]
                    == next_meeting["meetingRound"]["meetingRoundId"]
                )
        finally:
            runtime.close()


def test_failed_and_needs_continue_do_not_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with server_operator_scope("u-1", roles=("operator",)):
        team_id, _agents, runtime, request = _closed_collection_request(
            tmp_path, monkeypatch
        )
        try:
            failed = chain.notify_collection_run_terminal(
                team_id, request["collectionRunId"], "failed"
            )
            assert failed["status"] == "collection_recovery"
            latest = chain.list_collection_requests(team_id)["requests"][0]
            assert latest["status"] != "handed_off"
            assert latest["collectionRunStatus"] == "failed"

            continued = chain.notify_collection_run_terminal(
                team_id, request["collectionRunId"], "needs_continue"
            )
            assert continued["status"] == "collection_recovery"
            latest = chain.list_collection_requests(team_id)["requests"][0]
            assert latest["status"] != "handed_off"
            assert latest["collectionRunStatus"] == "needs_continue"
            assert latest["handoffRef"] == ""
        finally:
            runtime.close()


def test_handoff_failure_is_pending_and_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with server_operator_scope("u-1", roles=("operator",)):
        team_id, _agents, runtime, request = _closed_collection_request(
            tmp_path, monkeypatch
        )
        try:
            def boom(*_args, **_kwargs):
                raise RuntimeError("handoff writer exploded")

            original_handoff = chain.record_collection_handoff
            monkeypatch.setattr(chain, "record_collection_handoff", boom)
            pending = chain.notify_collection_run_terminal(
                team_id, request["collectionRunId"], "completed"
            )
            assert pending["status"] == "handoff_pending"
            latest = chain.list_collection_requests(team_id)["requests"][0]
            assert latest["status"] == "handoff_pending"
            assert latest["handoffError"]

            monkeypatch.setattr(chain, "record_collection_handoff", original_handoff)
            retried = chain.notify_collection_run_terminal(
                team_id, request["collectionRunId"], "completed"
            )
            assert retried["status"] == "handed_off"
            latest = chain.list_collection_requests(team_id)["requests"][0]
            assert latest["status"] == "handed_off"
        finally:
            runtime.close()


def test_completion_paths_share_sync_notifier() -> None:
    sync_src = inspect.getsource(
        search_execution._sync_source_collection_stage_round_after_search
    )
    assert "notify_collection_run_terminal" in sync_src
    foreground = inspect.getsource(collection_runs.execute_source_collection_search)
    background = inspect.getsource(
        search_execution._run_source_collection_search_background
    )
    recovery = inspect.getsource(
        residual._sync_source_collection_stage_round_from_latest_work_run
    )
    assert "_sync_source_collection_stage_round_after_search" in foreground
    assert "execute_source_collection_search" in background
    assert "_sync_source_collection_stage_round_after_search" in recovery


# ---------------------------------------------------------------------------
# chain-level claim bridge: completed collection -> claim ledger -> gate


def _anchored_chain_candidates() -> list[dict]:
    return [
        {
            "candidateId": "candidate-run-a-1",
            "candidateType": "source_manifest",
            "sourceKind": "paper",
            "title": "Collected source one",
            "summary": "The collected abstract states the hyp-b mechanism holds.",
            "sourceUrl": "https://example.org/paper-a",
            "createdAt": "2026-09-01T15:18:49Z",
            "createdByAgent": "source_finder",
        },
        {
            "candidateId": "candidate-run-a-2",
            "candidateType": "source_manifest",
            "sourceKind": "paper",
            "title": "Collected source two",
            "summary": "A second collected abstract reports the same bounded result.",
            "sourceUrl": "https://example.org/paper-b",
            "createdAt": "2026-09-01T15:20:01Z",
            "createdByAgent": "source_finder",
        },
    ]


def _seed_hyp_b_candidate(team_id: str) -> None:
    from tests.test_research_workflow_hypothesis_first_chain import _QUESTION_ID
    from tests.test_research_workflow_t51_claim_evidence_materialization import (
        _seed_chain_hypothesis_candidates,
    )

    _seed_chain_hypothesis_candidates(
        team_id, _QUESTION_ID, {"hyp-b": "candidate hyp-b"}
    )


def test_completed_handoff_materializes_chain_claims_and_gate_becomes_decidable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Completed chain collections land claim rows their gate can evaluate.

    SCI-001 root cause regression: the review decision's collection ran,
    handed off and the chain still failed the convergence gate with
    claim_data_missing forever, because nothing ever wrote the claim ledger
    at chain level.  The handoff now bridges the collected sources into the
    question-scoped claim ledger bound to the decision's candidate.  The
    follow-up meeting open is stubbed (its model fallback is out of scope
    here); the bridge runs strictly before it.
    """
    from core.research.evidence import ClaimEvidenceStore
    from core.web.services.team_workflow import claim_ledger as claim_ledger_service
    from tests.test_research_workflow_hypothesis_first_chain import _QUESTION_ID
    from tests.test_research_workflow_t51_claim_evidence_materialization import (
        _seed_chain_collection_candidates,
    )

    with server_operator_scope("u-1", roles=("operator",)):
        team_id, _agents, runtime, request = _closed_collection_request(
            tmp_path, monkeypatch
        )
        try:
            assert request["hypothesisCandidateIds"] == ["hyp-b"]
            _seed_hyp_b_candidate(team_id)
            _seed_chain_collection_candidates(
                monkeypatch, _anchored_chain_candidates()
            )
            opened_meetings: list[str] = []
            monkeypatch.setattr(
                chain,
                "open_next_review_meeting",
                lambda *args, **kwargs: opened_meetings.append(
                    str(kwargs.get("collection_request_id") or "")
                )
                or {"status": "opened"},
            )

            # Before the handoff the gate is fail-closed with no claim data.
            pre_gate = chain.evaluate_claim_belief_gate(
                team_id, _QUESTION_ID, ["hyp-b"]
            )["hyp-b"]
            assert pre_gate["status"] == "blocked"
            assert pre_gate["reason"] == "claim_data_missing"

            first = chain.notify_collection_run_terminal(
                team_id, request["collectionRunId"], "completed"
            )
            assert first["status"] == "handed_off"
            assert first["claimMaterialization"]["status"] == "materialized"
            assert first["claimMaterialization"]["candidateClaimCount"] == 1
            assert opened_meetings == [request["requestId"]]

            rows = {
                item["claim"]: item
                for item in claim_ledger_service.list_claims(team_id)["claims"]
            }
            assert "candidate hyp-b" in rows
            assert rows["candidate hyp-b"]["question"] == _QUESTION_ID
            stored = ClaimEvidenceStore(tmp_path).list(team_id)
            assert {
                item["candidateId"] for item in stored
            } == {"hyp-b", "candidate-run-a-1", "candidate-run-a-2"}

            # The gate now evaluates instead of failing closed forever.
            verdict = chain.evaluate_claim_belief_gate(
                team_id, _QUESTION_ID, ["hyp-b"]
            )["hyp-b"]
            assert verdict["status"] == "allowed"
            assert verdict["reason"] == ""

            # Idempotent replay (operator re-handoff on a handed_off request
            # is also the backfill path for pre-bridge collections).
            reused = chain.record_collection_handoff(
                team_id, request["requestId"]
            )
            assert reused["status"] == "reused"
            assert reused["claimMaterialization"]["status"] == "materialized"
            assert claim_ledger_service.list_claims(team_id)["claimCount"] == len(rows)
            assert (
                len({item["claimEvidenceId"] for item in ClaimEvidenceStore(tmp_path).list(team_id)})
                == len(stored)
            )
            again = chain.evaluate_claim_belief_gate(
                team_id, _QUESTION_ID, ["hyp-b"]
            )["hyp-b"]
            assert again["status"] == "allowed"
        finally:
            runtime.close()


def test_handoff_without_collected_candidates_keeps_gate_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A collection without anchorable sources must not mint empty rows."""
    from core.web.services.team_workflow import claim_ledger as claim_ledger_service
    from tests.test_research_workflow_hypothesis_first_chain import _QUESTION_ID
    from tests.test_research_workflow_t51_claim_evidence_materialization import (
        _collected_source_candidate,
        _seed_chain_collection_candidates,
    )

    with server_operator_scope("u-1", roles=("operator",)):
        team_id, _agents, runtime, request = _closed_collection_request(
            tmp_path, monkeypatch
        )
        try:
            _seed_hyp_b_candidate(team_id)
            _seed_chain_collection_candidates(
                monkeypatch,
                [_collected_source_candidate("candidate-empty")],
            )
            monkeypatch.setattr(
                chain,
                "open_next_review_meeting",
                lambda *args, **kwargs: {"status": "opened"},
            )
            result = chain.record_collection_handoff(
                team_id, request["requestId"]
            )
            assert result["status"] == "handed_off"
            assert result["claimMaterialization"]["status"] == "skipped"
            assert result["claimMaterialization"]["reason"] == "no_anchored_candidates"
            assert claim_ledger_service.list_claims(team_id)["claimCount"] == 0
            verdict = chain.evaluate_claim_belief_gate(
                team_id, _QUESTION_ID, ["hyp-b"]
            )["hyp-b"]
            assert verdict["status"] == "blocked"
            assert verdict["reason"] == "claim_data_missing"
        finally:
            runtime.close()
