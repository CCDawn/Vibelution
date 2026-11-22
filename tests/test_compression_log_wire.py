"""压缩诊断通道接线契约：JSONL 与 Markdown 都要能看到压缩结果。"""

from __future__ import annotations

import json
from pathlib import Path

from core.logging.logger import ConversationLogger
from core.logging.transcript_logger import TranscriptLogger

REPO_ROOT = Path(__file__).resolve().parents[1]


def _fresh_conversation_logger(tmp_path, monkeypatch) -> ConversationLogger:
    monkeypatch.setattr(ConversationLogger, "_instance", None)
    logger = ConversationLogger()
    monkeypatch.setattr(logger, "_log_dir", str(tmp_path))
    monkeypatch.setattr(logger, "_current_session_file", None)
    monkeypatch.setattr(logger, "_file_logging_enabled", True)
    monkeypatch.setattr(logger, "_session_active", True)
    monkeypatch.setattr(logger, "_session_id", "compression_wire_session")
    return logger


def test_conversation_logger_records_compression_details(tmp_path, monkeypatch):
    logger = _fresh_conversation_logger(tmp_path, monkeypatch)

    logger.log_compression(
        12_000,
        4_000,
        8_000,
        details={"level": "standard", "reason": "window", "effective": True},
    )

    session_file = Path(logger._get_session_file())
    records = [
        json.loads(line)
        for line in session_file.read_text(encoding="utf-8").splitlines()
    ]
    compression = [record for record in records if record["type"] == "compression"]

    assert len(compression) == 1
    record = compression[0]
    assert record["before_tokens"] == 12_000
    assert record["after_tokens"] == 4_000
    assert record["saved_tokens"] == 8_000
    assert record["details"]["level"] == "standard"
    assert record["details"]["reason"] == "window"
    assert record["details"]["effective"] is True


def test_conversation_logger_omits_details_when_absent(tmp_path, monkeypatch):
    logger = _fresh_conversation_logger(tmp_path, monkeypatch)

    logger.log_compression(100, 60, 40)

    session_file = Path(logger._get_session_file())
    record = json.loads(session_file.read_text(encoding="utf-8").splitlines()[-1])
    assert record["type"] == "compression"
    assert "details" not in record


def test_transcript_compression_renders_details(monkeypatch):
    captured: list[str] = []
    logger = TranscriptLogger.__new__(TranscriptLogger)
    monkeypatch.setattr(
        logger,
        "_enqueue_write",
        lambda content: captured.append(content) or 1,
    )

    logger.write_compression(
        12_000,
        4_000,
        8_000,
        details={"level": "standard", "reason": "window", "effective": True},
    )

    assert captured
    text = captured[-1]
    assert "上下文压缩" in text
    assert "standard" in text
    assert "是否生效: 是" in text
    assert "window" in text


def test_transcript_compression_stays_quiet_without_details(monkeypatch):
    captured: list[str] = []
    logger = TranscriptLogger.__new__(TranscriptLogger)
    monkeypatch.setattr(
        logger,
        "_enqueue_write",
        lambda content: captured.append(content) or 1,
    )

    logger.write_compression(100, 60, 40)

    assert captured
    text = captured[-1]
    assert "上下文压缩" in text
    assert "级别:" not in text
    assert "原因:" not in text


def test_compress_turn_messages_wires_diagnostic_log():
    source = (REPO_ROOT / "core" / "orchestration" / "turn_compression.py").read_text(
        encoding="utf-8"
    )
    body = source[source.index("def compress_turn_messages("):]

    assert "core.unified_logger" in body
    assert "log_compression(" in body
    assert "resolved_trigger_source" in body.split("log_compression(")[1][:600]
