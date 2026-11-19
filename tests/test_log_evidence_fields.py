"""日志证据字段回归：耗时、模型快照、配对序号、堆栈兜底、会话自检摘要。"""

from __future__ import annotations

import json

from core.logging.logger import ConversationLogger


def _isolated_logger(tmp_path, monkeypatch, session_id: str = "evidence_session"):
    ConversationLogger._instance = None
    logger = ConversationLogger()
    monkeypatch.setattr(logger, "_log_dir", str(tmp_path))
    monkeypatch.setattr(logger, "_session_id", session_id)
    monkeypatch.setattr(logger, "_session_file_stem", f"conversation_{session_id}")
    monkeypatch.setattr(logger, "_file_logging_enabled", True)
    monkeypatch.setattr(logger, "_session_active", True)
    monkeypatch.setattr(logger, "_current_session_file", None)
    logger._ensure_log_dir()
    return logger


def _records(tmp_path, session_id: str = "evidence_session") -> list[dict]:
    path = tmp_path / f"conversation_{session_id}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _record_of_type(records: list[dict], record_type: str) -> dict:
    return next(item for item in records if item["type"] == record_type)


def test_llm_response_carries_duration_model_and_pairing(tmp_path, monkeypatch):
    logger = _isolated_logger(tmp_path, monkeypatch)

    logger.log_llm_request([{"role": "user", "content": "hi"}], model="deepseek-v4", iteration=2)
    logger.log_llm_response("done", input_tokens=11, output_tokens=22, tool_call_count=0)

    records = _records(tmp_path)
    response = _record_of_type(records, "llm_response")

    assert response["model"] == "deepseek-v4"
    assert response["llm_seq"] == 1
    assert isinstance(response["duration_ms"], float)
    assert response["duration_ms"] >= 0.0


def test_llm_response_duration_is_null_without_request_anchor(tmp_path, monkeypatch):
    logger = _isolated_logger(tmp_path, monkeypatch)

    logger.log_llm_response("orphan response")

    response = _record_of_type(_records(tmp_path), "llm_response")

    assert response["duration_ms"] is None
    assert response["llm_seq"] is None


def test_tool_call_records_explicit_duration(tmp_path, monkeypatch):
    logger = _isolated_logger(tmp_path, monkeypatch)

    logger.log_tool_call("grep_search_tool", {"pattern": "x"}, "hit", duration_ms=12.5)
    logger.log_tool_call("noop", {}, None)

    records = [item for item in _records(tmp_path) if item["type"] == "tool_call"]

    assert records[0]["duration_ms"] == 12.5
    assert records[1]["duration_ms"] is None


def test_log_error_fills_traceback_from_active_exception(tmp_path, monkeypatch):
    logger = _isolated_logger(tmp_path, monkeypatch)

    try:
        raise ValueError("boom-evidence")
    except ValueError:
        logger.log_error("ValueError", "boom-evidence")

    error = _record_of_type(_records(tmp_path), "error")

    assert "ValueError: boom-evidence" in (error["traceback"] or "")


def test_log_error_keeps_explicit_traceback_when_supplied(tmp_path, monkeypatch):
    logger = _isolated_logger(tmp_path, monkeypatch)

    logger.log_error("TimeoutError", "slow", traceback="stack-from-caller")

    error = _record_of_type(_records(tmp_path), "error")

    assert error["traceback"] == "stack-from-caller"


def test_end_session_writes_self_check_summary(tmp_path, monkeypatch):
    logger = _isolated_logger(tmp_path, monkeypatch)

    logger.log_debug("note", "hello", "INFO")
    logger.end_session({"ok": True})

    records = _records(tmp_path)
    summary = records[-1]

    assert summary["type"] == "session_summary"
    assert summary["record_count"] >= 2
    assert summary["record_counts"].get("debug") == 1
    assert summary["record_counts"].get("session_end") == 1
    assert summary["write_failures"] == 0
    assert summary["payload_failures"] == 0
