# -*- coding: utf-8 -*-
"""Third wake signal: request_managed_continuation + waitsForPerson rails.

Covers the admission channel's accept/reject matrix, the persistent cap (3,
restart-safe) with its visible limit failure, the continuation_expected
fingerprint guarantee (a rejected managed request never disturbs the human
"继续" snapshot CAS), the worker auto-continue gate branch, and the two
machine-wake leak channels (queued notice drain, proactive plugin turns).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from core.chat.conversation_branches import analyze_conversation_branches
from core.chat.conversation_ledger import append_conversation_event, load_conversation_events
from core.chat.turn_journal import EVENT_USER_MESSAGE
from core.infrastructure import developer_sandbox
from core.ui.chat_state import load_session_chat_state, save_chat_state
from core.web.services import session_service
from core.web.services.session import managed_continuation, pending_question, proactive, queued_turns, submit, worker
from tests.helpers.web_chat_state import _reset_seeded_session_runtime
from tests.test_session_submit import _prepare_default_submit_session

SESSION_ID = "session-live"


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)


def _seed_conversation(tmp_path, **overrides: Any) -> dict[str, Any]:
    conversation = {
        "conversation_id": SESSION_ID,
        "title": "Managed continuation",
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
    return conversation


def _append_user_event(
    tmp_path,
    *,
    source: str,
    metadata: dict[str, Any] | None = None,
    turn_id: str = "turn-resting",
    content: str = "推进任务",
) -> None:
    append_conversation_event(
        tmp_path,
        SESSION_ID,
        turn_id,
        EVENT_USER_MESSAGE,
        payload={"content": content, "source": source, "metadata": metadata or {}},
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


def _machine_resting_state(tmp_path, monkeypatch) -> list[dict]:
    """Seed a resting session whose last speaker was a machine source."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_is_session_running", lambda sid: False)
    _seed_conversation(tmp_path)
    _append_user_event(
        tmp_path,
        source="agent_inbox",
        metadata={"kind": "agent_inbox_message"},
    )
    return _capture_lifecycle(monkeypatch)


def _capture_lifecycle(monkeypatch) -> list[dict]:
    captured: list[dict] = []

    def fake_record(session_id, phase, **kwargs):
        captured.append({"sessionId": session_id, "phase": phase, **kwargs})

    monkeypatch.setattr(session_service, "_record_session_turn_lifecycle_event", fake_record)
    return captured


# ---------------------------------------------------------------------------
# Admission channel: accept / reject matrix
# ---------------------------------------------------------------------------


def test_rejects_when_session_waits_for_person(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_is_session_running", lambda sid: False)
    _seed_conversation(tmp_path)
    _append_user_event(tmp_path, source="raw")
    captured = _capture_managed_submit(monkeypatch)
    receipt = managed_continuation.request_managed_continuation(
        SESSION_ID, source="research_org", reason="任务未完成"
    )
    assert receipt == {
        "accepted": False,
        "reason": "rejected_waiting_for_person",
        "sessionId": SESSION_ID,
        "source": "research_org",
        "restingPhase": "needs_continue",
    }
    assert captured == []
    assert load_session_chat_state(tmp_path, SESSION_ID).get(
        managed_continuation.MANAGED_CONTINUATION_STATE_KEY
    ) is None


def test_accepts_machine_resting_session_and_submits_dedicated_source(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_is_session_running", lambda sid: False)
    _seed_conversation(tmp_path)
    _append_user_event(
        tmp_path,
        source="agent_inbox",
        metadata={"kind": "agent_inbox_message", "messageId": "msg-1"},
    )
    captured = _capture_managed_submit(monkeypatch)
    receipt = managed_continuation.request_managed_continuation(
        SESSION_ID, source="research_org", reason="阶段未完成"
    )
    assert receipt["accepted"] is True
    assert receipt["managedContinuationCount"] == 1
    assert receipt["managedContinuationLimit"] == 3
    assert len(captured) == 1
    call = captured[0]
    assert call["message_source"] == "managed_continuation"
    assert call["message_metadata"]["kind"] == "managed_continuation"
    assert call["message_metadata"]["source"] == "research_org"
    assert call["message_metadata"]["managedContinuationCount"] == 1
    assert call["write_intent"] is False
    # The attempt counter is persisted before submit, restart-safe.
    state = load_session_chat_state(tmp_path, SESSION_ID)[
        managed_continuation.MANAGED_CONTINUATION_STATE_KEY
    ]
    assert state["count"] == 1
    assert state["lastSource"] == "research_org"


def test_rejects_sessions_not_resting_in_resumable_phases(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_is_session_running", lambda sid: False)
    _seed_conversation(tmp_path, last_turn_status="ready")
    _append_user_event(tmp_path, source="agent_inbox")
    receipt = managed_continuation.request_managed_continuation(
        SESSION_ID, source="research_org", reason="nudge"
    )
    assert receipt["accepted"] is False
    assert receipt["reason"] == "rejected_not_resumable"
    assert receipt["lastTurnStatus"] == "ready"


def test_rejects_running_session(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_is_session_running", lambda sid: True)
    _seed_conversation(tmp_path)
    receipt = managed_continuation.request_managed_continuation(
        SESSION_ID, source="research_org", reason="nudge"
    )
    assert receipt == {
        "accepted": False,
        "reason": "rejected_session_busy",
        "sessionId": SESSION_ID,
        "source": "research_org",
    }


def test_rejects_external_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_is_session_running", lambda sid: False)
    _seed_conversation(tmp_path, metadata={"source": "external_agent_task"})
    _append_user_event(tmp_path, source="external_agent_task")
    receipt = managed_continuation.request_managed_continuation(
        SESSION_ID, source="research_org", reason="nudge"
    )
    assert receipt["reason"] == "rejected_external_session"


def test_rejects_sessions_under_queue_hold(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_is_session_running", lambda sid: False)
    _seed_conversation(
        tmp_path,
        queued_turn_hold={"reason": "user_stop", "turnId": "turn-resting", "heldAt": "2026-11-01T00:00:00"},
    )
    _append_user_event(tmp_path, source="agent_inbox")
    receipt = managed_continuation.request_managed_continuation(
        SESSION_ID, source="research_org", reason="nudge"
    )
    assert receipt["reason"] == "rejected_queue_hold"


def test_rejects_when_queued_user_rows_own_the_next_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_is_session_running", lambda sid: False)
    _seed_conversation(
        tmp_path,
        queued_turns=[{"id": "q-user", "status": "queued", "content": "用户排队消息"}],
    )
    _append_user_event(tmp_path, source="agent_inbox")
    receipt = managed_continuation.request_managed_continuation(
        SESSION_ID, source="research_org", reason="nudge"
    )
    assert receipt["reason"] == "rejected_queued_user_turns"


def test_requires_non_empty_source(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_is_session_running", lambda sid: False)
    _seed_conversation(tmp_path)
    with pytest.raises(session_service.SessionValidationError):
        managed_continuation.request_managed_continuation(SESSION_ID, source="  ", reason="nudge")


# ---------------------------------------------------------------------------
# Cap: persistent attempts, restart-safe, visible failure beyond the limit
# ---------------------------------------------------------------------------


def _machine_resting_env(tmp_path, monkeypatch):
    lifecycle = _machine_resting_state(tmp_path, monkeypatch)
    return _capture_managed_submit(monkeypatch), lifecycle


def _simulate_managed_turn_settled(tmp_path) -> None:
    """Journal the managed turn's user message; the counter chain reads it back."""

    append_conversation_event(
        tmp_path,
        SESSION_ID,
        f"turn-managed-{1}",
        EVENT_USER_MESSAGE,
        payload={
            "content": managed_continuation.MANAGED_CONTINUATION_PROMPT,
            "source": "managed_continuation",
            "metadata": {"kind": "managed_continuation", "source": "research_org"},
        },
        source="submit_session_message",
    )


def test_cap_persists_across_restarts_and_fails_visibly(tmp_path, monkeypatch):
    captured, lifecycle = _machine_resting_env(tmp_path, monkeypatch)
    for expected_count in (1, 2, 3):
        receipt = managed_continuation.request_managed_continuation(
            SESSION_ID, source="research_org", reason="nudge"
        )
        assert receipt["accepted"] is True
        assert receipt["managedContinuationCount"] == expected_count
        _simulate_managed_turn_settled(tmp_path)
    # Simulated restart: no process memory holds the counter; the persisted
    # session state is the only source of truth.
    assert load_session_chat_state(tmp_path, SESSION_ID)[
        managed_continuation.MANAGED_CONTINUATION_STATE_KEY
    ]["count"] == 3
    receipt = managed_continuation.request_managed_continuation(
        SESSION_ID, source="research_org", reason="nudge"
    )
    assert receipt["accepted"] is False
    assert receipt["reason"] == "rejected_continuation_limit"
    assert receipt["managedContinuationCount"] == 3
    assert len(captured) == 3
    assert any(
        event["phase"] == "managed_continuation_limit_reached"
        and event["outcome"] == "failed"
        for event in lifecycle
    )


def test_human_engagement_blocks_the_channel_until_a_new_machine_turn(tmp_path, monkeypatch):
    captured, _lifecycle = _machine_resting_env(tmp_path, monkeypatch)
    managed_continuation.request_managed_continuation(SESSION_ID, source="research_org", reason="nudge")
    _simulate_managed_turn_settled(tmp_path)
    assert load_session_chat_state(tmp_path, SESSION_ID)[
        managed_continuation.MANAGED_CONTINUATION_STATE_KEY
    ]["count"] == 1
    # The person engages: the session now waits on the person, so machine
    # requests are refused outright — the channel never fights a person.
    append_conversation_event(
        tmp_path,
        SESSION_ID,
        "turn-human",
        EVENT_USER_MESSAGE,
        payload={"content": "继续", "source": "raw", "metadata": {}},
        source="submit_session_message",
        correlation_id="sub-human",
    )
    receipt = managed_continuation.request_managed_continuation(
        SESSION_ID, source="research_org", reason="nudge"
    )
    assert receipt["reason"] == "rejected_waiting_for_person"
    assert len(captured) == 1
    # A fresh machine-sourced turn (agent inbox wake) settles a new cycle:
    # the chain counter restarts from zero.
    append_conversation_event(
        tmp_path,
        SESSION_ID,
        "turn-inbox-2",
        EVENT_USER_MESSAGE,
        payload={"content": "新任务简报", "source": "agent_inbox", "metadata": {"kind": "agent_inbox_message"}},
        source="submit_session_message",
        correlation_id="sub-inbox-2",
    )
    receipt = managed_continuation.request_managed_continuation(
        SESSION_ID, source="research_org", reason="nudge"
    )
    assert receipt["accepted"] is True
    assert receipt["managedContinuationCount"] == 1
    assert len(captured) == 2


def test_submit_failure_rolls_back_the_attempt_counter(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_is_session_running", lambda sid: False)
    _seed_conversation(tmp_path)
    _append_user_event(tmp_path, source="agent_inbox", metadata={"kind": "agent_inbox_message"})

    def failing_submit(*_args, **_kwargs):
        raise session_service.SessionBusyError("busy")

    monkeypatch.setattr(session_service, "submit_session_message", failing_submit)
    with pytest.raises(session_service.SessionBusyError):
        managed_continuation.request_managed_continuation(SESSION_ID, source="research_org", reason="nudge")
    assert load_session_chat_state(tmp_path, SESSION_ID).get(
        managed_continuation.MANAGED_CONTINUATION_STATE_KEY
    ) is None


# ---------------------------------------------------------------------------
# Trap 4: the channel never disturbs the human continuation_expected CAS
# ---------------------------------------------------------------------------


@pytest.fixture
def resting_human_session(tmp_path, monkeypatch):
    """A settled needs_continue session whose last speaker was the person."""

    sid = _prepare_default_submit_session(tmp_path, monkeypatch)
    append_conversation_event(tmp_path, sid, "turn-resting", "turn_started", status="running", source="submit_session_message")
    append_conversation_event(
        tmp_path, sid, "turn-resting", EVENT_USER_MESSAGE,
        payload={"content": "整理调研结论", "source": "raw", "metadata": {}},
        source="submit_session_message", correlation_id="sub-original",
    )
    append_conversation_event(tmp_path, sid, "turn-resting", "assistant_message", payload={"content": "部分结果"})
    append_conversation_event(tmp_path, sid, "turn-resting", "turn_completed", status="needs_continue")
    events = load_conversation_events(tmp_path, sid)
    state = session_service.load_session_chat_state(tmp_path, sid)
    state["last_turn_status"] = "needs_continue"
    state["last_turn_terminal_turn_id"] = "turn-resting"
    session_service.save_session_chat_state(tmp_path, sid, state)
    expected = {
        "turnId": "turn-resting",
        "headId": analyze_conversation_branches(events).active_leaf_id,
        "ledgerSeq": events[-1].sequence,
        "agentId": state["agent_id"],
    }
    monkeypatch.setattr(session_service, "_is_session_running", lambda session_id: False)
    scheduled: list[dict] = []
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled.append(dict(context)))
    yield sid, expected, scheduled
    _reset_seeded_session_runtime(sid)


def test_rejected_managed_request_leaves_human_continue_snapshot_intact(
    resting_human_session, monkeypatch
):
    sid, expected, scheduled = resting_human_session
    receipt = managed_continuation.request_managed_continuation(
        sid, source="research_org", reason="nudge"
    )
    assert receipt["reason"] == "rejected_waiting_for_person"
    fingerprint_before = submit._session_submission_fingerprint_base(
        attachment_ids=[],
        references=[],
        mental_model_enabled=False,
        runtime_status_enabled=False,
        turn_mode="",
        write_intent=None,
        message_metadata=None,
        message_source="raw",
        turn_status_tail=None,
        model_selection=None,
    )
    reply = submit.submit_session_message_lightweight(
        sid, "继续", client_submission_id="continue-after-managed", _continuation_expected=expected,
    )
    assert reply["turnId"] not in ("", "turn-resting")
    assert len(scheduled) == 1
    fingerprint_after = submit._session_submission_fingerprint_base(
        attachment_ids=[],
        references=[],
        mental_model_enabled=False,
        runtime_status_enabled=False,
        turn_mode="",
        write_intent=None,
        message_metadata=None,
        message_source="raw",
        turn_status_tail=None,
        model_selection=None,
    )
    assert fingerprint_before == fingerprint_after


def test_managed_channel_submits_standalone_without_snapshot(tmp_path, monkeypatch):
    _machine_resting_state(tmp_path, monkeypatch)
    captured = _capture_managed_submit(monkeypatch)
    managed_continuation.request_managed_continuation(SESSION_ID, source="research_org", reason="nudge")
    assert len(captured) == 1
    # No continuation_expected snapshot rides the managed submission: the
    # fingerprint/CAS path is structurally unreachable for this channel.
    assert "_continuation_expected" not in captured[0]
    assert captured[0]["message_source"] == "managed_continuation"


# ---------------------------------------------------------------------------
# Worker gate: double-confirmed managed_continuation branch
# ---------------------------------------------------------------------------


def test_worker_gate_authorizes_double_confirmed_managed_source():
    context = {
        "user_message_source": "managed_continuation",
        "message_metadata": {"kind": "managed_continuation", "source": "research_org"},
    }
    assert worker._session_context_allows_internal_auto_continue(context) is True


@pytest.mark.parametrize(
    "context",
    [
        # Missing the metadata half of the double confirmation.
        {"user_message_source": "managed_continuation", "message_metadata": {"kind": "managed_continuation"}},
        {"user_message_source": "managed_continuation", "message_metadata": {}},
        {"user_message_source": "managed_continuation"},
        # Kind mismatch.
        {
            "user_message_source": "managed_continuation",
            "message_metadata": {"kind": "other", "source": "research_org"},
        },
        # Source mismatch.
        {
            "user_message_source": "raw",
            "message_metadata": {"kind": "managed_continuation", "source": "research_org"},
        },
    ],
)
def test_worker_gate_stays_closed_without_full_confirmation(context):
    assert worker._session_context_allows_internal_auto_continue(context) is False


def test_worker_gate_preserves_existing_branch_semantics():
    # raw/proactive stays closed; proactive explicit False stays False;
    # external explicit True stays True.
    assert worker._session_context_allows_internal_auto_continue(
        {"user_message_source": "raw", "message_metadata": {}}
    ) is False
    assert worker._session_context_allows_internal_auto_continue(
        {
            "allow_internal_auto_continue": False,
            "user_message_source": "proactive_plugin",
            "message_metadata": {"kind": "internal_turn_trigger"},
        }
    ) is False
    assert worker._session_context_allows_internal_auto_continue(
        {
            "user_message_source": "external_agent_task",
            "message_metadata": {"source": "external_agent_task", "allowInternalAutoContinue": True},
        }
    ) is True


# ---------------------------------------------------------------------------
# Leak channel 1: queued notice drain
# ---------------------------------------------------------------------------


@pytest.fixture
def drain_env(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", Path(tmp_path))
    monkeypatch.setattr(session_service, "_is_session_running", lambda session_id: False)
    published: list[str] = []
    monkeypatch.setattr(
        session_service,
        "_publish_session_detail_snapshot",
        lambda session_id, **_kwargs: published.append(str(session_id)),
    )
    monkeypatch.setattr(queued_turns, "_schedule_session_queued_turn_drain_continuation", lambda _sid: None)
    # Batch-4 held-marker tests enqueue through the real API; keep the
    # enqueue-triggered drain synchronous-only so the test's own drain call
    # is the one that decides.
    monkeypatch.setattr(session_service, "_schedule_session_queued_turn_drain", lambda _sid: None)
    submitted: list[dict] = []

    def fake_submit(_session_id, content, **kwargs):
        submitted.append({"content": content, **kwargs})
        return {"accepted": True}

    monkeypatch.setattr(session_service, "submit_session_message", fake_submit)
    return SimpleNamespace(tmp_path=tmp_path, submitted=submitted, published=published)


def _notice_row(row_id: str, kind: str) -> dict[str, Any]:
    return {
        "id": row_id,
        "content": f"notice-{row_id}",
        "kind": kind,
        "status": "queued",
        "createdAt": "2026-11-01T00:00:00",
        "updatedAt": "2026-11-01T00:00:00",
    }


def _seed_drain_session(tmp_path, rows: list[dict[str, Any]], **overrides: Any) -> None:
    _seed_conversation(tmp_path, queued_turns=rows, **overrides)


def test_drain_holds_machine_notices_when_session_waits_for_person(drain_env):
    _seed_drain_session(drain_env.tmp_path, [_notice_row("notice-1", "task_notification")])
    _append_user_event(drain_env.tmp_path, source="raw")
    assert queued_turns.drain_session_queued_turns(SESSION_ID) is False
    assert drain_env.submitted == []
    rows = load_session_chat_state(drain_env.tmp_path, SESSION_ID)["queued_turns"]
    assert rows[0]["status"] == "queued"


def test_drain_allows_machine_notices_when_last_speaker_is_machine(drain_env):
    _seed_drain_session(drain_env.tmp_path, [_notice_row("notice-1", "task_notification")])
    _append_user_event(
        drain_env.tmp_path,
        source="agent_inbox",
        metadata={"kind": "agent_inbox_message"},
    )
    assert queued_turns.drain_session_queued_turns(SESSION_ID) is True
    assert len(drain_env.submitted) == 1
    assert drain_env.submitted[0]["message_source"] == "task_notification"


def test_drain_allows_user_rows_even_when_session_waits_for_person(drain_env):
    user_row = {
        "id": "q-user",
        "clientSubmissionId": "sub-q-user",
        "content": "用户排队内容",
        "attachments": [],
        "references": [],
        "mentalModelEnabled": False,
        "runtimeStatusEnabled": False,
        "turnMode": "",
        "writeIntent": False,
        "status": "queued",
        "createdAt": "2026-11-01T00:00:00",
        "updatedAt": "2026-11-01T00:00:00",
    }
    _seed_drain_session(drain_env.tmp_path, [user_row])
    _append_user_event(drain_env.tmp_path, source="raw")
    assert queued_turns.drain_session_queued_turns(SESSION_ID) is True
    assert len(drain_env.submitted) == 1


def test_drain_ignores_gate_when_session_not_resting(drain_env):
    _seed_drain_session(drain_env.tmp_path, [_notice_row("notice-1", "task_notification")], last_turn_status="ready")
    _append_user_event(drain_env.tmp_path, source="raw")
    assert queued_turns.drain_session_queued_turns(SESSION_ID) is True
    assert len(drain_env.submitted) == 1


# ---------------------------------------------------------------------------
# Leak channel 2: proactive plugin turns
# ---------------------------------------------------------------------------


class _FakeExtension:
    def __init__(self, current: bool = True):
        self._current = current

    def proactive_turn_is_current(self, *, agent_id, binding_revision, delivery_token) -> bool:
        return self._current


def _clear_registered_proactive_contexts() -> None:
    with proactive._PROACTIVE_CONTEXTS_LOCK:
        proactive._PROACTIVE_CONTEXTS.clear()


def test_proactive_refused_when_session_waits_for_person(tmp_path, monkeypatch):
    import core.agent_plugins.runtime_extensions as runtime_extensions

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_is_session_running", lambda sid: False)
    _seed_conversation(tmp_path)
    _append_user_event(tmp_path, source="raw")
    monkeypatch.setattr(runtime_extensions, "proactive_runtime_extension", lambda **_kw: _FakeExtension())
    scheduled: list[dict] = []
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled.append(context))
    registered: list[dict] = []
    monkeypatch.setattr(proactive, "register_proactive_turn_context", lambda context: registered.append(context))
    with pytest.raises(session_service.SessionValidationError, match="waiting for its user"):
        proactive.submit_session_proactive_turn(
            session_id=SESSION_ID,
            agent_id="agent-x",
            origin="proactive_plugin",
            source_kind="virtual-human-life",
            plugin_id="virtual-human-life",
            trigger_id="trigger-1",
            delivery_token="token-1",
            binding_revision=1,
        )
    assert scheduled == []
    assert registered == []


def test_proactive_allowed_when_last_speaker_is_machine(tmp_path, monkeypatch):
    import core.agent_plugins.runtime_extensions as runtime_extensions

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_is_session_running", lambda sid: False)
    _seed_conversation(tmp_path)
    _append_user_event(tmp_path, source="agent_inbox", metadata={"kind": "agent_inbox_message"})
    monkeypatch.setattr(runtime_extensions, "proactive_runtime_extension", lambda **_kw: _FakeExtension())
    monkeypatch.setattr(session_service, "_record_session_turn_scheduled_event", lambda context: None)
    scheduled: list[dict] = []
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled.append(context))
    receipt = proactive.submit_session_proactive_turn(
        session_id=SESSION_ID,
        agent_id="agent-x",
        origin="proactive_plugin",
        source_kind="virtual-human-life",
        plugin_id="virtual-human-life",
        trigger_id="trigger-1",
        delivery_token="token-1",
        binding_revision=1,
    )
    assert receipt["accepted"] is True
    assert len(scheduled) == 1
    _clear_registered_proactive_contexts()


def test_proactive_allowed_when_session_not_resting(tmp_path, monkeypatch):
    import core.agent_plugins.runtime_extensions as runtime_extensions

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_is_session_running", lambda sid: False)
    _seed_conversation(tmp_path, last_turn_status="ready")
    _append_user_event(tmp_path, source="raw")
    monkeypatch.setattr(runtime_extensions, "proactive_runtime_extension", lambda **_kw: _FakeExtension())
    monkeypatch.setattr(session_service, "_record_session_turn_scheduled_event", lambda context: None)
    scheduled: list[dict] = []
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled.append(context))
    receipt = proactive.submit_session_proactive_turn(
        session_id=SESSION_ID,
        agent_id="agent-x",
        origin="proactive_plugin",
        source_kind="virtual-human-life",
        plugin_id="virtual-human-life",
        trigger_id="trigger-1",
        delivery_token="token-1",
        binding_revision=1,
    )
    assert receipt["accepted"] is True
    _clear_registered_proactive_contexts()


# ---------------------------------------------------------------------------
# waitsForPerson predicate unit coverage (native operator-event shape)
# ---------------------------------------------------------------------------


def test_predicate_follows_native_operator_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_is_session_running", lambda sid: False)
    _seed_conversation(tmp_path)

    def last_event_waits(payload: dict, *, source: str = "submit_session_message") -> bool:
        append_conversation_event(
            tmp_path, SESSION_ID, "turn-resting", EVENT_USER_MESSAGE,
            payload=payload, source=source,
        )
        return managed_continuation.session_waits_for_person(session_service, SESSION_ID)

    assert last_event_waits({"content": "hi", "source": "raw", "metadata": {}}) is True
    # Machine-shaped payloads never read as the person.
    assert last_event_waits({"content": "hi", "source": "agent_inbox", "metadata": {}}) is False
    assert last_event_waits({"content": "hi", "source": "raw", "metadata": {"kind": "agent_inbox_message"}}) is False
    assert last_event_waits({"content": "hi", "source": "raw", "metadata": {"agentId": "agent-x"}}) is False
    assert last_event_waits({"content": "hi", "source": "raw", "metadata": {"proactive": True}}) is False
    assert last_event_waits({"content": "hi", "source": "raw", "metadata": {"sourceKind": "machine"}}) is False
    assert last_event_waits({"content": "hi", "source": "queued_turn", "metadata": {}}) is False
    assert last_event_waits({"content": "hi", "source": "raw", "metadata": {}}, source="schedule_proactive") is False
    # operator-event source kind is part of the shape (event attribute).
    assert (
        managed_continuation._journal_user_event_is_person_message(
            type("E", (), {"payload": {"content": "hi", "source": "raw", "metadata": {}},
                           "source": "submit_session_message", "source_kind": "agent", "visible_in_model": True})()
        )
        is False
    )
    assert (
        managed_continuation._journal_user_event_is_person_message(
            type("E", (), {"payload": {"content": "hi", "source": "raw", "metadata": {}},
                           "source": "submit_session_message", "source_kind": "operator", "visible_in_model": False})()
        )
        is False
    )


def test_not_resting_sessions_never_count_as_waiting(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_is_session_running", lambda sid: False)
    _seed_conversation(tmp_path, last_turn_status="ready")
    _append_user_event(tmp_path, source="raw")
    assert managed_continuation.session_waits_for_person(session_service, SESSION_ID) is False


# ---------------------------------------------------------------------------
# Batch-4 waitsForPerson anchor semantics (real journal shape)
# ---------------------------------------------------------------------------


def _append_settled_waiting_turn(
    tmp_path,
    *,
    turn_id: str = "turn-person",
    driver_source: str = "raw",
    driver_metadata: dict[str, Any] | None = None,
    final_status: str = "needs_continue",
) -> None:
    """Journal a full turn: person/machine driver input + resumable settlement.

    This is the real ``persist.py`` shape: a ``user_message`` event followed
    by a terminal event carrying the resumable ``finalStatus``.
    """

    append_conversation_event(
        tmp_path,
        SESSION_ID,
        turn_id,
        EVENT_USER_MESSAGE,
        payload={"content": "推进任务", "source": driver_source, "metadata": driver_metadata or {}},
        source="submit_session_message",
    )
    append_conversation_event(
        tmp_path,
        SESSION_ID,
        turn_id,
        "turn_completed",
        status=final_status,
        payload={"resultStatus": final_status, "finalStatus": final_status},
        source="persist_session_turn_result",
    )


def _waits() -> bool:
    return managed_continuation.session_waits_for_person(session_service, SESSION_ID)


def test_predicate_machine_message_does_not_resolve_waiting(tmp_path, monkeypatch):
    """盲区② 收口：person-driven pause 之后的机器 user_message 不得解除等待。"""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_is_session_running", lambda sid: False)
    _seed_conversation(tmp_path)
    _append_settled_waiting_turn(tmp_path)
    assert _waits() is True
    # A machine user_message (inbox wake row) lands after the resting anchor.
    _append_user_event(tmp_path, source="agent_inbox", metadata={"kind": "agent_inbox_message"}, turn_id="turn-machine")
    assert _waits() is True


def test_predicate_person_message_after_anchor_resolves_waiting(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_is_session_running", lambda sid: False)
    _seed_conversation(tmp_path)
    _append_settled_waiting_turn(tmp_path)
    assert _waits() is True
    _append_user_event(tmp_path, source="raw", content="继续", turn_id="turn-human-2")
    assert _waits() is False


def test_predicate_phase_exit_clears_waiting(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_is_session_running", lambda sid: False)
    _seed_conversation(tmp_path)
    _append_settled_waiting_turn(tmp_path)
    assert _waits() is True
    _seed_conversation(tmp_path, last_turn_status="ready")
    assert _waits() is False


def test_predicate_machine_driven_pause_never_arms_waiting(tmp_path, monkeypatch):
    """Machine-owned work keeps flowing: a machine-driven resumable settlement
    neither arms the wait nor moves a person anchor (batch-3 channel intact)."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_is_session_running", lambda sid: False)
    _seed_conversation(tmp_path)
    _append_settled_waiting_turn(
        tmp_path,
        turn_id="turn-machine",
        driver_source="agent_inbox",
        driver_metadata={"kind": "agent_inbox_message"},
    )
    assert _waits() is False


def test_predicate_machine_turn_does_not_dissolve_armed_wait(tmp_path, monkeypatch):
    """An armed person wait survives a machine turn that re-pauses resumably."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_is_session_running", lambda sid: False)
    _seed_conversation(tmp_path)
    _append_settled_waiting_turn(tmp_path, turn_id="turn-person")
    _append_settled_waiting_turn(
        tmp_path,
        turn_id="turn-machine-2",
        driver_source="agent_inbox",
        driver_metadata={"kind": "agent_inbox_message"},
    )
    assert _waits() is True


def test_predicate_pending_question_slot_arms_waiting_without_resting(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_is_session_running", lambda sid: False)
    _seed_conversation(tmp_path, last_turn_status="ready")
    assert _waits() is False
    pending_question.set_session_pending_question(SESSION_ID, question_text="要把结论整理成简报吗？")
    assert _waits() is True
    pending_question.consume_session_pending_question(SESSION_ID)
    assert _waits() is False


def test_rail_off_restores_legacy_last_speaker_predicate(tmp_path, monkeypatch):
    """急停开关关闭=批三旧语义：机器 last-speaker 翻 False，闸门全部回到旧形状。"""

    monkeypatch.setenv(managed_continuation.WAITS_FOR_PERSON_RAIL_ENV, "0")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_is_session_running", lambda sid: False)
    _seed_conversation(tmp_path)
    _append_settled_waiting_turn(tmp_path, turn_id="turn-person")
    assert _waits() is True
    # Under the legacy shape the machine message flips the last speaker, so
    # the armed wait silently dissolves — the exact batch-3 behavior.
    _append_user_event(tmp_path, source="agent_inbox", metadata={"kind": "agent_inbox_message"}, turn_id="turn-machine")
    assert _waits() is False
    # The pendingQuestion slot stops counting too.
    _seed_conversation(tmp_path, last_turn_status="ready")
    pending_question.set_session_pending_question(SESSION_ID, question_text="要继续吗？")
    assert _waits() is False


# ---------------------------------------------------------------------------
# Batch-4 held marker on machine notices enqueued while waiting
# ---------------------------------------------------------------------------


def test_enqueue_marks_notice_held_while_waiting_and_drain_still_refuses(drain_env):
    _seed_drain_session(drain_env.tmp_path, [])
    _append_settled_waiting_turn(drain_env.tmp_path, turn_id="turn-person")
    row = queued_turns.enqueue_session_runtime_notice(
        SESSION_ID,
        kind="task_notification",
        content="后台任务回执",
        source_id="task-notice-1",
    )
    assert row.get("status") == "queued"
    held = row.get("held")
    assert isinstance(held, dict) and held.get("reason") == "waiting_for_person"
    assert str(held.get("heldAt") or "").strip()
    # The drain gate stays the enforcing second barrier.
    assert queued_turns.drain_session_queued_turns(SESSION_ID) is False
    assert drain_env.submitted == []
    rows = load_session_chat_state(drain_env.tmp_path, SESSION_ID)["queued_turns"]
    assert rows[0]["id"] == row["id"] and rows[0].get("held")


def test_held_row_drains_exactly_once_after_person_resolves(drain_env):
    _seed_drain_session(drain_env.tmp_path, [])
    _append_settled_waiting_turn(drain_env.tmp_path, turn_id="turn-person")
    row = queued_turns.enqueue_session_runtime_notice(
        SESSION_ID,
        kind="task_notification",
        content="后台任务回执",
        source_id="task-notice-1",
    )
    assert row.get("held")
    # The person answers: their message lands after the resting anchor.
    _append_user_event(drain_env.tmp_path, source="raw", content="继续", turn_id="turn-human-2")
    assert queued_turns.drain_session_queued_turns(SESSION_ID) is True
    assert len(drain_env.submitted) == 1
    rows = load_session_chat_state(drain_env.tmp_path, SESSION_ID).get("queued_turns") or []
    assert [item["id"] for item in rows if item.get("status") == "queued"] == []


def test_enqueue_skips_held_marker_when_rail_off(drain_env, monkeypatch):
    monkeypatch.setenv(managed_continuation.WAITS_FOR_PERSON_RAIL_ENV, "0")
    _seed_drain_session(drain_env.tmp_path, [])
    _append_settled_waiting_turn(drain_env.tmp_path, turn_id="turn-person")
    row = queued_turns.enqueue_session_runtime_notice(
        SESSION_ID,
        kind="task_notification",
        content="后台任务回执",
        source_id="task-notice-2",
    )
    assert "held" not in row
