"""Runtime management delegates to temporary native owners without content reads."""
from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest

from core.web.services.external_management import runtime_operations as operations
from core.web.services.external_management.service import ManagementError


def write(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row), encoding="utf-8")


@pytest.fixture
def env(tmp_path, monkeypatch):
    import vibelution_storage
    from core.infrastructure import developer_sandbox
    from core.runtime_manager.work_run_store import WorkRunStore
    from core.runtime_manager import constants, evolution_store
    from core.runtime_manager import process_identity
    import psutil
    from core.web.services import runtime_manager_control_service
    from core.web.services import runtime_task_registry, session_service, team_service
    from core.web.services.external_management.native import NativeAgentGateway
    from core.web.services.team import team_store
    from core.web.services.team_workflow.generic import runtime, service

    project = tmp_path / "project"
    project.mkdir()
    runtime_home, workspace = tmp_path / "runtime", tmp_path / "workspace"
    runtime_home.mkdir()
    workspace.mkdir()
    config = tmp_path / "config.toml"
    config.write_text("[launcher.developer_mode]\nenabled = false\n", encoding="utf-8")
    directory = SimpleNamespace(CONFIG_PATH=config)
    gateway = NativeAgentGateway(project)
    monkeypatch.setattr(gateway, "_owners", lambda: directory)
    for owner in (runtime_task_registry, session_service, team_service, constants):
        monkeypatch.setattr(owner, "PROJECT_ROOT", project)
    monkeypatch.setattr(vibelution_storage, "resolve_project_runtime_home", lambda root: runtime_home)
    monkeypatch.setattr(runtime_task_registry, "resolve_project_runtime_home", lambda root: runtime_home)
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)
    monkeypatch.setattr(developer_sandbox, "formal_workspace_path", lambda root, *parts: workspace.joinpath(*parts))
    work = WorkRunStore(runtime_home / "runtime-manager" / "work_runs")
    work.runs_dir("chat_turn").mkdir(parents=True)
    managed = WorkRunStore(runtime_home / "runtime-manager" / "evolution")
    monkeypatch.setattr(evolution_store, "EVOLUTION_DIR", managed.root)
    monkeypatch.setattr(evolution_store, "_WORK_RUN_STORE", managed)
    monkeypatch.setattr(runtime_manager_control_service, "current_runtime_manager_pid", lambda root: 0)
    monkeypatch.setattr(process_identity, "is_runtime_manager_process", lambda pid: pid == 4321)
    monkeypatch.setattr(psutil, "Process", lambda pid: SimpleNamespace(cwd=lambda: str(project)))
    monkeypatch.setattr(session_service, "_WORK_RUN_STORE", work)
    monkeypatch.setattr(session_service, "_RUNNING_SESSION_IDS", set())
    monkeypatch.setattr(session_service, "_SESSION_ACTIVE_TURN_IDS", {})
    monkeypatch.setattr(session_service, "_get_session_turn_control", lambda sid: None)
    tasks = runtime_task_registry.store_for(runtime_home / runtime_task_registry.STORE_DIR_NAME)
    tasks.root.mkdir()
    external = runtime_home / "external_agents" / "tasks"
    external.mkdir(parents=True)
    teams = [{"teamId": "team-a", "status": "active", "members": []}]
    write(workspace / "teams" / "teams.json", {"teams": teams})
    monkeypatch.setattr(team_store, "_teams_root", lambda **kwargs: workspace / "teams")
    monkeypatch.setattr(team_store, "_load_index", lambda: {"teams": teams})
    monkeypatch.setattr(service, "_wake", lambda: None)
    monkeypatch.setattr(runtime, "_ADMITTING", True)
    monkeypatch.setattr(runtime, "_STOP", threading.Event())
    return SimpleNamespace(project=project, gateway=gateway, work=work, managed=managed, tasks=tasks, external=external,
                           workspace=workspace, config=config, sessions=session_service, monkeypatch=monkeypatch)


def detail(env, kind, rid, **refs):
    return operations.read_operation(env.gateway, kind, rid, **refs)["operation"]


def invoke(env, row, action, *, request_id="", **refs):
    return operations.command(env.gateway, {"kind": row["kind"], "resource_id": row["resourceId"],
        "expected_revision": row["revision"], "command": action, **refs}, request_id=request_id)


def native_run(env, *, status="waiting", revision=1):
    row = {"id": "run-a", "teamId": "team-a", "flow": {"id": "flow-a", "name": "SECRET name",
        "description": "SECRET prompt C:/private/path", "steps": [{"id": "human", "kind": "human",
        "label": "SECRET body", "owner": "user", "instruction": "SECRET instructions"}]},
        "values": {"content": "SECRET transcript"}, "status": status, "current": 0, "revision": revision,
        "messages": ["SECRET summary"], "attempts": [], "stopRequested": False}
    path = env.workspace / "teams" / "team-a" / "generic-workflows" / "runs" / "run-a.json"
    write(path, row)
    return path


def test_real_session_stop_retains_turn_identity_and_only_acknowledges_request(env, monkeypatch):
    from core.web.services.session import control
    sessions = env.sessions
    controller = sessions.SessionTurnControl(session_id="hidden-session", turn_id="turn-a")
    write(env.work.runs_dir("chat_turn") / "turn-a.json", {"runId": "turn-a", "sessionId": "hidden-session",
        "agentId": "system-companion", "status": "running", "userMessage": "SECRET malicious prompt",
        "summary": "SECRET C:/private/path", "messages": ["SECRET transcript"]})
    monkeypatch.setattr(sessions, "_RUNNING_SESSION_IDS", {"hidden-session"})
    monkeypatch.setattr(sessions, "_SESSION_ACTIVE_TURN_IDS", {"hidden-session": "turn-a"})
    monkeypatch.setattr(sessions, "_get_session_turn_control", lambda sid: controller)
    monkeypatch.setattr(sessions, "_is_session_running", lambda sid: True)
    monkeypatch.setattr(sessions, "get_web_language", lambda: "zh")
    monkeypatch.setattr(sessions, "_cancel_queued_session_turn", lambda *args: False)
    monkeypatch.setattr(sessions, "_record_chat_next_state_signal", lambda **kwargs: None)
    monkeypatch.setattr(sessions, "_record_session_turn_lifecycle_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(sessions, "get_session_detail", lambda *args: pytest.fail("Session hydration used"))
    cascades = []
    original = control._cascade_stop_descendant_runtime_tasks
    def cascade(*args, **kwargs):
        cascades.append((args, kwargs))
        return original(*args, **kwargs)
    monkeypatch.setattr(control, "_cascade_stop_descendant_runtime_tasks", cascade)
    row = detail(env, "session_turn", "turn-a", session_id="hidden-session")
    assert row["commands"] == ["stop"] and row["agentId"] == "system-companion"
    result = invoke(env, row, "stop", session_id="hidden-session")
    assert controller.snapshot()["stopRequested"] is True
    assert result["accepted"] is True and result["stopRequested"] is True
    assert result["operation"]["status"] == "stopping"
    assert result["operation"]["resourceId"] == "turn-a"
    assert result["revisionCheck"] == "preflight_only"
    assert cascades[0][0] == ("hidden-session",) and cascades[0][1]["turn_id"] == "turn-a"
    assert "SECRET" not in json.dumps(result)


def test_real_generic_owner_confirm_uses_native_cas_and_stale_revision_writes_nothing(env):
    from core.web.services.team_workflow.generic import service
    path = native_run(env)
    row = detail(env, "team_run", "run-a", team_id="team-a", flow_id="flow-a")
    assert row["commands"] == ["stop", "confirm"]
    assert row["revision"] == "1"
    raw_before = path.read_bytes()
    with pytest.raises(ManagementError, match="STATE_CONFLICT"):
        operations.command(env.gateway, {"kind": "team_run", "resource_id": "run-a", "team_id": "team-a",
            "command": "confirm", "expected_revision": "0"})
    assert path.read_bytes() == raw_before
    result = invoke(env, row, "confirm", team_id="team-a")
    assert result["accepted"] is True and result["stopRequested"] is False
    assert result["revisionCheck"] == "native_cas"
    assert result["operation"]["revision"] == "2" and result["operation"]["status"] == "running"
    assert service.get_run("team-a", "run-a")["current"] == 1
    assert "SECRET" not in json.dumps(result)


def test_native_generic_second_cas_rejects_race_without_overwriting(env, monkeypatch):
    from core.web.services.team_workflow.generic import service
    path = native_run(env)
    row = detail(env, "team_run", "run-a", team_id="team-a")
    original = service.command_run
    raced = []
    def race(team, rid, payload):
        value = json.loads(path.read_bytes())
        value["revision"] += 1
        write(path, value)
        raced.append(path.read_bytes())
        return original(team, rid, payload)
    monkeypatch.setattr(service, "command_run", race)
    with pytest.raises(ManagementError, match="STATE_CONFLICT"):
        invoke(env, row, "confirm", team_id="team-a")
    assert path.read_bytes() == raced[0]


def test_full_directory_runtime_discovery_recovers_unindexed_task_without_repair(env):
    from core.web.services import runtime_task_registry
    snapshot = runtime_task_registry.new_snapshot(kind="cli_agent", task_id="unindexed", status="running",
                                                label="SECRET label", output="SECRET body")
    write(env.tasks.task_state_path("unindexed"), snapshot)
    write(env.tasks.index_path, {"schemaVersion": 1, "activeTaskIds": []})
    index_before = env.tasks.index_path.read_bytes()
    page = operations.read_operations(env.gateway, {"kind": "runtime_task"})
    assert [row["resourceId"] for row in page["operations"]] == ["unindexed"]
    assert page["coverage"] == [{"source": "runtime_task", "state": "available", "complete": True}]
    assert page["complete"] is True and env.tasks.index_path.read_bytes() == index_before
    assert "SECRET" not in json.dumps(page)


def test_real_registry_stop_is_not_reported_as_worker_completion(env):
    from core.web.services import runtime_task_registry
    env.tasks.save_state(runtime_task_registry.new_snapshot(kind="cli_agent", task_id="task-a", status="running"))
    row = detail(env, "runtime_task", "task-a")
    result = invoke(env, row, "stop")
    assert result["accepted"] is True and result["stopRequested"] is True
    assert result["operation"]["status"] == "running"
    assert result["operation"]["commands"] == []
    assert env.tasks.load_state("task-a")["stopInitiator"] == "user"


def test_source_failure_preserves_other_operations_and_corruption_is_not_quarantined(env, monkeypatch):
    native_run(env)
    broken = env.managed.runs_dir("supervised") / "bad.json"
    broken.parent.mkdir(parents=True)
    broken.write_text("{", encoding="utf-8")
    before = broken.read_bytes(), broken.stat().st_mtime_ns
    monkeypatch.setattr(operations, "_external_tasks", lambda gateway: (_ for _ in ()).throw(OSError("SECRET path")))
    page = operations.read_operations(env.gateway, {})
    assert any(row["kind"] == "team_run" for row in page["operations"])
    coverage = {row["source"]: row for row in page["coverage"]}
    assert coverage["external_task"] == {"source": "external_task", "state": "unavailable", "complete": False}
    assert coverage["supervised_run"] == {"source": "supervised_run", "state": "partial", "complete": False}
    assert page["complete"] is False and len(page["coverage"]) == len(operations.KINDS)
    assert (broken.read_bytes(), broken.stat().st_mtime_ns) == before
    assert list(broken.parent.glob("*.corrupt-*")) == []
    assert "SECRET" not in json.dumps(page)


def test_metadata_only_hidden_queued_turn_beyond_native_forty_snapshot_cap(env):
    for i in range(43):
        write(env.work.runs_dir("chat_turn") / f"turn-{i:02}.json", {"runId": f"turn-{i:02}",
            "sessionId": f"session-{i:02}", "status": "queued", "hidden": True,
            "companion": True, "userMessage": "SECRET", "summary": "SECRET"})
    page = operations.read_operations(env.gateway, {"kind": "session_turn", "offset": 42, "limit": 1})
    assert page["operations"][0]["resourceId"] == "turn-42" and page["total"] == 43
    assert page["coverage"] == [{"source": "session_turn", "state": "partial", "complete": False}]
    assert "SECRET" not in json.dumps(page)


def test_cross_owner_external_metadata_never_advertises_cancel(env):
    write(env.external / "eat-other.json", {"taskId": "eat-other", "agentId": "hidden-agent",
        "sessionId": "hidden-session", "revision": 3, "status": "running", "ownerSubjectHash": "SECRET",
        "prompt": "SECRET hostile instructions"})
    row = detail(env, "external_task", "eat-other")
    assert row["commands"] == [] and row["revision"] == "3"
    with pytest.raises(ManagementError, match="command_forbidden"):
        invoke(env, row, "stop")
    assert "SECRET" not in json.dumps(row)


@pytest.mark.parametrize("patch", [{"status": "SECRET instructions"}, {"agentId": "C:/private/path"},
                                  {"taskId": "SECRET instructions"}])
def test_untrusted_metadata_values_are_not_promoted_to_identity(env, patch):
    write(env.tasks.task_state_path("task-a"), {"taskId": "task-a", "status": "running", **patch})
    page = operations.read_operations(env.gateway, {"kind": "runtime_task"})
    if "status" in patch:
        assert page["operations"][0]["status"] == "unknown"
        assert page["operations"][0]["commands"] == []
    else:
        assert page["operations"] == []
    assert page["complete"] is False
    assert page["coverage"][0]["state"] == "partial" and "SECRET" not in json.dumps(page)


@pytest.mark.parametrize("kind,refs", [("session_turn", {}), ("team_run", {}),
    ("runtime_task", {"team_id": "team-a"}), ("research_run", {"team_id": "team-a"}),
    ("external_task", {"session_id": "session-a"}), ("team_run", {"team_id": "team-a", "path": "x"})])
def test_detail_rejects_wrong_reference_combinations_before_read(env, monkeypatch, kind, refs):
    monkeypatch.setattr(operations, "_source", lambda *args: pytest.fail("read preceded reference validation"))
    with pytest.raises(ManagementError, match="INVALID_INPUT"):
        detail(env, kind, "resource-a", **refs)


def test_wrong_reference_cannot_select_another_team_run(env):
    native_run(env)
    for refs in ({"team_id": "team-b"}, {"team_id": "team-a", "flow_id": "other-flow"}):
        with pytest.raises(ManagementError, match="OPERATION_UNAVAILABLE"):
            detail(env, "team_run", "run-a", **refs)


def test_lost_native_acknowledgement_is_unconfirmed_and_content_free(env, monkeypatch):
    from core.web.services.team_workflow.generic import service
    native_run(env)
    row = detail(env, "team_run", "run-a", team_id="team-a")
    original = service.command_run
    def lose_ack(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("SECRET native path")
    monkeypatch.setattr(service, "command_run", lose_ack)
    with pytest.raises(ManagementError, match="OPERATION_UNCONFIRMED") as failure:
        invoke(env, row, "confirm", team_id="team-a")
    assert failure.value.status_code == 503
    assert service.get_run("team-a", "run-a")["revision"] == 2


def test_native_source_root_mismatch_does_not_read_other_project(env, monkeypatch):
    from core.web.services import runtime_task_registry
    monkeypatch.setattr(runtime_task_registry, "PROJECT_ROOT", env.project / "other")
    monkeypatch.setattr(env.tasks, "iter_task_states", lambda: pytest.fail("foreign owner read"))
    page = operations.read_operations(env.gateway, {"kind": "runtime_task"})
    assert page["operations"] == [] and page["coverage"][0]["state"] == "unavailable"


@pytest.mark.parametrize("query", [{"limit": 4}, {"offset": -1}, {"limit": True}, {"path": "x"}, {"kind": "other"}])
def test_page_is_closed_and_bounded(env, query):
    with pytest.raises(ManagementError, match="INVALID_INPUT"):
        operations.read_operations(env.gateway, query)


def test_long_identity_page_survives_exact_native_model_wrapper_and_cursor(env, monkeypatch):
    from core.web.services.external_management.runtime_contracts import RuntimeOperationsResponse
    from tests.test_assistant_runtime_actions import _through_native_model_budget
    rows = [{"id": str(i) + "r" * 159, "teamId": "t" * 160, "flow": {"id": "f" * 160},
             "agentId": "a" * 160, "sessionId": "s" * 160, "status": "running", "revision": 999}
            for i in range(3)]
    monkeypatch.setattr(operations, "_source", lambda gateway, kind: (rows if kind == "team_run" else [], True))
    first = RuntimeOperationsResponse.model_validate(operations.read_operations(env.gateway, {})).model_dump()
    assert 1 <= len(first["operations"]) < 3
    assert first["nextOffset"] == len(first["operations"])
    raw, outcome, facts, rendered = _through_native_model_budget({"projectId": "p" * 160, **first})
    assert len(raw) <= 3400 and outcome is None and not facts.truncated
    assert json.loads(rendered.split("\nResult:\n", 1)[1]) == json.loads(raw)
    second = operations.read_operations(env.gateway, {"offset": first["nextOffset"]})
    assert second["operations"][0]["resourceId"] == rows[first["nextOffset"]]["id"]


def test_default_active_filter_is_native_kind_specific_and_unknown_is_visible(env, monkeypatch):
    source = {"runtime_task": [{"taskId": "task-done", "status": "blocked"},
                               {"taskId": "task-idle", "status": "idle"},
                               {"taskId": "task-unknown", "status": "SECRET body"}],
              "research_run": [{"runId": "research-blocked", "teamId": "team-a", "flowId": "research-flow",
                                "status": "blocked", "revision": 2}]}
    monkeypatch.setattr(operations, "_source", lambda gateway, kind: (source.get(kind, []), True))
    active = operations.read_operations(env.gateway, {"kind": "runtime_task"})
    assert [row["resourceId"] for row in active["operations"]] == ["task-idle", "task-unknown"]
    assert active["operations"][1]["status"] == "unknown" and active["coverage"][0]["state"] == "partial"
    terminal = operations.read_operations(env.gateway, {"kind": "runtime_task", "state": "terminal"})
    assert [row["resourceId"] for row in terminal["operations"]] == ["task-done"]
    research = operations.read_operations(env.gateway, {"kind": "research_run"})
    assert research["operations"][0]["resourceId"] == "research-blocked"
    assert research["operations"][0]["commands"] == [] and "SECRET" not in json.dumps(active)


def test_formal_research_ledger_metadata_read_has_no_operator_commands(env, tmp_path, monkeypatch):
    import sqlite3
    from core.research.workflow.ledger import WorkflowLedgerStore
    from core.web.services.team_workflow.research_runtime import formal_read_runtime, paths
    ledger_path = tmp_path / "workflow-ledger.sqlite"
    with sqlite3.connect(ledger_path) as connection:
        connection.execute("CREATE TABLE workflow_runs(run_id,team_id,workflow_id,status,run_version,body)")
        connection.execute("CREATE TABLE node_attempts(run_id)")
        connection.execute("INSERT INTO workflow_runs VALUES(?,?,?,?,?,?)",
            ("research-a", "team-a", "research-flow", "waiting_human", 4, "SECRET prompt/transcript C:/private"))
    ledger = WorkflowLedgerStore(ledger_path)
    monkeypatch.setattr(paths, "PROJECT_ROOT", env.project)
    monkeypatch.setattr(paths, "workflow_ledger_path", lambda: ledger_path)
    monkeypatch.setattr(formal_read_runtime, "get_formal_read_store", lambda: ledger)
    try:
        before = ledger_path.read_bytes()
        row = detail(env, "research_run", "research-a", team_id="team-a", flow_id="research-flow")
        assert row["revision"] == "4" and row["commands"] == []
        assert row["status"] == "waiting_human" and "SECRET" not in json.dumps(row)
        assert ledger_path.read_bytes() == before
        monkeypatch.setattr(paths, "workflow_ledger_path", lambda: tmp_path / "foreign.sqlite")
        page = operations.read_operations(env.gateway, {"kind": "research_run"})
        assert page["operations"] == [] and page["coverage"][0]["state"] == "unavailable"
    finally:
        ledger.close()


@pytest.mark.parametrize("kind,native_kind,module,method", [
    ("supervised_run", "supervised", "supervised_control_service", "request_pause_supervised_run"),
    ("self_evolution_run", "self", "self_evolution_control_service", "request_pause_self_evolution_run")])
def test_managed_controls_use_exported_owner_with_non_atomic_revision_label(env, monkeypatch, kind, native_kind, module, method):
    import importlib
    from core.web.services import runtime_manager_control_service
    owner = importlib.import_module("core.web.services." + module)
    monkeypatch.setattr(owner, "PROJECT_ROOT", env.project)
    monkeypatch.setattr(runtime_manager_control_service, "current_runtime_manager_pid", lambda root: 4321)
    control = {"ownerPid": 4321, "kind": native_kind}
    path = env.managed.runs_dir(native_kind) / "managed-a.json"
    write(path, {"runId": "managed-a", "status": "running", "summary": "SECRET body", "runtimeManagerControl": control})
    calls = []
    def pause(rid):
        calls.append(rid)
        row = {"runId": rid, "status": "paused", "pauseRequested": True, "goal": "SECRET prompt", "runtimeManagerControl": control}
        write(path, row)
        return row
    monkeypatch.setattr(owner, method, pause)
    row = detail(env, kind, "managed-a")
    result = invoke(env, row, "pause")
    assert calls == ["managed-a"] and result["operation"]["commands"] == ["stop", "resume"]
    assert result["revisionCheck"] == "preflight_only" and result["stopRequested"] is False
    assert "SECRET" not in json.dumps(result)
    page = operations.read_operations(env.gateway, {"kind": kind})
    assert page["coverage"] == [{"source": kind, "state": "partial", "complete": False}]


@pytest.mark.parametrize("kind,native_kind", [("supervised_run", "supervised"), ("self_evolution_run", "self")])
def test_managed_list_and_point_read_use_evolution_authority_without_index_repairs(env, monkeypatch, kind, native_kind):
    from core.runtime_manager.work_run_store import WorkRunStore
    from core.web.services import self_evolution_control_service, supervised_control_service
    monkeypatch.setattr(WorkRunStore, "load_active_run_ids", lambda *args: pytest.fail("read repaired the active index"))
    monkeypatch.setattr(operations, "_work_store", lambda gateway: pytest.fail("managed read used Session authority"))
    monkeypatch.setattr(supervised_control_service, "get_active_supervised_run", lambda: pytest.fail("read reconciled supervised state"))
    monkeypatch.setattr(self_evolution_control_service, "get_active_self_evolution_run", lambda: pytest.fail("read reconciled self state"))
    write(env.managed.runs_dir(native_kind) / "shared-id.json", {"runId": "shared-id", "status": "paused", "summary": "SECRET body"})
    write(env.work.runs_dir(native_kind) / "shared-id.json", {"runId": "shared-id", "status": "running"})
    index = env.managed.index_path(native_kind)
    write(index, {"activeRunId": "missing-id"})
    before = index.read_bytes()
    page = operations.read_operations(env.gateway, {"kind": kind})
    row = detail(env, kind, "shared-id")
    assert page["operations"] == [row] and row["status"] == "paused" and row["commands"] == []
    assert page["coverage"] == [{"source": kind, "state": "partial", "complete": False}]
    assert index.read_bytes() == before and "SECRET" not in json.dumps(page)


@pytest.mark.parametrize("kind,native_kind", [("supervised_run", "supervised"), ("self_evolution_run", "self")])
def test_managed_wrong_store_record_is_never_a_managed_target(env, kind, native_kind):
    write(env.work.runs_dir(native_kind) / "wrong-store.json", {"runId": "wrong-store", "status": "running"})
    page = operations.read_operations(env.gateway, {"kind": kind})
    assert page["operations"] == [] and page["coverage"][0]["state"] == "partial"
    with pytest.raises(ManagementError, match="OPERATION_UNAVAILABLE"):
        detail(env, kind, "wrong-store")


@pytest.mark.parametrize("kind,native_kind", [("supervised_run", "supervised"), ("self_evolution_run", "self")])
@pytest.mark.parametrize("initialized", [False, True])
def test_managed_uninitialized_or_missing_kind_is_empty_without_mkdir(env, kind, native_kind, initialized):
    if initialized:
        env.managed.root.mkdir()
    before = sorted(path.relative_to(env.managed.root.parent) for path in env.managed.root.parent.rglob("*"))
    page = operations.read_operations(env.gateway, {"kind": kind})
    assert page["operations"] == [] and page["coverage"][0]["state"] == "partial"
    with pytest.raises(ManagementError, match="OPERATION_UNAVAILABLE"):
        detail(env, kind, "absent-run")
    assert sorted(path.relative_to(env.managed.root.parent) for path in env.managed.root.parent.rglob("*")) == before


@pytest.mark.parametrize("kind,native_kind", [("supervised_run", "supervised"), ("self_evolution_run", "self")])
def test_managed_corrupt_record_stays_untouched_and_does_not_hide_valid_metadata(env, kind, native_kind):
    folder = env.managed.runs_dir(native_kind)
    write(folder / "valid.json", {"runId": "valid", "status": "running"})
    corrupt = folder / "broken.json"
    corrupt.write_bytes(b"{not-json")
    before = {path.name: path.read_bytes() for path in folder.iterdir()}
    page = operations.read_operations(env.gateway, {"kind": kind})
    assert [row["resourceId"] for row in page["operations"]] == ["valid"]
    assert page["coverage"][0]["state"] == "partial"
    with pytest.raises(ManagementError, match="OPERATION_SOURCE_UNAVAILABLE"):
        detail(env, kind, "broken")
    with pytest.raises(ManagementError, match="OPERATION_UNAVAILABLE"):
        detail(env, kind, "missing")
    assert {path.name: path.read_bytes() for path in folder.iterdir()} == before


@pytest.mark.parametrize("binding", ["project", "store", "owner-path"])
def test_managed_foreign_binding_is_unavailable_even_with_matching_run_id(env, tmp_path, monkeypatch, binding):
    from core.runtime_manager import constants, evolution_store
    write(env.managed.runs_dir("supervised") / "managed-a.json", {"runId": "managed-a", "status": "running"})
    write(env.work.runs_dir("supervised") / "managed-a.json", {"runId": "managed-a", "status": "running"})
    if binding == "project":
        monkeypatch.setattr(constants, "PROJECT_ROOT", tmp_path / "foreign-project")
    elif binding == "store":
        monkeypatch.setattr(evolution_store, "_WORK_RUN_STORE", env.work)
    else:
        monkeypatch.setattr(evolution_store, "EVOLUTION_DIR", tmp_path / "foreign-evolution")
    page = operations.read_operations(env.gateway, {"kind": "supervised_run"})
    assert page["operations"] == [] and page["coverage"][0]["state"] == "unavailable"
    with pytest.raises(ManagementError, match="TARGET_BINDING_CHANGED|OPERATION_SOURCE_UNAVAILABLE"):
        detail(env, "supervised_run", "managed-a")


@pytest.mark.parametrize("kind,native_kind", [("supervised_run", "supervised"), ("self_evolution_run", "self")])
@pytest.mark.parametrize("pid,control", [(0, {"ownerPid": 4321}), (4321, {"ownerPid": 9999}),
    (4321, {}), (4321, {"ownerPid": True}), (4321, {"ownerPid": 4321, "kind": "foreign"})])
def test_managed_historical_status_cannot_advertise_or_submit_controls(env, monkeypatch, kind, native_kind, pid, control):
    from core.web.services import runtime_manager_control_service, self_evolution_control_service, supervised_control_service
    monkeypatch.setattr(runtime_manager_control_service, "current_runtime_manager_pid", lambda root: pid)
    owner = supervised_control_service if kind == "supervised_run" else self_evolution_control_service
    method = "request_stop_supervised_run" if kind == "supervised_run" else "request_stop_self_evolution_run"
    monkeypatch.setattr(owner, method, lambda rid: pytest.fail("historical record sent a manager command"))
    write(env.managed.runs_dir(native_kind) / "managed-a.json", {"runId": "managed-a", "status": "running",
        "_liveControl": True, "runtimeManagerControl": {"kind": native_kind, **control}})
    row = detail(env, kind, "managed-a")
    assert row["commands"] == []
    with pytest.raises(ManagementError, match="COMMAND_UNAVAILABLE"):
        invoke(env, row, "stop")


@pytest.mark.parametrize("location", ["folder", "file"])
def test_managed_unreadable_source_is_distinct_from_an_uninitialized_store(env, monkeypatch, location):
    from pathlib import Path
    folder = env.managed.runs_dir("supervised")
    path = folder / "managed-a.json"
    write(path, {"runId": "managed-a", "status": "running"})
    original_stat = Path.lstat
    def denied(target, *args, **kwargs):
        if target == (folder if location == "folder" else path):
            raise PermissionError("test managed source denied")
        return original_stat(target, *args, **kwargs)
    monkeypatch.setattr(Path, "lstat", denied)
    page = operations.read_operations(env.gateway, {"kind": "supervised_run"})
    assert page["operations"] == []
    assert page["coverage"][0]["state"] == ("unavailable" if location == "folder" else "partial")
    with pytest.raises(ManagementError, match="OPERATION_SOURCE_UNAVAILABLE"):
        detail(env, "supervised_run", "managed-a")


@pytest.mark.parametrize("failed_probe", [False, True])
def test_managed_manager_loss_revokes_controls_without_repairing_durable_state(env, monkeypatch, failed_probe):
    from core.web.services import runtime_manager_control_service, supervised_control_service
    path = env.managed.runs_dir("supervised") / "managed-a.json"
    write(path, {"runId": "managed-a", "status": "running", "runtimeManagerControl": {"ownerPid": 4321, "kind": "supervised"}})
    before = path.read_bytes()
    monkeypatch.setattr(runtime_manager_control_service, "current_runtime_manager_pid", lambda root: 4321)
    row = detail(env, "supervised_run", "managed-a")
    assert row["commands"] == ["stop", "pause"]
    def unavailable(root):
        if failed_probe:
            raise OSError("test manager unavailable")
        return 0
    monkeypatch.setattr(runtime_manager_control_service, "current_runtime_manager_pid", unavailable)
    monkeypatch.setattr(supervised_control_service, "request_stop_supervised_run", lambda rid: pytest.fail("lost manager was commanded"))
    assert detail(env, "supervised_run", "managed-a")["commands"] == []
    page = operations.read_operations(env.gateway, {"kind": "supervised_run"})
    assert page["operations"][0]["resourceId"] == "managed-a" and page["coverage"][0]["state"] == "partial"
    with pytest.raises(ManagementError, match="STATE_CONFLICT"):
        invoke(env, row, "stop")
    assert path.read_bytes() == before


@pytest.mark.parametrize("identity", ["reused", "foreign-project", "unknown"])
def test_managed_live_pid_does_not_authorize_a_reused_or_foreign_process(env, monkeypatch, identity):
    import psutil
    from core.runtime_manager import process_identity
    from core.web.services import runtime_manager_control_service, supervised_control_service
    path = env.managed.runs_dir("supervised") / "managed-a.json"
    write(path, {"runId": "managed-a", "status": "running",
        "runtimeManagerControl": {"ownerPid": 4321, "kind": "supervised"}})
    before = path.read_bytes()
    monkeypatch.setattr(runtime_manager_control_service, "current_runtime_manager_pid", lambda root: 4321)
    if identity == "reused":
        monkeypatch.setattr(process_identity, "is_runtime_manager_process", lambda pid: False)
    elif identity == "foreign-project":
        monkeypatch.setattr(psutil, "Process", lambda pid: SimpleNamespace(cwd=lambda: str(env.project / "foreign")))
    else:
        monkeypatch.setattr(psutil, "Process", lambda pid: (_ for _ in ()).throw(PermissionError("identity unavailable")))
    monkeypatch.setattr(supervised_control_service, "request_stop_supervised_run", lambda rid: pytest.fail("unowned manager received a command"))
    row = detail(env, "supervised_run", "managed-a")
    assert row["commands"] == []
    with pytest.raises(ManagementError, match="COMMAND_UNAVAILABLE"):
        invoke(env, row, "stop")
    assert path.read_bytes() == before


def test_registry_terminal_race_returns_false_receipt_instead_of_replay_error(env, monkeypatch):
    from core.web.services import runtime_task_registry
    env.tasks.save_state(runtime_task_registry.new_snapshot(kind="cli_agent", task_id="task-a", status="running"))
    row = detail(env, "runtime_task", "task-a")
    original = env.tasks.request_stop
    def finish_before_stop(task_id, initiator):
        env.tasks.mark_task_terminal(task_id, status="completed")
        return original(task_id, initiator)
    monkeypatch.setattr(env.tasks, "request_stop", finish_before_stop)
    result = invoke(env, row, "stop")
    assert result["accepted"] is False and result["stopRequested"] is False
    assert result["operation"]["status"] == "completed"


def test_corrupt_records_consume_the_source_byte_budget(env, monkeypatch):
    monkeypatch.setattr(operations, "_MAX_BYTES", 12)
    for rid in ("bad-a", "bad-b", "bad-c"):
        path = env.tasks.root / (rid + ".json")
        path.write_bytes(b"{" * 12)
    original = operations._json
    reads = []
    def counted(path, max_bytes=2 * 1024 * 1024):
        reads.append(path.name)
        return original(path, max_bytes)
    monkeypatch.setattr(operations, "_json", counted)
    page = operations.read_operations(env.gateway, {"kind": "runtime_task"})
    assert reads == ["bad-a.json"] and page["coverage"][0]["state"] == "partial"


def test_stale_session_revision_and_native_turn_replacement_cannot_stop_new_turn(env, monkeypatch):
    from core.web.services.session import control
    controller = env.sessions.SessionTurnControl(session_id="session-a", turn_id="turn-a")
    write(env.work.runs_dir("chat_turn") / "turn-a.json", {"runId": "turn-a", "sessionId": "session-a", "status": "running"})
    monkeypatch.setattr(env.sessions, "_RUNNING_SESSION_IDS", {"session-a"})
    monkeypatch.setattr(env.sessions, "_SESSION_ACTIVE_TURN_IDS", {"session-a": "turn-a"})
    monkeypatch.setattr(env.sessions, "_get_session_turn_control", lambda sid: controller)
    monkeypatch.setattr(env.sessions, "_is_session_running", lambda sid: True)
    row = detail(env, "session_turn", "turn-a", session_id="session-a")
    monkeypatch.setattr(control, "request_stop_session_turn", lambda *args, **kwargs: pytest.fail("stale stop reached native owner"))
    with pytest.raises(ManagementError, match="STATE_CONFLICT"):
        invoke(env, {**row, "revision": "stale"}, "stop", session_id="session-a")
    replacement = env.sessions.SessionTurnControl(session_id="session-a", turn_id="turn-b")
    original = operations.read_operation
    def replace_after_preflight(*args, **kwargs):
        result = original(*args, **kwargs)
        monkeypatch.setattr(env.sessions, "_get_session_turn_control", lambda sid: replacement)
        return result
    monkeypatch.setattr(operations, "read_operation", replace_after_preflight)
    with pytest.raises(ManagementError, match="STATE_CONFLICT"):
        invoke(env, row, "stop", session_id="session-a")
    assert controller.snapshot()["stopRequested"] is False
    assert replacement.snapshot()["stopRequested"] is False


@pytest.fixture
def research(env, tmp_path, monkeypatch):
    from tests._support.command_helpers import CommandHarness
    from core.web.services.team_workflow.research_runtime import formal_read_runtime, formal_write_runtime, paths
    harness = CommandHarness(tmp_path / "native-research.sqlite")
    harness.seed_run()
    harness.service.submit(harness.request())
    monkeypatch.setattr(paths, "PROJECT_ROOT", env.project)
    monkeypatch.setattr(paths, "workflow_ledger_path", lambda: harness.store.path)
    monkeypatch.setattr(formal_read_runtime, "get_formal_read_store", lambda: harness.store)
    monkeypatch.setattr(formal_write_runtime, "get_write_store", lambda: harness.store)
    monkeypatch.setattr(formal_write_runtime, "get_command_service", lambda: harness.command_service)
    closures = []
    monkeypatch.setattr(harness.command_service, "_close_cancel_run_inflight_turns", lambda rid: closures.append(rid))
    record = harness.store.get_run("run-test")
    try:
        yield SimpleNamespace(harness=harness, refs={"team_id": record.team_id, "flow_id": record.workflow_id}, closures=closures)
    finally:
        harness.close()


def test_research_real_formal_pause_resume_cancel_use_server_actor_cas_and_stable_key(env, research):
    from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
    with server_operator_scope("real-human-operator", roles=("operator",)):
        row = detail(env, "research_run", "run-test", **research.refs)
        assert row["commands"] == ["stop", "pause"]
        paused = invoke(env, row, "pause", request_id="formal-pause", **research.refs)
        assert paused["revisionCheck"] == "native_cas" and paused["operation"]["status"] == "paused"
        assert paused["operation"]["revision"] == "3" and paused["stopRequested"] is False
        replay = invoke(env, row, "pause", request_id="formal-pause", **research.refs)
        assert replay == paused
        assert research.harness.store.get_run("run-test").run_version == 3
        record = research.harness.store.get_command_by_idempotency("run-test", "formal-pause")
        request = json.loads(record.request_json)
        assert json.loads(record.requested_by_json) == {"actorType": "user", "actorId": "real-human-operator"}
        assert request["payload"] == {"reason": "launcher_assistant_operator_control"}
        assert request["command"] == "pause_run" and request["expectedRunVersion"] == 2
        with pytest.raises(ManagementError, match="idempotency_conflict"):
            invoke(env, row, "resume", request_id="formal-pause", **research.refs)
        resumed = invoke(env, paused["operation"], "resume", request_id="formal-resume", **research.refs)
        assert resumed["operation"]["status"] == "running" and resumed["operation"]["revision"] == "4"
        cancelled = invoke(env, resumed["operation"], "stop", request_id="formal-cancel", **research.refs)
        assert cancelled["operation"]["status"] == "cancelled" and cancelled["operation"]["revision"] == "5"
        assert cancelled["stopRequested"] is True and research.closures == ["run-test"]
        cleanup = research.harness.store.list_pending_outbox("run-test")
        assert any(record.idempotency_key == "cancel_run_cleanup:run-test" for record in cleanup)


@pytest.mark.parametrize("roles", [None, (), ("agent",)])
def test_research_control_without_real_privileged_operator_is_403_with_no_write(env, research, roles):
    from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
    from contextlib import nullcontext
    context = nullcontext() if roles is None else server_operator_scope("real-reader", roles=roles)
    before = research.harness.store.get_run("run-test")
    with context:
        row = detail(env, "research_run", "run-test", **research.refs)
        assert row["commands"] == []
        with pytest.raises(ManagementError, match="command_forbidden") as failure:
            invoke(env, row, "pause", request_id="denied-pause", **research.refs)
    assert failure.value.status_code == 403
    assert research.harness.store.get_run("run-test") == before
    assert research.harness.store.get_command_by_idempotency("run-test", "denied-pause") is None


@pytest.mark.parametrize("request_id", ["", "../forged", "C:/private/path", "bad key", "x" * 161])
def test_research_control_requires_trusted_out_of_band_request_key(env, research, request_id):
    from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
    with server_operator_scope("human-admin", roles=("operator",)):
        row = detail(env, "research_run", "run-test", **research.refs)
        with pytest.raises(ManagementError, match="INVALID_INPUT"):
            invoke(env, row, "pause", request_id=request_id, **research.refs)
        assert research.harness.store.get_run("run-test").run_version == 2


def test_research_formal_native_version_race_preserves_native_conflict_code(env, research, monkeypatch):
    import dataclasses
    from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
    owner = research.harness.command_service
    submit = owner.submit
    def race(request):
        submit(dataclasses.replace(request, idempotency_key="another-accepted-pause"))
        return submit(request)
    monkeypatch.setattr(owner, "submit", race)
    with server_operator_scope("human-admin", roles=("operator",)):
        row = detail(env, "research_run", "run-test", **research.refs)
        with pytest.raises(ManagementError, match="run_version_conflict"):
            invoke(env, row, "pause", request_id="raced-pause", **research.refs)
    assert research.harness.store.get_run("run-test").run_version == 3
    assert research.harness.store.get_command_by_idempotency("run-test", "raced-pause") is None


def test_external_runtime_adapter_uses_public_operator_owner_without_borrowing_task_owner(env, monkeypatch):
    from core.web.services.external_agent import service
    from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
    from tests.test_external_agent_task_service import FakeRuntime, _service
    runtime = FakeRuntime()
    owner = _service(env.external.parent, runtime)
    result = owner.start_task(owner_id="unrelated-owner-capability", adapter_connection_id="connection-a",
        capabilities=set(), agent_id="coder", task="SECRET original prompt", permission_profile="read_only",
        client_request_id="unrelated-native-request", title="", runtime_revision="runtime-a")
    monkeypatch.setattr(service, "get_default_service", lambda root: owner)
    row = detail(env, "external_task", result["taskId"])
    assert row["commands"] == []
    with pytest.raises(ManagementError, match="command_forbidden"):
        invoke(env, row, "stop")
    with server_operator_scope("real-human-operator", roles=("operator",)):
        row = detail(env, "external_task", result["taskId"])
        assert row["commands"] == ["stop"]
        stopped = invoke(env, row, "stop")
        assert stopped["operation"]["status"] == "stop_unconfirmed" and stopped["stopRequested"] is True
        assert stopped["revisionCheck"] == "preflight_only"
        assert len(runtime.stop_calls) == 1 and "SECRET" not in json.dumps(stopped)


@pytest.mark.parametrize("extra", [{"requested_by": {"actor_type": "user", "actor_id": "forged"}},
    {"idempotency_key": "model-key"}, {"request_id": "model-key"}, {"payload": {"reason": "SECRET body"}}])
def test_research_model_cannot_supply_actor_key_or_audit_reason(env, research, extra):
    from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
    with server_operator_scope("human-admin", roles=("operator",)):
        with pytest.raises(ManagementError, match="INVALID_INPUT"):
            operations.command(env.gateway, {"kind": "research_run", "resource_id": "run-test",
                "command": "pause", "expected_revision": "2", **research.refs, **extra}, request_id="trusted-key")
    assert research.harness.store.get_run("run-test").run_version == 2


def test_research_write_owner_mismatch_never_submits_to_another_ledger(env, research, tmp_path, monkeypatch):
    from core.web.services.team_workflow.research_runtime import formal_write_runtime
    from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
    monkeypatch.setattr(formal_write_runtime, "get_write_store", lambda: SimpleNamespace(path=tmp_path / "foreign.sqlite"))
    monkeypatch.setattr(research.harness.command_service, "submit", lambda request: pytest.fail("foreign ledger write"))
    with server_operator_scope("human-admin", roles=("operator",)):
        row = detail(env, "research_run", "run-test", **research.refs)
        assert row["commands"] == []
        with pytest.raises(ManagementError, match="COMMAND_UNAVAILABLE"):
            invoke(env, row, "pause", request_id="trusted-key", **research.refs)
    assert research.harness.store.get_run("run-test").run_version == 2


def test_known_team_target_outside_partial_list_still_reads_and_commands_with_cas(env, monkeypatch):
    path = native_run(env)
    older = json.loads(path.read_bytes())
    write(path.with_name("run-0.json"), {**older, "id": "run-0"})
    monkeypatch.setattr(operations, "_MAX_FILES", 1)
    page = operations.read_operations(env.gateway, {"kind": "team_run"})
    assert page["coverage"][0]["state"] == "partial" and page["operations"][0]["resourceId"] == "run-0"
    monkeypatch.setattr(operations, "_scan", lambda *args, **kwargs: pytest.fail("point read scanned history"))
    row = detail(env, "team_run", "run-a", team_id="team-a")
    before = path.read_bytes()
    with pytest.raises(ManagementError, match="STATE_CONFLICT"):
        invoke(env, {**row, "revision": "0"}, "confirm", team_id="team-a")
    assert path.read_bytes() == before
    result = invoke(env, row, "confirm", team_id="team-a")
    assert result["operation"]["revision"] == "2" and result["operation"]["status"] == "running"


def test_known_external_target_outside_partial_list_uses_public_owner_and_rejects_stale(env, monkeypatch):
    from core.web.services.external_agent import service
    from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
    from tests.test_external_agent_task_service import FakeRuntime, _service
    write(env.external / "eat-000.json", {"taskId": "eat-000", "status": "running", "revision": 1})
    runtime = FakeRuntime()
    owner = _service(env.external.parent, runtime)
    started = owner.start_task(owner_id="other-owner", adapter_connection_id="connection-a", capabilities=set(),
        agent_id="coder", task="SECRET body", permission_profile="read_only", client_request_id="external-target",
        title="", runtime_revision="runtime-a")
    monkeypatch.setattr(service, "get_default_service", lambda root: owner)
    monkeypatch.setattr(operations, "_MAX_FILES", 1)
    with server_operator_scope("human-admin", roles=("operator",)):
        page = operations.read_operations(env.gateway, {"kind": "external_task"})
        assert page["coverage"][0]["state"] == "partial" and page["operations"][0]["resourceId"] == "eat-000"
        monkeypatch.setattr(operations, "_scan", lambda *args, **kwargs: pytest.fail("point read scanned history"))
        row = detail(env, "external_task", started["taskId"])
        path = owner.store.task_path(row["resourceId"])
        before = path.read_bytes()
        with pytest.raises(ManagementError, match="STATE_CONFLICT"):
            invoke(env, {**row, "revision": "0"}, "stop")
        assert path.read_bytes() == before and runtime.stop_calls == []
        result = invoke(env, row, "stop")
        assert result["accepted"] is True and result["operation"]["status"] == "stop_unconfirmed"


def test_known_research_target_outside_partial_list_uses_bounded_sql_lookup_and_native_cas(env, research, monkeypatch):
    from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
    research.harness.seed_run("run-000")
    monkeypatch.setattr(operations, "_MAX_FILES", 1)
    with server_operator_scope("human-admin", roles=("operator",)):
        page = operations.read_operations(env.gateway, {"kind": "research_run"})
        assert page["coverage"][0]["state"] == "partial" and page["operations"][0]["resourceId"] == "run-000"
        monkeypatch.setattr(operations, "_research_runs", lambda *args: pytest.fail("point read used a global SQL list"))
        row = detail(env, "research_run", "run-test", **research.refs)
        before = research.harness.store.get_run("run-test")
        with pytest.raises(ManagementError, match="STATE_CONFLICT"):
            invoke(env, {**row, "revision": "1"}, "pause", request_id="stale-known-target", **research.refs)
        assert research.harness.store.get_run("run-test") == before
        result = invoke(env, row, "pause", request_id="pause-known-target", **research.refs)
        assert result["revisionCheck"] == "native_cas" and result["operation"]["status"] == "paused"


def test_known_registry_target_outside_partial_list_does_not_use_global_scan(env, monkeypatch):
    from core.web.services import runtime_task_registry
    for rid in ("task-a", "task-z"):
        env.tasks.save_state(runtime_task_registry.new_snapshot(kind="cli_agent", task_id=rid, status="running"))
    monkeypatch.setattr(operations, "_MAX_FILES", 1)
    page = operations.read_operations(env.gateway, {"kind": "runtime_task"})
    assert page["coverage"][0]["state"] == "partial" and page["operations"][0]["resourceId"] == "task-a"
    monkeypatch.setattr(operations, "_scan", lambda *args, **kwargs: pytest.fail("point read scanned history"))
    row = detail(env, "runtime_task", "task-z")
    result = invoke(env, row, "stop")
    assert result["stopRequested"] is True and env.tasks.load_state("task-z")["stopInitiator"] == "user"


@pytest.mark.parametrize("rid", ["C:stream", "task.", "CON", "NUL.json", "COM1"])
def test_file_owner_unsafe_ids_are_rejected_before_any_owner_or_path_access(env, monkeypatch, rid):
    monkeypatch.setattr(env.gateway, "_owners", lambda: pytest.fail("unsafe ID reached owner resolution"))
    with pytest.raises(ManagementError, match="INVALID_INPUT"):
        detail(env, "runtime_task", rid)


def test_point_read_does_not_trust_a_snapshot_filename_with_another_native_id(env):
    write(env.tasks.task_state_path("task-a"), {"taskId": "task-other", "kind": "cli_agent", "status": "running"})
    with pytest.raises(ManagementError, match="OPERATION_SOURCE_UNAVAILABLE"):
        detail(env, "runtime_task", "task-a")


def test_point_read_rejects_linked_native_snapshot(env, tmp_path):
    import os
    path = env.tasks.task_state_path("task-a")
    write(path, {"taskId": "task-a", "kind": "cli_agent", "status": "running"})
    os.link(path, tmp_path / "other-hardlink.json")
    with pytest.raises(ManagementError, match="OPERATION_SOURCE_UNAVAILABLE"):
        detail(env, "runtime_task", "task-a")


def test_persisted_session_without_current_native_controller_cannot_advertise_stop(env):
    write(env.work.runs_dir("chat_turn") / "queued-turn.json", {"runId": "queued-turn", "sessionId": "queued-session", "status": "queued"})
    row = detail(env, "session_turn", "queued-turn", session_id="queued-session")
    assert row["status"] == "queued" and row["commands"] == []
    with pytest.raises(ManagementError, match="COMMAND_UNAVAILABLE"):
        invoke(env, row, "stop", session_id="queued-session")
