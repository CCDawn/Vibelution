from __future__ import annotations

import pytest

from core.web.services import session_service


def _install_detail_probe(monkeypatch: pytest.MonkeyPatch, *, running: bool):
    calls: dict[str, list[object]] = {
        "loads": [],
        "sync": [],
        "reconcile": [],
        "target": [],
    }
    conversation = {
        "conversation_id": "session-poll",
        "title": "轮询会话",
        "agent_id": "agent-poll",
        "last_turn_status": "running" if running else "ready",
    }

    monkeypatch.setattr(session_service, "_agent_lookup_for_conversations", lambda: {})
    monkeypatch.setattr(
        session_service,
        "load_session_chat_state",
        lambda *_args, **_kwargs: calls["loads"].append(1) or dict(conversation),
    )
    monkeypatch.setattr(
        "core.web.services.session.candidate_read_gate.assert_candidate_session_read",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "core.web.services.session.directory_bridge.sync_conversation_record",
        lambda *args, **kwargs: calls["sync"].append((args, kwargs)),
    )
    monkeypatch.setattr(
        session_service,
        "_reconcile_stale_session_ledger",
        lambda *args, **kwargs: calls["reconcile"].append((args, kwargs)),
    )
    monkeypatch.setattr(
        session_service,
        "_load_conversation_detail_target",
        lambda *args, **kwargs: calls["target"].append((args, kwargs)) or dict(conversation),
    )
    monkeypatch.setattr(
        session_service,
        "_build_session_detail",
        lambda target, **kwargs: {"id": target["conversation_id"], **kwargs},
    )
    monkeypatch.setattr(session_service, "_SESSION_ACTIVE_TURN_IDS", {"session-poll": "turn-poll"} if running else {})
    monkeypatch.setattr(session_service, "_RUNNING_SESSION_IDS", {"session-poll"} if running else set())
    return calls


def test_light_running_poll_skips_directory_write_and_repair_reload(monkeypatch: pytest.MonkeyPatch):
    calls = _install_detail_probe(monkeypatch, running=True)

    session_service.get_session_detail("session-poll", include_secondary=False)

    assert len(calls["loads"]) == 1
    assert calls["sync"] == []
    assert calls["reconcile"] == [(
        ("session-poll",),
        {"active_turn_id": "turn-poll", "reason": "detail_loaded_after_restart"},
    )]
    assert calls["target"][0][1]["repair"] is False


def test_light_idle_poll_keeps_reconcile_reload_and_repair(monkeypatch: pytest.MonkeyPatch):
    calls = _install_detail_probe(monkeypatch, running=False)

    session_service.get_session_detail("session-poll", include_secondary=False)

    assert len(calls["loads"]) == 2
    assert calls["sync"] == []
    assert calls["reconcile"] == [(
        ("session-poll",),
        {"active_turn_id": "", "reason": "detail_loaded_after_restart"},
    )]
    assert calls["target"][0][1]["repair"] is True


def test_full_detail_keeps_directory_sync_and_repair(monkeypatch: pytest.MonkeyPatch):
    calls = _install_detail_probe(monkeypatch, running=True)

    session_service.get_session_detail("session-poll", include_secondary=True)

    assert len(calls["sync"]) == 1
    assert len(calls["loads"]) == 2
    assert calls["target"][0][1]["repair"] is True


def test_candidate_permission_denial_precedes_detail_side_effects(monkeypatch: pytest.MonkeyPatch):
    calls = _install_detail_probe(monkeypatch, running=True)
    denied = RuntimeError("candidate read denied")
    monkeypatch.setattr(
        "core.web.services.session.candidate_read_gate.assert_candidate_session_read",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(denied),
    )

    with pytest.raises(RuntimeError, match="candidate read denied"):
        session_service.get_session_detail("session-poll", include_secondary=False)

    assert len(calls["loads"]) == 1
    assert calls["sync"] == []
    assert calls["reconcile"] == []
    assert calls["target"] == []
