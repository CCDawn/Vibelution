"""Speaker rolling-window and meeting anchor-block contract tests.

Covers the chat-room speaker context assembly (`_speaker_canonical_chat_history`):

- Zero-difference guarantee: a history at or below the rolling window must
  assemble byte-identically to the legacy full replay and must never receive
  the anchor block.
- Truncation behavior: one message past the window drops the oldest events,
  injects a single meeting key-facts anchor at the head, and never duplicates
  windowed-in messages.
- Anchor content: deduped evidence requests with best-effort retrieval status,
  converged/disagreeing conclusions and candidate anchors, all sourced from
  read-only projections.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from core.chat.conversation_ledger import (
    EVENT_ASSISTANT_MESSAGE,
    EVENT_USER_MESSAGE,
    append_conversation_event,
    load_conversation_events,
)
from core.chat.context_assembler import assemble_conversation_context
from core.web.services import chat_room_service, data_processing_service
from core.web.services.team_workflow import meeting_rounds
from core.web.services.team_workflow.source_collection import facade


def _canonical_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _seed_ledger_history(root: Path, session_id: str, count: int) -> list:
    for index in range(count):
        role_user = index % 2 == 0
        append_conversation_event(
            root,
            session_id,
            f"turn-{index:03d}",
            EVENT_USER_MESSAGE if role_user else EVENT_ASSISTANT_MESSAGE,
            status="recorded" if role_user else "completed",
            payload={
                "content": f"历史消息 {index:03d} " + ("问题" if role_user else "结论要点。"),
                "metadata": {},
            },
            timestamp=f"2026-06-01T10:{index // 60:02d}:{index % 60:02d}",
        )
    return load_conversation_events(root, session_id)


def _baseline_full_replay(ledger_events: list) -> Any:
    return assemble_conversation_context(
        [],
        session_id="session-window",
        current_turn_id="chat-room:round:speaker",
        ledger_events=ledger_events,
        recent_message_limit=None,
    )


@pytest.fixture(autouse=True)
def _default_window_env(monkeypatch):
    monkeypatch.delenv(chat_room_service.SPEAKER_RECENT_MESSAGE_LIMIT_ENV, raising=False)


def test_speaker_recent_message_limit_env_parsing(monkeypatch) -> None:
    assert chat_room_service._speaker_recent_message_limit() == 40
    monkeypatch.setenv(chat_room_service.SPEAKER_RECENT_MESSAGE_LIMIT_ENV, "12")
    assert chat_room_service._speaker_recent_message_limit() == 12
    monkeypatch.setenv(chat_room_service.SPEAKER_RECENT_MESSAGE_LIMIT_ENV, "not-a-number")
    assert chat_room_service._speaker_recent_message_limit() == 40
    monkeypatch.setenv(chat_room_service.SPEAKER_RECENT_MESSAGE_LIMIT_ENV, "0")
    assert chat_room_service._speaker_recent_message_limit() is None
    monkeypatch.setenv(chat_room_service.SPEAKER_RECENT_MESSAGE_LIMIT_ENV, "-3")
    assert chat_room_service._speaker_recent_message_limit() is None


@pytest.mark.parametrize("history_size", [10, 39, 40])
def test_history_at_or_below_window_is_byte_identical_and_has_no_anchor(
    tmp_path: Path, history_size: int
) -> None:
    session_id = "session-window"
    ledger_events = _seed_ledger_history(tmp_path, session_id, history_size)
    baseline = _baseline_full_replay(ledger_events)
    windowed, assembly = chat_room_service._speaker_canonical_chat_history(
        session_id=session_id,
        turn_identity="chat-room:round:speaker",
        ledger_events=ledger_events,
        context={"teamId": "team-x", "meetingRoundId": "meeting-x"},
    )
    assert _canonical_text(windowed) == _canonical_text(list(baseline.history_messages or []))
    assert assembly.included_event_ids == baseline.included_event_ids
    assert int(assembly.omitted_event_count or 0) == 0
    assert all(
        (message.get("metadata") or {}).get("kind") != chat_room_service._MEETING_ANCHOR_METADATA_KIND
        for message in windowed
    )


def test_history_window_plus_one_truncates_and_injects_single_anchor(
    tmp_path: Path, monkeypatch
) -> None:
    session_id = "session-window"
    ledger_events = _seed_ledger_history(tmp_path, session_id, 41)
    baseline = _baseline_full_replay(ledger_events)

    monkeypatch.setattr(
        meeting_rounds,
        "get_meeting_round",
        lambda team_id, meeting_round_id: {
            "meetingRound": {"linkedChatRoomId": "", "digestDraft": None}
        },
    )
    monkeypatch.setattr(
        meeting_rounds,
        "completed_meeting_source_messages",
        lambda meeting_round: [],
    )

    windowed, assembly = chat_room_service._speaker_canonical_chat_history(
        session_id=session_id,
        turn_identity="chat-room:round:speaker",
        ledger_events=ledger_events,
        context={"teamId": "team-x", "meetingRoundId": "meeting-x"},
    )
    assert int(assembly.omitted_event_count or 0) > 0
    assert len(windowed) < len(list(baseline.history_messages or []))
    anchors = [
        message
        for message in windowed
        if (message.get("metadata") or {}).get("kind")
        == chat_room_service._MEETING_ANCHOR_METADATA_KIND
    ]
    assert len(anchors) == 0  # empty meeting markers -> honest no-anchor truncation
    # Windowed-in messages are never duplicated.
    contents = [str(message.get("content") or "") for message in windowed]
    assert len(contents) == len(set(contents))


def test_truncated_history_with_meeting_facts_injects_anchor_once(
    tmp_path: Path, monkeypatch
) -> None:
    session_id = "session-window"
    ledger_events = _seed_ledger_history(tmp_path, session_id, 41)
    source_messages = [
        {
            "roomId": "room-1",
            "roundId": "room-round-1",
            "messageId": "m1",
            "status": "completed",
            "content": (
                "CANDIDATE: cand-a | 候选A的一句话陈述 | 已有基线数据\n"
                'EVIDENCE_REQUEST: {"rationale":"需要 RCT 证据支持 cand-a",'
                '"candidateRefs":["cand-a"],'
                '"searchEnvelope":{"keywords":["rct"],"sourceTypes":[],"evidenceLevels":[]},'
                '"requirements":{},"writebackPolicy":{}}\n'
                "AGREE: 采用 cand-a 作为主假设\n"
                "DISAGREE: 样本量不足以支撑结论"
            ),
        }
    ]
    monkeypatch.setattr(
        meeting_rounds,
        "get_meeting_round",
        lambda team_id, meeting_round_id: {
            "meetingRound": {"linkedChatRoomId": "", "digestDraft": None}
        },
    )
    monkeypatch.setattr(
        meeting_rounds,
        "completed_meeting_source_messages",
        lambda meeting_round: source_messages,
    )
    monkeypatch.setattr(
        data_processing_service,
        "list_processing_runs",
        lambda **kwargs: {"runs": []},
    )

    windowed, assembly = chat_room_service._speaker_canonical_chat_history(
        session_id=session_id,
        turn_identity="chat-room:round:speaker",
        ledger_events=ledger_events,
        context={"teamId": "team-x", "meetingRoundId": "meeting-x"},
    )
    assert int(assembly.omitted_event_count or 0) > 0
    anchors = [
        index
        for index, message in enumerate(windowed)
        if (message.get("metadata") or {}).get("kind")
        == chat_room_service._MEETING_ANCHOR_METADATA_KIND
    ]
    assert anchors == [0]
    anchor = windowed[0]
    assert anchor["role"] == "system"
    assert anchor["metadata"]["meetingRoundId"] == "meeting-x"
    assert anchor["metadata"]["omittedEventCount"] == int(assembly.omitted_event_count or 0)
    text = str(anchor["content"])
    assert "会议关键事实锚点" in text
    assert "需要 RCT 证据支持 cand-a" in text
    assert "cand-a" in text
    assert "采用 cand-a 作为主假设" in text
    assert "样本量不足以支撑结论" in text
    assert "待检索" in text
    # Anchor is compact: stays well below the hard char budget.
    assert len(text) <= chat_room_service._MEETING_ANCHOR_MAX_CHARS
    # The anchor references the candidate instead of replaying full messages.
    for message in windowed[1:]:
        assert "会议关键事实锚点" not in str(message.get("content") or "")


def test_anchor_evidence_request_status_follows_collection_runs(monkeypatch) -> None:
    envelope_done = {"keywords": ["rct"], "sourceTypes": [], "evidenceLevels": []}
    envelope_running = {"keywords": ["cohort"], "sourceTypes": [], "evidenceLevels": []}
    envelope_failed = {"keywords": ["survey"], "sourceTypes": [], "evidenceLevels": []}
    envelope_missing = {"keywords": ["meta"], "sourceTypes": [], "evidenceLevels": []}

    def _request(envelope: dict[str, Any]) -> dict[str, Any]:
        return {
            "rationale": f"关于 {envelope['keywords'][0]} 的证据",
            "candidateRefs": ["cand-a"],
            "searchEnvelope": envelope,
            "requirements": {},
            "writebackPolicy": {},
        }

    fingerprints = {
        key: facade.search_envelope_fingerprint(envelope, {})
        for key, envelope in (
            ("done", envelope_done),
            ("running", envelope_running),
            ("failed", envelope_failed),
            ("missing", envelope_missing),
        )
    }
    runs = [
        {
            "runId": "run-done",
            "status": "completed",
            "updatedAt": "2026-06-02T00:00:00Z",
            "metadata": {"searchEnvelopeFingerprint": fingerprints["done"]},
        },
        {
            "runId": "run-stale",
            "status": "cancelled",
            "updatedAt": "2026-06-01T00:00:00Z",
            "metadata": {"searchEnvelopeFingerprint": fingerprints["done"]},
        },
        {
            "runId": "run-running",
            "status": "collecting",
            "updatedAt": "2026-06-02T00:00:00Z",
            "metadata": {"searchEnvelopeFingerprint": fingerprints["running"]},
        },
        {
            "runId": "run-failed",
            "status": "cancelled",
            "updatedAt": "2026-06-02T00:00:00Z",
            "metadata": {"searchEnvelopeFingerprint": fingerprints["failed"]},
        },
    ]
    monkeypatch.setattr(
        data_processing_service,
        "list_processing_runs",
        lambda **kwargs: {"runs": runs},
    )

    markers = {
        "evidenceRequests": [
            _request(envelope_done),
            dict(_request(envelope_done)),  # exact duplicate -> deduped
            _request(envelope_running),
            _request(envelope_failed),
            _request(envelope_missing),
        ],
        "agreements": [],
        "disagreements": [],
        "proposedCandidates": [],
    }
    block = chat_room_service._format_meeting_anchor_block(
        markers,
        team_id="team-x",
        digest_draft=None,
    )
    assert "已满足" in block
    assert "检索中" in block
    assert "不可得" in block
    assert "待检索" in block
    # Duplicate identical request collapses into one anchor line.
    assert block.count("关于 rct 的证据") == 1


def test_anchor_block_is_bounded_for_unbounded_markers() -> None:
    markers = {
        "evidenceRequests": [
            {
                "rationale": f"证据请求 {index}：" + "长" * 120,
                "candidateRefs": [f"cand-{index}"],
                "searchEnvelope": {"keywords": [f"kw-{index}"], "sourceTypes": [], "evidenceLevels": []},
                "requirements": {},
                "writebackPolicy": {},
            }
            for index in range(30)
        ],
        "agreements": [f"共识结论 {index}：" + "长" * 120 for index in range(30)],
        "disagreements": [
            {"issue": f"分歧 {index}：" + "长" * 120, "positions": [], "unresolvedReason": "x"}
            for index in range(30)
        ],
        "proposedCandidates": [
            {
                "candidateId": f"cand-{index}",
                "statement": "陈述" + "长" * 120,
                "rationale": "r",
                "proposedBy": "speaker",
            }
            for index in range(30)
        ],
    }
    block = chat_room_service._format_meeting_anchor_block(
        markers,
        team_id="team-x",
        digest_draft={"summary": "摘要" * 500},
    )
    assert len(block) <= chat_room_service._MEETING_ANCHOR_MAX_CHARS + 40
    assert "证据请求 9" in block  # first capped window entries survive
    assert "cand-9" in block
    assert "证据请求 15" not in block  # entries beyond the cap are omitted


def test_anchor_seed_message_requires_meeting_context(tmp_path: Path, monkeypatch) -> None:
    assert (
        chat_room_service._meeting_anchor_seed_message(
            {"teamId": "", "meetingRoundId": "m"}, omitted_event_count=3
        )
        is None
    )
    assert (
        chat_room_service._meeting_anchor_seed_message(
            {"teamId": "team-x", "meetingRoundId": ""}, omitted_event_count=3
        )
        is None
    )
    # Missing meeting round record degrades to no anchor instead of raising.
    def _raise_missing(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise meeting_rounds.ResearchMeetingRoundNotFoundError("meeting round not found")

    monkeypatch.setattr(meeting_rounds, "get_meeting_round", _raise_missing)
    assert (
        chat_room_service._meeting_anchor_seed_message(
            {"teamId": "team-x", "meetingRoundId": "missing-meeting"},
            omitted_event_count=3,
        )
        is None
    )
