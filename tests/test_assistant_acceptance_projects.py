"""Evidence identity negatives; these tests never claim a simulated E2E pass."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import acceptance_assistant_projects as case


def target(tmp_path):
    slot = case.ProjectSlot("A", "opaque-a", tmp_path.resolve(), "A_VALUE", 610127)
    dispatch = {"projectId": slot.project_id, "agentId": "agent-a", "nativeTaskId": "native-a"}
    task = {"taskId": "native-a", "agentId": "agent-a", "sessionId": "session-a", "turnId": "turn-a",
            "effectivePermissionProfile": "read_only", "localWorkspacePath": str(slot.root)}
    return slot, dispatch, task


def test_native_binding_requires_root_agent_task_session_and_turn(tmp_path):
    slot, dispatch, task = target(tmp_path)
    proof = case.assert_native_binding(slot, "agent-a", dispatch, task)
    assert proof["root"] == str(slot.root)
    assert proof["agentId"] == "agent-a" and proof["turnId"] == "turn-a"


@pytest.mark.parametrize("surface,key,value,code", [
    ("dispatch", "projectId", "opaque-b", "project_dispatch_target_mismatch"),
    ("dispatch", "agentId", "agent-b", "project_dispatch_target_mismatch"),
    ("dispatch", "nativeTaskId", "native-b", "project_native_identity_mismatch"),
    ("task", "agentId", "agent-b", "project_native_identity_mismatch"),
    ("task", "sessionId", "", "project_native_identity_mismatch"),
    ("task", "turnId", "", "project_native_identity_mismatch"),
    ("task", "effectivePermissionProfile", "workspace_write", "project_native_workspace_mismatch"),
])
def test_native_projection_cannot_borrow_another_identity(tmp_path, surface, key, value, code):
    slot, dispatch, task = target(tmp_path)
    (dispatch if surface == "dispatch" else task)[key] = value
    with pytest.raises(case.AcceptanceFailure, match=code):
        case.assert_native_binding(slot, "agent-a", dispatch, task)


def test_successful_task_at_different_root_is_rejected(tmp_path):
    slot, dispatch, task = target(tmp_path)
    task.update(status="succeeded", localWorkspacePath=str(tmp_path / "other-root"))
    with pytest.raises(case.AcceptanceFailure, match="project_native_workspace_mismatch"):
        case.assert_native_binding(slot, "agent-a", dispatch, task)


def test_marker_value_is_held_in_file_and_never_disclosed_in_request(tmp_path):
    slots = [case.ProjectSlot(name, "opaque-" + name, tmp_path / name, name + "_VALUE", value)
             for name, value in (("A", 610127), ("A1", 620129), ("B", 630137))]
    for slot in slots:
        case.base.private_json(slot.root / case.MARKER_PATH,
                               {"slot": slot.name, "label": slot.label, "value": slot.value})
        snapshot = slot.snapshot()
        assert snapshot["sha256"] and snapshot["path"].is_absolute()
    message = case.task_message(slots, {slot.project_id: "agent-" + slot.name for slot in slots},
                                "goal", ["dispatch-a", "dispatch-a1", "dispatch-b"])
    assert all(str(slot.value) not in message for slot in slots)
    assert "delegation_goal_create" in message and "dispatch_derived" in message
    assert all(str(slot.root / case.MARKER_PATH) in message for slot in slots)
    with pytest.raises(case.AcceptanceFailure, match="project_marker_changed"):
        replace(slots[0], value=1).snapshot()


def test_fixture_git_discards_all_inherited_git_bindings(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(case, "git_hook_isolated_environment", lambda: {
        "PATH": "safe-path", "GIT_DIR": "real-repo", "GIT_CONFIG_COUNT": "1", "GIT_AUTHOR_NAME": "inherited"})

    def run(args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="verified\n")

    monkeypatch.setattr(case, "run_git", run)
    assert case.fixture_git(tmp_path, "status", env={"USERPROFILE": "private", "GIT_WORK_TREE": "real-tree"}) == "verified"
    assert captured["env"] == {"PATH": "safe-path", "USERPROFILE": "private"}


def test_launcher_handoff_does_not_claim_runtime_evidence(tmp_path):
    electron, pythonw = tmp_path / "electron.exe", tmp_path / "pythonw.exe"
    dist = tmp_path / "build"
    dist.mkdir()
    for path in (electron, pythonw, dist / "main.js"):
        path.write_text("fixture", encoding="utf-8")
    slot = case.ProjectSlot("A", "opaque-a", tmp_path / "checkout-a", "A_VALUE", 610127)
    fixture = SimpleNamespace(home=tmp_path / "private-home", _snapshot={})
    result = case.launcher_handoff(fixture, [slot], electron=electron, desktop_dist=dist, pythonw=pythonw)
    plan = case.base.read_json(Path(result["instructionsPath"]))
    assert result["status"] == plan["status"] == "not_tested"
    assert plan["pid"] is None and plan["cdp"] is None
    assert plan["standaloneProcessesMustStopBeforeStart"] is True
    assert "--smoke" not in plan["argvPrefix"] and "--canary" not in plan["argvPrefix"]
    private_local = Path(plan["environmentOverrides"]["LOCALAPPDATA"])
    profile = private_local / "Vibelution" / "DesktopShell" / "vibelution-launch-profile.json"
    assert case.base.read_json(profile)["operatorConfigPath"] == plan["environmentOverrides"]["VIBELUTION_CONFIG_PATH"]
    assert not any(word in str(plan).lower() for word in ("token", "capability", "authorization"))


def test_launcher_bootstraps_keep_each_private_projects_reserved_ports(tmp_path):
    controller = object.__new__(case.IsolatedLauncherController)
    controller.slots = {name: case.ProjectSlot(name, name, tmp_path / name, name, 1) for name in ("A", "A1", "B")}
    controller.env = {"VIBELUTION_PORT": "8000", "VIBELUTION_FRONTEND_PORT": "5173", "LOCALAPPDATA": "private"}
    controller.ports = {"A": {"backend": 23111, "frontend": 43111}, "B": {"backend": 23222, "frontend": 43222}}
    a = controller._target_environment(tmp_path / "A")
    b = controller._target_environment(tmp_path / "B")
    assert a["VIBELUTION_PORT"] == a["AGENT_WORKBENCH_BACKEND_PORT"] == "23111"
    assert b["VIBELUTION_PORT"] == b["AGENT_WORKBENCH_BACKEND_PORT"] == "23222"
    assert (a["VIBELUTION_FRONTEND_PORT"], b["VIBELUTION_FRONTEND_PORT"]) == ("43111", "43222")
    assert a["LOCALAPPDATA"] == b["LOCALAPPDATA"] == "private"
    assert a["PYTHONIOENCODING"] == b["PYTHONIOENCODING"] == "utf-8"
    assert controller.env["VIBELUTION_PORT"] == "8000"


def test_reused_checkout_runtime_bounds_exclude_other_projects(tmp_path):
    controller = object.__new__(case.IsolatedLauncherController)
    controller.fixture = SimpleNamespace(home=tmp_path / "new-runtime")
    root, other = tmp_path / "previous-private-checkouts" / "A", tmp_path / "other-project"
    controller.slots = {"A": case.ProjectSlot("A", "A", root, "A", 1)}
    assert controller._private_runtime_path(root / ".runtime", root)
    assert controller._private_runtime_path(root / ".runtime/runtime-manager", root)
    assert controller._private_runtime_path(controller.fixture.home / "projects/runtime", root)
    assert not controller._private_runtime_path(other / ".runtime", root)
    assert not controller._private_runtime_path(root / "unexpected-runtime", root)
    assert not controller._private_runtime_path(other / ".runtime", other)


def test_reused_checkout_runtime_bounds_reject_external_directory_links(tmp_path):
    controller = object.__new__(case.IsolatedLauncherController)
    controller.fixture = SimpleNamespace(home=tmp_path / "new-runtime")
    root, outside = tmp_path / "checkout", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    controller.slots = {"A": case.ProjectSlot("A", "A", root, "A", 1)}
    try:
        (root / ".runtime").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory links are unavailable in this test environment")
    assert not controller._private_runtime_path(root / ".runtime", root)
    assert not controller._private_runtime_path(root / ".runtime/runtime-manager", root)


def lifecycle_inputs(tmp_path, branch=False):
    expected = {"slot": "A1" if branch else "A", "root": str(tmp_path), "projectId": "native-project-id",
                "operation": "restart", "requestId": "stable-restart-id"}
    request = {key: expected[key] for key in ("projectId", "operation", "requestId")}
    command = {"commandId": "cmd_branch_123" if branch else "cmd_main_123", "operation": "restart", "type": "restart"}
    if branch:
        command.update(owner="branch", instanceId="native-branch-instance")
    record = {"schemaVersion": 1, "request": request, "binding": {"workspaceRoot": str(tmp_path)}, "command": command}
    native = {"schemaVersion": 1, "source": "electron_branch" if branch else "electron_main", **command,
              "accepted": True, "ok": True, "completed": True,
              "startedAt": "2026-11-02T00:00:00Z", "settledAt": "2026-11-02T00:00:02Z", "runMs": 2000}
    if branch:
        native["workspaceRoot"] = str(tmp_path)
    parameters = {"project_id": request["projectId"], "operation": request["operation"], "request_id": request["requestId"]}
    events = [{"eventType": "tool_result", "toolCallId": action, "sessionId": "s1", "turnId": "t1",
               "payload": {"toolCall": {"name": "personal_assistant_manage_tool",
                   "arguments": {"action": action, "arguments_json": parameters},
                   "result": {**request, "state": "completed", "accepted": True}}}}
              for action in ("project_lifecycle", "project_lifecycle_receipt")]
    return expected, record, native, events


@pytest.mark.parametrize("branch", [False, True])
def test_native_lifecycle_proof_joins_real_authorities(tmp_path, branch):
    expected, record, native, events = lifecycle_inputs(tmp_path, branch)
    proof = case.lifecycle_proof(expected, record, native, events)
    assert proof["nativeCompleted"] is True and proof["source"] == native["source"]


@pytest.mark.parametrize("key,value", [("source", "daemon"), ("completed", False),
                                      ("accepted", False), ("commandId", "cmd_other"), ("timedOut", True)])
def test_facade_status_or_unrelated_settlement_cannot_prove_restart(tmp_path, key, value):
    expected, record, native, events = lifecycle_inputs(tmp_path)
    native[key] = value
    with pytest.raises(case.AcceptanceFailure, match="launcher_real_native_settlement_missing"):
        case.lifecycle_proof(expected, record, native, events)


def test_lifecycle_done_file_cannot_replace_journal_or_branch_root(tmp_path):
    expected, record, native, events = lifecycle_inputs(tmp_path, True)
    with pytest.raises(case.AcceptanceFailure, match="launcher_real_assistant_lifecycle_journal_missing"):
        case.lifecycle_proof(expected, record, native, [])
    native["workspaceRoot"] = str(tmp_path / "different")
    with pytest.raises(case.AcceptanceFailure, match="launcher_branch_settlement_binding_mismatch"):
        case.lifecycle_proof(expected, record, native, events)


def test_restart_receipt_cannot_borrow_another_request_id(tmp_path):
    expected, record, native, events = lifecycle_inputs(tmp_path)
    events[-1]["payload"]["toolCall"]["result"]["requestId"] = "different-id"
    with pytest.raises(case.AcceptanceFailure, match="launcher_real_assistant_lifecycle_journal_missing"):
        case.lifecycle_proof(expected, record, native, events)


def test_failure_cleanup_only_stops_matching_owned_process_generations(monkeypatch, tmp_path):
    controller = object.__new__(case.IsolatedLauncherController)
    controller.process = SimpleNamespace(pid=100)
    controller.create_time = 1.0
    controller._children = {200: 2.0, 300: 3.0}
    controller.fixture = SimpleNamespace(cleanup={})
    controller.plan = {}
    controller.control_path = tmp_path / "control.json"
    alive = {(100, 1.0), (200, 2.0), (300, 99.0)}
    stopped = []
    monkeypatch.setattr(case.base.acceptance_runtime, "_process_matches", lambda pid, created: (pid, created) in alive)

    def stop(pid, created):
        stopped.append((pid, created))
        alive.discard((pid, created))
        return True

    monkeypatch.setattr(case.base.acceptance_runtime, "_terminate_recorded", stop)
    monkeypatch.setattr(controller, "_capture_children", lambda: None)
    controller.stop_owned_after_failure()
    assert stopped == [(100, 1.0), (200, 2.0)]
    assert (300, 99.0) in alive
    assert controller.fixture.cleanup == {"launcherElectronStopped": True, "launcherForcedStop": True}
    assert controller.plan["status"] == "failed"


def test_failure_cleanup_never_falls_back_to_pid_only(monkeypatch, tmp_path):
    controller = object.__new__(case.IsolatedLauncherController)
    controller.process = SimpleNamespace(pid=100)
    controller.create_time = None
    controller._children = {}
    controller.fixture = SimpleNamespace(cleanup={})
    controller.plan = {}
    controller.control_path = tmp_path / "control.json"
    monkeypatch.setattr(case.base.acceptance_runtime, "_process_matches", lambda *a: pytest.fail("PID-only lookup"))
    controller.stop_owned_after_failure()
    assert controller.fixture.cleanup["launcherElectronStopped"] is False
    assert controller.plan["cleanup"]["ownershipUnconfirmed"] is True


def test_crashed_electron_cannot_prove_formal_exit(tmp_path):
    controller = object.__new__(case.IsolatedLauncherController)
    controller.process = SimpleNamespace(wait=lambda **kw: 1)
    controller.plan = {"nextAction": {"type": "exit"}}
    with pytest.raises(case.AcceptanceFailure, match="formal_exit_unconfirmed"):
        controller.wait_exit()
