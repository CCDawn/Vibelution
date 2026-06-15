from core.web.services import cli_agent_protocols


def test_timeout_tail_uses_semantic_segments_not_character_slice():
    transcript = "\n\n".join(
        [
            "Thought: 准备上下文",
            "Status: 正在运行测试",
            "Answer: 第一段完整结论",
            "Error: 最后一段失败原因\nTraceback: config missing",
        ]
    )

    tail = cli_agent_protocols.tail_semantic_segments("mimo_code", transcript, limit=2)

    assert [item["kind"] for item in tail] == ["answer", "error"]
    assert tail[0]["text"] == "Answer: 第一段完整结论"
    assert "Traceback: config missing" in tail[1]["text"]


def test_claude_protocol_detects_permission_failures_without_char_tail():
    transcript = "\n\n".join(
        [
            "Thinking: checking workspace",
            "Error: permission denied while using Edit tool",
            "Answer: I could not complete the change.",
        ]
    )

    tail = cli_agent_protocols.tail_semantic_segments("claude_code", transcript, limit=2)

    assert cli_agent_protocols.detect_task_status("claude_code", transcript) == "failed"
    assert [item["kind"] for item in tail] == ["error", "answer"]
    assert "permission denied" in tail[0]["text"]
