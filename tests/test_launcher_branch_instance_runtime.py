from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core.launcher import branch_instance_lifecycle as lifecycle
from core.launcher import service as launcher_service


def _item(path: Path, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "worktree:feature",
        "kind": "worktree",
        "branch": "codex/feature",
        "path": str(path),
        "displayPath": ".worktrees/feature",
        "current": False,
        "checkedOut": True,
        "alive": False,
        "observedState": "idle",
        "port": 0,
        "pids": {"backend": 0, "window": 0, "manager": 0},
        "workbenchTitle": "feature 台",
    }
    payload.update(overrides)
    return payload


def _write_workbench_state(path: Path, **workbench: object) -> None:
    state_path = path / ".runtime" / "launcher" / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"workbench": workbench}), encoding="utf-8")


def _prepare_bundled_frontend(path: Path) -> None:
    dist = path / "web" / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text("<!doctype html>", encoding="utf-8")


def test_runtime_contract_classifies_running_partial_error_and_reserved_port(tmp_path, monkeypatch):
    running_path = tmp_path / "running"
    partial_path = tmp_path / "partial"
    failed_path = tmp_path / "failed"
    stopped_path = tmp_path / "stopped"
    for path in (running_path, partial_path, failed_path, stopped_path):
        path.mkdir()
        _prepare_bundled_frontend(path)

    _write_workbench_state(
        partial_path,
        desiredState="open",
        observedState="partial",
        phase="steady",
        backendHealthy=False,
        backendPortListening=False,
    )
    _write_workbench_state(failed_path, desiredState="open", observedState="closed", phase="steady")
    _write_workbench_state(stopped_path, desiredState="closed", observedState="closed", phase="steady")

    current = _item(
        running_path,
        id="main",
        kind="main",
        branch="main",
        current=True,
        alive=True,
        observedState="open",
        port=8002,
        pids={"backend": os.getpid(), "window": os.getpid(), "manager": 0},
        workbenchTitle="main 台",
    )
    partial = _item(
        partial_path,
        id="worktree:partial",
        alive=False,
        port=8003,
        pids={"backend": 0, "window": os.getpid(), "manager": 0},
        workbenchTitle="partial 台",
    )
    failed = _item(failed_path, id="worktree:failed", workbenchTitle="failed 台")
    stopped = _item(stopped_path, id="worktree:stopped", port=8005, workbenchTitle="stopped 台")

    monkeypatch.setattr(lifecycle, "_slot_fields_for_path", lambda _path: {})
    monkeypatch.setattr(
        lifecycle.registry,
        "list_instances",
        lambda: [
            {
                "instanceId": "worktree:partial",
                "projectRoot": str(partial_path),
                "port": 8003,
                "status": "running",
                "windowPid": os.getpid(),
                "windowTitle": "实际 partial 台",
            },
            {
                "instanceId": "worktree:failed",
                "projectRoot": str(failed_path),
                "port": 8004,
                "status": "failed",
            },
            {
                "instanceId": "worktree:stopped",
                "projectRoot": str(stopped_path),
                "port": 8005,
                "status": "closed",
            },
        ],
    )

    payload = lifecycle.overlay_instance_ports(
        {"items": [current, partial, failed, stopped]},
        launcher_state={"launcherControlPort": 8765},
        current_bundle={
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
            "failureMessage": "",
            "backend": {
                "pid": os.getpid(),
                "alive": True,
                "healthy": True,
                "port": 8002,
                "portListening": True,
                "portConflict": False,
            },
            "frontend": {"mode": "bundled_static_dist", "distReady": True},
            "browser": {"windowPid": os.getpid(), "alive": True},
        },
    )
    by_id = {item["id"]: item for item in payload["items"]}

    assert by_id["main"]["runtime"]["lifecycleState"] == "running"
    assert by_id["main"]["runtime"]["backend"] == {
        "alive": True,
        "healthy": True,
        "listening": True,
        "port": 8002,
        "portReserved": False,
        "portConflict": False,
        "pid": os.getpid(),
    }
    assert by_id["main"]["startable"] is False

    assert by_id["worktree:partial"]["runtime"]["lifecycleState"] == "partial"
    assert by_id["worktree:partial"]["runtime"]["window"] == {
        "open": True,
        "pid": os.getpid(),
        "title": "实际 partial 台",
        "titleObserved": True,
    }
    assert by_id["worktree:partial"]["startable"] is False

    assert by_id["worktree:failed"]["runtime"]["lifecycleState"] == "error"
    assert by_id["worktree:failed"]["runtime"]["error"]["code"] == "registry_failed"
    assert by_id["worktree:failed"]["startable"] is True
    assert by_id["worktree:failed"]["startBlockReason"] == ""

    assert by_id["worktree:stopped"]["runtime"]["lifecycleState"] == "closed"
    assert by_id["worktree:stopped"]["runtime"]["backend"]["portReserved"] is True
    assert by_id["worktree:stopped"]["startable"] is True


def test_runtime_contract_blocks_non_worktree_and_missing_paths(tmp_path, monkeypatch):
    missing = tmp_path / "missing"
    local = _item(missing, id="branch:local", kind="local_branch", checkedOut=False)
    local["path"] = ""
    checked_out_missing = _item(missing, id="worktree:missing")
    monkeypatch.setattr(lifecycle, "_slot_fields_for_path", lambda _path: {})
    monkeypatch.setattr(lifecycle.registry, "list_instances", lambda: [])

    payload = lifecycle.overlay_instance_ports(
        {"items": [local, checked_out_missing]},
        launcher_state={},
    )
    by_id = {item["id"]: item for item in payload["items"]}

    assert by_id["branch:local"]["startable"] is False
    assert by_id["branch:local"]["startBlockReason"] == "unsupported_kind"
    assert by_id["worktree:missing"]["startable"] is False
    assert by_id["worktree:missing"]["startBlockReason"] == "worktree_missing"


@pytest.mark.parametrize(
    ("phase", "port_conflict", "expected", "error_code"),
    [
        ("opening", False, "partial", ""),
        ("restarting", False, "restarting", ""),
        ("closing", False, "stopping", ""),
        ("steady", True, "error", "backend_port_conflict"),
    ],
)
def test_runtime_lifecycle_projection_preserves_transitions_and_conflicts(
    phase: str,
    port_conflict: bool,
    expected: str,
    error_code: str,
):
    state, code = lifecycle._instance_lifecycle_state(
        observed_state="partial",
        phase=phase,
        registry_status="running",
        backend_alive=True,
        backend_healthy=not port_conflict,
        backend_listening=not port_conflict,
        backend_conflict=port_conflict,
        frontend_ready=True,
        window_open=False,
        failure_message="",
    )
    assert state == expected
    assert code == error_code


def test_runtime_lifecycle_projection_keeps_starting_only_before_backend_is_ready():
    state, code = lifecycle._instance_lifecycle_state(
        observed_state="closed",
        phase="opening",
        registry_status="",
        backend_alive=False,
        backend_healthy=False,
        backend_listening=False,
        backend_conflict=False,
        frontend_ready=True,
        window_open=False,
        failure_message="",
    )
    assert state == "starting"
    assert code == ""


def test_runtime_lifecycle_projection_ignores_stale_failure_during_start():
    state, code = lifecycle._instance_lifecycle_state(
        observed_state="closed",
        phase="starting",
        desired_state="open",
        registry_status="starting",
        backend_alive=False,
        backend_healthy=False,
        backend_listening=False,
        backend_conflict=False,
        frontend_ready=True,
        window_open=False,
        failure_message="上次启动失败",
    )
    assert state == "starting"
    assert code == ""


def test_runtime_lifecycle_projection_does_not_treat_registry_running_as_ready():
    state, code = lifecycle._instance_lifecycle_state(
        observed_state="closed",
        phase="steady",
        desired_state="closed",
        registry_status="running",
        backend_alive=False,
        backend_healthy=False,
        backend_listening=False,
        backend_conflict=False,
        frontend_ready=True,
        window_open=False,
        failure_message="",
    )
    assert state == "closed"
    assert code == ""


def test_runtime_lifecycle_projection_requires_window_for_running():
    state, code = lifecycle._instance_lifecycle_state(
        observed_state="partial",
        phase="steady",
        desired_state="open",
        registry_status="steady",
        backend_alive=True,
        backend_healthy=True,
        backend_listening=True,
        backend_conflict=False,
        frontend_ready=True,
        window_open=False,
        failure_message="",
    )
    assert state == "partial"
    assert code == ""


def test_runtime_lifecycle_projection_ignores_leftover_observed_open_without_live_signals():
    state, code = lifecycle._instance_lifecycle_state(
        observed_state="open",
        phase="steady",
        desired_state="open",
        registry_status="running",
        backend_alive=False,
        backend_healthy=False,
        backend_listening=False,
        backend_conflict=False,
        frontend_ready=True,
        window_open=False,
        failure_message="",
    )
    assert state == "closed"
    assert code == ""


def test_branch_list_bundle_drops_leftover_opening_when_daemon_and_port_are_dead(monkeypatch):
    leftover = {
        "observedState": "open",
        "desiredState": "open",
        "phase": "opening",
        "failureMessage": "main dirty",
        "backend": {
            "alive": True,
            "healthy": True,
            "port": 8002,
            "portListening": True,
            "portConflict": False,
        },
        "browser": {"alive": False},
    }
    monkeypatch.setattr(launcher_service, "_live_backend_port_listening", lambda _port: False)
    reconciled = launcher_service._reconcile_stale_disk_bundle_for_branch_list(
        leftover,
        {"daemonRunning": False, "workbench": {"backendPort": 8002}},
    )
    assert reconciled["observedState"] == "closed"
    assert reconciled["desiredState"] == "closed"
    assert reconciled["phase"] == "steady"
    assert reconciled["failureMessage"] == ""
    assert reconciled["backend"]["alive"] is False
    assert reconciled["backend"]["healthy"] is False
    assert reconciled["backend"]["portListening"] is False


def test_branch_list_bundle_keeps_live_port_when_daemon_is_dead(monkeypatch):
    leftover = {
        "observedState": "partial",
        "desiredState": "open",
        "phase": "steady",
        "backend": {
            "alive": True,
            "healthy": True,
            "port": 8002,
            "portListening": True,
            "portConflict": False,
        },
        "browser": {"alive": False},
    }
    monkeypatch.setattr(launcher_service, "_live_backend_port_listening", lambda _port: True)
    reconciled = launcher_service._reconcile_stale_disk_bundle_for_branch_list(
        leftover,
        {"daemonRunning": False, "workbench": {"backendPort": 8002}},
    )
    assert reconciled["observedState"] == "partial"
    assert reconciled["backend"]["alive"] is True
    assert reconciled["backend"]["healthy"] is True


def test_branch_list_bundle_adopts_live_ports_json_when_disk_port_is_dead(monkeypatch):
    leftover = {
        "observedState": "closed",
        "desiredState": "closed",
        "phase": "steady",
        "backend": {
            "alive": False,
            "healthy": False,
            "port": 8000,
            "portListening": False,
            "portConflict": False,
        },
        "browser": {"alive": False},
    }
    monkeypatch.setattr(
        launcher_service,
        "_live_backend_port_listening",
        lambda port: int(port) == 8002,
    )
    monkeypatch.setattr(
        launcher_service,
        "_branch_list_backend_ports_to_probe",
        lambda _bundle, _runtime_state: [8000, 8002],
    )
    reconciled = launcher_service._reconcile_stale_disk_bundle_for_branch_list(
        leftover,
        {"daemonRunning": False, "workbench": {"backendPort": 8000}},
    )
    assert reconciled["backend"]["port"] == 8002
    assert reconciled["backend"]["alive"] is True
    assert reconciled["backend"]["healthy"] is True
    assert reconciled["backend"]["portListening"] is True
    assert reconciled["observedState"] == "closed"


def test_branch_list_bundle_keeps_opening_while_daemon_runs(monkeypatch):
    leftover = {
        "observedState": "closed",
        "desiredState": "open",
        "phase": "opening",
        "backend": {"alive": False, "healthy": False, "port": 8002, "portListening": False},
        "browser": {"alive": False},
    }
    monkeypatch.setattr(launcher_service, "_live_backend_port_listening", lambda _port: False)
    reconciled = launcher_service._reconcile_stale_disk_bundle_for_branch_list(
        leftover,
        {"daemonRunning": True, "workbench": {"backendPort": 8002}},
    )
    assert reconciled["phase"] == "opening"
    assert reconciled["desiredState"] == "open"


def test_service_binds_current_project_bundle_into_branch_runtime(monkeypatch):
    bundle = {"observedState": "partial", "backend": {"alive": True}}
    seen: dict[str, object] = {}

    monkeypatch.setattr(launcher_service, "_current_project_bundle_for_branch_list", lambda: bundle)

    from core.launcher import branch_instance_cleanup, branch_instance_lifecycle

    def fake_list(*, current_bundle=None):
        seen["bundle"] = current_bundle
        return {"items": []}

    monkeypatch.setattr(branch_instance_lifecycle, "list_overlayed_branch_instances", fake_list)

    def boom_annotate(_payload):
        raise AssertionError("default branch list must not annotate cleanup metadata")

    monkeypatch.setattr(branch_instance_cleanup, "annotate_cleanup_metadata", boom_annotate)

    assert launcher_service.list_launcher_branch_instances() == {"items": []}
    assert seen["bundle"] is bundle


def test_branch_list_does_not_call_full_launcher_status(monkeypatch):
    monkeypatch.setattr(
        launcher_service,
        "_current_project_bundle_for_branch_list",
        lambda: {"observedState": "closed"},
    )

    def boom():
        raise AssertionError("branch list must not wait on get_launcher_status")

    monkeypatch.setattr(launcher_service, "get_launcher_status", boom)

    from core.launcher import branch_instance_cleanup, branch_instance_lifecycle

    monkeypatch.setattr(
        branch_instance_lifecycle,
        "list_overlayed_branch_instances",
        lambda *, current_bundle=None: {"items": []},
    )

    def boom_annotate(_payload):
        raise AssertionError("default branch list must not annotate cleanup metadata")

    monkeypatch.setattr(branch_instance_cleanup, "annotate_cleanup_metadata", boom_annotate)

    assert launcher_service.list_launcher_branch_instances() == {"items": []}


def test_service_cleanup_metadata_annotation_is_opt_in(monkeypatch):
    monkeypatch.setattr(
        launcher_service,
        "_current_project_bundle_for_branch_list",
        lambda: {"observedState": "closed"},
    )

    from core.launcher import branch_instance_cleanup, branch_instance_lifecycle

    monkeypatch.setattr(
        branch_instance_lifecycle,
        "list_overlayed_branch_instances",
        lambda *, current_bundle=None: {"items": [{"id": "worktree:task"}]},
    )
    annotated = {"items": [{"id": "worktree:task", "mergedToMain": False}]}
    seen: dict[str, object] = {}

    def fake_annotate(payload):
        seen["payload"] = payload
        return annotated

    monkeypatch.setattr(branch_instance_cleanup, "annotate_cleanup_metadata", fake_annotate)

    assert launcher_service.list_launcher_branch_instances() == {"items": [{"id": "worktree:task"}]}
    assert seen == {}
    assert launcher_service.list_launcher_branch_instances(include_cleanup_metadata=True) == annotated
    assert seen["payload"] == {"items": [{"id": "worktree:task"}]}


def test_overlay_prefers_registry_starting_over_stale_worktree_failure(tmp_path, monkeypatch):
    path = tmp_path / "task"
    path.mkdir()
    _prepare_bundled_frontend(path)
    _write_workbench_state(
        path,
        desiredState="closed",
        observedState="closed",
        phase="failed",
        failureMessage="上次启动失败",
    )
    monkeypatch.setattr(lifecycle, "_slot_fields_for_path", lambda _path: {})
    monkeypatch.setattr(
        lifecycle.registry,
        "list_instances",
        lambda: [
            {
                "instanceId": "worktree:feature",
                "projectRoot": str(path),
                "status": "starting",
                "desiredState": "open",
                "phase": "starting",
                "generation": 2,
                "failureMessage": "",
                "port": 8003,
            }
        ],
    )
    payload = lifecycle.overlay_instance_ports(
        {"items": [_item(path)]},
        launcher_state={},
    )
    runtime = payload["items"][0]["runtime"]
    assert runtime["lifecycleState"] == "starting"
    assert runtime["desiredState"] == "open"
    assert runtime["generation"] == 2
    assert "error" not in runtime


def _stale_starting_entry(path: Path, **overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "instanceId": "worktree:feature",
        "projectRoot": str(path),
        "status": "starting",
        "desiredState": "open",
        "phase": "starting",
        "generation": 1,
        "failureMessage": "",
        "port": 8003,
        "spawnPid": 424242,
        "deadlineAt": "2026-08-18T04:52:41Z",
    }
    entry.update(overrides)
    return entry


def test_overlay_collapses_starting_when_supervisor_died_past_deadline(tmp_path, monkeypatch):
    path = tmp_path / "task"
    path.mkdir()
    _prepare_bundled_frontend(path)
    monkeypatch.setattr(lifecycle, "_slot_fields_for_path", lambda _path: {})
    monkeypatch.setattr(lifecycle, "_pid_alive", lambda _pid: False)
    monkeypatch.setattr(
        lifecycle.registry,
        "list_instances",
        lambda: [_stale_starting_entry(path)],
    )

    payload = lifecycle.overlay_instance_ports(
        {"items": [_item(path)]},
        launcher_state={},
    )

    item = payload["items"][0]
    runtime = item["runtime"]
    assert runtime["lifecycleState"] == "error"
    assert runtime["error"]["code"] == "start_supervisor_lost"
    assert "重试启动" in runtime["error"]["message"]
    assert item["startable"] is True


def test_overlay_keeps_starting_when_supervisor_alive_past_deadline(tmp_path, monkeypatch):
    path = tmp_path / "task"
    path.mkdir()
    _prepare_bundled_frontend(path)
    monkeypatch.setattr(lifecycle, "_slot_fields_for_path", lambda _path: {})
    monkeypatch.setattr(lifecycle, "_pid_alive", lambda _pid: True)
    monkeypatch.setattr(
        lifecycle.registry,
        "list_instances",
        lambda: [_stale_starting_entry(path)],
    )

    payload = lifecycle.overlay_instance_ports(
        {"items": [_item(path)]},
        launcher_state={},
    )

    runtime = payload["items"][0]["runtime"]
    assert runtime["lifecycleState"] == "starting"
    assert "error" not in runtime


def test_overlay_keeps_starting_before_deadline_even_when_spawn_pid_dead(tmp_path, monkeypatch):
    path = tmp_path / "task"
    path.mkdir()
    _prepare_bundled_frontend(path)
    monkeypatch.setattr(lifecycle, "_slot_fields_for_path", lambda _path: {})
    monkeypatch.setattr(lifecycle, "_pid_alive", lambda _pid: False)
    monkeypatch.setattr(
        lifecycle.registry,
        "list_instances",
        lambda: [_stale_starting_entry(path, deadlineAt="2999-01-01T00:00:00Z")],
    )

    payload = lifecycle.overlay_instance_ports(
        {"items": [_item(path)]},
        launcher_state={},
    )

    runtime = payload["items"][0]["runtime"]
    assert runtime["lifecycleState"] == "starting"
    assert "error" not in runtime


def test_runtime_lifecycle_projection_marks_lost_restarting_as_error():
    state, code = lifecycle._instance_lifecycle_state(
        observed_state="closed",
        phase="starting",
        desired_state="open",
        registry_status="restarting",
        backend_alive=False,
        backend_healthy=False,
        backend_listening=False,
        backend_conflict=False,
        frontend_ready=True,
        window_open=False,
        failure_message="",
        start_supervisor_lost=True,
    )
    assert state == "error"
    assert code == "start_supervisor_lost"


def test_runtime_lifecycle_projection_lost_supervisor_does_not_override_live_window():
    state, code = lifecycle._instance_lifecycle_state(
        observed_state="partial",
        phase="starting",
        desired_state="open",
        registry_status="starting",
        backend_alive=False,
        backend_healthy=False,
        backend_listening=False,
        backend_conflict=False,
        frontend_ready=True,
        window_open=True,
        failure_message="",
        start_supervisor_lost=True,
    )
    assert state == "partial"
    assert code == ""
