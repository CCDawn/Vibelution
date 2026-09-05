from __future__ import annotations

import copy
import json

import pytest

from core.chat.meeting_history_layering import apply_meeting_history_layering
from core.chatroom.context_checkpoint import (
    DEFAULT_DYNAMIC_TOKEN_THRESHOLD,
    DEFAULT_VERBATIM_ROUNDS,
    ChatRoomContextRefError,
    apply_chat_room_context_projection,
    apply_chat_room_context_snapshot,
    build_chat_room_context_checkpoint,
    build_chat_room_context_snapshot,
    maybe_rotate_chat_room_context_checkpoint,
    resolve_chat_room_context_refs,
    validate_chat_room_context_checkpoint,
)
from core.chatroom.context_payload import (
    CHAT_ROOM_CONTEXT_PAYLOAD_KIND,
    chat_room_context_output_contract,
    ingest_chat_room_context_output,
)
from core.chatroom.context_runtime import (
    chat_room_context_segment_tokens,
    chat_room_message_to_public,
    chat_room_structured_context_enabled,
    commit_chat_room_context_checkpoint,
    last_chat_room_message_ref,
)
from core.chatroom.store import ChatRoomStore
from core.llm.client import LLMClient
from tests.helpers.isolated_config import isolated_settings_config
from tools import chat_room_context_tools
from tools.token_manager import estimate_messages_tokens

ROOM_ID = "room-context-test"


def _structured_output(
    *,
    conclusion: str,
    agreements: list[str] | None = None,
    disagreements: list[dict] | None = None,
    risks: list[str] | None = None,
    action_items: list[dict] | None = None,
    evidence_requests: list[dict] | None = None,
    state_updates: list[dict] | None = None,
) -> str:
    return json.dumps(
        {
            "schemaVersion": 1,
            "display": {
                "conclusion": conclusion,
                "sections": [{"title": "依据", "bullets": ["保持可追溯"]}],
            },
            "protocol": {
                "agreements": agreements or [],
                "disagreements": disagreements or [],
                "risks": risks or [],
                "actionItems": action_items or [],
                "evidenceRequests": evidence_requests or [],
                "stateUpdates": state_updates or [],
            },
        },
        ensure_ascii=False,
    )


def _context_message(
    *,
    round_id: str,
    message_id: str,
    participant_id: str,
    output: str,
    status: str = "completed",
) -> dict:
    ingested = ingest_chat_room_context_output(output)
    return {
        "roomId": ROOM_ID,
        "roundId": round_id,
        "messageId": message_id,
        "participantId": participant_id,
        "agentId": participant_id,
        "speakerTitle": participant_id,
        "status": status,
        "content": ingested["content"],
        "contextPayload": ingested["contextPayload"],
        "timestamp": "2026-09-05T00:00:00+00:00",
    }


def _round(round_index: int, messages: list[dict], *, status: str = "completed") -> dict:
    return {
        "roomId": ROOM_ID,
        "roundId": f"round-{round_index}",
        "topic": f"议题 {round_index}",
        "status": status,
        "speakerOrder": ["role-a", "role-b"],
        "messages": messages,
        "finishedAt": f"2026-09-05T00:0{round_index}:00+00:00",
    }


def _room(rounds: list[dict]) -> dict:
    return {
        "roomId": ROOM_ID,
        "participants": [
            {"participantId": "role-a", "agentId": "agent-a", "teamRole": "role-a"},
            {"participantId": "role-b", "agentId": "agent-b", "teamRole": "role-b"},
        ],
        "rounds": rounds,
    }


def _transcript(round_id: str, content: str) -> dict:
    return {
        "role": "assistant",
        "content": content,
        "metadata": {
            "kind": "group_room_transcript",
            "sourceRoomId": ROOM_ID,
            "sourceRoundId": round_id,
        },
    }


def test_context_contract_ingests_display_and_keeps_protocol_internal() -> None:
    raw = _structured_output(
        conclusion="继续推进。",
        agreements=["采用冻结 checkpoint"],
        action_items=[
            {
                "ownerRoleId": "role-a",
                "action": "补充测试",
                "dueGate": "合入前",
                "status": "accepted",
            }
        ],
    )

    ingested = ingest_chat_room_context_output(raw)

    assert ingested["content"] == "继续推进。\n\n依据：\n- 保持可追溯"
    assert ingested["contextPayload"]["kind"] == CHAT_ROOM_CONTEXT_PAYLOAD_KIND
    assert ingested["contextPayload"]["audit"]["parseStatus"] == "structured"
    assert ingested["contextPayload"]["protocol"]["agreements"] == ["采用冻结 checkpoint"]
    assert "sourceMessageRefs" not in raw
    assert "只输出一个 JSON 对象" in chat_room_context_output_contract()


def test_invalid_context_output_stays_readable_but_never_becomes_protocol_fact() -> None:
    ingested = ingest_chat_room_context_output("普通自由文本")

    assert ingested["content"] == "普通自由文本"
    assert ingested["contextPayload"]["audit"]["parseStatus"] == "invalid"
    assert ingested["contextPayload"]["protocol"]["agreements"] == []


def test_failed_or_stopped_messages_never_enter_structured_or_legacy_state() -> None:
    failed = _context_message(
        round_id="round-1",
        message_id="message-failed",
        participant_id="role-a",
        output=_structured_output(conclusion="未完成", agreements=["不能提升"]),
        status="failed",
    )
    invalid_stopped = {
        "roomId": ROOM_ID,
        "roundId": "round-1",
        "messageId": "message-stopped",
        "participantId": "role-b",
        "status": "stopped",
        "content": "停止时的半截文本",
    }

    checkpoint = build_chat_room_context_checkpoint(
        _room([_round(1, [failed, invalid_stopped], status="failed")]),
        covered_round_ids=["round-1"],
        revision=1,
        created_at="fixed",
    )

    assert checkpoint["state"]["agreements"] == []
    assert checkpoint["legacyRecap"] == []
    assert checkpoint["sourceMessageRefs"] == []


def test_checkpoint_is_deterministic_and_requires_full_round_for_confirmed_agreement() -> None:
    shared = "采用冻结 checkpoint"
    round_one = _round(
        1,
        [
            _context_message(
                round_id="round-1",
                message_id="message-a1",
                participant_id="role-a",
                output=_structured_output(conclusion="A", agreements=[shared]),
            ),
            _context_message(
                round_id="round-1",
                message_id="message-b1",
                participant_id="role-b",
                output=_structured_output(conclusion="B", agreements=[shared]),
            ),
        ],
    )
    partial_round = _round(
        2,
        [
            _context_message(
                round_id="round-2",
                message_id="message-a2",
                participant_id="role-a",
                output=_structured_output(conclusion="A2", agreements=["尚未全员确认"]),
            )
        ],
        status="partial",
    )
    room = _room([round_one, partial_round])

    first = build_chat_room_context_checkpoint(
        room,
        covered_round_ids=["round-1", "round-2"],
        revision=1,
        created_at="2026-09-05T00:10:00+00:00",
    )
    second = build_chat_room_context_checkpoint(
        copy.deepcopy(room),
        covered_round_ids=["round-1", "round-2"],
        revision=1,
        created_at="2026-09-05T00:10:00+00:00",
    )

    assert first == second
    agreements = {item["statement"]: item for item in first["state"]["agreements"]}
    assert agreements[shared]["status"] == "confirmed"
    assert agreements["尚未全员确认"]["status"] == "proposed"
    assert validate_chat_room_context_checkpoint(first, room)["valid"] is True


def test_content_hash_excludes_revision_time_and_token_statistics() -> None:
    room = _room([_round(1, [], status="completed")])

    first = build_chat_room_context_checkpoint(
        room,
        covered_round_ids=["round-1"],
        revision=1,
        created_at="first",
        token_stats={"before": 100, "after": 20},
    )
    second = build_chat_room_context_checkpoint(
        room,
        covered_round_ids=["round-1"],
        revision=7,
        created_at="second",
        token_stats={"before": 999, "after": 888},
    )

    assert first["contentHash"] == second["contentHash"]
    assert first["checkpointId"] != second["checkpointId"]


def test_action_item_is_only_accepted_by_its_owner() -> None:
    action = {
        "ownerRoleId": "role-b",
        "action": "运行缓存测试",
        "dueGate": "closeout",
        "status": "accepted",
    }
    proposed = _round(
        1,
        [
            _context_message(
                round_id="round-1",
                message_id="message-a1",
                participant_id="role-a",
                output=_structured_output(conclusion="建议", action_items=[action]),
            )
        ],
        status="partial",
    )
    accepted = _round(
        2,
        [
            _context_message(
                round_id="round-2",
                message_id="message-b2",
                participant_id="role-b",
                output=_structured_output(conclusion="接受", action_items=[action]),
            )
        ],
        status="partial",
    )

    before = build_chat_room_context_checkpoint(
        _room([proposed]),
        covered_round_ids=["round-1"],
        revision=1,
        created_at="fixed",
    )
    after = build_chat_room_context_checkpoint(
        _room([proposed, accepted]),
        covered_round_ids=["round-1", "round-2"],
        revision=2,
        created_at="fixed",
    )

    assert before["state"]["actionItems"][0]["status"] == "proposed"
    assert after["state"]["actionItems"][0]["status"] == "accepted"


def test_action_owner_authority_uses_server_participant_role_identity() -> None:
    room = _room([])
    room["participants"] = [
        {
            "participantId": "session-reviewer",
            "agentId": "agent-reviewer",
            "teamRole": "Evidence Reviewer",
        }
    ]
    action = {
        "ownerRoleId": "evidence reviewer",
        "action": "核验来源",
        "dueGate": "closeout",
        "status": "accepted",
    }
    room["rounds"] = [
        {
            **_round(
                1,
                [
                    _context_message(
                        round_id="round-1",
                        message_id="message-reviewer",
                        participant_id="session-reviewer",
                        output=_structured_output(
                            conclusion="接受任务",
                            action_items=[action],
                        ),
                    )
                ],
                status="partial",
            ),
            "speakerOrder": ["session-reviewer"],
        }
    ]

    checkpoint = build_chat_room_context_checkpoint(
        room,
        covered_round_ids=["round-1"],
        revision=1,
        created_at="fixed",
    )

    assert checkpoint["state"]["actionItems"][0]["status"] == "accepted"


def test_single_agent_state_update_cannot_confirm_an_agreement() -> None:
    proposed_round = _round(
        1,
        [
            _context_message(
                round_id="round-1",
                message_id="message-a1",
                participant_id="role-a",
                output=_structured_output(
                    conclusion="提出",
                    agreements=["需要全员支持"],
                ),
            )
        ],
        status="partial",
    )
    initial = build_chat_room_context_checkpoint(
        _room([proposed_round]),
        covered_round_ids=["round-1"],
        revision=1,
        created_at="fixed",
    )
    agreement_id = initial["state"]["agreements"][0]["itemId"]
    update_round = _round(
        2,
        [
            _context_message(
                round_id="round-2",
                message_id="message-a2",
                participant_id="role-a",
                output=_structured_output(
                    conclusion="自称已确认",
                    state_updates=[
                        {"itemId": agreement_id, "status": "confirmed"}
                    ],
                ),
            )
        ],
        status="partial",
    )

    checkpoint = build_chat_room_context_checkpoint(
        _room([proposed_round, update_round]),
        covered_round_ids=["round-1", "round-2"],
        revision=2,
        created_at="fixed",
    )

    assert checkpoint["state"]["agreements"][0]["status"] == "proposed"
    assert checkpoint["state"]["rejectedStateUpdates"] == [
        {
            "itemId": agreement_id,
            "reason": "consensus_required",
            "sourceRef": f"{ROOM_ID}/round-2/message-a2",
        }
    ]


def test_legacy_messages_are_bounded_and_traceable_not_promoted_to_state() -> None:
    legacy = {
        "roomId": ROOM_ID,
        "roundId": "round-1",
        "messageId": "legacy-1",
        "participantId": "role-a",
        "status": "completed",
        "content": "这是旧版自由文本。\n第二行不应进入摘录。",
    }
    checkpoint = build_chat_room_context_checkpoint(
        _room([_round(1, [legacy])]),
        covered_round_ids=["round-1"],
        revision=1,
        created_at="fixed",
    )

    assert checkpoint["state"]["agreements"] == []
    assert checkpoint["legacyRecap"] == [
        {
            "excerpt": "这是旧版自由文本。",
            "sourceRef": f"{ROOM_ID}/round-1/legacy-1",
            "speaker": "role-a",
        }
    ]


def test_rotation_freezes_checkpoint_until_dynamic_threshold_is_crossed() -> None:
    rounds = []
    for index in range(1, 5):
        rounds.append(
            _round(
                index,
                [
                    _context_message(
                        round_id=f"round-{index}",
                        message_id=f"message-a{index}",
                        participant_id="role-a",
                        output=_structured_output(conclusion=f"结论 {index}"),
                    ),
                    _context_message(
                        round_id=f"round-{index}",
                        message_id=f"message-b{index}",
                        participant_id="role-b",
                        output=_structured_output(conclusion=f"补充 {index}"),
                    ),
                ],
            )
        )
    room = _room(rounds[:3])
    estimates = iter([20_000, 2_000])

    first = maybe_rotate_chat_room_context_checkpoint(
        room,
        previous_checkpoint=None,
        token_threshold=16_384,
        verbatim_rounds=2,
        estimate_tokens=lambda _messages: next(estimates),
        created_at="first",
    )
    frozen_hash = first["checkpoint"]["contentHash"]

    unchanged = maybe_rotate_chat_room_context_checkpoint(
        _room(rounds),
        previous_checkpoint=first["checkpoint"],
        token_threshold=16_384,
        verbatim_rounds=2,
        estimate_tokens=lambda _messages: 2_000,
        created_at="second",
    )

    assert DEFAULT_DYNAMIC_TOKEN_THRESHOLD == 16_384
    assert DEFAULT_VERBATIM_ROUNDS == 2
    assert first["rotated"] is True
    assert first["checkpoint"]["coveredRoundIds"] == ["round-1"]
    assert unchanged["rotated"] is False
    assert unchanged["checkpoint"]["contentHash"] == frozen_hash


def test_projection_replaces_covered_rounds_and_keeps_recent_two_verbatim() -> None:
    rounds = []
    history = [{"role": "user", "content": "unrelated direct history"}]
    for index in range(1, 5):
        rounds.append(
            _round(
                index,
                [
                    _context_message(
                        round_id=f"round-{index}",
                        message_id=f"message-{index}",
                        participant_id="role-a",
                        output=_structured_output(conclusion=f"结论 {index}"),
                    )
                ],
                status="partial",
            )
        )
        history.append(_transcript(f"round-{index}", f"raw round {index}"))
    room = _room(rounds)
    checkpoint = build_chat_room_context_checkpoint(
        room,
        covered_round_ids=["round-1"],
        revision=1,
        created_at="fixed",
    )

    projected, state = apply_chat_room_context_projection(
        history,
        room=room,
        checkpoint=checkpoint,
        verbatim_rounds=2,
    )

    assert projected[0]["metadata"]["kind"] == "chat_room_context_checkpoint"
    assert "unrelated direct history" not in json.dumps(projected, ensure_ascii=False)
    assert [
        item["metadata"]["sourceRoundId"]
        for item in projected[-2:]
    ] == ["round-3", "round-4"]
    assert state["checkpointValid"] is True
    assert state["recentRoundIds"] == ["round-3", "round-4"]
    assert any(
        item.get("metadata", {}).get("kind") == "chat_room_context_checkpoint"
        for item in projected
    )
    assert any(
        item.get("metadata", {}).get("kind") == "chat_room_context_delta"
        for item in projected
    )
    marker_messages = [
        item
        for item in projected
        if isinstance(item.get("content"), list)
        and any(isinstance(block, dict) and block.get("cache_control") for block in item["content"])
    ]
    assert len(marker_messages) == 1


def test_room_snapshot_is_built_once_and_applies_byte_identically_to_speakers() -> None:
    room = _room(
        [
            _round(
                index,
                [
                    _context_message(
                        round_id=f"round-{index}",
                        message_id=f"message-{index}",
                        participant_id="role-a",
                        output=_structured_output(conclusion=f"结论 {index}"),
                    )
                ],
                status="partial",
            )
            for index in range(1, 5)
        ]
    )
    checkpoint = build_chat_room_context_checkpoint(
        room,
        covered_round_ids=["round-1"],
        revision=1,
        created_at="fixed",
    )
    snapshot = build_chat_room_context_snapshot(room, checkpoint=checkpoint)
    shared = [_transcript(f"round-{index}", f"raw {index}") for index in range(1, 5)]
    history_a = [{"role": "user", "content": "A private"}, *shared]
    history_b = [{"role": "user", "content": "B private"}, *shared]

    projected_a, state_a = apply_chat_room_context_snapshot(history_a, snapshot)
    projected_b, state_b = apply_chat_room_context_snapshot(history_b, snapshot)

    assert projected_a == projected_b
    assert json.dumps(projected_a, ensure_ascii=False, sort_keys=True) == json.dumps(
        projected_b, ensure_ascii=False, sort_keys=True
    )
    assert all("private" not in json.dumps(item, ensure_ascii=False) for item in projected_a)
    assert projected_a[0]["metadata"]["kind"] == "chat_room_context_checkpoint"
    assert [
        item["metadata"]["sourceRoundId"]
        for item in projected_a
        if item.get("metadata", {}).get("kind") == "group_room_transcript"
    ] == ["round-3", "round-4"]
    assert state_a["excludedSessionMessageCount"] == len(history_a)
    assert state_b["excludedSessionMessageCount"] == len(history_b)
    assert state_a == state_b


def test_tampered_checkpoint_is_rebuilt_from_raw_room_state() -> None:
    room = _room(
        [
            _round(
                1,
                [
                    _context_message(
                        round_id="round-1",
                        message_id="message-1",
                        participant_id="role-a",
                        output=_structured_output(conclusion="结论"),
                    )
                ],
                status="partial",
            ),
            _round(2, [], status="completed"),
            _round(3, [], status="completed"),
        ]
    )
    checkpoint = build_chat_room_context_checkpoint(
        room,
        covered_round_ids=["round-1"],
        revision=1,
        created_at="fixed",
    )
    checkpoint["contentHash"] = "0" * 64

    projected, state = apply_chat_room_context_projection(
        [_transcript("round-1", "raw")],
        room=room,
        checkpoint=checkpoint,
        verbatim_rounds=2,
    )

    assert state["checkpointValid"] is False
    assert state["checkpointRebuilt"] is True
    assert projected[0]["metadata"]["kind"] == "chat_room_context_checkpoint"


def test_rebuild_rejects_formal_projection_with_unresolvable_source_refs() -> None:
    room = _room([_round(1, [], status="completed")])
    room["contextFormalProjections"] = [
        {
            "digestRef": "digest-corrupt",
            "decisionRefs": ["decision-corrupt"],
            "sourceMessageRefs": [f"{ROOM_ID}/round-1/missing-message"],
            "protocol": {
                "topics": [],
                "agreements": ["不应进入重建状态"],
                "disagreements": [],
                "risks": [],
                "actionItems": [],
                "evidenceRequests": [],
                "knowledgeCandidates": [],
            },
        }
    ]

    checkpoint = build_chat_room_context_checkpoint(
        room,
        covered_round_ids=["round-1"],
        revision=1,
        created_at="fixed",
    )

    assert checkpoint["sourceDigestRefs"] == []
    assert checkpoint["state"]["formalDecisionRefs"] == []
    assert checkpoint["state"]["agreements"] == []


def test_exact_ref_lookup_is_room_scoped_and_never_silently_truncates() -> None:
    message = _context_message(
        round_id="round-1",
        message_id="message-1",
        participant_id="role-a",
        output=_structured_output(conclusion="可回查正文"),
    )
    room = _room([_round(1, [message])])
    ref = f"{ROOM_ID}/round-1/message-1"

    result = resolve_chat_room_context_refs(room, [ref])

    assert result[0]["ref"] == ref
    assert result[0]["content"] == message["content"]
    assert len(result[0]["contentHash"]) == 64

    with pytest.raises(ChatRoomContextRefError, match="outside current room"):
        resolve_chat_room_context_refs(room, ["room-other/round-1/message-1"])
    with pytest.raises(ChatRoomContextRefError, match="at most 5"):
        resolve_chat_room_context_refs(room, [ref] * 6)
    with pytest.raises(ChatRoomContextRefError, match="exceeds 32768 bytes"):
        resolve_chat_room_context_refs(room, [ref], max_bytes=1)


def test_feature_flag_defaults_on_and_disables_only_on_explicit_false() -> None:
    assert chat_room_structured_context_enabled({}) is True
    assert chat_room_structured_context_enabled(
        {"VIBELUTION_CHAT_ROOM_STRUCTURED_CONTEXT_ENABLED": "true"}
    ) is True
    assert chat_room_structured_context_enabled(
        {"VIBELUTION_CHAT_ROOM_STRUCTURED_CONTEXT_ENABLED": "0"}
    ) is False


def test_checkpoint_commit_uses_last_message_ref_compare_and_swap() -> None:
    room = _room(
        [
            _round(
                1,
                [
                    _context_message(
                        round_id="round-1",
                        message_id="message-1",
                        participant_id="role-a",
                        output=_structured_output(conclusion="结论"),
                    )
                ],
                status="completed",
            )
        ]
    )
    state = {"rooms": [room]}
    checkpoint = build_chat_room_context_checkpoint(
        room,
        covered_round_ids=["round-1"],
        revision=1,
        created_at="fixed",
    )
    expected = last_chat_room_message_ref(room)

    stale = commit_chat_room_context_checkpoint(
        copy.deepcopy(state),
        room_id=ROOM_ID,
        expected_last_message_ref=f"{ROOM_ID}/round-1/old",
        checkpoint=checkpoint,
    )
    committed = commit_chat_room_context_checkpoint(
        state,
        room_id=ROOM_ID,
        expected_last_message_ref=expected,
        checkpoint=checkpoint,
    )

    assert stale["committed"] is False
    assert stale["reason"] == "room_advanced"
    assert committed["committed"] is True
    assert state["rooms"][0]["contextCheckpoint"]["contentHash"] == checkpoint["contentHash"]


def test_public_projection_hides_internal_context_and_segment_metrics_are_separate() -> None:
    message = {
        "messageId": "message-1",
        "content": "visible",
        "contextPayload": {"protocol": {"agreements": ["internal"]}},
    }
    public = chat_room_message_to_public(message)
    prompt_messages = [
        {"role": "system", "content": "stable"},
        {
            "role": "assistant",
            "content": "checkpoint",
            "metadata": {"kind": "chat_room_context_checkpoint"},
        },
        {
            "role": "assistant",
            "content": "raw",
            "metadata": {"kind": "group_room_transcript"},
        },
    ]
    stats = chat_room_context_segment_tokens(
        prompt_messages,
        estimate_tokens=lambda items: len(items) * 10,
    )

    assert "contextPayload" not in public
    assert "contextPayload" in message
    assert stats == {
        "system": 10,
        "checkpoint": 10,
        "delta": 0,
        "recentRaw": 10,
        "total": 30,
    }


def test_fixed_eight_round_three_speaker_fixture_meets_token_reduction_targets() -> None:
    participants = ["role-a", "role-b", "role-c"]
    rounds: list[dict] = []
    history: list[dict] = []
    for round_index in range(1, 9):
        messages = [
            _context_message(
                round_id=f"round-{round_index}",
                message_id=f"message-{round_index}-{speaker}",
                participant_id=speaker,
                output=_structured_output(conclusion=f"第 {round_index} 轮 {speaker} 结论"),
            )
            for speaker in participants
        ]
        for speaker, message in zip(participants, messages):
            message["content"] = (
                f"第{round_index}轮 {speaker} 证据链与边界条件需要逐项核对，" * 12
            )
        round_payload = _round(round_index, messages)
        round_payload["speakerOrder"] = participants
        rounds.append(round_payload)
        speeches = "\n".join(
            f"- {speaker}: "
            + (f"第{round_index}轮证据链与边界条件需要逐项核对，" * 12)
            for speaker in participants
        )
        history.append(
            _transcript(
                f"round-{round_index}",
                "\n".join(
                    [
                        "[群聊同步]",
                        "群聊: 缓存验收",
                        f"议题: 第 {round_index} 轮",
                        "摘要: 本轮已完成。",
                        "",
                        "其他 Agent 发言:",
                        speeches,
                    ]
                ),
            )
        )
    room = _room(rounds)
    room["participants"] = [
        {"participantId": speaker, "agentId": f"agent-{speaker}"}
        for speaker in participants
    ]
    checkpoint = build_chat_room_context_checkpoint(
        room,
        covered_round_ids=[f"round-{index}" for index in range(1, 6)],
        revision=1,
        created_at="fixed",
    )

    projected, _ = apply_chat_room_context_projection(
        history,
        room=room,
        checkpoint=checkpoint,
        verbatim_rounds=2,
    )
    current_recap, _ = apply_meeting_history_layering(
        history,
        room_id=ROOM_ID,
        verbatim_rounds=2,
    )
    full_tokens = estimate_messages_tokens(history)
    projected_tokens = estimate_messages_tokens(projected)
    structured_uncached = estimate_messages_tokens(
        [
            item
            for item in projected
            if item.get("metadata", {}).get("kind") != "chat_room_context_checkpoint"
        ]
    )
    current_uncached = estimate_messages_tokens(current_recap)

    assert (full_tokens - projected_tokens) / full_tokens >= 0.35
    assert (current_uncached - structured_uncached) / current_uncached >= 0.20


def test_qwen_room_payload_keeps_checkpoint_and_never_exceeds_four_markers() -> None:
    room = _room(
        [
            _round(1, [], status="completed"),
            _round(2, [], status="completed"),
            _round(3, [], status="completed"),
        ]
    )
    checkpoint = build_chat_room_context_checkpoint(
        room,
        covered_round_ids=["round-1"],
        revision=1,
        created_at="fixed",
    )
    snapshot = build_chat_room_context_snapshot(room, checkpoint=checkpoint)
    messages = [
        {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": "stable room system",
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        },
        snapshot["checkpointMessage"],
        {"role": "user", "content": "查证 checkpoint 引用"},
        {
            "role": "assistant",
            "content": "读取两条精确消息",
            "tool_calls": [
                {
                    "id": "call-a",
                    "type": "function",
                    "function": {
                        "name": "read_chat_room_context_refs",
                        "arguments": "{}",
                    },
                },
                {
                    "id": "call-b",
                    "type": "function",
                    "function": {
                        "name": "read_chat_room_context_refs",
                        "arguments": "{}",
                    },
                },
            ],
        },
        {"role": "tool", "tool_call_id": "call-a", "content": "A"},
        {"role": "tool", "tool_call_id": "call-b", "content": "B"},
    ]
    config = isolated_settings_config(
        **{
            "llm.providers.default.kind": "aliyun",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen3.6-plus",
            "llm.profiles.primary.prompt_cache.mode": "explicit_cache_control",
        }
    )

    payload = LLMClient(config=config, backend=lambda value: value)._build_payload(messages)

    marker_count = sum(
        1
        for message in payload["messages"]
        for block in (
            message.get("content")
            if isinstance(message.get("content"), list)
            else []
        )
        if isinstance(block, dict) and block.get("cache_control")
    )
    checkpoint_messages = [
        message
        for message in payload["messages"]
        if "ChatRoomContextCheckpoint.v1" in json.dumps(message, ensure_ascii=False)
    ]
    tool_messages = [
        message for message in payload["messages"] if message.get("role") == "tool"
    ]
    assert marker_count == 4
    assert len(checkpoint_messages) == 1
    assert len(tool_messages) == 1
    assert tool_messages[0]["content"][-1]["cache_control"] == {
        "type": "ephemeral"
    }


def test_non_cache_profile_strips_room_checkpoint_marker() -> None:
    room = _room([_round(1, [], status="completed")])
    checkpoint = build_chat_room_context_checkpoint(
        room,
        covered_round_ids=["round-1"],
        revision=1,
        created_at="fixed",
    )
    snapshot = build_chat_room_context_snapshot(room, checkpoint=checkpoint)
    config = isolated_settings_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://127.0.0.1:8081/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "non-caching-local-model",
            "llm.profiles.primary.prompt_cache.mode": "disabled",
        }
    )
    messages = [
        {"role": "system", "content": "stable"},
        snapshot["checkpointMessage"],
        {"role": "user", "content": "current"},
    ]

    payload = LLMClient(config=config, backend=lambda value: value)._build_payload(messages)

    assert not any(
        isinstance(block, dict) and block.get("cache_control")
        for message in payload["messages"]
        for block in (
            message.get("content")
            if isinstance(message.get("content"), list)
            else []
        )
    )


def test_agent_exact_ref_tool_uses_bound_room_and_returns_structured_error(monkeypatch) -> None:
    message = _context_message(
        round_id="round-1",
        message_id="message-1",
        participant_id="role-a",
        output=_structured_output(conclusion="精确正文"),
    )
    room = _room([_round(1, [message])])
    monkeypatch.setattr(
        chat_room_context_tools,
        "_current_runtime",
        lambda: {"roomId": ROOM_ID, "agentId": "agent-a"},
    )
    monkeypatch.setattr(chat_room_context_tools, "_load_room", lambda room_id: room)

    success = json.loads(
        chat_room_context_tools.read_chat_room_context_refs(
            [f"{ROOM_ID}/round-1/message-1"]
        )
    )
    outside = json.loads(
        chat_room_context_tools.read_chat_room_context_refs(
            ["room-other/round-1/message-1"]
        )
    )
    monkeypatch.setattr(chat_room_context_tools, "_current_runtime", dict)
    unbound = json.loads(chat_room_context_tools.read_chat_room_context_refs([]))

    assert success["ok"] is True
    assert success["messages"][0]["content"] == message["content"]
    assert outside["ok"] is False
    assert outside["error"] == "chat_room_context_ref_invalid"
    assert unbound["error"] == "chat_room_runtime_required"


def test_formal_digest_overrides_same_source_range_and_forces_checkpoint_refresh(
    tmp_path,
    monkeypatch,
) -> None:
    from core.web.services import chat_room_service

    message = _context_message(
        round_id="round-1",
        message_id="message-1",
        participant_id="role-a",
        output=_structured_output(conclusion="提议", agreements=["旧提议"]),
    )
    room = _room([_round(1, [message])])
    store = ChatRoomStore(root=tmp_path)
    store.save({"rooms": [room]})
    monkeypatch.setattr(chat_room_service, "_store", lambda: store)
    monkeypatch.setattr(
        chat_room_service,
        "record_runtime_scene_event",
        lambda *_args, **_kwargs: {"accepted": True},
    )
    source_ref = f"{ROOM_ID}/round-1/message-1"

    result = chat_room_service.promote_chat_room_formal_context(
        ROOM_ID,
        digest={
            "digestId": "digest-1",
            "contentHash": "d" * 64,
            "sourceMessageRefs": [source_ref],
            "discussionTopics": ["正式议题"],
            "agreements": ["正式共识"],
            "disagreements": [],
            "risks": ["正式风险"],
            "blockers": [],
            "actionItems": [
                {
                    "ownerRoleId": "role-a",
                    "action": "执行正式决定",
                    "dueGate": "closeout",
                }
            ],
            "evidenceRequests": [],
            "knowledgeCandidates": [],
        },
        decisions=[{"decisionId": "decision-1"}],
    )

    stored = store.load()["rooms"][0]
    checkpoint = stored["contextCheckpoint"]
    assert result["promoted"] is True
    assert result["checkpointRotated"] is True
    assert checkpoint["sourceDigestRefs"] == ["digest-1"]
    assert checkpoint["state"]["formalDecisionRefs"] == ["decision-1"]
    assert [item["statement"] for item in checkpoint["state"]["agreements"]] == [
        "正式共识"
    ]
    assert checkpoint["state"]["agreements"][0]["status"] == "confirmed"
    assert checkpoint["state"]["actionItems"][0]["status"] == "accepted"
    assert validate_chat_room_context_checkpoint(checkpoint, stored)["valid"] is True
    public = chat_room_service._room_to_api(stored)
    assert "contextCheckpoint" not in public
    assert "contextFormalProjections" not in public


def test_formal_projection_rejects_unknown_room_message_refs_before_persisting(
    tmp_path,
    monkeypatch,
) -> None:
    from core.web.services import chat_room_service

    room = _room([_round(1, [], status="completed")])
    store = ChatRoomStore(root=tmp_path)
    store.save({"rooms": [room]})
    monkeypatch.setattr(chat_room_service, "_store", lambda: store)

    result = chat_room_service.promote_chat_room_formal_context(
        ROOM_ID,
        digest={
            "digestId": "digest-invalid-ref",
            "sourceMessageRefs": [f"{ROOM_ID}/round-1/missing-message"],
        },
        decisions=[],
    )

    stored = store.load()["rooms"][0]
    assert result == {
        "promoted": False,
        "reason": "source_message_ref_invalid",
        "invalidSourceMessageRefs": [f"{ROOM_ID}/round-1/missing-message"],
    }
    assert "contextFormalProjections" not in stored


def test_closed_meeting_hook_promotes_only_the_linked_room(monkeypatch) -> None:
    from core.web.services import chat_room_service
    from core.web.services.team_workflow import meeting_rounds

    captured = []
    monkeypatch.setattr(
        chat_room_service,
        "promote_chat_room_formal_context",
        lambda room_id, **kwargs: captured.append((room_id, kwargs)),
    )
    meeting_rounds._promote_closed_meeting_room_context(
        {"linkedChatRoomId": "room-formal"},
        {"digestId": "digest-formal"},
        [{"decisionId": "decision-formal"}],
    )
    meeting_rounds._promote_closed_meeting_room_context(
        {"linkedChatRoomId": ""},
        {"digestId": "digest-unlinked"},
        [],
    )

    assert captured == [
        (
            "room-formal",
            {
                "digest": {"digestId": "digest-formal"},
                "decisions": [{"decisionId": "decision-formal"}],
            },
        )
    ]
