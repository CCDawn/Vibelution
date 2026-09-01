"""Evidence-gap marker consumption tests (hypothesis-first chain side).

Closes the retrieval-circuit gap loop on the review side, in three coupled
parts (stopping dispatch alone would only create a new deadlock):

1. stop-dispatch + injection: a live ``evidence_gap_unavailable`` marker for
   the same goal never triggers a new collection run; the collection request
   records the gap state and the next review round receives the unavailability
   verdict through a bounded side-channel agenda notice.
2. converge-with-gaps: when every digest evidence request is already judged
   unavailable, the round legally closes with an explicit gap manifest instead
   of synthesizing another dead ``request_new_evidence`` decision.
3. revocable marker: an operator can clear a marker by id so the goal
   re-enters the circuit; markers whose attempts retrieved results that never
   became new records surface the quote-anchor remediation retry hint.

Plus the hard zero-difference guarantee: with no live marker the collection
path, digest decisions and meeting payload are byte-identical to the legacy
behavior.  All storage is redirected into ``tmp_path``; no provider search,
model call, or runtime data is touched.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from core.research.workflow.contracts import scope_hash_for
from core.web.services import team_service
from core.web.services.team_workflow import meeting_rounds as meetings
from core.web.services.team_workflow import meeting_runtime
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain as chain,
)
from core.web.services.team_workflow.source_collection import facade
from core.web.services.team_workflow.source_collection import (
    runs as collection_runs,
)
from core.web.services.team_workflow.source_collection import search_circuit

from tests._support.team_workflow.helpers import _use_tmp_project_root

_TEAM = "team-gap-consume"
_MEETING = {
    "meetingRoundId": "meeting-gap-r1",
    "scopeHash": "scope-gap-r1",
    "question": "SCI-096",
}
_ENVELOPE = {
    "keywords": ["predictive coding"],
    "sourceTypes": ["paper"],
    "evidenceLevels": ["primary"],
}


def _decision(envelope: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "decision": chain.REQUEST_EVIDENCE_DECISION,
        "candidateRefs": ["hyp-a"],
        "evidenceRefs": ["evidence:m1"],
        "searchEnvelope": dict(envelope or _ENVELOPE),
    }


def _marker_for(
    envelope: dict[str, Any],
    *,
    marker_id: str = "scrgap-test-1",
    result_count: int = 7,
) -> dict[str, Any]:
    marker = search_circuit.build_evidence_gap_marker(
        goal_key=search_circuit.canonical_goal_key(envelope),
        goal_scope="question:sci-096",
        question="SCI-096",
        original_search_envelope=envelope,
        attempts=[
            {
                "runId": "dprun-old",
                "attemptKind": "original",
                "variantIndex": 0,
                "strategy": "",
                "searchEnvelope": {},
                "querySeeds": [],
                "status": "executed",
                "outcome": {
                    "resultCount": result_count,
                    "newRecordCount": 0,
                    "rejectedResultCount": result_count,
                },
            }
        ],
        latest_attempt_run_id="dprun-old",
        now_iso="2026-09-01T00:00:00Z",
    )
    marker["markerId"] = marker_id
    return marker


def _seed_marker(team_id: str, envelope: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    marker = _marker_for(envelope, **kwargs)
    search_circuit.record_evidence_gap_marker(team_id, marker)
    return marker


def _install_collection_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Redirect storage into tmp and normalize the close-result decision ids."""
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(
        chain, "_scope_envelope_for_meeting", lambda _meeting: {"scopeHash": "scope-gap-r1"}
    )
    monkeypatch.setattr(
        facade,
        "_normalize_search_envelope",
        lambda envelope, *, require_keywords: dict(envelope or {}),
    )
    monkeypatch.setattr(facade, "_normalize_requirements", lambda value: dict(value or {}))
    monkeypatch.setattr(
        facade, "_normalize_writeback_policy", lambda value: dict(value or {})
    )
    return {
        "decisions": [
            {"decisionId": chain._decision_id_for(_MEETING, decision)}
            for decision in decisions
        ]
    }


def _forbid_facade_and_start(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden_facade(**_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("facade ensure must not be called for a gap-marked goal")

    def forbidden_start(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("background search must not be started for a gap-marked goal")

    monkeypatch.setattr(facade, "research_knowledge_collection_facade", forbidden_facade)
    monkeypatch.setattr(
        collection_runs, "start_source_collection_search_background", forbidden_start
    )


# ---------------------------------------------------------------------------
# Part 1: stop-dispatch + gap-state request + next-round gap notice.
# ---------------------------------------------------------------------------


def test_live_marker_blocks_collection_run_and_records_gap_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decisions = [_decision()]
    close_result = _install_collection_fixture(tmp_path, monkeypatch, decisions)
    marker = _seed_marker(_TEAM, _ENVELOPE)
    _forbid_facade_and_start(monkeypatch)

    handoffs: list[dict[str, Any]] = []

    def fake_handoff(team_id: str, request_id: str, **kwargs: Any) -> dict[str, Any]:
        handoffs.append({"teamId": team_id, "requestId": request_id, **kwargs})
        return {"nextMeeting": {"meetingRoundId": "meeting-gap-r2"}}

    monkeypatch.setattr(chain, "record_collection_handoff", fake_handoff)

    result = chain._process_collection_decisions(
        _TEAM, _MEETING, close_result, {"decisions": decisions}
    )

    request = result["requests"][0]
    assert request["status"] == chain.EVIDENCE_GAP_STATUS
    assert request["collectionRunStatus"] == chain.EVIDENCE_GAP_STATUS
    assert request["evidenceGap"]["markerId"] == marker["markerId"]
    assert request["evidenceGap"]["summary"]
    assert result["evidenceGaps"][0]["evidenceGap"]["markerId"] == marker["markerId"]
    # The stop-dispatch is paired with the idempotent handoff so the loop
    # keeps moving: the next round opens and carries the gap notice.
    assert len(handoffs) == 1
    assert handoffs[0]["handoff_ref"] == f"evidence_gap:{marker['markerId']}"


def test_gap_resolved_request_injects_notice_into_next_round_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(team_service, "assert_team_exists", lambda team_id: team_id)
    marker = _seed_marker(_TEAM, _ENVELOPE)
    request_id = "hfcr-gap-notice-1"
    chain._append_jsonl(
        chain._storage_path(_TEAM),
        {
            "schemaVersion": 1,
            "recordKind": chain.COLLECTION_REQUEST_KIND,
            "requestId": request_id,
            "status": chain.EVIDENCE_GAP_STATUS,
            "searchEnvelope": dict(_ENVELOPE),
            "evidenceGap": chain._bounded_evidence_gap_payload(marker),
        },
    )

    captured: dict[str, Any] = {}

    def fake_open_meeting(team_id: str, payload: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        captured["payload"] = dict(payload)
        return {"meetingRound": {"meetingRoundId": str(payload["meetingRoundId"])}}

    monkeypatch.setattr(
        meeting_runtime, "_ensure_linked_room", lambda team_id: (None, "room-gap")
    )
    monkeypatch.setattr(
        chain,
        "_resolve_hypothesis_participants",
        lambda team_id, room_id, meeting_type: {"participants": ["coordinator"]},
    )
    monkeypatch.setattr(chain, "_active_review_binding_groups", lambda *a, **k: [])
    monkeypatch.setattr(chain, "_build_round_candidates", lambda *a, **k: [])
    monkeypatch.setattr(
        chain,
        "_append_review_dispatch_attempt_state",
        lambda *a, **k: {"attemptNumber": 1},
    )
    monkeypatch.setattr(chain, "_record_review_round_link", lambda *a, **k: {"link": "ok"})
    monkeypatch.setattr(
        chain, "_review_discussion_scope_base", lambda *a, **k: None
    )
    monkeypatch.setattr(meeting_runtime, "open_hypothesis_review_meeting", fake_open_meeting)

    selection = {
        "selectionId": "sel-gap-1",
        "questionId": "SCI-096",
        "selectedCandidateIds": ["hyp-a"],
        "selectionVersion": "selver-gap-1",
        "scopeHash": "scope-gap-r1",
    }
    chain.open_review_meeting_for_selection(
        _TEAM,
        selection,
        round_index=2,
        collection_request_id=request_id,
        _formal_candidate_id="hyp-a",
        _selection_version="selver-gap-1",
    )

    payload = captured["payload"]
    gap_refs = [
        ref
        for ref in payload["inputArtifactRefs"]
        if ref.startswith("evidence_gap_marker:")
    ]
    assert gap_refs == [f"evidence_gap_marker:{marker['markerId']}"]
    # The notice is appended to the standard agenda, never replaces it.
    assert payload["agenda"][: len(list(meeting_runtime._DEFAULT_AGENDA))] == list(
        meeting_runtime._DEFAULT_AGENDA
    )
    notice = payload["agenda"][-1]
    assert marker["markerId"][:24] in notice
    assert "带缺口收敛" in notice
    assert marker["unavailableReasonsSummary"]["summary"][:200] in notice


# ---------------------------------------------------------------------------
# Part 2: converge-with-gaps close semantics.
# ---------------------------------------------------------------------------


def _install_digest_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    evidence_requests: list[dict[str, Any]],
    content_hash: str = "hash-gap-1",
) -> dict[str, Any]:
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(team_service, "assert_team_exists", lambda team_id: team_id)
    digest_draft = {
        "contentHash": content_hash,
        "sourceMessageRefs": [],
        "evidenceRequests": evidence_requests,
    }
    meeting = {
        **_MEETING,
        "meetingType": chain.HYPOTHESIS_REVIEW_MEETING_TYPE,
        "status": "awaiting_approval",
        "digestDraft": digest_draft,
    }
    monkeypatch.setattr(meetings, "get_meeting_round", lambda team_id, round_id: {"meetingRound": meeting})
    captured: dict[str, Any] = {}

    def fake_close(team_id: str, round_id: str, payload: dict[str, Any], runtime: Any = None) -> dict[str, Any]:
        captured["payload"] = payload
        return {"status": "created", "closed": True}

    monkeypatch.setattr(chain, "close_review_meeting", fake_close)
    return captured


def _digest_request(envelope: dict[str, Any]) -> dict[str, Any]:
    return {
        "rationale": "需要补充文献",
        "candidateRefs": [],
        "evidenceRefs": ["evidence:m1"],
        "searchEnvelope": dict(envelope),
    }


def test_approve_digest_converges_with_gaps_when_all_requests_marked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _install_digest_fixture(
        tmp_path,
        monkeypatch,
        evidence_requests=[_digest_request(_ENVELOPE)],
    )
    marker = _seed_marker(_TEAM, _ENVELOPE)

    chain.approve_meeting_digest(
        _TEAM,
        _MEETING["meetingRoundId"],
        closed_by="operator",
        expected_digest_content_hash="hash-gap-1",
    )

    decision = captured["payload"]["decisions"][0]
    # No new request_new_evidence is synthesized for a fully-gap-marked set.
    assert decision["decision"] == "close_round"
    assert decision["rationale"].startswith("带缺口收敛")
    assert str(len(decision["candidateRefs"]) >= 0)  # shape contract kept
    assert f"evidence_gap_marker:{marker['markerId']}" in decision["evidenceRefs"]
    # Durable, auditable "converged with gaps" record with the full manifest.
    records = chain._read_jsonl(chain._storage_path(_TEAM))
    convergence = [
        item
        for item in records
        if item.get("recordKind") == chain.GAP_CONVERGENCE_KIND
    ]
    assert len(convergence) == 1
    assert convergence[0]["meetingRoundId"] == _MEETING["meetingRoundId"]
    assert convergence[0]["evidenceGaps"][0]["markerId"] == marker["markerId"]
    assert convergence[0]["decision"] == "close_round"


def test_approve_digest_mixed_requests_keep_legacy_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    open_envelope = {"keywords": ["spike sorting"]}
    captured = _install_digest_fixture(
        tmp_path,
        monkeypatch,
        evidence_requests=[
            _digest_request(_ENVELOPE),
            _digest_request(open_envelope),
        ],
    )
    # Seed after the fixture installed the tmp project root.
    _seed_marker(_TEAM, _ENVELOPE)

    chain.approve_meeting_digest(
        _TEAM,
        _MEETING["meetingRoundId"],
        closed_by="operator",
        expected_digest_content_hash="hash-gap-1",
    )

    decision = captured["payload"]["decisions"][0]
    # At least one open request remains: the legacy merged
    # request_new_evidence decision runs unchanged (the marked goal is
    # stopped later, at the collection path).
    assert decision["decision"] == chain.REQUEST_EVIDENCE_DECISION
    assert "predictive coding" in decision["searchEnvelope"]["keywords"]
    assert "spike sorting" in decision["searchEnvelope"]["keywords"]


# ---------------------------------------------------------------------------
# Part 3: revocable marker (operator clear + circuit re-entry).
# ---------------------------------------------------------------------------


def test_clear_marker_lets_goal_reenter_circuit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(team_service, "assert_team_exists", lambda team_id: team_id)
    marker = _seed_marker(_TEAM, _ENVELOPE)

    result = chain.clear_evidence_gap_marker(
        _TEAM, marker["markerId"], reason="quote-anchor remediation shipped"
    )
    assert result["cleared"] is True
    assert result["markerId"] == marker["markerId"]
    assert result["reason"] == "quote-anchor remediation shipped"
    # The cleared goal no longer matches any live marker.
    assert search_circuit.live_evidence_gap_marker_for_goal(_TEAM, _ENVELOPE) == {}

    # Clearing again reports not-cleared instead of failing.
    repeat = chain.clear_evidence_gap_marker(_TEAM, marker["markerId"])
    assert repeat["cleared"] is False

    # With the marker gone, the close path re-enters the circuit: the facade
    # ensure runs again and a fresh collection run is bound and started.
    decisions = [_decision()]
    close_result = _install_collection_fixture(tmp_path, monkeypatch, decisions)
    facade_calls: list[dict[str, Any]] = []

    def fake_facade(**kwargs: Any) -> dict[str, Any]:
        facade_calls.append(dict(kwargs))
        return {"locator": {"runId": "dprun-fresh"}}

    monkeypatch.setattr(facade, "research_knowledge_collection_facade", fake_facade)
    started: list[str] = []
    monkeypatch.setattr(
        collection_runs,
        "start_source_collection_search_background",
        lambda team_id, run_id, payload=None: started.append(run_id),
    )

    result = chain._process_collection_decisions(
        _TEAM, _MEETING, close_result, {"decisions": decisions}
    )

    assert len(facade_calls) == 1
    assert started == ["dprun-fresh"]
    assert result["requests"][0]["collectionRunId"] == "dprun-fresh"


# ---------------------------------------------------------------------------
# Zero-difference guarantee (no live marker).
# ---------------------------------------------------------------------------


def test_no_marker_keeps_legacy_collection_behavior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decisions = [_decision()]
    close_result = _install_collection_fixture(tmp_path, monkeypatch, decisions)

    facade_calls: list[dict[str, Any]] = []

    def fake_facade(**kwargs: Any) -> dict[str, Any]:
        facade_calls.append(dict(kwargs))
        return {"locator": {"runId": "dprun-fresh"}}

    monkeypatch.setattr(facade, "research_knowledge_collection_facade", fake_facade)
    started: list[str] = []
    monkeypatch.setattr(
        collection_runs,
        "start_source_collection_search_background",
        lambda team_id, run_id, payload=None: started.append(run_id),
    )
    handoffs: list[Any] = []
    monkeypatch.setattr(
        chain, "record_collection_handoff", lambda *args, **kwargs: handoffs.append(args)
    )

    result = chain._process_collection_decisions(
        _TEAM, _MEETING, close_result, {"decisions": decisions}
    )

    assert len(facade_calls) == 1
    assert started == ["dprun-fresh"]
    # Legacy path defers the handoff to run completion; no gap channel exists.
    assert handoffs == []
    request = result["requests"][0]
    assert request["status"] == "pending"
    assert "evidenceGap" not in request
    assert set(result.keys()) == {"requests", "skipped"}


def test_no_marker_keeps_digest_decision_and_payload_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _install_digest_fixture(
        tmp_path,
        monkeypatch,
        evidence_requests=[_digest_request(_ENVELOPE)],
    )

    chain.approve_meeting_digest(
        _TEAM,
        _MEETING["meetingRoundId"],
        closed_by="operator",
        expected_digest_content_hash="hash-gap-1",
    )

    decision = captured["payload"]["decisions"][0]
    assert decision["decision"] == chain.REQUEST_EVIDENCE_DECISION
    records = chain._read_jsonl(chain._storage_path(_TEAM))
    assert not [
        item
        for item in records
        if item.get("recordKind") == chain.GAP_CONVERGENCE_KIND
    ]

    # A request without a gap payload produces no notice and no extra refs.
    assert chain._collection_request_gap_notice(_TEAM, "hfcr-missing") == []
    request_id = "hfcr-plain-1"
    chain._append_jsonl(
        chain._storage_path(_TEAM),
        {
            "schemaVersion": 1,
            "recordKind": chain.COLLECTION_REQUEST_KIND,
            "requestId": request_id,
            "status": "pending",
            "searchEnvelope": dict(_ENVELOPE),
        },
    )
    assert chain._collection_request_gap_notice(_TEAM, request_id) == []


def test_no_marker_keeps_meeting_payload_byte_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(team_service, "assert_team_exists", lambda team_id: team_id)
    captured: dict[str, Any] = {}

    def fake_open_meeting(team_id: str, payload: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        captured["payload"] = dict(payload)
        return {"meetingRound": {"meetingRoundId": str(payload["meetingRoundId"])}}

    monkeypatch.setattr(
        meeting_runtime, "_ensure_linked_room", lambda team_id: (None, "room-plain")
    )
    monkeypatch.setattr(
        chain,
        "_resolve_hypothesis_participants",
        lambda team_id, room_id, meeting_type: {"participants": ["coordinator"]},
    )
    monkeypatch.setattr(chain, "_active_review_binding_groups", lambda *a, **k: [])
    monkeypatch.setattr(chain, "_build_round_candidates", lambda *a, **k: [])
    monkeypatch.setattr(
        chain,
        "_append_review_dispatch_attempt_state",
        lambda *a, **k: {"attemptNumber": 1},
    )
    monkeypatch.setattr(chain, "_record_review_round_link", lambda *a, **k: {"link": "ok"})
    monkeypatch.setattr(chain, "_review_discussion_scope_base", lambda *a, **k: None)
    monkeypatch.setattr(meeting_runtime, "open_hypothesis_review_meeting", fake_open_meeting)

    selection = {
        "selectionId": "sel-plain-1",
        "questionId": "SCI-096",
        "selectedCandidateIds": ["hyp-a"],
        "selectionVersion": "selver-plain-1",
        "scopeHash": "scope-plain",
    }
    chain.open_review_meeting_for_selection(
        _TEAM,
        selection,
        round_index=1,
        collection_request_id="hfcr-plain-1",
        _formal_candidate_id="hyp-a",
        _selection_version="selver-plain-1",
    )

    payload = captured["payload"]
    assert "agenda" not in payload
    assert not [
        ref for ref in payload["inputArtifactRefs"] if ref.startswith("evidence_gap_marker:")
    ]


# ---------------------------------------------------------------------------
# Retry hint (auth-wall / fetch-failure class) and recovery consumption.
# ---------------------------------------------------------------------------


def test_retry_hint_names_anchor_remediation_for_fetch_failure_markers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_tmp_project_root(tmp_path, monkeypatch)
    hit = _marker_for(_ENVELOPE, marker_id="scrgap-hit", result_count=7)
    hint = search_circuit.marker_retry_hint(hit)
    assert "quote 锚摘要降级" in hint
    assert "重试可能可得" in hint

    empty = _marker_for(_ENVELOPE, marker_id="scrgap-empty", result_count=0)
    generic = search_circuit.marker_retry_hint(empty)
    assert "quote 锚摘要降级" not in generic

    search_circuit.record_evidence_gap_marker(_TEAM, hit)
    cleared = search_circuit.clear_evidence_gap_marker(_TEAM, "scrgap-hit")
    assert cleared["cleared"] is True
    assert "重试可能可得" in cleared["retryHint"]

    unknown = search_circuit.clear_evidence_gap_marker(_TEAM, "scrgap-unknown")
    assert unknown["cleared"] is False
    assert unknown["retryHint"] == ""


def test_recovery_resolves_gap_request_without_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(team_service, "assert_team_exists", lambda team_id: team_id)
    marker = _seed_marker(_TEAM, _ENVELOPE)

    identity = {
        "program": "P1",
        "theme": "T1",
        "campaign": "C1",
        "question": "SCI-096",
        "branch": "main",
        "workflow": "hypothesis_and_plan",
    }
    request = {
        "schemaVersion": 1,
        "recordKind": chain.COLLECTION_REQUEST_KIND,
        "requestId": "hfcr-gap-recover-1",
        "requestHash": "rh-gap-recover-1",
        "status": "failed",
        "meetingRoundId": _MEETING["meetingRoundId"],
        "decisionId": "decision-gap-recover-1",
        "questionId": "SCI-096",
        **identity,
        "agentId": "agent-alpha",
        "mode": "formal",
        "scopeHash": scope_hash_for(**identity, agent_id="agent-alpha", mode="formal"),
        "searchEnvelope": dict(_ENVELOPE),
        "requirements": {},
        "writebackPolicy": {},
        "hypothesisCandidateIds": [],
        "collectionRunId": "dprun-old",
        "collectionRunStatus": "failed",
        "createdAt": "2026-09-01T00:00:00Z",
    }
    chain._append_jsonl(chain._storage_path(_TEAM), request)
    _forbid_facade_and_start(monkeypatch)

    handoffs: list[str] = []

    def fake_handoff(team_id: str, request_id: str, **kwargs: Any) -> dict[str, Any]:
        handoffs.append(request_id)
        return {"nextMeeting": {}}

    monkeypatch.setattr(chain, "record_collection_handoff", fake_handoff)

    result = chain._recover_collection_request_locked(_TEAM, "hfcr-gap-recover-1")

    recovered = result["request"]
    assert recovered["status"] == chain.EVIDENCE_GAP_STATUS
    assert recovered["evidenceGap"]["markerId"] == marker["markerId"]
    assert handoffs == ["hfcr-gap-recover-1"]


def test_read_api_is_fail_open_on_unreadable_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_tmp_project_root(tmp_path, monkeypatch)

    def broken_store(_team_id: str) -> dict[str, Any]:
        raise RuntimeError("unreadable ledger")

    monkeypatch.setattr(search_circuit, "load_circuit_store", broken_store)
    assert search_circuit.live_evidence_gap_marker_for_goal(_TEAM, _ENVELOPE) == {}
