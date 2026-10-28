"""Operator-authenticated neutral subjects; all native side effects stay fake."""
from __future__ import annotations

from copy import deepcopy
from threading import RLock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import launcher_assistant_management as route
from core.web.services.external_management.service import (
    ManagementError,
    ManagementService,
    TargetIdentity,
)

BINDING = {"projectId": "target-project", "instanceId": "target-instance"}
PREFIX = "/api/v1/launcher-assistant-management"


def test_session_config_documentation_only_advertises_its_neutral_read_subset():
    from core.web.services.external_management.documentation import _entry
    for path in (PREFIX + "/sessions/{session_id}/config", PREFIX + "/sessions/{session_id}/config-comparison",
                 "/api/sessions/{session_id}/llm-options", "/api/sessions/{session_id}/budget-parameters"):
        entry = _entry({"operationId": "read", "method": "GET", "path": path, "summary": "read", "tags": ["sessions"]})
        assert entry["executable"] is (path.startswith(PREFIX))
        if entry["executable"]:
            expected = "session_config_compare" if path.endswith("comparison") else "session_config_get"
            assert entry["action"] == expected and entry["capabilitySubset"] is True
        else:
            assert "action" not in entry


class FakeNative:
    def __init__(self):
        self.agents = {}
        self.calls = []
        self.lost_ack = False
        self.incomplete = False
        self.compiled_wide = False

    def read(self, agent_id):
        return deepcopy(self.agents.get(agent_id))

    def find_created(self, key):
        return [deepcopy(agent) for agent in self.agents.values()
                if (agent.get("metadata", {}).get("externalManagementCreation") or {}).get("requestKey") == key]

    def compiled(self, agent_id, session_id):
        agent = self.agents[agent_id]
        config = {key: deepcopy(agent[key]) for key in ("displayName", "permissionPreset", "taskProfile", "toolPolicy", "delegationPolicy", "llmBindings")}
        if self.compiled_wide:
            config.update(taskProfile={}, toolPolicy={"allowedTools": ["stale-wide-tool"], "networkAccess": "inherit", "mutationAccess": "inherit"})
        return config

    def current_compiled(self, agent_id):
        return self.compiled(agent_id, self.agents[agent_id]["directSessionId"])

    def create(self, parameters, marker):
        from core.web.services.external_management.contracts import agent_create_tool_policy
        self.calls.append("create")
        agent = {"agentId": "agent-1", "directSessionId": "real-target-session", "displayName": parameters["display_name"],
                 "roleKey": "assistant_worker", "status": "active", "configRevision": 1, "updatedAt": "v1",
                 "llmBindings": {"dialogue": {"modelId": parameters["model_id"]}},
                 "taskProfile": {"mission": parameters["mission"]}, "toolPolicy": agent_create_tool_policy(parameters.get("capability_preset")),
                 "delegationPolicy": {"allowSubagents": False, "allowWakeMessages": False},
                 "permissionPreset": "request_approval", "metadata": {"externalManagementCreation": marker,
                     "delegationPolicy": {"allowSubagents": False, "allowWakeMessages": False}}}
        if self.incomplete:
            agent["toolPolicy"]["allowedTools"] = ["unsafe"]
        self.agents["agent-1"] = agent
        if self.lost_ack:
            raise RuntimeError("private path secret")
        return deepcopy(agent)

    def update(self, parameters, marker):
        self.calls.append("update")
        agent = self.agents[parameters["agent_id"]]
        if agent["configRevision"] != parameters["expected_config_revision"]:
            raise ManagementError("STATE_CONFLICT", 409)
        agent.update(parameters["updates"])
        agent["metadata"]["externalManagementMutation"] = marker
        agent["configRevision"] += 1
        agent["updatedAt"] = "v2"
        if self.lost_ack:
            raise RuntimeError("secret")
        return deepcopy(agent)

    def avatar(self, parameters, marker):
        self.calls.append("avatar")
        agent = self.agents[parameters["agent_id"]]
        if agent["updatedAt"] != parameters["expected_updated_at"]:
            raise ManagementError("STATE_CONFLICT", 409)
        agent["avatarImagePath"] = parameters["avatar_image_path"]
        agent["metadata"]["externalManagementMutation"] = marker
        return deepcopy(agent)


@pytest.fixture
def harness(tmp_path, monkeypatch):
    native = FakeNative()
    identity = lambda: TargetIdentity(BINDING, "canonical-target-storage")
    service = ManagementService(tmp_path / "management", identity=identity, native=native)
    monkeypatch.setattr(route, "_SERVICE", service)
    app = FastAPI()
    app.include_router(route.router, prefix="/api")
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    control = {CONTROL_TOKEN_HEADER: get_control_token()}

    def bind(scopes=None, **changes):
        body = {"client_id": "stable-native-client", "expected_binding": BINDING,
                "scopes": scopes or ["agents:read", "agents:create", "agents:update", "agents:avatar"]}
        body.update(changes)
        return client.post(PREFIX + "/subjects/bind", headers=control, json=body)

    def headers(grant):
        return {**control, route.SUBJECT_HEADER: grant["subject_id"], route.CAPABILITY_HEADER: grant["subject_capability"]}

    def invoke(grant, action="agent_create", request_id="stable-create", parameters=None, **changes):
        body = {"request_id": request_id, "expected_binding": BINDING,
                "parameters": parameters or {"display_name": "Worker", "model_id": "provider/model", "mission": "Report evidence."}}
        body.update(changes)
        return client.post(PREFIX + "/actions/" + action, headers=headers(grant), json=body)

    return client, service, native, control, bind, headers, invoke


def test_control_precedes_binding_and_action_authorization(harness):
    client, _, native, _, _, _, _ = harness
    for path, body in [("/subjects/bind", {}), ("/actions/agent_create", {})]:
        response = client.post(PREFIX + path, headers={CONTROL_TOKEN_HEADER: "bad"}, json=body)
        assert response.status_code == 403
    assert client.get(PREFIX + "/binding").status_code == 403
    assert not native.calls


def test_bind_is_operator_grant_and_recovers_same_private_credential(harness):
    _, _, native, _, bind, _, _ = harness
    first = bind().json()
    assert bind().json() == first
    assert first["subject_id"].startswith("ops-")
    assert not {"agentId", "sessionId", "personalAssistantId"} & set(first)
    assert not native.calls
    assert bind(expected_binding={**BINDING, "instanceId": "foreign"}).status_code == 409
    assert bind(scopes=["agents:read"]).status_code == 409
    assert bind(scopes=["knowledge:write"]).status_code == 422


def test_bad_capability_binding_and_scope_never_reach_native(harness):
    client, _, native, _, bind, headers, invoke = harness
    grant = bind(scopes=["agents:read"]).json()
    assert invoke(grant).status_code == 403
    bad = {**headers(grant), route.CAPABILITY_HEADER: "task-capability-is-not-an-operator-grant"}
    assert client.get(PREFIX + "/agents/agent-1", headers=bad).status_code == 403
    grant = bind(client_id="write-client").json()
    assert invoke(grant, expected_binding={**BINDING, "projectId": "foreign"}).status_code == 409
    assert client.post(PREFIX + "/subjects/bind", headers={route.CAPABILITY_HEADER: grant["subject_capability"]}, json={}).status_code == 403
    assert not native.calls


@pytest.mark.parametrize("injection", [{"owner": "fake-agent"}, {"governed": True}, {"nativeApproval": True},
                                       {"url": "http://outside"}, {"path": "C:/private"}, {"toolPolicy": {"allowedTools": ["run"]}}])
def test_create_rejects_parameter_injection(harness, injection):
    _, _, native, _, bind, _, invoke = harness
    grant = bind().json()
    response = invoke(grant, parameters={"display_name": "Worker", "model_id": "provider/model", **injection})
    assert response.status_code == 422
    assert not native.calls


def test_create_retry_and_fingerprint_conflict_never_duplicate(harness):
    _, _, native, _, bind, _, invoke = harness
    grant = bind().json()
    first = invoke(grant)
    assert first.status_code == 200 and first.json()["status"] == "completed"
    assert invoke(grant).json()["reused"] is True
    assert native.calls == ["create"]
    assert invoke(grant, parameters={"display_name": "Changed", "model_id": "provider/model"}).status_code == 409
    assert grant["subject_capability"] not in first.text
    assert "externalManagement" not in first.text


def test_lost_create_ack_recovers_only_exact_complete_native_match(harness):
    _, _, native, _, bind, _, invoke = harness
    grant = bind().json()
    native.lost_ack = True
    assert invoke(grant).json()["status"] == "unknown"
    assert invoke(grant).json()["status"] == "completed"
    assert native.calls == ["create"]
    assert native.agents["agent-1"]["metadata"]["externalManagementCreation"]["subjectId"] == grant["subject_id"]


def test_native_api_delegation_in_metadata_can_be_verified(harness, monkeypatch):
    _, _, native, _, bind, _, invoke = harness
    original = native.find_created

    def projection(key):
        rows = original(key)
        for row in rows:
            row.pop("delegationPolicy", None)
        return rows

    monkeypatch.setattr(native, "find_created", projection)
    assert invoke(bind().json()).json()["status"] == "completed"


def test_registry_low_policy_cannot_hide_a_stale_wide_compiled_snapshot(harness):
    _, _, native, _, bind, _, invoke = harness
    native.compiled_wide = True
    grant = bind().json()
    assert invoke(grant).json()["status"] == "unknown"
    assert invoke(grant).json()["status"] == "unknown"
    assert native.calls == ["create"]


@pytest.mark.parametrize("kind", ["missing", "incomplete", "ambiguous"])
def test_unknown_create_never_rebuilds_on_zero_multiple_or_partial_matches(harness, kind):
    _, _, native, _, bind, _, invoke = harness
    grant = bind().json()
    native.lost_ack = True
    native.incomplete = kind == "incomplete"
    assert invoke(grant).json()["status"] == "unknown"
    if kind == "missing":
        native.agents.clear()
    elif kind == "ambiguous":
        native.agents["agent-2"] = {**deepcopy(native.agents["agent-1"]), "agentId": "agent-2"}
    for _ in range(2):
        assert invoke(grant).json()["status"] == "unknown"
    assert native.calls == ["create"]


def test_restart_reuses_subject_credential_and_original_pending_receipt(harness):
    client, service, native, _, bind, headers, invoke = harness
    grant = bind().json()
    native.lost_ack = True
    assert invoke(grant).json()["status"] == "unknown"
    route._SERVICE = ManagementService(service.root, identity=service.identity, native=native)
    assert bind().json() == grant
    response = client.get(PREFIX + "/actions/agent_create/requests/stable-create", headers=headers(grant))
    assert response.json()["status"] == "completed"
    assert native.calls == ["create"]


def test_update_uses_cas_and_rejects_permission_role_lifecycle(harness):
    _, _, native, _, bind, _, invoke = harness
    grant = bind().json()
    invoke(grant)
    parameters = {"agent_id": "agent-1", "expected_config_revision": 1, "updates": {"displayName": "Edited"}}
    assert invoke(grant, "agent_update", "update-one", parameters).json()["status"] == "completed"
    assert invoke(grant, "agent_update", "update-one", parameters).json()["reused"] is True
    assert invoke(grant, "agent_update", "stale-update", parameters).status_code == 409
    for field in ("permissionPreset", "roleKey", "status", "metadata", "toolPolicy", "delegationPolicy"):
        injected = {**parameters, "updates": {field: "forbidden"}}
        assert invoke(grant, "agent_update", "inject-" + field, injected).status_code == 422
    assert native.calls.count("update") == 2  # One native CAS rejection, never a duplicate successful write.


def test_update_cannot_confirm_only_registry_when_current_compiled_is_stale(harness, monkeypatch):
    _, _, native, _, bind, _, invoke = harness
    grant = bind().json()
    assert invoke(grant).json()["status"] == "completed"
    monkeypatch.setattr(native, "current_compiled", lambda _agent_id: {"displayName": "Old compiled name"})
    parameters = {"agent_id": "agent-1", "expected_config_revision": 1, "updates": {"displayName": "Edited"}}
    assert invoke(grant, "agent_update", "compiled-stale", parameters).json()["status"] == "unknown"
    assert invoke(grant, "agent_update", "compiled-stale", parameters).json()["status"] == "unknown"
    assert native.calls == ["create", "update"]


def test_avatar_requires_native_cas_and_closed_library_target(harness):
    _, _, _, _, bind, _, invoke = harness
    grant = bind().json()
    invoke(grant)
    parameters = {"agent_id": "agent-1", "expected_updated_at": "v1", "avatar_image_path": "workspace/avatars/preset.png"}
    assert invoke(grant, "agent_avatar", "avatar-one", parameters).json()["status"] == "completed"
    bad = {**parameters, "avatar_image_path": "http://outside/avatar.png"}
    assert invoke(grant, "agent_avatar", "avatar-bad", bad).status_code == 422
    assert invoke(grant, "agent_avatar", "avatar-stale", {**parameters, "expected_updated_at": "stale"}).status_code == 409


def test_native_gateway_has_no_project_pa_or_runtime_impersonation():
    from pathlib import Path

    from core.web.services.external_management import native
    source = Path(native.__file__).read_text(encoding="utf-8")
    for forbidden in ("current_agent_runtime", "set_current_agent", "personalAssistantCreatedBy", "create_personal_assistant", "active_agent_runtime"):
        assert forbidden not in source
    assert "create_configured_agent_with_session" in source
    assert "update_agent_from_catalog_request" in source
    assert "_STATE_LOCK" in source


def test_contracts_are_closed_and_do_not_add_daily_action_approval():
    from core.web.services.external_management.contracts import ACTION_MODELS, contracts
    for name, contract in contracts().items():
        assert contract["governed"] is (name in {"team_run", "session_pin", "agent_archive", "authorization_upgrade"})
        assert contract["parameters"]["additionalProperties"] is False
        assert not {"subject", "owner", "runtime", "governed", "nativeApproval", "expected_binding"} & set(ACTION_MODELS[name].model_fields)


def _grant_file_preset_scope(invoke, grant):
    upgraded = invoke(grant, action="authorization_upgrade", request_id="files-upgrade",
                      parameters={"expected_scopes": grant["scopes"], "add_scopes": ["agents:create:files"]})
    assert upgraded.json()["status"] == "completed"


def test_preset_requires_explicit_target_scope(harness):
    client, service, native, _, bind, headers, invoke = harness
    grant = bind().json()
    assert "agents:create:files" not in service.binding()["scopes"]
    assert bind(client_id="new-client", scopes=["agents:create", "agents:create:files"]).status_code == 403
    parameters = {"display_name": "Worker", "model_id": "provider/model", "capability_preset": "project_files_v1"}
    rejected = invoke(grant, parameters=parameters)
    assert rejected.status_code == 403 and rejected.json()["detail"]["code"] == "SCOPE_DENIED"
    assert not native.calls
    _grant_file_preset_scope(invoke, grant)
    rebound = bind(scopes=sorted(grant["scopes"] + ["agents:create:files"]))
    assert rebound.status_code == 200 and rebound.json()["subject_id"] == grant["subject_id"]
    created = invoke(grant, parameters=parameters)
    assert created.json()["status"] == "completed"
    assert native.calls == ["create"]
    path = service.store.path("subjects", grant["subject_id"])
    current = service.store.read(path)
    current["scopes"].remove("agents:create:files")
    service.store.write(path, current)
    assert invoke(grant, parameters=parameters).status_code == 403
    assert client.get(PREFIX + "/actions/agent_create/requests/stable-create", headers=headers(grant)).status_code == 403
    assert native.calls == ["create"]


def test_file_scope_alone_cannot_create_an_agent(harness):
    _, _, native, _, bind, _, invoke = harness
    grant = bind(scopes=["agents:read"]).json()
    _grant_file_preset_scope(invoke, grant)
    parameters = {"display_name": "Worker", "model_id": "provider/model", "capability_preset": "project_files_v1"}
    assert invoke(grant, parameters=parameters).status_code == 403
    assert native.calls == []


def test_fixed_file_preset_receipt_recovery_and_conflict(harness):
    _client, _service, native, _control, bind, _headers, invoke = harness
    grant = bind().json()
    _grant_file_preset_scope(invoke, grant)
    parameters = {"display_name": "Worker", "model_id": "provider/model", "mission": "Report evidence.",
                  "capability_preset": "project_files_v1"}
    native.lost_ack = True
    first = invoke(grant, parameters=parameters)
    assert first.json()["status"] == "unknown"
    native.lost_ack = False
    second = invoke(grant, parameters=parameters)
    assert second.json()["status"] == "completed" and second.json()["reused"] is True
    assert native.calls == ["create"]
    assert invoke(grant, parameters={**parameters, "capability_preset": None}).status_code == 409
    for invalid in ("full_access", "workspace_write", "unknown"):
        assert invoke(grant, request_id="invalid-" + invalid, parameters={**parameters, "capability_preset": invalid}).status_code == 422


def test_preset_receipt_waits_for_matching_compiled_config(harness):
    _, _, native, _, bind, _, invoke = harness
    grant = bind().json()
    _grant_file_preset_scope(invoke, grant)
    parameters = {"display_name": "Worker", "model_id": "provider/model", "capability_preset": "project_files_v1"}
    native.compiled_wide = True
    assert invoke(grant, parameters=parameters).json()["status"] == "unknown"
    native.compiled_wide = False
    recovered = invoke(grant, parameters=parameters).json()
    assert recovered["status"] == "completed" and recovered["reused"] is True
    assert native.calls == ["create"]


def test_fixed_preset_is_intersected_with_external_task_ceiling():
    from core.authorization import TurnToolGrant, evaluate_tool_policy, normalize_legacy_tool_policy
    from core.web.services.agent_directory_service import _with_runtime_tool_grants
    from core.web.services.external_agent.policy import external_runtime_tool_grants
    from core.web.services.external_management.contracts import agent_create_tool_policy
    from core.web.services.tool_catalog import build_tool_descriptor
    from core.authorization.collaboration_mode import with_collaboration_controls
    from tools.Key_Tools import create_key_tools
    policy = agent_create_tool_policy("project_files_v1")
    names = {tool.name for tool in create_key_tools()}
    assert set(policy["allowedTools"]) <= names
    assert with_collaboration_controls(policy)["allowedTools"] == policy["allowedTools"]
    for profile in ("read_only", "workspace_write"):
        effective = _with_runtime_tool_grants(policy, grants=external_runtime_tool_grants(profile),
                                             source="external_agent_task:" + profile)
        assert effective["allowedTools"] == (policy["allowedTools"][:3] if profile == "read_only" else policy["allowedTools"])
        assert effective["mutationAccess"] == ("none" if profile == "read_only" else "restricted")
        assert effective["approvalOverrides"] == {"apply_diff_edit_tool": "always", "write_file_tool": "always"}
    descriptors = tuple(build_tool_descriptor(name, args_schema={}) for name in policy["allowedTools"])
    normalized = normalize_legacy_tool_policy(policy, policy_id="bounded", registered_tool_names=policy["allowedTools"])
    grant = TurnToolGrant(turn_id="test", source="session", denied_tools=(), approval_mode="on_request",
                          allowed_capabilities=tuple(sorted({tag for item in descriptors for tag in item.capabilities})))
    decision = evaluate_tool_policy(agent_id="worker", policy=normalized, grant=grant, descriptors=descriptors,
                                    registry_version=1, registry_fingerprint="test")
    assert set(decision.executable_tools) == set(policy["allowedTools"])
    assert {name: approval for name, approval, _risk in decision.approval_requirements}["write_file_tool"] == "always"
    assert {name: approval for name, approval, _risk in decision.approval_requirements}["apply_diff_edit_tool"] == "always"


@pytest.mark.parametrize("mode,expected_approvals", [("build", 2), ("edit", 0), ("yolo", 0)])
def test_preset_real_execution_gate_respects_collaboration_mode(monkeypatch, mode, expected_approvals):
    from types import SimpleNamespace
    from core.authorization import TurnToolGrant, evaluate_tool_policy, normalize_legacy_tool_policy, tool_authorization_service as authorization
    from core.web.services import agent_directory_service
    from core.web.services.external_management.contracts import agent_create_tool_policy
    from core.web.services.tool_catalog import build_tool_descriptor
    policy = agent_create_tool_policy("project_files_v1")
    descriptors = tuple(build_tool_descriptor(name, args_schema={}) for name in policy["allowedTools"])
    normalized = normalize_legacy_tool_policy(policy, policy_id="bounded", registered_tool_names=policy["allowedTools"])
    grant = TurnToolGrant(turn_id="turn-a", source="session", denied_tools=(), approval_mode="on_request",
                          allowed_capabilities=tuple(sorted({tag for item in descriptors for tag in item.capabilities})))
    decision = evaluate_tool_policy(agent_id="agent-a", policy=normalized, grant=grant, descriptors=descriptors,
                                    registry_version=1, registry_fingerprint="test")
    runtime = {"agentId": "agent-a", "turnId": "turn-a", "sessionId": "session-a", "toolPolicy": policy,
               "agentConfigSnapshot": {"configRevision": 1, "configHash": "hash"}, "permissionPreset": "request_approval",
               "collaborationMode": {"mode": mode, "planEnabled": False, "prePlanMode": "build"}}
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: runtime)
    asked = []
    monkeypatch.setattr("core.web.services.session.tool_approvals.authorize_or_wait",
                        lambda **kwargs: asked.append(kwargs) or SimpleNamespace(allowed=True, code="approved", message=""))
    authorization.install_execution_authorization(SimpleNamespace(decision=decision), runtime=runtime)
    try:
        for index, name in enumerate(("write_file_tool", "apply_diff_edit_tool")):
            result = authorization.authorize_tool_execution(tool_name=name, tool_call_id=f"call-{index}", tool_args={"file_path": "fixture.txt"})
            assert result.allowed
        assert len(asked) == expected_approvals
        assert all(row["approval"] == "always" for row in asked)
    finally:
        authorization.clear_execution_authorization()


def test_ledger_ack_loss_after_native_creation_recovers_without_recreating(harness, monkeypatch):
    client, service, native, _, bind, headers, invoke = harness
    grant = bind().json()
    write = service.store.write
    failed = False

    def lost_ack(path, value):
        nonlocal failed
        if value.get("agentId") and not failed:
            failed = True
            raise OSError("private ledger path")
        write(path, value)

    monkeypatch.setattr(service.store, "write", lost_ack)
    first = invoke(grant)
    assert first.status_code == 503 and "private ledger path" not in first.text
    recovered = client.get(PREFIX + "/actions/agent_create/requests/stable-create", headers=headers(grant))
    assert recovered.json()["status"] == "completed"
    assert native.calls == ["create"]


def test_changed_canonical_storage_invalidates_existing_subject(harness):
    _, service, native, _, bind, _, invoke = harness
    grant = bind().json()
    service.identity = lambda: TargetIdentity(BINDING, "different-canonical-storage")
    assert invoke(grant).status_code == 409
    assert bind().status_code == 409
    assert not native.calls


@pytest.mark.parametrize("preset", [None, "project_files_v1"])
def test_concurrent_same_request_has_one_native_creation(harness, monkeypatch, preset):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    _, service, native, _, bind, _, _ = harness
    grant = bind().json()
    if preset:
        _grant_file_preset_scope(harness[-1], grant)
    entered, release = Event(), Event()
    original = native.create

    def blocked_create(*args):
        entered.set()
        assert release.wait(2)
        return original(*args)

    monkeypatch.setattr(native, "create", blocked_create)
    body = {"request_id": "concurrent-create", "expected_binding": BINDING,
            "parameters": {"display_name": "Worker", "model_id": "provider/model"}}
    if preset is not None:
        body["parameters"]["capability_preset"] = preset
    args = (grant["subject_id"], grant["subject_capability"], "agent_create", body)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.invoke, *args)
        assert entered.wait(2)
        second = pool.submit(service.invoke, *args)
        release.set()
        results = [first.result(timeout=3), second.result(timeout=3)]
    assert all(result["status"] == "completed" for result in results)
    assert sorted(result["reused"] for result in results) == [False, True]
    assert native.calls == ["create"]


def test_native_avatar_cas_is_inside_the_same_directory_lock(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from core.web.services.external_management.native import NativeAgentGateway
    lock = RLock()
    events = []
    agent = {"agentId": "a", "status": "active", "roleKey": "worker", "updatedAt": "v1", "metadata": {}}

    def read(*args, **kwargs):
        assert lock._is_owned()
        return deepcopy(agent)

    def avatar(*args, **kwargs):
        assert lock._is_owned()
        events.append("native-avatar")
        agent.update(avatarImagePath=kwargs["avatar_image_path"], updatedAt="v2")
        return deepcopy(agent)

    def update(*args, **kwargs):
        assert lock._is_owned()
        assert kwargs["expected_updated_at"] == "v2"
        events.append("native-audit-metadata")
        agent["metadata"] = kwargs["metadata"]
        return deepcopy(agent)

    directory = SimpleNamespace(_STATE_LOCK=lock, agent_session_lifecycle_transaction=lambda: lock,
                                get_agent=read, update_agent_avatar=avatar, update_agent_instance=update)
    gateway = NativeAgentGateway(tmp_path)
    monkeypatch.setattr(gateway, "_owners", lambda: directory)
    parameters = {"agent_id": "a", "expected_updated_at": "stale", "avatar_image_path": "workspace/avatars/a.png", "reset_to_default": False}
    with pytest.raises(ManagementError, match="STATE_CONFLICT"):
        gateway.avatar(parameters, {"subjectId": "operator"})
    assert not events
    result = gateway.avatar({**parameters, "expected_updated_at": "v1"}, {"subjectId": "operator"})
    assert events == ["native-avatar", "native-audit-metadata"]
    assert result["metadata"]["externalManagementMutation"] == {"subjectId": "operator"}
    assert not lock._is_owned()


@pytest.mark.parametrize("preset", [None, "project_files_v1"])
def test_native_creation_is_restricted_from_first_registry_write_and_first_sqlite_snapshot(tmp_path, monkeypatch, preset):
    from core.chat.conversation_store import ConversationStore
    from core.web.services import agent_directory_service as directory
    from core.web.services import session_service as sessions
    from core.web.services.agent_config_authority import canonical_agent_config_payload
    from core.web.services.external_management.native import NativeAgentGateway
    from core.web.services.external_management.contracts import agent_create_tool_policy
    from core.web.services.session import directory_runtime
    from tests.test_agent_config_workspace_service import _use_tmp_project_root

    _use_tmp_project_root(tmp_path, monkeypatch)
    store = ConversationStore(tmp_path / "isolated-control.sqlite3")
    store.open()
    monkeypatch.setattr(directory_runtime, "get_open_directory_store", lambda: store)
    monkeypatch.setattr(directory_runtime, "directory_store_project_root", lambda: tmp_path)
    gateway = NativeAgentGateway(tmp_path)
    monkeypatch.setattr(gateway, "_model", lambda _model: None)
    marker = {"subjectType": "operator", "subjectId": "neutral-operator", "requestKey": "opaque", "requestFingerprint": "frozen"}
    observations = []
    expected_policy = agent_create_tool_policy(preset)
    save = directory.save_state

    def observe(state):
        result = save(state)
        for row in state.get("agents", []):
            if (row.get("metadata") or {}).get("externalManagementCreation") != marker:
                continue
            policy = row["toolPolicy"]
            for key, value in expected_policy.items():
                assert policy[key] == value
            assert row["permissionPreset"] == "request_approval"
            assert row["metadata"]["delegationPolicy"]["allowWakeMessages"] is False
            observations.append(bool(row.get("directSessionId")))
        return result

    monkeypatch.setattr(directory, "save_state", observe)

    def create_session(**kwargs):
        assert kwargs["activate"] is False and kwargs["lightweight"] is True
        external = kwargs.get("created_by") == "external_agent_task"
        if external:
            assert kwargs["conversation_index_kind"] == "hidden"
            assert kwargs["session_metadata"]["effectivePermissionProfile"] == "workspace_write"
        else:
            assert kwargs["idempotency_key"] == marker["requestKey"]
        agent_id = kwargs["agent_id"]
        raw = next(row for row in directory.load_state()["agents"] if row["agentId"] == agent_id)
        config = canonical_agent_config_payload(raw)
        assert config["taskProfile"]["mission"] == "Report evidence."
        for key, value in expected_policy.items():
            assert config["toolPolicy"][key] == value
        assert config["delegationPolicy"]["allowSubagents"] is False
        assert config["delegationPolicy"]["allowWakeMessages"] is False
        revision = store.repository.import_agent_config_snapshots([{
            "agent_id": agent_id, "display_name": raw["displayName"], "kind": raw["kind"],
            "status": raw["status"], "config": config, "source": "isolated_native_session_binding",
        }]).result(timeout=3)[0]
        return store.repository.create_session(session_id="external-created-session" if external else "native-created-session", agent_id=agent_id,
            agent_config_revision_id=revision["configRevisionId"], title="New session").result(timeout=3)

    monkeypatch.setattr(sessions, "create_chat_session", create_session)
    try:
        parameters = {"display_name": "Worker", "model_id": "model-primary", "mission": "Report evidence."}
        if preset is not None:
            parameters["capability_preset"] = preset
        agent = gateway.create(parameters, marker)
        assert observations and observations[0] is False and observations[-1] is True
        assert agent["directSessionId"] == "native-created-session"
        assert "delegationPolicy" not in agent  # This is the real native API shape.
        compiled = gateway.compiled(agent["agentId"], agent["directSessionId"])
        for key, value in expected_policy.items():
            assert compiled["toolPolicy"][key] == value
        assert compiled["toolPolicy"]["networkAccess"] == "none"
        assert compiled["taskProfile"]["mission"] == "Report evidence."
        assert compiled["delegationPolicy"]["allowWakeMessages"] is False
        assert gateway.compiled(agent["agentId"], "foreign-session") is None
        service = ManagementService(tmp_path / "receipts", identity=lambda: TargetIdentity(BINDING, "test"), native=gateway)
        record = {"action": "agent_create", "parameters": parameters, "marker": marker}
        assert service._verify(record, agent)
        pinned = store.repository.get_session(agent["directSessionId"])["agentConfigRevisionId"]
        if preset:
            from tests.test_external_agent_task_service import FakeRuntime, _service
            # The isolated create_session stub does not perform the ordinary
            # directory visibility update made by the real session owner.
            runtime = FakeRuntime(agents=[{**agent, "conversationIndexKind": "personal_agent"}])
            runtime.create_session = create_session
            external = _service(tmp_path / "external-tasks", runtime)
            started = external.start_task(owner_id="launcher", adapter_connection_id="connection", capabilities=set(),
                agent_id=agent["agentId"], task="Edit the project", permission_profile="workspace_write",
                client_request_id="external-preset", title="", runtime_revision="rev")
            assert started["status"] == "running"
            hidden = store.repository.get_session("external-created-session")
            assert hidden["agentConfigRevisionId"] == pinned
            assert runtime.submit_calls[0]["sessionId"] == "external-created-session"
            assert runtime.submit_calls[0]["message_metadata"]["effectivePermissionProfile"] == "workspace_write"
        update_marker = {"subjectType": "operator", "subjectId": "neutral-operator", "requestKey": "update", "requestFingerprint": "update-frozen"}
        parameters = {"agent_id": agent["agentId"], "expected_config_revision": agent["configRevision"],
                      "updates": {"displayName": "Edited Worker", "taskProfile": {"mission": "Updated mission."}}}
        updated = gateway.update(parameters, update_marker)
        assert gateway.current_compiled(agent["agentId"])["displayName"] == "Edited Worker"
        assert gateway.current_compiled(agent["agentId"])["taskProfile"]["mission"] == "Updated mission."
        assert store.repository.get_session(agent["directSessionId"])["agentConfigRevisionId"] == pinned
        assert service._verify({"action": "agent_update", "parameters": parameters, "marker": update_marker}, updated)

        from core.chat.conversation_store.repository import (
            AgentConfigRevisionConflictError,
        )
        native_cas = store.repository.compare_and_swap_agent_config

        def competing_snapshot(**kwargs):
            concurrent = {**gateway.current_compiled(agent["agentId"]), "displayName": "Concurrent snapshot"}
            store.repository.import_agent_config_snapshots([{
                "agent_id": agent["agentId"], "display_name": "Concurrent snapshot", "kind": "persistent",
                "status": "active", "config": concurrent, "source": "isolated_competing_publisher",
            }]).result(timeout=3)
            return native_cas(**kwargs)

        monkeypatch.setattr(store.repository, "compare_and_swap_agent_config", competing_snapshot)
        with pytest.raises(AgentConfigRevisionConflictError):
            gateway.update({**parameters, "expected_config_revision": updated["configRevision"],
                            "updates": {"displayName": "Unconfirmed update"}}, {**update_marker, "requestKey": "conflicting"})
        assert gateway.current_compiled(agent["agentId"])["displayName"] == "Concurrent snapshot"
        assert store.repository.get_session(agent["directSessionId"])["agentConfigRevisionId"] == pinned
    finally:
        store.close()
