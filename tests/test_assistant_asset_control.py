"""Operator asset changes reuse native owners and reject stale authority."""
from concurrent.futures import Future
from copy import deepcopy
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from core.web.services import agent_directory_service as directory, team_knowledge_service as knowledge
from core.web.services.agent_config_authority import canonical_agent_config_payload
from core.web.services.external_management import asset_contracts as contracts
from core.web.services.external_management.native import NativeAgentGateway
from core.web.services.external_management.service import ManagementError
from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
from tests.test_agent_tool_policy_configuration import configured_agent as native_policy_agent, _registry_payload
from tests.test_team_knowledge_service import isolate_developer_sandbox_config, knowledge_env


def test_workspace_scope_contract_matches_native_policy():
    from typing import get_args
    assert get_args(contracts.Scope) == directory.TOOL_POLICY_WORKSPACE_SCOPES


@pytest.fixture
def configured_agent(native_policy_agent, monkeypatch):
    # Mutation tests supply an explicit native registry fixture. Real authority
    # routing and cold-read purity are exercised separately below.
    from core.web.services import tool_registry_service as registry
    from core.infrastructure import developer_sandbox
    directory.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    directory.CONFIG_PATH.write_text("[launcher.developer_mode]\nenabled = false\n", encoding="utf-8")
    monkeypatch.setattr(developer_sandbox, "CONFIG_PATH", directory.CONFIG_PATH)
    monkeypatch.setattr(registry, "get_existing_tool_registry", lambda snapshot: registry.get_tool_registry())
    return native_policy_agent


class Native:
    _editable = NativeAgentGateway._editable

    def __init__(self, agent_id=None):
        self.project_root = directory.PROJECT_ROOT
        self.publications = []
        self.session_pins = {"existing-session": "old-revision"}
        raw = directory._find_agent(directory.load_state(), agent_id) if agent_id else None
        self.compiled = {"configRevisionId": "old-revision", "config": canonical_agent_config_payload(raw)}
        repository = SimpleNamespace(get_current_agent_config=lambda _id: deepcopy(self.compiled),
                                     compare_and_swap_agent_config=self.publish)
        self.store = SimpleNamespace(repository=repository)

    def _owners(self):
        return directory

    def _control_store(self):
        return self.store

    def publish(self, **values):
        assert values["expected_config_revision_id"] == self.compiled["configRevisionId"]
        self.publications.append(values)
        self.compiled = {"configRevisionId": "new-revision", "config": deepcopy(values["config"])}
        result = Future()
        result.set_result({"configRevisionId": "new-revision"})
        return result


def _control(native):
    from core.web.services.external_management.asset_control import AssetControl
    return AssetControl(native)


def test_policy_inspect_uses_native_validation_and_never_writes(configured_agent, monkeypatch):
    from core.web.services.external_management.configuration_discovery import ConfigurationDiscovery
    native = Native(configured_agent["agentId"])
    control = ConfigurationDiscovery(native)
    monkeypatch.setattr(control, "_agent", lambda agent_id: {"agentId": agent_id, "compiledMatches": True})
    # The existing fixture supplies the canonical Agent/registry authority.
    from core.web.services.external_management.agent_configuration import AgentConfigurationControl
    from contextlib import contextmanager
    @contextmanager
    def locked(_self):
        with directory._STATE_LOCK:
            yield directory
    monkeypatch.setattr(AgentConfigurationControl, "_locked", locked)
    def forbidden(*_args, **_kwargs):
        pytest.fail("Policy inspection invoked a writer")
    from core.web.services import tool_policy_configuration_service as policies
    monkeypatch.setattr(policies, "update_tool_policy_configuration", forbidden)
    monkeypatch.setattr(native, "publish", forbidden)
    result = control.inspect_policy(configured_agent["agentId"], '{"allowedTools":["missing_tool"]}')
    assert result["validation"]["valid"] is False
    assert result["preview"]["unknownTools"] == ["missing_tool"]
    assert result["candidates"] and result["current"]["compiledMatches"]
    assert "approvalGrants" not in str(result)


def _policy_parameters(snapshot, **updates):
    return {"agent_id": snapshot["agentId"], "expected_config_revision": snapshot["configRevision"],
            "expected_agent_updated_at": snapshot["agentUpdatedAt"],
            "expected_policy_fingerprint": snapshot["policyFingerprint"],
            "expected_registry_version": snapshot["registryVersion"],
            "expected_registry_fingerprint": snapshot["registryFingerprint"], "updates": updates}


def test_asset_models_reject_authority_and_policy_identity_injection():
    valid = {"agent_id": "agent-a", "expected_config_revision": 1, "expected_agent_updated_at": "now",
             "expected_policy_fingerprint": "a" * 64, "expected_registry_version": "1",
             "expected_registry_fingerprint": "a" * 64,
             "updates": {"allowedTools": ["cli_tool"]}}
    for extra in ({"confirmed": True}, {"governed": True}, {"actor_agent_id": "owner"}):
        with pytest.raises(ValidationError):
            contracts.ToolPolicyUpdate.model_validate({**valid, **extra})
    for update in ({"allowAllTools": True}, {"policyId": "shared"}, {"roleToolProfileId": "role"},
                   {"maxCallsPerTurn": True}, {"perToolRules": {"cli_tool": {"approvalGrants": []}}}):
        with pytest.raises(ValidationError):
            contracts.ToolPolicyUpdate.model_validate({**valid, "updates": update})
    with pytest.raises(ValidationError):
        contracts.KnowledgeACLMutation.model_validate({"knowledge_base_id": "kb-a", "target_agent_id": "agent-a",
            "permissions": ["*"], "expected_acl_fingerprint": "a" * 64})
    with pytest.raises(ValidationError):
        contracts.KnowledgeACLQuery.model_validate({"knowledge_base_id": "kb/other"})


def test_tool_policy_requires_real_privileged_operator(configured_agent):
    control = _control(Native(configured_agent["agentId"]))
    with pytest.raises(ManagementError) as denied:
        control.read_tool_policy(configured_agent["agentId"])
    assert denied.value.code == "OPERATOR_CONTROL_REQUIRED"
    with server_operator_scope("reader", roles=("reader",)):
        with pytest.raises(ManagementError):
            control.read_tool_policy(configured_agent["agentId"])


def test_tool_policy_change_compiles_explicit_native_policy_without_repinning_sessions(configured_agent):
    native = Native(configured_agent["agentId"])
    control = _control(native)
    with server_operator_scope("operator-test", roles=("operator",)):
        before = control.read_tool_policy(configured_agent["agentId"])
        assert before["compiledMatches"] is True
        parameters = _policy_parameters(before, allowedTools=["exec_command"], preferredTools=[],
            readScopes=["private"], writeScopes=["private"], networkAccess="none",
            mutationAccess="workspace", delegationAccess="none", maxCallsPerTurn=7)
        result = control.update_tool_policy(parameters)
        after = control.read_tool_policy(configured_agent["agentId"])
    assert result["verified"] is True and result["action"] == "agent_tool_policy_update"
    assert result["revision"] == after["configRevision"] > before["configRevision"]
    assert result["fingerprint"] == after["policyFingerprint"]
    assert "policy" not in result and "updates" not in result
    assert after["policy"]["allowedTools"] == ["exec_command"]
    assert after["policy"]["writeScopes"] == ["private"]
    assert after["compiledMatches"] is True and len(native.publications) == 1
    assert native.session_pins == {"existing-session": "old-revision"}


@pytest.mark.parametrize("field,value", [("expected_config_revision", 999), ("expected_agent_updated_at", "old"),
    ("expected_policy_fingerprint", "0" * 64), ("expected_registry_version", "old")])
def test_tool_policy_four_cas_checks_precede_native_write(configured_agent, field, value):
    native = Native(configured_agent["agentId"])
    control = _control(native)
    with server_operator_scope("operator-test", roles=("operator",)):
        snapshot = control.read_tool_policy(configured_agent["agentId"])
        parameters = {**_policy_parameters(snapshot, allowedTools=[]), field: value}
        with pytest.raises(ManagementError) as stale:
            control.update_tool_policy(parameters)
        assert stale.value.code == "STATE_CONFLICT"
        assert control.read_tool_policy(configured_agent["agentId"])["policyFingerprint"] == snapshot["policyFingerprint"]
    assert native.publications == []


def test_tool_policy_unknown_tools_and_missing_compiled_snapshot_never_write(configured_agent):
    native = Native(configured_agent["agentId"])
    control = _control(native)
    with server_operator_scope("operator-test", roles=("operator",)):
        snapshot = control.read_tool_policy(configured_agent["agentId"])
        with pytest.raises(ManagementError) as invalid:
            control.update_tool_policy(_policy_parameters(snapshot, allowedTools=["missing_tool"], preferredTools=[]))
        assert invalid.value.code == "INVALID_INPUT"
        native.store = None
        with pytest.raises(ManagementError) as unavailable:
            control.update_tool_policy(_policy_parameters(snapshot, allowedTools=[], preferredTools=[]))
        assert unavailable.value.code == "CONFIG_SNAPSHOT_UNAVAILABLE"
    assert native.publications == []


@pytest.mark.parametrize("updates", [{"perToolRules": {"missing_tool": {"approval": "always"}}},
    {"approvalOverrides": {"missing_tool": "always"}}])
def test_every_tool_policy_reference_uses_native_registry(configured_agent, updates):
    native = Native(configured_agent["agentId"])
    control = _control(native)
    with server_operator_scope("operator-test", roles=("operator",)):
        before = control.read_tool_policy(configured_agent["agentId"])
        with pytest.raises(ManagementError) as invalid:
            control.update_tool_policy(_policy_parameters(before, **updates))
        assert invalid.value.code == "INVALID_INPUT"
        assert control.read_tool_policy(configured_agent["agentId"])["policyFingerprint"] == before["policyFingerprint"]
    assert native.publications == []


def test_registry_change_during_validation_is_rejected_before_write(configured_agent, monkeypatch):
    from core.web.services import tool_policy_configuration_service as policies
    native = Native(configured_agent["agentId"])
    control = _control(native)
    registry = policies.tool_registry_service.get_tool_registry
    calls = []
    with server_operator_scope("operator-test", roles=("operator",)):
        before = control.read_tool_policy(configured_agent["agentId"])
        def changing_registry():
            calls.append(1)
            return {**registry(), "registryVersion": 1 if len(calls) == 1 else 2}
        monkeypatch.setattr(policies.tool_registry_service, "get_tool_registry", changing_registry)
        with pytest.raises(ManagementError) as stale:
            control.update_tool_policy(_policy_parameters(before, maxCallsPerTurn=9))
        assert stale.value.code == "STATE_CONFLICT"
    assert native.publications == []


@pytest.mark.parametrize("gated_tool", ["cli_agent_run_tool", "create_child_session_tool"])
@pytest.mark.parametrize("already_declared", [True, False])
def test_declared_policy_and_compiled_config_keep_gated_tools_without_delegation(
        configured_agent, monkeypatch, gated_tool, already_declared):
    from core.web.services import tool_policy_configuration_service as policies
    monkeypatch.setattr(policies.tool_registry_service, "get_tool_registry",
        lambda: _registry_payload(["cli_tool", gated_tool]))
    agent_id = configured_agent["agentId"]
    directory.update_agent_instance(agent_id, delegation_policy={"allowSubagents": False},
        tool_policy={"allowedTools": ["cli_tool", *([gated_tool] if already_declared else [])],
                     "preferredTools": ["cli_tool"], "blockedTools": []})
    native = Native(agent_id)
    control = _control(native)
    raw_before = deepcopy(directory._find_agent(directory.load_state(), agent_id))
    assert gated_tool not in directory.get_agent(agent_id)["toolPolicy"]["allowedTools"]
    with server_operator_scope("operator-test", roles=("operator",)):
        before = control.read_tool_policy(agent_id)
        assert before["compiledMatches"] is True
        assert (gated_tool in before["policy"]["allowedTools"]) is already_declared
        assert gated_tool not in before["executableTools"]
        updates = {"maxCallsPerTurn": 13} if already_declared else {"allowedTools": ["cli_tool", gated_tool]}
        result = control.update_tool_policy(_policy_parameters(before, **updates))
        after = control.read_tool_policy(agent_id)
    assert result["verified"] is True and after["compiledMatches"] is True
    raw_after = directory._find_agent(directory.load_state(), agent_id)
    assert gated_tool in raw_after["toolPolicy"]["allowedTools"]
    assert raw_after["metadata"]["delegationPolicy"] == raw_before["metadata"]["delegationPolicy"]
    assert gated_tool not in directory.get_agent(agent_id)["toolPolicy"]["allowedTools"]
    assert gated_tool not in after["executableTools"]
    assert native.compiled["config"] == canonical_agent_config_payload(raw_after)
    assert native.session_pins == {"existing-session": "old-revision"}
    if already_declared:
        expected_policy = {**raw_before["toolPolicy"], "maxCallsPerTurn": 13,
                           "policyVersion": raw_before["toolPolicy"]["policyVersion"] + 1}
        assert raw_after["toolPolicy"] == expected_policy


@pytest.mark.parametrize("change_during_native_write", [False, True])
def test_same_registry_schema_with_changed_content_fingerprint_never_writes(
        configured_agent, monkeypatch, change_during_native_write):
    from core.web.services import tool_policy_configuration_service as policies
    registry = policies.tool_registry_service.get_tool_registry
    monkeypatch.setattr(policies.tool_registry_service, "get_tool_registry",
        lambda: {**registry(), "registryFingerprint": "a" * 64})
    native = Native(configured_agent["agentId"])
    control = _control(native)
    with server_operator_scope("operator-test", roles=("operator",)):
        before = control.read_tool_policy(configured_agent["agentId"])
        raw_before = deepcopy(directory._find_agent(directory.load_state(), configured_agent["agentId"]))
        compiled_before = deepcopy(native.compiled)
        calls = []
        def changed_registry():
            calls.append(1)
            fingerprint = "a" * 64 if change_during_native_write and len(calls) < 3 else "b" * 64
            return {**registry(), "registryFingerprint": fingerprint}
        monkeypatch.setattr(policies.tool_registry_service, "get_tool_registry", changed_registry)
        parameters = {**_policy_parameters(before, maxCallsPerTurn=23), "expected_registry_fingerprint": "a" * 64}
        with pytest.raises(ManagementError) as stale:
            control.update_tool_policy(parameters)
        assert stale.value.code == "STATE_CONFLICT"
    assert native.publications == [] and native.compiled == compiled_before
    assert directory._find_agent(directory.load_state(), configured_agent["agentId"]) == raw_before


@pytest.mark.parametrize("failure", ["cas_failure", "lost_ack", "value_error", "type_error"])
def test_policy_write_cas_failure_and_lost_ack_stay_unconfirmed(configured_agent, monkeypatch, failure):
    native = Native(configured_agent["agentId"])
    control = _control(native)
    def fail(**values):
        if failure == "lost_ack":
            native.publish(**values)
            raise TimeoutError("compiled acknowledgement lost")
        if failure == "value_error":
            raise ValueError("publication failed after registry mutation")
        if failure == "type_error":
            raise TypeError("publication failed after registry mutation")
        raise RuntimeError("compiled CAS rejected")
    monkeypatch.setattr(native.store.repository, "compare_and_swap_agent_config", fail)
    with server_operator_scope("operator-test", roles=("operator",)):
        before = control.read_tool_policy(configured_agent["agentId"])
        with pytest.raises(ManagementError) as unknown:
            control.update_tool_policy(_policy_parameters(before, maxCallsPerTurn=19))
        assert unknown.value.code == "OPERATION_UNCONFIRMED"
        after = control.read_tool_policy(configured_agent["agentId"])
    assert after["policy"]["maxCallsPerTurn"] == 19
    assert after["compiledMatches"] is (failure == "lost_ack")


@pytest.mark.parametrize("field,value", [
    ("role", "R" * 161),
    ("purpose", "P" * 1001),
    ("responsibilities", ["D" * 1001]),
])
def test_team_read_accepts_native_roster_text_without_expanding_writes(knowledge_env, monkeypatch, field, value):
    from core.web.services import team_service
    from core.web.services.team.team_crud import team_record_fingerprint
    from core.assistant_runtime.management_projection import project_management_asset

    row = deepcopy(knowledge_env["team"])
    member = {**row["members"][0], field: value}
    row["members"] = team_service._normalize_members([member], require_active=True)
    assert row["members"][0][field] == value
    control = _control(Native())
    monkeypatch.setattr(control, "_team_snapshot", lambda *_: deepcopy(row))
    with server_operator_scope("operator-test", roles=("operator",)):
        observed = control.read_team(row["teamId"])
    assert observed["members"][0][field] == value
    assert observed["fingerprint"] == team_record_fingerprint(row)
    pointer = f"/asset/members/0/{field}" + ("/0" if isinstance(value, list) else "")
    text = value[0] if isinstance(value, list) else value
    page = project_management_asset("team_asset_get", observed, "project-a",
        {"document_pointer": pointer, "limit": 100})
    assert page["value"] == text[:100]
    assert page["nextOffset"] == 100
    assert page["untrustedContent"] is True
    with pytest.raises(ValidationError):
        contracts.TeamUpdate.model_validate({"team_id": row["teamId"],
            "expected_team_fingerprint": observed["fingerprint"], "updates": {"members": [member]}})


def test_team_change_reuses_native_roster_rules_and_exact_fingerprint(knowledge_env):
    control = _control(Native())
    team_id = knowledge_env["team"]["teamId"]
    with server_operator_scope("operator-test", roles=("operator",)):
        before = control.read_team(team_id)
        result = control.update_team({"team_id": team_id, "expected_team_fingerprint": before["fingerprint"],
                                      "updates": {"name": "Maintained Team"}})
        assert result["verified"] is True
        assert control.read_team(team_id)["name"] == "Maintained Team"
        with pytest.raises(ManagementError) as stale:
            control.update_team({"team_id": team_id, "expected_team_fingerprint": before["fingerprint"],
                                 "updates": {"name": "stale overwrite"}})
        assert stale.value.code == "STATE_CONFLICT"


def test_team_roster_change_still_obeys_native_archive_lease(knowledge_env):
    from core.web.services.team.team_admission import archive_admission
    control = _control(Native())
    team_id = knowledge_env["team"]["teamId"]
    with server_operator_scope("operator-test", roles=("operator",)):
        before = control.read_team(team_id)
        with archive_admission(team_id):
            with pytest.raises(ManagementError) as locked:
                control.update_team({"team_id": team_id, "expected_team_fingerprint": before["fingerprint"],
                                     "updates": {"members": []}})
        assert locked.value.code == "TEAM_LOCKED"
        assert control.read_team(team_id)["members"] == before["members"]


def test_team_post_write_followup_failure_is_unconfirmed(knowledge_env, monkeypatch):
    from core.web.services import team_service
    control = _control(Native())
    team_id = knowledge_env["team"]["teamId"]
    def lost_detail(*_args, **_kwargs):
        raise ValueError("detail follow-up failed after Team index commit")
    with server_operator_scope("operator-test", roles=("operator",)):
        before = control.read_team(team_id)
        monkeypatch.setattr(team_service, "get_team", lost_detail)
        with pytest.raises(ManagementError) as unknown:
            control.update_team({"team_id": team_id, "expected_team_fingerprint": before["fingerprint"],
                                 "updates": {"name": "Already persisted"}})
        assert unknown.value.code == "OPERATION_UNCONFIRMED"
        assert control.read_team(team_id)["name"] == "Already persisted"


def test_acl_write_requires_exact_canonical_scoped_reference(knowledge_env):
    control = _control(Native())
    alias = knowledge_env["base"]["knowledgeBaseId"]
    with server_operator_scope("operator-test", roles=("operator",)):
        before = control.read_knowledge_acl(alias)
        assert before["scopedKnowledgeBaseId"] != alias
        parameters = {"knowledge_base_id": alias, "target_agent_id": knowledge_env["outsider"]["agentId"],
                      "permissions": ["read"], "expected_acl_fingerprint": before["fingerprint"]}
        for mutate in (control.grant_knowledge_acl, control.revoke_knowledge_acl):
            with pytest.raises(ManagementError) as rejected:
                mutate(parameters)
            assert rejected.value.code == "INVALID_INPUT"
        assert control.read_knowledge_acl(alias)["fingerprint"] == before["fingerprint"]


def test_operator_acl_grant_revoke_is_versioned_audited_and_preserves_agent_gate(knowledge_env):
    control = _control(Native())
    base_id = knowledge_env["base"]["knowledgeBaseId"]
    outsider = knowledge_env["outsider"]["agentId"]
    target = knowledge_env["member"]["agentId"]
    with pytest.raises(knowledge.TeamKnowledgePermissionError):
        knowledge.read_operator_knowledge_base_acl(base_id)
    with server_operator_scope("operator-test", roles=("operator",)):
        before = control.read_knowledge_acl(base_id)
        with pytest.raises(knowledge.TeamKnowledgePermissionError):
            knowledge.grant_knowledge_base_access(base_id, target, permissions=["review"], actor_agent_id=outsider)
        parameters = {"knowledge_base_id": before["scopedKnowledgeBaseId"], "target_agent_id": outsider, "permissions": ["read", "propose"],
                      "expected_acl_fingerprint": before["fingerprint"]}
        granted = control.grant_knowledge_acl(parameters)
        after = control.read_knowledge_acl(base_id)
        assert granted["verified"] is True and outsider in after["acl"]["grants"]["read"]
        with pytest.raises(ManagementError) as stale:
            control.revoke_knowledge_acl(parameters)
        assert stale.value.code == "STATE_CONFLICT"
        revoked = control.revoke_knowledge_acl({**parameters, "expected_acl_fingerprint": after["fingerprint"]})
        assert revoked["verified"] is True
        assert outsider not in control.read_knowledge_acl(base_id)["acl"]["grants"]["read"]
    owner, _ = knowledge._require_base_with_owner(base_id)
    rows = knowledge._read_jsonl(knowledge._audit_path_for_owner(owner))
    operator_rows = [row for row in rows if row.get("actorOperatorId") == "operator-test"]
    assert [row["action"] for row in operator_rows] == ["knowledge_base.operator_access_granted", "knowledge_base.operator_access_revoked"]
    assert all(not row.get("actorAgentId") for row in operator_rows)
    with pytest.raises(knowledge.TeamKnowledgePermissionError):
        knowledge.grant_knowledge_base_access(base_id, target, permissions=["review"], actor_agent_id=outsider)


@pytest.mark.parametrize("resource,condition", [
    (resource, condition) for resource in ("team", "policy", "acl_scoped", "acl_alias")
    for condition in ("existing", "missing", "bad_json", "bad_shape", "developer_no_active", "developer_missing_workspace", "developer_missing_authority")
] + [("policy", condition) for condition in (
    "missing_registry", "bad_registry", "registry_source_changed", "missing_registry_source_changed",
    "broken_registry_leaf_symlink", "linked_registry_parent_missing_file", "registry_deleted_during_read")])
def test_operator_asset_reads_never_initialize_repair_or_seed(tmp_path, monkeypatch, resource, condition):
    from core.infrastructure import developer_sandbox
    from core.web.services import team_service, tool_registry_service as registry
    from core.web.services.external_management.asset_control import AssetControl

    root, workspace, config = tmp_path / "project", tmp_path / "formal/workspace", tmp_path / "operator.toml"
    root.mkdir()
    workspace.mkdir(parents=True)
    developer = condition.startswith("developer_")
    config.write_text("[launcher.developer_mode]\nenabled = " + ("true" if developer else "false") + "\n", encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "data"))
    for module in (directory, team_service, knowledge, registry, developer_sandbox):
        monkeypatch.setattr(module, "PROJECT_ROOT", root)
    monkeypatch.setattr(directory, "CONFIG_PATH", config)
    monkeypatch.setattr(developer_sandbox, "CONFIG_PATH", config)
    monkeypatch.setattr(developer_sandbox, "formal_workspace_path", lambda _root, *parts: workspace.joinpath(*parts))
    if condition in {"developer_missing_workspace", "developer_missing_authority"}:
        active = developer_sandbox._active_state_path(root)
        active.parent.mkdir(parents=True, exist_ok=True)
        active.write_text(json.dumps({"schemaVersion": 1, "sandboxId": "sandbox-existing"}), encoding="utf-8")
        if condition == "developer_missing_authority":
            (developer_sandbox._sandbox_root(root, "sandbox-existing") / "workspace").mkdir(parents=True)
    raw = {"agentId": "agent-a", "agentCode": "AG-A", "displayName": "A", "status": "active",
        "kind": "persistent", "roleKey": "assistant_worker", "configRevision": 1, "updatedAt": "2026-01-01T00:00:00Z",
        "toolPolicyId": "tool-a", "toolPolicy": {**directory.default_tool_policy("tool-a"), "allowedTools": ["cli_tool"]},
        "metadata": {"delegationPolicy": {"allowSubagents": False}}}
    team = {"teamId": "team-a", "name": "A", "description": "", "purpose": "", "status": "active", "members": [], "updatedAt": "now"}
    base = {"knowledgeBaseId": "kb-a", "status": "active", "updatedAt": "now", "acl": {}}
    files = {"agents/agents.json": {"schemaVersion": 1, "agents": [raw]},
             "teams/teams.json": {"schemaVersion": 1, "teams": [team]},
             "teams/team-a/knowledge/knowledge_bases.json": {"schemaVersion": 1, "knowledgeBases": [base]},
             "tool_registry/generated_tools.json": {"schemaVersion": 1, "tools": []}}
    for name, value in files.items():
        path = workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
    authority = workspace / ({"team": "teams/teams.json", "policy": "agents/agents.json",
        "acl_scoped": "teams/team-a/knowledge/knowledge_bases.json", "acl_alias": "teams/team-a/knowledge/knowledge_bases.json"}[resource])
    if condition == "missing":
        authority.unlink()
    elif condition == "bad_json":
        authority.write_text("{broken", encoding="utf-8")
    elif condition == "bad_shape":
        value = json.loads(authority.read_text(encoding="utf-8"))
        if resource == "team":
            value["teams"][0]["members"] = "invalid"
        elif resource == "policy":
            value["agents"][0]["toolPolicy"] = "invalid"
        else:
            value["knowledgeBases"][0]["acl"] = "invalid"
        authority.write_text(json.dumps(value), encoding="utf-8")
    generated = workspace / "tool_registry/generated_tools.json"
    if condition in {"missing_registry", "missing_registry_source_changed"}:
        generated.unlink()
    elif condition == "bad_registry":
        generated.write_text("{broken", encoding="utf-8")
    elif condition in {"broken_registry_leaf_symlink", "linked_registry_parent_missing_file"}:
        generated.unlink()
        try:
            if condition == "broken_registry_leaf_symlink":
                generated.symlink_to(generated.parent / "missing-manifest.json")
                assert generated.is_symlink() and not generated.exists()
            else:
                generated.parent.rmdir()
                target = workspace / "registry-link-target"
                target.mkdir()
                generated.parent.symlink_to(target, target_is_directory=True)
                assert generated.parent.is_symlink() and not generated.exists()
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314:
                pytest.skip("Windows symbolic-link creation requires an unavailable privilege")
            raise
    native = SimpleNamespace(project_root=root, _owners=lambda: directory,
        _editable=lambda agent: NativeAgentGateway._editable(None, agent),
        _control_store=lambda: SimpleNamespace(repository=SimpleNamespace(
            get_current_agent_config=lambda _id: {"configRevisionId": "current", "config": canonical_agent_config_payload(raw)})))
    control = AssetControl(native)
    def forbidden(*_args, **_kwargs):
        pytest.fail("Operator read invoked native hydration, initialization, seeding or a writer")
    for name in ("get_agent", "list_agents", "load_state", "save_state", "repair_agent_directory"):
        monkeypatch.setattr(directory, name, forbidden)
    monkeypatch.setattr(team_service, "_load_index", forbidden)
    monkeypatch.setattr(team_service, "list_teams_compact", forbidden)
    monkeypatch.setattr(developer_sandbox, "_ensure_active_state", forbidden)
    monkeypatch.setattr(developer_sandbox, "seeded_sandbox_workspace_path", forbidden)
    monkeypatch.setattr(developer_sandbox, "sandboxed_workspace_path", forbidden)
    # Keep real snapshot/path/authority reading and native descriptor assembly;
    # dependency probes are facts, not permission to start background refresh.
    import tools.web_search_tool as web_search
    monkeypatch.setattr(web_search, "autoglm_search_tool_availability", forbidden)
    def inventory():
        result = {}
        for path in tmp_path.rglob("*"):
            info = path.lstat()
            content = (os.readlink(path) if stat.S_ISLNK(info.st_mode)
                       else path.read_bytes() if stat.S_ISREG(info.st_mode) else None)
            result[str(path.relative_to(tmp_path))] = (info.st_mode, info.st_mtime_ns, content)
        return result
    def after_manifest_mutation(previous):
        current = inventory()
        allowed = {str(path.relative_to(tmp_path)) for path in (generated, generated.parent)}
        assert {key: value for key, value in current.items() if key not in allowed} == {
            key: value for key, value in previous.items() if key not in allowed}
        return current
    before = inventory()
    deleted = []
    if condition == "registry_deleted_during_read":
        original_open = Path.open
        def delete_manifest_on_open(path, *args, **kwargs):
            nonlocal before
            mode = args[0] if args else kwargs.get("mode", "r")
            # Match the lexical file; resolving would erase precisely the alias
            # boundary exercised by the other optional-catalog cases.
            if path == generated and mode == "rb" and not deleted:
                assert path.is_file()
                path.unlink()
                deleted.append(path)
                before = after_manifest_mutation(before)
            return original_open(path, *args, **kwargs)
        monkeypatch.setattr(Path, "open", delete_manifest_on_open)
    operation = {"team": lambda: control.read_team("team-a"),
        "policy": lambda: control.read_tool_policy("agent-a"),
        "acl_scoped": lambda: control.read_knowledge_acl("team:team-a:kb-a"),
        "acl_alias": lambda: control.read_knowledge_acl("kb-a")}[resource]
    with server_operator_scope("operator-test", roles=("operator",)):
        if condition in {"registry_source_changed", "missing_registry_source_changed"}:
            first = operation()
            assert inventory() == before
            assert "cli_tool" in first["visibleTools"]
            generated.write_text(json.dumps({"schemaVersion": 1, "tools": [{"id": "dynamic_tool",
                "name": "dynamic_tool", "status": "validated", "validated": True, "enabled": True,
                "argsSchema": {"type": "object", "properties": {}}}]}), encoding="utf-8")
            before = after_manifest_mutation(before)
            second = operation()
            assert inventory() == before
            assert second["registryVersion"] == first["registryVersion"]
            assert second["registryFingerprint"] != first["registryFingerprint"]
            with pytest.raises(ManagementError) as stale:
                control.update_tool_policy(_policy_parameters(first, maxCallsPerTurn=27))
            assert stale.value.code == "STATE_CONFLICT"
        elif condition in {"existing", "missing_registry"}:
            result = operation()
            assert result["untrustedContent"] is True
            if condition == "missing_registry":
                assert "cli_tool" in result["visibleTools"]
                assert not generated.exists()
        else:
            with pytest.raises(ManagementError) as unavailable:
                operation()
            assert unavailable.value.code.endswith("UNAVAILABLE")
    if condition == "registry_deleted_during_read":
        assert deleted == [generated]
    assert inventory() == before
