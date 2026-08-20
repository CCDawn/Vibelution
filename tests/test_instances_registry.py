import json
import os
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from core.runtime_manager import instances_registry as registry
from core.runtime_manager import process_identity


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


def test_allocate_instance_ports_writes_once(registry_path, monkeypatch):
    monkeypatch.setattr(registry, "_port_is_free", lambda port, host: True)
    writes: list[int] = []
    original = registry.save_registry

    def counted(payload):
        writes.append(1)
        return original(payload)

    monkeypatch.setattr(registry, "save_registry", counted)
    registry.allocate_instance_ports("worktree:task")
    assert writes == [1]


def test_concurrent_allocate_instance_ports_are_disjoint(registry_path, monkeypatch):
    monkeypatch.setattr(registry, "_port_is_free", lambda port, host: True)
    results: list[tuple[int, int]] = []

    def worker(instance_id: str) -> None:
        results.append(registry.allocate_instance_ports(instance_id))

    threads = [
        __import__("threading").Thread(target=worker, args=(f"worktree:{index}",))
        for index in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    backends = [item[0] for item in results]
    controls = [item[1] for item in results]
    assert len(set(backends + controls)) == 16


def test_process_identity_detects_pid_reuse():
    class ReusedProcess:
        def create_time(self):
            return 200.0

        def exe(self):
            return "C:/Python/pythonw.exe"

    result = process_identity.inspect_process_identity(
        {"pid": 42, "createTime": 100.0, "executable": "C:/Python/pythonw.exe"},
        process_factory=lambda _pid: ReusedProcess(),
    )

    assert result["status"] == "mismatch"
    assert result["reason"] == "create_time_mismatch"


def test_upsert_migrates_schema_and_captures_owner_identity(registry_path, monkeypatch):
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps({"schemaVersion": 1, "instances": {"legacy": {"port": 8000}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        registry,
        "capture_process_identity",
        lambda pid: {"pid": pid, "createTime": 123.5, "executable": "C:/Python/pythonw.exe"},
    )

    registry.upsert_instance(
        "worktree:new",
        spawnPid=4321,
        generation=7,
        commandId="cmd-7",
        deadlineAt="2026-08-19T06:00:00Z",
    )

    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    entry = payload["instances"]["worktree:new"]
    assert payload["schemaVersion"] == registry.REGISTRY_SCHEMA_VERSION
    assert payload["updatedAt"]
    assert entry["updatedAt"]
    assert entry["ownerPid"] == 4321
    assert entry["ownerCreateTime"] == 123.5
    assert entry["ownerExecutable"] == "C:/Python/pythonw.exe"
    assert entry["inFlightDeadlineAt"] == entry["deadlineAt"]
    assert payload["instances"]["legacy"] == {"port": 8000}


def _safe_orphan_entry(project_root: str) -> dict:
    return {
        "projectRoot": project_root,
        "port": 8765,
        "ownerPid": 321,
        "ownerCreateTime": 100.0,
        "ownerExecutable": "C:/Python/pythonw.exe",
        "deadlineAt": "2026-08-19T05:00:00Z",
        "inFlightDeadlineAt": "2026-08-19T05:00:00Z",
    }


def test_reconcile_legacy_identity_is_unknown_and_not_removed(registry_path):
    registry.upsert_instance(
        "legacy",
        projectRoot="C:/missing/legacy",
        spawnPid=999,
        port=8765,
        deadlineAt="2026-08-19T05:00:00Z",
    )

    summary = registry.reconcile_registry(
        git_worktree_roots=[],
        electron_window_instance_ids=[],
        now=datetime(2026, 8, 19, 6, tzinfo=UTC),
        identity_inspector=lambda _identity: {"status": "dead"},
        listener_inspector=lambda _port, _identities: {"status": "none"},
    )

    assert summary["instances"][0]["classification"] == "unknown"
    assert registry.get_instance("legacy")


def test_reconcile_external_listener_is_conflict_and_never_removed(registry_path):
    registry.upsert_instance("external", **_safe_orphan_entry("C:/missing/external"))

    summary = registry.reconcile_registry(
        git_worktree_roots=[],
        electron_window_instance_ids=[],
        now=datetime(2026, 8, 19, 6, tzinfo=UTC),
        identity_inspector=lambda _identity: {"status": "dead"},
        listener_inspector=lambda _port, _identities: {"status": "external", "pid": 555},
    )

    assert summary["instances"][0]["classification"] == "conflict"
    assert registry.get_instance("external")


def test_reconcile_live_window_blocks_dead_process_cleanup(registry_path):
    registry.upsert_instance("windowed", **_safe_orphan_entry("C:/missing/windowed"))

    summary = registry.reconcile_registry(
        git_worktree_roots=[],
        electron_window_instance_ids=["windowed"],
        now=datetime(2026, 8, 19, 6, tzinfo=UTC),
        identity_inspector=lambda _identity: {"status": "dead"},
        listener_inspector=lambda _port, _identities: {"status": "none"},
    )

    assert summary["instances"][0]["classification"] == "stale"
    assert registry.get_instance("windowed")


def test_reconcile_requires_two_identical_observations_ten_seconds_apart(registry_path):
    registry.upsert_instance("orphan", **_safe_orphan_entry("C:/missing/orphan"))
    identity_calls: list[str] = []
    listener_calls: list[int] = []

    def inspect_dead(_identity):
        identity_calls.append("dead")
        return {"status": "dead"}

    def inspect_none(_port, _identities):
        listener_calls.append(int(_port))
        return {"status": "none"}

    first_at = datetime(2026, 8, 19, 6, tzinfo=UTC)

    first = registry.reconcile_registry(
        git_worktree_roots=[],
        electron_window_instance_ids=[],
        now=first_at,
        identity_inspector=inspect_dead,
        listener_inspector=inspect_none,
    )
    too_soon = registry.reconcile_registry(
        git_worktree_roots=[],
        electron_window_instance_ids=[],
        now=first_at + timedelta(seconds=9),
        identity_inspector=inspect_dead,
        listener_inspector=inspect_none,
    )

    assert first["removedInstanceIds"] == []
    assert too_soon["removedInstanceIds"] == []
    assert first["nextReconcileAt"] == "2026-08-19T06:00:10Z"
    assert too_soon["nextReconcileAt"] == "2026-08-19T06:00:10Z"
    assert first["instances"][0]["nextReconcileAt"] == "2026-08-19T06:00:10Z"
    assert first["worktreeDryRun"][0]["projectRoot"] == "C:/missing/orphan"
    assert registry.get_instance("orphan")
    first_identity_calls = len(identity_calls)
    first_listener_calls = len(listener_calls)
    assert first_identity_calls >= 1
    assert first_listener_calls >= 1

    confirmed = registry.reconcile_registry(
        git_worktree_roots=[],
        electron_window_instance_ids=[],
        now=first_at + timedelta(seconds=10),
        identity_inspector=inspect_dead,
        listener_inspector=inspect_none,
    )

    assert confirmed["removedInstanceIds"] == ["orphan"]
    assert confirmed.get("nextReconcileAt") in (None, "")
    assert confirmed["worktreeDryRun"][0]["action"] == "dry_run_only"
    assert registry.get_instance("orphan") == {}
    assert len(identity_calls) > first_identity_calls
    assert len(listener_calls) > first_listener_calls


def test_reconcile_no_change_does_not_rewrite_registry(registry_path, monkeypatch, tmp_path):
    existing_root = tmp_path / "existing-worktree"
    existing_root.mkdir()
    registry.upsert_instance("healthy", **_safe_orphan_entry(str(existing_root)))
    writes: list[int] = []
    original = registry.save_registry

    def counted(payload):
        writes.append(1)
        return original(payload)

    monkeypatch.setattr(registry, "save_registry", counted)
    summary = registry.reconcile_registry(
        git_worktree_roots=[existing_root],
        electron_window_instance_ids=[],
        now=datetime(2026, 8, 19, 6, tzinfo=UTC),
        identity_inspector=lambda _identity: {"status": "match"},
        listener_inspector=lambda _port, _identities: {"status": "owned"},
    )

    assert summary["instances"][0]["classification"] == "healthy"
    assert writes == []


def test_listener_identity_marks_unrelated_pid_as_external(monkeypatch):
    connection = SimpleNamespace(
        status="LISTEN",
        laddr=SimpleNamespace(ip="127.0.0.1", port=8765),
        pid=222,
    )
    fake_psutil = SimpleNamespace(net_connections=lambda kind: [connection])
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)
    result = process_identity.inspect_listener_identity(
        8765,
        [{"pid": 111, "createTime": 100.0, "executable": "C:/Python/pythonw.exe"}],
        identity_capture=lambda pid: {
            "pid": pid,
            "createTime": 200.0,
            "executable": "C:/Python/python.exe",
        },
    )

    assert result == {"status": "external", "pid": 222}


def test_allocate_reconciles_confirmed_orphan_before_claiming_ports(registry_path, monkeypatch):
    monkeypatch.setattr(registry, "_port_is_free", lambda port, host: True)
    registry.upsert_instance("orphan", **_safe_orphan_entry("C:/missing/orphan"))
    inspect_dead = lambda _identity: {"status": "dead"}
    inspect_none = lambda _port, _identities: {"status": "none"}
    first_at = datetime(2026, 8, 19, 6, tzinfo=UTC)
    registry.reconcile_registry(
        git_worktree_roots=[],
        electron_window_instance_ids=[],
        now=first_at,
        identity_inspector=inspect_dead,
        listener_inspector=inspect_none,
    )

    backend, control = registry.allocate_instance_ports(
        "replacement",
        git_worktree_roots=[],
        electron_window_instance_ids=[],
        reconcile_now=first_at + timedelta(seconds=10),
        identity_inspector=inspect_dead,
        listener_inspector=inspect_none,
    )

    assert (backend, control) == (8000, 8765)
    assert registry.get_instance("orphan") == {}


def test_reconcile_deadline_reobserves_facts_and_cancels_cleanup(registry_path):
    registry.upsert_instance("orphan", **_safe_orphan_entry("C:/missing/orphan"))
    first_at = datetime(2026, 8, 19, 6, tzinfo=UTC)
    facts = {"identity": "dead", "listener": "none", "windows": []}

    def inspect_identity(_identity):
        return {"status": facts["identity"]}

    def inspect_listener(_port, _identities):
        return {"status": facts["listener"]}

    first = registry.reconcile_registry(
        git_worktree_roots=[],
        electron_window_instance_ids=facts["windows"],
        now=first_at,
        identity_inspector=inspect_identity,
        listener_inspector=inspect_listener,
    )
    assert first["removedInstanceIds"] == []
    assert registry.get_instance("orphan")

    facts["listener"] = "owned"
    owned = registry.reconcile_registry(
        git_worktree_roots=[],
        electron_window_instance_ids=[],
        now=first_at + timedelta(seconds=10),
        identity_inspector=inspect_identity,
        listener_inspector=inspect_listener,
    )
    assert owned["removedInstanceIds"] == []
    assert owned["instances"][0]["classification"] == "healthy"
    assert registry.get_instance("orphan")
    assert "cleanupObservation" not in registry.get_instance("orphan")

    facts["listener"] = "none"
    facts["identity"] = "match"
    registry.upsert_instance("orphan", **_safe_orphan_entry("C:/missing/orphan"))
    registry.reconcile_registry(
        git_worktree_roots=[],
        electron_window_instance_ids=[],
        now=first_at,
        identity_inspector=inspect_identity,
        listener_inspector=inspect_listener,
    )
    matched = registry.reconcile_registry(
        git_worktree_roots=[],
        electron_window_instance_ids=[],
        now=first_at + timedelta(seconds=10),
        identity_inspector=inspect_identity,
        listener_inspector=inspect_listener,
    )
    assert matched["removedInstanceIds"] == []
    assert matched["instances"][0]["classification"] == "healthy"

    facts["identity"] = "dead"
    registry.upsert_instance("orphan", **_safe_orphan_entry("C:/missing/orphan"))
    registry.reconcile_registry(
        git_worktree_roots=[],
        electron_window_instance_ids=[],
        now=first_at,
        identity_inspector=inspect_identity,
        listener_inspector=inspect_listener,
    )
    windowed = registry.reconcile_registry(
        git_worktree_roots=[],
        electron_window_instance_ids=["orphan"],
        now=first_at + timedelta(seconds=10),
        identity_inspector=inspect_identity,
        listener_inspector=inspect_listener,
    )
    assert windowed["removedInstanceIds"] == []
    assert windowed["instances"][0]["classification"] == "stale"

    registry.upsert_instance("orphan", **_safe_orphan_entry("C:/missing/orphan"))
    registry.reconcile_registry(
        git_worktree_roots=[],
        electron_window_instance_ids=[],
        now=first_at,
        identity_inspector=inspect_identity,
        listener_inspector=inspect_listener,
    )
    registry.upsert_instance("orphan", generation=9, commandId="cmd-changed")
    fingerprint_changed = registry.reconcile_registry(
        git_worktree_roots=[],
        electron_window_instance_ids=[],
        now=first_at + timedelta(seconds=10),
        identity_inspector=inspect_identity,
        listener_inspector=inspect_listener,
    )
    assert fingerprint_changed["removedInstanceIds"] == []
    assert registry.get_instance("orphan")
    assert fingerprint_changed["nextReconcileAt"] == "2026-08-19T06:00:20Z"


def test_reconcile_legacy_unknown_quarantines_port_but_keeps_metadata(registry_path, monkeypatch):
    monkeypatch.setattr(registry, "_port_is_free", lambda port, host: True)
    registry.upsert_instance(
        "legacy",
        projectRoot="C:/missing/legacy",
        spawnPid=999,
        port=8765,
        controlPort=9001,
        deadlineAt="2026-08-19T05:00:00Z",
    )
    first_at = datetime(2026, 8, 19, 6, tzinfo=UTC)
    inspect_none = lambda _port, _identities: {"status": "none"}
    pid_missing = lambda _pid: False

    first = registry.reconcile_registry(
        git_worktree_roots=[],
        electron_window_instance_ids=[],
        now=first_at,
        identity_inspector=lambda _identity: {"status": "dead"},
        listener_inspector=inspect_none,
        pid_existence_inspector=pid_missing,
    )
    too_soon = registry.reconcile_registry(
        git_worktree_roots=[],
        electron_window_instance_ids=[],
        now=first_at + timedelta(seconds=9),
        identity_inspector=lambda _identity: {"status": "dead"},
        listener_inspector=inspect_none,
        pid_existence_inspector=pid_missing,
    )

    assert first["instances"][0]["classification"] == "unknown"
    assert first["removedInstanceIds"] == []
    assert first["nextReconcileAt"] == "2026-08-19T06:00:10Z"
    assert too_soon["removedInstanceIds"] == []
    assert registry.get_instance("legacy")["port"] == 8765
    assert registry.get_instance("legacy").get("portLeaseStatus") not in {"quarantined", "reclaimable"}

    confirmed = registry.reconcile_registry(
        git_worktree_roots=[],
        electron_window_instance_ids=[],
        now=first_at + timedelta(seconds=10),
        identity_inspector=lambda _identity: {"status": "dead"},
        listener_inspector=inspect_none,
        pid_existence_inspector=pid_missing,
    )

    stored = registry.get_instance("legacy")
    assert confirmed["removedInstanceIds"] == []
    assert confirmed["instances"][0]["classification"] == "unknown"
    assert confirmed["instances"][0]["portLeaseStatus"] == "reclaimable"
    assert stored
    assert stored["port"] == 8765
    assert stored["portLeaseStatus"] == "reclaimable"

    backend, control = registry.allocate_instance_ports(
        "replacement",
        preferred_backend=8765,
        preferred_control=9001,
        git_worktree_roots=[],
        electron_window_instance_ids=[],
        reconcile_now=first_at + timedelta(seconds=11),
        identity_inspector=lambda _identity: {"status": "dead"},
        listener_inspector=inspect_none,
        pid_existence_inspector=pid_missing,
    )

    assert (backend, control) == (8765, 9001)
    assert registry.get_instance("legacy")["port"] == 8765
    assert registry.get_instance("legacy")["portLeaseStatus"] == "reclaimable"
    assert registry.get_instance("replacement")["port"] == 8765


def test_reconcile_missing_path_closes_leftover_open_claim_without_deleting_unknown(registry_path):
    registry.upsert_instance(
        "ghost-start",
        projectRoot="C:/missing/ghost-start",
        spawnPid=999,
        port=8004,
        desiredState="open",
        status="starting",
        phase="starting",
        generation=1,
        commandId="cmd-ghost",
        deadlineAt="2026-08-18T04:52:41Z",
    )
    summary = registry.reconcile_registry(
        git_worktree_roots=[],
        electron_window_instance_ids=[],
        now=datetime(2026, 8, 19, 6, tzinfo=UTC),
        identity_inspector=lambda _identity: {"status": "dead"},
        listener_inspector=lambda _port, _identities: {"status": "none"},
        pid_existence_inspector=lambda _pid: False,
    )
    stored = registry.get_instance("ghost-start")

    assert summary["removedInstanceIds"] == []
    assert summary["instances"][0]["classification"] == "unknown"
    assert "closed_missing_worktree_claim" in summary["instances"][0]["reasons"]
    assert stored["desiredState"] == "closed"
    assert stored["status"] == "closed"
    assert stored["phase"] == "steady"
    assert stored.get("failureMessage") in {"", None}
    assert stored["port"] == 8004


def test_reconcile_missing_path_clears_sticky_worktree_path_missing_failure(registry_path):
    registry.upsert_instance(
        "ghost-stuck",
        projectRoot="C:/missing/ghost-stuck",
        port=8004,
        desiredState="closed",
        status="closed",
        phase="failed",
        failureMessage="worktree_path_missing",
    )
    summary = registry.reconcile_registry(
        git_worktree_roots=[],
        electron_window_instance_ids=[],
        now=datetime(2026, 8, 19, 6, tzinfo=UTC),
        identity_inspector=lambda _identity: {"status": "dead"},
        listener_inspector=lambda _port, _identities: {"status": "none"},
        pid_existence_inspector=lambda _pid: False,
    )
    stored = registry.get_instance("ghost-stuck")

    assert summary["removedInstanceIds"] == []
    assert "closed_missing_worktree_claim" in summary["instances"][0]["reasons"]
    assert stored["desiredState"] == "closed"
    assert stored["status"] == "closed"
    assert stored["phase"] == "steady"
    assert stored.get("failureMessage") in {"", None}


def test_reconcile_legacy_running_without_deadline_closes_when_path_missing(registry_path):
    registry.upsert_instance(
        "ghost-running",
        projectRoot="C:/missing/ghost-running",
        port=8000,
        status="running",
    )
    summary = registry.reconcile_registry(
        git_worktree_roots=[],
        electron_window_instance_ids=[],
        now=datetime(2026, 8, 19, 6, tzinfo=UTC),
        identity_inspector=lambda _identity: {"status": "dead"},
        listener_inspector=lambda _port, _identities: {"status": "external", "pid": 1},
        pid_existence_inspector=lambda _pid: False,
    )
    stored = registry.get_instance("ghost-running")

    assert summary["removedInstanceIds"] == []
    assert stored["status"] == "closed"
    assert stored.get("portLeaseStatus") not in {"quarantined", "reclaimable"}


def test_reconcile_missing_path_is_orphan_before_deadline(registry_path):
    registry.upsert_instance(
        "orphan",
        **{
            **_safe_orphan_entry("C:/missing/orphan"),
            "deadlineAt": "2026-08-19T07:00:00Z",
            "inFlightDeadlineAt": "2026-08-19T07:00:00Z",
        },
    )
    first_at = datetime(2026, 8, 19, 6, tzinfo=UTC)
    inspect_dead = lambda _identity: {"status": "dead"}
    inspect_none = lambda _port, _identities: {"status": "none"}
    first = registry.reconcile_registry(
        git_worktree_roots=[],
        electron_window_instance_ids=[],
        now=first_at,
        identity_inspector=inspect_dead,
        listener_inspector=inspect_none,
    )
    confirmed = registry.reconcile_registry(
        git_worktree_roots=[],
        electron_window_instance_ids=[],
        now=first_at + timedelta(seconds=10),
        identity_inspector=inspect_dead,
        listener_inspector=inspect_none,
    )

    assert first["instances"][0]["classification"] == "orphan"
    assert first["removedInstanceIds"] == []
    assert confirmed["removedInstanceIds"] == ["orphan"]
    assert registry.get_instance("orphan") == {}


def test_reconcile_legacy_unknown_does_not_quarantine_when_pid_still_exists(registry_path):
    registry.upsert_instance(
        "legacy",
        projectRoot="C:/missing/legacy",
        spawnPid=999,
        port=8765,
        deadlineAt="2026-08-19T05:00:00Z",
    )
    first_at = datetime(2026, 8, 19, 6, tzinfo=UTC)
    first = registry.reconcile_registry(
        git_worktree_roots=[],
        electron_window_instance_ids=[],
        now=first_at,
        identity_inspector=lambda _identity: {"status": "dead"},
        listener_inspector=lambda _port, _identities: {"status": "none"},
        pid_existence_inspector=lambda _pid: True,
    )
    later = registry.reconcile_registry(
        git_worktree_roots=[],
        electron_window_instance_ids=[],
        now=first_at + timedelta(seconds=10),
        identity_inspector=lambda _identity: {"status": "dead"},
        listener_inspector=lambda _port, _identities: {"status": "none"},
        pid_existence_inspector=lambda _pid: True,
    )

    assert first["instances"][0]["classification"] == "unknown"
    assert later["removedInstanceIds"] == []
    assert registry.get_instance("legacy").get("portLeaseStatus") not in {"quarantined", "reclaimable"}


def test_external_python_http_server_listener_is_conflict_and_never_killed(registry_path):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = int(reservation.getsockname()[1])

    python_executable = process_identity.capture_process_identity(os.getpid())["executable"]
    creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0
    process = subprocess.Popen(
        [python_executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
    try:
        deadline = time.monotonic() + 5
        result = {}
        while time.monotonic() < deadline:
            result = process_identity.inspect_listener_identity(
                port,
                [{"pid": os.getpid(), "createTime": 1.0, "executable": sys.executable}],
            )
            if result.get("status") == "external":
                break
            time.sleep(0.05)
        assert result == {"status": "external", "pid": process.pid}
        assert process.poll() is None

        entry = _safe_orphan_entry("C:/missing/external-http")
        entry["port"] = port
        registry.upsert_instance("external-http", **entry)
        summary = registry.reconcile_registry(
            git_worktree_roots=[],
            electron_window_instance_ids=[],
            now=datetime(2026, 8, 19, 6, tzinfo=UTC),
            identity_inspector=lambda _identity: {"status": "dead"},
        )
        assert summary["instances"][0]["classification"] == "conflict"
        assert summary["removedInstanceIds"] == []
        assert process.poll() is None
        assert registry.get_instance("external-http")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
