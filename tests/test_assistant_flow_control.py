"""Existing Flow definitions use native CAS, admission and bounded read views."""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from core.web.services.external_management.flow_control import FlowControl
from core.web.services.external_management import flow_control
from core.web.services.external_management.flow_contracts import (
    FLOW_ACTION_MODELS, FLOW_ACTION_SCOPES, FlowListQuery, FlowListResponse,
    FlowMutationResponse, FlowReadQuery, FlowReadResponse, FlowSave, FlowStart,
)
from core.web.services.external_management.service import ManagementError
from core.web.services.team_workflow.generic import service, store
from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
from tests.test_launcher_assistant_runtime_operations import env


def definition(**updates):
    return {"id": "flow-a", "name": "已有团队流程", "fields": [],
            "steps": [{"id": "review", "label": "人工确认", "kind": "human"}], **updates}


def test_save_uses_native_cas_and_exact_readback(env):
    control = FlowControl(env.gateway)
    with server_operator_scope("real-operator", roles=("operator",)):
        result = control.save_flow({"team_id": "team-a", "flow_id": "flow-a",
                                    "flow": definition(), "expectedRevision": 0})
    assert result["verified"] is True and result["status"] == "saved" and result["revision"] == 1
    assert store.read(store.path("team-a", "flows", "flow-a"))["revision"] == 1
    page = control.read_flow(FlowReadQuery(team_id="team-a", flow_id="flow-a"))
    assert page["revision"] == 1 and len(page["digest"]) == 64


def save_native(flow=None, revision=0):
    return service.save_flow("team-a", (flow or {}).get("id", "flow-a"),
                             {"flow": flow or definition(), "expectedRevision": revision})


def test_stale_save_cas_never_changes_existing_definition(env):
    save_native()
    path = store.path("team-a", "flows", "flow-a")
    original = path.read_bytes()
    with server_operator_scope("real-operator"), pytest.raises(ManagementError, match="STATE_CONFLICT"):
        FlowControl(env.gateway).save_flow({"team_id": "team-a", "flow_id": "flow-a",
            "flow": definition(name="different"), "expectedRevision": 0})
    assert path.read_bytes() == original


@pytest.mark.parametrize("action", ["save", "start"])
def test_missing_server_operator_cannot_mutate(env, action):
    save_native()
    control = FlowControl(env.gateway)
    with pytest.raises(ManagementError, match="OPERATOR_REQUIRED"):
        if action == "save":
            control.save_flow({"team_id": "team-a", "flow_id": "flow-a",
                               "flow": definition(), "expectedRevision": 1})
        else:
            control.start_flow({"team_id": "team-a", "flow_id": "flow-a", "expectedRevision": 1}, request_id="request-a")
    assert not service.list_runs("team-a")["runs"]


@pytest.mark.parametrize("extra", ["approved", "operator", "owner", "path", "force", "localIntegration", "idempotencyKey"])
def test_write_contracts_reject_model_authority_and_arbitrary_replay_keys(extra):
    for model, body in ((FlowSave, {"team_id": "team-a", "flow_id": "flow-a", "flow": definition(), "expectedRevision": 0}),
                        (FlowStart, {"team_id": "team-a", "flow_id": "flow-a", "expectedRevision": 1})):
        with pytest.raises(ValidationError):
            model.model_validate({**body, extra: "forged"})


@pytest.mark.parametrize("parameters", [
    {"team_id": "../team-a", "flow_id": "flow-a", "expectedRevision": 1},
    {"team_id": "team-a", "flow_id": "../flow-a", "expectedRevision": 1},
    {"team_id": "team-a", "flow_id": "flow-a", "expectedRevision": True},
    {"team_id": "team-a", "flow_id": "flow-a", "expectedRevision": "1"},
    {"team_id": "team-a", "flow_id": "flow-a", "expectedRevision": 1, "values": {"goal": 7}},
])
def test_closed_native_start_types(parameters):
    with pytest.raises(ValidationError):
        FlowStart.model_validate(parameters)


def test_nested_native_definition_extra_and_identity_mismatch_are_rejected():
    for flow in (definition(approval=True), definition(id="other"),
                 definition(steps=[{"id": "step", "kind": "human", "label": "step", "approved": True}])):
        with pytest.raises(ValidationError):
            FlowSave(team_id="team-a", flow_id="flow-a", flow=flow, expectedRevision=0)
    assert set(FLOW_ACTION_MODELS) == {"flow_save", "flow_start"}
    assert FLOW_ACTION_SCOPES == {"flow_save": "teams:flows:write", "flow_start": "teams:flows:run"}


def test_real_start_freezes_definition_and_reuses_native_request_identity(env):
    saved = save_native(definition(fields=[{"id": "goal", "label": "目标", "kind": "text", "required": True}]))
    control = FlowControl(env.gateway)
    parameters = {"team_id": "team-a", "flow_id": "flow-a", "expectedRevision": saved["revision"],
                  "values": {"goal": "untrusted goal"}}
    with server_operator_scope("real-operator"):
        first = control.start_flow(parameters, request_id="managed-project-action-key")
        second = control.start_flow(parameters, request_id="managed-project-action-key")
        assert first == second and first["verified"] is True and first["status"] == "running"
        assert first["teamId"] == "team-a" and first["flowId"] == "flow-a" and first["runId"].startswith("run-")
        with pytest.raises(ManagementError, match="STATE_CONFLICT"):
            control.start_flow({**parameters, "values": {"goal": "changed"}}, request_id="managed-project-action-key")
    runs = service.list_runs("team-a")["runs"]
    assert len(runs) == 1 and runs[0]["flow"] == saved and runs[0]["values"] == parameters["values"]
    assert "untrusted goal" not in json.dumps(first)
    assert FlowMutationResponse.model_validate(first).runId == first["runId"]
    save_native(definition(fields=[{"id": "goal", "label": "目标", "kind": "text", "required": True}],
                           name="later editor change"), revision=1)
    with server_operator_scope("real-operator"):
        assert control.start_flow(parameters, request_id="managed-project-action-key") == first


@pytest.mark.parametrize("values", [{}, {"other": "x"}, {"goal": "x" * 12001}])
def test_start_uses_native_input_validation_without_admission(env, values):
    save_native(definition(fields=[{"id": "goal", "label": "目标", "kind": "text", "required": True}]))
    with server_operator_scope("real-operator"), pytest.raises(ManagementError, match="FLOW_START_UNCONFIRMED"):
        FlowControl(env.gateway).start_flow({"team_id": "team-a", "flow_id": "flow-a", "expectedRevision": 1,
                                            "values": values}, request_id="request-a")
    assert not service.list_runs("team-a")["runs"]


def test_start_rejects_stale_version_and_wrong_step_owner(env):
    save_native()
    control = FlowControl(env.gateway)
    with server_operator_scope("real-operator"), pytest.raises(ManagementError, match="STATE_CONFLICT"):
        control.start_flow({"team_id": "team-a", "flow_id": "flow-a", "expectedRevision": 2}, request_id="request-a")
    bad = definition(steps=[{"id": "work", "label": "工作", "kind": "agent", "owner": "outside-team"}])
    save_native(bad, revision=1)
    with server_operator_scope("real-operator"), pytest.raises(ManagementError, match="FLOW_START_UNCONFIRMED"):
        control.start_flow({"team_id": "team-a", "flow_id": "flow-a", "expectedRevision": 2}, request_id="request-a")
    assert not service.list_runs("team-a")["runs"]


def test_save_preserves_existing_recovery_policy_but_cannot_grant_or_change_it(env):
    policy = {"repairFlowId": "repair", "directorAgentId": "director", "reviewerAgentId": "reviewer"}
    control = FlowControl(env.gateway)
    with server_operator_scope("real-operator"), pytest.raises(ManagementError, match="FLOW_RECOVERY_AUTHORIZATION_REQUIRED"):
        control.save_flow({"team_id": "team-a", "flow_id": "flow-a", "flow": definition(failureRecovery=policy), "expectedRevision": 0})
    save_native(definition(failureRecovery=policy))
    preserved = store.read(store.path("team-a", "flows", "flow-a"))["failureRecovery"]
    with server_operator_scope("real-operator"):
        result = control.save_flow({"team_id": "team-a", "flow_id": "flow-a",
                                   "flow": definition(name="renamed", failureRecovery=preserved), "expectedRevision": 1})
        assert result["verified"] and result["revision"] == 2
        with pytest.raises(ManagementError, match="FLOW_RECOVERY_AUTHORIZATION_REQUIRED"):
            control.save_flow({"team_id": "team-a", "flow_id": "flow-a", "flow": definition(), "expectedRevision": 2})


def test_save_readback_needs_exact_native_result_not_current_similarity(env, monkeypatch):
    original = service.save_flow

    def misleading(*args):
        result = original(*args)
        return {**result, "revision": result["revision"] + 1}

    monkeypatch.setattr(service, "save_flow", misleading)
    with server_operator_scope("real-operator"), pytest.raises(ManagementError, match="FLOW_SAVE_UNCONFIRMED"):
        FlowControl(env.gateway).save_flow({"team_id": "team-a", "flow_id": "flow-a", "flow": definition(), "expectedRevision": 0})
    assert store.read(store.path("team-a", "flows", "flow-a"))["revision"] == 1


def test_flow_list_exceeds_one_hundred_and_uses_actual_page_length(env):
    for index in range(103):
        save_native(definition(id=f"flow-{index:03d}", name='"' * 160))
    control, seen, offset, fingerprint = FlowControl(env.gateway), [], 0, None
    while True:
        page = control.list_flows(FlowListQuery(team_id="team-a", offset=offset, limit=10, expected_digest=fingerprint))
        assert page["complete"] and not page["truncated"] and page["total"] == 103
        assert page["limit"] == len(page["flows"]) and flow_control._size(page) <= 3400
        FlowListResponse.model_validate(page)
        seen.extend(row["flowId"] for row in page["flows"])
        fingerprint = page["digest"]
        if page["nextOffset"] is None:
            break
        offset = page["nextOffset"]
    assert seen == [f"flow-{index:03d}" for index in range(103)]


def test_invalid_flow_remains_discoverable_and_scan_budgets_are_explicit(env, monkeypatch):
    save_native()
    path = store.path("team-a", "flows", "broken")
    path.write_text("{bad", encoding="utf-8")
    control = FlowControl(env.gateway)
    page = control.list_flows({"team_id": "team-a"})
    assert not page["complete"] and page["unavailableCount"] == 1 and page["total"] == 2
    assert next(row for row in page["flows"] if row["flowId"] == "broken")["available"] is False
    monkeypatch.setattr(flow_control, "_MAX_FILES", 1)
    page = control.list_flows({"team_id": "team-a"})
    assert page["truncated"] is True and page["complete"] is False
    monkeypatch.setattr(flow_control, "_MAX_BYTES", 1)
    page = control.list_flows({"team_id": "team-a"})
    assert page["truncated"] is True and page["complete"] is False
    assert page["total"] == 1 and page["flows"][0]["available"] is False
    monkeypatch.setattr(flow_control, "_MAX_FILES", 10000)
    page = control.list_flows({"team_id": "team-a"})
    assert {row["flowId"] for row in page["flows"]} == {"broken", "flow-a"}
    assert page["total"] == page["unavailableCount"] == 2


def test_oversized_flow_is_an_explicit_placeholder_and_does_not_hide_later_ids(env, monkeypatch):
    save_native()
    store.path("team-a", "flows", "aaa-oversized").write_text("x" * 1001, encoding="utf-8")
    monkeypatch.setattr(flow_control, "_MAX_FILE", 1000)
    page = FlowControl(env.gateway).list_flows({"team_id": "team-a"})
    assert page["total"] == 2 and page["unavailableCount"] == 1 and page["complete"] is False
    assert page["flows"][0]["flowId"] == "aaa-oversized" and page["flows"][0]["available"] is False
    assert page["flows"][1]["flowId"] == "flow-a" and page["flows"][1]["available"] is True


def test_flow_node_paging_is_bounded_and_complete_without_session_reads(env, monkeypatch):
    text = '"\\' * 4000
    save_native(definition(steps=[{"id": "step", "label": "step", "kind": "human", "instruction": text}]))
    monkeypatch.setattr(env.sessions, "get_session_detail", lambda *a, **kw: pytest.fail("private Session body read"))
    control, offset, digest_value, parts = FlowControl(env.gateway), 0, None, []
    while True:
        page = control.read_flow(FlowReadQuery(team_id="team-a", flow_id="flow-a", pointer="/steps/0/instruction",
            offset=offset, limit=512, expected_digest=digest_value))
        assert flow_control._size(page) <= 3400 and page["source"] == "native-flow-definition"
        assert page["untrustedContent"] is True and page["nodeType"] == "string"
        FlowReadResponse.model_validate(page)
        parts.append(page["value"])
        digest_value = page["digest"]
        if page["nextOffset"] is None:
            break
        offset = page["nextOffset"]
    assert "".join(parts) == text
    root = control.read_flow({"team_id": "team-a", "flow_id": "flow-a", "limit": 1})
    assert root["limit"] == 1 and root["nextOffset"] == 1


def test_definition_and_directory_digest_reject_changed_sources(env):
    save_native()
    control = FlowControl(env.gateway)
    original = control.read_flow({"team_id": "team-a", "flow_id": "flow-a"})
    directory = control.list_flows({"team_id": "team-a"})
    save_native(definition(name="changed"), revision=1)
    with pytest.raises(ManagementError, match="FLOW_CHANGED"):
        control.read_flow({"team_id": "team-a", "flow_id": "flow-a", "expected_digest": original["digest"]})
    with pytest.raises(ManagementError, match="FLOW_DIRECTORY_CHANGED"):
        control.list_flows({"team_id": "team-a", "expected_digest": directory["digest"]})


@pytest.mark.parametrize("pointer", ["bad", "/bad~2", "/steps/01", "/steps/-", "/missing"])
def test_invalid_and_noncanonical_flow_pointers_never_enter_other_data(env, pointer):
    save_native()
    with pytest.raises(ManagementError, match="INVALID_INPUT|FLOW_NODE_UNAVAILABLE"):
        FlowControl(env.gateway).read_flow({"team_id": "team-a", "flow_id": "flow-a", "pointer": pointer})


def test_project_binding_and_team_owner_changes_invalidate_save_ack(env, monkeypatch):
    control = FlowControl(env.gateway)
    original = service.save_flow

    def changed(*args):
        result = original(*args)
        from core.web.services.team import team_store
        index = team_store._load_index()
        index["teams"][0]["members"].append({"agentId": "new-owner"})
        (env.workspace / "teams" / "teams.json").write_text(json.dumps(index), encoding="utf-8")
        return result

    monkeypatch.setattr(service, "save_flow", changed)
    with server_operator_scope("real-operator"), pytest.raises(ManagementError, match="FLOW_SAVE_UNCONFIRMED"):
        control.save_flow({"team_id": "team-a", "flow_id": "flow-a", "flow": definition(), "expectedRevision": 0})
    monkeypatch.setattr(env.gateway, "project_root", env.project / "different")
    with pytest.raises(ManagementError, match="TARGET_BINDING_CHANGED"):
        control.list_flows({"team_id": "team-a"})


def test_closed_read_response_rejects_oversized_wire_body_and_extra_fields(env):
    save_native()
    page = FlowControl(env.gateway).read_flow({"team_id": "team-a", "flow_id": "flow-a"})
    with pytest.raises(ValidationError):
        FlowReadResponse.model_validate({**page, "value": "x" * 5000})
    with pytest.raises(ValidationError):
        FlowReadResponse.model_validate({**page, "sessionBody": "private content"})
    with pytest.raises(ValidationError):
        FlowReadResponse.model_validate({**page, "untrustedContent": 1})


def test_invalid_flow_namespace_is_unavailable_without_repair(env):
    folder = env.workspace / "teams" / "team-a" / "generic-workflows"
    folder.mkdir(parents=True)
    (folder / "flows").write_text("not a directory", encoding="utf-8")
    with pytest.raises(ManagementError, match="FLOW_DIRECTORY_UNAVAILABLE"):
        FlowControl(env.gateway).list_flows({"team_id": "team-a"})
    assert (folder / "flows").read_text(encoding="utf-8") == "not a directory"


def test_step_owner_validation_uses_native_roster_without_granting_tools(env, monkeypatch):
    from core.web.services import agent_directory_service
    from core.web.services.team import team_store

    agent = {"agentId": "member-a", "toolPolicy": {"allowedTools": ["read_file"], "writeRoots": []}}
    monkeypatch.setattr(agent_directory_service, "get_agent", lambda agent_id, **kw: agent if agent_id == "member-a" else None)
    control = FlowControl(env.gateway)
    flow = definition(steps=[{"id": "work", "label": "工作", "kind": "agent", "owner": "member-a"}])
    with server_operator_scope("real-operator"):
        with pytest.raises(ManagementError, match="FLOW_SAVE_UNCONFIRMED"):
            control.save_flow({"team_id": "team-a", "flow_id": "flow-a", "flow": flow, "expectedRevision": 0})
        team_store._load_index()["teams"][0]["members"].append({"agentId": "member-a"})
        assert control.save_flow({"team_id": "team-a", "flow_id": "flow-a", "flow": flow,
                                  "expectedRevision": 0})["verified"] is True
        assert control.start_flow({"team_id": "team-a", "flow_id": "flow-a", "expectedRevision": 1},
                                  request_id="managed-owner-check")["status"] == "running"
    assert agent["toolPolicy"] == {"allowedTools": ["read_file"], "writeRoots": []}


def test_start_revalidates_binding_after_definition_read_before_native_effect(env, monkeypatch):
    save_native()
    control = FlowControl(env.gateway)
    read = control._flow

    def changed(*args):
        flow = read(*args)
        env.gateway.project_root = env.project / "changed-binding"
        return flow

    monkeypatch.setattr(control, "_flow", changed)
    with server_operator_scope("real-operator"), pytest.raises(ManagementError, match="TARGET_BINDING_CHANGED"):
        control.start_flow({"team_id": "team-a", "flow_id": "flow-a", "expectedRevision": 1}, request_id="request-a")
    assert not service.list_runs("team-a")["runs"]


@pytest.mark.parametrize("operation", ["list", "get"])
@pytest.mark.parametrize("condition", [
    "existing", "missing_workspace", "missing_teams", "missing_index", "bad_index_json",
    "bad_index_shape", "duplicate_team_ids", "missing_team", "developer_no_active",
    "developer_missing_workspace", "developer_missing_teams", "developer_missing_index",
    "developer_bad_index", "developer_existing",
])
def test_flow_reads_never_initialize_repair_or_seed(tmp_path, monkeypatch, operation, condition):
    from types import SimpleNamespace

    from core.infrastructure import developer_sandbox
    from core.web.services import agent_directory_service as directory, team_service
    from core.web.services.team import team_store
    from core.web.services.team_workflow.generic.models import Flow

    project = tmp_path / "project"
    project.mkdir()
    formal = tmp_path / "formal" / "workspace"
    config = tmp_path / "operator.toml"
    developer = condition.startswith("developer_")
    config.write_text("[launcher.developer_mode]\nenabled = " + ("true" if developer else "false") + "\n", encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "data"))
    for owner in (directory, team_service, developer_sandbox):
        monkeypatch.setattr(owner, "PROJECT_ROOT", project)
    monkeypatch.setattr(directory, "CONFIG_PATH", config)
    monkeypatch.setattr(developer_sandbox, "CONFIG_PATH", config)
    monkeypatch.setattr(developer_sandbox, "formal_workspace_path", lambda _root, *parts: formal.joinpath(*parts))

    def write_existing(workspace, *, partial="", label="formal-flow"):
        if partial == "missing_workspace":
            return
        workspace.mkdir(parents=True)
        if partial == "missing_teams":
            return
        teams = workspace / "teams"
        teams.mkdir()
        index = teams / "teams.json"
        team = {"teamId": "team-a", "status": "active", "members": []}
        if partial == "bad_index_json":
            index.write_text("{broken", encoding="utf-8")
        elif partial == "bad_index_shape":
            index.write_text(json.dumps({"teams": [None]}), encoding="utf-8")
        elif partial == "duplicate_team_ids":
            index.write_text(json.dumps({"teams": [team, team]}), encoding="utf-8")
        elif partial == "missing_team":
            index.write_text(json.dumps({"teams": []}), encoding="utf-8")
        elif partial != "missing_index":
            index.write_text(json.dumps({"schemaVersion": 1, "teams": [team]}), encoding="utf-8")
        # Even an orphaned valid definition must not authorize index repair.
        folder = teams / "team-a" / "generic-workflows" / "flows"
        folder.mkdir(parents=True)
        flow = Flow.model_validate(definition(name=label, revision=1, updatedAt="2026-11-02T00:00:00Z"))
        (folder / "flow-a.json").write_text(json.dumps(flow.model_dump()), encoding="utf-8")

    if developer:
        # A readable formal copy must neither become a fallback nor seed a
        # missing active sandbox/workspace/authority during the query.
        write_existing(formal)
        if condition != "developer_no_active":
            active = developer_sandbox._active_state_path(project)
            active.parent.mkdir(parents=True, exist_ok=True)
            active.write_text(json.dumps({"schemaVersion": 1, "sandboxId": "sandbox-existing"}), encoding="utf-8")
            active_workspace = developer_sandbox._sandbox_root(project, "sandbox-existing") / "workspace"
            partial = condition.removeprefix("developer_")
            if partial == "bad_index":
                partial = "bad_index_json"
            write_existing(active_workspace, partial=partial, label="active-flow")
    else:
        write_existing(formal, partial=condition)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Flow read invoked native hydration, initialization, seeding, repair or a writer")

    for name in ("get_agent", "list_agents", "load_state", "save_state", "repair_agent_directory"):
        monkeypatch.setattr(directory, name, forbidden)
    for owner, names in ((team_service, ("_load_index", "_teams_root", "list_teams_compact")),
                         (team_store, ("_load_index", "_teams_root", "_save_index", "_write_json")),
                         (store, ("team", "write")),
                         (service, ("save_flow", "start_run")),
                         (developer_sandbox, ("_ensure_active_state", "seeded_sandbox_workspace_path", "sandboxed_workspace_path"))):
        for name in names:
            monkeypatch.setattr(owner, name, forbidden)

    def inventory():
        return {str(path.relative_to(tmp_path)): (path.is_dir(), path.stat().st_mtime_ns,
                    None if path.is_dir() else path.read_bytes())
                for path in (tmp_path, *sorted(tmp_path.rglob("*")))}

    control = FlowControl(SimpleNamespace(project_root=project, _owners=lambda: directory))
    query = (lambda: control.list_flows({"team_id": "team-a"})) if operation == "list" else (
        lambda: control.read_flow({"team_id": "team-a", "flow_id": "flow-a", "pointer": "/name"}))
    before = inventory()
    with server_operator_scope("operator-test", roles=("operator",)):
        if condition in {"existing", "developer_existing"}:
            result = query()
            assert result["untrustedContent"] is True
            expected = "active-flow" if developer else "formal-flow"
            assert (result["flows"][0]["name"] if operation == "list" else result["value"]) == expected
        else:
            with pytest.raises(ManagementError) as unavailable:
                query()
            assert unavailable.value.code.endswith("UNAVAILABLE")
    assert inventory() == before


def _authorized_flow_management(env, root):
    from core.web.services.external_management.service import ManagementService, TargetIdentity
    binding = {"projectId": "flow-project", "instanceId": "flow-instance"}
    identity = lambda: TargetIdentity(binding, "native-flow-authority")
    management = ManagementService(root, identity=identity, native=env.gateway)
    grant = management.bind({"client_id": "flow-management-test", "expected_binding": binding,
                             "scopes": ["agents:read"]})
    credentials = (grant["subject_id"], grant["subject_capability"])
    upgraded = management.invoke(*credentials, "authorization_upgrade", {
        "request_id": "grant-flow-control", "expected_binding": binding,
        "parameters": {"expected_scopes": ["agents:read"],
                       "add_scopes": ["teams:flows:run", "teams:flows:write"]}})
    assert upgraded["verified"] is True
    return management, credentials, binding


@pytest.mark.parametrize("action", ["flow_save", "flow_start"])
@pytest.mark.parametrize("failure", ["lost_ack", "readback", "owner_changed"])
def test_management_flow_post_write_failures_are_unknown_and_never_replayed(env, tmp_path, monkeypatch, action, failure):
    """Historical admission proof may recover; missing proof never permits replay."""
    from core.web.services.external_management.service import ManagementService
    from core.web.services.team import team_store

    if action == "flow_start":
        save_native()
    management, credentials, binding = _authorized_flow_management(env, tmp_path / "flow-management")
    parameters = {"team_id": "team-a", "flow_id": "flow-a", "expectedRevision": 0 if action == "flow_save" else 1}
    if action == "flow_save":
        parameters["flow"] = definition()
    payload = {"request_id": "one-original-flow-request", "expected_binding": binding, "parameters": parameters}
    method = "save_flow" if action == "flow_save" else "start_run"
    original = getattr(service, method)
    native_results = []

    def write_then_lose_proof(*args, **kwargs):
        result = original(*args, **kwargs)
        native_results.append(result)
        if failure == "lost_ack":
            raise OSError("Native Flow acknowledgement was lost after commit")
        if failure == "owner_changed":
            index = team_store._load_index()
            index["teams"][0]["members"].append({"agentId": "later-owner"})
            (env.workspace / "teams" / "teams.json").write_text(json.dumps(index), encoding="utf-8")
        return result

    monkeypatch.setattr(service, method, write_then_lose_proof)
    if failure == "readback":
        # save reads the committed definition; start verifies the original
        # owner again after the native run has been durably admitted.
        if action == "flow_save":
            readback = FlowControl._flow
            def unavailable_flow(*args):
                if native_results:
                    raise OSError("Committed Flow readback is temporarily unavailable")
                return readback(*args)
            monkeypatch.setattr(FlowControl, "_flow", staticmethod(unavailable_flow))
        else:
            verify = FlowControl._verify
            def unavailable_owner(self, *args):
                if native_results:
                    raise OSError("Run owner readback is temporarily unavailable")
                return verify(self, *args)
            monkeypatch.setattr(FlowControl, "_verify", unavailable_owner)
    with server_operator_scope("real-operator", roles=("operator",)):
        first = management.invoke(*credentials, action, payload)
    assert first == {"status": "unknown", "action": action, "requestId": payload["request_id"],
                     "verified": False, "reused": False, "code": "OPERATION_UNCONFIRMED"}
    restarted = ManagementService(management.root, identity=management.identity, native=env.gateway)
    historical_admission = action == "flow_start" and failure in {"lost_ack", "owner_changed"}
    expected = restarted.receipt(*credentials, action, payload["request_id"])
    if historical_admission:
        assert expected["status"] == "completed" and expected["verified"] is True and expected["reused"] is True
        assert expected["action"] == action and expected["requestId"] == payload["request_id"]
        proof = expected["flow"]
        assert proof["teamId"] == "team-a" and proof["flowId"] == "flow-a"
        assert proof["runId"] == native_results[0]["id"]
        # This proves the original request's admission, not current-owner
        # reauthorization or completion of the business workflow.
        assert proof["status"] == "running" and proof["verified"] is True
    else:
        assert expected == {**first, "reused": True}
    assert restarted.invoke(*credentials, action, payload) == expected
    assert management.invoke(*credentials, action, payload) == expected
    assert len(native_results) == 1
    assert store.read(store.path("team-a", "flows", "flow-a"))["revision"] == 1
    runs = service.list_runs("team-a")["runs"]
    assert len(runs) == (1 if action == "flow_start" else 0)
    if runs:
        assert runs[0]["id"] == native_results[0]["id"]
    key = management._request_key(credentials[0], action, payload["request_id"])
    record = management.store.read(management.store.path("requests", key))
    assert "failure" not in record and ("receipt" in record) == historical_admission
    reconciliation = restarted.reconcile_request(*credentials, action, payload["request_id"])
    assert reconciliation["state"] == ("confirmed" if historical_admission else "requires_review")
    assert reconciliation["verified"] is historical_admission
    assert reconciliation["requiresReview"] is not historical_admission
