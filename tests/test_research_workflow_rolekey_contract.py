"""Contract tests for Challenge Cup workflow role resolution.

The workflow stores semantic role names in ``primaryRoleKey`` while the team
catalog also carries the directory-facing ``roleKey``. These tests validate
the mapping between both layers and then exercise the real team binding path,
so a one-sided rename cannot silently leave a workflow node unbound.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from core.research.workflow.bindings import build_run_binding_snapshots
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.models import ActorKind, AgentBindingLayers, WorkflowDefinition
from core.web.services.team.team_constants import (
    CHALLENGE_CUP_RESEARCH_TEAM_ROLES,
    RESEARCH_TEAM_MEMBER_ROLE_KEYS,
)
from core.web.services.team_workflow.research_runtime.team_role_source import (
    resolve_team_role_bindings,
)


EXPECTED_AGENT_NODE_ROLE_KEYS = {
    "source_finding": "source_finder",
    "source_extraction": "source_extractor",
    "evidence_relations": "source_relation_mapper",
    "knowledge_ingestion": "source_ingestor",
    "hypothesis_design": "experiment_planner",
    "protocol_design": "experiment_planner",
    "protocol_review": "experiment_ledger",
    "result_evaluation": "experiment_ledger",
    "iteration_decision": "iteration_planner",
    "version_governance": "iteration_versioning",
}


def _definition_agent_role_keys(definition: WorkflowDefinition) -> dict[str, str]:
    return {
        node.nodeId: node.primaryRoleKey
        for node in definition.nodes
        if node.actorKind is ActorKind.AGENT
    }


def _assert_definition_agent_role_keys(definition: WorkflowDefinition) -> None:
    assert _definition_agent_role_keys(definition) == EXPECTED_AGENT_NODE_ROLE_KEYS


def test_team_role_key_mapping_matches_challenge_cup_catalog() -> None:
    """The organization-role map and challenge team catalog stay in lockstep."""

    roles_by_name = {
        str(item["role"]): item
        for item in CHALLENGE_CUP_RESEARCH_TEAM_ROLES
        if str(item.get("role") or "").strip()
    }
    mapping = {
        str(role): str(role_key)
        for role, role_key in RESEARCH_TEAM_MEMBER_ROLE_KEYS.items()
    }

    assert all(role.strip() and role_key.strip() for role, role_key in mapping.items())
    assert set(mapping) <= set(roles_by_name)
    assert len(mapping) == len(set(mapping.values()))
    catalog_role_keys = {
        str(item.get("roleKey") or "").strip()
        for item in CHALLENGE_CUP_RESEARCH_TEAM_ROLES
    }
    assert all(catalog_role_keys)
    assert catalog_role_keys == set(mapping.values())
    for role, role_key in mapping.items():
        assert str(roles_by_name[role]["roleKey"]) == role_key


def test_every_definition_agent_role_resolves_through_team_binding_path(monkeypatch) -> None:
    """Every agent node can resolve through the production team-role adapter."""

    definition = build_challenge_cup_workflow_definition()
    _assert_definition_agent_role_keys(definition)
    definition_agent_roles = set(_definition_agent_role_keys(definition).values())
    mapping_roles = set(RESEARCH_TEAM_MEMBER_ROLE_KEYS)
    assert definition_agent_roles <= mapping_roles

    sources = {
        "canvas_nodes": [],
        "members": [
            {"role": role, "agentId": f"agent-{role}"}
            for role in sorted(mapping_roles)
        ],
    }
    monkeypatch.setattr(
        "core.web.services.team_service.list_team_role_binding_sources",
        lambda _team_id: sources,
    )

    resolved = resolve_team_role_bindings("research-team")
    assert set(resolved) == mapping_roles

    snapshots = build_run_binding_snapshots(
        run_id="role-contract-run",
        workflow_version_id="2.1.0",
        layers=AgentBindingLayers(workflowDefaults=resolved),
        captured_at="2026-08-23T00:00:00Z",
    )
    by_node_id = {snapshot.nodeId: snapshot for snapshot in snapshots}

    for node in definition.nodes:
        if node.actorKind is not ActorKind.AGENT:
            continue
        snapshot = by_node_id[node.nodeId]
        assert snapshot.roleKey == node.primaryRoleKey
        assert snapshot.agentId == f"agent-{node.primaryRoleKey}"


def test_role_key_contract_rejects_a_legal_cross_node_rename() -> None:
    """A rename to another valid roleKey must still fail the node contract."""

    definition = build_challenge_cup_workflow_definition()
    mutated = replace(
        definition,
        nodes=tuple(
            replace(node, primaryRoleKey="source_extractor")
            if node.nodeId == "source_finding"
            else node
            for node in definition.nodes
        ),
    )

    with pytest.raises(AssertionError):
        _assert_definition_agent_role_keys(mutated)
