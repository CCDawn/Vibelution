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
    build_room_round_history,
    resolve_meeting_history_verbatim_rounds,
    synthesize_room_round_message,
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


# ---------------------------------------------------------------------------
# 房间轮次合成：失败发言错误详情（有界）对经理/后续发言者可见。
# 失败消息形状对齐 chat_room_service：status=failed、content=""、
# summary="ErrorType: 异常摘要"、errorType="ErrorType"（prep 失败与 runner
# 异常同一契约）；auto-continue 耗尽死信挂在轮记录 autoContinueDeadLetters。
# ---------------------------------------------------------------------------

_MIXED_ROUND_SUMMARY = "本轮群聊完成：2/4 位参与者成功发言，2 位未成功（失败 2、受阻 0、停止 0、0 位部分完成）。"
_SUCCESS_ROUND_SUMMARY = "本轮群聊完成：2/2 位参与者成功发言，0 位未成功（失败 0、受阻 0、停止 0、0 位部分完成）。"


def _speaker_message(
    speaker: str,
    participant_id: str,
    *,
    status: str = "completed",
    content: str = "围绕议题给出结论。",
    summary: str = "",
    error_type: str = "",
) -> dict:
    return {
        "participantId": participant_id,
        "speakerTitle": speaker,
        "status": status,
        "content": content,
        "summary": summary,
        "errorType": error_type,
    }


def _failed_message(
    index: int,
    *,
    error_type: str = "AgentLlmResolutionError",
    summary: str | None = None,
    participant_id: str = "",
    speaker: str = "",
) -> dict:
    return _speaker_message(
        speaker or f"失败成员{index}",
        participant_id or f"participant-f{index}",
        status="failed",
        content="",
        summary=(
            summary
            if summary is not None
            else f"{error_type}: 无法解析成员 {index} 的模型绑定"
        ),
        error_type=error_type,
    )


def _failure_section(content: str) -> str:
    assert "失败发言详情:" in content
    return content.split("失败发言详情:", 1)[1]


def test_room_round_synthesis_keeps_count_line_and_adds_failure_details():
    round_payload = {
        "roundId": "round-mixed",
        "topic": "接口联调",
        "summary": _MIXED_ROUND_SUMMARY,
        "status": "completed",
        "messages": [
            _speaker_message("经理", "participant-m", content="请补齐失败项后重新评估。"),
            _speaker_message("甲研究员", "participant-a", content="实验数据已复核。"),
            _failed_message(1),
            _failed_message(
                2,
                error_type="PromptAssemblyBudgetError",
                summary="PromptAssemblyBudgetError: 预算超限",
            ),
        ],
    }
    message = synthesize_room_round_message(
        round_payload, round_number=1, room_id=ROOM_ID, participant_id="participant-a"
    )
    content = message["content"]
    # 既有失败计数行保留（轮 summary 原样进入「摘要:」行）。
    assert f"摘要: {_MIXED_ROUND_SUMMARY}" in content
    # 成功发言仍进入 own/peer 段。
    assert "- 甲研究员: 实验数据已复核。" in content
    assert "- 经理: 请补齐失败项后重新评估。" in content
    # 失败详情段：speaker + errorType + 异常摘要（summary 已带类名时不重复）。
    section = _failure_section(content)
    assert "- 失败成员1: AgentLlmResolutionError: 无法解析成员 1 的模型绑定" in section
    assert "- 失败成员2: PromptAssemblyBudgetError: 预算超限" in section
    # 纯投影确定性：同一轮 payload 两次合成逐字节一致。
    again = synthesize_room_round_message(
        round_payload, round_number=1, room_id=ROOM_ID, participant_id="participant-a"
    )
    assert again == message


def test_room_round_failure_details_truncated_beyond_three_entries():
    round_payload = {
        "roundId": "round-many-failures",
        "topic": "回归验证",
        "summary": "本轮群聊完成：1/6 位参与者成功发言，5 位未成功（失败 5、受阻 0、停止 0、0 位部分完成）。",
        "status": "completed",
        "messages": [
            _speaker_message("经理", "participant-m"),
            *(_failed_message(index) for index in range(1, 6)),
        ],
    }
    content = synthesize_room_round_message(round_payload, round_number=2, room_id=ROOM_ID)["content"]
    section = _failure_section(content)
    bullets = [line for line in section.splitlines() if line.startswith("- ")]
    # 有界：3 条详情 + 1 条截断说明。
    assert len(bullets) == 4
    assert bullets[0].startswith("- 失败成员1: ")
    assert bullets[2].startswith("- 失败成员3: ")
    assert bullets[3] == "- 其余 2 条失败详情已截断"
    assert "失败成员4" not in section
    assert "失败成员5" not in section


def test_room_round_failure_detail_is_line_and_char_bounded():
    long_summary = "RuntimeError: " + "调用链路过长需要收敛 " * 60
    round_payload = {
        "roundId": "round-bounded",
        "topic": "长异常截断",
        "summary": _MIXED_ROUND_SUMMARY,
        "status": "completed",
        "messages": [
            _speaker_message("经理", "participant-m"),
            _failed_message(1, summary=long_summary),
            _failed_message(
                2,
                error_type="ValueError",
                summary="ValueError: 第一行\n第二行\n第三行\n第四行",
            ),
        ],
    }
    content = synthesize_room_round_message(round_payload, round_number=1, room_id=ROOM_ID)["content"]
    long_bullet = next(line for line in content.splitlines() if "RuntimeError" in line)
    # 240 字符上限 + 省略号（"- " + speaker + ": " 前缀之外即为详情主体）。
    assert long_bullet.endswith("…")
    assert len(long_bullet) <= len("- 失败成员1: ") + 240 + 1
    # 多行摘要只保留前 2 行。
    assert "ValueError: 第一行\n第二行" in content
    assert "第三行" not in content
    assert "第四行" not in content


def test_pure_success_round_synthesis_matches_legacy_shape():
    round_payload = {
        "roundId": "round-success",
        "topic": "接口联调",
        "summary": _SUCCESS_ROUND_SUMMARY,
        "status": "completed",
        "messages": [
            _speaker_message("甲研究员", "participant-a", content="实验数据已复核。"),
            _speaker_message("乙分析师", "participant-b", content="结论成立。"),
        ],
    }
    message = synthesize_room_round_message(
        round_payload,
        round_number=1,
        room_id=ROOM_ID,
        room_title="评审会议",
    )
    expected = "\n".join(
        [
            "[群聊同步]",
            "群聊: 评审会议",
            "议题: 接口联调",
            f"摘要: {_SUCCESS_ROUND_SUMMARY}",
            "",
            "你的发言:",
            "- 本轮你没有发言。",
            "",
            "其他 Agent 发言:",
            "- 甲研究员: 实验数据已复核。",
            "- 乙分析师: 结论成立。",
        ]
    )
    # 纯成功轮不加失败详情段，字节与旧契约一致。
    assert message["content"] == expected


def test_failure_detail_degrades_without_error_type():
    round_payload = {
        "roundId": "round-degraded",
        "topic": "降级形态",
        "summary": _MIXED_ROUND_SUMMARY,
        "status": "completed",
        "messages": [
            _speaker_message("经理", "participant-m"),
            _failed_message(1, error_type="", summary=""),
            _failed_message(2, error_type="", summary="模型解析失败"),
        ],
    }
    content = synthesize_room_round_message(round_payload, round_number=1, room_id=ROOM_ID)["content"]
    section = _failure_section(content)
    # 拿不到 errorType：有 summary 用 summary，两者皆空只留 speaker+status。
    assert "- 失败成员2: 模型解析失败" in section
    assert "- 失败成员1: status=failed" in section


def test_open_dead_letter_surfaces_and_resolved_ignored():
    round_payload = {
        "roundId": "round-deadletter",
        "topic": "自动续写耗尽",
        "summary": "本轮群聊完成：1/2 位参与者成功发言，1 位未成功（失败 0、受阻 0、停止 0、1 位部分完成）。",
        "status": "completed",
        "messages": [
            _speaker_message("经理", "participant-m"),
            _speaker_message(
                "丙工程师", "participant-p3", status="partial", content="分析进行到一半"
            ),
        ],
        "autoContinueDeadLetters": [
            {
                "participantId": "participant-p3",
                "attemptCount": 4,
                "reason": "quota_exhausted",
                "status": "open",
                "lastErrorCategory": "provider",
                "lastErrorDisposition": "retry",
                "lastErrorSummary": "ConnectionError: 上游超时",
            },
            {
                "participantId": "participant-p9",
                "attemptCount": 3,
                "reason": "deadline_insufficient",
                "status": "resolved",
                "lastErrorSummary": "ConnectionError: 已恢复",
            },
        ],
    }
    content = synthesize_room_round_message(round_payload, round_number=1, room_id=ROOM_ID)["content"]
    section = _failure_section(content)
    # open 死信有界纳入：speaker 由 participantId 映射，reason/尝试次数/末错齐全。
    assert "- 丙工程师: 自动续写耗尽（quota_exhausted，尝试 4 次）：ConnectionError: 上游超时" in section
    # resolved 死信已恢复，不再进入详情。
    assert "deadline_insufficient" not in section
    assert "已恢复" not in section


def test_dead_letter_skipped_when_message_level_failure_present():
    round_payload = {
        "roundId": "round-dedupe",
        "topic": "去重",
        "summary": _MIXED_ROUND_SUMMARY,
        "status": "completed",
        "messages": [
            _speaker_message("经理", "participant-m"),
            _failed_message(
                1, participant_id="participant-f1", speaker="丙工程师"
            ),
        ],
        "autoContinueDeadLetters": [
            {
                "participantId": "participant-f1",
                "attemptCount": 2,
                "reason": "quota_exhausted",
                "status": "open",
                "lastErrorSummary": "ConnectionError: 上游超时",
            }
        ],
    }
    content = synthesize_room_round_message(round_payload, round_number=1, room_id=ROOM_ID)["content"]
    section = _failure_section(content)
    # 同一 participant 既有 failed 消息又有 open 死信：只保留消息级详情。
    detail_bullets = [
        line for line in section.splitlines() if line.startswith("- ") and "自动续写耗尽" not in line
    ]
    assert detail_bullets == ["- 丙工程师: AgentLlmResolutionError: 无法解析成员 1 的模型绑定"]


def test_build_room_round_history_keeps_failure_details_in_verbatim_tail():
    mixed_round = {
        "roundId": "round-mixed",
        "topic": "接口联调",
        "summary": _MIXED_ROUND_SUMMARY,
        "status": "completed",
        "messages": [
            _speaker_message("经理", "participant-m"),
            _failed_message(1),
        ],
    }
    success_round = {
        "roundId": "round-success",
        "topic": "复审",
        "summary": _SUCCESS_ROUND_SUMMARY,
        "status": "completed",
        "messages": [_speaker_message("甲研究员", "participant-a")],
    }
    messages, state = build_room_round_history(
        [mixed_round, success_round],
        room_id=ROOM_ID,
        room_title="评审会议",
        participant_id="participant-a",
        verbatim_rounds=2,
    )
    assert state["terminalRoundCount"] == 2
    # 逐字窗口内的合成轮次消息带失败详情，经理重新被唤起时可见失败原因。
    assert "失败发言详情:" in messages[0]["content"]
    assert "AgentLlmResolutionError" in messages[0]["content"]
    assert "失败发言详情:" not in messages[1]["content"]
