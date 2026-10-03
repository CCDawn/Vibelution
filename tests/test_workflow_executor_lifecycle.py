from __future__ import annotations

import threading
import time

import pytest

from core.infrastructure.owned_executor import OwnedThreadPoolExecutor
from core.web.services import chat_room_service
from core.web.services.team_workflow import meeting_runtime
from core.web.services.team_workflow.research_runtime import hypothesis_command_attempts


def _held_task(started: threading.Event, release: threading.Event) -> None:
    started.set()
    assert release.wait(3)


def _wait_for_start(executor: OwnedThreadPoolExecutor) -> tuple[threading.Event, threading.Event]:
    started = threading.Event()
    release = threading.Event()
    executor.submit(_held_task, started, release)
    assert started.wait(1)
    return started, release


def test_chat_room_pools_reject_cancel_and_reopen_only_after_physical_exit(monkeypatch):
    room_pool = OwnedThreadPoolExecutor(1, "test-room-lifecycle")
    speaker_pool = OwnedThreadPoolExecutor(1, "test-speaker-lifecycle")
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_EXECUTOR", room_pool)
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_SPEAKER_BATCH_EXECUTOR", speaker_pool)
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_LIFECYCLE_FAILURES", set())
    monkeypatch.setattr(chat_room_service, "force_stop_active_chat_room_rounds_for_shutdown", lambda *_: [])

    assert chat_room_service.begin_chat_room_lifecycle()["opened"]
    _, room_release = _wait_for_start(room_pool)
    _, speaker_release = _wait_for_start(speaker_pool)
    queued_room = room_pool.submit(lambda: None)
    queued_speaker = speaker_pool.submit(lambda: None)

    assert chat_room_service.stop_chat_room_admission()["closed"]
    assert queued_room.cancelled()
    assert queued_speaker.cancelled()
    with pytest.raises(RuntimeError, match="shutting down"):
        room_pool.submit(lambda: None)
    with pytest.raises(RuntimeError, match="shutting down"):
        speaker_pool.submit(lambda: None)

    first = chat_room_service.shutdown_chat_room_executors(
        deadline=time.monotonic() + 0.02
    )
    assert not first["closed"]
    assert first["pendingThreads"]
    assert not chat_room_service.begin_chat_room_lifecycle()["opened"]

    room_release.set()
    speaker_release.set()
    drained = chat_room_service.shutdown_chat_room_executors(
        deadline=time.monotonic() + 2
    )
    assert drained["closed"]
    assert chat_room_service.begin_chat_room_lifecycle() == {
        "opened": True,
        "recreated": True,
    }


def test_chat_room_speaker_pool_stays_lazy_and_cannot_open_during_shutdown(monkeypatch):
    room_pool = OwnedThreadPoolExecutor(1, "test-room-lazy-lifecycle")
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_EXECUTOR", room_pool)
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_SPEAKER_BATCH_EXECUTOR", None)
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_LIFECYCLE_STOPPING", False)
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_LIFECYCLE_FAILURES", set())
    monkeypatch.setattr(chat_room_service, "force_stop_active_chat_room_rounds_for_shutdown", lambda *_: [])

    assert chat_room_service.begin_chat_room_lifecycle() == {
        "opened": True,
        "recreated": False,
    }
    assert chat_room_service._CHAT_ROOM_SPEAKER_BATCH_EXECUTOR is None
    assert chat_room_service.stop_chat_room_admission()["closed"]
    with pytest.raises(RuntimeError, match="shutting down"):
        chat_room_service._speaker_batch_executor()
    assert chat_room_service._CHAT_ROOM_SPEAKER_BATCH_EXECUTOR is None

    drained = chat_room_service.shutdown_chat_room_executors(
        deadline=time.monotonic() + 2
    )
    assert drained["closed"]
    assert chat_room_service.begin_chat_room_lifecycle()["opened"]
    speaker_pool = chat_room_service._speaker_batch_executor()
    assert isinstance(speaker_pool, OwnedThreadPoolExecutor)
    speaker_pool.shutdown(wait=True, cancel_futures=True)


def test_chat_room_unknown_executor_is_not_reported_closed():
    result = chat_room_service._executor_shutdown_until(
        object(), time.monotonic() + 0.1
    )
    assert not result["closed"]
    assert result["failed"] == ["unowned_executor_unverifiable"]


def test_canceled_chat_room_round_releases_quota_and_stop_control(monkeypatch):
    pool = OwnedThreadPoolExecutor(1, "test-room-queued-round")
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_EXECUTOR", pool)
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_SPEAKER_BATCH_EXECUTOR", None)
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_LIFECYCLE_STOPPING", False)
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_LIFECYCLE_FAILURES", set())
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_INFLIGHT_COUNT", 0)
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_ROUND_CONTROLS", {})

    def request_stop(_reason):
        chat_room_service._request_chat_room_round_stop("queued-round", "shutdown")
        return []

    monkeypatch.setattr(
        chat_room_service, "force_stop_active_chat_room_rounds_for_shutdown", request_stop
    )
    assert chat_room_service.begin_chat_room_lifecycle()["opened"]
    started, release = _wait_for_start(pool)
    assert chat_room_service._try_acquire_chat_room_inflight()
    chat_room_service._create_chat_room_round_control("queued-room", "queued-round")
    queued = chat_room_service._submit_chat_room_round_background(
        "queued-room", "queued-round", {}, {}, [], lambda *_: {}, "en", None
    )
    assert chat_room_service._CHAT_ROOM_INFLIGHT_COUNT == 1

    assert chat_room_service.stop_chat_room_admission()["closed"]
    assert queued.cancelled()
    assert chat_room_service._CHAT_ROOM_INFLIGHT_COUNT == 0
    assert not chat_room_service._chat_room_round_has_process_control("queued-round")
    release.set()
    assert started.is_set()
    assert chat_room_service.shutdown_chat_room_executors(
        deadline=time.monotonic() + 2
    )["closed"]
    assert chat_room_service.begin_chat_room_lifecycle()["opened"]
    assert chat_room_service._try_acquire_chat_room_inflight()
    chat_room_service._release_chat_room_inflight()
    assert chat_room_service._CHAT_ROOM_INFLIGHT_COUNT == 0


def test_running_chat_room_round_releases_quota_once(monkeypatch):
    pool = OwnedThreadPoolExecutor(1, "test-room-running-round")
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_EXECUTOR", pool)
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_SPEAKER_BATCH_EXECUTOR", None)
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_LIFECYCLE_STOPPING", False)
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_LIFECYCLE_FAILURES", set())
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_INFLIGHT_COUNT", 0)
    monkeypatch.setattr(
        chat_room_service, "force_stop_active_chat_room_rounds_for_shutdown", lambda *_: []
    )
    started = threading.Event()
    release = threading.Event()

    def run_round(*_args):
        started.set()
        assert release.wait(3)

    monkeypatch.setattr(chat_room_service, "_run_chat_room_round_background", run_round)
    assert chat_room_service.begin_chat_room_lifecycle()["opened"]
    assert chat_room_service._try_acquire_chat_room_inflight()
    running = chat_room_service._submit_chat_room_round_background(
        "running-room", "running-round", {}, {}, [], lambda *_: {}, "en", None
    )
    assert started.wait(1)
    assert chat_room_service._CHAT_ROOM_INFLIGHT_COUNT == 1
    release.set()
    running.result(timeout=2)
    assert chat_room_service._CHAT_ROOM_INFLIGHT_COUNT == 0
    assert chat_room_service._try_acquire_chat_room_inflight()
    chat_room_service._release_chat_room_inflight()
    assert chat_room_service._CHAT_ROOM_INFLIGHT_COUNT == 0
    assert chat_room_service.shutdown_chat_room_executors(
        deadline=time.monotonic() + 2
    )["closed"]


def test_meeting_pool_canceled_queue_fails_intent_and_waits_for_running_thread(monkeypatch):
    pool = OwnedThreadPoolExecutor(1, "test-meeting-lifecycle")
    monkeypatch.setattr(meeting_runtime, "_MEETING_DISCUSSION_EXECUTOR", pool)
    monkeypatch.setattr(meeting_runtime, "_MEETING_EXECUTOR_STOPPING", False)
    monkeypatch.setattr(meeting_runtime, "_MEETING_EXECUTOR_STOPPING_KEYS", set())
    monkeypatch.setattr(meeting_runtime, "_MEETING_EXECUTOR_LIFECYCLE_FAILURES", set())
    monkeypatch.setattr(meeting_runtime, "_MEETING_EXECUTOR_FUTURES", {})
    monkeypatch.setattr(meeting_runtime, "_MEETING_CANCELLED_EXECUTOR_JOBS", [])
    monkeypatch.setattr(meeting_runtime, "_record_driver_work_state", lambda *args, **kwargs: True)
    monkeypatch.setattr(meeting_runtime, "_release_discussion_session", lambda *args: None)

    meeting_runtime._MEETING_DISCUSSION_JOBS[("live-team", "live-round")] = "live-token"
    meeting_runtime._MEETING_DISCUSSION_SESSIONS[("live-team", "live-round")] = "live-token"
    meeting_runtime._MEETING_DIGEST_JOBS.add(("digest-team", "digest-round"))
    assert meeting_runtime.begin_meeting_discussion_lifecycle() == {
        "opened": True,
        "recreated": False,
    }
    assert ("live-team", "live-round") in meeting_runtime._MEETING_DISCUSSION_JOBS
    assert meeting_runtime._MEETING_DISCUSSION_SESSIONS[("live-team", "live-round")] == "live-token"
    assert ("digest-team", "digest-round") in meeting_runtime._MEETING_DIGEST_JOBS
    _, release = _wait_for_start(pool)
    queued = meeting_runtime._submit_meeting_executor(
        lambda: None,
        kind="discussion",
        team_id="test-team",
        meeting_round_id="test-meeting",
        job_token="test-token",
    )

    stop = meeting_runtime.stop_meeting_discussion_admission()
    assert stop["closed"]
    assert stop["cancelledQueuedJobs"] == 1
    assert queued.cancelled()
    with pytest.raises(RuntimeError, match="shutting down"):
        meeting_runtime._submit_meeting_executor(
            lambda: None,
            kind="discussion",
            team_id="test-team",
            meeting_round_id="another-meeting",
        )
    first = meeting_runtime.shutdown_meeting_discussion_executor(
        deadline=time.monotonic() + 0.02
    )
    assert not first["closed"]
    assert not meeting_runtime.begin_meeting_discussion_lifecycle()["opened"]

    release.set()
    drained = meeting_runtime.shutdown_meeting_discussion_executor(
        deadline=time.monotonic() + 2
    )
    assert drained["closed"]
    assert meeting_runtime.begin_meeting_discussion_lifecycle()["opened"]


def test_meeting_heartbeat_blocked_in_io_is_drained_before_reopen(monkeypatch):
    pool = OwnedThreadPoolExecutor(1, "test-meeting-heartbeat-lifecycle")
    monkeypatch.setattr(meeting_runtime, "_MEETING_DISCUSSION_EXECUTOR", pool)
    monkeypatch.setattr(meeting_runtime, "_MEETING_EXECUTOR_STOPPING", False)
    monkeypatch.setattr(meeting_runtime, "_MEETING_EXECUTOR_STOPPING_KEYS", set())
    monkeypatch.setattr(meeting_runtime, "_MEETING_EXECUTOR_LIFECYCLE_FAILURES", set())
    monkeypatch.setattr(meeting_runtime, "_MEETING_EXECUTOR_FUTURES", {})
    monkeypatch.setattr(meeting_runtime, "_MEETING_CANCELLED_EXECUTOR_JOBS", [])
    monkeypatch.setattr(meeting_runtime, "_MEETING_DISCUSSION_JOBS", {})
    monkeypatch.setattr(meeting_runtime, "_MEETING_DISCUSSION_SESSIONS", {})
    monkeypatch.setattr(meeting_runtime, "_MEETING_DIGEST_JOBS", set())
    monkeypatch.setattr(meeting_runtime, "_record_driver_work_state", lambda *args, **kwargs: True)

    entered_io = threading.Event()
    release_io = threading.Event()

    def blocked_refresh(*_args):
        entered_io.set()
        assert release_io.wait(3)

    monkeypatch.setattr(meeting_runtime.meeting_driver_work, "refresh_intent_lease", blocked_refresh)
    stop_event = threading.Event()
    heartbeat = meeting_runtime.meeting_driver_work.start_lease_heartbeat(
        "blocked-team",
        "blocked-round",
        stop_event=stop_event,
        interval_ms=10,
    )
    assert entered_io.wait(1)

    first = meeting_runtime.shutdown_meeting_discussion_executor(
        deadline=time.monotonic() + 0.02
    )
    assert stop_event.is_set()
    assert not first["closed"]
    assert first["pendingCount"] == 1
    assert heartbeat.name in first["pendingThreads"]
    reopened = meeting_runtime.begin_meeting_discussion_lifecycle()
    assert not reopened["opened"]
    assert reopened["pendingThreads"] == [heartbeat.name]

    release_io.set()
    heartbeat.join(timeout=2)
    assert not heartbeat.is_alive()
    drained = meeting_runtime.shutdown_meeting_discussion_executor(
        deadline=time.monotonic() + 2
    )
    assert drained["closed"]
    assert meeting_runtime.begin_meeting_discussion_lifecycle() == {
        "opened": True,
        "recreated": True,
    }
    pool.shutdown(wait=True, cancel_futures=True)


def test_command_pool_canceled_queue_is_durably_failed_and_reopens_after_drain(monkeypatch):
    pool = OwnedThreadPoolExecutor(1, "test-command-lifecycle")
    monkeypatch.setattr(hypothesis_command_attempts, "_COMMAND_EXECUTOR", pool)
    monkeypatch.setattr(hypothesis_command_attempts, "_COMMAND_LIFECYCLE_STOPPING", False)
    monkeypatch.setattr(hypothesis_command_attempts, "_COMMAND_LIFECYCLE_FAILURES", set())
    monkeypatch.setattr(hypothesis_command_attempts, "_COMMAND_FUTURES", {})
    monkeypatch.setattr(hypothesis_command_attempts, "_COMMAND_CANCELLED_ATTEMPTS", [])
    monkeypatch.setattr(hypothesis_command_attempts, "_ACTIVE_ATTEMPTS", set())
    transitions: list[tuple[str, str]] = []
    monkeypatch.setattr(
        hypothesis_command_attempts,
        "finish_attempt",
        lambda attempt, *, status, **kwargs: transitions.append(
            (str(attempt.get("attemptId")), status)
        ),
    )

    assert hypothesis_command_attempts.begin_hypothesis_command_lifecycle()["opened"]
    _, release = _wait_for_start(pool)
    queued_attempt = {
        "attemptId": "queued-at-shutdown",
        "teamId": "test-team",
        "questionId": "Q1",
        "command": "approve_summary",
    }
    hypothesis_command_attempts.submit_execution(queued_attempt, lambda: {"ok": True})

    stop = hypothesis_command_attempts.stop_hypothesis_command_admission()
    assert stop["closed"]
    assert stop["cancelledQueuedAttempts"] == 1
    assert transitions == [("queued-at-shutdown", hypothesis_command_attempts.STATUS_FAILED)]
    with pytest.raises(RuntimeError, match="shutting down"):
        hypothesis_command_attempts.submit_execution(
            {"attemptId": "rejected", "teamId": "test-team"}, dict
        )
    first = hypothesis_command_attempts.shutdown_hypothesis_command_executor(
        deadline=time.monotonic() + 0.02
    )
    assert not first["closed"]
    assert not hypothesis_command_attempts.begin_hypothesis_command_lifecycle()["opened"]

    release.set()
    drained = hypothesis_command_attempts.shutdown_hypothesis_command_executor(
        deadline=time.monotonic() + 2
    )
    assert drained["closed"]
    assert hypothesis_command_attempts.begin_hypothesis_command_lifecycle()["opened"]
