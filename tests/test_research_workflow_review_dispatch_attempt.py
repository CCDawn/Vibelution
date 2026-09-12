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


class _FakeChainClock:
    """Injectable chain clock: no wall-clock dependence in gate tests."""

    def __init__(self, start_ms: int = 1_700_000_000_000) -> None:
        self.now_ms = start_ms

    def __call__(self) -> str:
        return (
            datetime.fromtimestamp(self.now_ms / 1000, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

    def advance(self, seconds: float) -> None:
        self.now_ms += int(seconds * 1000)


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


def test_terminal_transition_replay_never_appends_duplicate_rows(
    tmp_path, monkeypatch
) -> None:
    """终态被重复观察是幂等写入：同一 attempt 的 completed/succeeded 只留一行。

    SCI-056 里单个 attempt 被重复追加了 3,000+ 次完全相同的终态行，账本膨胀到
    淹没投影与审计；重复读取/围栏清扫不得再写第二行。
    """
    team_id = _fanout_env(tmp_path, monkeypatch)
    queued = chain._append_review_dispatch_attempt_state(
        team_id,
        question_id="SCI-096",
        selection_id="selection-dispatch-1",
        selection_version="v1",
        candidate_id="hyp-a",
        round_index=1,
        lifecycle="queued",
    )
    transition = {
        "question_id": "SCI-096",
        "selection_id": "selection-dispatch-1",
        "selection_version": "v1",
        "candidate_id": "hyp-a",
        "round_index": 1,
        "lifecycle": "completed",
        "outcome": "succeeded",
        "meeting_round_id": "hf-review-selection-dispatch-1-hyp-a",
    }
    first = chain._append_review_dispatch_attempt_state(team_id, **transition)
    assert first["attemptId"] == queued["attemptId"]

    for _ in range(3):
        repeated = chain._append_review_dispatch_attempt_state(team_id, **transition)
        assert repeated == first

    def attempt_rows() -> list[dict]:
        return [
            record
            for record in _chain_records(team_id)
            if record.get("recordKind") == chain.REVIEW_DISPATCH_ATTEMPT_KIND
        ]

    assert len(attempt_rows()) == 2  # queued + one terminal transition

    # A different terminal verdict about the same attempt still appends.
    superseded = chain._append_review_dispatch_attempt_state(
        team_id,
        **{
            **transition,
            "lifecycle": "failed",
            "outcome": "superseded",
            "error": "ReviewMeetingClosed",
            "error_type": "ReviewMeetingClosed",
        },
    )
    assert superseded["lifecycle"] == "failed"
    assert len(attempt_rows()) == 3
    latest = _attempts(team_id)
    assert len(latest) == 1
    assert latest[0]["outcome"] == "superseded"


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
    clock = _FakeChainClock()
    monkeypatch.setattr(chain, "_utc_now", clock)

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

    # The retry backoff gates an immediate re-dispatch after a real failure:
    # the next attempt is only minted once the exponential window elapsed.
    clock.advance(chain._review_dispatch_backoff_seconds(1) + 1)
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


def test_retry_bumps_attempt_for_open_meeting_with_dead_silent_latest_round(
    tmp_path, monkeypatch
) -> None:
    """Restart-orphan depth defense (SCI-007): a dispatch whose bound meeting
    is still ``open`` but whose latest bound round terminally died with zero
    completed speech is a dead attempt — retry must bump the attempt number
    and open a fresh meeting instead of replaying the silent one.
    """
    from core.web.services import chat_room_service

    team_id = _fanout_env(tmp_path, monkeypatch)
    selection = _persist_selection(team_id)

    chain.open_review_meeting_for_selection(team_id, selection, background=False)
    attempts = {item["candidateId"]: item for item in _attempts(team_id)}
    orphan_meeting_id = attempts["hyp-b"]["meetingRoundId"]
    assert attempts["hyp-b"]["attemptNumber"] == 1

    # Model the backend restart: the meeting record stays ``open`` (the
    # append-only ledger never saw the kill) while the newest bound room round
    # is terminal with zero completed speech.
    def staged_get_meeting_round(_team_id, meeting_round_id, **_kwargs):
        if meeting_round_id == orphan_meeting_id:
            return {
                "meetingRound": {
                    "meetingRoundId": orphan_meeting_id,
                    "meetingType": "hypothesis_review",
                    "status": "open",
                    "linkedChatRoomId": "team-room",
                    "chatRoomRoundIds": ["round-hyp-b"],
                }
            }
        raise meetings.ResearchMeetingRoundNotFoundError("missing")

    monkeypatch.setattr(meetings, "get_meeting_round", staged_get_meeting_round)
    monkeypatch.setattr(
        chat_room_service,
        "get_chat_room_detail",
        # meeting_rounds reads bound rounds with get_chat_room_detail(room_id,
        # reconcile=False) since the bounded-sweep read path landed on main.
        lambda room_id, **_kwargs: {
            "roomId": "team-room",
            "rounds": [
                {"roundId": "round-hyp-b", "status": "stopped", "messages": []}
            ],
        }
        if room_id == "team-room"
        else None,
    )

    chain.retry_review_dispatch(team_id, "selection-dispatch-1", ["hyp-b"])

    attempts = {item["candidateId"]: item for item in _attempts(team_id)}
    assert attempts["hyp-b"]["attemptNumber"] == 2
    assert attempts["hyp-b"]["lifecycle"] == "completed"
    assert attempts["hyp-b"]["outcome"] == "succeeded"
    fresh_meeting_id = attempts["hyp-b"]["meetingRoundId"]
    assert fresh_meeting_id != orphan_meeting_id
    assert fresh_meeting_id.endswith("-a2")


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


# ---------------------------------------------------------------------------
# Failing-identity backoff + cap (SCI-092 storm fix)


def _persist_single_selection(
    team_id: str, candidate_id: str = "hyp-solo"
) -> dict:
    record = {
        "schemaVersion": 1,
        "selectionId": "selection-solo",
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
        "selectedCandidateIds": [candidate_id],
        "previousSelectionId": "",
        "decidedBy": "agent-a",
        "selectionHash": "hash-solo",
        "createdAt": "2026-08-26T00:00:00Z",
    }
    selections._append_jsonl(selections._storage_path(team_id), record)
    return record


def _raw_dispatch_rows(team_id: str) -> list[dict]:
    return [
        dict(record)
        for record in _chain_records(team_id)
        if record.get("recordKind") == chain.REVIEW_DISPATCH_ATTEMPT_KIND
    ]


def test_retry_backoff_gates_immediate_requeue_after_failure(
    tmp_path, monkeypatch
) -> None:
    """A failing identity mints no fresh attempt inside the backoff window."""
    clock = _FakeChainClock()
    monkeypatch.setattr(chain, "_utc_now", clock)

    def always_fails(_team_id, payload, **_kwargs):
        raise RuntimeError("workflowRunId does not resolve to a Ledger run")

    team_id = _fanout_env(tmp_path, monkeypatch, open_meeting=always_fails)
    selection = _persist_single_selection(team_id)

    with pytest.raises(RuntimeError, match="does not resolve"):
        chain.open_review_meeting_for_selection(team_id, selection, background=False)
    assert len(_raw_dispatch_rows(team_id)) == 2  # one queued + one failed

    # Sweep pass 98s later (the storm cadence): the identity is inside the
    # 5-min baseline window, so nothing is appended and nothing opens.
    clock.advance(98)
    result = chain.open_review_meeting_for_selection(
        team_id, selection, background=False
    )
    assert result["status"] == "dispatch_gated"
    assert result["gated"] is True
    assert result["gatedCandidates"] == {"hyp-solo": "backoff"}
    assert result["candidateCount"] == 0
    assert len(_raw_dispatch_rows(team_id)) == 2

    # Still inside the window: repeated passes stay zero-append.
    clock.advance(98)
    again = chain.open_review_meeting_for_selection(
        team_id, selection, background=False
    )
    assert again["status"] == "dispatch_gated"
    assert len(_raw_dispatch_rows(team_id)) == 2

    # A human retry entry rides the same gate (one choke point).
    replay = chain.retry_review_dispatch(team_id, "selection-solo", ["hyp-solo"])
    assert replay["status"] == "dispatch_gated"
    assert len(_raw_dispatch_rows(team_id)) == 2


def test_retry_backoff_expires_into_a_fresh_attempt(tmp_path, monkeypatch) -> None:
    """Past the window the identity retries and recovers normally."""
    clock = _FakeChainClock()
    monkeypatch.setattr(chain, "_utc_now", clock)

    state = {"fail": True}

    def recoverable_open(_team_id, payload, **_kwargs):
        if state["fail"]:
            raise RuntimeError("transient dispatch failure")
        return {
            "status": "created",
            "meetingRound": {"meetingRoundId": payload["meetingRoundId"]},
            "roomId": "team-room",
            "roundId": f"round-{payload['candidateId']}",
            "chatRoomRoundIds": [f"round-{payload['candidateId']}"],
        }

    team_id = _fanout_env(tmp_path, monkeypatch, open_meeting=recoverable_open)
    selection = _persist_single_selection(team_id)

    with pytest.raises(RuntimeError, match="transient"):
        chain.open_review_meeting_for_selection(team_id, selection, background=False)
    clock.advance(chain._review_dispatch_backoff_seconds(1) + 1)
    state["fail"] = False
    result = chain.retry_review_dispatch(team_id, "selection-solo", ["hyp-solo"])
    assert result["candidateCount"] == 1
    attempts = {item["candidateId"]: item for item in _attempts(team_id)}
    assert attempts["hyp-solo"]["attemptNumber"] == 2
    assert attempts["hyp-solo"]["lifecycle"] == "completed"


def test_cap_appends_one_capped_marker_then_never_queues_again(
    tmp_path, monkeypatch
) -> None:
    """Eight failed attempts cap the identity; repeated passes append zero."""
    clock = _FakeChainClock()
    monkeypatch.setattr(chain, "_utc_now", clock)

    def always_fails(_team_id, payload, **_kwargs):
        raise RuntimeError("workflowRunId does not resolve to a Ledger run")

    team_id = _fanout_env(tmp_path, monkeypatch, open_meeting=always_fails)
    selection = _persist_single_selection(team_id)

    # Drive 8 real failures, each past its own backoff window.
    for failure_count in range(chain.REVIEW_DISPATCH_ATTEMPT_FAILURE_CAP):
        with pytest.raises(RuntimeError, match="does not resolve"):
            chain.open_review_meeting_for_selection(
                team_id, selection, background=False
            )
        clock.advance(
            chain._review_dispatch_backoff_seconds(failure_count + 1) + 1
        )

    assert len(_raw_dispatch_rows(team_id)) == 2 * chain.REVIEW_DISPATCH_ATTEMPT_FAILURE_CAP

    # The next pass appends exactly ONE terminal capped marker, opens nothing
    # and does not raise (the gate returns before any meeting side effect).
    result = chain.open_review_meeting_for_selection(
        team_id, selection, background=False
    )
    assert result["status"] == "dispatch_gated"
    assert result["gatedCandidates"] == {"hyp-solo": "capped"}
    rows = _raw_dispatch_rows(team_id)
    assert len(rows) == 2 * chain.REVIEW_DISPATCH_ATTEMPT_FAILURE_CAP + 1
    capped = next(item for item in rows if item.get("capped"))
    assert capped["lifecycle"] == "failed"
    assert capped["outcome"] == "capped"
    assert capped["errorType"] == "ReviewDispatchAttemptCapReached"
    assert capped["idempotencyKey"].endswith(":capped")

    # Repeated sweep passes: the capped identity produces ZERO further
    # queued appends (check-before-append on the single marker).
    for _ in range(3):
        clock.advance(24 * 60 * 60)
        replay = chain.open_review_meeting_for_selection(
            team_id, selection, background=False
        )
        assert replay["status"] == "dispatch_gated"
        assert replay["gatedCandidates"] == {"hyp-solo": "capped"}
    assert (
        len(_raw_dispatch_rows(team_id))
        == 2 * chain.REVIEW_DISPATCH_ATTEMPT_FAILURE_CAP + 1
    )
    assert sum(1 for item in _raw_dispatch_rows(team_id) if item.get("capped")) == 1


def test_retry_backoff_seconds_growth() -> None:
    """5 min doubling, 24 h ceiling."""
    assert chain._review_dispatch_backoff_seconds(0) == 300.0
    assert chain._review_dispatch_backoff_seconds(1) == 600.0
    assert chain._review_dispatch_backoff_seconds(2) == 1200.0
    assert chain._review_dispatch_backoff_seconds(7) == 38400.0
    assert chain._review_dispatch_backoff_seconds(8) == 76800.0
    assert chain._review_dispatch_backoff_seconds(20) == 86400.0


def test_superseded_attempts_do_not_count_as_dispatch_failures(
    tmp_path, monkeypatch
) -> None:
    """A fence/restart supersede is a verdict, not a repeated dispatch
    failure: the dead-silent requeue stays immediately available."""
    from core.web.services import chat_room_service

    team_id = _fanout_env(tmp_path, monkeypatch)
    selection = _persist_single_selection(team_id, candidate_id="hyp-solo")

    chain.open_review_meeting_for_selection(team_id, selection, background=False)
    attempts = {item["candidateId"]: item for item in _attempts(team_id)}
    orphan_meeting_id = attempts["hyp-solo"]["meetingRoundId"]

    def staged_get_meeting_round(_team_id, meeting_round_id, **_kwargs):
        if meeting_round_id == orphan_meeting_id:
            return {
                "meetingRound": {
                    "meetingRoundId": orphan_meeting_id,
                    "meetingType": "hypothesis_review",
                    "status": "open",
                    "linkedChatRoomId": "team-room",
                    "chatRoomRoundIds": ["round-hyp-solo"],
                }
            }
        raise meetings.ResearchMeetingRoundNotFoundError("missing")

    monkeypatch.setattr(meetings, "get_meeting_round", staged_get_meeting_round)
    monkeypatch.setattr(
        chat_room_service,
        "get_chat_room_detail",
        lambda room_id, **_kwargs: {
            "roomId": "team-room",
            "rounds": [
                {"roundId": "round-hyp-solo", "status": "stopped", "messages": []}
            ],
        }
        if room_id == "team-room"
        else None,
    )

    result = chain.retry_review_dispatch(team_id, "selection-solo", ["hyp-solo"])
    assert result["candidateCount"] == 1
    latest = {item["candidateId"]: item for item in _attempts(team_id)}["hyp-solo"]
    assert latest["attemptNumber"] == 2
    assert latest["lifecycle"] == "completed"
