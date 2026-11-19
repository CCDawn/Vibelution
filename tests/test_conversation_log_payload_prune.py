#!/usr/bin/env python3
"""ConversationLogger 会话清理必须同时回收孤儿 payload 目录。"""

from __future__ import annotations

import os
import time
from pathlib import Path

from core.logging.logger import PAYLOAD_PRUNE_GRACE_SECONDS, ConversationLogger


def _seed_payload(payload_root: Path, session_id: str, mtime: float) -> Path:
    session_dir = payload_root / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    payload_file = session_dir / "turn_1_tool_args.txt"
    payload_file.write_text("payload", encoding="utf-8")
    os.utime(payload_file, (mtime, mtime))
    os.utime(session_dir, (mtime, mtime))
    return session_dir


def _make_logger(tmp_path: Path, monkeypatch, session_id: str) -> ConversationLogger:
    logger = ConversationLogger()
    monkeypatch.setattr(logger, "_log_dir", str(tmp_path))
    monkeypatch.setattr(logger, "_session_id", session_id)
    monkeypatch.setattr(logger, "_file_logging_enabled", False)
    monkeypatch.setattr(logger, "_session_active", True)
    return logger


def test_cleanup_prunes_orphan_payload_dirs(tmp_path, monkeypatch):
    logger = _make_logger(tmp_path, monkeypatch, "live_session")
    payload_root = tmp_path / "payloads"
    payload_root.mkdir()

    stale = time.time() - PAYLOAD_PRUNE_GRACE_SECONDS - 7200
    for index, name in enumerate(("keep_one", "keep_two", "drop_one", "drop_two")):
        (tmp_path / f"conversation_{name}.jsonl").write_text("{}\n", encoding="utf-8")
        _seed_payload(payload_root, name, stale - index)

    # 当前进程会话的 payload 即使没有 jsonl 也不能删。
    _seed_payload(payload_root, "live_session", stale)
    # 宽限期内的目录可能属于并发进程，交给下一轮。
    fresh_dir = _seed_payload(payload_root, "fresh_orphan", time.time())

    now = time.time()
    os.utime(tmp_path / "conversation_keep_one.jsonl", (now - 10, now - 10))
    os.utime(tmp_path / "conversation_keep_two.jsonl", (now - 20, now - 20))
    os.utime(tmp_path / "conversation_drop_one.jsonl", (stale - 10, stale - 10))
    os.utime(tmp_path / "conversation_drop_two.jsonl", (stale - 11, stale - 11))

    logger.cleanup_old_conversations(keep_recent=2)

    remaining = sorted(child.name for child in payload_root.iterdir() if child.is_dir())
    assert remaining == ["fresh_orphan", "keep_one", "keep_two", "live_session"]
    assert fresh_dir.is_dir()


def test_cleanup_keeps_payload_when_jsonl_delete_fails(tmp_path, monkeypatch):
    logger = _make_logger(tmp_path, monkeypatch, "live_session")
    payload_root = tmp_path / "payloads"
    payload_root.mkdir()

    stale = time.time() - PAYLOAD_PRUNE_GRACE_SECONDS - 7200
    for index, name in enumerate(("keep_one", "keep_two", "stuck")):
        (tmp_path / f"conversation_{name}.jsonl").write_text("{}\n", encoding="utf-8")
        _seed_payload(payload_root, name, stale - index)

    now = time.time()
    os.utime(tmp_path / "conversation_keep_one.jsonl", (now - 10, now - 10))
    os.utime(tmp_path / "conversation_keep_two.jsonl", (now - 20, now - 20))
    os.utime(tmp_path / "conversation_stuck.jsonl", (now - 30, now - 30))

    original_remove = os.remove

    def remove_or_fail(path):
        if str(path).endswith("conversation_stuck.jsonl"):
            raise PermissionError("in use")
        return original_remove(path)

    monkeypatch.setattr(os, "remove", remove_or_fail)

    logger.cleanup_old_conversations(keep_recent=2)

    remaining = sorted(child.name for child in payload_root.iterdir() if child.is_dir())
    assert remaining == ["keep_one", "keep_two", "stuck"]


def test_cleanup_prune_counts_payloads(tmp_path, monkeypatch, caplog):
    logger = _make_logger(tmp_path, monkeypatch, "live_session")
    payload_root = tmp_path / "payloads"
    payload_root.mkdir()

    stale = time.time() - PAYLOAD_PRUNE_GRACE_SECONDS - 7200
    (tmp_path / "conversation_keep.jsonl").write_text("{}\n", encoding="utf-8")
    os.utime(tmp_path / "conversation_keep.jsonl", (time.time(), time.time()))
    _seed_payload(payload_root, "keep", stale)
    for index in range(3):
        _seed_payload(payload_root, f"orphan_{index}", stale - index)

    removed = logger._prune_orphan_payloads([str(tmp_path / "conversation_keep.jsonl")])

    assert removed == 3
    assert sorted(child.name for child in payload_root.iterdir() if child.is_dir()) == ["keep"]
