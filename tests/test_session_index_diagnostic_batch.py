from concurrent.futures import ThreadPoolExecutor

from core.web.services import runtime_scene_service, session_service


def _entries(count):
    return [({
        "agentId": f"agent-{index}", "agentCode": f"A{index}",
        "primaryMode": "chat", "roleKey": "", "promptTemplateId": "prompt-chat-default",
    }, f"session-{index}") for index in range(count)]


def _capture(monkeypatch, tmp_path):
    captured = []
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_AGENT_DIRECTORY_INDEX_EVENT_KEYS", set())
    monkeypatch.setattr(session_service, "record_runtime_scene_event", lambda *args, **kwargs: captured.append((args, kwargs)))
    return captured


def _normalized_rows(events):
    result = []
    for args, kwargs in events:
        fields = runtime_scene_service._normalize_telemetry_fields(kwargs["fields"])
        if args[2].endswith(".batch"):
            assert len(fields["indexedSessions"]) == fields["indexedCount"]
            result.extend(fields["indexedSessions"])
        else:
            result.append(fields)
    return result


def _identities(events):
    return [(row["sessionId"], row["agentId"]) for row in _normalized_rows(events)]


def test_index_diagnostics_batch_all_identities_with_bounded_scene_writes(monkeypatch, tmp_path):
    captured = _capture(monkeypatch, tmp_path)
    entries = _entries(45)
    session_service._record_agent_directory_conversation_index_events(entries)
    assert len(captured) == 3
    assert _normalized_rows(captured) == [{"sessionId": session, **agent} for agent, session in entries]
    assert all(event[1]["lifecycle"] for event in captured)
    session_service._record_agent_directory_conversation_index_events(entries)
    assert len(captured) == 3


def test_index_diagnostics_retains_single_event_and_new_identity_after_dedupe(monkeypatch, tmp_path):
    captured = _capture(monkeypatch, tmp_path)
    entries = _entries(3)
    session_service._record_agent_directory_conversation_index_event(entries[0][0], session_id=entries[0][1])
    assert captured[0][0][2] == "session.agent_directory_index_added"
    assert captured[0][1]["fields"] == {"sessionId": "session-0", **entries[0][0]}
    session_service._record_agent_directory_conversation_index_events([*entries, entries[0]])
    assert _identities(captured) == [(session, agent["agentId"]) for agent, session in entries]
    # The same Agent bound to a different session remains a distinct identity.
    session_service._record_agent_directory_conversation_index_events([(entries[0][0], "rebound")])
    assert _identities(captured)[-1] == ("rebound", "agent-0")


def test_index_diagnostics_deduplicates_concurrent_queries(monkeypatch, tmp_path):
    captured = _capture(monkeypatch, tmp_path)
    entries = _entries(30)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(session_service._record_agent_directory_conversation_index_events, [entries] * 4))
    identities = _identities(captured)
    assert len(identities) == len(set(identities)) == 30


def test_index_diagnostic_failure_does_not_abort_later_batches(monkeypatch, tmp_path):
    captured = _capture(monkeypatch, tmp_path)

    def record(*args, **kwargs):
        if kwargs["fields"].get("indexedSessions", [{}])[0].get("agentId") == "agent-0":
            raise OSError("diagnostic write unavailable")
        captured.append((args, kwargs))

    monkeypatch.setattr(session_service, "record_runtime_scene_event", record)
    session_service._record_agent_directory_conversation_index_events(_entries(20))
    assert len(captured) == 1
    assert _identities(captured) == [(f"session-{index}", f"agent-{index}") for index in range(16, 20)]
