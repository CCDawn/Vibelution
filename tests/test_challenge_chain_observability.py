"""Hypothesis-chain observability events on the runtime-scene stream.

Command execution, selection recording, review fan-out, and projection
failures each leave a structured best-effort event so chain stalls are
diagnosable from the event stream without replaying the JSONL ledger.
"""

from __future__ import annotations

import pytest

from core.web.services.team_workflow import hypothesis_selection as selections
from core.web.services.team_workflow import meeting_rounds as meetings
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain as chain,
)
from tests._support.team_workflow.helpers import _use_tmp_project_root


class _SceneEventRecorder:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.events: list[dict[str, object]] = []
        from core.web.services import runtime_scene_service

        monkeypatch.setattr(
            runtime_scene_service,
            "record_runtime_scene_event_quietly",
            self._capture,
        )

    def _capture(self, component, phase, event_code, **kwargs):
        self.events.append(
            {
                "component": component,
                "phase": phase,
                "eventCode": event_code,
                **{key: value for key, value in kwargs.items()},
            }
        )
        return None

    def codes(self) -> list[str]:
        return [str(event["eventCode"]) for event in self.events]

    def find(self, event_code: str) -> dict[str, object] | None:
        return next(
            (event for event in self.events if event["eventCode"] == event_code),
            None,
        )


def _fanout_env(tmp_path, monkeypatch, *, open_meeting=None):
    from core.web.services import team_service
    from core.web.services.team_workflow import meeting_runtime
    from core.web.services.team_workflow.research_runtime import (
        meeting_receipt_authority,
    )

    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(chain, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(meetings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(selections, "PROJECT_ROOT", tmp_path)
    team_id = "team-chain-observability"
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
    monkeypatch.setattr(chain, "_build_round_candidates", lambda *_args: [])
    monkeypatch.setattr(
        chain,
        "list_hypothesis_candidates",
        lambda *_args, **_kwargs: {
            "candidates": [
                {"candidateId": candidate_id} for candidate_id in ("hyp-a", "hyp-b")
            ]
        },
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


def _persist_selection(team_id: str, selection_id: str = "selection-obs-1") -> dict:
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


def test_review_fanout_records_started_and_completed(tmp_path, monkeypatch) -> None:
    recorder = _SceneEventRecorder(monkeypatch)
    team_id = _fanout_env(tmp_path, monkeypatch)
    selection = _persist_selection(team_id)

    result = chain.open_review_meeting_for_selection(team_id, selection, background=False)

    assert result["candidateCount"] == 2
    codes = recorder.codes()
    assert codes.count("review_dispatch.started") == 1
    assert codes.count("review_dispatch.completed") == 1
    started = recorder.find("review_dispatch.started")
    assert started["outcome"] == "started"
    assert started["fields"]["candidateCount"] == 2
    assert started["fields"]["selectionId"] == "selection-obs-1"
    completed = recorder.find("review_dispatch.completed")
    assert completed["fields"]["openedCount"] == 2


def test_review_fanout_failure_records_candidate_failed(tmp_path, monkeypatch) -> None:
    recorder = _SceneEventRecorder(monkeypatch)

    def flaky_open(_team_id, payload, **_kwargs):
        if payload.get("candidateId") == "hyp-b":
            raise RuntimeError("room backend unavailable")
        return {
            "status": "created",
            "meetingRound": {"meetingRoundId": payload["meetingRoundId"]},
            "roomId": "team-room",
            "roundId": "round",
            "chatRoomRoundIds": ["round"],
        }

    team_id = _fanout_env(tmp_path, monkeypatch, open_meeting=flaky_open)
    selection = _persist_selection(team_id)

    with pytest.raises(RuntimeError, match="room backend unavailable"):
        chain.open_review_meeting_for_selection(team_id, selection, background=False)

    codes = recorder.codes()
    assert codes.count("review_dispatch.started") == 1
    failed = recorder.find("review_dispatch.candidate_failed")
    assert failed is not None
    assert failed["outcome"] == "failed"
    assert failed["fields"]["candidateId"] == "hyp-b"
    assert failed["fields"]["errorType"] == "RuntimeError"
    # No completed event for a failed fan-out.
    assert "review_dispatch.completed" not in codes


def test_selection_recording_leaves_created_event(tmp_path, monkeypatch) -> None:
    recorder = _SceneEventRecorder(monkeypatch)
    team_id = _fanout_env(tmp_path, monkeypatch)

    result = selections.record_hypothesis_selection(
        team_id,
        {
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
        },
        background=False,
    )

    assert result["status"] == "created"
    recorded = recorder.find("selection.recorded")
    assert recorded is not None
    assert recorded["outcome"] == "created"
    assert recorded["fields"]["candidateCount"] == 2
    assert recorded["fields"]["selectionId"]
    # The auto review fan-out side effect is visible on the same stream.
    assert recorder.find("review_dispatch.started") is not None
    assert recorder.find("review_dispatch.completed") is not None


def test_selection_validation_failure_leaves_failed_event(tmp_path, monkeypatch) -> None:
    recorder = _SceneEventRecorder(monkeypatch)
    team_id = _fanout_env(tmp_path, monkeypatch)

    with pytest.raises(Exception):
        selections.record_hypothesis_selection(
            team_id,
            {"questionId": "SCI-096", "decidedBy": ""},
            background=False,
        )

    failed = recorder.find("selection.record_failed")
    assert failed is not None
    assert failed["outcome"] == "failed"
    assert failed["fields"]["errorType"]


def test_v2_command_failure_leaves_failed_event(tmp_path, monkeypatch) -> None:
    recorder = _SceneEventRecorder(monkeypatch)
    team_id = _fanout_env(tmp_path, monkeypatch)

    with pytest.raises(Exception):
        chain.execute_v2_command(team_id, {"command": "open_generation"})

    failed = recorder.find("command.failed")
    assert failed is not None
    assert failed["fields"]["command"] == "open_generation"
    assert failed["fields"]["errorType"]
    assert failed["fields"]["durationMs"] >= 0
    assert "command.executed" not in recorder.codes()


def test_projection_source_failure_leaves_failed_event(tmp_path, monkeypatch) -> None:
    recorder = _SceneEventRecorder(monkeypatch)
    team_id = _fanout_env(tmp_path, monkeypatch)
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_state_v2 as state_v2,
    )
    from core.web.services.team_workflow.research_runtime import formal_read_runtime

    def broken_query_service():
        raise RuntimeError("ledger connection lost")

    monkeypatch.setattr(
        formal_read_runtime,
        "get_query_service",
        broken_query_service,
    )

    with pytest.raises(state_v2.HypothesisFirstStateSourceError):
        state_v2.project_hypothesis_first_state_v2(team_id, "SCI-096")

    failed = recorder.find("state_projection.failed")
    assert failed is not None
    assert failed["phase"] == "hypothesis_first_state"
    assert failed["fields"]["questionId"] == "SCI-096"
    assert failed["fields"]["sourceErrorType"] == "RuntimeError"
