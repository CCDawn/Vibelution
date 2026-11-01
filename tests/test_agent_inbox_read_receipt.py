# -*- coding: utf-8 -*-
"""Inbox row read receipts: sent (createdAt) -> read (readAt) -> consumed (consumedAt).

``consumedAt`` is written optimistically at submit time, before the model has
actually read the message. ``readAt`` adds the missing middle state: the
session worker writes it right after context assembly survived the stop race.
Legacy rows without the field read as unread; consume semantics stay intact.
"""

from __future__ import annotations

import json
import itertools
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.web.services.agent_directory import ops_residual
from core.web.services.session import worker as session_worker
from core.web.services import session_service

AGENT_ID = "agent-target"
SESSION_ID = "session-live"
TURN_ID = "turn-inbox-read"


def _read_jsonl(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, payloads: list[dict]) -> None:
    lines = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in payloads]
    Path(path).write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")


@pytest.fixture
def inbox_env(tmp_path, monkeypatch):
    """Fake facade around a real jsonl file so read/rewrite round-trips are real."""

    (tmp_path / "ws" / "events").mkdir(parents=True)
    memory_events: list[dict] = []
    agent = {
        "agentId": AGENT_ID,
        "agentCode": "A002",
        "displayName": "Target",
        "directSessionId": SESSION_ID,
        "workspacePath": str(tmp_path / "ws"),
    }
    errors: dict[str, type[BaseException]] = {}
    clock = itertools.count()

    def advancing_now_iso() -> str:
        # Monotonic fake clock so createdAt < readAt < consumedAt is assertable.
        return f"2026-11-01T00:00:{next(clock):02d}+00:00"

    service = SimpleNamespace(
        get_agent=lambda agent_id, include_archived=False: (
            agent if agent_id == AGENT_ID else None
        ),
        AgentNotFoundError=ValueError,
        AgentMessageNotFoundError=ValueError,
        utc_now_iso=advancing_now_iso,
        _new_event_id=lambda prefix: f"{prefix}-fixed",
        trim_lines=lambda text, max_lines=4: str(text or "")[:200],
        _safe_metadata=lambda metadata: dict(metadata or {}),
        _agent_inbox_thread_id=lambda src, tgt: "thread-1",
        _agent_workspace_event_path=lambda target_agent, name: tmp_path / "ws" / "events" / name,
        _append_jsonl=lambda path, payload: _write_jsonl(path, [*_read_jsonl(path), payload]),
        _read_jsonl=lambda path: _read_jsonl(path),
        _write_jsonl=lambda path, payloads: _write_jsonl(path, payloads),
        _record_memory_event=lambda *args, **kwargs: memory_events.append(kwargs) or memory_events.append(args),
        _resolve_project_path=lambda p: tmp_path / "ws",
    )
    errors["service"] = service
    monkeypatch.setattr(ops_residual, "_service", lambda: service)
    return SimpleNamespace(
        tmp_path=tmp_path,
        agent=agent,
        service=service,
        memory_events=memory_events,
        path=tmp_path / "ws" / "events" / "agent_inbox_messages.jsonl",
    )


def _write_message(env, message_id: str, **overrides) -> dict:
    message = ops_residual.write_agent_inbox_message(
        AGENT_ID,
        content=f"任务简报 {message_id}",
        message_id=message_id,
        target_session_id=SESSION_ID,
        **overrides,
    )
    return message


def _rows(env) -> list[dict]:
    return _read_jsonl(env.path)


def test_new_inbox_rows_start_in_sent_state(inbox_env):
    message = _write_message(inbox_env, "msg-1")
    assert message["readAt"] == ""
    assert message["consumedAt"] == ""
    row = _rows(inbox_env)[0]
    assert row["createdAt"] and row["readAt"] == "" and row["consumedAt"] == ""


def test_mark_read_sets_read_at_without_touching_consume(inbox_env):
    _write_message(inbox_env, "msg-1")
    receipt = ops_residual.mark_agent_inbox_messages_read(
        AGENT_ID,
        ["msg-1"],
        read_by_session_id=SESSION_ID,
        read_by_turn_id=TURN_ID,
    )
    assert receipt["readCount"] == 1
    assert receipt["readMessageIds"] == ["msg-1"]
    row = _rows(inbox_env)[0]
    assert row["readAt"].startswith("2026-11-01T00:00:")
    assert row["status"] == "pending"
    assert row["consumedAt"] == ""
    assert inbox_env.memory_events


def test_mark_read_is_idempotent_and_scoped(inbox_env):
    _write_message(inbox_env, "msg-1")
    _write_message(inbox_env, "msg-2")
    first = ops_residual.mark_agent_inbox_messages_read(
        AGENT_ID, ["msg-1"], read_by_session_id=SESSION_ID, read_by_turn_id=TURN_ID
    )
    second = ops_residual.mark_agent_inbox_messages_read(
        AGENT_ID, ["msg-1"], read_by_session_id=SESSION_ID, read_by_turn_id=TURN_ID
    )
    assert first["readMessageIds"] == ["msg-1"]
    assert second["readCount"] == 0
    rows = {row["messageId"]: row for row in _rows(inbox_env)}
    assert rows["msg-1"]["readAt"] and rows["msg-2"]["readAt"] == ""


def test_mark_read_accepts_legacy_rows_without_read_at_field(inbox_env):
    _write_message(inbox_env, "msg-legacy")
    rows = _rows(inbox_env)
    for row in rows:
        row.pop("readAt", None)
    _write_jsonl(inbox_env.path, rows)
    receipt = ops_residual.mark_agent_inbox_messages_read(
        AGENT_ID, ["msg-legacy"], read_by_session_id=SESSION_ID, read_by_turn_id=TURN_ID
    )
    assert receipt["readMessageIds"] == ["msg-legacy"]
    assert _rows(inbox_env)[0]["readAt"].startswith("2026-11-01T00:00:")


def test_mark_read_without_ids_sweeps_consumed_by_session_and_turn(inbox_env):
    _write_message(inbox_env, "msg-own")
    rows = _rows(inbox_env)
    rows[0]["status"] = "consumed"
    rows[0]["consumedAt"] = "2026-10-31T09:00:00+00:00"
    rows[0]["consumedBySessionId"] = SESSION_ID
    rows[0]["consumedByTurnId"] = TURN_ID
    _write_jsonl(inbox_env.path, rows)
    _write_message(inbox_env, "msg-other")
    receipt = ops_residual.mark_agent_inbox_messages_read(
        AGENT_ID, None, read_by_session_id=SESSION_ID, read_by_turn_id=TURN_ID
    )
    assert receipt["readMessageIds"] == ["msg-own"]
    rows_by_id = {row["messageId"]: row for row in _rows(inbox_env)}
    assert rows_by_id["msg-own"]["readAt"]
    assert rows_by_id["msg-other"]["readAt"] == ""


def test_consume_preserves_read_at_three_state_ordering(inbox_env):
    _write_message(inbox_env, "msg-1")
    ops_residual.mark_agent_inbox_messages_read(
        AGENT_ID, ["msg-1"], read_by_session_id=SESSION_ID, read_by_turn_id=TURN_ID
    )
    consumed = ops_residual.consume_agent_inbox_message(
        AGENT_ID, "msg-1", consumed_by_session_id=SESSION_ID, consumed_by_turn_id=TURN_ID
    )
    assert consumed["status"] == "consumed"
    assert consumed["consumedAt"]
    row = _rows(inbox_env)[0]
    assert row["createdAt"] < row["readAt"] < row["consumedAt"]


def test_worker_writeback_helper_targets_inbox_rows_only(monkeypatch):
    calls: list[dict] = []

    def fake_mark(agent_id, message_ids=None, **kwargs):
        calls.append({"agentId": agent_id, "messageIds": message_ids, **kwargs})
        return {"readCount": 1}

    monkeypatch.setattr(ops_residual, "mark_agent_inbox_messages_read", fake_mark)

    inbox_context = {
        "agent_id": "agent-fallback",
        "message_metadata": {
            "kind": "agent_inbox_message",
            "messageId": "msg-42",
            "targetAgentId": AGENT_ID,
        },
    }
    session_worker._mark_agent_inbox_turn_messages_read(
        SESSION_ID, turn_id=TURN_ID, context=inbox_context
    )
    assert calls == [
        {
            "agentId": AGENT_ID,
            "messageIds": ["msg-42"],
            "read_by_session_id": SESSION_ID,
            "read_by_turn_id": TURN_ID,
        }
    ]

    calls.clear()
    session_worker._mark_agent_inbox_turn_messages_read(
        SESSION_ID,
        turn_id=TURN_ID,
        context={"agent_id": AGENT_ID, "message_metadata": {"kind": "internal_turn_trigger"}},
    )
    assert calls == []


def test_worker_writeback_failure_never_breaks_the_turn(monkeypatch):
    def failing_mark(*_args, **_kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(ops_residual, "mark_agent_inbox_messages_read", failing_mark)
    monkeypatch.setattr(session_service, "record_runtime_scene_event", lambda *a, **k: {})
    context = {
        "agent_id": AGENT_ID,
        "message_metadata": {"kind": "agent_inbox_message", "messageId": "msg-7"},
    }
    # Best-effort receipt: the failure must be swallowed, not raised.
    session_worker._mark_agent_inbox_turn_messages_read(SESSION_ID, turn_id=TURN_ID, context=context)


def test_worker_writeback_falls_back_to_context_agent(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(
        ops_residual,
        "mark_agent_inbox_messages_read",
        lambda agent_id, message_ids=None, **kwargs: calls.append(
            {"agentId": agent_id, "messageIds": message_ids, **kwargs}
        )
        or {"readCount": 0},
    )
    context = {
        "agent_id": "agent-from-context",
        "message_metadata": {"kind": "agent_inbox_message", "messageId": ""},
    }
    session_worker._mark_agent_inbox_turn_messages_read(SESSION_ID, turn_id=TURN_ID, context=context)
    assert calls[0]["agentId"] == "agent-from-context"
    assert calls[0]["messageIds"] is None
