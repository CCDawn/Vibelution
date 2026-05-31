from core.web.services import session_service


def test_hidden_missing_agent_session_index_event_is_control_signal(monkeypatch):
    events = []
    monkeypatch.setattr(session_service, "PROJECT_ROOT", session_service.PROJECT_ROOT)
    monkeypatch.setattr(session_service, "record_runtime_scene_event", lambda *args, **kwargs: events.append((args, kwargs)))
    session_service._SESSION_MISSING_INDEX_EVENT_KEYS.clear()

    session_service._record_session_agent_missing_index_event(
        {
            "id": "session-a",
            "agentId": "agent-missing",
            "agentStatusCode": "missing_agent",
            "agentStatusMessage": "缺少有效 Agent",
        },
        source="list_sessions",
    )

    assert events
    args, kwargs = events[-1]
    assert args[:3] == ("conversation", "session_agent_missing", "session.agent_missing.hidden_from_index")
    assert kwargs["level"] == "info"
    assert kwargs["outcome"] == "hidden_control"
    assert kwargs["fields"]["hiddenFromIndex"] is True
    assert kwargs["child_log_payload"]["hidden_from_index"] is True
    assert kwargs["child_log_payload"]["control_signal"] is True
