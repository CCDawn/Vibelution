"""Durable challenge meeting driver intent + startup recovery tests.

Covers the T2 lean contract: ``schedule_meeting_discussion`` persists a
durable intent next to ``meeting_rounds.jsonl`` (pending before submit,
completed/failed after the run, failed on submit rejection); running intents
carry a bounded lease that the live driver refreshes through a heartbeat
thread, so the startup sweep ``recover_challenge_meeting_drivers`` re-drives
a running intent whose boot id is foreign OR whose lease has expired —
including same-boot drivers that wedged past their lease.  The sweep fences
deadline-expired open meetings through the existing terminal path (no partial
digest promoted), re-drives interrupted discussions after a simulated process
restart, and stays idempotent across consecutive runs.  Awaiting-approval /
closed meetings are untouched; open meetings without any durable work record
are split by identity: challenge-identity meetings get the governed deadline
backfilled, while identity-less legacy orphans are fenced through the
terminal path because no governed deadline can ever be derived for them;
failed work at the attempt cap is left auditable instead of retried.  Digest
drafts are durable work too (T3): ``draft_meeting_digest`` records a
``run_digest`` intent carrying the source hash and the meeting's governed
deadline, and the sweep re-drives interrupted digest drafts for summarizing
meetings through ``schedule_meeting_digest_redrive`` — blocked re-drives
finalize as failed, fresh same-boot leases are trusted, and summarizing
meetings without any digest intent keep the legacy identity-gap behavior.

All discussion content comes from fake runners (DEV fixtures); no real model
or network is involved.
"""

from __future__ import annotations

import threading
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
    with meeting_runtime._MEETING_DIGEST_JOBS_LOCK:
        meeting_runtime._MEETING_DIGEST_JOBS.clear()


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
        # The runner signature is (teamId, meetingRoundId, jobToken); the
        # durable intent is keyed by the first two.
        intent = meeting_driver_work.latest_intent(args[0], args[1])
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


def _append_intent(team_id: str, meeting_round_id: str, **overrides) -> dict:
    """Stage an intent shape ``record_intent`` cannot write (e.g. expired lease).

    The store is append-only jsonl, so a same-boot wedged driver is staged by
    appending the record exactly as a dead heartbeat would have left it.
    """

    now_ms = int(time.time() * 1000)
    record = {
        "schemaVersion": meeting_driver_work.SCHEMA_VERSION,
        "workId": f"work-staged-{meeting_round_id}",
        "teamId": team_id,
        "meetingRoundId": meeting_round_id,
        "actionKind": meeting_driver_work.ACTION_RUN_DISCUSSION,
        "status": "running",
        "attemptCount": 1,
        "workerBootId": meeting_driver_work.worker_boot_id(),
        "createdAtMs": now_ms,
        "updatedAtMs": now_ms,
        "leaseExpiresAtMs": 0,
        "sourceHash": "",
        "deadlineAtMs": 0,
        "lastProblem": "",
    }
    record.update(overrides)
    from core.web.services.team_workflow.storage_durability import append_jsonl_locked

    append_jsonl_locked(meeting_driver_work.work_path(team_id), record)
    return record


def test_recovery_reschedules_same_boot_running_work_with_expired_lease(
    tmp_path, monkeypatch
):
    _isolate(tmp_path, monkeypatch)
    team_id, agent_ids = _team(tmp_path, monkeypatch)

    # A same-boot driver wedged past its lease: running intent under the
    # current boot id whose heartbeat stopped, leaving an expired lease.
    wedged = _create_open_meeting(team_id, agent_ids, "meeting-lease-expired")
    _append_intent(
        team_id,
        wedged["meetingRoundId"],
        leaseExpiresAtMs=int(time.time() * 1000) - 1000,
    )

    # A healthy same-boot driver mid-flight: its fresh lease must be trusted.
    healthy = _create_open_meeting(team_id, agent_ids, "meeting-lease-fresh")
    meeting_driver_work.record_intent(team_id, healthy["meetingRoundId"], status="pending")
    meeting_driver_work.record_intent(team_id, healthy["meetingRoundId"], status="running")

    _ready_to_drive(
        monkeypatch,
        {**wedged, "linkedChatRoomId": "room-lease", "chatRoomRoundIds": ["round-lease"]},
    )
    executor = _InlineExecutor()
    monkeypatch.setattr(meeting_runtime, "_MEETING_DISCUSSION_EXECUTOR", executor)
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(meeting_runtime, "run_meeting_discussion", _recorder(calls))

    summary = meeting_driver_work.recover_challenge_meeting_drivers()

    assert summary["meetingsScanned"] == 2
    assert summary["rescheduled"] == 1
    assert summary["skipped"] == 1
    assert summary["fenced"] == 0
    assert calls == [(team_id, wedged["meetingRoundId"])]
    re_driven = meeting_driver_work.latest_intent(team_id, wedged["meetingRoundId"])
    assert re_driven["status"] == "completed"
    # The fresh lease was trusted: no second driver was layered on top.
    healthy_after = meeting_driver_work.latest_intent(team_id, healthy["meetingRoundId"])
    assert healthy_after["status"] == "running"
    assert healthy_after["attemptCount"] == 1


def test_heartbeat_extends_lease_without_inflating_attempts(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    team_id = "team-lease-heartbeat"
    round_id = "meeting-lease-heartbeat"
    assert meeting_driver_work.refresh_intent_lease(team_id, "meeting-missing") is None
    meeting_driver_work.record_intent(team_id, round_id, status="pending")
    running = meeting_driver_work.record_intent(team_id, round_id, status="running")
    assert running["attemptCount"] == 1
    assert running["leaseExpiresAtMs"] > running["createdAtMs"]

    refreshed = meeting_driver_work.refresh_intent_lease(team_id, round_id)
    assert refreshed is not None
    assert refreshed["status"] == "running"
    assert refreshed["heartbeat"] is True
    assert refreshed["attemptCount"] == 1
    assert refreshed["leaseExpiresAtMs"] >= running["leaseExpiresAtMs"]
    assert not meeting_driver_work._lease_expired(refreshed, int(time.time() * 1000))
    assert (
        meeting_driver_work.latest_intent(team_id, round_id)["workId"]
        == refreshed["workId"]
    )

    # A foreign boot must never extend the lease (no adoption of another
    # process's driver); the latest record stays untouched.
    meeting_driver_work.reset_for_tests()
    assert meeting_driver_work.refresh_intent_lease(team_id, round_id) is None
    assert (
        meeting_driver_work.latest_intent(team_id, round_id)["workId"]
        == refreshed["workId"]
    )

    # Terminal intents are not heartbeated either.
    meeting_driver_work.reset_for_tests()
    meeting_driver_work.record_intent(team_id, round_id, status="completed")
    assert meeting_driver_work.refresh_intent_lease(team_id, round_id) is None
    assert meeting_driver_work.latest_intent(team_id, round_id)["status"] == "completed"


def test_lease_heartbeat_thread_refreshes_until_stopped(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    team_id = "team-heartbeat-thread"
    round_id = "meeting-heartbeat-thread"
    running = meeting_driver_work.record_intent(team_id, round_id, status="running")
    stop = threading.Event()
    thread = meeting_driver_work.start_lease_heartbeat(
        team_id, round_id, stop_event=stop, interval_ms=10
    )
    deadline = time.monotonic() + 5.0
    latest = running
    while time.monotonic() < deadline:
        latest = meeting_driver_work.latest_intent(team_id, round_id)
        if latest.get("heartbeat"):
            break
        time.sleep(0.01)
    stop.set()
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    assert latest["heartbeat"] is True
    assert latest["attemptCount"] == 1
    assert latest["leaseExpiresAtMs"] >= running["leaseExpiresAtMs"]


def test_driver_wrapper_runs_lease_heartbeat_around_discussion(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    team_id = "team-heartbeat-wiring"
    meeting = {
        "meetingRoundId": "meeting-heartbeat-wiring",
        "status": "open",
        "chatRoomRoundIds": ["round-1"],
    }
    _ready_to_drive(monkeypatch, meeting)
    monkeypatch.setattr(meeting_runtime, "_MEETING_DISCUSSION_EXECUTOR", _InlineExecutor())

    original_start = meeting_driver_work.start_lease_heartbeat
    heartbeats: list[tuple[str, str, threading.Event]] = []

    def spy(team_id_arg, round_id_arg, *, stop_event, **kwargs):
        heartbeats.append((team_id_arg, round_id_arg, stop_event))
        # Long interval: verify wiring without racing the synchronous run.
        return original_start(
            team_id_arg, round_id_arg, stop_event=stop_event, interval_ms=60_000
        )

    monkeypatch.setattr(meeting_driver_work, "start_lease_heartbeat", spy)
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(meeting_runtime, "run_meeting_discussion", _recorder(calls))

    scheduled = meeting_runtime.schedule_meeting_discussion(
        team_id, meeting["meetingRoundId"]
    )
    assert scheduled["status"] == "scheduled"
    assert calls == [(team_id, meeting["meetingRoundId"])]
    assert len(heartbeats) == 1
    assert heartbeats[0][:2] == (team_id, meeting["meetingRoundId"])
    # The wrapper stops the heartbeat before releasing the dedup key.
    assert heartbeats[0][2].is_set()
    completed = meeting_driver_work.latest_intent(team_id, meeting["meetingRoundId"])
    assert completed["status"] == "completed"


def test_recovery_redrives_stale_digest_and_trusts_fresh_lease(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    team_id, agent_ids = _team(tmp_path, monkeypatch)

    # Case A: the digest LLM call was interrupted by a process restart. The
    # running record belongs to a foreign boot, so the sweep re-drives it
    # through the real idempotent summary-draft state machine; the meeting has
    # no completed discussion output, so the re-drive finalizes as blocked.
    interrupted = _amend_meeting(
        team_id,
        _create_open_meeting(team_id, agent_ids, "meeting-digest-stale"),
        status="summarizing",
    )
    _append_intent(
        team_id,
        interrupted["meetingRoundId"],
        actionKind=meeting_driver_work.ACTION_RUN_DIGEST,
        workerBootId="foreign-boot",
        leaseExpiresAtMs=int(time.time() * 1000) + 60_000,
        sourceHash="a" * 64,
    )

    # Case B: digest work already failed at the attempt cap: left auditable.
    capped = _amend_meeting(
        team_id,
        _create_open_meeting(team_id, agent_ids, "meeting-digest-cap"),
        status="summarizing",
    )
    _append_intent(
        team_id,
        capped["meetingRoundId"],
        actionKind=meeting_driver_work.ACTION_RUN_DIGEST,
        status="failed",
        attemptCount=3,
        lastProblem="digest_redrive_blocked:discussion_has_no_completed_messages",
    )

    # Case C: a digest draft still inside its crash-fence lease is trusted.
    healthy = _amend_meeting(
        team_id,
        _create_open_meeting(team_id, agent_ids, "meeting-digest-fresh"),
        status="summarizing",
    )
    meeting_driver_work.record_intent(
        team_id,
        healthy["meetingRoundId"],
        status="running",
        action_kind=meeting_driver_work.ACTION_RUN_DIGEST,
        source_hash="b" * 64,
    )

    discussion_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        meeting_runtime, "run_meeting_discussion", _recorder(discussion_calls)
    )
    executor = _InlineExecutor()
    monkeypatch.setattr(meeting_runtime, "_MEETING_DISCUSSION_EXECUTOR", executor)

    summary = meeting_driver_work.recover_challenge_meeting_drivers()

    assert summary["meetingsScanned"] == 3
    assert summary["rescheduled"] == 1
    assert summary["skipped"] == 2
    assert summary["fenced"] == 0
    assert summary["backfilled"] == 0
    # A digest re-drive never layers a second discussion driver on top.
    assert discussion_calls == []
    assert len(executor.submissions) == 1
    redriven = meeting_driver_work.latest_intent(
        team_id,
        interrupted["meetingRoundId"],
        action_kind=meeting_driver_work.ACTION_RUN_DIGEST,
    )
    assert redriven["status"] == "failed"
    assert (
        redriven["lastProblem"]
        == "digest_redrive_blocked:discussion_has_no_completed_messages"
    )
    # The blocked finalization inherited the identity of the interrupted work.
    assert redriven["sourceHash"] == "a" * 64
    assert redriven["workerBootId"] == "foreign-boot"
    # Digest work never enters the discussion namespace.
    assert (
        meeting_driver_work.latest_intent(team_id, interrupted["meetingRoundId"])
        is None
    )
    assert (
        meeting_driver_work.latest_intent(
            team_id,
            healthy["meetingRoundId"],
            action_kind=meeting_driver_work.ACTION_RUN_DIGEST,
        )["status"]
        == "running"
    )
    assert (
        meetings.get_meeting_round(team_id, interrupted["meetingRoundId"])[
            "meetingRound"
        ]["status"]
        == "summarizing"
    )


def test_digest_roundtrip_persists_source_hash_and_reuse_redrive_completes(
    tmp_path, monkeypatch
):
    _isolate(tmp_path, monkeypatch)
    team_id, agent_ids = _team(tmp_path, monkeypatch)
    opened = meeting_runtime.open_hypothesis_review_meeting(
        team_id,
        _selection_payload(agent_ids, "meeting-digest-durable"),
        agent_runner=_marker_runner,
        background=False,
    )
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]
    meetings.begin_meeting_summary(team_id, meeting_round_id, actor=agent_ids[0])
    drafted = meeting_runtime.draft_meeting_digest(team_id, meeting_round_id)
    assert drafted["status"] == "awaiting_approval"

    stored = meetings.get_meeting_round(team_id, meeting_round_id)["meetingRound"]
    source_hash = str(stored["digestDraft"]["sourceMessageContentHash"] or "")
    assert source_hash
    intent = meeting_driver_work.latest_intent(
        team_id, meeting_round_id, action_kind=meeting_driver_work.ACTION_RUN_DIGEST
    )
    assert intent["status"] == "completed"
    assert intent["sourceHash"] == source_hash
    assert intent["attemptCount"] == 1
    assert meeting_driver_work.latest_intent(team_id, meeting_round_id) is None

    # Replay the hang shape: the draft landed but the process died before the
    # intent was closed out. The re-drive must reuse the hash-matched draft
    # instead of paying for a second model call.
    _amend_meeting(team_id, stored, status="summarizing")
    _append_intent(
        team_id,
        meeting_round_id,
        workId="work-staged-digest-crash",
        actionKind=meeting_driver_work.ACTION_RUN_DIGEST,
        leaseExpiresAtMs=int(time.time() * 1000) - 1000,
        sourceHash=source_hash,
    )

    def _no_second_model_call(*_args, **_kwargs):
        raise AssertionError("digest re-drive must reuse the hash-matched draft")

    monkeypatch.setattr(meeting_runtime, "draft_meeting_digest", _no_second_model_call)
    executor = _InlineExecutor()
    monkeypatch.setattr(meeting_runtime, "_MEETING_DISCUSSION_EXECUTOR", executor)

    summary = meeting_driver_work.recover_challenge_meeting_drivers()

    assert summary["meetingsScanned"] == 1
    assert summary["rescheduled"] == 1
    assert summary["fenced"] == 0
    assert len(executor.submissions) == 1
    recovered = meetings.get_meeting_round(team_id, meeting_round_id)["meetingRound"]
    assert recovered["status"] == "awaiting_approval"
    finalized = meeting_driver_work.latest_intent(
        team_id, meeting_round_id, action_kind=meeting_driver_work.ACTION_RUN_DIGEST
    )
    assert finalized["status"] == "completed"
    assert finalized["sourceHash"] == source_hash

    # Idempotent: the meeting left the summarizing window, so a second sweep
    # submits nothing even though the completed record is the latest state.
    second = meeting_driver_work.recover_challenge_meeting_drivers()
    assert second["meetingsScanned"] == 0
    assert second["rescheduled"] == 0
    assert len(executor.submissions) == 1


def test_digest_intent_lease_clamps_to_deadline_and_inherits_identity(
    tmp_path, monkeypatch
):
    _isolate(tmp_path, monkeypatch)
    team_id = "team-digest-store"
    round_id = "meeting-digest-store"
    digest = meeting_driver_work.ACTION_RUN_DIGEST

    with pytest.raises(meeting_driver_work.MeetingDriverWorkError):
        meeting_driver_work.record_intent(
            team_id, round_id, status="running", action_kind="run_review"
        )

    now_ms = int(time.time() * 1000)
    deadline = now_ms + 5_000
    pending = meeting_driver_work.record_intent(
        team_id,
        round_id,
        status="pending",
        action_kind=digest,
        source_hash="f" * 64,
        deadline_at_ms=deadline,
    )
    assert pending["leaseExpiresAtMs"] == 0
    assert pending["sourceHash"] == "f" * 64
    assert pending["deadlineAtMs"] == deadline

    # The crash fence never outlives the governed meeting deadline.
    running = meeting_driver_work.record_intent(
        team_id, round_id, status="running", action_kind=digest
    )
    assert running["leaseExpiresAtMs"] == deadline
    assert running["attemptCount"] == 1
    assert running["sourceHash"] == "f" * 64

    failed = meeting_driver_work.record_intent(
        team_id,
        round_id,
        status="failed",
        action_kind=digest,
        last_problem="RuntimeError: digest exploded",
    )
    assert failed["leaseExpiresAtMs"] == 0
    assert failed["sourceHash"] == "f" * 64
    assert failed["deadlineAtMs"] == deadline
    assert failed["attemptCount"] == 1

    # A generous deadline keeps the full digest crash-fence lease.
    roomy = meeting_driver_work.record_intent(
        team_id,
        "meeting-digest-roomy",
        status="running",
        action_kind=digest,
        deadline_at_ms=now_ms + 3_600_000,
    )
    assert roomy["leaseExpiresAtMs"] >= now_ms + meeting_driver_work.DIGEST_INTENT_LEASE_MS
    assert roomy["leaseExpiresAtMs"] < roomy["deadlineAtMs"]

    # The two action kinds keep separate durable timelines per meeting.
    discussion = meeting_driver_work.record_intent(
        team_id, round_id, status="running", action_kind=meeting_driver_work.ACTION_RUN_DISCUSSION
    )
    assert discussion["leaseExpiresAtMs"] == (
        discussion["createdAtMs"] + meeting_driver_work.DEFAULT_INTENT_LEASE_MS
    )
    assert (
        meeting_driver_work.latest_intent(team_id, round_id, action_kind=digest)[
            "status"
        ]
        == "failed"
    )


def test_wedged_driver_heartbeat_fences_attempt_and_redrives_in_run(
    tmp_path, monkeypatch
):
    """T1: a driver wedged inside an unbounded blocking call loses its lease.

    The heartbeat is progress-gated: once the driver stops advancing its
    progress stamp past one maximal bounded step, the heartbeat stops
    renewing, fences the attempt as failed, and re-drives the meeting
    in-run.  The wedged attempt is superseded at its next boundary and can
    neither release the replacement's dedup registration nor clobber the
    replacement's terminal intent.
    """
    _isolate(tmp_path, monkeypatch)
    team_id, agent_ids = _team(tmp_path, monkeypatch)
    meeting = _create_open_meeting(team_id, agent_ids, "meeting-wedged-driver")
    wedged_view = {
        **meeting,
        "linkedChatRoomId": "room-wedged",
        "chatRoomRoundIds": ["round-wedged"],
    }
    _ready_to_drive(monkeypatch, wedged_view)

    release_first = threading.Event()
    first_entered = threading.Event()
    calls: list[tuple[str, str]] = []

    def wedged_runner(team_id_arg, meeting_round_id_arg):
        calls.append((team_id_arg, meeting_round_id_arg))
        if len(calls) == 1:
            first_entered.set()
            release_first.wait(timeout=30.0)
        return {"stopReason": "converged"}

    monkeypatch.setattr(meeting_runtime, "run_meeting_discussion", wedged_runner)

    class _ThreadExecutor:
        def __init__(self):
            self.threads: list[threading.Thread] = []

        def submit(self, callback, *args):
            thread = threading.Thread(target=callback, args=args, daemon=True)
            thread.start()
            self.threads.append(thread)
            return object()

    executor = _ThreadExecutor()
    monkeypatch.setattr(meeting_runtime, "_MEETING_DISCUSSION_EXECUTOR", executor)
    monkeypatch.setattr(meeting_driver_work, "HEARTBEAT_INTERVAL_MS", 20)
    monkeypatch.setattr(meeting_driver_work, "discussion_step_window_ms", lambda: 150)

    scheduled = meeting_runtime.schedule_meeting_discussion(
        team_id, meeting["meetingRoundId"]
    )
    assert scheduled["status"] == "scheduled"
    assert first_entered.wait(timeout=5.0)

    # The re-drive runs to completion while the first attempt stays wedged.
    deadline = time.monotonic() + 10.0
    latest = None
    while time.monotonic() < deadline:
        latest = meeting_driver_work.latest_intent(team_id, meeting["meetingRoundId"])
        if str(latest.get("status") or "") == "completed":
            break
        time.sleep(0.02)
    assert latest is not None and latest["status"] == "completed"
    assert latest["attemptCount"] == 2
    assert len(calls) >= 2

    trail = meeting_driver_work._read_records(
        meeting_driver_work.work_path(team_id)
    )
    assert any(
        str(item.get("status") or "") == "failed"
        and item.get("lastProblem") == meeting_driver_work.WEDGED_DRIVER_PROBLEM
        for item in trail
    )

    # The superseded attempt unwinds without touching the replacement.
    release_first.set()
    for thread in executor.threads:
        thread.join(timeout=5.0)
    final = meeting_driver_work.latest_intent(team_id, meeting["meetingRoundId"])
    assert final["status"] == "completed"
    assert final["attemptCount"] == 2
    key = (team_id, meeting["meetingRoundId"])
    with meeting_runtime._MEETING_DISCUSSION_JOBS_LOCK:
        assert key not in meeting_runtime._MEETING_DISCUSSION_JOBS
        assert key not in meeting_runtime._MEETING_DISCUSSION_SESSIONS


def test_sweep_redrives_expired_lease_despite_held_dedup_job(tmp_path, monkeypatch):
    """T1: an expired lease proves the same-boot dedup holder is wedged.

    The startup sweep evicts the stale holder and re-drives; a live driver
    with a fresh lease keeps its dedup registration untouched.
    """
    _isolate(tmp_path, monkeypatch)
    team_id, agent_ids = _team(tmp_path, monkeypatch)
    wedged = _create_open_meeting(team_id, agent_ids, "meeting-sweep-wedged")
    healthy = _create_open_meeting(team_id, agent_ids, "meeting-sweep-healthy")

    wedged_view = {
        **wedged,
        "linkedChatRoomId": "room-sweep-wedged",
        "chatRoomRoundIds": ["round-sweep-wedged"],
    }
    healthy_view = {
        **healthy,
        "linkedChatRoomId": "room-sweep-healthy",
        "chatRoomRoundIds": ["round-sweep-healthy"],
    }
    _ready_to_drive(monkeypatch, wedged_view)

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(meeting_runtime, "run_meeting_discussion", _recorder(calls))
    executor = _InlineExecutor()
    monkeypatch.setattr(meeting_runtime, "_MEETING_DISCUSSION_EXECUTOR", executor)

    # Simulate a same-boot wedged driver: the dedup registry is held and the
    # running intent's lease has expired (a live driver never lets that
    # happen — the progress-gated heartbeat keeps renewing it).
    wedged_key = (team_id, wedged["meetingRoundId"])
    healthy_key = (team_id, healthy["meetingRoundId"])
    with meeting_runtime._MEETING_DISCUSSION_JOBS_LOCK:
        meeting_runtime._MEETING_DISCUSSION_JOBS[wedged_key] = "wedged-token"
        meeting_runtime._MEETING_DISCUSSION_SESSIONS[wedged_key] = "wedged-token"
        meeting_runtime._MEETING_DISCUSSION_JOBS[healthy_key] = "healthy-token"
        meeting_runtime._MEETING_DISCUSSION_SESSIONS[healthy_key] = "healthy-token"
    meeting_driver_work.record_intent(
        team_id, wedged["meetingRoundId"], status="pending"
    )
    running = meeting_driver_work.record_intent(
        team_id, wedged["meetingRoundId"], status="running"
    )
    _append_intent(
        team_id,
        wedged["meetingRoundId"],
        workId="work-staged-wedged-expired",
        leaseExpiresAtMs=int(running["createdAtMs"]) - 1000,
    )
    meeting_driver_work.record_intent(
        team_id, healthy["meetingRoundId"], status="running"
    )

    summary = meeting_driver_work.recover_challenge_meeting_drivers()

    assert summary["rescheduled"] == 1
    assert summary["skipped"] >= 1
    assert calls == [(team_id, wedged["meetingRoundId"])]
    redriven = meeting_driver_work.latest_intent(
        team_id, wedged["meetingRoundId"]
    )
    assert redriven["status"] == "completed"
    # The expired-lease holder was evicted, the fresh-lease holder was not.
    with meeting_runtime._MEETING_DISCUSSION_JOBS_LOCK:
        assert meeting_runtime._MEETING_DISCUSSION_JOBS.get(wedged_key) is None
        assert (
            meeting_runtime._MEETING_DISCUSSION_JOBS.get(healthy_key)
            == "healthy-token"
        )


def test_discussion_intent_and_heartbeat_clamp_to_meeting_deadline(
    tmp_path, monkeypatch
):
    """T1: the discussion RUNNING lease and every heartbeat renewal are
    clamped to the governed meeting deadline like the digest lease."""
    _isolate(tmp_path, monkeypatch)
    team_id = "team-clamp"
    round_id = "meeting-clamp"
    now_ms = int(time.time() * 1000)
    tight_deadline = now_ms + 5_000

    running = meeting_driver_work.record_intent(
        team_id, round_id, status="running", deadline_at_ms=tight_deadline
    )
    assert running["leaseExpiresAtMs"] == tight_deadline

    refreshed = meeting_driver_work.refresh_intent_lease(team_id, round_id)
    assert refreshed is not None
    assert refreshed["heartbeat"] is True
    assert refreshed["leaseExpiresAtMs"] == tight_deadline
    assert refreshed["deadlineAtMs"] == tight_deadline

    # A generous deadline keeps the full discussion lease.
    roomy = meeting_driver_work.record_intent(
        team_id,
        "meeting-clamp-roomy",
        status="running",
        deadline_at_ms=now_ms + 3_600_000,
    )
    assert roomy["leaseExpiresAtMs"] == (
        roomy["createdAtMs"] + meeting_driver_work.DEFAULT_INTENT_LEASE_MS
    )


def test_lease_and_step_window_track_effective_llm_timeout(
    tmp_path, monkeypatch
):
    """T4: digest lease and the discussion stale-progress window derive from
    the effective review-call timeout (>= historical 480s floor), so a
    configured 600s timeout can never be re-driven as stale mid-call."""
    _isolate(tmp_path, monkeypatch)
    team_id = "team-derived-lease"
    digest = meeting_driver_work.ACTION_RUN_DIGEST

    monkeypatch.setattr(
        meeting_driver_work, "effective_review_call_timeout_seconds", lambda: 600.0
    )
    slow = meeting_driver_work.record_intent(
        team_id,
        "meeting-derived-slow",
        status="running",
        action_kind=digest,
        deadline_at_ms=int(time.time() * 1000) + 3_600_000,
    )
    assert (
        slow["leaseExpiresAtMs"] - slow["createdAtMs"]
        >= 600_000 + meeting_driver_work.DIGEST_LEASE_MARGIN_MS
    )
    assert meeting_driver_work.discussion_step_window_ms() == (
        600_000 * meeting_driver_work.DISCUSSION_STEP_ALLOWANCE_CALLS
        + meeting_driver_work.DISCUSSION_STEP_MARGIN_MS
    )

    # A short effective timeout never under-covers the historical floor.
    monkeypatch.setattr(
        meeting_driver_work, "effective_review_call_timeout_seconds", lambda: 100.0
    )
    floored = meeting_driver_work.record_intent(
        team_id,
        "meeting-derived-floored",
        status="running",
        action_kind=digest,
        deadline_at_ms=int(time.time() * 1000) + 3_600_000,
    )
    assert (
        floored["leaseExpiresAtMs"] - floored["createdAtMs"]
        == meeting_driver_work.DIGEST_INTENT_LEASE_MS
    )

    # The discussion heartbeat lease itself stays the short crash window.
    discussion = meeting_driver_work.record_intent(
        team_id, "meeting-derived-discussion", status="running"
    )
    assert discussion["leaseExpiresAtMs"] == (
        discussion["createdAtMs"] + meeting_driver_work.DEFAULT_INTENT_LEASE_MS
    )


def test_effective_review_timeout_env_override_is_honored(
    tmp_path, monkeypatch
):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("VIBELUTION_REVIEW_LLM_CALL_TIMEOUT_SECONDS", "550")
    assert meeting_driver_work.effective_review_call_timeout_seconds() == 550.0
