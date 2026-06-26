from core.chat.conversation_ledger import append_conversation_event
from core.web.services import session_service


def test_cached_session_conversation_events_reuses_matching_signature(tmp_path, monkeypatch):
    session_id = "session-cache-hit"
    append_conversation_event(
        tmp_path,
        session_id,
        "turn-1",
        session_service.EVENT_USER_MESSAGE,
        payload={"content": "first"},
        source="test",
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    original_load = session_service.load_conversation_events
    load_calls = 0

    def load_spy(project_root, requested_session_id):
        nonlocal load_calls
        load_calls += 1
        return original_load(project_root, requested_session_id)

    monkeypatch.setattr(session_service, "load_conversation_events", load_spy)

    first = session_service._load_session_conversation_events_cached(session_id)
    second = session_service._load_session_conversation_events_cached(session_id)

    assert [event.event_id for event in first] == [event.event_id for event in second]
    assert first is not second
    assert load_calls == 1


def test_cached_session_conversation_events_invalidates_after_session_append(tmp_path, monkeypatch):
    session_id = "session-cache-invalidate"
    append_conversation_event(
        tmp_path,
        session_id,
        "turn-1",
        session_service.EVENT_USER_MESSAGE,
        payload={"content": "first"},
        source="test",
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    original_load = session_service.load_conversation_events
    load_calls = 0

    def load_spy(project_root, requested_session_id):
        nonlocal load_calls
        load_calls += 1
        return original_load(project_root, requested_session_id)

    monkeypatch.setattr(session_service, "load_conversation_events", load_spy)

    before = session_service._load_session_conversation_events_cached(session_id)
    session_service._append_session_conversation_event(
        session_id,
        "turn-2",
        session_service.EVENT_USER_MESSAGE,
        payload={"content": "second"},
        source="test",
    )
    after = session_service._load_session_conversation_events_cached(session_id)

    assert len(before) == 1
    assert len(after) == 2
    assert [event.sequence for event in after] == [1, 2]
    assert load_calls == 2
