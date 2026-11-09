"""个人助理派遣回执的只读尾消息投影。"""

from __future__ import annotations

from core.web.services.session.projection import _pending_receipt_projection_messages


def test_projects_pending_receipt_body_as_read_only_message() -> None:
    rows = [
        {
            "messageId": "r-1",
            "content": "调研结论：量子纠错进展",
            "sourceAgentName": "研究员",
            "createdAt": "2026-11-09T00:00:00Z",
        }
    ]

    messages = _pending_receipt_projection_messages(rows)

    assert len(messages) == 1
    message = messages[0]
    assert message["id"] == "pending-receipt:r-1"
    assert message["role"] == "assistant"
    assert message["turnId"] == ""
    assert message["createdAt"] == "2026-11-09T00:00:00Z"
    assert message["content"] == "[Agent 私信·研究员·待处理] 调研结论：量子纠错进展"
    assert message["metadata"] == {
        "kind": "agent_inbox_message",
        "pendingReceipt": True,
        "messageId": "r-1",
        "summary": "调研结论：量子纠错进展",
        "sourceAgentId": "",
        "sourceAgentName": "研究员",
    }


def test_skips_rows_without_body_or_message_id() -> None:
    rows = [
        {"messageId": "r-1"},
        {"content": "只有正文没有编号"},
        "not-a-dict",
        {"messageId": "r-2", "summary": "摘要正文"},
    ]

    messages = _pending_receipt_projection_messages(rows)

    assert [message["metadata"]["messageId"] for message in messages] == ["r-2"]
    assert messages[0]["content"].endswith("摘要正文")


def test_caps_projection_count_and_body_length() -> None:
    rows = [{"messageId": f"r-{index}", "content": "x" * 1000} for index in range(8)]

    messages = _pending_receipt_projection_messages(rows)

    assert len(messages) == 5
    assert messages[0]["content"].endswith("…")
    assert len(messages[0]["content"]) < 1000


def test_ignores_non_list_input() -> None:
    assert _pending_receipt_projection_messages(None) == []
    assert _pending_receipt_projection_messages({"messageId": "r-1"}) == []
