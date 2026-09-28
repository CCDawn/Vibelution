# -*- coding: utf-8 -*-

"""会议参会者历史分层压缩（确定性投影 + 闭轮冻结）单测。

覆盖：确定性（同一输入两次装配逐字节一致）、轮窗口边界（最近 M 轮逐字保
留、更早轮原位替换为逐轮冻结 recap）、闭轮冻结（跨投影/重复调用逐字节一致，
开新轮后字节变化只从老化轮开始）、旋钮=0 与基线逐字节一致、非会议
session/其他房间消息不受影响、seed invariant 保持、6 轮合成会议 fixture 上
历史字符量下降 ≥35%。

语义修正记录（相对单条聚合 recap 的旧契约）：
- 聚合 recap（更早轮合并为单条消息）改为逐轮冻结 recap 原位替换：消息数不
  变（1:1 替换），压缩体现在字符量；聚合消息每开一轮即增长、历史前缀逐轮全
  灭的 churn 被消除。
- recap 消息 metadata 由聚合的 ``recapRoundCount``/``recappedRoundIds`` 改为
  单轮身份 ``roundNumber`` + ``sourceRoundId``。
- 聚合渲染器 ``build_meeting_history_recap`` 由单轮纯函数
  ``build_meeting_round_recap`` 取代（无外部消费方）。
"""

from __future__ import annotations

import json

import pytest

from core.chat.conversation_invariant import (
    check_conversation_payload_invariant,
    conversation_layer_fingerprint,
)
from core.chat.meeting_history_layering import (
    DEFAULT_MEETING_HISTORY_VERBATIM_ROUNDS,
    MEETING_HISTORY_RECAP_KIND,
    MEETING_HISTORY_VERBATIM_ROUNDS_ENV,
    apply_meeting_history_layering,
    build_meeting_round_recap,
    resolve_meeting_history_verbatim_rounds,
)
from core.chat.model_messages import ProviderMessageChain
from core.web.services import chat_room_service

ROOM_ID = "room-meeting-alpha"


def _group_sync_message(
    round_id: str,
    topic: str,
    own_speech: str,
    peer_speech: str,
    summary: str = "本轮已形成结论。",
) -> dict:
    """按 chat_room_service._build_group_round_session_message 的固定格式构造轮次同步消息。"""

    content = "\n".join(
        [
            "[群聊同步]",
            f"群聊: 评审会议",
            f"议题: {topic}",
            f"摘要: {summary}",
            "",
            "你的发言:",
            f"- 甲研究员: {own_speech}",
            "",
            "其他 Agent 发言:",
            f"- 乙分析师: {peer_speech}",
        ]
    )
    return {
        "role": "assistant",
        "content": content,
        "metadata": {
            "kind": "group_room_transcript",
            "sourceRoomId": ROOM_ID,
            "sourceRoundId": round_id,
        },
    }


def _round_speech(round_index: int, speaker: str) -> str:
    """多行长发言，模拟 trim_lines(4) 之后的真实轮次重放体积。"""

    return "\n".join(
        f"{speaker}第{round_index}轮第{line_no}点：围绕评审议题展开论证并给出证据链，"
        f"说明假设、数据来源与下一步实验安排，避免重复早前结论。"
        for line_no in range(1, 5)
    )


def _build_meeting_seed(round_count: int) -> list[dict]:
    """合成会议参会者 history seed：用户任务消息穿插逐轮「[群聊同步]」。"""

    messages: list[dict] = [
        {"role": "user", "content": "请围绕评审议题准备本轮发言。", "metadata": {}},
    ]
    for round_index in range(1, round_count + 1):
        messages.append(
            _group_sync_message(
                round_id=f"round-{round_index:02d}",
                topic=f"第{round_index}轮评审议题",
                own_speech=_round_speech(round_index, "甲研究员"),
                peer_speech=_round_speech(round_index, "乙分析师"),
            )
        )
        if round_index < round_count:
            messages.append(
                {"role": "user", "content": f"第{round_index + 1}轮请继续。", "metadata": {}}
            )
    return messages


def _serialize(messages: list[dict]) -> str:
    return json.dumps(messages, ensure_ascii=False, sort_keys=True, indent=1)


def _recap_messages(messages: list[dict]) -> list[dict]:
    return [
        item
        for item in messages
        if isinstance(item, dict) and item.get("metadata", {}).get("kind") == MEETING_HISTORY_RECAP_KIND
    ]


def _seed_message_by_round_id(seed: list[dict], round_id: str) -> dict:
    return next(
        item for item in seed if item.get("metadata", {}).get("sourceRoundId") == round_id
    )


def test_resolve_verbatim_rounds_defaults_and_knob(monkeypatch):
    monkeypatch.delenv(MEETING_HISTORY_VERBATIM_ROUNDS_ENV, raising=False)
    assert resolve_meeting_history_verbatim_rounds() == DEFAULT_MEETING_HISTORY_VERBATIM_ROUNDS
    assert resolve_meeting_history_verbatim_rounds("3") == 3
    assert resolve_meeting_history_verbatim_rounds("0") == 0
    # 负数与非整数回退安全值：负数=禁用，非法=默认窗口。
    assert resolve_meeting_history_verbatim_rounds("-2") == 0
    assert resolve_meeting_history_verbatim_rounds("abc") == DEFAULT_MEETING_HISTORY_VERBATIM_ROUNDS


def test_disabled_knob_matches_baseline_byte_for_byte():
    seed = _build_meeting_seed(6)
    layered, state = apply_meeting_history_layering(seed, room_id=ROOM_ID, verbatim_rounds=0)
    assert layered == seed
    assert _serialize(layered) == _serialize(seed)
    assert state["enabled"] is False
    assert state["recapRoundCount"] == 0


def test_verbatim_window_and_per_round_frozen_recaps():
    seed = _build_meeting_seed(6)
    layered, state = apply_meeting_history_layering(seed, room_id=ROOM_ID, verbatim_rounds=2)

    # 最近 2 轮逐字保留，位置不变。
    assert layered[-2] == seed[-2]
    assert layered[-1] == seed[-1]
    # 更早 4 轮逐轮冻结 recap 原位替换：消息数不变（1:1），压缩体现在字符量。
    assert len(layered) == len(seed)
    recap_messages = _recap_messages(layered)
    assert len(recap_messages) == 4
    assert [item["metadata"]["roundNumber"] for item in recap_messages] == [1, 2, 3, 4]
    assert [item["metadata"]["sourceRoundId"] for item in recap_messages] == [
        "round-01",
        "round-02",
        "round-03",
        "round-04",
    ]
    # 每条冻结 recap 占据该轮同步消息的确切位置，不越过窗口内消息。
    for recap in recap_messages:
        source_index = seed.index(_seed_message_by_round_id(seed, recap["metadata"]["sourceRoundId"]))
        assert layered.index(recap) == source_index
    assert layered.index(recap_messages[-1]) < layered.index(seed[-2])

    # 固定 recap 格式：header + 「## 轮 N: 议题」+ 每条发言「发言人：首行内容」。
    first_recap = recap_messages[0]
    assert first_recap["role"] == "assistant"
    assert first_recap["metadata"]["sourceRoomId"] == ROOM_ID
    lines = first_recap["content"].splitlines()
    assert lines[0] == "[会议历史回顾]"
    assert lines[2] == "## 轮 1: 第1轮评审议题"
    utterance_lines = [line for line in lines if line.startswith("- ")]
    assert len(utterance_lines) == 2
    assert utterance_lines[0].startswith("- 甲研究员：")
    assert "甲研究员第1轮第1点" in utterance_lines[0]
    # 该轮多行正文不再整段重放，也不含其他轮次内容。
    assert "甲研究员第1轮第4点" not in first_recap["content"]
    assert "第2轮评审议题" not in first_recap["content"]

    assert state["transcriptRoundCount"] == 6
    assert state["recapRoundCount"] == 4
    assert state["recappedRoundIds"] == ["round-01", "round-02", "round-03", "round-04"]
    assert state["originalChars"] > state["recapChars"] > 0


def test_layering_is_deterministic_across_repeated_assemblies():
    seed = _build_meeting_seed(6)
    first, first_state = apply_meeting_history_layering(seed, room_id=ROOM_ID, verbatim_rounds=2)
    second, second_state = apply_meeting_history_layering(seed, room_id=ROOM_ID, verbatim_rounds=2)
    # 同一 ledger 状态两次装配：消息序列与统计逐字节一致（qwen 前缀缓存硬前提）。
    assert _serialize(first) == _serialize(second)
    assert first_state == second_state
    # 输入序列不被修改（copy-on-write）。
    assert len(seed) == 6 * 2
    assert all(item.get("metadata", {}).get("kind") != MEETING_HISTORY_RECAP_KIND for item in seed)


def test_closed_round_recap_freeze_across_projections_and_recalls():
    """验收③：闭轮 recap 冻结——跨投影（窗口增长）与单独重算均逐字节一致。"""

    frozen_by_round: dict[int, str] = {}
    for round_count in (4, 5, 6, 7):
        seed = _build_meeting_seed(round_count)
        layered, _ = apply_meeting_history_layering(seed, room_id=ROOM_ID, verbatim_rounds=2)
        for recap in _recap_messages(layered):
            number = recap["metadata"]["roundNumber"]
            # 同一闭轮跨投影（轮数增多、窗口滑动）字节不漂移。
            if number in frozen_by_round:
                assert frozen_by_round[number] == recap["content"]
            else:
                frozen_by_round[number] = recap["content"]
            # 投影内 recap 与单轮纯函数重算逐字节一致（无隐藏上下文依赖）。
            source_message = _seed_message_by_round_id(seed, recap["metadata"]["sourceRoundId"])
            assert recap["content"] == build_meeting_round_recap(
                source_message, round_number=number
            )


def test_aging_round_bounds_byte_changes_to_aging_point():
    """验收②：开新轮后，老化轮之前的分段逐字节不变，变化从老化轮开始。"""

    seed_4 = _build_meeting_seed(4)
    seed_5 = _build_meeting_seed(5)
    # 同一批前 4 轮，再开第 5 轮：ledger 前缀逐字节一致。
    assert _serialize(seed_5[: len(seed_4)]) == _serialize(seed_4)

    layered_4, _ = apply_meeting_history_layering(seed_4, room_id=ROOM_ID, verbatim_rounds=2)
    layered_5, _ = apply_meeting_history_layering(seed_5, room_id=ROOM_ID, verbatim_rounds=2)

    # M=2：4 轮时老化 [1,2]、5 轮时老化 [1,2,3]；第 3 轮是本次老化出的轮。
    aging_source_index = seed_4.index(_seed_message_by_round_id(seed_4, "round-03"))
    for index in range(aging_source_index):
        assert _serialize([layered_4[index]]) == _serialize([layered_5[index]])
    # 首个字节变化恰好落在老化轮的位置：逐字原文 -> 它的冻结 recap（一次性转换）。
    assert layered_4[aging_source_index] is _seed_message_by_round_id(seed_4, "round-03")
    aging_recap = layered_5[aging_source_index]
    assert aging_recap["metadata"]["kind"] == MEETING_HISTORY_RECAP_KIND
    assert aging_recap["metadata"]["roundNumber"] == 3
    assert aging_recap["content"] == build_meeting_round_recap(
        _seed_message_by_round_id(seed_5, "round-03"), round_number=3
    )
    # 更早轮（1、2）的冻结 recap 在两次投影中逐字节相同：稳定前缀覆盖全部已冻结历史。
    assert _serialize(_recap_messages(layered_4)[:2]) == _serialize(_recap_messages(layered_5)[:2])


def test_recap_text_stable_and_content_truncation():
    long_speech = "很长的发言" * 60
    message = _group_sync_message("round-x", "议题X", long_speech, "短发言")
    recap_first = build_meeting_round_recap(message, round_number=1)
    recap_second = build_meeting_round_recap(message, round_number=1)
    assert recap_first == recap_second
    truncated_line = next(line for line in recap_first.splitlines() if line.startswith("- 甲研究员："))
    assert truncated_line.endswith("…")
    assert len(truncated_line) <= 4 + 5 + 121


def test_other_room_and_non_transcript_messages_untouched():
    seed = _build_meeting_seed(3)
    other_room = _group_sync_message("round-other", "别的房间议题", "内容A", "内容B")
    other_room["metadata"]["sourceRoomId"] = "room-other"
    seed.insert(1, other_room)

    layered, state = apply_meeting_history_layering(seed, room_id=ROOM_ID, verbatim_rounds=1)
    assert layered[layered.index(other_room)] is other_room
    assert state["transcriptRoundCount"] == 3
    # 只有本房间的更早轮被 recap，其他房间内容不出现在任何冻结 recap 中。
    recap_messages = _recap_messages(layered)
    assert len(recap_messages) == 2
    assert all("别的房间议题" not in item["content"] for item in recap_messages)


def test_layered_history_passes_seed_invariant():
    seed = _build_meeting_seed(6)
    layered, _ = apply_meeting_history_layering(seed, room_id=ROOM_ID, verbatim_rounds=2)
    # seed_chat_history 的两道门：不允许 silent repair，conversation payload 合法。
    provider_chain = ProviderMessageChain.from_messages(layered)
    assert provider_chain.repaired is False
    invariant = check_conversation_payload_invariant(provider_chain.to_provider_payload())
    assert invariant.ok is True


def test_layering_keeps_conversation_fingerprint_stable_for_verbatim_tail():
    """窗口内消息不变 => 分层只影响 recap 区域，尾段 conversation layer 逐字节一致。"""

    seed = _build_meeting_seed(6)
    layered, _ = apply_meeting_history_layering(seed, room_id=ROOM_ID, verbatim_rounds=2)
    assert conversation_layer_fingerprint(seed[-2:]) == conversation_layer_fingerprint(layered[-2:])


def test_history_chars_reduction_on_six_round_fixture():
    seed = _build_meeting_seed(6)
    baseline, _ = apply_meeting_history_layering(seed, room_id=ROOM_ID, verbatim_rounds=0)
    layered, state = apply_meeting_history_layering(seed, room_id=ROOM_ID, verbatim_rounds=2)

    def total_chars(messages: list[dict]) -> int:
        return sum(len(str(item.get("content") or "")) for item in messages)

    baseline_chars = total_chars(baseline)
    layered_chars = total_chars(layered)
    reduction = (baseline_chars - layered_chars) / baseline_chars
    assert reduction >= 0.35, f"expected >=35% reduction, got {reduction:.2%}"
    # recap 自身对被替换轮次的压缩率应有更大余量。
    recap_reduction = (state["originalChars"] - state["recapChars"]) / state["originalChars"]
    assert recap_reduction >= 0.35


def test_chat_room_gate_only_applies_to_meeting_rooms():
    seed = _build_meeting_seed(6)
    non_meeting_context = {"roomId": ROOM_ID, "meetingType": ""}
    layered, state = chat_room_service._apply_meeting_history_layering_for_room(seed, non_meeting_context)
    # 非会议 session：一律原样返回，不受分层影响。
    assert state is None
    assert layered is seed

    meeting_context = {"roomId": ROOM_ID, "meetingType": "hypothesis_review"}
    layered, state = chat_room_service._apply_meeting_history_layering_for_room(seed, meeting_context)
    assert state is not None
    assert state["recapRoundCount"] == 4
    assert len(layered) == len(seed)
    assert len(_recap_messages(layered)) == 4


@pytest.mark.parametrize("verbatim_rounds", [4, 1])
def test_explicit_rounds_override_via_argument(verbatim_rounds):
    """显式参数路径（env 由调用方解析），保证 wrapper 之外的可测试性。"""

    seed = _build_meeting_seed(6)
    layered, state = apply_meeting_history_layering(seed, room_id=ROOM_ID, verbatim_rounds=verbatim_rounds)
    assert state["verbatimRounds"] == verbatim_rounds
    # 逐轮原位替换不改变消息数；冻结 recap 消息数 = 老化轮数。
    assert len(layered) == len(seed)
    assert len(_recap_messages(layered)) == 6 - verbatim_rounds
