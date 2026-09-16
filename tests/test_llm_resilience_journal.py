"""Session Journal authority for LLM resilience events.

The old in-memory ``route_fallback_registry`` lost every recorded switch on
process restart. ``llm_resilience`` journal events are the durable authority:
one sibling event per attempt, written synchronously at decision time, read
back by the turn DTO projection. Covered here: stage mapping, payload shape
per stage, attempt-as-sibling semantics, exact-turn projection (no
mislabelling), restart survival, post-terminal write immunity, unknown
schema forward compatibility, and the binding-layer scene-event mirror gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.chat.llm_resilience_journal import (
    DEFAULT_PROJECT_ROOT,
    EVENT_LLM_RESILIENCE,
    RESILIENCE_SCHEMA,
    latest_route_fallback_from_events,
    record_llm_resilience_event,
    record_llm_resilience_from_scene_event,
    resilience_events_for_turn,
    resilience_stage_for_scene_event,
)
from core.chat.turn_journal import (
    EVENT_TOOL_RESULT,
    EVENT_TURN_COMPLETED,
    EVENT_TURN_STARTED,
    TurnJournalPostTerminalWriteError,
    append_turn_event,
    load_turn_events,
)
from core.infrastructure import developer_sandbox


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)


_FALLBACK_FIELDS = {
    "sessionId": "sess-res",
    "turnId": "turn-1",
    "from": "primary",
    "to": "backup_qwen",
    "errorCategory": "server_error",
    "routeId": "route-primary",
}


def _session_events(session_id: str) -> list:
    return load_turn_events(DEFAULT_PROJECT_ROOT, session_id)


def test_scene_event_stage_mapping():
    assert resilience_stage_for_scene_event("llm_route_fallback_switched") == "fallback_switch"
    assert resilience_stage_for_scene_event("llm_route_degraded_retry") == "degraded_retry"
    assert resilience_stage_for_scene_event("answer_channel_leak_detected") == "answer_channel_leak"
    assert resilience_stage_for_scene_event("conversation.turn.stuck_loop_detected") == "stuck_detected"
    assert resilience_stage_for_scene_event("llm_route_attempt_exhausted") == ""
    assert resilience_stage_for_scene_event("") == ""


def test_record_fallback_switch_payload_shape():
    event = record_llm_resilience_event(
        None, "sess-res", "turn-1", stage="fallback_switch", attempt=2, fields=_FALLBACK_FIELDS
    )
    assert event is not None
    assert event.event_type == EVENT_LLM_RESILIENCE
    assert event.visible_in_model is False
    assert event.status == "fallback_switch"
    assert event.payload["schema"] == RESILIENCE_SCHEMA
    assert event.payload["stage"] == "fallback_switch"
    assert event.payload["attempt"] == 2
    assert event.payload["fromProfileId"] == "primary"
    assert event.payload["toProfileId"] == "backup_qwen"
    assert event.payload["errorCategory"] == "server_error"
    assert event.payload["routeId"] == "route-primary"


def test_record_degraded_retry_keeps_action_and_category():
    event = record_llm_resilience_event(
        None,
        "sess-res",
        "turn-1",
        stage="degraded_retry",
        attempt=2,
        fields={
            "action": "retry_without_streaming",
            "fromCategory": "empty_content_error",
            "errorCategory": "empty_content_error",
            "routeId": "route-primary",
        },
    )
    assert event.payload["action"] == "retry_without_streaming"
    assert event.payload["errorCategory"] == "empty_content_error"


def test_record_answer_channel_leak_bounds_extras():
    event = record_llm_resilience_event(
        None,
        "sess-res",
        "turn-1",
        stage="answer_channel_leak",
        fields={
            "leakRecovered": True,
            "leakRetried": True,
            "leakMarkers": [f"marker-{index}" for index in range(12)],
            "leakTriggeredBy": ["reasoning"],
            "outcomeKind": "final_answer",
        },
    )
    assert event.payload["leakRecovered"] is True
    assert event.payload["leakRetried"] is True
    assert len(event.payload["leakMarkers"]) == 8
    assert event.payload["leakTriggeredBy"] == ["reasoning"]
    assert event.payload["outcomeKind"] == "final_answer"


def test_record_stuck_detected_bounds_evidence():
    event = record_llm_resilience_event(
        None,
        "sess-res",
        "turn-1",
        stage="stuck_detected",
        fields={
            "stuckPattern": "repeated_action_error",
            "stuckTool": "apply_patch_tool",
            "stuckRepeatCount": 3,
            "stuckEvidence": "x" * 900,
            "reason": "stuck_loop_detected",
        },
    )
    assert event.payload["stuckPattern"] == "repeated_action_error"
    assert event.payload["stuckTool"] == "apply_patch_tool"
    assert event.payload["stuckRepeatCount"] == 3
    assert len(event.payload["stuckEvidence"]) == 500
    assert event.payload["reason"] == "stuck_loop_detected"


def test_attempts_are_sibling_events_and_latest_switch_wins():
    record_llm_resilience_event(
        None, "sess-res", "turn-1", stage="fallback_switch", attempt=1, fields=_FALLBACK_FIELDS
    )
    record_llm_resilience_event(
        None,
        "sess-res",
        "turn-1",
        stage="degraded_retry",
        attempt=2,
        fields={"action": "retry_without_tools", "errorCategory": "tool_protocol_error"},
    )
    second = record_llm_resilience_event(
        None,
        "sess-res",
        "turn-1",
        stage="fallback_switch",
        attempt=3,
        fields={**_FALLBACK_FIELDS, "to": "backup_glm"},
    )

    events = resilience_events_for_turn(_session_events("sess-res"), turn_id="turn-1")
    assert [event.payload["attempt"] for event in events] == [1, 2, 3]
    assert events[-1].event_id == second.event_id
    assert latest_route_fallback_from_events(events, turn_id="turn-1") == {
        "from": "primary",
        "to": "backup_glm",
    }


def test_projection_does_not_mislabel_turns_or_sessions():
    record_llm_resilience_event(
        None, "sess-a", "turn-1", stage="fallback_switch", fields=_FALLBACK_FIELDS
    )

    events_a = _session_events("sess-a")
    # Exact turn wins.
    assert latest_route_fallback_from_events(events_a, turn_id="turn-1") == {
        "from": "primary",
        "to": "backup_qwen",
    }
    # A turn that never switched must not inherit an older turn's entry.
    assert latest_route_fallback_from_events(events_a, turn_id="turn-2") is None
    # Without a turn id, the session's latest switch stays visible.
    assert latest_route_fallback_from_events(events_a) == {"from": "primary", "to": "backup_qwen"}
    # Another session sees nothing.
    assert latest_route_fallback_from_events(_session_events("sess-b")) is None
    # Same-profile "switches" are never projected.
    record_llm_resilience_event(
        None,
        "sess-a",
        "turn-3",
        stage="fallback_switch",
        fields={**_FALLBACK_FIELDS, "from": "backup_qwen", "to": "backup_qwen"},
    )
    assert latest_route_fallback_from_events(events_a, turn_id="turn-3") is None


def test_resilience_write_after_terminal_event_does_not_raise():
    append_turn_event(DEFAULT_PROJECT_ROOT, "sess-term", "turn-9", EVENT_TURN_COMPLETED)
    event = record_llm_resilience_event(
        None, "sess-term", "turn-9", stage="fallback_switch", fields=_FALLBACK_FIELDS
    )
    assert event is not None
    assert latest_route_fallback_from_events(
        _session_events("sess-term"), turn_id="turn-9"
    ) == {"from": "primary", "to": "backup_qwen"}


def test_unknown_schema_version_is_forward_compatible():
    record_llm_resilience_event(
        None, "sess-fwd", "turn-1", stage="fallback_switch", fields=_FALLBACK_FIELDS
    )
    # A future writer bumps the schema and renames the stage: the v1 reader
    # must skip it without crashing and keep returning the v1 record.
    append_turn_event(
        DEFAULT_PROJECT_ROOT,
        "sess-fwd",
        "turn-1",
        EVENT_LLM_RESILIENCE,
        status="fallback_switch",
        payload={"schema": "llm_resilience.v2", "stage": "fallback_switch", "fromProfileId": "a", "toProfileId": "b"},
        visible_in_model=False,
    )
    append_turn_event(
        DEFAULT_PROJECT_ROOT,
        "sess-fwd",
        "turn-1",
        EVENT_LLM_RESILIENCE,
        status="future_stage",
        payload={"schema": RESILIENCE_SCHEMA, "stage": "future_stage"},
        visible_in_model=False,
    )
    events = _session_events("sess-fwd")
    assert latest_route_fallback_from_events(events, turn_id="turn-1") == {
        "from": "primary",
        "to": "backup_qwen",
    }


def test_fallback_switch_survives_cache_reset_and_is_fsynced_on_disk():
    from core.web.services.session import signals_format
    from core.web.services.session.journal_bridge import (
        invalidate_session_conversation_events_cache,
    )

    # Write and read through the exact same project root the session service
    # resolves, so the assertion targets the authority the DTO reader uses.
    root = Path(str(signals_format._service().PROJECT_ROOT))
    record_llm_resilience_event(
        root, "sess-restart", "turn-live", stage="fallback_switch", fields=_FALLBACK_FIELDS
    )

    events = load_turn_events(root, "sess-restart")
    persisted = [
        event
        for event in events
        if event.event_type == EVENT_LLM_RESILIENCE and event.payload.get("stage") == "fallback_switch"
    ]
    assert len(persisted) == 1
    assert persisted[0].visible_in_model is False
    assert persisted[0].payload["schema"] == RESILIENCE_SCHEMA
    assert persisted[0].payload["fromProfileId"] == "primary"

    # Simulate a fresh process: the session events cache is gone, the read
    # must come back from the durable journal.
    invalidate_session_conversation_events_cache("sess-restart")
    assert signals_format._current_session_route_fallback("sess-restart", "turn-live") == {
        "from": "primary",
        "to": "backup_qwen",
    }


def test_scene_mirror_requires_journal_backed_session():
    # No sessionId/turnId (CLI surfaces): scene-only, no journal write.
    assert (
        record_llm_resilience_from_scene_event(
            "llm_route_fallback_switched", fields={"from": "a", "to": "b"}
        )
        is None
    )
    # Journal-backed session without a journal file yet (turn_started has not
    # been committed): still scene-only.
    assert (
        record_llm_resilience_from_scene_event(
            "llm_route_fallback_switched",
            fields={**_FALLBACK_FIELDS, "sessionId": "sess-nojournal", "turnId": "turn-1"},
        )
        is None
    )
    assert latest_route_fallback_from_events(_session_events("sess-nojournal")) is None


def test_scene_mirror_writes_journal_once_journal_exists():
    root = Path(DEFAULT_PROJECT_ROOT)
    append_turn_event(root, "sess-mirror", "turn-7", EVENT_TURN_STARTED, visible_in_model=False)

    event = record_llm_resilience_from_scene_event(
        "llm_route_fallback_switched",
        fields={**_FALLBACK_FIELDS, "sessionId": "sess-mirror", "turnId": "turn-7", "attempt": 1},
    )
    assert event is not None
    assert event.payload["stage"] == "fallback_switch"
    assert event.payload["attempt"] == 1
    # Unmapped scene events are ignored.
    assert (
        record_llm_resilience_from_scene_event(
            "agent.turn.failed", fields={"sessionId": "sess-mirror", "turnId": "turn-7"}
        )
        is None
    )
    assert latest_route_fallback_from_events(
        load_turn_events(root, "sess-mirror"), turn_id="turn-7"
    ) == {"from": "primary", "to": "backup_qwen"}


def test_binding_layer_mirrors_without_breaking_scene_event(monkeypatch):
    from core.orchestration import agent_runtime_bindings

    scene_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "core.web.services.runtime_scene_service.record_runtime_scene_event",
        lambda _source, phase, event_code, **_kwargs: scene_calls.append((phase, event_code)),
    )

    root = Path(DEFAULT_PROJECT_ROOT)
    append_turn_event(root, "sess-funnel", "turn-2", EVENT_TURN_STARTED, visible_in_model=False)

    agent_runtime_bindings._record_agent_scene_event(
        "llm_route",
        "llm_route_fallback_switched",
        message="switching",
        fields={**_FALLBACK_FIELDS, "sessionId": "sess-funnel", "turnId": "turn-2"},
        level="warning",
        outcome="switched",
    )
    assert scene_calls == [("llm_route", "llm_route_fallback_switched")]
    events = load_turn_events(root, "sess-funnel")
    assert latest_route_fallback_from_events(events, turn_id="turn-2") == {
        "from": "primary",
        "to": "backup_qwen",
    }


def test_post_terminal_guard_only_protects_model_visible_types():
    root = Path(DEFAULT_PROJECT_ROOT)
    append_turn_event(root, "sess-guard", "turn-3", EVENT_TURN_COMPLETED)
    with pytest.raises(TurnJournalPostTerminalWriteError):
        append_turn_event(root, "sess-guard", "turn-3", EVENT_TOOL_RESULT)
    # llm_resilience is not model-visible: late resilience writes degrade to
    # a normal sibling append instead of failing the settled turn.
    event = record_llm_resilience_event(
        None, "sess-guard", "turn-3", stage="answer_channel_leak", fields={"leakRetried": True}
    )
    assert event is not None
