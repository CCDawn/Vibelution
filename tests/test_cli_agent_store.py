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
