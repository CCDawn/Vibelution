"""Durable challenge meeting driver intent + startup recovery tests.

Covers the T2 lean contract: ``schedule_meeting_discussion`` persists a
durable intent next to ``meeting_rounds.jsonl`` (pending before submit,
completed/failed after the run, failed on submit rejection); the startup
sweep ``recover_challenge_meeting_drivers`` fences deadline-expired open
meetings through the existing terminal path (no partial digest promoted),
re-drives interrupted discussions after a simulated process restart, and
stays idempotent across consecutive runs.  Awaiting-approval / closed
meetings are untouched; open meetings without any durable work record are
split by identity: challenge-identity meetings get the governed deadline
backfilled, while identity-less legacy orphans are fenced through the
terminal path because no governed deadline can ever be derived for them;
failed work at the attempt cap is left auditable instead of retried.

All discussion content comes from fake runners (DEV fixtures); no real model
or network is involved.
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

from tests._support.team_workflow.helpers import _use_tmp_project_root

_TEAM_ROLES = (
    "challenge_cup_search",
    "challenge_cup_extractor",
    "challenge_cup_knowledge_manager",
    "challenge_cup_execution_steward",
    "challenge_cup_experiment_revision",
    "challenge_cup_evaluator",
)
# The server-resolved hypothesis-review roster only spans these roles.
_PARTICIPANT_ROLES = (
    "challenge_cup_search",
    "challenge_cup_knowledge_manager",
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
    with meeting_runtime._MEETING_DISCUSSION_JOBS_LOCK:
        meeting_runtime._MEETING_DISCUSSION_JOBS.clear()


def _team(tmp_path, monkeypatch) -> tuple[str, list[str]]:
    agents: dict[str, str] = {}
    for role in _TEAM_ROLES:
        agent = agent_directory_service.create_agent_instance(display_name=f"DRV {role}")
        session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title=f"DRV {role}")
        agents[role] = agent["agentId"]
    team_id = team_service.create_team(
        name="会议驱动恢复团队",
        members=[{"agentId": agents[role], "role": role} for role in _TEAM_ROLES],
    )["teamId"]
    return team_id, [agents[role] for role in _PARTICIPANT_ROLES]


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


def _marker_runner(participant, prompt, context):
    if "批评与修订" in str(prompt):
        return {"status": "completed", "raw_output": "pass", "summary": "pass"}
    role = str(participant.get("teamRole") or "participant")
    if role == "challenge_cup_search":
        content = "AGREE: cand-a 的机制证据最完整，进入有界验证"
    else:
        content = (
            "DISAGREE: cand-b 的泛化证据不足\n"
            "RISK: 数据集偏差尚未评估\n"
            "ACTION: researcher | 补充 cand-b 的消融实验证据\n"
            "KNOWLEDGE: 预测编码层级最新综述"
        )
    return {"status": "completed", "raw_output": content, "summary": "ok"}


class _DeferredExecutor:
    """Submit accepts the job but never runs it (job stays in-process)."""

    def __init__(self):
        self.submissions: list[tuple[object, tuple[object, ...]]] = []
        self.status_at_submit: list[str | None] = []

    def submit(self, callback, *args):
        intent = meeting_driver_work.latest_intent(*args)
        self.status_at_submit.append(
            str(intent.get("status") or "") if intent else None
        )
        self.submissions.append((callback, args))
        return object()


class _InlineExecutor:
    """Submit runs the job synchronously (driver advances immediately)."""

    def __init__(self):
        self.submissions: list[tuple[object, tuple[object, ...]]] = []

    def submit(self, callback, *args):
        self.submissions.append((callback, args))
        callback(*args)
        return object()


class _ExplodingExecutor:
    def submit(self, callback, *args):
        raise RuntimeError("executor queue saturated")


def _ready_to_drive(monkeypatch, meeting: dict):
    """Make the real scheduler treat the staged meeting as ready to drive."""

    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(
        meetings,
        "get_meeting_round",
        lambda *_args: {"meetingRound": dict(meeting)},
    )
    monkeypatch.setattr(meetings, "running_bound_round_ids", lambda *_args: [])
    monkeypatch.setattr(
        meeting_runtime,
        "_latest_bound_round_messages",
        lambda *_args: [{"status": "completed"}],
    )


def _recorder(calls, *, error: Exception | None = None):
    def runner(team_id, meeting_round_id):
        calls.append((team_id, meeting_round_id))
        if error is not None:
            raise error
        return {"stopReason": "converged"}

    return runner


def _create_open_meeting(team_id: str, agent_ids, meeting_round_id: str, **overrides):
    created = meetings.create_meeting_round(
        team_id,
        _selection_payload(agent_ids, meeting_round_id, **overrides),
    )
    assert created["status"] == "created"
    return created["meetingRound"]


def _expire_deadline(team_id: str, meeting: dict, deadline_at_ms: int) -> dict:
    """Append an amended record with a past ``challengeDeadlineAtMs``.

    T1 replaced the creation-time fixed 300s window with the derived deadline
    policy, so a past deadline is staged through the append-only store's
    latest-wins read instead of patching a removed module constant.
    """

    amended = {**meeting, "challengeDeadlineAtMs": int(deadline_at_ms)}
    with meetings._LOCK:
        meetings._append_round_record(team_id, amended)
    return amended


def test_schedule_persists_pending_before_submit_and_closes_outcome(
    tmp_path, monkeypatch
):
    _isolate(tmp_path, monkeypatch)
    team_id = "team-driver-lifecycle"
    meeting = {
        "meetingRoundId": "meeting-driver-lifecycle",
        "status": "open",
        "chatRoomRoundIds": ["round-1"],
    }
    _ready_to_drive(monkeypatch, meeting)
    executor = _DeferredExecutor()
    monkeypatch.setattr(meeting_runtime, "_MEETING_DISCUSSION_EXECUTOR", executor)
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(meeting_runtime, "run_meeting_discussion", _recorder(calls))

    scheduled = meeting_runtime.schedule_meeting_discussion(
        team_id, meeting["meetingRoundId"]
    )
    assert scheduled["status"] == "scheduled"
    # The durable intent is written before the executor accepts the job.
    assert executor.status_at_submit == ["pending"]
    intent = meeting_driver_work.latest_intent(team_id, meeting["meetingRoundId"])
    assert intent["status"] == "pending"
    assert intent["attemptCount"] == 0
    assert intent["actionKind"] == "run_discussion"
    assert intent["workerBootId"] == meeting_driver_work.worker_boot_id()
    # Same directory as meeting_rounds.jsonl for the same team.
    assert (
        meeting_driver_work.work_path(team_id).parent
        == meetings._rounds_path(team_id).parent
    )

    callback, args = executor.submissions[0]
    callback(*args)
    assert calls == [(team_id, meeting["meetingRoundId"])]
    completed = meeting_driver_work.latest_intent(team_id, meeting["meetingRoundId"])
    assert completed["status"] == "completed"
    assert completed["attemptCount"] == 1
    assert completed["lastProblem"] == ""

    # A runner crash flips the same durable intent to failed with a bounded
    # type-plus-message problem (no traceback).
    failed_meeting = {
        "meetingRoundId": "meeting-driver-failed",
        "status": "open",
        "chatRoomRoundIds": ["round-1"],
    }
    monkeypatch.setattr(
        meetings,
        "get_meeting_round",
        lambda *_args: {"meetingRound": dict(failed_meeting)},
    )
    monkeypatch.setattr(
        meeting_runtime,
        "run_meeting_discussion",
        _recorder(calls, error=RuntimeError("fanout exploded")),
    )
    assert meeting_runtime.schedule_meeting_discussion(
        team_id, failed_meeting["meetingRoundId"]
    )["status"] == "scheduled"
    callback, args = executor.submissions[1]
    callback(*args)
    failed = meeting_driver_work.latest_intent(team_id, failed_meeting["meetingRoundId"])
    assert failed["status"] == "failed"
    assert failed["attemptCount"] == 1
    assert failed["lastProblem"] == "RuntimeError: fanout exploded"
    assert len(failed["lastProblem"]) <= 240


def test_schedule_submit_failure_persists_failed_and_reraises(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    team_id = "team-driver-submit-failed"
    meeting = {
        "meetingRoundId": "meeting-driver-submit-failed",
        "status": "open",
        "chatRoomRoundIds": ["round-1"],
    }
    _ready_to_drive(monkeypatch, meeting)
    monkeypatch.setattr(meeting_runtime, "_MEETING_DISCUSSION_EXECUTOR", _ExplodingExecutor())
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(meeting_runtime, "run_meeting_discussion", _recorder(calls))

    with pytest.raises(RuntimeError, match="executor queue saturated"):
        meeting_runtime.schedule_meeting_discussion(team_id, meeting["meetingRoundId"])

    failed = meeting_driver_work.latest_intent(team_id, meeting["meetingRoundId"])
    assert failed["status"] == "failed"
    assert failed["attemptCount"] == 0
    assert failed["lastProblem"] == "RuntimeError: executor queue saturated"
    assert calls == []
    # The dedup key was released, so a later scheduler can submit again.
    monkeypatch.setattr(meeting_runtime, "_MEETING_DISCUSSION_EXECUTOR", _DeferredExecutor())
    assert meeting_runtime.schedule_meeting_discussion(
        team_id, meeting["meetingRoundId"]
    )["status"] == "scheduled"


def test_recovery_reschedules_pending_and_stale_running_work_after_restart(
    tmp_path, monkeypatch
):
    _isolate(tmp_path, monkeypatch)
    team_id, agent_ids = _team(tmp_path, monkeypatch)

    # Case A: the old process persisted a pending intent, then died before
    # the executor picked the job up.
    pending_meeting = _create_open_meeting(team_id, agent_ids, "meeting-recover-pending")
    meeting_driver_work.record_intent(team_id, pending_meeting["meetingRoundId"], status="pending")
    meeting_driver_work.reset_for_tests()  # simulate a backend restart
    pending_view = {
        **pending_meeting,
        "linkedChatRoomId": "room-pending",
        "chatRoomRoundIds": ["round-pending"],
    }
    _ready_to_drive(monkeypatch, pending_view)
    executor = _InlineExecutor()
    monkeypatch.setattr(meeting_runtime, "_MEETING_DISCUSSION_EXECUTOR", executor)
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(meeting_runtime, "run_meeting_discussion", _recorder(calls))

    summary = meeting_driver_work.recover_challenge_meeting_drivers()

    assert summary["teams"] >= 1
    assert summary["meetingsScanned"] == 1
    assert summary["rescheduled"] == 1
    assert summary["fenced"] == 0
    recovered = meeting_driver_work.latest_intent(team_id, pending_meeting["meetingRoundId"])
    assert recovered["status"] == "completed"
    assert calls == [(team_id, pending_meeting["meetingRoundId"])]

    # Case B: the old process marked the driver running and died mid-flight;
    # the running record carries a foreign boot id, so the sweep re-drives it.
    running_meeting = _create_open_meeting(team_id, agent_ids, "meeting-recover-running")
    meeting_driver_work.record_intent(team_id, running_meeting["meetingRoundId"], status="pending")
    meeting_driver_work.record_intent(team_id, running_meeting["meetingRoundId"], status="running")
    stale_boot_id = meeting_driver_work.worker_boot_id()
    meeting_driver_work.reset_for_tests()
    assert stale_boot_id != meeting_driver_work.worker_boot_id()
    calls.clear()
    _ready_to_drive(
        monkeypatch,
        {
            **running_meeting,
            "linkedChatRoomId": "room-running",
            "chatRoomRoundIds": ["round-running"],
        },
    )

    summary = meeting_driver_work.recover_challenge_meeting_drivers()

    assert summary["rescheduled"] == 1
    assert calls == [(team_id, running_meeting["meetingRoundId"])]
    rerun = meeting_driver_work.latest_intent(team_id, running_meeting["meetingRoundId"])
    assert rerun["status"] == "completed"
    assert rerun["attemptCount"] == 2


def test_recovery_fences_expired_open_meeting_without_promoting_digest(
    tmp_path, monkeypatch
):
    _isolate(tmp_path, monkeypatch)
    team_id, agent_ids = _team(tmp_path, monkeypatch)
    meeting = _create_open_meeting(
        team_id,
        agent_ids,
        "meeting-fence-expired",
        meetingType="plan_review",
        stage="protocol",
        roundType="decision_gate",
        modelInvocationReceiptAuthority={
            "schemaVersion": 1,
            "authorityKind": "workflow_run",
            "teamId": team_id,
            "questionId": "SCI-096",
            "workflowRunId": "run-fence",
            "workflowId": "challenge-cup-research",
            "workflowVersionId": "wv-fence",
            "modelPolicySha256": "a" * 64,
        },
    )
    assert meeting["challengeDeadlineAtMs"] > 0
    meeting = _expire_deadline(
        team_id, meeting, int(time.time() * 1000) - 60_000
    )
    assert meeting["challengeDeadlineAtMs"] < int(time.time() * 1000)
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(meeting_runtime, "run_meeting_discussion", _recorder(calls))

    summary = meeting_driver_work.recover_challenge_meeting_drivers()

    assert summary["meetingsScanned"] == 1
    assert summary["fenced"] == 1
    assert summary["rescheduled"] == 0
    terminal = meetings.get_meeting_round(team_id, meeting["meetingRoundId"])["meetingRound"]
    assert terminal["status"] == "closed"
    assert terminal["executionStatus"] == "stopped"
    assert terminal["terminalReason"] == "challenge_deadline"
    assert terminal["closedBy"] == "system:challenge-execution-fence"
    # No partial digest was promoted by the fence.
    digests_path = meetings._rounds_path(team_id).with_name("meeting_digests.jsonl")
    assert not digests_path.exists()
    # The driver never ran for the fenced meeting.
    assert calls == []
    assert (
        meeting_driver_work.latest_intent(team_id, meeting["meetingRoundId"]) is None
    )


def _amend_meeting(team_id: str, meeting: dict, **fields) -> dict:
    """Append an amended record to stage a shape ``create_meeting_round`` cannot.

    Mirrors ``_expire_deadline``: the append-only store's latest-wins read is
    the staging mechanism, so pre-policy / mid-lifecycle shapes are produced by
    appending an amended record rather than patching removed constants.
    """

    amended = {**meeting, **fields}
    with meetings._LOCK:
        meetings._append_round_record(team_id, amended)
    return amended


def test_recovery_fences_legacy_orphan_meetings_without_identity(
    tmp_path, monkeypatch
):
    _isolate(tmp_path, monkeypatch)
    team_id, agent_ids = _team(tmp_path, monkeypatch)

    # A bare open meeting created before the identity contract: no scope
    # authority, no receipt authority, and therefore no possible deadline.
    orphan_open = _create_open_meeting(team_id, agent_ids, "meeting-orphan-open")
    # The production hang shape: stuck in ``summarizing`` with a draft error
    # and no driver that can ever advance it.
    orphan_stuck = _create_open_meeting(team_id, agent_ids, "meeting-orphan-stuck")
    _amend_meeting(
        team_id,
        orphan_stuck,
        status="summarizing",
        summaryDraftError={
            "code": "summary_draft_timeout",
            "message": "digest draft timed out after 450s",
        },
    )
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(meeting_runtime, "run_meeting_discussion", _recorder(calls))

    summary = meeting_driver_work.recover_challenge_meeting_drivers()

    assert summary["meetingsScanned"] == 2
    assert summary["fenced"] == 2
    assert summary["backfilled"] == 0
    assert summary["rescheduled"] == 0
    assert summary["skipped"] == 0
    assert calls == []
    for meeting_round_id in (
        orphan_open["meetingRoundId"],
        orphan_stuck["meetingRoundId"],
    ):
        terminal = meetings.get_meeting_round(team_id, meeting_round_id)["meetingRound"]
        assert terminal["status"] == "closed"
        assert terminal["executionStatus"] == "stopped"
        assert terminal["terminalReason"] == "legacy_orphan_closeout"
        assert terminal["closedBy"] == "system:challenge-execution-fence"
        assert (
            meeting_driver_work.latest_intent(team_id, meeting_round_id) is None
        )
    # No partial digest was promoted by the legacy fence.
    digests_path = meetings._rounds_path(team_id).with_name("meeting_digests.jsonl")
    assert not digests_path.exists()

    # Idempotent: fenced meetings are now closed, so a second sweep scans none.
    second = meeting_driver_work.recover_challenge_meeting_drivers()
    assert second["meetingsScanned"] == 0
    assert second["fenced"] == 0
    assert calls == []


def test_recovery_backfills_deadline_for_identity_meeting_missing_policy(
    tmp_path, monkeypatch
):
    _isolate(tmp_path, monkeypatch)
    team_id, agent_ids = _team(tmp_path, monkeypatch)
    meeting = _create_open_meeting(
        team_id,
        agent_ids,
        "meeting-backfill",
        modelInvocationReceiptAuthority={
            "schemaVersion": 1,
            "authorityKind": "workflow_run",
            "teamId": team_id,
            "questionId": "SCI-096",
            "workflowRunId": "run-backfill",
            "workflowId": "challenge-cup-research",
            "workflowVersionId": "wv-backfill",
            "modelPolicySha256": "c" * 64,
        },
    )
    assert meeting["challengeDeadlineAtMs"] > 0
    # Strip the persisted policy to reproduce a pre-policy identity meeting:
    # challenge identity present, governed deadline absent.
    _amend_meeting(
        team_id,
        meeting,
        challengeDeadlineAtMs=0,
        meetingDeadlineAtMs=0,
        deadlinePolicyVersion="",
    )
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(meeting_runtime, "run_meeting_discussion", _recorder(calls))

    summary = meeting_driver_work.recover_challenge_meeting_drivers()

    assert summary["meetingsScanned"] == 1
    assert summary["backfilled"] == 1
    assert summary["fenced"] == 0
    assert summary["rescheduled"] == 0
    assert calls == []
    restored = meetings.get_meeting_round(team_id, meeting["meetingRoundId"])[
        "meetingRound"
    ]
    # The meeting stays open and now carries a future governed deadline.
    assert restored["status"] == "open"
    assert restored["challengeDeadlineAtMs"] > int(time.time() * 1000)
    assert (
        meeting_driver_work.latest_intent(team_id, meeting["meetingRoundId"]) is None
    )

    # Idempotent: the backfilled deadline is in the future and there is no
    # durable intent, so the second sweep leaves the meeting untouched.
    second = meeting_driver_work.recover_challenge_meeting_drivers()
    assert second["meetingsScanned"] == 1
    assert second["backfilled"] == 0
    assert second["fenced"] == 0
    assert second["skipped"] == 1
    assert calls == []


def test_recovery_leaves_awaiting_approval_and_closed_meetings_alone(
    tmp_path, monkeypatch
):
    _isolate(tmp_path, monkeypatch)
    team_id, agent_ids = _team(tmp_path, monkeypatch)

    # Awaiting approval sits beyond the sweep's open/summarizing window; walk
    # the real four-state flow to get there.
    opened = meeting_runtime.open_hypothesis_review_meeting(
        team_id,
        _selection_payload(agent_ids, "meeting-awaiting-approval"),
        agent_runner=_marker_runner,
        background=False,
    )
    awaiting_id = opened["meetingRound"]["meetingRoundId"]
    meetings.begin_meeting_summary(team_id, awaiting_id, actor=agent_ids[0])
    drafted = meeting_runtime.draft_meeting_digest(team_id, awaiting_id)
    assert drafted["status"] == "awaiting_approval"

    closed = _create_open_meeting(team_id, agent_ids, "meeting-already-closed")
    meetings.terminate_meeting_execution(
        team_id, closed["meetingRoundId"], reason="challenge_workflow_run_cancelled"
    )
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(meeting_runtime, "run_meeting_discussion", _recorder(calls))

    summary = meeting_driver_work.recover_challenge_meeting_drivers()

    # Both terminal meetings sit outside the open/summarizing scan window.
    assert summary["meetingsScanned"] == 0
    assert summary["rescheduled"] == 0
    assert summary["fenced"] == 0
    assert summary["backfilled"] == 0
    assert summary["skipped"] == 0
    assert calls == []
    assert (
        meetings.get_meeting_round(team_id, awaiting_id)["meetingRound"]["status"]
        == "awaiting_approval"
    )
    assert (
        meetings.get_meeting_round(team_id, closed["meetingRoundId"])["meetingRound"][
            "status"
        ]
        == "closed"
    )


def test_recovery_does_not_reschedule_failed_work_at_attempt_cap(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    team_id, agent_ids = _team(tmp_path, monkeypatch)
    meeting = _create_open_meeting(team_id, agent_ids, "meeting-attempt-cap")
    meeting_round_id = meeting["meetingRoundId"]
    # Three exhausted attempts: the latest durable state is failed at the cap.
    meeting_driver_work.record_intent(team_id, meeting_round_id, status="pending")
    for _ in range(3):
        meeting_driver_work.record_intent(team_id, meeting_round_id, status="running")
        meeting_driver_work.record_intent(team_id, meeting_round_id, status="failed")
    exhausted = meeting_driver_work.latest_intent(team_id, meeting_round_id)
    assert exhausted["status"] == "failed"
    assert exhausted["attemptCount"] == 3
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(meeting_runtime, "run_meeting_discussion", _recorder(calls))

    summary = meeting_driver_work.recover_challenge_meeting_drivers()

    assert summary["meetingsScanned"] == 1
    assert summary["rescheduled"] == 0
    assert summary["skipped"] == 1
    assert calls == []
    still = meeting_driver_work.latest_intent(team_id, meeting_round_id)
    assert still["status"] == "failed"
    assert still["attemptCount"] == 3


def test_recovery_is_idempotent_across_consecutive_runs(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    team_id, agent_ids = _team(tmp_path, monkeypatch)
    expired = _create_open_meeting(
        team_id,
        agent_ids,
        "meeting-idem-expired",
        modelInvocationReceiptAuthority={
            "schemaVersion": 1,
            "authorityKind": "workflow_run",
            "teamId": team_id,
            "questionId": "SCI-096",
            "workflowRunId": "run-idem",
            "workflowId": "challenge-cup-research",
            "workflowVersionId": "wv-idem",
            "modelPolicySha256": "b" * 64,
        },
    )
    expired = _expire_deadline(
        team_id, expired, int(time.time() * 1000) - 60_000
    )
    assert expired["challengeDeadlineAtMs"] < int(time.time() * 1000)
    resumable = _create_open_meeting(team_id, agent_ids, "meeting-idem-resumable")
    meeting_driver_work.record_intent(team_id, resumable["meetingRoundId"], status="pending")
    meeting_driver_work.reset_for_tests()
    _ready_to_drive(
        monkeypatch,
        {
            **resumable,
            "linkedChatRoomId": "room-idem",
            "chatRoomRoundIds": ["round-idem"],
        },
    )
    executor = _DeferredExecutor()
    monkeypatch.setattr(meeting_runtime, "_MEETING_DISCUSSION_EXECUTOR", executor)
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(meeting_runtime, "run_meeting_discussion", _recorder(calls))

    first = meeting_driver_work.recover_challenge_meeting_drivers()
    assert first == {
        "teams": 1,
        "meetingsScanned": 2,
        "fenced": 1,
        "backfilled": 0,
        "rescheduled": 1,
        "skipped": 0,
    }
    assert len(executor.submissions) == 1

    second = meeting_driver_work.recover_challenge_meeting_drivers()
    # The fenced meeting is closed and the rescheduled one is protected by the
    # in-process dedup set, so the second sweep is a no-op.
    assert second["teams"] == 1
    assert second["meetingsScanned"] == 1
    assert second["fenced"] == 0
    assert second["backfilled"] == 0
    assert second["rescheduled"] == 0
    assert second["skipped"] == 1
    assert len(executor.submissions) == 1
    assert calls == []
