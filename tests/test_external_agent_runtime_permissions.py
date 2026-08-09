from __future__ import annotations

from core.web.services import agent_directory_service
from core.web.services.agent_directory import projections
from core.web.services.external_agent.policy import external_runtime_tool_grants
from core.web.services.session import worker


def _persistent_policy() -> dict:
    return {
        "policyId": "tool-external-runtime-probe",
        "policyVersion": 1,
        "allowedTools": [
            "grep_search_tool",
            "read_file_tool",
            "apply_patch_tool",
            "python_lint_tool",
            "clean_workspace_debris_tool",
            "agent_message_tool",
        ],
        "blockedTools": [],
        "preferredTools": ["apply_patch_tool", "grep_search_tool"],
        "networkAccess": "restricted",
        "mutationAccess": "controlled",
        "delegationAccess": "none",
        "maxCallsPerTurn": 16,
        "approvalOverrides": {"apply_patch_tool": "never"},
    }


def test_external_permission_grants_are_profile_bounded() -> None:
    read_only = set(external_runtime_tool_grants("read_only"))
    workspace_write = set(external_runtime_tool_grants("workspace_write"))
    full_access = set(external_runtime_tool_grants("full_access"))

    assert {"grep_search_tool", "read_file_tool"} <= read_only
    assert "apply_patch_tool" not in read_only
    assert "python_lint_tool" not in read_only
    assert "apply_patch_tool" in workspace_write
    assert "python_lint_tool" in workspace_write
    assert "clean_workspace_debris_tool" not in workspace_write
    assert "agent_message_tool" not in workspace_write
    assert "clean_workspace_debris_tool" in full_access
    for grants in (read_only, workspace_write, full_access):
        assert "agent_message_tool" not in grants
        assert "list_child_sessions_tool" not in grants
        assert "source_collection_context_tool" not in grants
        assert "unified_memory_search_tool" not in grants


def test_external_runtime_policy_intersects_agent_policy_and_forces_explicit_write_approval() -> (
    None
):
    policy = _persistent_policy()
    runtime = agent_directory_service._with_runtime_tool_grants(
        policy,
        external_runtime_tool_grants("workspace_write"),
        source="external_agent_task:workspace_write",
    )

    assert runtime["allowedTools"] == [
        "grep_search_tool",
        "read_file_tool",
        "apply_patch_tool",
        "python_lint_tool",
    ]
    assert runtime["preferredTools"] == ["apply_patch_tool", "grep_search_tool"]
    assert runtime["approvalOverrides"]["apply_patch_tool"] == "always"
    assert runtime["approvalOverrides"]["python_lint_tool"] == "always"
    assert runtime["runtimeToolSource"] == "external_agent_task:workspace_write"
    assert policy["approvalOverrides"]["apply_patch_tool"] == "never"


def test_external_read_only_runtime_disables_mutation_even_if_agent_is_full_access() -> (
    None
):
    runtime = agent_directory_service._with_runtime_tool_grants(
        _persistent_policy(),
        external_runtime_tool_grants("read_only"),
        source="external_agent_task:read_only",
    )

    assert runtime["allowedTools"] == ["grep_search_tool", "read_file_tool"]
    assert runtime["mutationAccess"] == "none"
    assert (
        projections._runtime_permission_preset(
            "full_access",
            runtime_tool_source="external_agent_task:read_only",
        )
        == "request_approval"
    )


def test_worker_only_accepts_external_profile_from_internal_external_source() -> None:
    trusted = {
        "user_message_source": "external_agent_task",
        "message_metadata": {
            "source": "external_agent_task",
            "effectivePermissionProfile": "workspace_write",
        },
    }
    spoofed = {
        "user_message_source": "user",
        "message_metadata": {
            "source": "external_agent_task",
            "effectivePermissionProfile": "full_access",
        },
    }

    assert (
        worker._external_agent_runtime_permission_profile(trusted) == "workspace_write"
    )
    assert worker._external_agent_runtime_permission_profile(spoofed) == ""


def test_worker_only_allows_external_auto_continue_from_trusted_backend_metadata() -> None:
    trusted = {
        "user_message_source": "external_agent_task",
        "message_metadata": {
            "source": "external_agent_task",
            "allowInternalAutoContinue": True,
        },
    }
    spoofed = {
        "user_message_source": "user",
        "message_metadata": {
            "source": "external_agent_task",
            "allowInternalAutoContinue": True,
        },
    }

    assert worker._session_context_allows_internal_auto_continue(trusted) is True
    assert worker._session_context_allows_internal_auto_continue(spoofed) is False


def test_active_agent_runtime_applies_external_profile_end_to_end(monkeypatch) -> None:
    agent = {
        "agentId": "coder",
        "permissionPreset": "full_access",
        "toolPolicyId": "tool-external-runtime-probe",
        "toolPolicy": _persistent_policy(),
        "metadata": {},
    }
    monkeypatch.setattr(
        agent_directory_service,
        "get_agent",
        lambda agent_id, **_kwargs: agent if agent_id == "coder" else None,
    )

    with agent_directory_service.active_agent_runtime(
        "coder",
        session_id="session-external",
        turn_id="turn-external",
        runtime_tool_grants=external_runtime_tool_grants("workspace_write"),
        runtime_tool_source="external_agent_task:workspace_write",
    ) as runtime:
        visible = agent_directory_service.effective_visible_tool_names_for_current_agent(
            [
                "read_file_tool",
                "apply_patch_tool",
                "clean_workspace_debris_tool",
                "agent_message_tool",
            ]
        )

    assert runtime["permissionPreset"] == "request_approval"
    assert "apply_patch_tool" in runtime["toolPolicy"]["allowedTools"]
    assert "agent_message_tool" not in runtime["toolPolicy"]["allowedTools"]
    assert visible == ["apply_patch_tool"]
    assert runtime["toolPolicy"]["approvalOverrides"]["apply_patch_tool"] == "always"
    assert runtime["toolPolicy"]["runtimeToolSource"] == (
        "external_agent_task:workspace_write"
    )
