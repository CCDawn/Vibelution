import json

from tools import conversation_log_tools


def _write_jsonl(path, rows):
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_conversation_log_inspect_summarizes_tokens_tools_and_inefficiencies(tmp_path, monkeypatch):
    monkeypatch.setattr(conversation_log_tools, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(conversation_log_tools, "LOG_INFO_DIR", tmp_path / "log_info")
    log_dir = tmp_path / "log_info"
    log_dir.mkdir()
    log_path = log_dir / "conversation_20260604_120000__chat__demo.jsonl"
    _write_jsonl(
        log_path,
        [
            {
                "type": "session_start",
                "session_id": "20260604_120000",
                "session_label": "chat__demo",
                "metadata": {"agent_mode": "chat", "model": "gpt-test", "tools_count": 9},
            },
            {"type": "llm_response", "input_tokens": 60000, "output_tokens": 800},
            {
                "type": "tool_call",
                "turn": 1,
                "tool_name": "read_file_tool",
                "tool_args": {"file_path": "log_info/demo.jsonl", "max_lines": 0},
                "status": "success",
                "tool_result_length": 12000,
            },
            {
                "type": "tool_call",
                "turn": 1,
                "tool_name": "read_file_tool",
                "tool_args": {"file_path": "log_info/demo.jsonl", "max_lines": 0},
                "status": "success",
                "tool_result_length": 12000,
            },
            {"type": "llm_error", "status": "failed", "message": "429 rate limit"},
            {"type": "session_end", "ok": True},
        ],
    )

    result = conversation_log_tools.inspect_conversation_logs(log_path=str(log_path))
    inspection = result["inspections"][0]

    assert result["status"] == "ok"
    assert inspection["path"] == "log_info/conversation_20260604_120000__chat__demo.jsonl"
    assert inspection["tokenUsage"]["inputTokens"] == 60000
    assert inspection["toolCalls"]["byTool"]["read_file_tool"] == 2
    assert inspection["toolCalls"]["repeated"]
    assert {item["code"] for item in inspection["inefficiencies"]}.issuperset(
        {"repeated_tool_call", "large_tool_result", "token_imbalance", "error_status_check_needed"}
    )
    assert inspection["errors"][0]["preview"] == "429 rate limit"


def test_conversation_log_inspect_query_selects_matching_recent_log(tmp_path, monkeypatch):
    monkeypatch.setattr(conversation_log_tools, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(conversation_log_tools, "LOG_INFO_DIR", tmp_path / "log_info")
    log_dir = tmp_path / "log_info"
    log_dir.mkdir()
    first = log_dir / "conversation_20260604_120000__chat__alpha.jsonl"
    second = log_dir / "conversation_20260604_120100__chat__beta.jsonl"
    _write_jsonl(first, [{"type": "session_start", "metadata": {"conversation_topic": "alpha"}}])
    _write_jsonl(second, [{"type": "session_start", "metadata": {"conversation_topic": "程听澜"}}])

    result = conversation_log_tools.inspect_conversation_logs(query="程听澜", limit=1)

    assert result["candidateCount"] == 1
    assert result["candidates"][0]["path"] == "log_info/conversation_20260604_120100__chat__beta.jsonl"


def test_conversation_log_inspect_rejects_non_log_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(conversation_log_tools, "PROJECT_ROOT", tmp_path)
    target = tmp_path / "secret.jsonl"
    target.write_text("{}", encoding="utf-8")

    payload = conversation_log_tools.conversation_log_inspect_tool(log_path=str(target))

    assert "only reads log_info/" in payload
