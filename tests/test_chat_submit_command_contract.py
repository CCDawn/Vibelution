"""平台与助理两条提交链路的对称性守卫。

这两条链路的 wire 契约是**有意分开**的（平台 ``/sessions/{id}/messages``、
助理 ``/api/assistant/messages``），但语义必须一致。本测试锁定三件事：

1. 规范映射表两侧覆盖同一批语义字段；
2. 映射到的 wire 字段在各自 pydantic 模型里真实存在（改名即红）；
3. 两条入口对等价输入归一化出同一个规范命令。

失败时不要放宽断言——先确认是无意漂移还是有意分叉，再决定改哪边。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.chat.submit_command_contract import (
    CANONICAL_TO_ASSISTANT,
    CANONICAL_TO_PLATFORM,
    ContinuationCommand,
    SubmitCommandError,
    from_assistant_payload,
    from_platform_payload,
    validate_submit_command,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_mapping_tables_cover_the_same_canonical_fields():
    assert set(CANONICAL_TO_PLATFORM) == set(CANONICAL_TO_ASSISTANT)


def test_platform_wire_fields_still_exist():
    from core.web.routes.sessions import SessionMessagePayload

    fields = set(SessionMessagePayload.model_fields)
    missing = sorted(
        f"{canonical} -> {wire}"
        for canonical, wire in CANONICAL_TO_PLATFORM.items()
        if wire not in fields
    )
    assert not missing, f"平台 SessionMessagePayload 缺少映射字段: {missing}"


def test_assistant_wire_fields_still_exist():
    from core.assistant_runtime.host import Message

    fields = set(Message.model_fields)
    missing = sorted(
        f"{canonical} -> {wire}"
        for canonical, wire in CANONICAL_TO_ASSISTANT.items()
        if wire not in fields
    )
    assert not missing, f"助理 Message 缺少映射字段: {missing}"


def test_both_entries_normalize_to_the_same_command():
    platform = from_platform_payload({
        "content": "hello",
        "clientSubmissionId": "req-1",
        "attachmentIds": ["art-1"],
        "references": [{"kind": "file"}],
        "continuation": {"turnId": "t1", "headId": "h1", "ledgerSeq": 3, "agentId": "a1"},
    })
    assistant = from_assistant_payload({
        "message": "hello",
        "requestId": "req-1",
        "attachmentIds": ["art-1"],
        "references": [{"kind": "file"}],
        "controlContinuation": {"agentId": "a1", "sessionId": "s1", "turnId": "t1", "headId": "h1", "ledgerSeq": 3},
    })
    assert platform.content == assistant.content == "hello"
    assert platform.client_submission_id == assistant.client_submission_id == "req-1"
    assert platform.attachment_ids == assistant.attachment_ids == ("art-1",)
    assert platform.continuation == assistant.continuation


def test_continuation_is_optional_on_both_entries():
    assert from_platform_payload({"content": "x"}).continuation is None
    assert from_assistant_payload({"message": "x"}).continuation is None


def test_validate_rejects_oversized_submission_id():
    command = from_platform_payload({"content": "x", "clientSubmissionId": "a" * 129})
    with pytest.raises(SubmitCommandError):
        validate_submit_command(command)


def test_validate_accepts_empty_submission_id_for_platform_default():
    # 平台会在 handler 里补默认幂等键，规范层不替它生成。
    validate_submit_command(from_platform_payload({"content": "x"}))


def test_validate_rejects_incomplete_continuation():
    command = from_platform_payload({
        "content": "x",
        "continuation": {"turnId": "", "headId": "h1", "ledgerSeq": 1, "agentId": "a1"},
    })
    with pytest.raises(SubmitCommandError):
        validate_submit_command(command)


def test_validate_rejects_non_positive_ledger_seq():
    command = from_platform_payload({
        "content": "x",
        "continuation": {"turnId": "t1", "headId": "h1", "ledgerSeq": 0, "agentId": "a1"},
    })
    with pytest.raises(SubmitCommandError):
        validate_submit_command(command)


def test_validate_accepts_well_formed_continuation():
    command = from_platform_payload({
        "content": "x",
        "continuation": {"turnId": "t1", "headId": "h1", "ledgerSeq": 1, "agentId": "a1"},
    })
    validate_submit_command(command)
    assert command.continuation == ContinuationCommand(turn_id="t1", head_id="h1", ledger_seq=1, agent_id="a1")


def _routes(source: str, pattern: str) -> set[tuple[str, str]]:
    return {(method.upper(), path) for method, path in re.findall(pattern, source)}


def test_dialog_route_pairs_exist_on_both_sides():
    """对话语义子集必须两边都在；缺一边说明有人在单侧加了能力。"""
    platform_source = (_REPO_ROOT / "core/web/routes/sessions.py").read_text(encoding="utf-8")
    assistant_source = (_REPO_ROOT / "core/assistant_runtime/host.py").read_text(encoding="utf-8")
    platform = _routes(platform_source, r'@router\.(get|post|patch|delete|put)\(\s*"/sessions/\{session_id\}/([a-z\-/{}a-z]+)"')
    assistant = _routes(assistant_source, r'@app\.(get|post|patch|delete|put)\("(/api/assistant/[a-z\-/]+)"')

    # 平台路径已带 {session_id} 前缀，助理是固定单会话；按尾段语义配对。
    platform_tails = {path.rsplit("/", 1)[-1] for _, path in platform}
    assistant_tails = {path.rsplit("/", 1)[-1] for _, path in assistant}

    for tail in ("messages", "stop", "head", "regenerate", "guidance", "events"):
        assert tail in platform_tails, f"平台侧缺少对话语义路由: {tail}"
        assert tail in assistant_tails, f"助理侧缺少对话语义路由: {tail}"
