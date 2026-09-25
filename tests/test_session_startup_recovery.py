"""Session startup recovery sweep (interrupted turns + queued-turn drain).

After a restart the in-memory running registry is empty and nobody re-triggers
the queue drain, so an open turn and queued rows would stay stuck forever.
These tests lock the sweep contract:

- an interrupted turn (open journal turn + still-active chat_turn work-run
  snapshot) is resubmitted once via the hot_restart_resume path, one
  ``session_recovery_resumed`` status line is journaled, and the interrupted
  partial gets the display-only ``recoverySuperseded`` marker;
- the operator switch, the retry budget and the idempotency key each gate the
  resume independently;
- queue rows schedule exactly one drain; Companion sessions are skipped.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core.chat.turn_journal import (
    EVENT_ASSISTANT_PARTIAL,
    EVENT_SESSION_RECOVERY_RESUMED,
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    append_turn_event,
    load_turn_events,
    model_visible_messages_from_events,
)
from core.infrastructure import developer_sandbox
from core.runtime_manager.work_run_store import WorkRunStore
from core.ui.chat_state import save_chat_state
from core.web.services import session_service
from core.web.services.session import startup_recovery

SESSION_ID = "session-a"
ORIGINAL_TURN_ID = "turn-1"
RESUMED_TURN_ID = "turn-resume-1"
ORIGINAL_PROMPT = "帮我重构导出脚本"


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)


@pytest.fixture(autouse=True)
def _reset_sweep_guards():
    startup_recovery._RESUMED_TURN_KEYS.clear()
    with startup_recovery._SWEEP_LOCK:
        startup_recovery._SWEEP_IN_FLIGHT = False
    yield
    startup_recovery._RESUMED_TURN_KEYS.clear()
    with startup_recovery._SWEEP_LOCK:
        startup_recovery._SWEEP_IN_FLIGHT = False


@pytest.fixture
def work_run_store(tmp_path, monkeypatch) -> WorkRunStore:
    store = WorkRunStore(root=tmp_path / "work-runs")
    monkeypatch.setattr(session_service, "_WORK_RUN_STORE", store)
    return store


@pytest.fixture
def recovery_env(tmp_path, monkeypatch, work_run_store):
    """Isolated session runtime: PROJECT_ROOT, idle registry, no companions."""
    monkeypatch.setattr(session_service, "PROJECT_ROOT", Path(tmp_path))
    monkeypatch.setattr(session_service, "_is_session_running", lambda session_id: False)
    monkeypatch.setattr(
        session_service,
        "_publish_session_detail_snapshot",
        lambda session_id, **_kwargs: None,
    )
    monkeypatch.setattr(
        session_service.agent_directory_service,
        "list_agents",
        lambda include_archived=False: [],
    )
    monkeypatch.setattr(
        startup_recovery, "is_session_recovery_enabled", lambda *args, **kwargs: True
    )
    monkeypatch.setattr(
        startup_recovery, "session_recovery_max_auto_retries", lambda *args, **kwargs: 2
    )
    return work_run_store


@pytest.fixture
def submit_calls(monkeypatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_submit(session_id, content, **kwargs):
        calls.append({"session_id": session_id, "content": content, **kwargs})
        return {
            "accepted": True,
            "sessionId": session_id,
            "turnId": RESUMED_TURN_ID,
            "startedTurnId": RESUMED_TURN_ID,
            "status": "running",
        }

    monkeypatch.setattr(session_service, "submit_session_message", fake_submit)
    return calls


@pytest.fixture
def drain_calls(monkeypatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(
        session_service,
        "_schedule_session_queued_turn_drain",
        lambda session_id: calls.append(str(session_id)),
    )
    return calls


def _seed_conversation(
    tmp_path,
    *,
    session_id: str = SESSION_ID,
    recovery_state: dict[str, Any] | None = None,
    queued_turns: list[dict[str, Any]] | None = None,
) -> None:
    conversation: dict[str, Any] = {
        "conversation_id": session_id,
        "title": "Startup recovery",
    }
    if recovery_state is not None:
        conversation[startup_recovery.RECOVERY_STATE_KEY] = recovery_state
    if queued_turns is not None:
        conversation["queued_turns"] = queued_turns
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": session_id,
            "conversations": [conversation],
        },
    )


def _seed_interrupted_turn(
    tmp_path,
    *,
    session_id: str = SESSION_ID,
    turn_id: str = ORIGINAL_TURN_ID,
    prompt: str = ORIGINAL_PROMPT,
    with_partial: bool = False,
) -> None:
    """An open (never-settled) turn: the crash-left-behind state the sweep owns."""

    append_turn_event(
        tmp_path,
        session_id,
        turn_id,
        EVENT_TURN_STARTED,
        status="running",
        payload={},
        source="submit",
    )
    append_turn_event(
        tmp_path,
        session_id,
        turn_id,
        EVENT_USER_MESSAGE,
        payload={"content": prompt, "metadata": {}},
        source="submit",
    )
    if with_partial:
        append_turn_event(
            tmp_path,
            session_id,
            turn_id,
            EVENT_ASSISTANT_PARTIAL,
            payload={"content": "half-streamed answer", "metadata": {}},
            source="capture",
        )


def _seed_active_work_run(work_run_store: WorkRunStore, turn_id: str = ORIGINAL_TURN_ID) -> None:
    work_run_store.persist_snapshot(
        "chat_turn",
        {
            "runId": turn_id,
            "runKind": "chat_turn",
            "status": "running",
            "sessionId": SESSION_ID,
            "finishedAt": "",
        },
        active_run_id=turn_id,
    )


def _recovery_events(tmp_path, session_id: str = SESSION_ID) -> list[Any]:
    return [
        event
        for event in load_turn_events(Path(tmp_path), session_id)
        if event.event_type == EVENT_SESSION_RECOVERY_RESUMED
    ]


def test_interrupted_turn_is_resubmitted_with_status_line(
    recovery_env, tmp_path, submit_calls, drain_calls
) -> None:
    _seed_conversation(tmp_path)
    _seed_interrupted_turn(tmp_path)
    _seed_active_work_run(recovery_env)

    summary = startup_recovery.recover_interrupted_session_turns_on_startup()

    assert summary["resumedCount"] == 1
    assert summary["errorCount"] == 0
    assert len(submit_calls) == 1
    call = submit_calls[0]
    assert call["session_id"] == SESSION_ID
    assert call["content"] == ORIGINAL_PROMPT
    assert call["turn_mode"] == "hot_restart_resume"
    assert call["write_intent"] is False
    assert call["message_source"] == "hot_restart_resume"
    assert call["client_submission_id"] == f"resume:{ORIGINAL_TURN_ID}"
    assert call["message_metadata"]["kind"] == "hot_restart_resume"
    assert call["message_metadata"]["recoveredTurnId"] == ORIGINAL_TURN_ID

    events = _recovery_events(tmp_path)
    assert len(events) == 1
    payload = events[0].payload["recovery"]
    assert payload["attempt"] == 1
    assert payload["recoveredTurnId"] == ORIGINAL_TURN_ID
    assert payload["resumedTurnId"] == RESUMED_TURN_ID
    assert payload["turnLabel"] == ORIGINAL_PROMPT

    conversation = session_service.load_session_chat_state(
        session_service.PROJECT_ROOT, SESSION_ID
    )
    state = conversation[startup_recovery.RECOVERY_STATE_KEY]
    assert state["attempts"] == 1
    assert state["originTurnId"] == ORIGINAL_TURN_ID
    assert state["resumedTurnId"] == RESUMED_TURN_ID


def test_recovery_status_line_projects_visible_assistant_message(
    recovery_env, tmp_path, submit_calls
) -> None:
    _seed_conversation(tmp_path)
    _seed_interrupted_turn(tmp_path)
    _seed_active_work_run(recovery_env)

    startup_recovery.recover_interrupted_session_turns_on_startup()

    messages = model_visible_messages_from_events(load_turn_events(Path(tmp_path), SESSION_ID))
    recovery_rows = [
        message
        for message in messages
        if message.get("metadata", {}).get("kind") == EVENT_SESSION_RECOVERY_RESUMED
    ]
    assert len(recovery_rows) == 1
    row = recovery_rows[0]
    assert row["role"] == "assistant"
    assert row["content"]
    assert row["metadata"]["attempt"] == 1
    assert row["metadata"]["turnLabel"] == ORIGINAL_PROMPT
    assert row["metadata"]["recoveredTurnId"] == ORIGINAL_TURN_ID


def test_interrupted_partial_gets_recovery_superseded_marker(
    recovery_env, tmp_path, submit_calls
) -> None:
    _seed_conversation(tmp_path)
    _seed_interrupted_turn(tmp_path, with_partial=True)
    _seed_active_work_run(recovery_env)

    startup_recovery.recover_interrupted_session_turns_on_startup()

    raw_items = model_visible_messages_from_events(
        load_turn_events(Path(tmp_path), SESSION_ID)
    )
    partials = [
        message
        for message in raw_items
        if message.get("metadata", {}).get("interrupted") is True
        and message.get("metadata", {}).get("kind") == "journal_assistant_partial"
    ]
    assert len(partials) == 1

    normalized = session_service._normalize_messages(SESSION_ID, raw_items)
    normalized_partials = [
        message
        for message in normalized
        if message.get("metadata", {}).get("interrupted") is True
    ]
    assert len(normalized_partials) == 1
    assert normalized_partials[0]["metadata"]["recoverySuperseded"] is True


def test_already_settled_turn_is_not_recovered(
    recovery_env, tmp_path, submit_calls
) -> None:
    """A turn with an interrupted marker is terminal; the sweep skips it."""

    _seed_conversation(tmp_path)
    _seed_interrupted_turn(tmp_path)
    _seed_active_work_run(recovery_env)
    append_turn_event(
        tmp_path,
        SESSION_ID,
        ORIGINAL_TURN_ID,
        "turn_interrupted",
        status="interrupted",
        payload={"reason": "process_restarted"},
        source="turn_journal_reconcile",
    )

    summary = startup_recovery.recover_interrupted_session_turns_on_startup()

    assert summary["resumedCount"] == 0
    assert submit_calls == []
    assert _recovery_events(tmp_path) == []


def test_disabled_switch_keeps_status_quo(recovery_env, tmp_path, submit_calls, monkeypatch) -> None:
    monkeypatch.setattr(
        startup_recovery, "is_session_recovery_enabled", lambda *args, **kwargs: False
    )
    _seed_conversation(tmp_path)
    _seed_interrupted_turn(tmp_path)
    _seed_active_work_run(recovery_env)

    summary = startup_recovery.recover_interrupted_session_turns_on_startup()

    assert summary["enabled"] is False
    assert submit_calls == []
    assert _recovery_events(tmp_path) == []


def test_retry_limit_skips_resume_and_keeps_interrupted(
    recovery_env, tmp_path, submit_calls
) -> None:
    _seed_conversation(
        tmp_path,
        recovery_state={
            "originTurnId": ORIGINAL_TURN_ID,
            "resumedTurnId": "",
            "attempts": 2,
            "updatedAt": "2026-09-25T00:00:00Z",
        },
    )
    _seed_interrupted_turn(tmp_path)
    _seed_active_work_run(recovery_env)

    summary = startup_recovery.recover_interrupted_session_turns_on_startup()

    assert summary["retryLimitSkipCount"] == 1
    assert summary["resumedCount"] == 0
    assert submit_calls == []
    assert _recovery_events(tmp_path) == []


def test_retry_budget_follows_resume_chain(
    recovery_env, tmp_path, submit_calls
) -> None:
    """A re-interrupted resumed turn keeps counting against the same budget."""

    _seed_conversation(
        tmp_path,
        recovery_state={
            "originTurnId": "turn-0",
            "resumedTurnId": ORIGINAL_TURN_ID,
            "attempts": 1,
            "updatedAt": "2026-09-25T00:00:00Z",
        },
    )
    _seed_interrupted_turn(tmp_path)
    _seed_active_work_run(recovery_env)

    summary = startup_recovery.recover_interrupted_session_turns_on_startup()

    assert summary["resumedCount"] == 1
    assert len(submit_calls) == 1
    conversation = session_service.load_session_chat_state(
        session_service.PROJECT_ROOT, SESSION_ID
    )
    state = conversation[startup_recovery.RECOVERY_STATE_KEY]
    assert state["attempts"] == 2
    assert state["originTurnId"] == "turn-0"


def test_idempotent_sweep_accepts_resume_once(
    recovery_env, tmp_path, submit_calls
) -> None:
    _seed_conversation(tmp_path)
    _seed_interrupted_turn(tmp_path)
    _seed_active_work_run(recovery_env)

    first = startup_recovery.recover_interrupted_session_turns_on_startup()
    second = startup_recovery.recover_interrupted_session_turns_on_startup()

    assert first["resumedCount"] == 1
    assert second.get("resumedCount", 0) == 0
    assert len(submit_calls) == 1
    assert len(_recovery_events(tmp_path)) == 1


def test_queued_session_schedules_drain(recovery_env, tmp_path, submit_calls, drain_calls) -> None:
    _seed_conversation(
        tmp_path,
        queued_turns=[
            {
                "id": "queued-1",
                "content": "排队消息",
                "status": "queued",
                "attachments": [],
                "references": [],
            }
        ],
    )

    summary = startup_recovery.recover_interrupted_session_turns_on_startup()

    assert drain_calls == [SESSION_ID]
    assert summary["queuedDrainScheduledCount"] == 1
    assert submit_calls == []


def test_companion_session_is_skipped(
    recovery_env, tmp_path, submit_calls, drain_calls, monkeypatch
) -> None:
    monkeypatch.setattr(
        session_service.agent_directory_service,
        "list_agents",
        lambda include_archived=False: [
            {
                "agentId": "agent-companion",
                "directSessionId": SESSION_ID,
                "metadata": {"virtualHumanCompanion": True},
            }
        ],
    )
    _seed_conversation(tmp_path)
    _seed_interrupted_turn(tmp_path)
    _seed_active_work_run(recovery_env)

    summary = startup_recovery.recover_interrupted_session_turns_on_startup()

    assert summary["companionSkipCount"] == 1
    assert summary["scannedSessionCount"] == 0
    assert submit_calls == []
    assert _recovery_events(tmp_path) == []


def test_companion_scoping_unavailable_fails_closed(
    recovery_env, tmp_path, submit_calls, monkeypatch
) -> None:
    def broken_list_agents(include_archived=False):
        raise RuntimeError("directory unavailable")

    monkeypatch.setattr(
        session_service.agent_directory_service,
        "list_agents",
        broken_list_agents,
    )
    _seed_conversation(tmp_path)
    _seed_interrupted_turn(tmp_path)
    _seed_active_work_run(recovery_env)

    summary = startup_recovery.recover_interrupted_session_turns_on_startup()

    assert summary.get("skipped") == "companion_scope_unavailable"
    assert submit_calls == []
    assert _recovery_events(tmp_path) == []


def test_healthy_session_is_a_noop(recovery_env, tmp_path, submit_calls, drain_calls) -> None:
    _seed_conversation(tmp_path)

    summary = startup_recovery.recover_interrupted_session_turns_on_startup()

    assert summary["scannedSessionCount"] == 1
    assert summary["resumedCount"] == 0
    assert summary["queuedDrainScheduledCount"] == 0
    assert submit_calls == []
    assert drain_calls == []


def test_finished_work_run_is_not_recovered(
    recovery_env, tmp_path, submit_calls
) -> None:
    """A settled work-run snapshot belongs to the runtime reconcile path."""

    _seed_conversation(tmp_path)
    _seed_interrupted_turn(tmp_path)
    recovery_env.persist_snapshot(
        "chat_turn",
        {
            "runId": ORIGINAL_TURN_ID,
            "runKind": "chat_turn",
            "status": "completed",
            "sessionId": SESSION_ID,
            "finishedAt": "2026-09-25T00:00:00Z",
        },
        active_run_id="",
    )

    summary = startup_recovery.recover_interrupted_session_turns_on_startup()

    assert summary["resumedCount"] == 0
    assert submit_calls == []
