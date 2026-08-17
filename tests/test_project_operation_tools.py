from __future__ import annotations

import json

import pytest

from core.infrastructure.agent_session import reset_session_state
from core.infrastructure.tool_executor import ToolExecutor
from core.web.services import agent_directory_service
from core.web.services import session_service
from core.web.services import team_knowledge_service
from core.web.services import tool_catalog
from core.web.services.agent_operation_service import create_agent_from_catalog_request
from tests.helpers.tool_authorization import authorized_agent_tool_executor
from tests.test_agent_config_workspace_service import (
    ProviderConfig,
    _fake_config_workspace,
    _use_tmp_project_root,
    client,
    config_service,
)
from tools.Key_Tools import create_key_tools, create_llm_facing_tools

PROJECT_OPERATION_TOOLS = (
    "agent_create_tool",
    "agent_update_tool",
    "agent_archive_tool",
    "agent_reset_tool",
    "session_create_tool",
    "session_update_tool",
    "session_stop_tool",
    "session_delete_tool",
    "agent_inbox_list_tool",
    "agent_message_consume_tool",
    "agent_messages_consume_all_tool",
    "knowledge_base_acl_grant_tool",
)

WRITE_OPERATION_TOOLS = (
    "agent_create_tool",
    "agent_update_tool",
    "session_create_tool",
    "session_update_tool",
    "session_stop_tool",
    "agent_message_consume_tool",
    "agent_messages_consume_all_tool",
    "knowledge_base_acl_grant_tool",
)

READ_OPERATION_TOOLS = ("agent_inbox_list_tool",)

DESTRUCTIVE_OPERATION_TOOLS = (
    "agent_archive_tool",
    "agent_reset_tool",
    "session_delete_tool",
)


@pytest.fixture(autouse=True)
def _isolate_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.delenv("VIBELUTION_AGENT_ID", raising=False)
    monkeypatch.delenv("VIBELUTION_AGENT_DIRECT_SESSION_ID", raising=False)
    reset_session_state()


def _executor_result(tool_name: str, args: dict) -> tuple[str, object]:
    result, action = ToolExecutor().execute(tool_name, args)
    return str(result or ""), action


def _payload(result: str) -> dict:
    data = json.loads(result)
    assert isinstance(data, dict)
    for key in ("status", "ok", "error", "message"):
        assert key in data, f"missing {key} in {data}"
    return data


def test_project_operation_tools_registered_in_key_and_llm_catalogs():
    canonical_names = {tool.name for tool in create_key_tools()}
    llm_names = {tool.name for tool in create_llm_facing_tools()}

    assert set(PROJECT_OPERATION_TOOLS).issubset(canonical_names)
    assert set(PROJECT_OPERATION_TOOLS).issubset(llm_names)
    assert "agent_purge_tool" not in canonical_names


def test_project_operation_tool_descriptors_match_governance_contract():
    descriptors = {
        item.name: item
        for item in tool_catalog.validate_tool_descriptors(
            tuple(
                tool_catalog.build_tool_descriptor(name, args_schema={"type": "object"})
                for name in PROJECT_OPERATION_TOOLS
            )
        )
    }

    for tool_name in WRITE_OPERATION_TOOLS:
        descriptor = descriptors[tool_name]
        assert descriptor.risk == "write"
        assert descriptor.approval == "on_request"
        assert descriptor.concurrency == "serialized"

    for tool_name in DESTRUCTIVE_OPERATION_TOOLS:
        descriptor = descriptors[tool_name]
        assert descriptor.risk == "destructive"
        assert descriptor.approval == "always"
        assert descriptor.concurrency == "serialized"

    for tool_name in READ_OPERATION_TOOLS:
        descriptor = descriptors[tool_name]
        assert descriptor.risk == "read"
        assert descriptor.approval == "never"
        assert descriptor.concurrency == "safe"


def test_project_operation_tools_in_default_session_agent_policy():
    allowed = set(agent_directory_service.DEFAULT_SESSION_AGENT_ALLOWED_TOOLS)
    assert set(PROJECT_OPERATION_TOOLS).issubset(allowed)


def test_agent_create_tool_rejects_blank_required_fields():
    result, action = _executor_result(
        "agent_create_tool",
        {
            "display_name": "",
            "primary_mode": "chat",
            "prompt_template_id": "prompt-chat-default",
            "model_id": "model-primary",
        },
    )

    payload = _payload(result)
    assert action is None
    assert payload["ok"] is False
    assert payload["status"] == "error"


def test_agent_create_tool_creates_chat_agent_with_defaults(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)

    result, action = _executor_result(
        "agent_create_tool",
        {
            "display_name": "工具创建会话",
            "primary_mode": "chat",
            "prompt_template_id": "prompt-chat-default",
            "model_id": "model-primary",
        },
    )

    payload = _payload(result)
    assert action is None
    assert payload["ok"] is True
    assert payload["status"] == "ok"
    agent_id = str(payload.get("agentId") or "").strip()
    assert agent_id
    agent = agent_directory_service.get_agent(agent_id)
    assert agent is not None
    assert agent["displayName"] == "工具创建会话"
    assert agent["primaryMode"] == "chat"
    assert agent["toolPolicy"]["allowedTools"] == list(
        agent_directory_service.DEFAULT_SESSION_AGENT_ALLOWED_TOOLS
    )


def test_agent_create_tool_applies_context_compression_policy_json(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    custom_policy = {
        "mode": "custom",
        "enabled": True,
        "maxTokenLimit": 131072,
    }

    result, action = _executor_result(
        "agent_create_tool",
        {
            "display_name": "压缩策略 Agent",
            "primary_mode": "chat",
            "prompt_template_id": "prompt-chat-default",
            "model_id": "model-primary",
            "context_compression_policy_json": json.dumps(custom_policy),
        },
    )

    payload = _payload(result)
    assert action is None
    assert payload["ok"] is True
    agent = agent_directory_service.get_agent(payload["agentId"])
    assert agent is not None
    assert agent["contextCompressionPolicy"]["mode"] == "custom"
    assert agent["contextCompressionPolicy"]["enabled"] is True
    assert agent["contextCompressionPolicy"]["maxTokenLimit"] == 131072


def test_agent_create_tool_rejects_invalid_context_compression_policy_json():
    result, action = _executor_result(
        "agent_create_tool",
        {
            "display_name": "无效压缩策略",
            "primary_mode": "chat",
            "prompt_template_id": "prompt-chat-default",
            "model_id": "model-primary",
            "context_compression_policy_json": "not-json",
        },
    )

    payload = _payload(result)
    assert action is None
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["error"] == "invalid_input"


def test_agent_create_tool_shares_service_semantics_with_api_route(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)

    api_response = client.post(
        "/api/agents",
        json={
            "displayName": "",
            "llmBindings": {"dialogue": {"modelId": "model-primary"}},
            "primaryMode": "chat",
            "promptTemplateId": "prompt-chat-default",
        },
    )
    assert api_response.status_code == 422

    tool_result, _action = _executor_result(
        "agent_create_tool",
        {
            "display_name": "",
            "primary_mode": "chat",
            "prompt_template_id": "prompt-chat-default",
            "model_id": "model-primary",
        },
    )
    tool_payload = _payload(tool_result)
    assert tool_payload["ok"] is False
    assert tool_payload["status"] == "error"


def test_agent_archive_tool_returns_busy_when_archive_in_flight(monkeypatch):
    from core.web.services.agent_bulk_delete_service import AgentLifecycleBusyError

    def raise_busy(agent_ids):
        raise AgentLifecycleBusyError("Agent archive already in progress for agent-busy.")

    monkeypatch.setattr(
        "core.web.services.agent_bulk_delete_service.bulk_archive_agents",
        raise_busy,
    )

    result, action = _executor_result("agent_archive_tool", {"agent_id": "agent-busy"})
    payload = _payload(result)

    assert action is None
    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert payload["error"] == "busy"


def test_create_agent_from_catalog_request_invalidates_workspace_cache_on_success(
    tmp_path, monkeypatch
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    calls: list[str] = []
    monkeypatch.setattr(
        "core.web.services.agent_operation_service.invalidate_agent_config_workspace_cache",
        lambda: calls.append("create"),
    )

    create_agent_from_catalog_request(
        display_name="缓存失效创建",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        prompt_template_id="prompt-chat-default",
        source="agent_create_tool",
    )

    assert calls == ["create"]


def test_create_agent_from_catalog_request_does_not_invalidate_on_validation_failure(monkeypatch):
    from core.web.services.agent_directory_service import AgentDirectoryError

    calls: list[str] = []
    monkeypatch.setattr(
        "core.web.services.agent_operation_service.invalidate_agent_config_workspace_cache",
        lambda: calls.append("create"),
    )

    with pytest.raises(AgentDirectoryError):
        create_agent_from_catalog_request(
            display_name="",
            llm_bindings={"dialogue": {"modelId": "model-primary"}},
            primary_mode="chat",
            prompt_template_id="prompt-chat-default",
            source="agent_create_tool",
        )

    assert calls == []


def test_agent_archive_tool_invalidates_workspace_cache_on_success(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    session = session_service.create_chat_session(title="缓存失效归档")
    calls: list[str] = []
    monkeypatch.setattr(
        "core.web.services.agent_config_workspace_service.invalidate_agent_config_workspace_cache",
        lambda: calls.append("archive"),
    )

    result, action = _executor_result("agent_archive_tool", {"agent_id": session["agentId"]})
    payload = _payload(result)

    assert action is None
    assert payload["ok"] is True
    assert calls == ["archive"]


def test_agent_reset_tool_invalidates_workspace_cache_on_success(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="缓存失效重置",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
    )
    calls: list[str] = []
    monkeypatch.setattr(
        "core.web.services.agent_config_workspace_service.invalidate_agent_config_workspace_cache",
        lambda: calls.append("reset"),
    )

    result, action = _executor_result("agent_reset_tool", {"agent_id": agent["agentId"]})
    payload = _payload(result)

    assert action is None
    assert payload["ok"] is True
    assert calls == ["reset"]


def test_agent_archive_tool_archives_agent_via_bulk_service(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    session = session_service.create_chat_session(title="待归档 Agent")
    agent_id = session["agentId"]

    result, action = _executor_result("agent_archive_tool", {"agent_id": agent_id})
    payload = _payload(result)

    assert action is None
    assert payload["ok"] is True
    assert payload["status"] == "ok"
    assert payload["agentId"] == agent_id
    archived = agent_directory_service.get_agent(agent_id)
    assert archived is not None
    assert archived["status"] == "archived"


def test_agent_archive_tool_blocks_protected_agent(monkeypatch):
    protected_id = "agent-protected-core"

    def reject_archive(agent_ids):
        return {
            "success": [],
            "skipped": [
                {
                    "agentId": protected_id,
                    "reason": "protected",
                    "message": "Protected core Agent cannot be archived.",
                }
            ],
            "failed": [],
        }

    monkeypatch.setattr(
        "core.web.services.agent_bulk_delete_service.bulk_archive_agents",
        reject_archive,
    )

    result, action = _executor_result("agent_archive_tool", {"agent_id": protected_id})
    payload = _payload(result)

    assert action is None
    assert payload["ok"] is False
    assert payload["status"] == "blocked"


def test_agent_reset_tool_resets_agent_instance(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="Reset Tool Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
    )

    result, action = _executor_result("agent_reset_tool", {"agent_id": agent["agentId"]})
    payload = _payload(result)

    assert action is None
    assert payload["ok"] is True
    assert payload["status"] == "ok"
    assert payload["agentId"] == agent["agentId"]
    assert payload.get("resetSummary")


def test_session_create_tool_defaults_agent_id_from_runtime(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="Session Create Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
    )
    direct_session_id = agent["directSessionId"]

    with authorized_agent_tool_executor(
        agent["agentId"],
        session_id=direct_session_id,
        executable_tools=("session_create_tool",),
    ) as execute:
        result, action = execute("session_create_tool", {"title": "并行工作会话"})
    payload = _payload(result)

    assert action is None
    assert payload["ok"] is True
    assert payload["status"] == "ok"
    session_id = str(payload.get("sessionId") or payload.get("id") or "").strip()
    assert session_id
    detail = session_service.get_session_detail(session_id)
    assert detail is not None
    assert detail["agentId"] == agent["agentId"]


def test_session_create_tool_fails_without_agent_id(monkeypatch):
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: {})

    result, action = _executor_result("session_create_tool", {"title": "无 Agent 会话"})
    payload = _payload(result)

    assert action is None
    assert payload["ok"] is False
    assert payload["status"] == "error"


def test_session_stop_tool_requires_turn_id(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    session = session_service.create_chat_session(title="Stop Contract Session")

    result, action = _executor_result(
        "session_stop_tool",
        {"session_id": session["id"], "turn_id": ""},
    )
    payload = _payload(result)

    assert action is None
    assert payload["ok"] is False
    assert payload["status"] == "error"


def test_session_stop_tool_calls_request_stop_with_turn_id(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    session = session_service.create_chat_session(title="Stop Guard Session")
    seen: dict[str, str] = {}

    def fake_request_stop(session_id: str, *, expected_turn_id: str = "") -> dict:
        seen["session_id"] = session_id
        seen["expected_turn_id"] = expected_turn_id
        return {"id": session_id, "status": "stopping"}

    monkeypatch.setattr(session_service, "request_stop_session_turn", fake_request_stop)

    result, action = _executor_result(
        "session_stop_tool",
        {"session_id": session["id"], "turn_id": "turn-abc"},
    )
    payload = _payload(result)

    assert action is None
    assert payload["ok"] is True
    assert payload["status"] == "ok"
    assert seen == {"session_id": session["id"], "expected_turn_id": "turn-abc"}


def test_session_delete_tool_deletes_session(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    session = session_service.create_chat_session(title="Delete Tool Session")

    result, action = _executor_result(
        "session_delete_tool",
        {"session_id": session["id"]},
    )
    payload = _payload(result)

    assert action is None
    assert payload["ok"] is True
    assert payload["status"] == "ok"
    assert payload.get("deletedSessionId") == session["id"]
    assert session_service.get_session_detail(session["id"]) is None


def _create_chat_agent(name: str) -> dict:
    return create_agent_from_catalog_request(
        display_name=name,
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        prompt_template_id="prompt-chat-default",
        source="test_project_operation_tools",
    )


def test_agent_update_tool_preserves_omitted_fields_and_records_revision(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = _create_chat_agent("Before update")
    original_prompt = agent["promptTemplateId"]

    result, action = _executor_result(
        "agent_update_tool",
        {
            "agent_id": agent["agentId"],
            "updates_json": json.dumps({"displayName": "After update"}),
        },
    )
    payload = _payload(result)

    assert action is None
    assert payload["ok"] is True
    updated = agent_directory_service.get_agent(agent["agentId"])
    assert updated["displayName"] == "After update"
    assert updated["promptTemplateId"] == original_prompt
    assert payload["publishedConfigChange"]


def test_agent_update_tool_rejects_lifecycle_status_and_conflict(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = _create_chat_agent("Update guard")

    status_result, _ = _executor_result(
        "agent_update_tool",
        {"agent_id": agent["agentId"], "updates_json": json.dumps({"status": "archived"})},
    )
    conflict_result, _ = _executor_result(
        "agent_update_tool",
        {
            "agent_id": agent["agentId"],
            "updates_json": json.dumps({"displayName": "Stale update"}),
            "expected_updated_at": "2000-01-01T00:00:00+00:00",
        },
    )

    assert _payload(status_result)["error"] == "validation_error"
    conflict = _payload(conflict_result)
    assert conflict["status"] == "blocked"
    assert conflict["error"] == "conflict"
    assert agent_directory_service.get_agent(agent["agentId"])["status"] == "active"


def test_session_update_tool_updates_title_and_rejects_empty_change(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    session = session_service.create_chat_session(title="Before session update")

    result, _ = _executor_result(
        "session_update_tool",
        {"session_id": session["id"], "title": "After session update"},
    )
    empty_result, _ = _executor_result(
        "session_update_tool",
        {"session_id": session["id"], "title": "", "agent_id": ""},
    )

    assert _payload(result)["session"]["title"] == "After session update"
    assert _payload(empty_result)["error"] == "update_required"


def test_agent_inbox_tools_list_and_consume_messages(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = _create_chat_agent("Inbox target")
    first = agent_directory_service.write_agent_inbox_message(agent["agentId"], content="First message")
    second = agent_directory_service.write_agent_inbox_message(agent["agentId"], content="Second message")

    listed_result, _ = _executor_result("agent_inbox_list_tool", {"agent_id": agent["agentId"]})
    listed = _payload(listed_result)
    assert listed["messageCount"] == 2

    consumed_result, _ = _executor_result(
        "agent_message_consume_tool",
        {"agent_id": agent["agentId"], "message_id": first["messageId"], "consumed_by_turn_id": "turn-1"},
    )
    consumed = _payload(consumed_result)
    assert consumed["inboxMessage"]["status"] == "consumed"
    assert consumed["inboxMessage"]["consumedByTurnId"] == "turn-1"

    all_result, _ = _executor_result("agent_messages_consume_all_tool", {"agent_id": agent["agentId"]})
    all_payload = _payload(all_result)
    assert all_payload["consumedCount"] == 1
    assert second["messageId"] in all_payload["consumedMessageIds"]


def test_agent_inbox_tools_return_not_found_for_unknown_targets():
    listed, _ = _executor_result("agent_inbox_list_tool", {"agent_id": "agent-missing"})
    consumed, _ = _executor_result(
        "agent_message_consume_tool",
        {"agent_id": "agent-missing", "message_id": "message-missing"},
    )
    consumed_all, _ = _executor_result("agent_messages_consume_all_tool", {"agent_id": "agent-missing"})

    assert _payload(listed)["error"] == "not_found"
    assert _payload(consumed)["error"] == "not_found"
    assert _payload(consumed_all)["error"] == "not_found"


def test_agent_inbox_tools_deny_cross_agent_runtime_access(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    actor = _create_chat_agent("Inbox actor")
    target = _create_chat_agent("Inbox other target")

    with authorized_agent_tool_executor(
        actor["agentId"],
        session_id=actor["directSessionId"],
        executable_tools=("agent_inbox_list_tool", "agent_message_consume_tool"),
    ) as execute:
        listed, _ = execute("agent_inbox_list_tool", {"agent_id": target["agentId"]})
        consumed, _ = execute(
            "agent_message_consume_tool",
            {"agent_id": target["agentId"], "message_id": "message-other"},
        )

    assert listed.lstrip().startswith("{"), listed
    assert consumed.lstrip().startswith("{"), consumed
    assert _payload(listed)["error"] == "permission_denied"
    assert _payload(consumed)["error"] == "permission_denied"


def test_knowledge_base_acl_grant_tool_is_authorized_and_idempotent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    owner = _create_chat_agent("Knowledge owner")
    target = _create_chat_agent("Knowledge reader")
    base = team_knowledge_service.create_agent_knowledge_base(
        owner["agentId"],
        name="Project handbook",
        actor_agent_id=owner["agentId"],
    )
    args = {
        "knowledge_base_id": base["knowledgeBaseId"],
        "target_agent_id": target["agentId"],
        "permissions_json": json.dumps(["read", "propose"]),
    }
    with authorized_agent_tool_executor(
        owner["agentId"],
        session_id=owner["directSessionId"],
        executable_tools=("knowledge_base_acl_grant_tool",),
    ) as execute:
        first, _ = execute("knowledge_base_acl_grant_tool", args)
        second, _ = execute("knowledge_base_acl_grant_tool", args)

    assert first.lstrip().startswith("{"), first
    assert second.lstrip().startswith("{"), second
    first_payload = _payload(first)
    second_payload = _payload(second)
    assert first_payload["grantResult"]["changedPermissions"] == ["read", "propose"]
    assert second_payload["grantResult"]["changed"] is False
    listed = team_knowledge_service.list_agent_knowledge_bases(
        owner["agentId"],
        actor_agent_id=target["agentId"],
    )
    assert listed["summary"]["knowledgeBaseCount"] == 1


def test_knowledge_base_acl_grant_tool_denies_non_reviewer_actor(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    owner = _create_chat_agent("ACL owner")
    outsider = _create_chat_agent("ACL outsider")
    target = _create_chat_agent("ACL target")
    base = team_knowledge_service.create_agent_knowledge_base(
        owner["agentId"],
        name="Private handbook",
        actor_agent_id=owner["agentId"],
    )
    with authorized_agent_tool_executor(
        outsider["agentId"],
        session_id=outsider["directSessionId"],
        executable_tools=("knowledge_base_acl_grant_tool",),
    ) as execute:
        result, _ = execute(
            "knowledge_base_acl_grant_tool",
            {
                "knowledge_base_id": base["knowledgeBaseId"],
                "target_agent_id": target["agentId"],
                "permissions_json": json.dumps(["read"]),
            },
        )
    payload = _payload(result)

    assert payload["status"] == "blocked"
    assert payload["error"] == "permission_denied"


def test_knowledge_base_acl_grant_tool_rejects_wildcard(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    owner = _create_chat_agent("Wildcard owner")
    target = _create_chat_agent("Wildcard target")
    base = team_knowledge_service.create_agent_knowledge_base(
        owner["agentId"],
        name="Wildcard guard",
        actor_agent_id=owner["agentId"],
    )

    with authorized_agent_tool_executor(
        owner["agentId"],
        session_id=owner["directSessionId"],
        executable_tools=("knowledge_base_acl_grant_tool",),
    ) as execute:
        result, _ = execute(
            "knowledge_base_acl_grant_tool",
            {
                "knowledge_base_id": base["knowledgeBaseId"],
                "target_agent_id": target["agentId"],
                "permissions_json": json.dumps(["*"]),
            },
        )

    payload = _payload(result)
    assert payload["error"] == "validation_error"
