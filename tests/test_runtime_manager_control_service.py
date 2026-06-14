from pathlib import Path

import pytest

from core.web.services import runtime_manager_control_service as service

pytestmark = pytest.mark.serial


def test_runtime_manager_live_control_uses_short_ttl_cache(monkeypatch, tmp_path):
    service.reset_runtime_manager_live_control_cache()
    monkeypatch.setattr(service, "RUNTIME_MANAGER_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(service, "load_pid", lambda: 1234)
    monkeypatch.setattr(service, "record_runtime_scene_event", lambda *args, **kwargs: None)
    process_checks: list[int] = []

    def fake_is_process_alive(pid: int) -> bool:
        process_checks.append(pid)
        return True

    monkeypatch.setattr(service, "_is_process_alive", fake_is_process_alive)

    assert service.runtime_manager_live_control_enabled(tmp_path) is True
    assert service.runtime_manager_live_control_enabled(tmp_path) is True

    assert process_checks == [1234]


def test_runtime_manager_live_control_rechecks_after_cache_expiry(monkeypatch, tmp_path):
    service.reset_runtime_manager_live_control_cache()
    monkeypatch.setattr(service, "RUNTIME_MANAGER_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(service, "load_pid", lambda: 1234)
    monkeypatch.setattr(service, "record_runtime_scene_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "LIVE_CONTROL_CACHE_TTL_SECONDS", 1.0)
    monotonic_values = iter([10.0, 10.5, 12.0])
    monkeypatch.setattr(service.time, "monotonic", lambda: next(monotonic_values))
    process_checks: list[int] = []

    def fake_is_process_alive(pid: int) -> bool:
        process_checks.append(pid)
        return True

    monkeypatch.setattr(service, "_is_process_alive", fake_is_process_alive)

    assert service.runtime_manager_live_control_enabled(tmp_path) is True
    assert service.runtime_manager_live_control_enabled(tmp_path) is True
    assert service.runtime_manager_live_control_enabled(tmp_path) is True

    assert process_checks == [1234, 1234]


def test_runtime_manager_live_control_requires_matching_project_root(monkeypatch, tmp_path):
    service.reset_runtime_manager_live_control_cache()
    project_root = tmp_path / "project"
    manager_root = tmp_path / "other"
    project_root.mkdir()
    manager_root.mkdir()
    monkeypatch.setattr(service, "RUNTIME_MANAGER_PROJECT_ROOT", manager_root)
    monkeypatch.setattr(service, "load_pid", lambda: 1234)
    monkeypatch.setattr(service, "record_runtime_scene_event", lambda *args, **kwargs: None)
    process_checks: list[int] = []
    monkeypatch.setattr(service, "_is_process_alive", lambda pid: process_checks.append(pid) or True)

    assert service.runtime_manager_live_control_enabled(Path(project_root)) is False

    assert process_checks == []
