from core.web.services import session_service


def test_targeted_lookup_projects_only_bound_and_direct_candidates(monkeypatch):
    records = [
        {"agentId": "unrelated", "directSessionId": "elsewhere"},
        {"agentId": "bound", "directSessionId": "parent", "status": "archived"},
        {"agentId": "collision", "directSessionId": "target"},
    ]
    observed = []
    projected = []
    monkeypatch.setattr(session_service, "_sync_agent_directory_project_root", lambda: None)
    monkeypatch.setattr(session_service.agent_directory_service, "load_state", lambda: (_ for _ in ()).throw(AssertionError("full registry copy")))

    def selected(**kwargs):
        observed.append(kwargs)
        return [row for row in records if row["agentId"] in kwargs["agent_ids"] or row["directSessionId"] in kwargs["direct_session_ids"]]

    def project(row, **kwargs):
        projected.append((row["agentId"], id(kwargs["avatar_url_cache"])))
        return dict(row)

    monkeypatch.setattr(session_service.agent_directory_service, "load_agent_records", selected)
    monkeypatch.setattr(session_service, "_conversation_agent_from_state", project)
    result = session_service._agent_lookup_for_conversations(session_id="target", agent_ids=("bound",))
    assert list(result) == ["bound", "collision"]
    assert result["bound"]["status"] == "archived"
    assert observed == [{"agent_ids": ("bound",), "direct_session_ids": ("target",)}]
    assert [item[0] for item in projected] == ["bound", "collision"]
    assert len({item[1] for item in projected}) == 1


def test_unscoped_lookup_keeps_complete_registry_projection(monkeypatch):
    records = [{"agentId": "first"}, {"agentId": "second"}]
    monkeypatch.setattr(session_service, "_sync_agent_directory_project_root", lambda: None)
    monkeypatch.setattr(session_service.agent_directory_service, "load_state", lambda: {"agents": records})
    monkeypatch.setattr(session_service.agent_directory_service, "load_agent_records", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected scoped lookup")))
    monkeypatch.setattr(session_service, "_conversation_agent_from_state", lambda row, **_kwargs: dict(row))
    assert list(session_service._agent_lookup_for_conversations()) == ["first", "second"]


def test_direct_only_identity_keeps_full_lookup_last_record_semantics(monkeypatch):
    from core.web.services.agent_directory import repair_store

    records = [
        {"agentId": "collision", "directSessionId": "target", "status": "active"},
        {"agentId": "unrelated", "directSessionId": "elsewhere", "status": "active"},
        {"agentId": "collision", "directSessionId": "other", "status": "archived"},
    ]
    monkeypatch.setattr(session_service, "_sync_agent_directory_project_root", lambda: None)
    monkeypatch.setattr(repair_store, "_load_state_snapshot_locked", lambda: {"agents": records})
    monkeypatch.setattr(session_service.agent_directory_service, "load_state", lambda: {"agents": records})
    monkeypatch.setattr(session_service, "_conversation_agent_from_state", lambda row, **_kwargs: dict(row))

    full = session_service._agent_lookup_for_conversations()
    targeted = session_service._agent_lookup_for_conversations(session_id="target", agent_ids=("missing",))

    assert list(targeted) == ["collision"]
    assert targeted["collision"] == full["collision"]
    assert targeted["collision"]["status"] == "archived"
    assert targeted["collision"]["directSessionId"] == "other"
