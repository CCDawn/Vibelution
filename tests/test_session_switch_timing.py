"""Switch-latency probe: select and detail must emit stage timings.

The probe exists to answer one question with evidence instead of intuition:
when a switch feels slow while a turn is running, is the time spent waiting
for ``_CHAT_STATE_LOCK`` or inside the locked body? These tests pin the
contract that makes that measurement possible, and pin the switch-path cost
reductions that followed from it.
"""

from __future__ import annotations

from core.infrastructure import developer_sandbox
from core.web.services import agent_directory_service, session_service


def _isolate(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", tmp_path)


def _capture_scene_events(monkeypatch) -> list[tuple[tuple, dict]]:
    events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )
    return events


def _switch_events(events, code: str) -> list[dict]:
    matched = []
    for args, kwargs in events:
        if len(args) >= 3 and args[2] == code:
            matched.append(dict(kwargs.get("fields") or {}))
    return matched


def test_select_emits_switch_timing_with_lock_wait_split(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    events = _capture_scene_events(monkeypatch)
    created = session_service.create_chat_session(title="Switch probe", lightweight=True)
    events.clear()

    detail = session_service.select_chat_session(created["id"], lightweight=True)

    assert detail["id"] == created["id"]
    samples = _switch_events(events, "conversation.session.switch.timing")
    assert len(samples) == 1
    sample = samples[0]
    assert sample["surface"] == "select_lightweight"
    assert sample["sessionId"] == created["id"]
    stage = sample["stageDurationsMs"]
    # Wait and hold must stay separate fields; collapsing them would hide the
    # contention this probe is meant to expose.
    for key in ("chatStateLockWaitMs", "chatStateLockHoldMs", "agentLookupMs"):
        assert key in stage, key
        assert isinstance(stage[key], int), key
        assert stage[key] >= 0, key
    assert sample["totalMs"] >= stage["chatStateLockWaitMs"] + stage["chatStateLockHoldMs"]


def test_select_resolves_agent_closure_instead_of_full_registry(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    created = session_service.create_chat_session(title="Scoped lookup", lightweight=True)
    observed: list[dict] = []

    def scoped(**kwargs):
        observed.append(dict(kwargs))
        return {}

    monkeypatch.setattr(session_service, "_agent_lookup_for_conversations", scoped)

    session_service.select_chat_session(created["id"], lightweight=True)

    # Every switch resolve must be scoped. An unscoped call (no kwargs) would
    # deep-copy the whole Agent registry per switch, which is what we removed.
    assert observed, "select must resolve agent metadata"
    assert all(call for call in observed), observed


def test_detail_emits_timing_with_secondary_flag(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    created = session_service.create_chat_session(title="Detail probe", lightweight=True)
    events = _capture_scene_events(monkeypatch)

    session_service.get_session_detail(created["id"], include_secondary=False)

    samples = _switch_events(events, "conversation.session.detail.timing")
    assert len(samples) == 1
    sample = samples[0]
    assert sample["includeSecondary"] is False
    assert sample["sessionId"] == created["id"]
    stage = sample["stageDurationsMs"]
    for key in ("rowReadMs", "agentLookupMs", "reconcileMs", "projectionMs"):
        assert key in stage, key
        assert isinstance(stage[key], int), key
        assert stage[key] >= 0, key
