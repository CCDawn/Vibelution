from core.orchestration.round_state import RoundStateController
from core.web.services import session_service


def test_round_state_separates_ui_status_from_runtime_telemetry():
    state = RoundStateController(max_iterations=4)
    state.next_iteration()
    state.note_response_tools(1, "")

    ui_status = state.thinking_status("demo")
    telemetry = state.runtime_telemetry()

    assert ui_status["goal"] == "demo"
    assert "tool_only_steps" not in ui_status
    assert telemetry["consecutive_tool_only_steps"] == 1


def test_chat_turn_subpackage_log_path_is_session_and_turn_scoped():
    path = session_service._conversation_turn_log_path(
        "session:demo",
        "turn/demo",
        "trace_events.jsonl",
    )

    assert path.startswith("conversations/session-demo-")
    assert "/turn-demo-" in path
    assert path.endswith("/trace_events.jsonl")


def test_chat_turn_trace_event_writes_lifecycle_subpackage(monkeypatch):
    recorded: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded.append((args, kwargs)) or {"accepted": True, "path": kwargs.get("child_log_path")},
    )

    session_service._record_session_turn_trace_event(
        "session-live",
        "session-live-20260526120522497070",
        "mental",
        {"summary": "stable"},
        status="completed",
        summary="Mental model trace captured.",
    )

    assert recorded
    args, kwargs = recorded[0]
    assert args[:3] == ("conversation", "turn_trace_mental", "conversation.turn.trace.mental")
    assert kwargs["child_log_path"] == (
        "conversations/session-live/session-live-20260526120522497070/trace_events.jsonl"
    )
    assert kwargs["child_log_payload"]["kind"] == "mental"
    assert kwargs["child_log_payload"]["status"] == "completed"
    assert kwargs["lifecycle"] is True


def test_chat_turn_execution_registry_records_entry_type(monkeypatch):
    recorded: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded.append((args, kwargs)) or {"accepted": True, "path": kwargs.get("child_log_path")},
    )

    session_service._record_session_execution_registry_event(
        "session-live",
        "turn-1",
        "llm_turn",
        "running",
        details={"turnIndex": 1},
    )

    assert recorded
    _args, kwargs = recorded[0]
    assert kwargs["child_log_path"] == "conversations/session-live/turn-1/execution_registry.jsonl"
    assert kwargs["child_log_payload"]["entry_type"] == "llm_turn"
    assert kwargs["child_log_payload"]["status"] == "running"
    assert kwargs["child_log_payload"]["details"] == {"turnIndex": 1}
