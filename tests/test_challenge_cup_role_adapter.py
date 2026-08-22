from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.research.workflow.contracts.research_team_role_contract import (
    CURRENT_RESEARCH_TEAM_ROLE_CONTRACT,
)
from core.web.services.team_workflow import knowledge_kernel
from core.web.services.team_workflow.research_project_agent_sessions import (
    research_project_agent_role_label,
)
from core.web.services.team_workflow.research_runtime.task_adapter_registry import (
    resolve_agent_task_adapter,
)

LEGACY_SOURCE_ROLES = [
    "source_finder",
    "source_extractor",
    "source_relation_mapper",
    "source_ingestor",
]


class _WorkflowError(ValueError):
    pass


@pytest.fixture
def source_assignment_service(monkeypatch):
    service = SimpleNamespace(
        TeamWorkflowOrchestrationError=_WorkflowError,
        _trim_text=lambda value, max_length=160: str(value or "").strip()[:max_length],
        _normalize_source_collection_agent_role=lambda value: str(value or "").strip(),
    )
    monkeypatch.setattr(knowledge_kernel, "_service", lambda: service)
    return service


def _canonical_team() -> dict:
    bindings = {
        "challenge_cup_search": "agent-search",
        "challenge_cup_extractor": "agent-extractor",
        "challenge_cup_knowledge_manager": "agent-knowledge",
        "challenge_cup_execution_steward": "agent-execution",
        "challenge_cup_experiment_revision": "agent-revision",
        "challenge_cup_evaluator": "agent-evaluator",
    }
    members = [
        {"agentId": agent_id, "role": role_key}
        for role_key, agent_id in bindings.items()
    ]
    return {
        "members": members,
        "canvas": {"nodes": list(reversed(members))},
        "activeBinding": {
            "status": "active",
            "productRoleAgentIds": bindings,
        },
        "legacyBindings": [
            {
                "agentId": "agent-old-search",
                "sourceRole": "source_finder",
                "ownerType": "product_agent",
                "ownerId": "challenge_cup_search",
                "status": "legacy",
                "activeBinding": False,
            }
        ],
    }


def test_contract_resolves_product_aliases_and_keeps_system_capabilities_separate():
    contract = CURRENT_RESEARCH_TEAM_ROLE_CONTRACT

    assert contract.resolve_role_owner("source_finder") == (
        "product_agent",
        "challenge_cup_search",
    )
    assert contract.resolve_role_owner("source_ingestor") == (
        "product_agent",
        "challenge_cup_knowledge_manager",
    )
    assert contract.resolve_role_owner("formal_runner") == (
        "system_capability",
        "formal_runner",
    )
    assert contract.resolve_role_owner("iteration_versioning") == (
        "system_capability",
        "versioning_service",
    )
    assert contract.resolve_product_role_id("formal_runner") is None
    assert contract.resolve_product_role_id("not-a-role") is None


def test_source_assignment_projects_canonical_agents_onto_legacy_stage_keys(
    source_assignment_service,
):
    del source_assignment_service

    resolved = knowledge_kernel._source_collection_team_agent_ids(
        _canonical_team(),
        LEGACY_SOURCE_ROLES,
        {},
    )

    assert resolved == {
        "source_finder": "agent-search",
        "source_extractor": "agent-extractor",
        "source_relation_mapper": "agent-knowledge",
        "source_ingestor": "agent-knowledge",
    }
    assert "agent-old-search" not in resolved.values()


def test_source_assignment_preserves_legacy_team_stage_bindings(
    source_assignment_service,
):
    del source_assignment_service
    legacy_bindings = {
        "source_finder": "agent-source-finder",
        "source_extractor": "agent-source-extractor",
        "source_relation_mapper": "agent-knowledge-manager",
        "source_ingestor": "agent-knowledge-manager",
    }
    team = {
        "canvas": {
            "nodes": [
                {"role": role, "agentId": agent_id}
                for role, agent_id in legacy_bindings.items()
            ]
        }
    }

    resolved = knowledge_kernel._source_collection_team_agent_ids(
        team,
        LEGACY_SOURCE_ROLES,
        {
            "agentIds": legacy_bindings
        },
    )

    assert resolved == legacy_bindings


def test_source_assignment_rejects_legacy_explicit_binding_over_canonical_team_role(
    source_assignment_service,
):
    del source_assignment_service
    team = {
        "canvas": {
            "nodes": [
                {
                    "role": "challenge_cup_search",
                    "agentId": "agent-canonical-search",
                },
                {"role": "source_finder", "agentId": "agent-legacy-search"},
            ]
        }
    }

    with pytest.raises(_WorkflowError, match="canonical Team role binding"):
        knowledge_kernel._source_collection_team_agent_ids(
            team,
            ["source_finder"],
            {"agentIds": {"source_finder": "agent-legacy-search"}},
        )


def test_source_assignment_rejects_unrequested_alias_conflicting_with_canonical_explicit(
    source_assignment_service,
):
    del source_assignment_service
    team = {
        "canvas": {
            "nodes": [
                {
                    "role": "challenge_cup_knowledge_manager",
                    "agentId": "agent-canonical-knowledge",
                },
                {
                    "role": "source_relation_mapper",
                    "agentId": "agent-legacy-knowledge",
                },
                {
                    "role": "source_ingestor",
                    "agentId": "agent-canonical-knowledge",
                },
            ]
        }
    }

    with pytest.raises(_WorkflowError, match="conflicting explicit bindings"):
        knowledge_kernel._source_collection_team_agent_ids(
            team,
            ["source_ingestor"],
            {
                "agentIds": {
                    "challenge_cup_knowledge_manager": "agent-canonical-knowledge",
                    "source_relation_mapper": "agent-legacy-knowledge",
                }
            },
        )


def test_source_assignment_rejects_cross_role_agent_reuse_in_legacy_team(
    source_assignment_service,
):
    del source_assignment_service
    team = {
        "canvas": {
            "nodes": [
                {"role": "source_finder", "agentId": "agent-shared"},
                {"role": "source_extractor", "agentId": "agent-shared"},
            ]
        }
    }

    with pytest.raises(_WorkflowError, match="more than one product role"):
        knowledge_kernel._source_collection_team_agent_ids(
            team,
            ["source_finder", "source_extractor"],
            {},
        )


def test_source_assignment_fails_closed_on_empty_active_binding(
    source_assignment_service,
):
    del source_assignment_service
    team = _canonical_team()
    team["activeBinding"]["productRoleAgentIds"] = {}

    with pytest.raises(_WorkflowError, match="has no canonical product role bindings"):
        knowledge_kernel._source_collection_team_agent_ids(
            team,
            LEGACY_SOURCE_ROLES,
            {},
        )


@pytest.mark.parametrize(
    ("agent_ids", "message"),
    [
        ({"source_finder": "agent-old-search"}, "conflicts with the active canonical binding"),
        ({"unknown_role": "agent-search"}, "unknown role"),
        ({"source_finder": "agent-missing"}, "conflicts with the active canonical binding"),
    ],
)
def test_source_assignment_rejects_untrusted_explicit_agent_ids(
    source_assignment_service,
    agent_ids,
    message,
):
    del source_assignment_service

    with pytest.raises(_WorkflowError, match=message):
        knowledge_kernel._source_collection_team_agent_ids(
            _canonical_team(),
            LEGACY_SOURCE_ROLES,
            {"agentIds": agent_ids},
        )


def test_source_assignment_rejects_duplicate_cross_role_active_bindings(
    source_assignment_service,
):
    del source_assignment_service
    team = _canonical_team()
    team["activeBinding"]["productRoleAgentIds"]["challenge_cup_extractor"] = (
        "agent-search"
    )

    with pytest.raises(_WorkflowError, match="more than one product role"):
        knowledge_kernel._source_collection_team_agent_ids(
            team,
            LEGACY_SOURCE_ROLES,
            {},
        )


def test_task_adapter_exposes_canonical_owner_without_rewriting_legacy_stage_key():
    source = resolve_agent_task_adapter("source_finding")
    versioning = resolve_agent_task_adapter("version_governance")

    assert source is not None
    assert source.role_key == "source_finder"
    assert source.owner_type == "product_agent"
    assert source.owner_id == "challenge_cup_search"
    assert source.canonical_role_key == "challenge_cup_search"
    assert versioning is not None
    assert versioning.owner_type == "system_capability"
    assert versioning.owner_id == "versioning_service"
    assert versioning.canonical_role_key == ""


def test_session_labels_accept_canonical_roles_without_changing_legacy_labels():
    assert research_project_agent_role_label("challenge_cup_search") == "搜索 Agent"
    assert research_project_agent_role_label("source_finder") == "资料寻找"
