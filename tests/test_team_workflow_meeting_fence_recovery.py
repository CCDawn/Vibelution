"""Meeting fence recovery regressions for the 2026-10-17 E2E triple defect.

The hypothesis generation meeting was killed twice by the ``legacy_orphan``
fence through three stacked gaps:

1. the dispatched opening round left no durable scheduling evidence, so a
   restarted backend read the meeting as work-less;
2. the recovery sweep's orphan close ignored ``running_bound_round_ids``, so a
   meeting with a round still in flight was fenced anyway;
3. ``is_challenge_meeting`` could not identify dev/cold-start meetings (no
   workflow run, hence no scope/receipt authority), so they never received the
   governed deadline backfill and fell into the orphan branch.

Each test below is red without its owning fix and green with it.
"""

from __future__ import annotations

import time

import pytest

from core.web.services import (
    agent_directory_service,
    session_service,
    team_service,
)
from core.web.services.team_workflow import meeting_driver_work
from core.web.services.team_workflow import meeting_rounds as meetings
from core.web.services.team_workflow import meeting_runtime
from core.web.services.team_workflow.challenge_deadline_policy import (
    is_challenge_meeting,
)

from tests._support.team_workflow.helpers import _use_tmp_project_root

_TEAM_ROLES = (
    "challenge_cup_search",
    "challenge_cup_extractor",
    "challenge_cup_knowledge_manager",
    "challenge_cup_execution_steward",
    "challenge_cup_experiment_revision",
    "challenge_cup_evaluator",
)


def _isolate(tmp_path, monkeypatch):
    """Hermetic store roots plus a fresh simulated process boot id."""

    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(meetings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        meeting_runtime,
        "_record_meeting_discussion_driver_event",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        meeting_driver_work,
        "_record_recovery_scene_event",
        lambda *_args, **_kwargs: None,
    )
    meeting_driver_work.reset_for_tests()
    meeting_driver_work.reset_digest_stuck_sweep_throttle_for_tests()
    meeting_driver_work.reset_driver_recovery_sweep_throttle_for_tests()
    with meeting_runtime._MEETING_DISCUSSION_JOBS_LOCK:
        meeting_runtime._MEETING_DISCUSSION_JOBS.clear()
    with meeting_runtime._MEETING_DIGEST_JOBS_LOCK:
        meeting_runtime._MEETING_DIGEST_JOBS.clear()


def _team(tmp_path, monkeypatch) -> tuple[str, list[str]]:
    agents: dict[str, str] = {}
    for role in _TEAM_ROLES:
        agent = agent_directory_service.create_agent_instance(display_name=f"FENCE {role}")
        session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title=f"FENCE {role}")
        agents[role] = agent["agentId"]
    team_id = team_service.create_team(
        name="会议围栏恢复团队",
        members=[{"agentId": agents[role], "role": role} for role in _TEAM_ROLES],
    )["teamId"]
    return team_id, [agents[role] for role in _TEAM_ROLES]


def _selection_payload(agent_ids, meeting_round_id, **overrides):
    payload = {
        "selectionId": f"sel-{meeting_round_id}",
        "questionId": "SCI-096",
        "selectedCandidateIds": ["cand-a", "cand-b"],
        "decidedBy": agent_ids[0],
        "meetingRoundId": meeting_round_id,
        "program": "XH-202619",
        "theme": "cc-neuro-001",
        "campaign": "cc-campaign-neuro-001",
        "question": "SCI-096",
        "branch": "main",
        "workflow": "hypothesis_first",
        "agentId": agent_ids[0],
        "mode": "dev",
        "participants": list(agent_ids),
    }
    payload.update(overrides)
    return payload


def _create_open_meeting(team_id: str, agent_ids, meeting_round_id: str, **overrides):
    created = meetings.create_meeting_round(
        team_id,
        _selection_payload(agent_ids, meeting_round_id, **overrides),
    )
    assert created["status"] == "created"
    return created["meetingRound"]


def _amend_meeting(team_id: str, meeting: dict, **fields) -> dict:
    amended = {**meeting, **fields}
    with meetings._LOCK:
        meetings._append_round_record(team_id, amended)
    return amended


def _stage_opening_round_in_flight(monkeypatch, meeting: dict) -> None:
    """Make the real scheduler see one bound round still running."""

    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    in_flight_view = {
        **meeting,
        "linkedChatRoomId": f"room-{meeting['meetingRoundId']}",
        "chatRoomRoundIds": [f"round-{meeting['meetingRoundId']}"],
    }
    monkeypatch.setattr(
        meetings,
        "get_meeting_round",
        lambda *_args: {"meetingRound": dict(in_flight_view)},
    )
    monkeypatch.setattr(
        meetings,
        "running_bound_round_ids",
        lambda _meeting: list(in_flight_view["chatRoomRoundIds"]),
    )


def test_opening_round_dispatch_persists_recoverable_pending_intent(
    tmp_path, monkeypatch
):
    """Defect 1: scheduling while the opening round runs must leave durable
    evidence, so a restarted sweep sees dispatched work instead of a work-less
    meeting it would fence as a legacy orphan."""
    _isolate(tmp_path, monkeypatch)
    team_id, agent_ids = _team(tmp_path, monkeypatch)
    meeting = _create_open_meeting(team_id, agent_ids, "meeting-fence-opening")
    _stage_opening_round_in_flight(monkeypatch, meeting)

    scheduled = meeting_runtime.schedule_meeting_discussion(
        team_id, meeting["meetingRoundId"]
    )
    assert scheduled["status"] == "waiting_for_opening_round"

    # The dispatch fact is durable: a pending run_discussion intent exists
    # (red without fix 1 — latest_intent stayed None).
    intent = meeting_driver_work.latest_intent(team_id, meeting["meetingRoundId"])
    assert intent is not None
    assert intent["status"] == "pending"
    assert intent["actionKind"] == "run_discussion"
    assert intent["workerBootId"] == meeting_driver_work.worker_boot_id()

    # Simulate the backend restart: a fresh boot id, then the startup sweep.
    meeting_driver_work.reset_for_tests()
    summary = meeting_driver_work.recover_challenge_meeting_drivers()

    assert summary["meetingsScanned"] == 1
    assert summary["fenced"] == 0
    terminal = meetings.get_meeting_round(team_id, meeting["meetingRoundId"])[
        "meetingRound"
    ]
    assert terminal["status"] == "open"
    assert not str(terminal.get("terminalReason") or "")
    # The re-entered scheduler stayed a no-op and did not duplicate evidence.
    after = meeting_driver_work.latest_intent(team_id, meeting["meetingRoundId"])
    assert after["status"] == "pending"


def test_recovery_does_not_fence_orphan_shaped_meeting_with_running_bound_round(
    tmp_path, monkeypatch
):
    """Defect 2: an identity-less, intent-less meeting whose bound round is
    still running has live work and must not be closed as ``legacy_orphan``."""
    _isolate(tmp_path, monkeypatch)
    team_id, agent_ids = _team(tmp_path, monkeypatch)
    meeting = _create_open_meeting(team_id, agent_ids, "meeting-fence-running-round")
    # No durable intent and no challenge identity: exactly the orphan shape.
    assert (
        meeting_driver_work.latest_intent(team_id, meeting["meetingRoundId"]) is None
    )
    bound = _amend_meeting(
        team_id,
        meeting,
        linkedChatRoomId="room-fence-running",
        chatRoomRoundIds=["round-fence-running"],
    )
    monkeypatch.setattr(
        meetings,
        "running_bound_round_ids",
        lambda _meeting: list(bound["chatRoomRoundIds"]),
    )

    summary = meeting_driver_work.recover_challenge_meeting_drivers()

    assert summary["meetingsScanned"] == 1
    assert summary["fenced"] == 0
    terminal = meetings.get_meeting_round(team_id, meeting["meetingRoundId"])[
        "meetingRound"
    ]
    assert terminal["status"] == "open"
    assert not str(terminal.get("terminalReason") or "")


def test_is_challenge_meeting_recognizes_dev_coldstart_roster():
    """Defect 3 (unit): the frozen participant contract is the identity a
    dev/cold-start meeting (no workflow run, no authorities) can still show."""
    roster = {
        "participantRoleIds": [
            "challenge_cup_search",
            "challenge_cup_evaluator",
        ],
        "teamRoleContractVersion": 1,
        "participantPolicyVersion": 1,
        "roleContractFingerprint": "a" * 64,
        "resolutionHash": "b" * 64,
    }
    assert is_challenge_meeting({"meetingType": "hypothesis_candidate_generation", **roster})
    # A legacy record predating the roster contract stays unidentifiable.
    assert not is_challenge_meeting(
        {
            "meetingType": "hypothesis_review",
            "participants": ["agent-1"],
            "participantRoleIds": [],
            "teamRoleContractVersion": 0,
            "participantPolicyVersion": 0,
        }
    )


def test_recovery_backfills_deadline_for_dev_coldstart_meeting(
    tmp_path, monkeypatch
):
    """Defect 3: a dev/cold-start meeting carrying the frozen roster but no
    scope/receipt authority gets the governed deadline backfilled instead of
    the ``legacy_orphan`` fence."""
    _isolate(tmp_path, monkeypatch)
    team_id, agent_ids = _team(tmp_path, monkeypatch)
    meeting = _create_open_meeting(
        team_id,
        agent_ids,
        "meeting-fence-dev-backfill",
        meetingType="hypothesis_candidate_generation",
        stage="hypothesis",
        roundType="generation",
        # The dev/cold-start roster stamp every challenge-chain meeting open
        # path persists, without any workflow-run authority.
        participants=[agent_ids[0], agent_ids[1]],
        participantRoleIds=["challenge_cup_search", "challenge_cup_evaluator"],
        participantRoleSnapshot=[
            {"roleId": "challenge_cup_search", "agentId": agent_ids[0]},
            {"roleId": "challenge_cup_evaluator", "agentId": agent_ids[1]},
        ],
        teamRoleContractVersion=1,
        participantPolicyVersion=1,
        roleContractFingerprint="c" * 64,
        resolutionHash="d" * 64,
    )
    assert not int(meeting.get("challengeDeadlineAtMs") or 0)
    assert (
        meeting_driver_work.latest_intent(team_id, meeting["meetingRoundId"]) is None
    )

    summary = meeting_driver_work.recover_challenge_meeting_drivers()

    assert summary["meetingsScanned"] == 1
    assert summary["backfilled"] == 1
    assert summary["fenced"] == 0
    restored = meetings.get_meeting_round(team_id, meeting["meetingRoundId"])[
        "meetingRound"
    ]
    assert restored["status"] == "open"
    assert restored["challengeDeadlineAtMs"] > int(time.time() * 1000)
    assert not str(restored.get("terminalReason") or "")
