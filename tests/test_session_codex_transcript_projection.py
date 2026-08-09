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
