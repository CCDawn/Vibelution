import json

from core.web.services import session_service


def test_assistant_session_projection_has_only_a_revisioned_turn_item_package():
    messages = session_service._normalize_messages(
        "session-codex",
        [
            {
                "role": "assistant",
                "content": "已经完成检查。",
                "timestamp": "2026-08-09T05:00:00Z",
                "feedback_events": [
                    {
                        "sequence": 1,
                        "kind": "tool",
                        "status": "done",
                        "name": "git_status",
                        "summary": "工作区干净",
                        "resultPreview": "clean",
                    }
                ],
            }
        ],
    )

    assistant = messages[0]

    assert assistant["role"] == "assistant"
    assert assistant["status"] == "completed"
    assert "content" not in assistant
    assert "thought" not in assistant
    assert "timelineItems" not in assistant
    assert "feedbackEvents" not in assistant
    assert "codexTranscript" not in assistant
    assert [item["type"] for item in assistant["turnItems"]] == ["tool_call", "agent_message"]
    assert all(item["version"] == 3 for item in assistant["turnItems"])
    assert assistant["turnItems"][-1]["text"] == "已经完成检查。"


def test_live_tool_revision_survives_the_codex_projection() -> None:
    messages = session_service._normalize_messages(
        "session-live",
        [{
            "role": "assistant",
            "timestamp": "2026-08-10T00:00:00Z",
            "streaming": True,
            "feedback_events": [{
                "sequence": 4,
                "revision": 2,
                "kind": "tool",
                "status": "completed",
                "name": "grep_search_tool",
                "callId": "call-live",
                "summary": "found",
                "createdAt": "2026-08-10T00:00:01Z",
                "updatedAt": "2026-08-10T00:00:02Z",
            }],
        }],
    )

    tool_item = next(item for item in messages[0]["turnItems"] if item["type"] == "tool_call")
    assert tool_item["callId"] == "call-live"
    assert tool_item["revision"] == 2
    assert tool_item["createdAt"] == "2026-08-10T00:00:01Z"
    assert tool_item["updatedAt"] == "2026-08-10T00:00:02Z"


def test_tool_turn_item_carries_canonical_arguments_for_patch_diff():
    patch_text = "\n".join([
        "*** Begin Patch",
        "*** Update File: demo.py",
        "@@",
        "-value = 1",
        "+value = 2",
        "*** End Patch",
    ])

    messages = session_service._normalize_messages(
        "session-patch",
        [{
            "role": "assistant",
            "timestamp": "2026-08-10T00:00:00Z",
            "streaming": True,
            "feedback_events": [{
                "sequence": 1,
                "kind": "tool",
                "status": "running",
                "name": "apply_patch_tool",
                "callId": "call-patch",
                "summary": "editing",
                "arguments": {"patch_text": patch_text},
            }],
        }],
    )

    tool_item = next(item for item in messages[0]["turnItems"] if item["type"] == "tool_call")
    assert json.loads(tool_item["input"])["patch_text"] == patch_text


def test_turn_item_protocol_normalizes_legacy_internal_kinds_without_serializing_aliases():
    items = session_service._canonicalize_session_turn_items_for_protocol(
        [
            {
                "id": "legacy-answer",
                "type": "assistant_message",
                "kind": "assistant_message",
                "channel": "answer",
                "phase": "final_answer",
                "status": "in_progress",
                "text": "正在输出",
            },
            {
                "id": "legacy-retry",
                "type": "model_retry",
                "kind": "model_retry",
                "status": "in_progress",
                "summary": "模型连接正在重试",
                "iteration": 2,
            },
        ],
        session_id="session-1",
        turn_id="turn-1",
    )

    assert [item["type"] for item in items] == ["retry", "agent_message"]
    assert [item["status"] for item in items] == ["running", "running"]
    assert items[1]["phase"] == "final_answer"
    assert items[0]["attempt"] == 2
    for item in items:
        assert "kind" not in item
        assert "channel" not in item
        assert "protocol" not in item
        assert "provisional" not in item


def test_terminal_error_is_a_failed_turn_item_instead_of_a_second_error_message_surface():
    messages = session_service._normalize_messages(
        "session-error",
        [
            {
                "role": "assistant",
                "content": "模型调用失败",
                "metadata": {"kind": "turn_error", "providerFailure": True},
            }
        ],
    )

    assistant = messages[0]

    assert assistant["status"] == "failed"
    assert assistant["turnItems"][0]["type"] == "error"
    assert assistant["turnItems"][0]["status"] == "failed"
    assert "content" not in assistant


def test_window_slim_keeps_tool_result_text_visible_beyond_header_lines():
    # window 投影曾把工具文本截到 400 字符：grep 输出头部（正则/目录/计数行）
    # 就会吃光预算，匹配内容在聊天 UI 完全不可见。工具文本放宽到 4000。
    from core.web.services.session.projection import _slim_session_turn_items_for_window_payload

    header = "[搜索] 正则: ttft\n[搜索] 目录: C:\repo\n[搜索] 类型: .py\n[搜索] 找到 3 个匹配\n"
    matches = "\n".join(f"core/web/file{i}.py:{i * 10}: TTFT_FIRST_CHUNK_MS = {i}" for i in range(60))
    tool_text = header + matches

    slimmed = _slim_session_turn_items_for_window_payload(
        [
            {"type": "tool_call", "status": "completed", "text": tool_text},
            {"type": "reasoning", "status": "completed", "text": "x" * 900},
            {"type": "agent_message", "status": "completed", "text": "final answer"},
        ]
    )

    by_type = {item["type"]: item for item in slimmed}
    tool_item = by_type["tool_call"]
    # 头部行完整保留，且大部分匹配行随 4000 上限保留下来。
    assert tool_item["text"].startswith(header)
    assert "TTFT_FIRST_CHUNK_MS" in tool_item["text"]
    assert len(tool_item["text"]) <= 4001
    # 非工具类目维持原 400 上限。
    assert len(by_type["reasoning"]["text"]) <= 401
    # 最终答案文本不受影响。
    assert by_type["agent_message"]["text"] == "final answer"
