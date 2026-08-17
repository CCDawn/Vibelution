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
    assert by_id["worktree:failed"]["startBlockReason"] == "runtime_error"

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


def test_service_binds_current_project_bundle_into_branch_runtime(monkeypatch):
    bundle = {"observedState": "partial", "backend": {"alive": True}}
    seen: dict[str, object] = {}

    monkeypatch.setattr(launcher_service, "_current_project_bundle_for_branch_list", lambda: bundle)

    from core.launcher import branch_instance_cleanup, branch_instance_lifecycle

    def fake_list(*, current_bundle=None):
        seen["bundle"] = current_bundle
        return {"items": []}

    monkeypatch.setattr(branch_instance_lifecycle, "list_overlayed_branch_instances", fake_list)
    monkeypatch.setattr(branch_instance_cleanup, "annotate_cleanup_metadata", lambda payload: payload)

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
    monkeypatch.setattr(branch_instance_cleanup, "annotate_cleanup_metadata", lambda payload: payload)

    assert launcher_service.list_launcher_branch_instances() == {"items": []}
