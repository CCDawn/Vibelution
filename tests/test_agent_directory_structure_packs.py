"""Focused tests for agent_directory structure packs."""

from __future__ import annotations

from core.web.services import agent_directory_service as facade
from core.web.services.agent_directory import (
    lifecycle,
    mutations,
    ops_residual,
    policies,
    profiles,
    projections,
    repair_store,
)


def test_facade_reexports_profiles_pack() -> None:
    assert facade.normalize_persona_profile is profiles.normalize_persona_profile
    assert facade.normalize_task_profile is profiles.normalize_task_profile
    assert facade.agent_persona_profile_has_content is profiles.agent_persona_profile_has_content


def test_facade_reexports_policies_pack() -> None:
    assert facade.evaluate_tool_policy is policies.evaluate_tool_policy
    assert facade.normalize_tool_policy is policies.normalize_tool_policy
    assert facade.resolve_tool_policy_for_agent is policies.resolve_tool_policy_for_agent
    assert facade.evaluate_delegation_policy is policies.evaluate_delegation_policy
    assert facade.evaluate_supervision_policy is policies.evaluate_supervision_policy
    assert facade.normalize_memory_policy is policies.normalize_memory_policy
    assert facade.compute_effective_tool_visibility is policies.compute_effective_tool_visibility
    assert facade.default_tool_policy is policies.default_tool_policy
    assert facade.build_agent_policy_options is policies.build_agent_policy_options


def test_facade_reexports_lifecycle_pack() -> None:
    # Serializer wrappers stay on the facade.
    assert getattr(facade.archive_agent_instance, "__wrapped__", None) is lifecycle.archive_agent_instance
    assert getattr(facade.purge_archived_agent_instance, "__wrapped__", None) is lifecycle.purge_archived_agent_instance
    assert getattr(facade.reset_agent_instance, "__wrapped__", None) is lifecycle.reset_agent_instance
    assert facade.ensure_agent_purge_allowed is lifecycle.ensure_agent_purge_allowed
    assert facade.ensure_agent_archive_allowed is lifecycle.ensure_agent_archive_allowed
    assert facade.agent_archive_protected is lifecycle.agent_archive_protected


def test_facade_reexports_projections_pack() -> None:
    assert facade.list_agents is projections.list_agents
    assert facade.get_agent is projections.get_agent
    assert facade._agent_to_api is projections._agent_to_api
    assert facade._agent_to_api_summary is projections._agent_to_api_summary
    assert facade.build_agent_runtime_context_block is projections.build_agent_runtime_context_block
    assert facade.agent_conversation_index_classification is projections.agent_conversation_index_classification
    assert facade.active_agent_runtime is projections.active_agent_runtime


def test_facade_reexports_mutations_pack() -> None:
    assert getattr(facade.create_agent_instance, "__wrapped__", None) is mutations.create_agent_instance
    assert getattr(facade.update_agent_instance, "__wrapped__", None) is mutations.update_agent_instance
    assert facade.replace_agent_llm_bindings_if_current is mutations.replace_agent_llm_bindings_if_current
    assert facade.store_agent_avatar_image is mutations.store_agent_avatar_image
    assert facade.update_agent_avatar is mutations.update_agent_avatar
    assert facade.list_agent_avatar_options is mutations.list_agent_avatar_options
    assert facade.resolve_agent_avatar_file is mutations.resolve_agent_avatar_file


def test_facade_reexports_repair_store_pack() -> None:
    assert facade.repair_agent_directory is repair_store.repair_agent_directory
    assert facade.load_state is repair_store.load_state
    assert facade.save_state is repair_store.save_state
    assert facade.default_state is repair_store.default_state
    assert facade._normalize_agent_record_for_storage is repair_store._normalize_agent_record_for_storage
    assert facade._guard_against_suspicious_registry_shrink is repair_store._guard_against_suspicious_registry_shrink


def test_facade_reexports_ops_residual_pack() -> None:
    assert facade.write_agent_inbox_message is ops_residual.write_agent_inbox_message
    assert facade.consume_agent_inbox_message is ops_residual.consume_agent_inbox_message
    assert facade.evaluate_agent_workspace_write is ops_residual.evaluate_agent_workspace_write
    assert getattr(facade.ensure_agent_for_session, "__wrapped__", None) is ops_residual.ensure_agent_for_session
    assert getattr(facade.reactivate_agent_instance, "__wrapped__", None) is ops_residual.reactivate_agent_instance
    assert facade.write_project_memory_update_proposal is ops_residual.write_project_memory_update_proposal
    assert callable(facade.agent_session_lifecycle_serialized)
    assert callable(facade.agent_session_lifecycle_transaction)
