"""D04 hypothesis round contract + service tests.

Verifies that a round requires two substantially different candidates, a
seven-dimension independent review per candidate, pairwise comparisons covering
every pair, a Pareto analysis, a MetaReview, and full scope/lineage/meeting
refs — with fail-closed rejection when any item is missing.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import pytest

from core.research.workflow.contracts import (
    SCORE_DIMENSIONS,
    ContractValidationError,
    HypothesisRound,
    scope_hash_for,
)
from core.web.services import team_service
from core.web.services.team_workflow import (
    hypothesis_rounds as hypothesis_rounds_service,
)

_QUARANTINE_LOGGER = "core.web.services.team_workflow.jsonl_quarantine"


def _team(tmp_path, monkeypatch):
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(hypothesis_rounds_service, "PROJECT_ROOT", tmp_path)
    return team_service.create_team(name="hypothesis round team")["teamId"]


def _scope(**overrides):
    base = {
        "program": "XH-202619",
        "theme": "cc-gpu-operator-001",
        "campaign": "cc-campaign-gpu-operator-001",
        "question": "SCI-091",
        "branch": "main",
        "workflow": "hypothesis_and_plan",
        "agentId": "agent-alpha",
        "mode": "formal",
    }
    base.update(overrides)
    return base


def _scope_hash(**overrides):
    scope = _scope(**overrides)
    return scope_hash_for(
        program=scope["program"],
        theme=scope["theme"],
        campaign=scope["campaign"],
        question=scope["question"],
        branch=scope["branch"],
        workflow=scope["workflow"],
        agent_id=scope["agentId"],
        mode=scope["mode"],
    )


def _candidate(candidate_id, claim, difference, reviewer="agent-reviewer-1"):
    return {
        "candidateId": candidate_id,
        "claim": claim,
        "rationale": f"rationale for {candidate_id}",
        "differenceFromAlternatives": difference,
        "lineageRefs": [],
        "scores": {dim: 0.8 for dim in SCORE_DIMENSIONS},
        "reviewedBy": reviewer,
        "status": "proposed",
    }


def _round_payload(**overrides):
    payload = {
        **_scope(),
        "roundId": "hround-test-1",
        "candidates": [
            _candidate(
                "cand-a",
                "A bounded proxy improves reconstruction under noise.",
                "Proposes a bounded proxy mechanism on the encoder side.",
            ),
            _candidate(
                "cand-b",
                "A higher-capacity decoder generalizes better on the held-out split.",
                "Proposes a decoder capacity change instead of an encoder proxy.",
                reviewer="agent-reviewer-2",
            ),
        ],
        "lineage": [{"kind": "candidate", "id": "cand-root-0"}],
        "meetingRefs": [],
        "status": "open",
    }
    payload.update(overrides)
    return payload


def _meeting_refs():
    return [
        {"kind": "meeting_round", "id": "meeting-close-1"},
        {"kind": "meeting_digest", "id": "digest-close-1"},
        {"kind": "decision_record", "id": "decision-close-1"},
    ]


def _closure(round_payload, candidates=None):
    candidates = candidates or round_payload["candidates"]
    candidate_ids = [item["candidateId"] for item in candidates]
    left, right = candidate_ids[0], candidate_ids[1]
    return {
        "pairwiseComparisons": [
            {
                "comparisonId": f"cmp-{left}-{right}",
                "leftCandidateId": left,
                "rightCandidateId": right,
                "reviewerAgentId": "agent-pairwise",
                "outcome": "left_wins",
                "justification": f"{left} dominates on feasibility and evidence support.",
            }
        ],
        "pareto": {
            "paretoFrontCandidateIds": [left],
            "dominatedCandidateIds": [right],
            "analystAgentId": "agent-pareto",
            "notes": "Pareto front verified over all seven dimensions.",
        },
        "metaReview": {
            "metaReviewId": "meta-close-1",
            "reviewerAgentId": "agent-meta",
            "recommendationCandidateId": left,
            "rationale": f"{left} is the strongest candidate across the review matrix.",
            "riskNotes": "Falsifiability remains the weakest dimension.",
            "accepted": True,
        },
        "meetingRefs": _meeting_refs(),
        "closedBy": "agent-coordinator",
    }


def test_contract_round_trips_a_complete_round() -> None:
    payload = _round_payload(status="closed")
    closure = _closure(payload)
    closed = {
        **payload,
        **closure,
        "scopeHash": _scope_hash(),
        "createdAt": "2026-08-16T00:00:00Z",
        "closedAt": "2026-08-17T00:00:00Z",
    }

    parsed = HypothesisRound.from_dict(closed)
    parsed.validate_complete()

    assert parsed.roundId == "hround-test-1"
    assert len(parsed.candidates) == 2
    assert parsed.candidates[0].scores == {dim: 0.8 for dim in SCORE_DIMENSIONS}
    assert parsed.to_dict() == closed
    assert parsed.scopeHash == _scope_hash()


def test_create_rejects_fewer_than_two_candidates(tmp_path, monkeypatch) -> None:
    team_id = _team(tmp_path, monkeypatch)
    payload = _round_payload(candidates=[_candidate("cand-a", "Only one candidate.", "Sole alternative.")])

    with pytest.raises(ContractValidationError, match="at least two"):
        hypothesis_rounds_service.create_hypothesis_round(team_id, payload)


def test_create_rejects_missing_review_dimension(tmp_path, monkeypatch) -> None:
    team_id = _team(tmp_path, monkeypatch)
    candidate = _candidate("cand-a", "Candidate without a full review matrix.", "Missing one dimension.")
    candidate["scores"] = {dim: 0.7 for dim in SCORE_DIMENSIONS if dim != "novelty"}
    payload = _round_payload(candidates=[candidate, _candidate("cand-b", "Second candidate.", "Second alternative.")])

    with pytest.raises(ContractValidationError, match="novelty"):
        hypothesis_rounds_service.create_hypothesis_round(team_id, payload)


def test_create_rejects_duplicate_claim_as_not_substantially_different(tmp_path, monkeypatch) -> None:
    team_id = _team(tmp_path, monkeypatch)
    first = _candidate("cand-a", "The proxy mechanism reduces reconstruction drift.", "Encoder-side proxy.")
    duplicate = _candidate("cand-b", "the proxy mechanism reduces reconstruction drift", "Encoder-side proxy.")
    payload = _round_payload(candidates=[first, duplicate])

    with pytest.raises(ContractValidationError, match="substantially different"):
        hypothesis_rounds_service.create_hypothesis_round(team_id, payload)


def test_create_and_close_round_fails_closed_on_missing_items(tmp_path, monkeypatch) -> None:
    team_id = _team(tmp_path, monkeypatch)
    created = hypothesis_rounds_service.create_hypothesis_round(team_id, _round_payload())
    round_id = created["round"]["roundId"]
    closure = _closure(created["round"])

    with pytest.raises(ContractValidationError, match="meeting digest and decision refs"):
        missing_meeting = dict(closure)
        missing_meeting["meetingRefs"] = []
        hypothesis_rounds_service.close_hypothesis_round(team_id, round_id, missing_meeting)

    with pytest.raises(ContractValidationError, match="pairwise"):
        missing_pair = dict(closure)
        missing_pair["pairwiseComparisons"] = []
        hypothesis_rounds_service.close_hypothesis_round(team_id, round_id, missing_pair)

    with pytest.raises(ContractValidationError, match="Pareto"):
        missing_pareto = dict(closure)
        missing_pareto["pareto"] = {
            "paretoFrontCandidateIds": [],
            "dominatedCandidateIds": [],
            "analystAgentId": "agent-pareto",
            "notes": "",
        }
        hypothesis_rounds_service.close_hypothesis_round(team_id, round_id, missing_pareto)

    with pytest.raises(ContractValidationError, match="MetaReview"):
        missing_meta = dict(closure)
        missing_meta["metaReview"] = {
            "metaReviewId": "meta-close-1",
            "reviewerAgentId": "",
            "recommendationCandidateId": "",
            "rationale": "",
            "riskNotes": "",
            "accepted": False,
        }
        hypothesis_rounds_service.close_hypothesis_round(team_id, round_id, missing_meta)


def test_create_and_close_round_is_idempotent(tmp_path, monkeypatch) -> None:
    team_id = _team(tmp_path, monkeypatch)
    created = hypothesis_rounds_service.create_hypothesis_round(team_id, _round_payload())
    round_id = created["round"]["roundId"]
    closure = _closure(created["round"])

    first = hypothesis_rounds_service.close_hypothesis_round(team_id, round_id, closure)
    repeated = hypothesis_rounds_service.close_hypothesis_round(team_id, round_id, closure)

    assert first["status"] == "created"
    assert first["closed"] is True
    assert first["round"]["status"] == "closed"
    assert repeated["status"] == "reused"
    assert repeated["round"]["roundId"] == round_id
    assert repeated["round"]["status"] == "closed"


def test_round_id_and_closure_reject_conflicting_reuse(tmp_path, monkeypatch) -> None:
    team_id = _team(tmp_path, monkeypatch)
    created = hypothesis_rounds_service.create_hypothesis_round(team_id, _round_payload())
    conflicting = _round_payload(
        candidates=[
            _candidate("cand-a", "A changed claim.", "Different definition."),
            _candidate("cand-b", "Another changed claim.", "Different definition two."),
        ]
    )
    with pytest.raises(
        hypothesis_rounds_service.ResearchHypothesisRoundError,
        match="different content",
    ):
        hypothesis_rounds_service.create_hypothesis_round(team_id, conflicting)

    round_id = created["round"]["roundId"]
    closure = _closure(created["round"])
    hypothesis_rounds_service.close_hypothesis_round(team_id, round_id, closure)
    conflicting_closure = dict(closure)
    conflicting_closure["closedBy"] = "another-agent"
    with pytest.raises(
        hypothesis_rounds_service.ResearchHypothesisRoundError,
        match="different closure content",
    ):
        hypothesis_rounds_service.close_hypothesis_round(
            team_id, round_id, conflicting_closure
        )


def test_recovery_reopens_an_incomplete_round(tmp_path, monkeypatch) -> None:
    team_id = _team(tmp_path, monkeypatch)
    created = hypothesis_rounds_service.create_hypothesis_round(team_id, _round_payload())
    round_id = created["round"]["roundId"]

    assert hypothesis_rounds_service.get_hypothesis_round(team_id, round_id)["round"]["status"] == "open"
    with pytest.raises(ContractValidationError, match="meeting digest and decision refs"):
        incomplete = _closure(created["round"])
        incomplete["meetingRefs"] = []
        hypothesis_rounds_service.close_hypothesis_round(
            team_id, round_id, incomplete
        )


def test_list_returns_latest_round_records(tmp_path, monkeypatch) -> None:
    team_id = _team(tmp_path, monkeypatch)
    created = hypothesis_rounds_service.create_hypothesis_round(team_id, _round_payload(roundId="hround-list-1"))

    listed = hypothesis_rounds_service.list_hypothesis_rounds(team_id)

    assert listed["roundCount"] == 1
    assert listed["rounds"][0]["roundId"] == "hround-list-1"
    assert created["round"]["roundId"] == "hround-list-1"
    assert listed["corruptQuarantinedLineCount"] == 0


def test_corrupt_round_lines_are_quarantined_instead_of_raising(
    tmp_path, monkeypatch, caplog
) -> None:
    team_id = _team(tmp_path, monkeypatch)
    created = hypothesis_rounds_service.create_hypothesis_round(
        team_id, _round_payload(roundId="hround-quarantine")
    )
    round_id = created["round"]["roundId"]
    storage_path = Path(
        hypothesis_rounds_service.list_hypothesis_rounds(team_id)["storagePath"]
    )
    corrupt_texts = ["{torn-round-line", json.dumps(["wrong", "shape"])]
    with open(storage_path, "a", encoding="utf-8") as handle:
        handle.write("".join(text + "\n" for text in corrupt_texts))
    original_bytes = storage_path.read_bytes()

    with caplog.at_level(logging.WARNING, logger=_QUARANTINE_LOGGER):
        listed = hypothesis_rounds_service.list_hypothesis_rounds(team_id)
        fetched = hypothesis_rounds_service.get_hypothesis_round(team_id, round_id)

    assert [item["roundId"] for item in listed["rounds"]] == [round_id]
    assert listed["roundCount"] == 1
    assert listed["corruptQuarantinedLineCount"] == 2
    assert fetched["corruptQuarantinedLineCount"] == 2
    assert fetched["round"]["status"] == "open"

    # The ledger stays byte-identical; only the sidecar gains evidence.
    assert storage_path.read_bytes() == original_bytes
    sidecar = storage_path.with_name(storage_path.name + ".corrupt.jsonl")
    rows = [
        json.loads(line)
        for line in sidecar.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [row["lineHash"] for row in rows] == [
        hashlib.sha256(text.encode("utf-8")).hexdigest() for text in corrupt_texts
    ]
    assert [row["lineNumber"] for row in rows] == [2, 3]

    count_warnings = [
        record
        for record in caplog.records
        if record.name == _QUARANTINE_LOGGER and len(record.args) >= 2
    ]
    assert any(
        str(storage_path) in record.getMessage() and record.args[1] == 2
        for record in count_warnings
    )
    logged_text = "".join(record.getMessage() for record in caplog.records)
    assert all(text not in logged_text for text in corrupt_texts)


def test_round_reads_are_idempotent_and_clean_ledgers_stay_sidecar_free(
    tmp_path, monkeypatch
) -> None:
    team_id = _team(tmp_path, monkeypatch)
    created = hypothesis_rounds_service.create_hypothesis_round(
        team_id, _round_payload(roundId="hround-clean")
    )
    round_id = created["round"]["roundId"]

    clean_listed = hypothesis_rounds_service.list_hypothesis_rounds(team_id)
    clean_fetched = hypothesis_rounds_service.get_hypothesis_round(team_id, round_id)
    assert clean_listed["corruptQuarantinedLineCount"] == 0
    assert clean_fetched["corruptQuarantinedLineCount"] == 0
    storage_path = Path(clean_listed["storagePath"])
    sidecar = storage_path.with_name(storage_path.name + ".corrupt.jsonl")
    assert not sidecar.exists()

    with open(storage_path, "a", encoding="utf-8") as handle:
        handle.write("{torn-round-line\n")
    first = hypothesis_rounds_service.list_hypothesis_rounds(team_id)
    assert first["corruptQuarantinedLineCount"] == 1
    sidecar_after_first = sidecar.read_bytes()

    repeated_list = hypothesis_rounds_service.list_hypothesis_rounds(team_id)
    repeated_fetch = hypothesis_rounds_service.get_hypothesis_round(team_id, round_id)

    assert repeated_list["corruptQuarantinedLineCount"] == 1
    assert repeated_fetch["corruptQuarantinedLineCount"] == 1
    assert sidecar.read_bytes() == sidecar_after_first


def test_failure_records_persist_resolve_and_leave_rounds_untouched(
    tmp_path, monkeypatch
) -> None:
    """Failure traces live in a sibling ledger and never enter the rounds file."""
    team_id = _team(tmp_path, monkeypatch)
    service = hypothesis_rounds_service

    recorded = service.record_hypothesis_round_failure(
        team_id,
        {
            "status": "blocked",
            "failureCode": "fan_in_waiting_for_sibling_reviews",
            "reason": "fan-in pending",
            "meetingRoundIds": ["meeting-a"],
            "selectionId": "selection-1",
            "roundIndex": 1,
            "questionId": "SCI-091",
            "retryHint": "close the pending sibling reviews",
            "context": {"pendingMeetingRoundIds": ["meeting-b"]},
        },
    )
    assert recorded["status"] == "recorded"
    record = recorded["failure"]
    assert record["failureId"].startswith("hrfail-")
    assert record["status"] == "blocked"
    assert record["recordKind"] == "hypothesis_round_failure"
    assert record["resolvedAt"] == ""
    assert record["resolvedByRoundId"] == ""
    assert record["context"] == {"pendingMeetingRoundIds": ["meeting-b"]}

    listed = service.list_hypothesis_round_failures(team_id)
    assert listed["failureCount"] == 1
    assert listed["openFailureCount"] == 1
    assert listed["failures"][0]["failureId"] == record["failureId"]
    # The round ledger itself must stay free of failure-state records.
    assert service.list_hypothesis_rounds(team_id)["roundCount"] == 0

    resolved_count = service.resolve_hypothesis_round_failures(
        team_id,
        resolved_by_round_id="hround-abc123",
        round_id="hround-abc123",
        selection_id="selection-1",
        round_index=1,
        meeting_round_ids=["meeting-a", "meeting-b"],
    )
    assert resolved_count == 1
    after = service.list_hypothesis_round_failures(team_id)
    assert after["openFailureCount"] == 0
    assert after["failures"][0]["status"] == "resolved"
    assert after["failures"][0]["resolvedByRoundId"] == "hround-abc123"
    assert after["failures"][0]["resolvedAt"]
    # Idempotent: an already-resolved trace never resolves twice.
    assert (
        service.resolve_hypothesis_round_failures(
            team_id,
            resolved_by_round_id="hround-abc123",
            selection_id="selection-1",
            round_index=1,
        )
        == 0
    )


def test_failure_resolution_requires_correlation(tmp_path, monkeypatch) -> None:
    team_id = _team(tmp_path, monkeypatch)
    service = hypothesis_rounds_service
    service.record_hypothesis_round_failure(
        team_id,
        {
            "status": "failed",
            "failureCode": "hypothesis_round_precondition_failed",
            "reason": "candidate requires a non-empty claim",
            "meetingRoundIds": ["meeting-x"],
            "selectionId": "selection-1",
            "roundIndex": 1,
        },
    )
    assert (
        service.resolve_hypothesis_round_failures(
            team_id,
            resolved_by_round_id="hround-other",
            selection_id="selection-2",
            round_index=1,
        )
        == 0
    )
    assert (
        service.resolve_hypothesis_round_failures(
            team_id,
            resolved_by_round_id="hround-other",
            selection_id="selection-1",
            round_index=2,
        )
        == 0
    )
    assert (
        service.resolve_hypothesis_round_failures(
            team_id,
            resolved_by_round_id="hround-other",
            round_id="hround-other",
        )
        == 0
    )
    remaining = service.list_hypothesis_round_failures(team_id)
    assert remaining["openFailureCount"] == 1
    assert remaining["failures"][0]["failureCode"] == (
        "hypothesis_round_precondition_failed"
    )


def test_failure_record_requires_code_and_known_status(
    tmp_path, monkeypatch
) -> None:
    team_id = _team(tmp_path, monkeypatch)
    service = hypothesis_rounds_service
    with pytest.raises(service.ResearchHypothesisRoundError):
        service.record_hypothesis_round_failure(team_id, {"status": "failed"})
    with pytest.raises(service.ResearchHypothesisRoundError):
        service.record_hypothesis_round_failure(
            team_id, {"failureCode": "some_code", "status": "bogus"}
        )
    assert service.list_hypothesis_round_failures(team_id)["failureCount"] == 0
