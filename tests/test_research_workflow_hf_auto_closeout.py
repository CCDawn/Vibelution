"""Challenge hypothesis-chain auto closeout tests.

Covers the 2026-09 four-part fix for "the challenge chain runs a while and
then wedges":

1. Fence closeout completeness — every Challenge fence (deadline, restart,
   legacy orphan, operator chat-room stop) now writes failure terminal state
   onto the owning generation/review attempts and supersedes live digest
   work, idempotently, for all three gap shapes (open dead-silent, open with
   history rounds, summarizing with a failed digest);
2. Missing-digest scheduling — a discussion whose last bound round completed
   with citable speech gets ``run_digest`` scheduled by the periodic sweep,
   and a terminal-failed digest work is re-driven under a hard cap of 2;
3. The auto-executor — a fenced review meeting whose discussion really
   completed is redriven through the existing ``retry_review_dispatch`` path
   (exactly once, newest-attempt-guarded, ``HARD_ROUND_LIMIT``-capped), and a
   fenced digest-less generation attempt is superseded + retried through the
   existing ``retry_generation`` internal path;
4. Candidate-generation digest auto-approval — the (default zero-TTL,
   immediate) digest auto-approve covers ``hypothesis_candidate_generation``
   behind a quality gate (zero validation errors, at least one proposed
   candidate); a failing gate keeps the human gate and emits a reminder
   event.

All content is faked at the store/monkeypatch level; no real model, network,
or product runtime is involved.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from core.web.services import team_service
from core.web.services.team_workflow import meeting_driver_work
from core.web.services.team_workflow import meeting_rounds
from core.web.services.team_workflow import meeting_runtime
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain as chain,
)

from tests._support.team_workflow.helpers import _use_tmp_project_root

_TEAM_ID = "team-hf-auto-closeout"
_QUESTION_ID = "SCI-008"

_BASE_TS = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def _offset_iso(offset_seconds: float) -> str:
    return (_BASE_TS - timedelta(seconds=offset_seconds)).isoformat().replace(
        "+00:00", "Z"
    )


def _offset_ms(offset_seconds: float) -> int:
    return int((_BASE_TS - timedelta(seconds=offset_seconds)).timestamp() * 1000)


def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Hermetic store roots for meeting rounds, chain ledger, driver work."""

    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(meeting_rounds, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chain, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(
        meeting_runtime,
        "_record_meeting_discussion_driver_event",
        lambda *_args, **_kwargs: None,
    )
    meeting_driver_work.reset_for_tests()
    meeting_runtime.reset_digest_missing_sweep_throttle_for_tests()
    with meeting_runtime._MEETING_DIGEST_JOBS_LOCK:
        meeting_runtime._MEETING_DIGEST_JOBS.clear()


def _seed_meeting(record: dict[str, Any]) -> None:
    path = meeting_rounds._rounds_path(_TEAM_ID)
    path.parent.mkdir(parents=True, exist_ok=True)
    meeting_rounds._append_jsonl(path, record)


def _fenced_meeting_record(
    meeting_id: str,
    *,
    meeting_type: str,
    status: str = "open",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = {
        "meetingRoundId": meeting_id,
        "question": _QUESTION_ID,
        "meetingType": meeting_type,
        "status": status,
        "participants": ["agent-a"],
        "chatRoomRoundIds": ["round-1"],
        "discussionItemRefs": [],
        "startedAt": "2026-09-01T00:00:00Z",
        # MeetingRound contract scope identity (required by the store).
        "program": "XH-202619",
        "theme": "cc-neuro-001",
        "campaign": "cc-campaign-neuro-001",
        "branch": "main",
        "workflow": "hypothesis_first",
        "agentId": "agent-a",
        "mode": "dev",
    }
    record["scopeHash"] = chain.scope_hash_for(
        **{field: record[field] for field in chain._SCOPE_FIELDS},
        agent_id=record["agentId"],
        mode=record["mode"],
    )
    record.update(extra or {})
    return record


def _seed_review_dispatch_attempt(
    meeting_id: str,
    *,
    selection_id: str = "sel-closeout-1",
    candidate_id: str = "cand-closeout-a",
    round_index: int = 1,
) -> dict[str, Any]:
    """Queue then complete one review dispatch attempt bound to a meeting."""

    chain._append_review_dispatch_attempt_state(
        _TEAM_ID,
        question_id=_QUESTION_ID,
        selection_id=selection_id,
        selection_version="v1",
        candidate_id=candidate_id,
        round_index=round_index,
        lifecycle="queued",
    )
    return chain._append_review_dispatch_attempt_state(
        _TEAM_ID,
        question_id=_QUESTION_ID,
        selection_id=selection_id,
        selection_version="v1",
        candidate_id=candidate_id,
        round_index=round_index,
        lifecycle="completed",
        outcome="succeeded",
        meeting_round_id=meeting_id,
    )


def _seed_generation_attempt(
    meeting_id: str,
    attempt_number: int = 1,
    *,
    lifecycle: str = "running",
) -> dict[str, Any]:
    return chain._append_generation_attempt_state(
        _TEAM_ID,
        question_id=_QUESTION_ID,
        attempt_id=f"gen-attempt-{attempt_number}",
        attempt_number=attempt_number,
        meeting_round_id=meeting_id,
        lifecycle=lifecycle,
    )


def _latest_review_attempt_records() -> list[dict[str, Any]]:
    return chain._review_dispatch_attempts(chain._read_jsonl(chain._storage_path(_TEAM_ID)))


def _latest_generation_attempt_records() -> list[dict[str, Any]]:
    return chain._generation_attempts(chain._read_jsonl(chain._storage_path(_TEAM_ID)))


# ---------------------------------------------------------------------------
# spec 1: fence closeout writes attempt terminal state, idempotently


@pytest.mark.parametrize(
    "meeting_id,status,extra",
    [
        pytest.param(
            "meeting-open-dead-silent",
            "open",
            {"chatRoomRoundIds": ["round-1"]},
            id="open_dead_silent_last_round",
        ),
        pytest.param(
            "meeting-open-history",
            "open",
            {"chatRoomRoundIds": ["round-1", "round-2"]},
            id="open_with_history_rounds",
        ),
        pytest.param(
            "meeting-summarizing-failed-digest",
            "summarizing",
            {"chatRoomRoundIds": ["round-1"]},
            id="summarizing_with_failed_digest",
        ),
    ],
)
def test_fence_closeout_writes_attempt_terminal_state_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    meeting_id: str,
    status: str,
    extra: dict[str, Any],
) -> None:
    """三种围栏缺口形态：关会 → 生成/评审 attempt 失败终态 + 活 digest work
    superseded；重复收口不二次写。"""
    _isolate(tmp_path, monkeypatch)
    _seed_meeting(
        _fenced_meeting_record(
            meeting_id,
            meeting_type=chain.HYPOTHESIS_REVIEW_MEETING_TYPE,
            status=status,
            extra=extra,
        )
    )
    review_attempt = _seed_review_dispatch_attempt(meeting_id)
    _seed_generation_attempt(meeting_id)
    meeting_driver_work.record_intent(
        _TEAM_ID,
        meeting_id,
        status=meeting_driver_work.STATUS_RUNNING,
        action_kind=meeting_driver_work.ACTION_RUN_DIGEST,
    )
    if status == "summarizing":
        # The summarizing gap shape carries a terminal-failed digest work.
        meeting_driver_work.record_intent(
            _TEAM_ID,
            meeting_id,
            status=meeting_driver_work.STATUS_FAILED,
            action_kind=meeting_driver_work.ACTION_RUN_DIGEST,
            last_problem="digest_draft_stuck",
        )

    # The fence: terminate, then the shared closeout bridge.
    meeting_rounds.terminate_meeting_execution(
        _TEAM_ID, meeting_id, reason="challenge_deadline"
    )
    meeting_runtime.closeout_fenced_meeting(
        _TEAM_ID, meeting_id, reason="challenge_deadline"
    )

    review_latest = [
        item
        for item in _latest_review_attempt_records()
        if str(item.get("attemptId") or "") == str(review_attempt.get("attemptId"))
    ][-1]
    assert str(review_latest.get("lifecycle") or "") == "failed"
    assert str(review_latest.get("outcome") or "") == "superseded"
    assert str(review_latest.get("errorType") or "") == "ReviewMeetingClosed"
    assert "challenge_deadline" in str(review_latest.get("error") or "")

    generation_latest = _latest_generation_attempt_records()[-1]
    assert str(generation_latest.get("lifecycle") or "") == "failed"
    assert "challenge_deadline" in str(generation_latest.get("error") or "")

    digest_latest = meeting_driver_work.latest_intent(
        _TEAM_ID, meeting_id, action_kind=meeting_driver_work.ACTION_RUN_DIGEST
    )
    # A live digest work is superseded; a terminal-failed one stays failed —
    # either way nothing live survives the fence.
    assert str(digest_latest.get("status") or "") not in {
        meeting_driver_work.STATUS_PENDING,
        meeting_driver_work.STATUS_RUNNING,
    }

    # Idempotency: a repeated fence sweep must not write a second time.
    chain_records_before = len(chain._read_jsonl(chain._storage_path(_TEAM_ID)))
    work_records_before = len(
        meeting_driver_work._read_records(meeting_driver_work.work_path(_TEAM_ID))
    )
    meeting_runtime.closeout_fenced_meeting(
        _TEAM_ID, meeting_id, reason="challenge_deadline"
    )
    assert len(chain._read_jsonl(chain._storage_path(_TEAM_ID))) == chain_records_before
    assert (
        len(meeting_driver_work._read_records(meeting_driver_work.work_path(_TEAM_ID)))
        == work_records_before
    )


def test_fence_closeout_supersedes_live_digest_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """已终态（failed）的 digest work 不被收口改写；活 work 才 superseded。"""
    _isolate(tmp_path, monkeypatch)
    meeting_id = "meeting-digest-terminal"
    _seed_meeting(
        _fenced_meeting_record(
            meeting_id,
            meeting_type=chain.CANDIDATE_GENERATION_MEETING_TYPE,
            status="summarizing",
        )
    )
    meeting_driver_work.record_intent(
        _TEAM_ID,
        meeting_id,
        status=meeting_driver_work.STATUS_FAILED,
        action_kind=meeting_driver_work.ACTION_RUN_DIGEST,
        last_problem="digest_draft_stuck",
    )
    meeting_runtime.closeout_fenced_meeting(
        _TEAM_ID, meeting_id, reason="legacy_orphan_closeout"
    )
    digest_latest = meeting_driver_work.latest_intent(
        _TEAM_ID, meeting_id, action_kind=meeting_driver_work.ACTION_RUN_DIGEST
    )
    assert str(digest_latest.get("status") or "") == meeting_driver_work.STATUS_FAILED


def test_chat_room_stop_finalize_closes_review_attempt_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """聊天室停止路径：评审会的 dispatch attempt 一并失败终态（此前只有
    candgen 会被关闭）。"""
    _isolate(tmp_path, monkeypatch)
    meeting_id = "meeting-room-stop-review"
    _seed_meeting(
        _fenced_meeting_record(
            meeting_id,
            meeting_type=chain.HYPOTHESIS_REVIEW_MEETING_TYPE,
            status="open",
        )
    )
    _seed_review_dispatch_attempt(meeting_id)

    result = meeting_runtime.finalize_stopped_meeting_after_chat_round(
        {"config": {"teamId": _TEAM_ID}},
        {
            "config": {"meetingRoundId": meeting_id},
            "terminalReason": "challenge_deadline",
        },
    )

    assert str(result.get("status") or "") == "stopped"
    review_latest = _latest_review_attempt_records()[-1]
    assert str(review_latest.get("lifecycle") or "") == "failed"
    assert str(review_latest.get("outcome") or "") == "superseded"


def test_startup_sweep_deadline_fence_closes_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """startup sweep 的 deadline 围栏同样走收口：candgen attempt 失败终态。"""
    _isolate(tmp_path, monkeypatch)
    meeting_id = "meeting-sweep-fence"
    _seed_meeting(
        _fenced_meeting_record(
            meeting_id,
            meeting_type=chain.CANDIDATE_GENERATION_MEETING_TYPE,
            status="open",
            extra={"challengeDeadlineAtMs": 1_000},
        )
    )
    _seed_generation_attempt(meeting_id)

    from core.web.services.team_workflow import meeting_driver_work as driver

    outcome = driver._recover_one_meeting(
        _TEAM_ID,
        meeting_id,
        dict(
            meeting_rounds.get_meeting_round(_TEAM_ID, meeting_id)["meetingRound"]
        ),
        now_ms=2_000,
    )

    assert outcome == "fenced"
    generation_latest = _latest_generation_attempt_records()[-1]
    assert str(generation_latest.get("lifecycle") or "") == "failed"
    assert "challenge_deadline" in str(generation_latest.get("error") or "")


# ---------------------------------------------------------------------------
# spec 2: missing-digest scheduling sweep


def _digest_sweep_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> list[dict[str, Any]]:
    scheduled: list[tuple[str, str]] = []

    def _schedule(team_id: str, meeting_round_id: str):
        scheduled.append((team_id, meeting_round_id))
        return {"status": "scheduled", "teamId": team_id}

    monkeypatch.setattr(
        meeting_runtime, "schedule_meeting_digest_redrive", _schedule
    )
    return scheduled


def test_missing_digest_sweep_schedules_completed_open_meeting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """open 末轮有 completed 非 pass 发言且无 digest 产物 → 调度 run_digest。"""
    _isolate(tmp_path, monkeypatch)
    scheduled = _digest_sweep_env(tmp_path, monkeypatch)
    meeting_id = "meeting-open-completed"
    _seed_meeting(
        _fenced_meeting_record(
            meeting_id,
            meeting_type=chain.HYPOTHESIS_REVIEW_MEETING_TYPE,
            status="open",
        )
    )
    monkeypatch.setattr(meeting_rounds, "running_bound_round_ids", lambda _m: [])
    monkeypatch.setattr(
        meeting_rounds,
        "completed_latest_bound_round_source_messages",
        lambda _m: [{"status": "completed", "content": "AGREE: 证据充分"}],
    )

    summary = meeting_runtime.sweep_meetings_missing_digest(
        now_ms=1_000_000, force=True
    )

    assert summary["scheduled"] == 1
    assert scheduled == [(_TEAM_ID, meeting_id)]


def test_missing_digest_sweep_redrives_failed_digest_within_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """summarizing + digest 终态 failed 且未超上限 → 重投。"""
    _isolate(tmp_path, monkeypatch)
    scheduled = _digest_sweep_env(tmp_path, monkeypatch)
    meeting_id = "meeting-summarizing-failed"
    _seed_meeting(
        _fenced_meeting_record(
            meeting_id,
            meeting_type=chain.HYPOTHESIS_REVIEW_MEETING_TYPE,
            status="summarizing",
        )
    )
    meeting_driver_work.record_intent(
        _TEAM_ID,
        meeting_id,
        status=meeting_driver_work.STATUS_FAILED,
        action_kind=meeting_driver_work.ACTION_RUN_DIGEST,
        last_problem="llm timeout",
    )
    monkeypatch.setattr(
        meeting_rounds,
        "completed_meeting_source_messages",
        lambda _m: [{"status": "completed", "content": "AGREE: 证据充分"}],
    )

    summary = meeting_runtime.sweep_meetings_missing_digest(
        now_ms=1_000_000, force=True
    )

    assert summary["scheduled"] == 1
    assert scheduled == [(_TEAM_ID, meeting_id)]


def test_missing_digest_sweep_stops_at_redrive_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """digest failed 达到重投上限（默认 2）→ 不再投，留人工重试。"""
    _isolate(tmp_path, monkeypatch)
    scheduled = _digest_sweep_env(tmp_path, monkeypatch)
    meeting_id = "meeting-summarizing-capped"
    _seed_meeting(
        _fenced_meeting_record(
            meeting_id,
            meeting_type=chain.HYPOTHESIS_REVIEW_MEETING_TYPE,
            status="summarizing",
        )
    )
    # Two consumed attempts (initial run + one redrive) reach the cap.
    # attemptCount only advances on RUNNING records; FAILED inherits it.
    for _round in range(2):
        meeting_driver_work.record_intent(
            _TEAM_ID,
            meeting_id,
            status=meeting_driver_work.STATUS_RUNNING,
            action_kind=meeting_driver_work.ACTION_RUN_DIGEST,
        )
        meeting_driver_work.record_intent(
            _TEAM_ID,
            meeting_id,
            status=meeting_driver_work.STATUS_FAILED,
            action_kind=meeting_driver_work.ACTION_RUN_DIGEST,
        )
    latest = meeting_driver_work.latest_intent(
        _TEAM_ID, meeting_id, action_kind=meeting_driver_work.ACTION_RUN_DIGEST
    )
    assert meeting_driver_work._attempt_count(latest) == (
        meeting_runtime.MAX_DIGEST_AUTO_REDRIVE_ATTEMPTS
    )
    monkeypatch.setattr(
        meeting_rounds,
        "completed_meeting_source_messages",
        lambda _m: [{"status": "completed", "content": "AGREE"}],
    )

    summary = meeting_runtime.sweep_meetings_missing_digest(
        now_ms=1_000_000, force=True
    )

    assert summary["scheduled"] == 0
    assert scheduled == []


def test_missing_digest_sweep_skips_live_work_and_existing_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """活 digest work（running）与已有 digest 产物的会议都不投。"""
    _isolate(tmp_path, monkeypatch)
    scheduled = _digest_sweep_env(tmp_path, monkeypatch)
    live_id = "meeting-digest-live"
    _seed_meeting(
        _fenced_meeting_record(
            live_id,
            meeting_type=chain.HYPOTHESIS_REVIEW_MEETING_TYPE,
            status="summarizing",
        )
    )
    meeting_driver_work.record_intent(
        _TEAM_ID,
        live_id,
        status=meeting_driver_work.STATUS_RUNNING,
        action_kind=meeting_driver_work.ACTION_RUN_DIGEST,
    )
    drafted_id = "meeting-digest-drafted"
    _seed_meeting(
        _fenced_meeting_record(
            drafted_id,
            meeting_type=chain.HYPOTHESIS_REVIEW_MEETING_TYPE,
            status="summarizing",
            extra={"digestDraft": {"contentHash": "hash-1"}},
        )
    )
    monkeypatch.setattr(
        meeting_rounds,
        "completed_meeting_source_messages",
        lambda _m: [{"status": "completed", "content": "AGREE"}],
    )
    monkeypatch.setattr(meeting_rounds, "running_bound_round_ids", lambda _m: [])
    monkeypatch.setattr(
        meeting_rounds,
        "completed_latest_bound_round_source_messages",
        lambda _m: [{"status": "completed", "content": "AGREE"}],
    )

    summary = meeting_runtime.sweep_meetings_missing_digest(
        now_ms=1_000_000, force=True
    )

    assert summary["scheduled"] == 0
    assert scheduled == []


def test_missing_digest_sweep_is_self_throttled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同一周期只扫一次：节流窗口内的第二次调用是 no-op。"""
    _isolate(tmp_path, monkeypatch)
    scheduled = _digest_sweep_env(tmp_path, monkeypatch)
    _seed_meeting(
        _fenced_meeting_record(
            "meeting-throttled",
            meeting_type=chain.HYPOTHESIS_REVIEW_MEETING_TYPE,
            status="open",
        )
    )
    monkeypatch.setattr(meeting_rounds, "running_bound_round_ids", lambda _m: [])
    monkeypatch.setattr(
        meeting_rounds,
        "completed_latest_bound_round_source_messages",
        lambda _m: [{"status": "completed", "content": "AGREE"}],
    )

    first = meeting_runtime.sweep_meetings_missing_digest(now_ms=1_000_000)
    second = meeting_runtime.sweep_meetings_missing_digest(now_ms=1_015_000)

    assert first.get("scheduled") == 1
    assert second.get("throttled") is True
    assert scheduled == [(_TEAM_ID, "meeting-throttled")]


# ---------------------------------------------------------------------------
# spec 3: the auto-executor for fenced review / generation attempts


def test_auto_redrive_fenced_review_meeting_dispatches_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """被围栏关闭且讨论真完成的评审会 → retry_review_dispatch 恰好一次；
    幂等：dispatch identity 已有更新 attempt 时不再重驱。"""
    _isolate(tmp_path, monkeypatch)
    meeting_id = "meeting-fenced-review"
    _seed_meeting(
        _fenced_meeting_record(
            meeting_id,
            meeting_type=chain.HYPOTHESIS_REVIEW_MEETING_TYPE,
            status="closed",
            extra={"executionStatus": "stopped", "terminalReason": "challenge_deadline"},
        )
    )
    chain._append_jsonl(
        chain._storage_path(_TEAM_ID),
        {
            "schemaVersion": 1,
            "recordKind": chain.REVIEW_ROUND_LINK_KIND,
            "linkId": "link-1",
            "meetingRoundId": meeting_id,
            "selectionId": "sel-redrive-1",
            "candidateId": "cand-redrive-a",
            "questionId": _QUESTION_ID,
            "roundIndex": 1,
            "createdAt": "2026-09-01T00:00:00Z",
        },
    )
    _seed_review_dispatch_attempt(
        meeting_id, selection_id="sel-redrive-1", candidate_id="cand-redrive-a"
    )
    monkeypatch.setattr(
        meeting_rounds,
        "completed_latest_bound_round_source_messages",
        lambda _m: [{"status": "completed", "content": "AGREE: 证据充分"}],
    )
    dispatched: list[tuple[str, str, list[str]]] = []

    def _retry(team_id: str, selection_id: str, candidate_ids: list[str]):
        dispatched.append((team_id, selection_id, list(candidate_ids)))
        return {"status": "opened"}

    monkeypatch.setattr(chain, "retry_review_dispatch", _retry)

    summary = chain.auto_redrive_fenced_review_meeting(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert summary["redriven"] == 1
    assert dispatched == [(_TEAM_ID, "sel-redrive-1", ["cand-redrive-a"])]

    # Simulate the ledger state a real redrive leaves behind: a newer
    # attempt (number 2) now owns the dispatch identity.
    chain._append_review_dispatch_attempt_state(
        _TEAM_ID,
        question_id=_QUESTION_ID,
        selection_id="sel-redrive-1",
        selection_version="v1",
        candidate_id="cand-redrive-a",
        round_index=1,
        lifecycle="failed",
    )
    chain._append_review_dispatch_attempt_state(
        _TEAM_ID,
        question_id=_QUESTION_ID,
        selection_id="sel-redrive-1",
        selection_version="v1",
        candidate_id="cand-redrive-a",
        round_index=1,
        lifecycle="queued",
    )
    summary = chain.auto_redrive_fenced_review_meeting(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert summary["redriven"] == 0
    assert len(dispatched) == 1


def test_auto_redrive_skips_dead_silent_and_capped_meetings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """末轮死寂的围栏会与已达 HARD 上限的 dispatch identity 不重驱。"""
    _isolate(tmp_path, monkeypatch)
    dispatched: list[tuple[str, str, list[str]]] = []

    def _retry(team_id: str, selection_id: str, candidate_ids: list[str]):
        dispatched.append((team_id, selection_id, list(candidate_ids)))
        return {"status": "opened"}

    monkeypatch.setattr(chain, "retry_review_dispatch", _retry)
    # Dead-silent latest round: the discussion did NOT truly complete.
    _seed_meeting(
        _fenced_meeting_record(
            "meeting-fenced-silent",
            meeting_type=chain.HYPOTHESIS_REVIEW_MEETING_TYPE,
            status="closed",
            extra={"executionStatus": "stopped", "terminalReason": "challenge_deadline"},
        )
    )
    chain._append_jsonl(
        chain._storage_path(_TEAM_ID),
        {
            "schemaVersion": 1,
            "recordKind": chain.REVIEW_ROUND_LINK_KIND,
            "linkId": "link-silent",
            "meetingRoundId": "meeting-fenced-silent",
            "selectionId": "sel-silent",
            "candidateId": "cand-silent-a",
            "questionId": _QUESTION_ID,
            "roundIndex": 1,
            "createdAt": "2026-09-01T00:00:00Z",
        },
    )
    _seed_review_dispatch_attempt(
        "meeting-fenced-silent", selection_id="sel-silent", candidate_id="cand-silent-a"
    )
    monkeypatch.setattr(
        meeting_rounds, "completed_latest_bound_round_source_messages", lambda _m: []
    )

    summary = chain.auto_redrive_fenced_review_meeting(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert summary["redriven"] == 0
    assert dispatched == []

    # Attempt cap: HARD_ROUND_LIMIT attempts for the identity stop the hop.
    for attempt_number in range(2, chain.HARD_ROUND_LIMIT + 1):
        chain._append_review_dispatch_attempt_state(
            _TEAM_ID,
            question_id=_QUESTION_ID,
            selection_id="sel-silent",
            selection_version="v1",
            candidate_id="cand-silent-a",
            round_index=1,
            lifecycle="failed",
        )
        chain._append_review_dispatch_attempt_state(
            _TEAM_ID,
            question_id=_QUESTION_ID,
            selection_id="sel-silent",
            selection_version="v1",
            candidate_id="cand-silent-a",
            round_index=1,
            lifecycle="queued",
        )
    monkeypatch.setattr(
        meeting_rounds,
        "completed_latest_bound_round_source_messages",
        lambda _m: [{"status": "completed", "content": "AGREE"}],
    )
    summary = chain.auto_redrive_fenced_review_meeting(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert summary["redriven"] == 0
    assert dispatched == []


def test_auto_redrive_is_one_hop_per_question(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """每 sweep 每题最多一跳：多个合格围栏会一次只重驱一个。"""
    _isolate(tmp_path, monkeypatch)
    dispatched: list[tuple[str, str, list[str]]] = []

    def _retry(team_id: str, selection_id: str, candidate_ids: list[str]):
        dispatched.append((team_id, selection_id, list(candidate_ids)))
        return {"status": "opened"}

    monkeypatch.setattr(chain, "retry_review_dispatch", _retry)
    for index in (1, 2):
        meeting_id = f"meeting-fenced-multi-{index}"
        _seed_meeting(
            _fenced_meeting_record(
                meeting_id,
                meeting_type=chain.HYPOTHESIS_REVIEW_MEETING_TYPE,
                status="closed",
                extra={
                    "executionStatus": "stopped",
                    "terminalReason": "challenge_deadline",
                },
            )
        )
        chain._append_jsonl(
            chain._storage_path(_TEAM_ID),
            {
                "schemaVersion": 1,
                "recordKind": chain.REVIEW_ROUND_LINK_KIND,
                "linkId": f"link-multi-{index}",
                "meetingRoundId": meeting_id,
                "selectionId": f"sel-multi-{index}",
                "candidateId": f"cand-multi-{index}",
                "questionId": _QUESTION_ID,
                "roundIndex": 1,
                "createdAt": "2026-09-01T00:00:00Z",
            },
        )
        _seed_review_dispatch_attempt(
            meeting_id,
            selection_id=f"sel-multi-{index}",
            candidate_id=f"cand-multi-{index}",
        )
    monkeypatch.setattr(
        meeting_rounds,
        "completed_latest_bound_round_source_messages",
        lambda _m: [{"status": "completed", "content": "AGREE"}],
    )

    summary = chain.auto_redrive_fenced_review_meeting(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    # One hop per sweep per question: the scan stops at the first redrive.
    assert summary["redriven"] == 1
    assert len(dispatched) == 1


def test_auto_retry_fenced_generation_attempt_supersedes_and_retries_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """candgen 会 closed 无 digest → 走 retry-generation 内部路径自动
    supersede 重试恰好一次；已有更新 attempt / 带 digest / 达上限不重试。"""
    _isolate(tmp_path, monkeypatch)
    meeting_id = "meeting-fenced-candgen"
    _seed_meeting(
        _fenced_meeting_record(
            meeting_id,
            meeting_type=chain.CANDIDATE_GENERATION_MEETING_TYPE,
            status="closed",
            extra={"executionStatus": "stopped", "terminalReason": "challenge_deadline"},
        )
    )
    _seed_generation_attempt(meeting_id)
    chain.fail_generation_attempt_for_meeting(
        _TEAM_ID, meeting_id, reason="challenge_deadline"
    )
    opened: list[tuple[str, str]] = []
    monkeypatch.setattr(
        chain, "resolve_stage_one_generation_launch", lambda *_a, **_k: {}
    )

    def _open(team_id: str, question_id: str, **_kwargs):
        opened.append((team_id, question_id))
        return {"status": "opened"}

    monkeypatch.setattr(chain, "open_candidate_generation_meeting", _open)

    summary = chain.auto_retry_fenced_generation_attempt(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert summary["retried"] == 1
    assert opened == [(_TEAM_ID, _QUESTION_ID)]

    # A newer attempt (the retry's own attempt) blocks a second hop.
    _seed_generation_attempt("meeting-fenced-candgen-next", attempt_number=2)
    summary = chain.auto_retry_fenced_generation_attempt(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert summary["retried"] == 0
    assert len(opened) == 1


def test_auto_retry_generation_skips_digest_and_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """带 digest 产物的围栏会不重试；attempt 数达 HARD 上限也不重试。"""
    _isolate(tmp_path, monkeypatch)
    opened: list[tuple[str, str]] = []
    monkeypatch.setattr(
        chain, "resolve_stage_one_generation_launch", lambda *_a, **_k: {}
    )

    def _open(team_id: str, question_id: str, **_kwargs):
        opened.append((team_id, question_id))
        return {"status": "opened"}

    monkeypatch.setattr(chain, "open_candidate_generation_meeting", _open)
    # 1) digest product present -> not eligible.
    _seed_meeting(
        _fenced_meeting_record(
            "meeting-candgen-with-digest",
            meeting_type=chain.CANDIDATE_GENERATION_MEETING_TYPE,
            status="closed",
            extra={
                "executionStatus": "stopped",
                "digestDraft": {"contentHash": "hash-1"},
            },
        )
    )
    _seed_generation_attempt("meeting-candgen-with-digest")
    summary = chain.auto_retry_fenced_generation_attempt(
        _TEAM_ID, question_id=_QUESTION_ID
    )
    assert summary["retried"] == 0
    assert opened == []

    # 2) HARD_ROUND_LIMIT attempts consumed -> not eligible.
    for attempt_number in range(1, chain.HARD_ROUND_LIMIT + 1):
        _seed_generation_attempt(
            f"meeting-candgen-capped-{attempt_number}", attempt_number=attempt_number
        )
    _seed_meeting(
        _fenced_meeting_record(
            "meeting-candgen-capped-3",
            meeting_type=chain.CANDIDATE_GENERATION_MEETING_TYPE,
            status="closed",
            extra={"executionStatus": "stopped"},
        )
    )
    summary = chain.auto_retry_fenced_generation_attempt(
        _TEAM_ID, question_id=_QUESTION_ID
    )
    assert summary["retried"] == 0
    assert opened == []


def test_auto_advance_sweep_counts_redrives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sweep_auto_advance_closure 汇总新执行者计数（step four/five 接线）。"""
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(
        chain,
        "question_ids_with_chain_records",
        lambda _team_id: [_QUESTION_ID],
    )
    monkeypatch.setattr(
        chain,
        "_team_ids_with_chain_storage",
        lambda: [_TEAM_ID],
    )

    def _noop_review(_team_id, *, question_id):
        return {"fenced": 1, "redriven": 1, "skipped": 0, "failed": 0}

    def _noop_generation(_team_id, *, question_id):
        return {"fenced": 1, "retried": 1, "skipped": 0, "failed": 0}

    monkeypatch.setattr(
        chain, "auto_approve_awaiting_review_digests", lambda *_a, **_k: {}
    )
    monkeypatch.setattr(
        chain, "auto_regenerate_missing_hypothesis_round", lambda *_a, **_k: {}
    )
    monkeypatch.setattr(
        chain, "auto_retry_pending_collection_handoffs", lambda *_a, **_k: {}
    )
    monkeypatch.setattr(chain, "auto_adjudicate_exhausted_round", lambda *_a, **_k: {})
    monkeypatch.setattr(
        chain, "auto_accept_knowledge_handoffs", lambda *_a, **_k: {}
    )
    monkeypatch.setattr(chain, "auto_retry_blocked_formal_nodes", lambda *_a, **_k: {})
    monkeypatch.setattr(chain, "auto_redrive_fenced_review_meeting", _noop_review)
    monkeypatch.setattr(
        chain, "auto_retry_fenced_generation_attempt", _noop_generation
    )

    summary = chain.sweep_auto_advance_closure()

    assert summary["fencedReviewsRedriven"] == 1
    assert summary["closedGenerationsRetried"] == 1


# ---------------------------------------------------------------------------
# spec 4: candidate-generation digest auto-approval with quality gate


def _approve_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Approve isolation; returns the captured scene events."""
    _isolate(tmp_path, monkeypatch)
    # The TTL default is an operator decision: a leaked env override must not
    # change what "default" means in these tests.
    monkeypatch.delenv("VIBELUTION_AUTO_APPROVE_DIGEST_TTL_MS", raising=False)
    events: list[dict[str, Any]] = []

    def _capture(
        event_code: str,
        *,
        outcome: str,
        fields: dict[str, Any] | None = None,
        level: str = "info",
    ) -> None:
        events.append(
            {
                "code": event_code,
                "outcome": outcome,
                "fields": dict(fields or {}),
                "level": level,
            }
        )

    monkeypatch.setattr(chain, "_record_scene_event", _capture)
    return events


def _candgen_digest_approvers(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, Any]]:
    approved: list[dict[str, Any]] = []

    def _approve(team_id: str, meeting_round_id: str, **kwargs):
        approved.append(
            {
                "teamId": team_id,
                "meetingRoundId": meeting_round_id,
                **kwargs,
            }
        )
        return {"status": "created", "meetingRound": {"status": "closed"}}

    monkeypatch.setattr(chain, "approve_meeting_digest", _approve)
    return approved


def _candgen_awaiting_meeting(
    meeting_id: str,
    *,
    updated_at: str,
    proposals: int = 1,
    validation_errors: int = 0,
) -> dict[str, Any]:
    return {
        "meetingRoundId": meeting_id,
        "question": _QUESTION_ID,
        "meetingType": chain.CANDIDATE_GENERATION_MEETING_TYPE,
        "status": "awaiting_approval",
        "startedAt": "2026-09-01T00:00:00Z",
        "updatedAt": updated_at,
        "participants": ["agent-a"],
        "digestDraft": {
            "digestDraftId": f"draft-{meeting_id}",
            "contentHash": f"hash-{meeting_id}",
            "proposedCandidates": [
                {"candidateId": f"cand-{meeting_id}-{index}"} for index in range(proposals)
            ],
            "validationErrors": [
                {"code": "bad_request", "message": "invalid"}
                for _index in range(validation_errors)
            ],
        },
    }


def test_auto_approve_closes_stale_candgen_digest_passing_quality_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """candgen digest 零 validationErrors 且有提案 → 过质量门即在默认
    TTL=0 下同 pass 立即批准，closedBy 为 generation 专用系统标识。"""
    events = _approve_env(tmp_path, monkeypatch)
    _seed_meeting(
        _candgen_awaiting_meeting(
            "meeting-candgen-clean", updated_at=_offset_iso(600)
        )
    )
    approved = _candgen_digest_approvers(monkeypatch)

    summary = chain.auto_approve_awaiting_review_digests(
        _TEAM_ID,
        question_id=_QUESTION_ID,
        now_ms=_offset_ms(0),  # digest 10 minutes old: age 0 default approves now
    )

    assert summary["approved"] == 1
    assert len(approved) == 1
    assert approved[0]["closed_by"] == chain.AUTO_APPROVE_GENERATION_DIGEST_CLOSED_BY
    approved_events = [
        item
        for item in events
        if item["code"] == "hypothesis_first.auto_approve_review_digest"
        and item["outcome"] == "approved"
    ]
    assert len(approved_events) == 1
    assert (
        approved_events[0]["fields"]["closedBy"]
        == chain.AUTO_APPROVE_GENERATION_DIGEST_CLOSED_BY
    )


def test_auto_approve_keeps_human_gate_for_candgen_quality_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """candgen digest 带校验错误或缺提案 → 不自动批，人工门保留并留提醒事件。"""
    events = _approve_env(tmp_path, monkeypatch)
    _seed_meeting(
        _candgen_awaiting_meeting(
            "meeting-candgen-errors",
            updated_at=_offset_iso(600),
            validation_errors=1,
        )
    )
    _seed_meeting(
        _candgen_awaiting_meeting(
            "meeting-candgen-empty",
            updated_at=_offset_iso(600),
            proposals=0,
        )
    )
    approved = _candgen_digest_approvers(monkeypatch)

    summary = chain.auto_approve_awaiting_review_digests(
        _TEAM_ID,
        question_id=_QUESTION_ID,
        now_ms=_offset_ms(0),
    )

    assert approved == []
    assert summary["approved"] == 0
    assert summary["skipped"] == 2
    skipped_by_meeting = {
        item["fields"]["meetingRoundId"]: item
        for item in events
        if item["code"] == "hypothesis_first.auto_approve_review_digest"
        and item["outcome"] == "skipped"
    }
    assert (
        skipped_by_meeting["meeting-candgen-errors"]["fields"]["reason"]
        == "candgen_digest_validation_errors"
    )
    assert skipped_by_meeting["meeting-candgen-errors"]["level"] == "warning"
    assert str(skipped_by_meeting["meeting-candgen-errors"]["fields"]["reminder"])
    assert (
        skipped_by_meeting["meeting-candgen-empty"]["fields"]["reason"]
        == "candgen_digest_no_proposals"
    )
    assert skipped_by_meeting["meeting-candgen-empty"]["level"] == "warning"
