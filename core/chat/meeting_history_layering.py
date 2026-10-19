# -*- coding: utf-8 -*-
"""会议参会者历史的确定性分层压缩投影。

点对点传输切换（chatroom-p2p-transport）后，``chat_room_service`` 不再向参会
者 session ledger 广播整轮「[群聊同步]」转写；本模块因此有两个数据源路径：

- 遗留路径 ``apply_meeting_history_layering``：只投影历史上已经写入 ledger 的
  同步消息（迁移期房间），最近若干轮保留原文，更早的轮次收成固定回顾；
- 房间轮次路径 ``build_room_round_history``：直接从房间持久化 rounds 合成与
  旧转写同形的轮次消息，再做同样的逐字/回顾分层——group 事件不再写入后，
  会议房参会者的房间视图由房间 rounds 而非 session ledger 承担。

- 最近 M 轮同步消息逐字保留（M 由环境变量
  ``VIBELUTION_MEETING_HISTORY_VERBATIM_ROUNDS`` 控制，默认 2，0=禁用）；
- 更早的每一轮**原位**替换为一条冻结 recap assistant 消息（一轮一条）。

闭轮冻结（稳定前缀契约）：

- 一条冻结 recap 只依赖两样输入：该轮不可变的原文，以及该轮在本房间
  轮次序列中的绝对序号（1-based，出现顺序）。渲染是确定性纯函数（无 LLM、
  无时间戳、无随机），因此闭轮 recap 语义冻结：重复投影逐字节一致，不因后
  续轮次增加、窗口滑动或重算路径不同而漂移——无需持久化即保证「永不改字
  节」，因为重算与首算逐字节相同；
- 一轮从逐字窗滑出时发生**一次性** verbatim→recap 转换；此后每开一轮，投影
  字节变化只从「正在老化出的那一轮」开始，更早的冻结前缀逐字节不变。这与
  Manus 上下文工程的稳定前缀 + append-only 铁律、以及 ZCode 微压缩的
  preserveCanonicalContextPrefix/copy-on-write（只改尾部保前缀）同构。

硬约束：

- ledger 原文不动：本模块只作用于投影的 history seed 消息序列或房间 rounds
  只读快照，不写回任何存储；
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

# 失败发言详情段（有界投影）：合成轮次消息在成功发言之外，为经理/后续发
# 言者保留失败原因（speaker + errorType + 截断异常摘要；auto-continue 耗尽
# 死信一并纳入）。有界约束：最多 3 条、每条截断到 2 行 / 240 字符；纯成功
# 轮不追加该段，字节与旧契约一致。``_parse_round_lines`` 不认识该段标记，
# 失败详情不进入冻结 recap（recap 语义保持逐字节不变）。
_FAILURE_SECTION_MARKER = "失败发言详情:"
_FAILURE_DETAIL_MAX_ENTRIES = 3
_FAILURE_DETAIL_MAX_LINES = 2
_FAILURE_DETAIL_MAX_CHARS = 240
_DEAD_LETTER_STATUS_OPEN = "open"


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


TERMINAL_ROUND_STATUSES = frozenset(
    {"completed", "partial", "stopped", "failed", "cancelled"}
)


def _round_completed_utterances(round_payload: Any) -> list[tuple[str, str]]:
    """Extract ``(speaker, bounded content)`` for one terminal room round."""

    utterances: list[tuple[str, str]] = []
    messages = round_payload.get("messages") if isinstance(round_payload, dict) else None
    for message in list(messages or []):
        if not isinstance(message, dict):
            continue
        if str(message.get("status") or "").strip().lower() != "completed":
            continue
        speaker = str(message.get("speakerTitle") or message.get("participantId") or "").strip()
        content = _trim_lines_bounded(
            str(message.get("content") or message.get("summary") or ""),
            max_lines=4,
        )
        if not content:
            continue
        utterances.append((speaker, content))
    return utterances


def _trim_lines_bounded(text: str, *, max_lines: int) -> str:
    lines = [line.rstrip() for line in str(text or "").splitlines() if line.strip()]
    return "\n".join(lines[:max_lines])


def _cap_failure_detail_chars(text: str) -> str:
    if len(text) <= _FAILURE_DETAIL_MAX_CHARS:
        return text
    return f"{text[:_FAILURE_DETAIL_MAX_CHARS]}…"


def _failed_message_detail(message: dict[str, Any]) -> str:
    """把一条 failed 发言压成有界摘要（errorType + 截断异常文本）。

    ``chat_room_service`` 两条失败路径（prep 失败与 runner 异常）的 summary
    均形如 ``"ErrorType: 异常摘要"``，与 errorType 同时存在时不再重复回显类
    名；拿不到 errorType 时按 summary 降级，两者皆空时只留 status。
    """

    error_type = str(message.get("errorType") or "").strip()
    summary = _trim_lines_bounded(
        str(message.get("summary") or ""), max_lines=_FAILURE_DETAIL_MAX_LINES
    )
    if error_type and summary.startswith(f"{error_type}:"):
        detail = summary
    elif error_type and summary:
        detail = f"{error_type}: {summary}"
    elif error_type:
        detail = error_type
    elif summary:
        detail = summary
    else:
        detail = "status=failed"
    return _cap_failure_detail_chars(detail)


def _dead_letter_detail(dead_letter: dict[str, Any]) -> str:
    """把一条 auto-continue 耗尽死信压成有界摘要（reason + 尝试次数 + 末错）。"""

    reason = str(dead_letter.get("reason") or "").strip()
    try:
        attempts = int(dead_letter.get("attemptCount") or 0)
    except (TypeError, ValueError):
        attempts = 0
    last_error = _trim_lines_bounded(
        str(dead_letter.get("lastErrorSummary") or ""), max_lines=_FAILURE_DETAIL_MAX_LINES
    )
    bits = [bit for bit in (reason, f"尝试 {attempts} 次" if attempts > 0 else "") if bit]
    head = f"自动续写耗尽（{'，'.join(bits)}）" if bits else "自动续写耗尽"
    detail = f"{head}：{last_error}" if last_error else head
    return _cap_failure_detail_chars(detail)


def _round_failure_details(round_payload: Any) -> tuple[list[tuple[str, str]], int]:
    """Collect bounded ``(speaker, digest)`` failure entries for one round.

    failed 发言（消息顺序）在前；未 resolved 的 auto-continue 死信在后，且同
    一 participant 已有消息级失败详情时跳过（消息级信息更权威，去重）。返回
    ``(entries, hidden_count)``：超过上限的条目被截断并计数。纯投影——只读
    不可变轮 payload，不依赖时间/随机，与模块其余部分同样确定性。
    """

    if not isinstance(round_payload, dict):
        return [], 0
    messages = [item for item in list(round_payload.get("messages") or []) if isinstance(item, dict)]
    entries: list[tuple[str, str]] = []
    failed_participants: set[str] = set()
    for message in messages:
        if str(message.get("status") or "").strip().lower() != "failed":
            continue
        speaker = str(message.get("speakerTitle") or message.get("participantId") or "").strip()
        entries.append((speaker, _failed_message_detail(message)))
        participant_id = str(message.get("participantId") or "").strip()
        if participant_id:
            failed_participants.add(participant_id)
    speaker_by_participant = {
        str(message.get("participantId") or "").strip(): str(
            message.get("speakerTitle") or message.get("participantId") or ""
        ).strip()
        for message in messages
        if str(message.get("participantId") or "").strip()
    }
    for dead_letter in list(round_payload.get("autoContinueDeadLetters") or []):
        if not isinstance(dead_letter, dict):
            continue
        if str(dead_letter.get("status") or "").strip() != _DEAD_LETTER_STATUS_OPEN:
            continue
        participant_id = str(dead_letter.get("participantId") or "").strip()
        if participant_id and participant_id in failed_participants:
            continue
        speaker = speaker_by_participant.get(participant_id) or participant_id
        entries.append((speaker, _dead_letter_detail(dead_letter)))
    if len(entries) <= _FAILURE_DETAIL_MAX_ENTRIES:
        return entries, 0
    hidden = len(entries) - _FAILURE_DETAIL_MAX_ENTRIES
    return entries[:_FAILURE_DETAIL_MAX_ENTRIES], hidden


def synthesize_room_round_message(
    round_payload: Any,
    *,
    round_number: int,
    room_id: str,
    room_title: str = "",
    participant_id: str = "",
) -> dict[str, Any]:
    """Project one terminal room round into the legacy sync-message shape.

    Deterministic pure function of the round payload: same input produces the
    same bytes, so the verbatim window and frozen recaps built on top keep
    their stable-prefix contract.  The output carries the
    ``group_room_transcript`` metadata so downstream consumers (recap parser,
    token buckets) treat it exactly like the ledger transcripts it replaces.

    Failure visibility (bounded): the round summary keeps its existing failure
    count line, and when the round has failed speeches (or unresolved
    auto-continue dead letters) a trailing ``失败发言详情:`` section appends up
    to three ``speaker + errorType + 截断异常摘要`` entries so the manager and
    later speakers can see why a turn failed.  Pure-success rounds emit no
    such section — byte-identical to the legacy shape.
    """

    room_id_normalized = str(room_id or "").strip()
    topic = str(round_payload.get("topic") or "").strip() if isinstance(round_payload, dict) else ""
    summary = str(round_payload.get("summary") or "").strip() if isinstance(round_payload, dict) else ""
    own_lines: list[str] = []
    peer_lines: list[str] = []
    participant_normalized = str(participant_id or "").strip()
    for speaker, content in _round_completed_utterances(round_payload):
        line = f"- {speaker}: {content}" if speaker else f"- {content}"
        if participant_normalized and speaker == participant_normalized:
            own_lines.append(line)
        else:
            peer_lines.append(line)
    content_lines = [
        _SYNC_HEADER_LINE,
        f"群聊: {room_title or room_id_normalized}",
        f"{_TOPIC_PREFIX}{topic}",
        f"{_SUMMARY_PREFIX}{summary}",
        "",
        _MY_SECTION_MARKER,
        *(own_lines or ["- 本轮你没有发言。"]),
        "",
        _PEER_SECTION_MARKER,
        *(peer_lines or ["- 本轮暂无其他 Agent 发言。"]),
    ]
    failure_entries, failure_hidden = _round_failure_details(round_payload)
    if failure_entries:
        failure_lines = [
            f"- {speaker}: {detail}" if speaker else f"- {detail}"
            for speaker, detail in failure_entries
        ]
        if failure_hidden:
            failure_lines.append(f"- 其余 {failure_hidden} 条失败详情已截断")
        content_lines.extend(["", _FAILURE_SECTION_MARKER, *failure_lines])
    round_id = str(round_payload.get("roundId") or "").strip() if isinstance(round_payload, dict) else ""
    return {
        "role": "assistant",
        "content": "\n".join(content_lines),
        "metadata": {
            "kind": GROUP_ROOM_TRANSCRIPT_KIND,
            "sourceRoomId": room_id_normalized,
            "sourceRoundId": round_id,
            "sourceRoomTitle": str(room_title or "").strip(),
            "participantId": participant_normalized,
            "roundNumber": int(round_number),
        },
    }


def build_room_round_history(
    rounds: Iterable[Any],
    *,
    room_id: str,
    room_title: str = "",
    participant_id: str = "",
    verbatim_rounds: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build the meeting speaker's room view from persisted room rounds.

    Terminal rounds only (the running round the speaker is currently
    contributing to is not history).  Each round is synthesized into the
    legacy sync-message shape and then run through the same verbatim/recap
    layering as ledger transcripts, so a meeting speaker keeps cross-round
    context after broadcast transcript fan-out stopped writing group events
    into session ledgers.  Returns ``(messages, state)``.
    """

    terminal_rounds = [
        round_payload
        for round_payload in list(rounds or [])
        if isinstance(round_payload, dict)
        and str(round_payload.get("status") or "").strip().lower() in TERMINAL_ROUND_STATUSES
    ]
    synthesized = [
        synthesize_room_round_message(
            round_payload,
            round_number=number,
            room_id=room_id,
            room_title=room_title,
            participant_id=participant_id,
        )
        for number, round_payload in enumerate(terminal_rounds, start=1)
    ]
    layered, state = apply_meeting_history_layering(
        synthesized,
        room_id=room_id,
        verbatim_rounds=verbatim_rounds,
    )
    state["dataSource"] = "room_rounds"
    state["terminalRoundCount"] = len(terminal_rounds)
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
    "TERMINAL_ROUND_STATUSES",
    "apply_meeting_history_layering",
    "build_meeting_round_recap",
    "build_room_round_history",
    "is_group_room_transcript_message",
    "resolve_meeting_history_verbatim_rounds",
    "synthesize_room_round_message",
]
