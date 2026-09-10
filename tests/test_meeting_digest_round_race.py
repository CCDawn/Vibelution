"""Digest round-race guards and stale awaiting-approval draft self-heal.

SCI-085: a review meeting's summarize step raced the last bound discussion
round — the digest draft persisted with only round 1's markers, round 2
landed afterwards, and ``approve_meeting_closure`` then failed closed on the
missing round-2 disagreement marker, stranding the meeting in
``awaiting_approval`` forever.  The three defense layers covered here:

- ``submit_meeting_digest_draft`` refuses to persist while a bound round is
  still running (the meeting stays summarizing, existing retry paths
  recover);
- ``prepare_meeting_summary_draft`` generalizes its awaiting-approval
  repair: a draft whose ``sourceMessageContentHash`` no longer matches the
  bound messages is rejected and redrafted once every bound round is
  terminal;
- ``sweep_meetings_missing_digest`` gains the third shape: a stale
  awaiting-approval draft with terminal rounds and no live digest work is
  rejected, then re-entered through the existing redrive — idempotently, so
  repeated sweeps never tear freshly repaired state.

All discussion content comes from fake runners or seeded records (DEV
fixtures); no real model or network is involved.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.contracts import ContractValidationError
from core.web.services import chat_room_service
from core.web.services.team_workflow import meeting_driver_work
from core.web.services.team_workflow import meeting_rounds as meetings
from core.web.services.team_workflow import meeting_runtime
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain as chain,
)
from core.web.services.team_workflow.research_runtime.operator_authorization import (
    server_operator_scope,
)
from tests.test_research_workflow_hf_auto_closeout import (
    _TEAM_ID as _SWEEP_TEAM_ID,
    _digest_sweep_env,
    _fenced_meeting_record,
    _isolate as _sweep_isolate,
    _seed_meeting,
)
from tests.test_research_workflow_hypothesis_first_chain import (
    _ROLES,
    _hf_env,
    _marker_runner,
    _open_first_meeting,
    _patch_approved_question,
)

_ROUND2_DISAGREE_ISSUE = "上一轮引用的 FDM 文献锚点是否可作为已核验证据进入评审"


def _simple_drafter(meeting_round, source_messages):
    """Minimal injected drafter; deterministic markers still come from sources."""

    return {
        "summary": "评审纪要（注入起草器）。",
        "documentMarkdown": "# 纪要\n- 注入起草器",
    }


# ---------------------------------------------------------------------------
# Layer 1 — submit gate: no digest draft while a bound round is running


def test_submit_digest_draft_blocked_while_bound_round_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    monkeypatch.setattr(meeting_runtime, "maybe_auto_draft_meeting", lambda *a, **k: None)
    agent_ids = [agents[role] for role in _ROLES]
    with server_operator_scope("u-1", roles=("operator",)):
        recorded = _open_first_meeting(team_id, agent_ids)
        meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]
        meetings.begin_meeting_summary(
            team_id, meeting_id, actor=agent_ids[0], human_triggered=True
        )
        # Pretend the bound round is still speaking (existing test trick).
        monkeypatch.setattr(
            chat_room_service,
            "RUNNING_ROUND_STATUSES",
            {"queued", "running", "stopping", "completed"},
        )
        draft = {
            "summary": "阶段纪要",
            "agreements": [],
            "disagreements": [],
            "actionItems": [],
            "risks": [],
            "knowledgeCandidates": [],
            "sourceMessageRefs": ["room-a/round-1/message-1"],
        }
        with pytest.raises(ContractValidationError, match="still running"):
            meetings.submit_meeting_digest_draft(team_id, meeting_id, draft)
        meeting = meetings.get_meeting_round(team_id, meeting_id)["meetingRound"]
        assert meeting["status"] == "summarizing"
        assert not meeting.get("digestDraft")


# ---------------------------------------------------------------------------
# Layer 2 — prepare self-heal: stale awaiting-approval draft is redrafted


def test_prepare_repairs_stale_awaiting_approval_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    monkeypatch.setattr(meeting_runtime, "maybe_auto_draft_meeting", lambda *a, **k: None)
    agent_ids = [agents[role] for role in _ROLES]
    with server_operator_scope("u-1", roles=("operator",)):
        recorded = _open_first_meeting(team_id, agent_ids)
        meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]

        first = meeting_runtime.prepare_meeting_summary_draft(
            team_id, meeting_id, drafter=_simple_drafter
        )
        assert first["status"] == "awaiting_approval"
        meeting = meetings.get_meeting_round(team_id, meeting_id)["meetingRound"]
        old_draft = meeting["digestDraft"]
        old_hash = old_draft["sourceMessageContentHash"]
        old_refs = set(old_draft["sourceMessageRefs"])

        # Round 2 lands after the draft: a disagreement marker the stored
        # draft cannot contain (the SCI-085 incident shape).
        round2_message = {
            "messageId": "message-round-2-1",
            "roundId": "round-2",
            "roomId": meeting["linkedChatRoomId"],
            "status": "completed",
            "speakerTitle": "评审员",
            "content": f"DISAGREE: {_ROUND2_DISAGREE_ISSUE}",
        }
        real_source_messages = meetings.meeting_source_messages

        def _extended(meeting_round):
            return [*real_source_messages(meeting_round), round2_message]

        monkeypatch.setattr(meetings, "meeting_source_messages", _extended)
        repaired = meeting_runtime.prepare_meeting_summary_draft(
            team_id, meeting_id, drafter=_simple_drafter
        )
        assert repaired["status"] == "awaiting_approval"
        meeting = meetings.get_meeting_round(team_id, meeting_id)["meetingRound"]
        new_draft = meeting["digestDraft"]
        assert new_draft["sourceMessageContentHash"] != old_hash
        assert meeting["draftRejectedBy"] == "system:summary-repair"
        issues_after = {
            str(item.get("issue") or "") for item in new_draft["disagreements"]
        }
        assert _ROUND2_DISAGREE_ISSUE in issues_after
        assert old_refs < set(new_draft["sourceMessageRefs"])


def test_prepare_reuses_fresh_awaiting_approval_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The repair must only fire on a real hash drift, not on every reuse."""

    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    monkeypatch.setattr(meeting_runtime, "maybe_auto_draft_meeting", lambda *a, **k: None)
    agent_ids = [agents[role] for role in _ROLES]
    build_calls = {"count": 0}
    original = meeting_runtime.build_meeting_digest_draft

    def counting_builder(*args, **kwargs):
        build_calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(meeting_runtime, "build_meeting_digest_draft", counting_builder)
    with server_operator_scope("u-1", roles=("operator",)):
        recorded = _open_first_meeting(team_id, agent_ids)
        meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]
        first = meeting_runtime.prepare_meeting_summary_draft(
            team_id, meeting_id, drafter=_simple_drafter
        )
        assert first["status"] == "awaiting_approval"
        builds_after_first = build_calls["count"]
        second = meeting_runtime.prepare_meeting_summary_draft(
            team_id, meeting_id, drafter=_simple_drafter
        )
        assert second["status"] == "awaiting_approval"
        assert build_calls["count"] == builds_after_first
        meeting = meetings.get_meeting_round(team_id, meeting_id)["meetingRound"]
        assert not meeting.get("draftRejectedBy")


# ---------------------------------------------------------------------------
# Layer 3 — sweep self-heal: stale awaiting-approval drafts re-enter redrive


def _completed_messages() -> list[dict]:
    return [
        {
            "messageId": "message-1",
            "roundId": "round-1",
            "roomId": "room-a",
            "status": "completed",
            "content": "AGREE: 第一轮结论一致",
        },
        {
            "messageId": "message-2",
            "roundId": "round-2",
            "roomId": "room-a",
            "status": "completed",
            "content": f"DISAGREE: {_ROUND2_DISAGREE_ISSUE}",
        },
    ]


def _patch_terminal_rounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(meetings, "running_bound_round_ids", lambda _m: [])
    monkeypatch.setattr(
        meetings,
        "meeting_source_messages",
        lambda _m: [dict(item) for item in _completed_messages()],
    )


def _stale_awaiting_meeting(meeting_id: str, draft_hash: str) -> dict:
    return _fenced_meeting_record(
        meeting_id,
        meeting_type=chain.HYPOTHESIS_REVIEW_MEETING_TYPE,
        status="awaiting_approval",
        extra={
            "digestDraft": {
                "contentHash": "digest-content-1",
                "sourceMessageContentHash": draft_hash,
                "summary": "只覆盖第一轮的纪要",
                "agreements": [],
                "disagreements": [],
                "actionItems": [],
                "risks": [],
                "knowledgeCandidates": [],
                "sourceMessageRefs": ["room-a/round-1/message-1"],
            }
        },
    )


def test_missing_digest_sweep_repairs_stale_awaiting_approval_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sweep_isolate(tmp_path, monkeypatch)
    scheduled = _digest_sweep_env(tmp_path, monkeypatch)
    _patch_terminal_rounds(monkeypatch)
    stale_hash = meetings.source_message_content_hash(_completed_messages()[:1])
    meeting_id = "meeting-stale-awaiting"
    _seed_meeting(_stale_awaiting_meeting(meeting_id, stale_hash))

    summary = meeting_runtime.sweep_meetings_missing_digest(
        now_ms=1_000_000, force=True
    )

    assert summary["repaired"] == 1
    assert summary["scheduled"] == 1
    assert scheduled == [(_SWEEP_TEAM_ID, meeting_id)]
    meeting = meetings.get_meeting_round(_SWEEP_TEAM_ID, meeting_id)["meetingRound"]
    assert meeting["status"] == "summarizing"
    assert not meeting.get("digestDraft")
    assert meeting["draftRejectedBy"] == "system:summary-repair"


def test_missing_digest_sweep_skips_stale_awaiting_draft_with_live_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A live in-process digest job or pending intent parks the repair."""

    _sweep_isolate(tmp_path, monkeypatch)
    scheduled = _digest_sweep_env(tmp_path, monkeypatch)
    _patch_terminal_rounds(monkeypatch)
    stale_hash = meetings.source_message_content_hash(_completed_messages()[:1])
    job_id = "meeting-stale-live-job"
    intent_id = "meeting-stale-live-intent"
    _seed_meeting(_stale_awaiting_meeting(job_id, stale_hash))
    _seed_meeting(_stale_awaiting_meeting(intent_id, stale_hash))
    with meeting_runtime._MEETING_DIGEST_JOBS_LOCK:
        meeting_runtime._MEETING_DIGEST_JOBS.add((_SWEEP_TEAM_ID, job_id))
    meeting_driver_work.record_intent(
        _SWEEP_TEAM_ID,
        intent_id,
        status=meeting_driver_work.STATUS_RUNNING,
        action_kind=meeting_driver_work.ACTION_RUN_DIGEST,
    )

    summary = meeting_runtime.sweep_meetings_missing_digest(
        now_ms=1_000_000, force=True
    )

    assert summary.get("repaired", 0) == 0
    assert summary["scheduled"] == 0
    assert scheduled == []
    for meeting_id in (job_id, intent_id):
        meeting = meetings.get_meeting_round(_SWEEP_TEAM_ID, meeting_id)[
            "meetingRound"
        ]
        assert meeting["status"] == "awaiting_approval"
        assert meeting["digestDraft"]["sourceMessageContentHash"] == stale_hash


def test_missing_digest_sweep_skips_fresh_awaiting_approval_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sweep_isolate(tmp_path, monkeypatch)
    scheduled = _digest_sweep_env(tmp_path, monkeypatch)
    _patch_terminal_rounds(monkeypatch)
    fresh_hash = meetings.source_message_content_hash(_completed_messages())
    meeting_id = "meeting-fresh-awaiting"
    _seed_meeting(_stale_awaiting_meeting(meeting_id, fresh_hash))

    summary = meeting_runtime.sweep_meetings_missing_digest(
        now_ms=1_000_000, force=True
    )

    assert summary.get("repaired", 0) == 0
    assert summary["scheduled"] == 0
    assert scheduled == []
    meeting = meetings.get_meeting_round(_SWEEP_TEAM_ID, meeting_id)["meetingRound"]
    assert meeting["status"] == "awaiting_approval"
    assert meeting["digestDraft"]["sourceMessageContentHash"] == fresh_hash


# ---------------------------------------------------------------------------
# Idempotency — repeated sweeps never tear state


def test_missing_digest_sweep_is_noop_for_non_awaiting_states(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A summarizing meeting with a draft product must not be torn down."""

    _sweep_isolate(tmp_path, monkeypatch)
    scheduled = _digest_sweep_env(tmp_path, monkeypatch)
    _patch_terminal_rounds(monkeypatch)
    stale_hash = meetings.source_message_content_hash(_completed_messages()[:1])
    meeting_id = "meeting-summarizing-with-draft"
    record = _stale_awaiting_meeting(meeting_id, stale_hash)
    record["status"] = "summarizing"
    _seed_meeting(record)

    summary = meeting_runtime.sweep_meetings_missing_digest(
        now_ms=1_000_000, force=True
    )

    assert summary.get("repaired", 0) == 0
    assert summary["scheduled"] == 0
    assert scheduled == []
    meeting = meetings.get_meeting_round(_SWEEP_TEAM_ID, meeting_id)["meetingRound"]
    assert meeting["status"] == "summarizing"
    assert meeting["digestDraft"]["sourceMessageContentHash"] == stale_hash


def test_repeated_sweeps_do_not_tear_repaired_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The redrive job stays deduped, so the second sweep is a no-op."""

    _sweep_isolate(tmp_path, monkeypatch)
    _patch_terminal_rounds(monkeypatch)
    stale_hash = meetings.source_message_content_hash(_completed_messages()[:1])
    meeting_id = "meeting-stale-idempotent"
    _seed_meeting(_stale_awaiting_meeting(meeting_id, stale_hash))

    class _DeferredRedrive:
        """Accepts the redrive submission but never runs it."""

        def __init__(self):
            self.submissions: list[tuple[object, tuple[object, ...]]] = []

        def submit(self, callback, *args):
            self.submissions.append((callback, args))
            return object()

    deferred = _DeferredRedrive()
    monkeypatch.setattr(meeting_runtime, "_MEETING_DISCUSSION_EXECUTOR", deferred)

    first = meeting_runtime.sweep_meetings_missing_digest(
        now_ms=1_000_000, force=True
    )
    assert first["repaired"] == 1
    assert first["scheduled"] == 1
    assert len(deferred.submissions) == 1
    meeting = meetings.get_meeting_round(_SWEEP_TEAM_ID, meeting_id)["meetingRound"]
    assert meeting["status"] == "summarizing"
    assert not meeting.get("digestDraft")

    second = meeting_runtime.sweep_meetings_missing_digest(
        now_ms=1_015_000, force=True
    )
    assert second.get("repaired", 0) == 0
    assert second.get("scheduled", 0) == 0
    assert len(deferred.submissions) == 1
    meeting = meetings.get_meeting_round(_SWEEP_TEAM_ID, meeting_id)["meetingRound"]
    assert meeting["status"] == "summarizing"
    assert not meeting.get("digestDraft")
    assert meeting["draftRejectedBy"] == "system:summary-repair"
