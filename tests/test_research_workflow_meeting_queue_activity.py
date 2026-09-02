"""Queued discussion driver activity renewal (P2 review-executor stale queue).

The meeting discussion executor is process-wide with four workers and an
unbounded submission queue.  Under multi-question x multi-candidate fan-out a
scheduled driver can wait far past the 15-minute execution-heartbeat window
(``hypothesis_first_state_v2._EXECUTION_HEARTBEAT_STALE_AFTER_SECONDS``) that
the V2 projection uses to flag zombie meetings and expose ``reopen_review``.
A queued driver legitimately writes no meeting or WorkRun activity, so queue
depth used to read exactly like a dead executor.

Covers the narrow contract of ``refresh_queued_meeting_activity``: only a
meeting whose latest ``run_discussion`` intent is still ``pending`` (executor
has not started it) gets a bounded ``queueActivityAt`` stamp once its record
goes quiet past the renewal threshold, so the projection stops misreading
queue wait as ``review_heartbeat_stale``; a genuinely wedged RUNNING driver
is never renewed and keeps going stale (the progress-gated heartbeat fence
stays the sole wedge authority); terminal meetings, fresh meetings, and jobs
without a durable pending intent are skipped; the sweep self-throttles,
isolates broken meetings, and is hosted by the resident maintenance tick.

All content comes from DEV fixtures; no real model or network is involved.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from core.web.services import team_service
from core.web.services.team_workflow import meeting_driver_work
from core.web.services.team_workflow import meeting_rounds as meetings
from core.web.services.team_workflow import meeting_runtime
from core.web.services.team_workflow.research_runtime import (
    service as research_runtime_service_module,
)
from core.web.services.team_workflow.research_runtime.hypothesis_first_state_v2 import (
    _EXECUTION_HEARTBEAT_STALE_AFTER_SECONDS,
    _meeting_heartbeat_stale_problem,
)

from tests._support.team_workflow.helpers import _use_tmp_project_root


@pytest.fixture
def restore_runtime_service_singleton():
    """Keep the research-runtime service singleton test-local."""
    original = research_runtime_service_module._SERVICE
    try:
        yield
    finally:
        research_runtime_service_module._SERVICE = original


def _isolate(tmp_path, monkeypatch):
    """Hermetic store roots plus fresh in-memory sweep/driver state."""

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
    monkeypatch.setattr(
        meeting_driver_work,
        "_record_queue_sweep_event",
        lambda *_args, **_kwargs: None,
    )
    meeting_driver_work.reset_for_tests()
    meeting_driver_work.reset_digest_stuck_sweep_throttle_for_tests()
    meeting_driver_work.reset_queue_sweep_throttle_for_tests()
    with meeting_runtime._MEETING_DISCUSSION_JOBS_LOCK:
        meeting_runtime._MEETING_DISCUSSION_JOBS.clear()
    with meeting_runtime._MEETING_DIGEST_JOBS_LOCK:
        meeting_runtime._MEETING_DIGEST_JOBS.clear()


def _selection_payload(meeting_round_id: str) -> dict:
    return {
        "selectionId": f"sel-{meeting_round_id}",
        "questionId": "SCI-096",
        "selectedCandidateIds": ["cand-a", "cand-b"],
        "decidedBy": "agent-reviewer",
        "meetingRoundId": meeting_round_id,
        "program": "XH-202619",
        "theme": "cc-neuro-001",
        "campaign": "cc-campaign-neuro-001",
        "question": "SCI-096",
        "branch": "main",
        "workflow": "hypothesis_first",
        "agentId": "agent-reviewer",
        "mode": "dev",
        "participants": ["agent-reviewer"],
    }


class _DeferredExecutor:
    """Submit accepts the job but never runs it (the driver stays queued)."""

    def __init__(self):
        self.submissions: list[tuple[object, tuple[object, ...]]] = []

    def submit(self, callback, *args):
        self.submissions.append((callback, args))
        return object()


def _stage_queued_review_meeting(
    tmp_path, monkeypatch, meeting_round_id: str, *, quiet_minutes: int
) -> dict:
    """One real open review meeting with an old ``updatedAt`` plus a driver
    scheduled onto a deferred executor (pending intent, dedup key held)."""

    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    meeting = meetings.create_meeting_round(
        "team-queue-activity", _selection_payload(meeting_round_id)
    )["meetingRound"]
    # Stage the queue-wait shape through the append-only store's latest-wins
    # read: the meeting is bound to a finished opening round and legitimately
    # produced no activity since.
    stale_at = (
        datetime.now(timezone.utc) - timedelta(minutes=quiet_minutes)
    ).isoformat().replace("+00:00", "Z")
    with meetings._LOCK:
        meetings._append_round_record(
            "team-queue-activity",
            {
                **meeting,
                "updatedAt": stale_at,
                "linkedChatRoomId": f"room-{meeting['meetingRoundId']}",
                "chatRoomRoundIds": [f"round-{meeting['meetingRoundId']}"],
            },
        )
    monkeypatch.setattr(meetings, "running_bound_round_ids", lambda *_args: [])
    monkeypatch.setattr(
        meeting_runtime,
        "_latest_bound_round_messages",
        lambda *_args: [{"status": "completed"}],
    )
    monkeypatch.setattr(
        meeting_runtime, "_MEETING_DISCUSSION_EXECUTOR", _DeferredExecutor()
    )
    scheduled = meeting_runtime.schedule_meeting_discussion(
        "team-queue-activity", meeting["meetingRoundId"]
    )
    assert scheduled["status"] == "scheduled"
    intent = meeting_driver_work.latest_intent(
        "team-queue-activity", meeting["meetingRoundId"]
    )
    assert intent["status"] == "pending"
    return meetings.get_meeting_round("team-queue-activity", meeting["meetingRoundId"])[
        "meetingRound"
    ]


def test_queued_driver_stays_beyond_stale_window_without_false_reopen(
    tmp_path, monkeypatch
):
    """A driver queued past the 15-minute window must not read as a zombie.

    Before the sweep the projection flags ``review_heartbeat_stale`` for the
    quiet meeting; after the queue sweep stamps its activity the same
    projection reads a live executing discussion again, so the guarded
    ``reopen_review`` recovery is never surfaced for a healthy queue wait.
    """
    _isolate(tmp_path, monkeypatch)
    assert _EXECUTION_HEARTBEAT_STALE_AFTER_SECONDS == 15 * 60
    meeting = _stage_queued_review_meeting(
        tmp_path, monkeypatch, "meeting-queued-stale", quiet_minutes=16
    )

    # Queue wait alone reproduces the audited false positive.
    stale_problem = _meeting_heartbeat_stale_problem(meeting, None)
    assert stale_problem is not None
    assert stale_problem["code"] == "review_heartbeat_stale"

    summary = meeting_driver_work.refresh_queued_meeting_activity(force=True)

    assert summary["scanned"] == 1
    assert summary["queued"] == 1
    assert summary["renewed"] == 1
    assert summary["skipped"] == 0
    renewed = meetings.get_meeting_round(
        "team-queue-activity", meeting["meetingRoundId"]
    )["meetingRound"]
    assert renewed[meetings.QUEUE_ACTIVITY_MARKER]
    assert renewed["updatedAt"] == renewed[meetings.QUEUE_ACTIVITY_MARKER]
    # The stamp changes nothing else: same status, same lifecycle facts.
    assert renewed["status"] == "open"
    # The projection now reads a live meeting: no stale problem, no reopen.
    assert _meeting_heartbeat_stale_problem(renewed, None) is None

    # Bounded churn: a second pass finds the fresh stamp and rewrites nothing.
    second = meeting_driver_work.refresh_queued_meeting_activity(force=True)
    assert second["queued"] == 1
    assert second["renewed"] == 0
    again = meetings.get_meeting_round(
        "team-queue-activity", meeting["meetingRoundId"]
    )["meetingRound"]
    assert again["updatedAt"] == renewed["updatedAt"]


def test_wedged_running_driver_keeps_going_stale(tmp_path, monkeypatch):
    """A RUNNING driver is never renewed: a real wedge still trips stale.

    The discriminator is the durable intent: once the executor starts the job
    the intent flips to ``running``, and from there the queue sweep must stay
    silent so the existing progress-gated heartbeat fence (and the projection
    stale window) remains the sole wedge authority.
    """
    _isolate(tmp_path, monkeypatch)
    meeting = _stage_queued_review_meeting(
        tmp_path, monkeypatch, "meeting-wedge-stays-stale", quiet_minutes=16
    )
    # The driver started and then wedged: running intent, quiet meeting.
    meeting_driver_work.record_intent(
        "team-queue-activity", meeting["meetingRoundId"], status="running"
    )

    summary = meeting_driver_work.refresh_queued_meeting_activity(force=True)

    assert summary["scanned"] == 0
    assert summary["queued"] == 0
    assert summary["renewed"] == 0
    untouched = meetings.get_meeting_round(
        "team-queue-activity", meeting["meetingRoundId"]
    )["meetingRound"]
    assert meetings.QUEUE_ACTIVITY_MARKER not in untouched
    assert untouched["updatedAt"] == meeting["updatedAt"]
    # The genuine hang keeps surfacing the stale problem and the guarded
    # reopen recovery path.
    stale_problem = _meeting_heartbeat_stale_problem(untouched, None)
    assert stale_problem is not None
    assert stale_problem["code"] == "review_heartbeat_stale"


def test_queue_sweep_skips_fresh_queued_and_intentless_jobs(tmp_path, monkeypatch):
    """Fresh queued meetings and jobs without a durable pending intent stay
    untouched — staleness is proven from durable facts, never guessed."""

    _isolate(tmp_path, monkeypatch)
    fresh = _stage_queued_review_meeting(
        tmp_path, monkeypatch, "meeting-queue-fresh", quiet_minutes=0
    )
    # A scheduled job whose pending intent write was lost (storage outage at
    # schedule time): the sweep cannot prove it is queued, so it must skip.
    intentless_id = "meeting-queue-intentless"
    meetings.create_meeting_round(
        "team-queue-activity", _selection_payload(intentless_id)
    )
    key = ("team-queue-activity", intentless_id)
    with meeting_runtime._MEETING_DISCUSSION_JOBS_LOCK:
        meeting_runtime._MEETING_DISCUSSION_JOBS[key] = "intentless-token"
        meeting_runtime._MEETING_DISCUSSION_JOBS[
            ("team-queue-activity", fresh["meetingRoundId"])
        ] = "fresh-token"

    summary = meeting_driver_work.refresh_queued_meeting_activity(force=True)

    assert summary["scanned"] == 1
    assert summary["queued"] == 1
    assert summary["renewed"] == 0
    assert summary["skipped"] == 1
    fresh_after = meetings.get_meeting_round(
        "team-queue-activity", fresh["meetingRoundId"]
    )["meetingRound"]
    assert meetings.QUEUE_ACTIVITY_MARKER not in fresh_after
    intentless_after = meetings.get_meeting_round(
        "team-queue-activity", intentless_id
    )["meetingRound"]
    assert meetings.QUEUE_ACTIVITY_MARKER not in intentless_after


def test_queue_activity_stamp_guards_terminal_meetings(tmp_path, monkeypatch):
    """Only open/summarizing records take the stamp; terminal meetings keep
    their real timestamps so genuine staleness stays provable."""
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    meeting = meetings.create_meeting_round(
        "team-queue-guard", _selection_payload("meeting-queue-guard")
    )["meetingRound"]
    meetings.terminate_meeting_execution(
        "team-queue-guard",
        meeting["meetingRoundId"],
        reason="challenge_workflow_run_cancelled",
    )

    assert (
        meetings.record_meeting_queue_activity(
            "team-queue-guard", meeting["meetingRoundId"]
        )
        is None
    )
    terminal = meetings.get_meeting_round(
        "team-queue-guard", meeting["meetingRoundId"]
    )["meetingRound"]
    assert meetings.QUEUE_ACTIVITY_MARKER not in terminal

    # An open meeting gets the stamp and keeps every other field byte-equal.
    open_meeting = meetings.create_meeting_round(
        "team-queue-guard", _selection_payload("meeting-queue-guard-open")
    )["meetingRound"]
    stamped = meetings.record_meeting_queue_activity(
        "team-queue-guard", open_meeting["meetingRoundId"], now="2026-09-02T01:00:00Z"
    )
    assert stamped is not None
    for field, value in open_meeting.items():
        if field in {"updatedAt"}:
            continue
        assert stamped[field] == value
    assert stamped["updatedAt"] == "2026-09-02T01:00:00Z"
    assert stamped[meetings.QUEUE_ACTIVITY_MARKER] == "2026-09-02T01:00:00Z"


def test_queue_sweep_throttles_between_ticks(tmp_path, monkeypatch):
    """The sweep is hosted by a fast tick, so it self-throttles; tests bypass
    with force=True or reset the stamp."""
    _isolate(tmp_path, monkeypatch)
    _stage_queued_review_meeting(
        tmp_path, monkeypatch, "meeting-queue-throttle", quiet_minutes=16
    )
    # A realistic epoch base: the sweep also evaluates record staleness
    # against ``now_ms``, so the throttle fixtures share one timeline.
    base_ms = int(time.time() * 1000)

    first = meeting_driver_work.refresh_queued_meeting_activity(now_ms=base_ms)
    assert first.get("throttled") is None
    assert first["renewed"] == 1
    throttled = meeting_driver_work.refresh_queued_meeting_activity(
        now_ms=base_ms + 1_000
    )
    assert throttled.get("throttled") is True
    after_interval = meeting_driver_work.refresh_queued_meeting_activity(
        now_ms=base_ms + meeting_driver_work.QUEUE_SWEEP_INTERVAL_MS + 1
    )
    assert after_interval.get("throttled") is None
    forced = meeting_driver_work.refresh_queued_meeting_activity(
        now_ms=base_ms + meeting_driver_work.QUEUE_SWEEP_INTERVAL_MS + 2,
        force=True,
    )
    assert forced.get("throttled") is None
    meeting_driver_work.reset_queue_sweep_throttle_for_tests()
    after_reset = meeting_driver_work.refresh_queued_meeting_activity(now_ms=base_ms)
    assert after_reset.get("throttled") is None


def test_queue_sweep_isolates_broken_meeting_reads(tmp_path, monkeypatch):
    """One broken meeting read is skipped; the sweep never raises."""
    _isolate(tmp_path, monkeypatch)
    meeting = _stage_queued_review_meeting(
        tmp_path, monkeypatch, "meeting-queue-broken", quiet_minutes=16
    )

    def _explode(*_args, **_kwargs):
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(meetings, "get_meeting_round", _explode)

    summary = meeting_driver_work.refresh_queued_meeting_activity(force=True)

    assert summary["scanned"] == 1
    assert summary["skipped"] == 1
    assert summary["renewed"] == 0
    # The durable record was left exactly as staged.
    untouched = meetings._load_meeting_round(
        "team-queue-activity", meeting["meetingRoundId"]
    )
    assert meetings.QUEUE_ACTIVITY_MARKER not in untouched


def test_maintenance_tick_hosts_queued_activity_refresh(
    tmp_path, monkeypatch, restore_runtime_service_singleton
):
    """run_maintenance_once is the queue-activity sweep host.

    Same minimal-intrusion host pattern as the digest watchdog: the tick peeks
    the meeting-driver sweep (never creates a second scheduler), and the sweep
    itself is owned and covered by the meeting queue-activity tests.
    """
    from core.web.services.team_workflow.research_runtime import (
        service as research_runtime_service_module,
    )
    from core.web.services.team_workflow.research_runtime.runtime_factory import (
        build_workflow_runtime,
    )

    _use_tmp_project_root(tmp_path, monkeypatch)
    runtime = build_workflow_runtime(
        tmp_path / "ledger.sqlite3",
        checkpoint_path=tmp_path / "ledger-checkpoints.sqlite",
    )
    calls: list[dict] = []

    def _sweep(*args, **kwargs):
        calls.append(kwargs)
        return {"scanned": 0, "queued": 0, "renewed": 0, "skipped": 0}

    monkeypatch.setattr(
        meeting_driver_work, "refresh_queued_meeting_activity", _sweep
    )
    try:
        handled = runtime.run_maintenance_once(limit=2)
    finally:
        runtime.close()
    assert calls == [{}]
    assert handled >= 0
