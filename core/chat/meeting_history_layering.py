# -*- coding: utf-8 -*-
"""会议参会者历史的确定性分层压缩投影。

评审会议每轮结束后，``chat_room_service._sync_group_round_to_participant_sessions``
把本轮全部发言拼成一条「[群聊同步]」assistant 消息追加到每个参会者 session
ledger。多轮会议之后，参会者历史 seed 会全量重放所有轮次原文，历史重放占据
单轮 prompt 的绝大部分。本模块在历史 seed 上做一层**纯投影**：

- 最近 M 轮「[群聊同步]」消息逐字保留（M 由环境变量
  ``VIBELUTION_MEETING_HISTORY_VERBATIM_ROUNDS`` 控制，默认 2，0=禁用）；
- 更早的每一轮**原位**替换为一条冻结 recap assistant 消息（一轮一条）。

闭轮冻结（稳定前缀契约）：

- 一条冻结 recap 只依赖两样输入：该轮不可变的 ledger 原文，以及该轮在本房间
  轮次序列中的绝对序号（1-based，出现顺序）。渲染是确定性纯函数（无 LLM、
  无时间戳、无随机），因此闭轮 recap 语义冻结：重复投影逐字节一致，不因后
  续轮次增加、窗口滑动或重算路径不同而漂移——无需持久化即保证「永不改字
  节」，因为重算与首算逐字节相同；
- 一轮从逐字窗滑出时发生**一次性** verbatim→recap 转换；此后每开一轮，投影
  字节变化只从「正在老化出的那一轮」开始，更早的冻结前缀逐字节不变。这与
  Manus 上下文工程的稳定前缀 + append-only 铁律、以及 ZCode 微压缩的
  preserveCanonicalContextPrefix/copy-on-write（只改尾部保前缀）同构。

硬约束：

- ledger 原文不动：本模块只作用于已投影的 history seed 消息序列，不写回
  ConversationLedger，因此 ``_has_group_round_session_sync`` 的幂等重同步与
  ledger fingerprint 均不受影响；
- conversation invariant 安全：recap 是纯 assistant 文本消息（无 tool_calls、
  无 silent-repair metadata），插入/替换发生在 assembler 的
  ``conversation_layer_fingerprint`` 双向校验之后（校验对象是 ledger 投影视
  图，recap 属于后处理层，不参与 fingerprint），也不会破坏
  ``seed_chat_history`` 的 provider tool 链不变量；
- recap 不进入 cacheable system prompt，始终保持 history 消息形态，同一轮内
  两次装配结果逐字节一致；跨轮的稳定前缀位于 qwen cache_control 断点（当前
  user 前最后一条 history，见 core/llm/payload_builder.py）之前，前缀缓存按
  最长公共前缀命中到老化边界，每轮至多一次显式缓存重建。

借鉴：core/chat/context_compression_ledger 的「按 event sequence 覆盖的投影
层替换」思想（压缩 checkpoint 以投影层覆盖历史）与业界分层压缩（近期原文 +
远期摘要）的通行结构。
"""

from __future__ import annotations

import os
from typing import Any, Iterable

MEETING_HISTORY_VERBATIM_ROUNDS_ENV = "VIBELUTION_MEETING_HISTORY_VERBATIM_ROUNDS"
DEFAULT_MEETING_HISTORY_VERBATIM_ROUNDS = 2

# 「[群聊同步]」消息的 metadata.kind 标记（与 chat_room_service 保持一致）。
GROUP_ROOM_TRANSCRIPT_KIND = "group_room_transcript"
# 分层后冻结 recap 消息的 metadata.kind 标记。
MEETING_HISTORY_RECAP_KIND = "meeting_history_recap"

# recap 中每条发言保留的首行内容上限（字符）。
RECAP_SPEAKER_CHAR_LIMIT = 120
# recap 固定头（逐字节确定；不要在运行期拼接时间/随机量）。
RECAP_HEADER = "[会议历史回顾]"
RECAP_HEADER_NOTE = "以下为更早轮次的确定性摘要，发言原文见会话历史与会议记录。"

_SYNC_HEADER_LINE = "[群聊同步]"
_TOPIC_PREFIX = "议题: "
_SUMMARY_PREFIX = "摘要: "
_MY_SECTION_MARKER = "你的发言:"
_PEER_SECTION_MARKER = "其他 Agent 发言:"
_BULLET_PREFIX = "- "
_SPEAKER_SEPARATOR = ": "


def resolve_meeting_history_verbatim_rounds(env: str | None = None) -> int:
    """解析逐字保留轮数旋钮。

    默认 2；显式 0 或负数=禁用；非法值回退默认，避免手误把旋钮写成
    非整数时静默改变窗口大小。
    """

    raw = os.environ.get(MEETING_HISTORY_VERBATIM_ROUNDS_ENV, "") if env is None else env
    text = str(raw or "").strip()
    if not text:
        return DEFAULT_MEETING_HISTORY_VERBATIM_ROUNDS
    try:
        value = int(text)
    except (TypeError, ValueError):
        return DEFAULT_MEETING_HISTORY_VERBATIM_ROUNDS
    if value <= 0:
        return 0
    return value


def is_group_room_transcript_message(message: Any, *, room_id: str = "") -> bool:
    """识别「[群聊同步]」轮次同步消息。

    优先读 metadata（``kind == group_room_transcript``）；投影后的 model
    消息保留 ledger payload 的 metadata，这是最可靠来源。metadata 缺失时退
    回内容启发式（与 ``_is_group_room_transcript_message`` 的判断精神一致）。

    ``room_id`` 非空时要求消息归属该房间：metadata ``sourceRoomId`` 必须相
    等；无 metadata 的内容启发式只对内容里包含该房间标识的消息成立，避免把
    其他房间的同步消息误分层。
    """

    if not isinstance(message, dict):
        return False
    normalized_room_id = str(room_id or "").strip()
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    kind = str(metadata.get("kind") or "").strip()
    if kind == GROUP_ROOM_TRANSCRIPT_KIND:
        if not normalized_room_id:
            return True
        return str(metadata.get("sourceRoomId") or "").strip() == normalized_room_id
    content = str(message.get("content") or "")
    if _SYNC_HEADER_LINE not in content:
        return False
    if not normalized_room_id:
        return True
    # 无 metadata 的兜底：内容启发式无法可靠判定房间，仅当房间标识出现在
    # 内容中时才认领（chat_room_service 的既有兜底语义）。
    return normalized_room_id in content


def apply_meeting_history_layering(
    messages: Iterable[Any],
    *,
    room_id: str,
    verbatim_rounds: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """对参会者 history seed 做会议轮次分层压缩的确定性纯投影。

    返回 ``(layered_messages, state)``。输入序列不修改（copy-on-write）。

    - ``verbatim_rounds <= 0``：禁用，原样返回（与基线装配逐字节一致）；
    - 「[群聊同步]」轮次消息按出现顺序视作轮（每轮恰有一条同步消息，由
      ``_has_group_round_session_sync`` 幂等保证）；最近 M 轮逐字保留；
    - 更早的每一轮原位替换为单轮冻结 recap assistant 消息（一轮一条，消息
      数不变），非同步消息（本轮任务提示、工具链等）一律不动。
    """

    source = list(messages or [])
    normalized_room_id = str(room_id or "").strip()
    resolved_rounds = (
        resolve_meeting_history_verbatim_rounds()
        if verbatim_rounds is None
        else max(0, int(verbatim_rounds or 0))
    )
    state: dict[str, Any] = {
        "enabled": resolved_rounds > 0,
        "verbatimRounds": resolved_rounds,
        "roomId": normalized_room_id,
        "transcriptRoundCount": 0,
        "recapRoundCount": 0,
        "recappedRoundIds": [],
        "originalChars": 0,
        "recapChars": 0,
    }
    if resolved_rounds <= 0 or not source:
        return source, state

    transcript_indexes = [
        index
        for index, message in enumerate(source)
        if is_group_room_transcript_message(message, room_id=normalized_room_id)
    ]
    state["transcriptRoundCount"] = len(transcript_indexes)
    if len(transcript_indexes) <= resolved_rounds:
        return source, state

    recapped_indexes = transcript_indexes[:-resolved_rounds]
    # 轮的绝对序号（1-based，按本房间轮次出现顺序）；闭轮后不再变化，是冻结
    # recap 字节的一部分。
    round_number_by_index = {
        index: number for number, index in enumerate(transcript_indexes, start=1)
    }

    recap_message_by_index: dict[int, dict[str, Any]] = {}
    original_chars = 0
    recap_chars = 0
    for index in recapped_indexes:
        round_message = source[index]
        recap_message = _build_round_recap_message(
            round_message,
            round_number=round_number_by_index[index],
            room_id=normalized_room_id,
        )
        recap_message_by_index[index] = recap_message
        original_chars += len(str(round_message.get("content") or ""))
        recap_chars += len(recap_message["content"])

    state["recapRoundCount"] = len(recapped_indexes)
    state["recappedRoundIds"] = _recapped_round_ids([source[index] for index in recapped_indexes])
    state["originalChars"] = original_chars
    state["recapChars"] = recap_chars

    layered: list[dict[str, Any]] = []
    for index, message in enumerate(source):
        recap_message = recap_message_by_index.get(index)
        # 原位替换：冻结 recap 占据该轮同步消息的确切位置，其前其后的非替换
        # 消息逐字节不动。
        layered.append(recap_message if recap_message is not None else message)
    return layered, state


def build_meeting_round_recap(message: Any, *, round_number: int) -> str:
    """把一条已关闭轮次的「[群聊同步]」消息渲染成该轮的冻结 recap 文本。

    只依赖该轮消息原文与轮次绝对序号：输入相同则输出逐字节相同，不读其他
    轮次、窗口大小或任何运行期状态（时间、随机、集合迭代序），因此对同一
    闭轮重复调用永不改字节（冻结语义由纯函数确定性保证）。
    """

    round_lines = _parse_round_lines(message)
    lines: list[str] = [
        RECAP_HEADER,
        RECAP_HEADER_NOTE,
        f"## 轮 {int(round_number)}: {round_lines.topic}",
    ]
    for speaker, content in round_lines.utterances:
        bounded = _bounded_recap_content(content)
        if speaker:
            lines.append(f"- {speaker}：{bounded}")
        else:
            lines.append(f"- {bounded}")
    return "\n".join(lines)


class _RoundLines:
    """单条「[群聊同步]」消息的确定性解析结果。"""

    __slots__ = ("topic", "summary", "utterances")

    def __init__(self, topic: str, summary: str, utterances: list[tuple[str, str]]) -> None:
        self.topic = topic
        self.summary = summary
        self.utterances = utterances


def _parse_round_lines(message: Any) -> _RoundLines:
    content = str(message.get("content") or "") if isinstance(message, dict) else str(message or "")
    topic = ""
    summary = ""
    utterances: list[tuple[str, str]] = []
    section_active = False
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line == _SYNC_HEADER_LINE:
            continue
        if line.startswith(_TOPIC_PREFIX):
            topic = line[len(_TOPIC_PREFIX):].strip()
            continue
        if line.startswith(_SUMMARY_PREFIX):
            summary = line[len(_SUMMARY_PREFIX):].strip()
            continue
        if line == _MY_SECTION_MARKER or line == _PEER_SECTION_MARKER:
            section_active = True
            continue
        if line.startswith(_BULLET_PREFIX) and section_active:
            utterances.append(_split_speaker_utterance(line[len(_BULLET_PREFIX):]))
            continue
        section_active = False
    if not topic:
        topic = summary or "（无议题记录）"
    return _RoundLines(topic=topic, summary=summary, utterances=utterances)


def _split_speaker_utterance(body: str) -> tuple[str, str]:
    """把「speaker: content」拆成 (speaker, content)；无分隔符时整段是内容。"""

    separator_index = body.find(_SPEAKER_SEPARATOR)
    if separator_index <= 0:
        return "", body.strip()
    speaker = body[:separator_index].strip()
    content = body[separator_index + len(_SPEAKER_SEPARATOR):].strip()
    return speaker, content


def _bounded_recap_content(content: str) -> str:
    first_line = next((line.strip() for line in str(content or "").splitlines() if line.strip()), "")
    if len(first_line) <= RECAP_SPEAKER_CHAR_LIMIT:
        return first_line
    return f"{first_line[:RECAP_SPEAKER_CHAR_LIMIT]}…"


def _recapped_round_ids(recapped: list[Any]) -> list[str]:
    ids: list[str] = []
    for message in recapped:
        metadata = message.get("metadata") if isinstance(message, dict) and isinstance(message.get("metadata"), dict) else {}
        round_id = str(metadata.get("sourceRoundId") or "").strip()
        ids.append(round_id)
    return ids


def _build_round_recap_message(
    message: Any,
    *,
    round_number: int,
    room_id: str,
) -> dict[str, Any]:
    metadata = (
        message.get("metadata")
        if isinstance(message, dict) and isinstance(message.get("metadata"), dict)
        else {}
    )
    return {
        "role": "assistant",
        "content": build_meeting_round_recap(message, round_number=round_number),
        "metadata": {
            "kind": MEETING_HISTORY_RECAP_KIND,
            "sourceRoomId": str(room_id or "").strip(),
            "roundNumber": int(round_number),
            "sourceRoundId": str(metadata.get("sourceRoundId") or "").strip(),
        },
    }


__all__ = [
    "DEFAULT_MEETING_HISTORY_VERBATIM_ROUNDS",
    "MEETING_HISTORY_VERBATIM_ROUNDS_ENV",
    "MEETING_HISTORY_RECAP_KIND",
    "GROUP_ROOM_TRANSCRIPT_KIND",
    "apply_meeting_history_layering",
    "build_meeting_round_recap",
    "is_group_room_transcript_message",
    "resolve_meeting_history_verbatim_rounds",
]
