# -*- coding: utf-8 -*-
"""PA-dispatch self-heal lane contract tests.

A session woken by a PA dispatch envelope and stalled into
``needs_continue``/``paused_limit`` must continue exactly once per unit of
budget through ``request_managed_continuation``; revoked/unharvested
envelopes, plain inbox sessions, and patrol follow-up rows must never
continue; the budget (2 per envelope) and the two-consecutive-no-progress
permanent stop must hold and persist.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from core.chat.conversation_ledger import append_conversation_event
from core.chat.turn_journal import EVENT_USER_MESSAGE
from core.infrastructure import developer_sandbox
from core.ui.chat_state import load_session_chat_state, save_chat_state
from core.web.services import agent_directory_service as directory
from core.web.services import personal_assistant_dispatch_ledger as ledger
from core.web.services import personal_assistant_service as pa_service
from core.web.services import session_service
from core.web.services.session import managed_continuation, schedule, worker
from tests.test_financial_knowledge_service import finance_env as _finance_env
from tests.test_personal_assistant_service import personal_env as _personal_env

finance_env = _finance_env
personal_env = _personal_env

PA_ID = "assistant-agent"
TARGET_ID = "target-agent"
SESSION_ID = "session-dispatched"


@pytest.fixture(autouse=True)
def _reset_ledger_memo():
    ledger.reset_identity_memo()
    yield
    ledger.reset_identity_memo()


@pytest.fixture(autouse=True)
def _isolated_developer_mode(monkeypatch):
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)


# ---------------------------------------------------------------------------
# Seeding helpers (shapes copied from the ledger/patrol test corpus)
# ---------------------------------------------------------------------------


def _agent_row(agent_id: str, *, is_assistant: bool = False) -> dict:
    row = {
        "agentId": agent_id,
        "displayName": agent_id,
        "status": "active",
        "workspacePath": f"workspace/agents/{agent_id}",
        "metadata": {},
    }
    if is_assistant:
        row["roleKey"] = pa_service.ROLE
        row["primaryMode"] = "general"
        row["metadata"] = {"personalAssistantProfile": pa_service.PROFILE}
    return row


def _seed_agents(personal_env, rows) -> None:
    state = directory.load_state()
    state["agents"] = rows
    directory.save_state(state)


def _inbox_path(personal_env, agent_id: str) -> Path:
    return (
        personal_env["root"]
        / "workspace"
        / "agents"
        / agent_id
        / "events"
        / "agent_inbox_messages.jsonl"
    )


def _write_inbox(personal_env, agent_id: str, rows) -> None:
    inbox = _inbox_path(personal_env, agent_id)
    inbox.parent.mkdir(parents=True, exist_ok=True)
    with open(inbox, "w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _dispatch_row(message_id: str, *, status: str = "pending") -> dict:
    return {
        "eventId": f"event-{message_id}",
        "messageId": message_id,
        "threadId": f"thread-{message_id}",
        "kind": "agent_message",
        "status": status,
        "sourceAgentId": PA_ID,
        "sourceAgentName": "个人助理",
        "targetAgentId": TARGET_ID,
        "targetAgentName": TARGET_ID,
        "targetSessionId": SESSION_ID,
        "summary": "dispatch summary",
        "createdAt": "2026-11-01T10:00:00+00:00",
        "metadata": {"sourceSessionId": "pa-session"},
    }


def _envelope_metadata(
    message_id: str = "dispatch-1",
    *,
    inbox_kind: str = "agent_direct_message",
    source_agent_id: str = PA_ID,
) -> dict[str, Any]:
    return {
        "kind": "agent_inbox_message",
        "messageId": message_id,
        "inboxKind": inbox_kind,
        "threadId": f"thread-{message_id}",
        "sourceAgentId": source_agent_id,
        "sourceAgentName": "个人助理",
        "sourceSessionId": "pa-session",
        "targetAgentId": TARGET_ID,
        "targetAgentName": TARGET_ID,
        "targetSessionId": SESSION_ID,
    }


def _seed_conversation(tmp_path, **overrides: Any) -> None:
    persisted = load_session_chat_state(tmp_path, SESSION_ID)
    if isinstance(persisted, dict) and persisted.get("conversation_id") == SESSION_ID:
        conversation = persisted
    else:
        conversation = {
            "conversation_id": SESSION_ID,
            "title": "Dispatched session",
            "agent_id": TARGET_ID,
            "last_turn_status": "needs_continue",
            "last_turn_terminal_turn_id": "turn-resting",
        }
    conversation.update(overrides)
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": SESSION_ID,
            "conversations": [conversation],
        },
    )


def _append_driver_event(
    tmp_path,
    message_id: str,
    *,
    turn_id: str = "turn-dispatch",
    metadata: dict[str, Any] | None = None,
    source: str = "agent_inbox",
    content: str = "派遣任务",
) -> None:
    append_conversation_event(
        tmp_path,
        SESSION_ID,
        turn_id,
        EVENT_USER_MESSAGE,
        payload={
            "content": content,
            "source": source,
            "metadata": metadata
            if metadata is not None
            else _envelope_metadata(message_id),
        },
        source="submit_session_message",
        correlation_id=f"sub-{turn_id}",
    )


def _append_managed_driver_event(tmp_path, *, turn_id: str = "turn-managed") -> None:
    append_conversation_event(
        tmp_path,
        SESSION_ID,
        turn_id,
        EVENT_USER_MESSAGE,
        payload={
            "content": managed_continuation.MANAGED_CONTINUATION_PROMPT,
            "source": "managed_continuation",
            "metadata": {
                "kind": "managed_continuation",
                "source": managed_continuation.PA_DISPATCH_SELF_HEAL_SOURCE,
            },
        },
        source="submit_session_message",
        correlation_id=f"sub-{turn_id}",
    )


def _capture_managed_submit(monkeypatch) -> list[dict]:
    captured: list[dict] = []

    def fake_submit(_session_id, content, **kwargs):
        captured.append({"content": content, **kwargs})
        return {"startedTurnId": f"turn-managed-{len(captured)}", "accepted": True}

    monkeypatch.setattr(session_service, "submit_session_message", fake_submit)
    return captured


def _capture_lifecycle(monkeypatch) -> list[dict]:
    captured: list[dict] = []

    def fake_record(session_id, phase, **kwargs):
        captured.append({"sessionId": session_id, "phase": phase, **kwargs})

    monkeypatch.setattr(
        session_service, "_record_session_turn_lifecycle_event", fake_record
    )
    return captured


def _self_heal_state(tmp_path) -> dict[str, Any]:
    state = load_session_chat_state(tmp_path, SESSION_ID).get(
        managed_continuation.PA_DISPATCH_SELF_HEAL_STATE_KEY
    )
    return state if isinstance(state, dict) else {}


def _seed_pa_dispatch_chain(personal_env, monkeypatch, *, message_id: str = "dispatch-1", status: str = "pending"):
    """Common env: PA identity, current dispatch envelope, resting session."""

    tmp_path = personal_env["root"]
    _seed_agents(
        personal_env,
        [_agent_row(PA_ID, is_assistant=True), _agent_row(TARGET_ID)],
    )
    _write_inbox(personal_env, TARGET_ID, [_dispatch_row(message_id, status=status)])
    assert ledger.ensure_harvested(PA_ID) is True
    monkeypatch.setattr(session_service, "_is_session_running", lambda sid: False)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_conversation(tmp_path)
    _append_driver_event(tmp_path, message_id)
    return tmp_path


# ---------------------------------------------------------------------------
# ① stalled dispatched session → exactly one machine continuation, gate closed
# ---------------------------------------------------------------------------


def test_stalled_dispatched_session_self_heals_once_with_progress(
    personal_env, monkeypatch
):
    tmp_path = _seed_pa_dispatch_chain(personal_env, monkeypatch)
    submitted = _capture_managed_submit(monkeypatch)

    receipt = managed_continuation.maybe_self_heal_pa_dispatched_session_after_release(
        SESSION_ID
    )
    assert receipt["accepted"] is True
    assert receipt["source"] == managed_continuation.PA_DISPATCH_SELF_HEAL_SOURCE
    assert receipt["managedContinuationCount"] == 1
    assert len(submitted) == 1
    call = submitted[0]
    assert call["message_source"] == "managed_continuation"
    assert call["message_metadata"]["kind"] == "managed_continuation"
    assert call["message_metadata"]["source"] == "pa_dispatch_self_heal"
    assert call["write_intent"] is False
    # Closed loop: the submitted shape is exactly what the worker's
    # internal-auto-continue gate authorizes.
    assert (
        worker._session_context_allows_internal_auto_continue(
            {
                "user_message_source": call["message_source"],
                "message_metadata": call["message_metadata"],
            }
        )
        is True
    )
    state = _self_heal_state(tmp_path)
    assert state["count"] == 1
    assert state["envelope"]["messageId"] == "dispatch-1"
    assert state["consecutiveNoProgress"] == 0

    # The continuation then settles the work (ready): progress resets the
    # no-progress counter and no further continuation is attempted.
    _append_managed_driver_event(tmp_path)
    _seed_conversation(tmp_path, last_turn_status="ready")
    assert (
        managed_continuation.maybe_self_heal_pa_dispatched_session_after_release(
            SESSION_ID
        )
        is None
    )
    assert len(submitted) == 1
    assert _self_heal_state(tmp_path)["consecutiveNoProgress"] == 0


# ---------------------------------------------------------------------------
# ② revoked / unknown / missing-ledger envelope never continues
# ---------------------------------------------------------------------------


def test_revoked_envelope_never_self_heals(personal_env, monkeypatch):
    _seed_pa_dispatch_chain(personal_env, monkeypatch, status="revoked")
    submitted = _capture_managed_submit(monkeypatch)
    assert (
        managed_continuation.maybe_self_heal_pa_dispatched_session_after_release(
            SESSION_ID
        )
        is None
    )
    assert submitted == []
    assert _self_heal_state(personal_env["root"]) == {}


def test_unknown_and_missing_ledger_envelopes_fail_closed(
    personal_env, monkeypatch
):
    tmp_path = _seed_pa_dispatch_chain(personal_env, monkeypatch)
    submitted = _capture_managed_submit(monkeypatch)
    # Unknown row: the ledger cannot answer → no continuation.
    _append_driver_event(
        tmp_path, "dispatch-unknown", turn_id="turn-dispatch-unknown"
    )
    assert (
        managed_continuation.maybe_self_heal_pa_dispatched_session_after_release(
            SESSION_ID
        )
        is None
    )
    assert submitted == []
    # Missing ledger entirely: fail closed as well.
    ledger.ledger_database_path().unlink()
    _append_driver_event(tmp_path, "dispatch-1", turn_id="turn-dispatch-again")
    assert (
        managed_continuation.maybe_self_heal_pa_dispatched_session_after_release(
            SESSION_ID
        )
        is None
    )
    assert submitted == []


# ---------------------------------------------------------------------------
# ③ budget cap (2 per envelope) + two consecutive no-progress → permanent stop
# ---------------------------------------------------------------------------


def test_no_progress_permanent_stop_survives_newer_envelopes(
    personal_env, monkeypatch
):
    tmp_path = _seed_pa_dispatch_chain(personal_env, monkeypatch)
    submitted = _capture_managed_submit(monkeypatch)
    lifecycle = _capture_lifecycle(monkeypatch)

    # Continuation 1: accepted, budget spent.
    assert (
        managed_continuation.maybe_self_heal_pa_dispatched_session_after_release(
            SESSION_ID
        )["accepted"]
        is True
    )
    # The continuation stalls again (still resting, driver = our lane).
    _append_managed_driver_event(tmp_path, turn_id="turn-managed-1")
    assert (
        managed_continuation.maybe_self_heal_pa_dispatched_session_after_release(
            SESSION_ID
        )["accepted"]
        is True
    )
    assert len(submitted) == 2
    assert _self_heal_state(tmp_path)["consecutiveNoProgress"] == 1

    # Second consecutive stall: permanent stop, visible in the lifecycle.
    _append_managed_driver_event(tmp_path, turn_id="turn-managed-2")
    receipt = (
        managed_continuation.maybe_self_heal_pa_dispatched_session_after_release(
            SESSION_ID
        )
    )
    assert receipt["accepted"] is False
    assert receipt["reason"] == "stopped_no_progress"
    assert len(submitted) == 2
    state = _self_heal_state(tmp_path)
    assert state["stopped"] is True
    assert state["stoppedReason"] == "no_progress"
    assert any(
        event["phase"] == "pa_dispatch_self_heal_stopped" for event in lifecycle
    )

    # The stop is permanent: a fresh current envelope cannot revive the lane
    # (and the flag survives a state reload, i.e. a restart).
    _write_inbox(personal_env, TARGET_ID, [_dispatch_row("dispatch-2")])
    assert ledger.ensure_harvested(PA_ID) is True
    _append_driver_event(tmp_path, "dispatch-2", turn_id="turn-dispatch-2")
    assert (
        managed_continuation.maybe_self_heal_pa_dispatched_session_after_release(
            SESSION_ID
        )
        is None
    )
    assert len(submitted) == 2
    assert _self_heal_state(tmp_path)["stopped"] is True


def test_budget_cap_stops_even_after_progress(personal_env, monkeypatch):
    tmp_path = _seed_pa_dispatch_chain(personal_env, monkeypatch)
    submitted = _capture_managed_submit(monkeypatch)

    assert (
        managed_continuation.maybe_self_heal_pa_dispatched_session_after_release(
            SESSION_ID
        )["accepted"]
        is True
    )
    _append_managed_driver_event(tmp_path, turn_id="turn-managed-1")
    assert (
        managed_continuation.maybe_self_heal_pa_dispatched_session_after_release(
            SESSION_ID
        )["accepted"]
        is True
    )
    assert len(submitted) == 2
    # Interleaved progress resets the no-progress counter but not the budget.
    _seed_conversation(tmp_path, last_turn_status="ready")
    assert (
        managed_continuation.maybe_self_heal_pa_dispatched_session_after_release(
            SESSION_ID
        )
        is None
    )
    assert _self_heal_state(tmp_path)["consecutiveNoProgress"] == 0
    # Another stall of the same envelope: the budget (2) is exhausted.
    _seed_conversation(tmp_path, last_turn_status="needs_continue")
    assert (
        managed_continuation.maybe_self_heal_pa_dispatched_session_after_release(
            SESSION_ID
        )
        is None
    )
    assert len(submitted) == 2


# ---------------------------------------------------------------------------
# ④ plain inbox sessions and patrol follow-ups are never continued
# ---------------------------------------------------------------------------


def test_plain_inbox_and_followup_drivers_never_self_heal(
    personal_env, monkeypatch
):
    tmp_path = _seed_pa_dispatch_chain(personal_env, monkeypatch)
    submitted = _capture_managed_submit(monkeypatch)

    # Another agent's inbox message: not a PA dispatch.
    _append_driver_event(
        tmp_path,
        "dispatch-1",
        turn_id="turn-peer",
        metadata=_envelope_metadata("dispatch-1", source_agent_id=TARGET_ID),
    )
    assert (
        managed_continuation.maybe_self_heal_pa_dispatched_session_after_release(
            SESSION_ID
        )
        is None
    )
    # PA patrol follow-up row: the patrol's own lane.
    _append_driver_event(
        tmp_path,
        "dispatch-1",
        turn_id="turn-followup",
        metadata=_envelope_metadata("dispatch-1", inbox_kind="pa_followup"),
    )
    assert (
        managed_continuation.maybe_self_heal_pa_dispatched_session_after_release(
            SESSION_ID
        )
        is None
    )
    # Person message: the person owns the next move (waitsForPerson also holds).
    _append_driver_event(
        tmp_path,
        "dispatch-1",
        turn_id="turn-person",
        metadata={},
        source="raw",
        content="继续",
    )
    assert (
        managed_continuation.maybe_self_heal_pa_dispatched_session_after_release(
            SESSION_ID
        )
        is None
    )
    assert submitted == []


def test_lane_kill_switch_disables_self_heal(personal_env, monkeypatch):
    _seed_pa_dispatch_chain(personal_env, monkeypatch)
    submitted = _capture_managed_submit(monkeypatch)
    monkeypatch.setenv(managed_continuation.PA_DISPATCH_SELF_HEAL_ENV, "0")
    assert managed_continuation.pa_dispatch_self_heal_enabled() is False
    assert (
        managed_continuation.maybe_self_heal_pa_dispatched_session_after_release(
            SESSION_ID
        )
        is None
    )
    assert submitted == []


# ---------------------------------------------------------------------------
# Wiring: the release path invokes the hook after the inbox drain
# ---------------------------------------------------------------------------


def test_release_path_invokes_self_heal_hook(monkeypatch):
    called: list[str] = []
    monkeypatch.setattr(
        managed_continuation,
        "maybe_self_heal_pa_dispatched_session_after_release",
        lambda session_id: called.append(str(session_id)),
    )
    monkeypatch.setattr(
        session_service,
        "_SESSION_TURN_SCHEDULER",
        SimpleNamespace(release=lambda context: None, clear=lambda: None),
    )
    schedule._release_scheduled_session_turn(
        {"session_id": SESSION_ID, "agent_id": ""}
    )
    assert called == [SESSION_ID]
