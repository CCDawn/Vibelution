from __future__ import annotations

from core.web.services import session_service


def _assistant_visible_text(message: dict) -> str:
    return "\n".join(
        str(item.get("text") or "").strip()
        for item in list(message.get("turnItems") or [])
        if str(item.get("type") or "") in {"agent_message", "error"}
        if str(item.get("text") or "").strip()
    )


def test_normalize_messages_collapses_tool_result_air_bubbles_when_answer_exists():
    items = [
        {"role": "user", "content": "继续", "timestamp": "t0"},
        {
            "role": "assistant",
            "content": "",
            "timestamp": "t1",
            "toolCalls": [
                {"name": "cli_tool", "id": "c1", "status": "done", "summary": "ok"},
            ],
            "metadata": {"kind": "tool_result", "turnId": "turn-a"},
        },
        {
            "role": "assistant",
            "content": "",
            "timestamp": "t2",
            "toolCalls": [
                {"name": "get_git_status_summary_tool", "id": "c2", "status": "done", "summary": "clean"},
            ],
            "metadata": {"kind": "tool_result", "turnId": "turn-a"},
        },
        {
            "role": "assistant",
            "content": "最终回答正文",
            "timestamp": "t3",
            "metadata": {"kind": "journal_assistant_message", "turnId": "turn-a"},
        },
    ]

    messages = session_service._normalize_messages("session-air", items, include_timeline=False)

    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "继续"
    assert _assistant_visible_text(messages[1]) == "最终回答正文"
    assert not messages[1].get("toolCalls")


def test_normalize_messages_keeps_one_process_host_while_tools_are_running():
    items = [
        {"role": "user", "content": "继续", "timestamp": "t0"},
        {
            "role": "assistant",
            "content": "",
            "timestamp": "t1",
            "toolCalls": [
                {"name": "cli_tool", "id": "c1", "status": "done", "summary": "ok"},
            ],
            "metadata": {"kind": "tool_result", "turnId": "turn-b"},
        },
        {
            "role": "assistant",
            "content": "",
            "timestamp": "t2",
            "toolCalls": [
                {"name": "task_list_tool", "id": "c2", "status": "running", "summary": "listing"},
            ],
            "metadata": {"kind": "tool_result", "turnId": "turn-b"},
        },
    ]

    messages = session_service._normalize_messages("session-air-live", items, include_timeline=False)

    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert _assistant_visible_text(messages[1]) == ""
    tool_items = [
        item
        for item in list(messages[1].get("turnItems") or [])
        if str(item.get("type") or "") == "tool_call"
    ]
    assert tool_items
    assert tool_items[0]["toolName"] == "cli_tool"
