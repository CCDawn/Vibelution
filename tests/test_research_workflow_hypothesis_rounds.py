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


def test_blocked_wait_trace_is_idempotent_per_wait_episode(
    tmp_path, monkeypatch
) -> None:
    """Repeated observations of one wait keep one open blocked row.

    The auto-advance sweep re-enters a waiting fan-in every tick; before this
    guarantee the ledger appended a fresh blocked row per observation
    (SCI-117: 3,692 identical rows for one stuck question), so wait-state
    bookkeeping must correlate by scope, not by observation time.
    """
    team_id = _team(tmp_path, monkeypatch)
    service = hypothesis_rounds_service
    payload = {
        "status": "blocked",
        "failureCode": "fan_in_waiting_for_sibling_reviews",
        "reason": "fan-in pending",
        "meetingRoundIds": ["meeting-a"],
        "selectionId": "selection-1",
        "roundIndex": 1,
        "context": {"pendingMeetingRoundIds": ["meeting-b", "meeting-c"]},
    }
    first = service.record_hypothesis_round_failure(team_id, payload)
    assert first["deduplicated"] is False

    # Sibling progress changes the context but not the wait identity: the
    # episode keeps its original row instead of minting a new failure id.
    shrunk = {
        **payload,
        "context": {"pendingMeetingRoundIds": ["meeting-c"]},
    }
    for _ in range(3):
        repeated = service.record_hypothesis_round_failure(team_id, shrunk)
        assert repeated["status"] == "recorded"
        assert repeated["deduplicated"] is True
        assert repeated["failure"]["failureId"] == first["failure"]["failureId"]
    listed = service.list_hypothesis_round_failures(team_id)
    assert listed["failureCount"] == 1
    assert listed["openFailureCount"] == 1

    # Resolving the episode (round generated) closes dedupe: the same scope
    # may wait again later as a genuinely new episode.
    assert (
        service.resolve_hypothesis_round_failures(
            team_id,
            resolved_by_round_id="hround-later",
            selection_id="selection-1",
            round_index=1,
            meeting_round_ids=["meeting-a"],
        )
        == 1
    )
    fresh = service.record_hypothesis_round_failure(team_id, payload)
    assert fresh["deduplicated"] is False
    assert fresh["failure"]["failureId"] != first["failure"]["failureId"]
    assert service.list_hypothesis_round_failures(team_id)["openFailureCount"] == 1

    # Failed generations stay per-attempt: each one spent real work, and the
    # automatic retry budget counts attempts (never dedupes them away).
    for index in range(2):
        recorded = service.record_hypothesis_round_failure(
            team_id,
            {
                **payload,
                "status": "failed",
                "failureCode": f"hypothesis_round_generation_error_{index}",
            },
        )
        assert recorded["deduplicated"] is False
    assert service.list_hypothesis_round_failures(team_id)["failureCount"] == 4


# ---------------------------------------------------------------------------
# Pre-generation dedup: reuse before spend + in-flight rejection
# ---------------------------------------------------------------------------


def _race_env(tmp_path, monkeypatch) -> str:
    """Create a tmp team and wire a closed two-meeting fan-in group."""
    from core.research.workflow.contracts import scope_hash_for
    from core.web.services.team_workflow import meeting_rounds

    team_id = _team(tmp_path, monkeypatch)

    scope = _scope(mode="dev", agentId="agent-coordinator")
    scope_hash = scope_hash_for(
        program=scope["program"],
        theme=scope["theme"],
        campaign=scope["campaign"],
        question=scope["question"],
        branch=scope["branch"],
        workflow=scope["workflow"],
        agent_id=scope["agentId"],
        mode=scope["mode"],
    )
    meetings_by_id = {}
    for candidate_id, meeting_id in (
        ("cand-a", "meeting-a"),
        ("cand-b", "meeting-b"),
    ):
        meetings_by_id[meeting_id] = {
            **scope,
            "scopeHash": scope_hash,
            "meetingRoundId": meeting_id,
            "meetingType": "hypothesis_review",
            "status": "closed",
            "digestId": f"digest-{candidate_id}",
            "decisionRefs": [f"decision-{candidate_id}"],
            "discussionItemRefs": [f"hypothesis_candidate:{candidate_id}"],
            "participants": ["agent-coordinator"],
            "participantRoleIds": ["coordinator"],
            "closedBy": "agent-coordinator",
        }
    digest_rows = [
        {
            "digestId": f"digest-{candidate_id}",
            "summary": candidate_id,
            "sourceMessageRefs": [f"message:{candidate_id}"],
            "contentHash": f"hash-{candidate_id}",
        }
        for candidate_id in ("cand-a", "cand-b")
    ]
    decision_rows = [
        {
            "decisionId": f"decision-{candidate_id}",
            "decision": "approve",
            "candidateRefs": [candidate_id],
            "evidenceRefs": [f"message:{candidate_id}"],
        }
        for candidate_id in ("cand-a", "cand-b")
    ]
    monkeypatch.setattr(
        meeting_rounds,
        "get_meeting_round",
        lambda _team_id, meeting_id: {"meetingRound": meetings_by_id[meeting_id]},
    )
    monkeypatch.setattr(
        meeting_rounds, "_digests_path", lambda _team_id: Path("digests")
    )
    monkeypatch.setattr(
        meeting_rounds, "_decisions_path", lambda _team_id: Path("decisions")
    )
    monkeypatch.setattr(
        meeting_rounds,
        "_read_jsonl",
        lambda path: digest_rows if str(path) == "digests" else decision_rows,
    )
    return team_id


def _group_payload():
    return {
        "meetingRoundIds": ["meeting-a", "meeting-b"],
        "candidates": [
            {
                "candidateId": "cand-a",
                "claim": "cand-a 的有界代理机制陈述",
                "rationale": "rationale-a",
                "differenceFromAlternatives": "cand-a 走编码器代理路径",
            },
            {
                "candidateId": "cand-b",
                "claim": "cand-b 的解码器容量机制陈述",
                "rationale": "rationale-b",
                "differenceFromAlternatives": "cand-b 走解码器容量路径",
            },
        ],
    }


def _complete_review_output():
    return {
        "candidates": [
            {
                "candidateId": "cand-a",
                "claim": "cand-a 的有界代理机制陈述",
                "rationale": "rationale-a",
                "differenceFromAlternatives": "cand-a 走编码器代理路径",
                "lineageRefs": [],
                "scores": {dim: 0.8 for dim in SCORE_DIMENSIONS},
                "reviewedBy": "agent-coordinator",
                "status": "proposed",
            },
            {
                "candidateId": "cand-b",
                "claim": "cand-b 的解码器容量机制陈述",
                "rationale": "rationale-b",
                "differenceFromAlternatives": "cand-b 走解码器容量路径",
                "lineageRefs": [],
                "scores": {dim: 0.6 for dim in SCORE_DIMENSIONS},
                "reviewedBy": "agent-coordinator",
                "status": "proposed",
            },
        ],
        "pairwiseComparisons": [
            {
                "comparisonId": "cmp-cand-a-cand-b",
                "leftCandidateId": "cand-a",
                "rightCandidateId": "cand-b",
                "reviewerAgentId": "agent-coordinator",
                "outcome": "left_wins",
                "justification": "cand-a 证据更完整",
            }
        ],
        "pareto": {
            "paretoFrontCandidateIds": ["cand-a"],
            "dominatedCandidateIds": ["cand-b"],
            "analystAgentId": "agent-coordinator",
            "notes": "",
        },
        "metaReview": {
            "metaReviewId": "meta-race-1",
            "reviewerAgentId": "agent-coordinator",
            "recommendationCandidateId": "cand-a",
            "rationale": "cand-a 收敛",
            "riskNotes": "",
            "accepted": True,
        },
        "reviewContextId": "ctx-race",
        "executionMode": "dev",
        "positionSeed": "seed",
        "roles": {"metareview": "agent-coordinator"},
        "modelInvocationReceipts": [],
    }


def _patch_review_executor(monkeypatch, review_calls, entered, finish):
    from core.web.services.team_workflow import (
        hypothesis_review_executor,
        research_memory_context,
    )

    def fake_review(context, **kwargs):
        review_calls.append(str(kwargs.get("round_id")))
        entered.set()
        finish.wait(timeout=10)
        return _complete_review_output()

    monkeypatch.setattr(
        research_memory_context,
        "build_hypothesis_review_context",
        lambda **_kwargs: {"contextId": "ctx-race"},
    )
    monkeypatch.setattr(
        hypothesis_review_executor, "execute_hypothesis_review", fake_review
    )


def test_concurrent_group_generation_runs_executor_exactly_once(
    tmp_path, monkeypatch
) -> None:
    """Two aligned triggers for one fan-in group spend the review budget once.

    The loser trigger either reuses the stored round or is rejected with the
    structured in-progress error; it never double-spends the executor and
    never leaves a content-conflict ghost failure trace.
    """
    import threading

    team_id = _race_env(tmp_path, monkeypatch)

    review_calls: list[str] = []
    executor_entered = threading.Event()
    finish_review = threading.Event()
    _patch_review_executor(
        monkeypatch, review_calls, executor_entered, finish_review
    )

    barrier = threading.Barrier(2)
    results: list[dict] = []

    def trigger():
        barrier.wait(timeout=10)
        try:
            results.append(
                hypothesis_rounds_service.generate_hypothesis_round_from_meeting(
                    team_id, "meeting-a", dict(_group_payload())
                )
            )
        except (
            hypothesis_rounds_service.ResearchHypothesisRoundGenerationInProgressError
        ) as exc:
            results.append(
                {"status": "generation_in_progress", "roundId": exc.round_id}
            )

    threads = [threading.Thread(target=trigger) for _ in range(2)]
    for thread in threads:
        thread.start()
    assert executor_entered.wait(timeout=10)
    finish_review.set()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads)
    assert len(results) == 2

    statuses = [str(item.get("status")) for item in results]
    assert statuses.count("created") == 1
    assert set(statuses) <= {"created", "reused", "generation_in_progress"}
    assert len(review_calls) == 1
    assert hypothesis_rounds_service.list_hypothesis_rounds(team_id)[
        "roundCount"
    ] == 1
    failures = hypothesis_rounds_service.list_hypothesis_round_failures(team_id)
    assert failures["failureCount"] == 0
    assert failures["openFailureCount"] == 0


def test_in_flight_generation_rejects_second_trigger_then_reuses(
    tmp_path, monkeypatch
) -> None:
    """A live generation rejects the second trigger; later replays reuse free."""
    import threading

    team_id = _race_env(tmp_path, monkeypatch)

    review_calls: list[str] = []
    executor_entered = threading.Event()
    finish_review = threading.Event()
    _patch_review_executor(
        monkeypatch, review_calls, executor_entered, finish_review
    )

    worker_result: dict = {}
    worker_errors: list[BaseException] = []

    def worker():
        try:
            worker_result.update(
                hypothesis_rounds_service.generate_hypothesis_round_from_meeting(
                    team_id, "meeting-a", dict(_group_payload())
                )
            )
        except BaseException as exc:  # noqa: BLE001 - surfaced by the asserts
            worker_errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    assert executor_entered.wait(timeout=10)

    # While the first generation holds the in-flight slot, the second trigger
    # is rejected fast with the structured error: no executor run, no queuing.
    with pytest.raises(
        hypothesis_rounds_service.ResearchHypothesisRoundGenerationInProgressError
    ) as excinfo:
        hypothesis_rounds_service.generate_hypothesis_round_from_meeting(
            team_id, "meeting-a", dict(_group_payload())
        )
    assert excinfo.value.round_id
    assert excinfo.value.team_id == team_id
    assert len(review_calls) == 1

    finish_review.set()
    thread.join(timeout=30)
    assert not worker_errors
    assert worker_result["status"] == "created"

    # Once the winner stored the round, a replay reuses it with zero
    # additional executor calls (pre-read reuse, not create-time byte match).
    replay = hypothesis_rounds_service.generate_hypothesis_round_from_meeting(
        team_id, "meeting-a", dict(_group_payload())
    )
    assert replay["status"] == "reused"
    assert replay["round"]["roundId"] == worker_result["round"]["roundId"]
    assert replay["closed"] is True
    assert replay["review"]["contextId"] == "ctx-race"
    assert len(review_calls) == 1
    assert hypothesis_rounds_service.list_hypothesis_rounds(team_id)[
        "roundCount"
    ] == 1


def test_run_bound_dev_theme_executes_receipt_bound_review(tmp_path, monkeypatch):
    from core.web.services.team_workflow import meeting_rounds, hypothesis_review_executor
    team_id = _race_env(tmp_path, monkeypatch)
    original_get = meeting_rounds.get_meeting_round
    authority = {"authorityKind": "workflow_run", "workflowRunId": "run-single"}
    def get_meeting(*args, **kwargs):
        result = original_get(*args, **kwargs)
        return {**result, "meetingRound": {**result["meetingRound"], "modelInvocationReceiptAuthority": authority}}
    monkeypatch.setattr(meeting_rounds, "get_meeting_round", get_meeting)
    class ModeCaptured(Exception):
        pass
    def execute(context, **kwargs):
        assert kwargs["execution_mode"] is hypothesis_review_executor.HypothesisReviewExecutionMode.FORMAL
        assert context["_modelInvocationReceiptAuthority"] == authority
        raise ModeCaptured
    monkeypatch.setattr(hypothesis_review_executor, "execute_hypothesis_review", execute)
    with pytest.raises(ModeCaptured):
        hypothesis_rounds_service.generate_hypothesis_round_from_meeting(team_id, "meeting-a", _group_payload())


def test_negative_quality_round_is_persisted_and_reused_without_losing_verdict(tmp_path, monkeypatch):
    team_id = _team(tmp_path, monkeypatch)
    quality = {
        "qualityStatus": "failed", "qualityFailureCode": "coherence_failure",
        "qualityFailureCandidateIds": ["cand-b"],
        "coreHypothesisCoherence": [{"candidateId": "cand-b", "passed": False}],
        "coreHypothesisCoherenceArtifactRef": "artifact:coherence-negative",
    }
    payload = _round_payload(**quality)
    created = hypothesis_rounds_service.create_hypothesis_round(team_id, payload)
    closed = hypothesis_rounds_service.close_hypothesis_round(
        team_id, created["round"]["roundId"], _closure(created["round"]),
    )
    assert closed["round"]["status"] == "closed"
    reused = hypothesis_rounds_service.find_reusable_hypothesis_round(team_id, created["round"]["roundId"])
    assert reused is not None
    for key, value in quality.items():
        assert reused[key] == value


def test_coherence_feedback_candidate_ids_persist_as_recommendation_scoped_feedback(tmp_path, monkeypatch):
    """Recommendation-scoped rounds persist feedback-only candidate ids."""
    team_id = _team(tmp_path, monkeypatch)
    quality = {
        "qualityStatus": "passed", "qualityFailureCode": "",
        "qualityFailureCandidateIds": [],
        "coherenceFeedbackCandidateIds": ["cand-b"],
        "coreHypothesisCoherence": [
            {"candidateId": "cand-a", "passed": True},
            {"candidateId": "cand-b", "passed": False},
        ],
        "coreHypothesisCoherenceArtifactRef": "artifact:coherence-feedback",
    }
    payload = _round_payload(**quality)
    created = hypothesis_rounds_service.create_hypothesis_round(team_id, payload)
    closed = hypothesis_rounds_service.close_hypothesis_round(
        team_id, created["round"]["roundId"], _closure(created["round"]),
    )
    assert closed["round"]["status"] == "closed"
    reused = hypothesis_rounds_service.find_reusable_hypothesis_round(team_id, created["round"]["roundId"])
    assert reused is not None
    for key, value in quality.items():
        assert reused[key] == value


# ---------------------------------------------------------------------------
# additive identity bindings (questionId / workflowRunId)
#
# New round rows carry the owning question id (normalized uppercase) and,
# when the round was generated inside a workflow run, that run id.  Both
# fields are additive: unknown values stay absent, historical rows are never
# rewritten, and no existing reader scopes rounds by them.


def _generate_once(monkeypatch, team_id, payload, meeting_id="meeting-a"):
    """Run one full generation with a fake (zero-cost) review executor."""
    from core.web.services.team_workflow import (
        hypothesis_review_executor,
        research_memory_context,
    )

    monkeypatch.setattr(
        research_memory_context,
        "build_hypothesis_review_context",
        lambda **_kwargs: {"contextId": "ctx-identity"},
    )
    monkeypatch.setattr(
        hypothesis_review_executor,
        "execute_hypothesis_review",
        lambda context, **kwargs: _complete_review_output(),
    )
    return hypothesis_rounds_service.generate_hypothesis_round_from_meeting(
        team_id, meeting_id, dict(payload)
    )


def _with_meeting_extra_field(monkeypatch, extra_by_meeting):
    """Overlay extra fields onto the fan-in meetings served by _race_env."""
    from core.web.services.team_workflow import meeting_rounds

    original_get = meeting_rounds.get_meeting_round

    def get_meeting(*args, **kwargs):
        result = original_get(*args, **kwargs)
        meeting_id = str((result.get("meetingRound") or {}).get("meetingRoundId") or "")
        extra = extra_by_meeting.get(meeting_id)
        if not extra:
            return result
        return {
            **result,
            "meetingRound": {**result["meetingRound"], **extra},
        }

    monkeypatch.setattr(meeting_rounds, "get_meeting_round", get_meeting)


def test_generated_round_carries_question_id_and_workflow_run_id(
    tmp_path, monkeypatch
) -> None:
    """A round generated inside a workflow run binds questionId + run id."""
    team_id = _race_env(tmp_path, monkeypatch)
    _with_meeting_extra_field(
        monkeypatch,
        {
            "meeting-a": {"discussionScope": {"workflowRunId": "run-fanin-1"}},
            "meeting-b": {"discussionScope": {"workflowRunId": "run-fanin-1"}},
        },
    )

    result = _generate_once(monkeypatch, team_id, _group_payload())

    assert result["status"] == "created"
    stored = hypothesis_rounds_service.find_reusable_hypothesis_round(
        team_id, result["round"]["roundId"]
    )
    assert stored is not None
    assert stored["questionId"] == "SCI-091"
    assert stored["workflowRunId"] == "run-fanin-1"


def test_generated_round_without_a_workflow_run_carries_question_id_only(
    tmp_path, monkeypatch
) -> None:
    """Dev/chain-only generation binds questionId; no run id is invented."""
    team_id = _race_env(tmp_path, monkeypatch)

    result = _generate_once(monkeypatch, team_id, _group_payload())

    assert result["status"] == "created"
    stored = hypothesis_rounds_service.find_reusable_hypothesis_round(
        team_id, result["round"]["roundId"]
    )
    assert stored is not None
    assert stored["questionId"] == "SCI-091"
    assert "workflowRunId" not in stored


def test_generation_refuses_meetings_from_different_workflow_runs(
    tmp_path, monkeypatch
) -> None:
    """Disagreeing run identities across the fan-in fail closed unbound."""
    team_id = _race_env(tmp_path, monkeypatch)
    _with_meeting_extra_field(
        monkeypatch,
        {
            "meeting-a": {"discussionScope": {"workflowRunId": "run-1"}},
            "meeting-b": {"discussionScope": {"workflowRunId": "run-2"}},
        },
    )

    with pytest.raises(
        hypothesis_rounds_service.ResearchHypothesisRoundError
    ) as excinfo:
        _generate_once(monkeypatch, team_id, _group_payload())
    assert "different workflow runs" in str(excinfo.value)
    assert (
        hypothesis_rounds_service.list_hypothesis_rounds(team_id)["roundCount"] == 0
    )


def test_create_round_binds_question_id_only_when_known(tmp_path, monkeypatch) -> None:
    """Direct creates bind the normalized questionId; absent keys stay absent."""
    team_id = _team(tmp_path, monkeypatch)

    with_run = hypothesis_rounds_service.create_hypothesis_round(
        team_id,
        _round_payload(questionId="sci-091", workflowRunId="run-create-1"),
    )
    assert with_run["round"]["questionId"] == "SCI-091"
    assert with_run["round"]["workflowRunId"] == "run-create-1"

    question_only = hypothesis_rounds_service.create_hypothesis_round(
        team_id,
        _round_payload(roundId="hround-test-question-only", questionId="SCI-091"),
    )
    assert question_only["round"]["questionId"] == "SCI-091"
    assert "workflowRunId" not in question_only["round"]

    legacy_shape = hypothesis_rounds_service.create_hypothesis_round(
        team_id,
        _round_payload(roundId="hround-test-legacy-shape"),
    )
    assert "questionId" not in legacy_shape["round"]
    assert "workflowRunId" not in legacy_shape["round"]


def test_closure_copy_carries_identity_bindings(tmp_path, monkeypatch) -> None:
    """Closing a round appends the closure copy with the bindings intact."""
    team_id = _team(tmp_path, monkeypatch)
    created = hypothesis_rounds_service.create_hypothesis_round(
        team_id,
        _round_payload(questionId="sci-091", workflowRunId="run-create-1"),
    )

    closed = hypothesis_rounds_service.close_hypothesis_round(
        team_id, created["round"]["roundId"], _closure(created["round"])
    )

    assert closed["round"]["questionId"] == "SCI-091"
    assert closed["round"]["workflowRunId"] == "run-create-1"


def test_round_stored_without_identity_fields_still_reuses_across_binding(
    tmp_path, monkeypatch
) -> None:
    """The derived binding never flips append-only id reuse (historical rows)."""
    team_id = _team(tmp_path, monkeypatch)
    # Deterministic metaReview: the default embeds createdAt, which would
    # conflict on any re-presentation regardless of identity bindings.
    fixed_meta_review = {
        "metaReviewId": "meta-historical-1",
        "reviewerAgentId": "agent-meta",
        "recommendationCandidateId": "",
        "rationale": "",
        "riskNotes": "",
        "accepted": False,
    }

    # Historical shape: the request carries no identity fields, so the stored
    # row has neither key — exactly like the pre-binding production rows.
    historical = hypothesis_rounds_service.create_hypothesis_round(
        team_id, _round_payload(metaReview=fixed_meta_review)
    )
    assert "questionId" not in historical["round"]

    # Re-presenting the same round id with the now-derived binding must reuse
    # the stored row instead of failing with a content conflict.
    reused = hypothesis_rounds_service.create_hypothesis_round(
        team_id,
        _round_payload(
            metaReview=fixed_meta_review,
            questionId="SCI-091",
            workflowRunId="run-late-1",
        ),
    )
    assert reused["status"] == "reused"
    assert "questionId" not in reused["round"]
    assert "workflowRunId" not in reused["round"]
    assert (
        hypothesis_rounds_service.list_hypothesis_rounds(team_id)["roundCount"] == 1
    )
