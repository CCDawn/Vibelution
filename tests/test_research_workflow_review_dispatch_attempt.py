"""Durable per-candidate review-dispatch attempts: writing and projection.

Fan-out intents must survive a refresh: every candidate gets a
``review_dispatch_attempt`` queued before its meeting side effect and a
terminal transition after it, so a failed or interrupted dispatch stays
explainable in the V2 snapshot instead of collapsing into an opaque
"review_dispatch_missing" block.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.web.services.team_workflow import hypothesis_selection as selections
from core.web.services.team_workflow import meeting_rounds as meetings
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain as chain,
)
from core.web.services.team_workflow.research_runtime.hypothesis_first_state_v2 import (
    project_state_from_records,
)
from tests._support.team_workflow.helpers import _use_tmp_project_root


def _fresh_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _fanout_env(tmp_path, monkeypatch, *, open_meeting=None):
    """Patch fan-out surroundings; attempts hit the real JSONL ledger."""
    from core.web.services import team_service
    from core.web.services.team_workflow import meeting_runtime
    from core.web.services.team_workflow.research_runtime import (
        meeting_receipt_authority,
    )

    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(chain, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(meetings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(selections, "PROJECT_ROOT", tmp_path)
    team_id = "team-dispatch-attempt"
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(
        meeting_receipt_authority,
        "resolve_active_question_authority",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        meetings,
        "get_meeting_round",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            meetings.ResearchMeetingRoundNotFoundError("missing")
        ),
    )
    monkeypatch.setattr(
        meeting_runtime,
        "_ensure_linked_room",
        lambda value: ({"teamId": value}, "team-room"),
    )
    monkeypatch.setattr(
        chain,
        "_resolve_hypothesis_participants",
        lambda *_args: {"participants": ["agent-a"]},
    )
    monkeypatch.setattr(
        chain,
        "_build_round_candidates",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        chain,
        "list_hypothesis_candidates",
        lambda *_args, **_kwargs: {"candidates": []},
    )

    def default_open(_team_id, payload, **_kwargs):
        return {
            "status": "created",
            "meetingRound": {"meetingRoundId": payload["meetingRoundId"]},
            "roomId": "team-room",
            "roundId": f"round-{payload['candidateId']}",
            "chatRoomRoundIds": [f"round-{payload['candidateId']}"],
        }

    monkeypatch.setattr(
        meeting_runtime, "open_hypothesis_review_meeting", open_meeting or default_open
    )
    return team_id


def _selection_payload(**overrides):
    payload = {
        "program": "XH-202619",
        "theme": "theme-1",
        "campaign": "campaign-1",
        "question": "SCI-096",
        "branch": "main",
        "workflow": "hypothesis_and_plan",
        "agentId": "agent-a",
        "mode": "formal",
        "questionId": "SCI-096",
        "selectedCandidateIds": ["hyp-a", "hyp-b"],
        "decidedBy": "agent-a",
    }
    payload.update(overrides)
    return payload


def _persist_selection(team_id: str, selection_id: str = "selection-dispatch-1") -> dict:
    record = {
        "schemaVersion": 1,
        "selectionId": selection_id,
        "program": "XH-202619",
        "theme": "theme-1",
        "campaign": "campaign-1",
        "question": "SCI-096",
        "branch": "main",
        "workflow": "hypothesis_and_plan",
        "agentId": "agent-a",
        "mode": "formal",
        "scopeHash": "scope-hash",
        "questionId": "SCI-096",
        "selectedCandidateIds": ["hyp-a", "hyp-b"],
        "previousSelectionId": "",
        "decidedBy": "agent-a",
        "selectionHash": f"hash-{selection_id}",
        "createdAt": "2026-08-26T00:00:00Z",
    }
    selections._append_jsonl(selections._storage_path(team_id), record)
    return record


def _chain_records(team_id: str) -> list[dict]:
    return chain._read_jsonl(chain._storage_path(team_id))


def _attempts(team_id: str) -> list[dict]:
    return [
        dict(record)
        for record in chain.list_review_dispatch_attempts(team_id)["attempts"]
    ]


def _project(team_id: str, selection: dict, meeting_records: list[dict]) -> dict:
    return project_state_from_records(
        team_id=team_id,
        question_id="SCI-096",
        reset_boundary=None,
        chain_records=_chain_records(team_id),
        selection_records=[dict(selection)],
        meeting_records=meeting_records,
        digest_records=[],
        decision_records=[],
        hypothesis_round_records=[],
        return_to="/return",
    )


def test_fanout_records_completed_attempt_per_candidate(tmp_path, monkeypatch) -> None:
    team_id = _fanout_env(tmp_path, monkeypatch)
    selection = _persist_selection(team_id)

    result = chain.open_review_meeting_for_selection(
        team_id, selection, background=False
    )

    assert result["candidateCount"] == 2
    attempts = _attempts(team_id)
    assert len(attempts) == 2
    by_candidate = {item["candidateId"]: item for item in attempts}
    for candidate_id in ("hyp-a", "hyp-b"):
        attempt = by_candidate[candidate_id]
        assert attempt["lifecycle"] == "completed"
        assert attempt["outcome"] == "succeeded"
        assert attempt["attemptNumber"] == 1
        assert attempt["selectionId"] == "selection-dispatch-1"
        assert attempt["roundIndex"] == 1
        assert attempt["meetingRoundId"].startswith("hf-review-selection-dispatch-1-")


def test_failed_candidate_keeps_durable_error_and_projects_retry(
    tmp_path, monkeypatch
) -> None:

    def flaky_open(_team_id, payload, **_kwargs):
        if payload.get("candidateId") == "hyp-b":
            raise RuntimeError("room backend unavailable")
        return {
            "status": "created",
            "meetingRound": {"meetingRoundId": payload["meetingRoundId"]},
            "roomId": "team-room",
            "roundId": f"round-{payload['candidateId']}",
            "chatRoomRoundIds": [f"round-{payload['candidateId']}"],
        }

    team_id = _fanout_env(tmp_path, monkeypatch, open_meeting=flaky_open)
    selection = _persist_selection(team_id)

    with pytest.raises(RuntimeError, match="room backend unavailable"):
        chain.open_review_meeting_for_selection(team_id, selection, background=False)

    attempts = {item["candidateId"]: item for item in _attempts(team_id)}
    assert attempts["hyp-a"]["lifecycle"] == "completed"
    assert attempts["hyp-b"]["lifecycle"] == "failed"
    assert "room backend unavailable" in attempts["hyp-b"]["error"]
    assert attempts["hyp-b"]["errorType"] == "RuntimeError"

    succeeded_meeting = {
        "meetingRoundId": attempts["hyp-a"]["meetingRoundId"],
        "meetingType": "hypothesis_review",
        "question": "SCI-096",
        "selectionId": "selection-dispatch-1",
        "status": "open",
        "linkedChatRoomId": "team-room",
        # Fresh on purpose: this fixture models a healthy live discussion,
        # not a heartbeat-stale one (see test_hypothesis_first_state_v2).
        "createdAt": _fresh_iso(),
    }
    state = _project(team_id, selection, [succeeded_meeting])

    by_candidate = {item["candidateId"]: item for item in state["review"]["candidates"]}
    assert by_candidate["hyp-a"]["lifecycle"] == "running"
    assert by_candidate["hyp-b"]["lifecycle"] == "failed"
    assert by_candidate["hyp-b"]["actionability"] == "available"
    problems = by_candidate["hyp-b"]["problems"]
    assert [problem["code"] for problem in problems] == ["review_dispatch_failed"]
    assert "room backend unavailable" in problems[0]["message"]
    assert by_candidate["hyp-b"]["attempt"]["number"] == 1

    aggregate = state["review"]["aggregate"]
    assert aggregate == {"total": 2, "completed": 0, "pending": 1, "failed": 1, "blocked": 0, "superseded": 0}
    assert state["review"]["lifecycle"] == "failed"
    assert state["review"]["actionability"] == "available"

    retry_actions = [
        action
        for action in state["allowedActions"]
        if action.get("command") == "retry_review_dispatch"
    ]
    assert len(retry_actions) == 1
    assert retry_actions[0]["payload"]["candidateIds"] == ["hyp-b"]


def test_retry_bumps_attempt_number_and_recovers(tmp_path, monkeypatch) -> None:

    state = {"fail_hyp_b": True}

    def recoverable_open(_team_id, payload, **_kwargs):
        if payload.get("candidateId") == "hyp-b" and state["fail_hyp_b"]:
            raise RuntimeError("transient dispatch failure")
        return {
            "status": "created",
            "meetingRound": {"meetingRoundId": payload["meetingRoundId"]},
            "roomId": "team-room",
            "roundId": f"round-{payload['candidateId']}",
            "chatRoomRoundIds": [f"round-{payload['candidateId']}"],
        }

    team_id = _fanout_env(tmp_path, monkeypatch, open_meeting=recoverable_open)
    selection = _persist_selection(team_id)

    with pytest.raises(RuntimeError, match="transient dispatch failure"):
        chain.open_review_meeting_for_selection(team_id, selection, background=False)

    state["fail_hyp_b"] = False
    chain.retry_review_dispatch(team_id, "selection-dispatch-1", ["hyp-b"])

    attempts = {item["candidateId"]: item for item in _attempts(team_id)}
    assert attempts["hyp-a"]["attemptNumber"] == 1
    assert attempts["hyp-a"]["lifecycle"] == "completed"
    assert attempts["hyp-b"]["attemptNumber"] == 2
    assert attempts["hyp-b"]["lifecycle"] == "completed"
    assert attempts["hyp-b"]["outcome"] == "succeeded"

    succeeded_meetings = [
        {
            "meetingRoundId": attempts[candidate_id]["meetingRoundId"],
            "meetingType": "hypothesis_review",
            "question": "SCI-096",
            "selectionId": "selection-dispatch-1",
            "status": "open",
            "linkedChatRoomId": "team-room",
            # Fresh on purpose: healthy live discussion, not heartbeat-stale.
            "createdAt": _fresh_iso(),
        }
        for candidate_id in ("hyp-a", "hyp-b")
    ]
    projected = _project(team_id, selection, succeeded_meetings)
    aggregate = projected["review"]["aggregate"]
    assert aggregate == {"total": 2, "completed": 0, "pending": 2, "failed": 0, "blocked": 0, "superseded": 0}


def test_replay_does_not_stack_attempts(tmp_path, monkeypatch) -> None:
    team_id = _fanout_env(tmp_path, monkeypatch)
    selection = _persist_selection(team_id)

    chain.open_review_meeting_for_selection(team_id, selection, background=False)
    chain.open_review_meeting_for_selection(team_id, selection, background=False)

    attempts = _attempts(team_id)
    assert len(attempts) == 2
    assert all(item["attemptNumber"] == 1 for item in attempts)
    assert all(item["lifecycle"] == "completed" for item in attempts)


def test_queued_attempt_projects_waiting_system_not_blocked() -> None:
    state = project_state_from_records(
        team_id="team-1",
        question_id="SCI-096",
        reset_boundary=None,
        chain_records=[
            {
                "recordKind": "review_dispatch_attempt",
                "attemptId": f"attempt-queued-{candidate_id}",
                "attemptNumber": 1,
                "questionId": "SCI-096",
                "selectionId": "selection-1",
                "candidateId": candidate_id,
                "roundIndex": 1,
                "lifecycle": "queued",
                "outcome": "none",
                "createdAt": "2026-08-26T00:00:00Z",
                "updatedAt": "2026-08-26T00:00:00Z",
            }
            for candidate_id in ("hyp-a", "hyp-b")
        ],
        selection_records=[
            {
                "selectionId": "selection-1",
                "questionId": "SCI-096",
                "selectedCandidateIds": ["hyp-a", "hyp-b"],
                "createdAt": "2026-08-25T00:00:00Z",
            }
        ],
        meeting_records=[],
        digest_records=[],
        decision_records=[],
        hypothesis_round_records=[],
    )

    assert state["currentPhase"] == "review"
    assert state["review"]["aggregate"] == {
        "total": 2,
        "completed": 0,
        "pending": 2,
        "failed": 0,
        "blocked": 0,
        "superseded": 0,
    }
    for candidate in state["review"]["candidates"]:
        assert candidate["lifecycle"] == "queued"
        assert candidate["actionability"] == "waiting_system"
        assert candidate["problems"] == []
    assert not any(
        action.get("command") == "retry_review_dispatch"
        for action in state["allowedActions"]
    )


def test_legacy_selection_without_attempt_keeps_review_dispatch_missing() -> None:
    state = project_state_from_records(
        team_id="team-1",
        question_id="SCI-096",
        reset_boundary=None,
        chain_records=[],
        selection_records=[
            {
                "selectionId": "selection-1",
                "questionId": "SCI-096",
                "selectedCandidateIds": ["hyp-a", "hyp-b"],
                "createdAt": "2026-08-25T00:00:00Z",
            }
        ],
        meeting_records=[],
        digest_records=[],
        decision_records=[],
        hypothesis_round_records=[],
    )

    assert state["review"]["aggregate"]["blocked"] == 2
    for candidate in state["review"]["candidates"]:
        assert [problem["code"] for problem in candidate["problems"]] == [
            "review_dispatch_missing"
        ]
        assert candidate["lifecycle"] == "not_started"
        assert candidate["actionability"] == "blocked"
    assert any(
        action.get("command") == "retry_review_dispatch"
        for action in state["allowedActions"]
    )


def test_round_projection_uses_durable_fanout_candidates() -> None:
    selection_id = "selection-sci-003"
    active_candidate = "sci-003-cb1735d8f"
    selected_candidates = [
        active_candidate,
        "sci-003-ignored-1",
        "sci-003-ignored-2",
        "sci-003-ignored-3",
    ]
    meeting_id = "hf-review-hsel-58303ec029fc13cf-d8b9ebbc38-r3"
    state = project_state_from_records(
        team_id="team-1",
        question_id="SCI-003",
        reset_boundary=None,
        chain_records=[
            {
                "recordKind": "review_round_link",
                "linkId": "link-sci-003-r3",
                "selectionId": selection_id,
                "selectionVersion": "selection-version-sci-003",
                "candidateId": active_candidate,
                "candidateOrder": 0,
                "roundIndex": 3,
                "meetingRoundId": meeting_id,
                "questionId": "SCI-003",
                "createdAt": "2026-08-27T00:00:00Z",
            },
            {
                "recordKind": "review_dispatch_attempt",
                "attemptId": "attempt-sci-003-r3",
                "attemptNumber": 1,
                "questionId": "SCI-003",
                "selectionId": selection_id,
                "selectionVersion": "selection-version-sci-003",
                "candidateId": active_candidate,
                "roundIndex": 3,
                "lifecycle": "completed",
                "outcome": "succeeded",
                "meetingRoundId": meeting_id,
                "createdAt": "2026-08-27T00:00:00Z",
                "updatedAt": "2026-08-27T00:00:01Z",
            },
        ],
        selection_records=[
            {
                "selectionId": selection_id,
                "questionId": "SCI-003",
                "selectedCandidateIds": selected_candidates,
                "createdAt": "2026-08-26T00:00:00Z",
            }
        ],
        meeting_records=[
            {
                "meetingRoundId": meeting_id,
                "meetingType": "hypothesis_review",
                "question": "SCI-003",
                "selectionId": selection_id,
                "status": "awaiting_approval",
                "linkedChatRoomId": "room-sci-003",
                "createdAt": "2026-08-27T00:00:00Z",
            }
        ],
        digest_records=[],
        decision_records=[],
        hypothesis_round_records=[],
    )

    assert state["selection"]["selectedCandidateIds"] == selected_candidates
    assert [item["candidateId"] for item in state["review"]["candidates"]] == [
        active_candidate
    ]
    assert state["review"]["aggregate"] == {
        "total": 1,
        "completed": 0,
        "pending": 1,
        "failed": 0,
        "blocked": 0,
        "superseded": 0,
    }
    assert state["review"]["lifecycle"] == "waiting_human"
    assert not any(
        problem["code"] == "review_dispatch_missing"
        for problem in state["review"]["problems"]
    )


def test_completed_attempt_without_link_is_integrity_problem() -> None:
    state = project_state_from_records(
        team_id="team-1",
        question_id="SCI-096",
        reset_boundary=None,
        chain_records=[
            {
                "recordKind": "review_dispatch_attempt",
                "attemptId": "attempt-completed-1",
                "attemptNumber": 1,
                "questionId": "SCI-096",
                "selectionId": "selection-1",
                "candidateId": "hyp-a",
                "roundIndex": 1,
                "lifecycle": "completed",
                "outcome": "succeeded",
                "meetingRoundId": "meeting-gone",
                "createdAt": "2026-08-26T00:00:00Z",
                "updatedAt": "2026-08-26T00:00:30Z",
            }
        ],
        selection_records=[
            {
                "selectionId": "selection-1",
                "questionId": "SCI-096",
                "selectedCandidateIds": ["hyp-a", "hyp-b"],
                "createdAt": "2026-08-25T00:00:00Z",
            }
        ],
        meeting_records=[],
        digest_records=[],
        decision_records=[],
        hypothesis_round_records=[],
    )

    by_candidate = {item["candidateId"]: item for item in state["review"]["candidates"]}
    assert [problem["code"] for problem in by_candidate["hyp-a"]["problems"]] == [
        "review_dispatch_state_missing"
    ]
    assert by_candidate["hyp-a"]["actionability"] == "blocked"
    # The untouched sibling stays on the legacy missing-problem path.
    assert [problem["code"] for problem in by_candidate["hyp-b"]["problems"]] == [
        "review_dispatch_missing"
    ]
