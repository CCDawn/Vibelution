from __future__ import annotations

import pytest

from core.web.services import agent_directory_service, tool_policy_configuration_service
from tests.test_agent_config_workspace_service import _mark_config_agent_instances_present, _use_tmp_project_root, client


def _registry_payload():
    return {
        "registryVersion": "test-registry-v1",
        "tools": [
            {"name": "cli_tool", "enabled": True, "runtimeActive": True, "status": "validated", "permissionPolicy": {"requiresExplicitAllow": False}},
            {"name": "dangerous_tool", "enabled": True, "runtimeActive": True, "status": "validated", "permissionPolicy": {"requiresExplicitAllow": True}},
            {"name": "offline_tool", "enabled": True, "runtimeActive": False, "status": "validated"},
        ],
    }


@pytest.fixture()
def configured_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _mark_config_agent_instances_present()
    monkeypatch.setattr(tool_policy_configuration_service.tool_registry_service, "get_tool_registry", _registry_payload)
    agent = agent_directory_service.create_agent_instance(display_name="Policy Agent", primary_mode="chat")
    return agent_directory_service.update_agent_instance(
        agent["agentId"],
        tool_policy={"allowedTools": ["cli_tool"], "preferredTools": ["cli_tool"], "blockedTools": []},
    )


def test_validate_projects_exact_effective_visibility_and_invalid_names(configured_agent):
    response = client.post(
        f"/api/agents/{configured_agent['agentId']}/tool-policy/validate",
        json={"toolPolicy": {**configured_agent["toolPolicy"], "allowedTools": ["cli_tool", "offline_tool", "missing_tool"], "preferredTools": ["cli_tool"]}},
    )
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["validation"]["valid"] is False
    assert payload["preview"]["visibleTools"] == ["cli_tool"]
    assert payload["preview"]["unavailableTools"] == ["offline_tool"]
    assert payload["preview"]["unknownTools"] == ["missing_tool"]


def test_versioned_update_rejects_stale_policy_fingerprint(configured_agent):
    detail = client.get(f"/api/agents/{configured_agent['agentId']}/tool-policy").json()
    body = {
        "toolPolicy": {**detail["currentPolicy"], "blockedTools": ["cli_tool"], "allowedTools": [], "preferredTools": []},
        "expectedAgentUpdatedAt": detail["agent"]["updatedAt"],
        "expectedPolicyFingerprint": detail["policyFingerprint"],
        "confirmed": False,
    }
    updated = client.put(f"/api/agents/{configured_agent['agentId']}/tool-policy", json=body)
    stale = client.put(f"/api/agents/{configured_agent['agentId']}/tool-policy", json=body)
    assert updated.status_code == 200, updated.json()
    assert updated.json()["policyVersion"] == detail["policyVersion"] + 1
    assert stale.status_code == 409
    assert "changed after this editor was opened" in stale.json()["detail"]


def test_shared_or_high_risk_policy_requires_explicit_confirmation(configured_agent):
    second = agent_directory_service.create_agent_instance(display_name="Shared Policy Agent", primary_mode="chat")
    agent_directory_service.update_agent_instance(second["agentId"], tool_policy_id=configured_agent["toolPolicyId"])
    detail = client.get(f"/api/agents/{configured_agent['agentId']}/tool-policy").json()
    body = {
        "toolPolicy": {**detail["currentPolicy"], "allowedTools": ["cli_tool", "dangerous_tool"], "preferredTools": ["cli_tool"]},
        "expectedAgentUpdatedAt": detail["agent"]["updatedAt"],
        "expectedPolicyFingerprint": detail["policyFingerprint"],
        "confirmed": False,
    }
    blocked = client.put(f"/api/agents/{configured_agent['agentId']}/tool-policy", json=body)
    body["confirmed"] = True
    applied = client.put(f"/api/agents/{configured_agent['agentId']}/tool-policy", json=body)
    assert blocked.status_code == 409
    assert "affects 2 Agents" in blocked.json()["detail"]
    assert applied.status_code == 200, applied.json()
    assert applied.json()["impact"]["affectedAgentCount"] == 2
    assert "dangerous_tool" in applied.json()["preview"]["visibleTools"]
