from core.web.services import evolution_service


def _install_dashboard_cache_fixtures(monkeypatch, tmp_path, now, calls):
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(evolution_service, "get_web_language", lambda: "zh")
    monkeypatch.setattr(evolution_service.time, "monotonic", lambda: now["value"])
    monkeypatch.setattr(evolution_service, "load_workbench_state", lambda _root: {})
    monkeypatch.setattr(
        evolution_service,
        "list_dataset_status",
        lambda _root, include_environment_preflight=False: [],
    )
    monkeypatch.setattr(
        evolution_service,
        "get_workbench_contract",
        lambda: {
            "intakeMode": "manual_review",
            "modeAvailability": {
                "self_evolution": False,
                "supervised_evolution": True,
            },
        },
    )

    def fake_load_dashboard_records(*, project_root, limit):
        calls.append((project_root, limit))
        return [], 0

    monkeypatch.setattr(evolution_service, "load_dashboard_records", fake_load_dashboard_records)
    evolution_service.invalidate_evolution_workspace_dashboard_cache()


def test_evolution_workspace_dashboard_reuses_cached_payload_until_ttl(tmp_path, monkeypatch):
    now = {"value": 10.0}
    calls = []
    _install_dashboard_cache_fixtures(monkeypatch, tmp_path, now, calls)

    first = evolution_service.get_evolution_workspace_dashboard()
    second = evolution_service.get_evolution_workspace_dashboard()

    assert first == second
    assert len(calls) == 1

    first["runs"].append({"id": "mutated"})
    third = evolution_service.get_evolution_workspace_dashboard()
    assert third["runs"] == []
    assert len(calls) == 1

    now["value"] += evolution_service.EVOLUTION_WORKSPACE_DASHBOARD_CACHE_TTL_SECONDS + 0.1
    evolution_service.get_evolution_workspace_dashboard()
    assert len(calls) == 2


def test_evolution_workspace_dashboard_cache_can_be_invalidated(tmp_path, monkeypatch):
    now = {"value": 20.0}
    calls = []
    _install_dashboard_cache_fixtures(monkeypatch, tmp_path, now, calls)

    evolution_service.get_evolution_workspace_dashboard()
    evolution_service.invalidate_evolution_workspace_dashboard_cache()
    evolution_service.get_evolution_workspace_dashboard()

    assert len(calls) == 2
