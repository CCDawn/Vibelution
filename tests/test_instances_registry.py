import json

import pytest

from core.runtime_manager import instances_registry as registry


@pytest.fixture
def registry_path(tmp_path, monkeypatch):
    path = tmp_path / "Vibelution" / "instances.json"
    monkeypatch.setattr(registry, "instances_registry_path", lambda: path)
    return path


def test_load_registry_missing_file_returns_empty(registry_path):
    assert registry.load_registry() == registry.empty_registry()


def test_load_registry_corrupt_file_returns_empty(registry_path):
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text("{not json", encoding="utf-8")
    assert registry.load_registry() == registry.empty_registry()


def test_upsert_and_list_roundtrip(registry_path):
    registry.upsert_instance("vibelution--main", projectRoot="C:/repo/main", port=8000)
    registry.upsert_instance("vibelution--chat", projectRoot="C:/repo/chat", port=8001, status="running")

    instances = registry.list_instances()
    assert [i["instanceId"] for i in instances] == ["vibelution--chat", "vibelution--main"]
    assert {i["port"] for i in instances} == {8000, 8001}

    registry.upsert_instance("vibelution--main", status="running")
    entry = registry.get_instance("vibelution--main")
    assert entry["projectRoot"] == "C:/repo/main"
    assert entry["status"] == "running"
    assert entry["port"] == 8000


def test_release_instance(registry_path):
    registry.upsert_instance("vibelution--main", port=8000)
    removed = registry.release_instance("vibelution--main")
    assert removed["port"] == 8000
    assert registry.get_instance("vibelution--main") == {}
    assert registry.release_instance("missing") == {}


def test_allocate_prefers_free_port(registry_path, monkeypatch):
    monkeypatch.setattr(registry, "_port_is_free", lambda port, host: True)
    assert registry.allocate_backend_port("a", 8000) == 8000
    assert registry.get_instance("a")["port"] == 8000


def test_allocate_skips_occupied_and_registered_ports(registry_path, monkeypatch):
    busy = {8000, 8002}
    monkeypatch.setattr(registry, "_port_is_free", lambda port, host: int(port) not in busy)
    registry.upsert_instance("other", port=8001)

    assert registry.allocate_backend_port("a", 8000) == 8003
    assert registry.get_instance("a")["port"] == 8003
    assert registry.get_instance("other")["port"] == 8001


def test_allocate_reuses_own_port(registry_path, monkeypatch):
    monkeypatch.setattr(registry, "_port_is_free", lambda port, host: True)
    registry.upsert_instance("a", port=8004, controlPort=8768)
    assert registry.allocate_backend_port("a", 8000) == 8004


def test_allocate_records_chosen_port_before_return(registry_path, monkeypatch):
    def fake_free(port, host):
        return True

    monkeypatch.setattr(registry, "_port_is_free", fake_free)
    registry.allocate_backend_port("a", 8000)
    assert registry.get_instance("a")["port"] == 8000


def test_allocate_exhaustion_raises(registry_path, monkeypatch):
    monkeypatch.setattr(registry, "_port_is_free", lambda port, host: False)
    with pytest.raises(RuntimeError, match="No free backend port"):
        registry.allocate_backend_port("a", 8000)


def test_allocate_instance_ports_keeps_backend_and_control_disjoint(registry_path, monkeypatch):
    monkeypatch.setattr(registry, "_port_is_free", lambda port, host: True)
    registry.upsert_instance("other", port=8000, controlPort=8765)

    backend, control = registry.allocate_instance_ports("worktree:task")

    assert backend == 8001
    assert control == 8766
    entry = registry.get_instance("worktree:task")
    assert entry["port"] == 8001
    assert entry["controlPort"] == 8766


def test_allocate_control_skips_backend_port(registry_path, monkeypatch):
    monkeypatch.setattr(registry, "_port_is_free", lambda port, host: True)
    backend, control = registry.allocate_instance_ports(
        "a",
        preferred_backend=8000,
        preferred_control=8000,
    )
    assert backend == 8000
    assert control == 8001


def test_save_is_atomic_and_keeps_payload(registry_path):
    registry.upsert_instance("a", port=8000)
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    assert payload["schemaVersion"] == registry.REGISTRY_SCHEMA_VERSION
    assert payload["instances"]["a"]["port"] == 8000
    assert list(registry_path.parent.glob(".instances.json.*")) == []


def test_empty_instance_id_rejected():
    with pytest.raises(ValueError):
        registry.upsert_instance("  ")
