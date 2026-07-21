"""Focused tests for agent_directory structure packs (profiles/policies/lifecycle)."""

from __future__ import annotations

from core.web.services import agent_directory_service as facade
from core.web.services.agent_directory import lifecycle, policies, profiles


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
