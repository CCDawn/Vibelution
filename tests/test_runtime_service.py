from core.web.services import runtime_service


def test_work_run_summary_includes_source_collection_active_item(monkeypatch):
    source_active = {
        "runId": "dprun-source-live",
        "runKind": "source_collection_run",
        "status": "running",
        "currentPhase": "searching",
        "summary": "正在执行资料搜集。",
    }

    monkeypatch.setattr(
        runtime_service,
        "load_chat_turn_work_run_summary",
        lambda: {"active": None, "latest": None, "activeItems": []},
    )
    monkeypatch.setattr(
        runtime_service,
        "_safe_load_chat_room_work_run_summary",
        lambda: {"active": None, "latest": None},
    )
    monkeypatch.setattr(
        runtime_service,
        "_safe_load_source_collection_work_run_summary",
        lambda: {"active": source_active, "latest": source_active, "activeItems": [source_active]},
    )
    monkeypatch.setattr(runtime_service, "_safe_load_evolution_work_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime_service, "_safe_load_supervised_worktree_work_run", lambda *args, **kwargs: None)

    summary = runtime_service._work_run_summary()
    active_runs = runtime_service._active_work_runs(summary)

    assert summary["active"]["source_collection_run"] == source_active
    assert summary["latest"]["source_collection_run"] == source_active
    assert summary["activeItems"]["source_collection_run"] == [source_active]
    assert active_runs == [
        {
            "kind": "source_collection_run",
            "runId": "dprun-source-live",
            "status": "running",
            "sessionId": "",
        }
    ]


def test_work_run_summary_degrades_when_chat_turn_summary_fails(monkeypatch):
    def fail_chat_turn_summary():
        raise RuntimeError("session index is blocked")

    monkeypatch.setattr(runtime_service, "load_chat_turn_work_run_summary", fail_chat_turn_summary)
    monkeypatch.setattr(
        runtime_service,
        "_safe_load_chat_room_work_run_summary",
        lambda: {"active": None, "latest": None},
    )
    monkeypatch.setattr(
        runtime_service,
        "_safe_load_source_collection_work_run_summary",
        lambda: {"active": None, "latest": None, "activeItems": []},
    )
    monkeypatch.setattr(runtime_service, "_safe_load_evolution_work_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime_service, "_safe_load_supervised_worktree_work_run", lambda *args, **kwargs: None)

    summary = runtime_service._work_run_summary()

    assert summary["active"]["chat_turn"] is None
    assert summary["latest"]["chat_turn"] is None
    assert summary["activeItems"]["chat_turn"] == []
