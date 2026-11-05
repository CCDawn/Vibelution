"""The native assistant can discover, edit and verify finite non-secret settings."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest
from pydantic import ValidationError

from tests.test_external_management_workspace import env
from tests.test_external_management_session_parameters import parameters_env
from tests.test_external_management_agent_configuration import configuration_env


@pytest.fixture
def prompt_env(configuration_env, monkeypatch):
    from core.web.services import prompt_template_service as prompts, agent_operation_service as operations
    from core.web.services.agent_config_authority import canonical_agent_config_payload
    from core.web.services.external_management.configuration_discovery import ConfigurationDiscovery

    data = configuration_env
    data.agent["promptTemplateId"] = "prompt-shared"
    data.save()
    current = data.store.repository.get_current_agent_config("agent-a")
    data.store.repository.compare_and_swap_agent_config(agent_id="agent-a",
        expected_config_revision_id=current["configRevisionId"], display_name=data.agent["displayName"],
        kind=data.agent["kind"], status="active", config=canonical_agent_config_payload(data.agent), source="test").result(timeout=3)
    data.index = data.root / "agent_config" / "prompt_templates.json"
    data.index.parent.mkdir()
    data.shared_file = data.root / "shared-prompt.md"
    data.shared_file.write_text("SHARED PROMPT", encoding="utf-8")
    data.index.write_text(json.dumps({"schemaVersion": 1, "templates": [{"templateId": "prompt-shared",
        "name": "Shared", "category": "general", "status": "active", "sourcePath": "shared-prompt.md",
        "content": "SHARED PROMPT", "metadata": {"SECRET": "not public"}}]}), encoding="utf-8")
    data.discovery = ConfigurationDiscovery(data.native)
    monkeypatch.setattr(data.directory, "load_state", lambda: {"agents": [deepcopy(data.agent)]})
    def update(agent_id, **kwargs):
        assert agent_id == "agent-a"
        assert kwargs["expected_config_revision"] == data.agent["configRevision"]
        data.agent.update(kwargs["updates"])
        data.agent["configRevision"] += 1
        data.save()
        return deepcopy(data.agent)
    monkeypatch.setattr(operations, "update_agent_from_catalog_request", update)
    data.prompt_request = {"agent_id": "agent-a", "expected_config_revision": 7,
        "expected_template_id": "prompt-shared", "expected_content_hash": "sha256:" + hashlib.sha256(b"SHARED PROMPT").hexdigest(),
        "content": "AGENT LOCAL PROMPT"}
    return data


def test_prompt_read_is_existing_only_and_does_not_export_metadata(prompt_env, monkeypatch):
    from core.web.services import prompt_template_service as prompts
    data = prompt_env
    def forbidden(*_args, **_kwargs):
        pytest.fail("Prompt GET repaired or initialized state")
    for name in ("repair_prompt_templates", "prompt_template_path", "get_prompt_template", "_workspace_path"):
        monkeypatch.setattr(prompts, name, forbidden)
    before = data.index.read_bytes()
    result = data.discovery.read_prompt("agent-a")
    assert result["template"]["content"] == "SHARED PROMPT"
    assert "content" not in result["candidates"][0]
    assert "SECRET" not in json.dumps(result)
    assert result["editScope"] == "single_agent_copy_on_write"
    assert data.index.read_bytes() == before


def test_prompt_edit_copies_inline_and_preserves_shared_source_and_record(prompt_env):
    data = prompt_env
    original = json.loads(data.index.read_text(encoding="utf-8"))["templates"][0]
    result = data.discovery.update_prompt(data.prompt_request)
    assert result["verified"] and result["revision"] == 8
    records = json.loads(data.index.read_text(encoding="utf-8"))["templates"]
    assert records[0] == original and data.shared_file.read_text(encoding="utf-8") == "SHARED PROMPT"
    assert len(records) == 2 and records[1]["sourcePath"] == ""
    assert records[1]["content"] == "AGENT LOCAL PROMPT"
    assert data.agent["promptTemplateId"] == records[1]["templateId"]
    assert data.discovery.read_prompt("agent-a")["template"]["content"] == "AGENT LOCAL PROMPT"


def test_unrelated_missing_prompt_source_does_not_block_selected_agent(prompt_env):
    data = prompt_env
    payload = json.loads(data.index.read_text(encoding="utf-8"))
    payload["templates"].append({"templateId": "missing-source", "sourcePath": "missing.md", "category": "general"})
    data.index.write_text(json.dumps(payload), encoding="utf-8")
    result = data.discovery.read_prompt("agent-a")
    candidate = next(row for row in result["candidates"] if row["templateId"] == "missing-source")
    assert candidate["contentAvailable"] is False and candidate["contentHash"] is None
    assert data.discovery.update_prompt(data.prompt_request)["verified"]


@pytest.mark.parametrize("field,value", [("expected_config_revision", 6),
    ("expected_template_id", "other"), ("expected_content_hash", "sha256:" + "0" * 64)])
def test_prompt_cas_rejects_before_any_write(prompt_env, field, value):
    from core.web.services.external_management.service import ManagementError
    data = prompt_env
    before = data.index.read_bytes()
    with pytest.raises(ManagementError) as error:
        data.discovery.update_prompt({**data.prompt_request, field: value})
    assert error.value.code == "STATE_CONFLICT"
    assert data.index.read_bytes() == before and data.agent["configRevision"] == 7


def test_prompt_partial_durability_returns_unknown_and_never_claims_success(prompt_env, monkeypatch):
    from core.web.services.external_management.service import ManagementError
    data = prompt_env
    def fail(**_kwargs):
        raise OSError("ack lost")
    monkeypatch.setattr(data.store.repository, "compare_and_swap_agent_config", fail)
    with pytest.raises(ManagementError) as error:
        data.discovery.update_prompt(data.prompt_request)
    assert error.value.code == "OPERATION_UNCONFIRMED"
    assert data.agent["configRevision"] == 8


@pytest.mark.parametrize("raw", ['{"allowedTools":[],"allowedTools":["cli_tool"]}',
    '{"approvalGrants":{}}', '{"networkAccess":"invalid"}', '[]', '{"maxCallsPerTurn":NaN}'])
def test_policy_discovery_cannot_inject_credentials_or_ambiguous_json(raw):
    from core.web.services.external_management.configuration_discovery_contracts import ToolPolicyInspectQuery
    with pytest.raises(ValidationError):
        ToolPolicyInspectQuery(agent_id="agent-a", updates_json=raw)


def test_action_discovery_and_approval_share_native_schemas():
    from core.assistant_runtime import actions
    from core.assistant_runtime.platform_approval import platform_management_approval_summary
    from core.web.services.external_management.contracts import contracts, EXPLICIT_UPGRADE_SCOPES
    for name in ("agent_config_get", "agent_prompt_get", "agent_tool_policy_inspect"):
        assert name in actions._project_read_contracts() and name in actions._HELP
    assert {"agents:configuration:read", "agents:configuration:write"} <= EXPLICIT_UPGRADE_SCOPES
    for name in ("agent_prompt_update", "agent_parameters_update"):
        assert contracts()[name]["governed"]
    summary = platform_management_approval_summary("agent_prompt_update", {
        "project_id": "project", "request_id": "request", "agent_id": "agent-a", "expected_config_revision": 7,
        "expected_template_id": "shared", "expected_content_hash": "sha256:" + "a" * 64, "content": "PRIVATE FULL PROMPT"})
    assert "PRIVATE FULL PROMPT" not in json.dumps(summary)
    assert summary["assistantTargets"] == {"project_id": "project", "request_id": "request", "agent_id": "agent-a",
        "expected_config_revision": "7", "expected_template_id": "shared", "expected_content_hash": "sha256:" + "a" * 64}
    assert summary["assistantChangedFields"] == ["promptContent", "promptTemplateId"]
    assert summary["assistantContentOmitted"] is True and summary["assistantDetailsOmitted"] is False
    assert summary["assistantDelta"] == {"scope": "single_agent_copy_on_write", "contentChars": "19",
        "contentDigest": hashlib.sha256(json.dumps("PRIVATE FULL PROMPT").encode()).hexdigest(), "activation": "next_submission"}


@pytest.mark.parametrize("kind,parameters,expected", [
    ("model", {"expected_model_ref": "relay/model", "context_window": 9007199254740993, "reasoning_effort": "high"},
        {"expected_model_ref": "relay/model", "context_window": "9007199254740993", "reasoning_effort": "high"}),
    ("budget", {"maxCallsPerTurn": None}, {"maxCallsPerTurn": None}),
    ("budget", {"maxCallsPerTurn": 0}, {"maxCallsPerTurn": "0"}),
    ("budget", {"maxCallsPerTurn": 200}, {"maxCallsPerTurn": "200"}),
])
def test_agent_parameter_approval_preserves_native_types_and_exact_targets(kind, parameters, expected):
    from core.assistant_runtime.platform_approval import platform_management_approval_summary
    summary = platform_management_approval_summary("agent_parameters_update", {"project_id": "project", "request_id": "request",
        "agent_id": "agent-a", "expected_config_revision": 9007199254740993, "kind": kind, "parameters": parameters})
    assert summary["assistantTargets"] == {"project_id": "project", "request_id": "request", "agent_id": "agent-a",
        "expected_config_revision": "9007199254740993", "kind": kind}
    assert summary["assistantChangedFields"] == [kind] and summary["assistantDelta"] == expected
    assert summary["assistantContentOmitted"] is False and summary["assistantDetailsOmitted"] is False


def test_compression_approval_preserves_float_thresholds_and_serializes_integer_defaults():
    from core.assistant_runtime.platform_approval import platform_management_approval_summary
    summary = platform_management_approval_summary("agent_parameters_update", {"project_id": "project", "request_id": "request",
        "agent_id": "agent-a", "expected_config_revision": 0, "kind": "compression", "parameters": {"policy": {
            "mode": "custom", "enabled": True, "maxTokenLimit": 50000, "maxCompressionsPerSession": 10,
            "levels": {"light": 0.7, "standard": 0.8, "deep": 0.9, "emergency": 1},
            "summaryChars": {"light": 1000, "standard": 2000, "deep": 3000, "emergency": 4000},
            "preservation": {"keepAiMessages": 5, "preserveErrors": True, "extractKeyDecisions": False}}}})
    policy = summary["assistantDelta"]["policy"]
    assert policy["levels"] == {"light": 0.7, "standard": 0.8, "deep": 0.9, "emergency": 1.0}
    assert all(type(value) is float for value in policy["levels"].values())
    assert policy["summaryChars"] == {"light": "1000", "standard": "2000", "deep": "3000", "emergency": "4000"}
    assert policy["policyVersion"] == "0" and policy["compressionTriggerTokenLimit"] == "0"
    assert policy["postCompressionTargetTokenLimit"] == "0"
    assert policy["preservation"] == {"keepAiMessages": "5", "preserveErrors": True, "extractKeyDecisions": False, "retentionFocus": None}


def test_http_requires_explicit_new_scope_before_read(prompt_env):
    data = prompt_env
    url = "/v1/launcher-assistant-management/assets/agent-prompt"
    denied = data.client.get(url, params={"agent_id": "agent-a"}, headers=data.headers)
    assert denied.status_code == 403
    payload = {"request_id": "upgrade-config", "expected_binding": data.identity,
        "parameters": {"expected_scopes": ["sessions:read"], "add_scopes": ["agents:configuration:read"]}}
    upgraded = data.client.post("/v1/launcher-assistant-management/actions/authorization_upgrade",
        json=payload, headers=data.headers)
    assert upgraded.status_code == 200, upgraded.text
    response = data.client.get(url, params={"agent_id": "agent-a"}, headers=data.headers)
    assert response.status_code == 200, response.text
    assert response.json()["template"]["content"] == "SHARED PROMPT"
    extra = data.client.get(url, params={"agent_id": "agent-a", "metadata": "all"}, headers=data.headers)
    assert extra.status_code == 422


def test_http_prompt_write_receipt_is_idempotent_and_rejects_changed_content(prompt_env):
    data = prompt_env
    base = "/v1/launcher-assistant-management/actions/"
    upgraded = data.client.post(base + "authorization_upgrade", json={"request_id": "upgrade-write",
        "expected_binding": data.identity, "parameters": {"expected_scopes": ["sessions:read"],
            "add_scopes": ["agents:configuration:write"]}}, headers=data.headers)
    assert upgraded.status_code == 200, upgraded.text
    envelope = {"request_id": "prompt-edit", "expected_binding": data.identity, "parameters": data.prompt_request}
    first = data.client.post(base + "agent_prompt_update", json=envelope, headers=data.headers)
    assert first.status_code == 200, first.text
    assert first.json()["verified"] and first.json()["asset"]["revision"] == 8
    repeat = data.client.post(base + "agent_prompt_update", json=envelope, headers=data.headers)
    assert repeat.status_code == 200 and repeat.json()["reused"]
    assert len(json.loads(data.index.read_text(encoding="utf-8"))["templates"]) == 2
    changed = deepcopy(envelope)
    changed["parameters"]["content"] = "different"
    conflict = data.client.post(base + "agent_prompt_update", json=changed, headers=data.headers)
    assert conflict.status_code == 409


def test_model_projection_bounds_prompt_text_and_rejects_changed_digest():
    from core.assistant_runtime.management_projection import project_management_asset
    payload = {"template": {"content": "Long Prompt " * 8000}}
    first = project_management_asset("agent_prompt_get", payload, "project", {"document_pointer": "/asset/template/content"})
    assert len(json.dumps(first, ensure_ascii=False)) < 8000
    assert "Long Prompt " * 8000 not in json.dumps(first)
    changed = project_management_asset("agent_prompt_get", {"template": {"content": "changed"}}, "project",
        {"document_pointer": "/asset/template/content", "expected_document_digest": first["documentDigest"]})
    assert changed["ok"] is False
