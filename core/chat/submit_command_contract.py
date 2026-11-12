"""Single-source submit-command contract for platform and assistant transports.

平台 ``POST /sessions/{id}/messages`` 与助理 ``POST /api/assistant/messages``
表达同一个语义提交命令，但 wire 字段名不同（``content``/``message``、
``clientSubmissionId``/``requestId``）。两边各自保留既有 wire 契约，只在本模块
归一化成同一个 :class:`ChatSubmitCommand`，让共有字段的语义、默认值和校验规则
只维护一份。

边界说明：本模块只承载两边**语义等价**的部分。平台独有字段（``turnMode``、
``writeIntent``、``modelSelection`` 等）留在各自的 payload 上，不进入规范层，
避免把平台专有能力误当成共有约定。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# 两边共用同一上限；改这里等于同时改两个入口。
MAX_CLIENT_SUBMISSION_ID = 128
MAX_CONTINUATION_TURN_ID = 160
MAX_CONTINUATION_HEAD_ID = 200
MAX_CONTINUATION_AGENT_ID = 160

# 规范层字段 -> 各入口 wire 字段名。新增语义字段时三处一起改，
# 契约测试会拦住只改一边的情况。
CANONICAL_TO_PLATFORM = {
    "content": "content",
    "client_submission_id": "clientSubmissionId",
    "attachment_ids": "attachmentIds",
    "references": "references",
    "continuation": "continuation",
}

CANONICAL_TO_ASSISTANT = {
    "content": "message",
    "client_submission_id": "requestId",
    "attachment_ids": "attachmentIds",
    "references": "references",
    "continuation": "controlContinuation",
}


class SubmitCommandError(ValueError):
    """规范层拒绝一次提交；调用方负责映射成各自入口的错误码。"""


@dataclass(frozen=True, slots=True)
class ContinuationCommand:
    """一次续写的定位信息；两个入口的 continuation 形状完全一致。"""

    turn_id: str
    head_id: str
    ledger_seq: int
    agent_id: str


@dataclass(frozen=True, slots=True)
class ChatSubmitCommand:
    """两边共有的提交语义。平台独有字段不在此列。"""

    content: str
    client_submission_id: str
    attachment_ids: tuple[str, ...]
    references: tuple[Mapping[str, Any], ...]
    continuation: ContinuationCommand | None


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _items(value: Any) -> tuple:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(value)


def _continuation(raw: Any) -> ContinuationCommand | None:
    if raw is None:
        return None
    if isinstance(raw, ContinuationCommand):
        return raw
    if not isinstance(raw, Mapping):
        raise SubmitCommandError("continuation must be an object")
    return ContinuationCommand(
        turn_id=_text(raw.get("turnId")),
        head_id=_text(raw.get("headId")),
        ledger_seq=raw.get("ledgerSeq") if isinstance(raw.get("ledgerSeq"), int) else 0,
        agent_id=_text(raw.get("agentId")),
    )


def _from_mapping(raw: Mapping[str, Any], ref) -> ChatSubmitCommand:
    return ChatSubmitCommand(
        content=_text(raw.get(ref["content"])),
        client_submission_id=_text(raw.get(ref["client_submission_id"])),
        attachment_ids=tuple(str(item) for item in _items(raw.get(ref["attachment_ids"])) if isinstance(item, str)),
        references=_items(raw.get(ref["references"])),
        continuation=_continuation(raw.get(ref["continuation"])),
    )


def from_platform_payload(payload: Any) -> ChatSubmitCommand:
    """把平台 ``SessionMessagePayload`` 归一化成规范命令。

    接受 pydantic 模型或普通映射；``clientSubmissionId`` 为空时由调用方补默认值，
    本函数不生成幂等键（生成策略属于入口职责）。
    """
    raw = payload if isinstance(payload, Mapping) else payload.model_dump()
    return _from_mapping(raw, CANONICAL_TO_PLATFORM)


def from_assistant_payload(payload: Any) -> ChatSubmitCommand:
    """把助理 ``Message`` 归一化成规范命令。"""
    raw = payload if isinstance(payload, Mapping) else payload.model_dump()
    return _from_mapping(raw, CANONICAL_TO_ASSISTANT)


def validate_submit_command(command: ChatSubmitCommand) -> None:
    """只校验两边**共有**且**等价**的约束。

    刻意不校验 ``content`` 长度上限和 ``attachmentIds`` 数量：平台入口从未限制
    这两项，在此加严会静默改变平台既有接受边界。各入口自己的 wire 模型继续
    负责其历史边界，规范层不越权收窄。
    """
    if len(command.client_submission_id) > MAX_CLIENT_SUBMISSION_ID:
        raise SubmitCommandError("client submission id is too long")
    continuation = command.continuation
    if continuation is not None:
        if not continuation.turn_id or len(continuation.turn_id) > MAX_CONTINUATION_TURN_ID:
            raise SubmitCommandError("continuation turnId is invalid")
        if not continuation.head_id or len(continuation.head_id) > MAX_CONTINUATION_HEAD_ID:
            raise SubmitCommandError("continuation headId is invalid")
        if not continuation.agent_id or len(continuation.agent_id) > MAX_CONTINUATION_AGENT_ID:
            raise SubmitCommandError("continuation agentId is invalid")
        if continuation.ledger_seq < 1:
            raise SubmitCommandError("continuation ledgerSeq is invalid")
