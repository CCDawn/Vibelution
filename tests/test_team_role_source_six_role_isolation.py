from __future__ import annotations

from core.research.workflow.bindings import build_run_binding_snapshots
from core.research.workflow.models import AgentBindingLayers
from core.web.services.team_workflow.research_runtime import team_role_source


def _set_team_sources(monkeypatch, *, canvas_nodes=(), members=()) -> None:
    monkeypatch.setattr(
        "core.web.services.team_service.list_team_role_binding_sources",
        lambda _team_id: {
            "team_exists": True,
            "canvas_nodes": list(canvas_nodes),
            "members": list(members),
        },
    )


def _binding(node_id: str, role_key: str, agent_id: str) -> dict[str, str]:
    return {
        "nodeId": node_id,
        "roleKey": role_key,
        "agentId": agent_id,
    }


def _snapshot(*bindings: dict[str, str]) -> dict[str, list[dict[str, str]]]:
    return {"agentBindingSnapshot": list(bindings)}


def test_canonical_product_agents_project_aliases_and_drop_non_product_sources(
    monkeypatch,
) -> None:
    canonical = {
        "challenge_cup_search": "agent-search",
        "challenge_cup_extractor": "agent-extractor",
        "challenge_cup_knowledge_manager": "agent-knowledge",
        "challenge_cup_execution_steward": "agent-execution",
        "challenge_cup_experiment_revision": "agent-revision",
        "challenge_cup_evaluator": "agent-evaluator",
    }
    _set_team_sources(
        monkeypatch,
        canvas_nodes=(
            {"role": "source_finder", "agentId": "agent-legacy-search"},
            {"role": "formal_runner", "agentId": "agent-formal-runner"},
            {"role": "unknown_role", "agentId": "agent-unknown"},
        ),
        members=(
            {"role": role_key, "agentId": agent_id}
            for role_key, agent_id in canonical.items()
        ),
    )

    resolved = team_role_source.resolve_team_role_bindings("research-team")

    assert resolved["challenge_cup_search"] == "agent-search"
    assert resolved["source_finder"] == "agent-search"
    assert resolved["source_relation_mapper"] == "agent-knowledge"
    assert resolved["source_ingestor"] == "agent-knowledge"
    assert resolved["experiment_planner"] == "agent-revision"
    assert resolved["iteration_planner"] == "agent-revision"
    assert resolved["experiment_ledger"] == "agent-evaluator"
    assert resolved["execution_steward"] == "agent-execution"
    assert "formal_runner" not in resolved
    assert "unknown_role" not in resolved
    assert "agent-legacy-search" not in resolved.values()


def test_member_exact_role_ambiguity_is_unbound(
    monkeypatch,
) -> None:
    _set_team_sources(
        monkeypatch,
        members=(
            {"role": "source_finder", "agentId": "agent-search-a"},
            {"role": "source_finder", "agentId": "agent-search-b"},
        ),
    )

    assert "source_finder" not in team_role_source.resolve_team_role_bindings(
        "research-team"
    )


def test_duplicate_records_for_one_agent_are_not_ambiguous(monkeypatch) -> None:
    duplicate = {"role": "source_finder", "agentId": "agent-search"}
    _set_team_sources(monkeypatch, members=(duplicate, dict(duplicate)))

    assert (
        team_role_source.resolve_team_role_bindings("research-team")["source_finder"]
        == "agent-search"
    )


def test_canonical_ambiguity_blocks_alias_projection(monkeypatch) -> None:
    _set_team_sources(
        monkeypatch,
        members=(
            {"role": "challenge_cup_search", "agentId": "agent-search-a"},
            {"role": "challenge_cup_search", "agentId": "agent-search-b"},
            {"role": "source_finder", "agentId": "agent-legacy"},
        ),
    )

    resolved = team_role_source.resolve_team_role_bindings("research-team")
    assert "challenge_cup_search" not in resolved
    assert "source_finder" not in resolved


def test_legacy_exact_roles_remain_independent_without_canonical_binding(
    monkeypatch,
) -> None:
    _set_team_sources(
        monkeypatch,
        members=(
            {"role": "experiment_planner", "agentId": "agent-plan"},
            {"role": "iteration_planner", "agentId": "agent-iterate"},
        ),
    )

    resolved = team_role_source.resolve_team_role_bindings("research-team")
    assert resolved["experiment_planner"] == "agent-plan"
    assert resolved["iteration_planner"] == "agent-iterate"
    assert "challenge_cup_experiment_revision" not in resolved


def test_persisted_layers_drop_unknown_and_system_owned_bindings() -> None:
    layers = team_role_source.effective_binding_layers(
        "",
        AgentBindingLayers(
            workflowDefaults={
                "source_finder": "agent-search-default",
                "formal_runner": "agent-formal-default",
                "unknown_role": "agent-unknown-default",
            },
            stageOverrides={
                "execution_iteration": {
                    "experiment_planner": "agent-revision-stage",
                    "iteration_versioning": "agent-versioning-stage",
                    "unknown_role": "agent-unknown-stage",
                }
            },
            nodeOverrides={
                "hypothesis_design": "agent-revision-node",
                "version_governance": "agent-versioning-node",
                "controlled_run": "agent-formal-node",
                "protocol_freeze": "agent-human-node",
                "missing_node": "agent-missing-node",
            },
        ),
    )

    assert layers.workflowDefaults == {"source_finder": "agent-search-default"}
    assert layers.stageOverrides == {
        "execution_iteration": {"experiment_planner": "agent-revision-stage"}
    }
    assert layers.nodeOverrides == {"hypothesis_design": "agent-revision-node"}

    snapshots = build_run_binding_snapshots(
        run_id="run-six-role-isolation",
        workflow_version_id="workflow-v2",
        layers=layers,
        captured_at="2026-08-23T00:00:00Z",
    )
    by_node = {item.nodeId: item.agentId for item in snapshots}
    assert by_node["hypothesis_design"] == "agent-revision-node"
    assert by_node["version_governance"] == ""


def test_persisted_stage_overrides_drop_unknown_workflow_stage_ids() -> None:
    layers = team_role_source.effective_binding_layers(
        "",
        AgentBindingLayers(
            stageOverrides={
                "knowledge_collection": {
                    "source_finder": "agent-search-stage",
                },
                "unknown_stage": {
                    "source_finder": "agent-unknown-stage",
                },
            }
        ),
    )

    assert layers.stageOverrides == {
        "knowledge_collection": {"source_finder": "agent-search-stage"}
    }


def test_team_members_override_retired_persisted_workflow_defaults(monkeypatch) -> None:
    _set_team_sources(
        monkeypatch,
        members=({"role": "challenge_cup_search", "agentId": "agent-team-search"},),
    )

    layers = team_role_source.effective_binding_layers(
        "research-team",
        AgentBindingLayers(workflowDefaults={"source_finder": "agent-config-search"}),
    )

    assert layers.workflowDefaults["challenge_cup_search"] == "agent-team-search"
    assert layers.workflowDefaults["source_finder"] == "agent-team-search"


def test_team_lookup_failure_does_not_revive_persisted_workflow_defaults(
    monkeypatch,
) -> None:
    def unavailable(_team_id):
        raise RuntimeError("team source unavailable")

    monkeypatch.setattr(
        "core.web.services.team_service.list_team_role_binding_sources",
        unavailable,
    )

    layers = team_role_source.effective_binding_layers(
        "research-team",
        AgentBindingLayers(
            workflowDefaults={"source_finder": "stale-config-search"},
            stageOverrides={
                "knowledge_collection": {"source_finder": "stage-search"}
            },
            nodeOverrides={"hypothesis_design": "node-revision"},
        ),
    )

    assert layers.workflowDefaults == {}
    assert layers.stageOverrides == {
        "knowledge_collection": {"source_finder": "stage-search"}
    }
    assert layers.nodeOverrides == {"hypothesis_design": "node-revision"}


def test_missing_team_does_not_revive_persisted_workflow_defaults(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.web.services.team_service.list_team_role_binding_sources",
        lambda _team_id: {
            "team_exists": False,
            "canvas_nodes": [],
            "members": [],
        },
    )

    layers = team_role_source.effective_binding_layers(
        "missing-team",
        AgentBindingLayers(workflowDefaults={"source_finder": "stale-config-search"}),
    )

    assert layers.workflowDefaults == {}


def test_live_healing_uses_contract_aliases_without_team_constants(
    monkeypatch,
) -> None:
    from core.web.services.team import team_constants

    class _ForbiddenSecondRoleSource(dict):
        def get(self, *_args, **_kwargs):
            raise AssertionError("healing must not read the team constants role map")

    monkeypatch.setattr(
        team_constants,
        "RESEARCH_TEAM_MEMBER_ROLE_KEYS",
        _ForbiddenSecondRoleSource(),
    )
    monkeypatch.setattr(
        team_role_source,
        "resolve_team_role_bindings",
        lambda _team_id: {
            "challenge_cup_experiment_planner": "agent-revision",
        },
    )

    healed = team_role_source.heal_agent_binding_for_node(
        "research-team",
        "hypothesis_design",
    )

    assert healed is not None
    assert healed["agentId"] == "agent-revision"

    monkeypatch.setattr(
        team_role_source,
        "resolve_team_role_bindings",
        lambda _team_id: {
            "challenge_cup_experiment_planner": "agent-revision-a",
            "challenge_cup_iteration_planner": "agent-revision-b",
        },
    )
    assert (
        team_role_source.heal_agent_binding_for_node(
            "research-team",
            "hypothesis_design",
        )
        is None
    )


def test_live_healing_rejects_system_owned_agent_shaped_node(monkeypatch) -> None:
    monkeypatch.setattr(
        team_role_source,
        "resolve_team_role_bindings",
        lambda _team_id: {"iteration_versioning": "agent-versioning"},
    )

    assert (
        team_role_source.heal_agent_binding_for_node(
            "research-team", "version_governance"
        )
        is None
    )


def test_sibling_healing_requires_real_product_node_and_matching_owner() -> None:
    rejected = (
        _snapshot(_binding("", "experiment_planner", "agent-missing-node")),
        _snapshot(_binding("missing_node", "experiment_planner", "agent-fake-node")),
        _snapshot(_binding("protocol_freeze", "experiment_planner", "agent-human")),
        _snapshot(_binding("controlled_run", "experiment_planner", "agent-system")),
        _snapshot(_binding("source_finding", "experiment_planner", "agent-mismatch")),
        _snapshot(_binding("protocol_design", "unknown_role", "agent-unknown")),
    )

    for snapshot in rejected:
        assert (
            team_role_source.heal_agent_binding_from_sibling_freeze(
                snapshot, "hypothesis_design"
            )
            is None
        )

    assert (
        team_role_source.heal_agent_binding_from_sibling_freeze(
            _snapshot(
                _binding(
                    "version_governance",
                    "iteration_versioning",
                    "agent-versioning",
                )
            ),
            "version_governance",
        )
        is None
    )


def test_sibling_healing_prefers_one_exact_legacy_candidate() -> None:
    snapshot = _snapshot(
        _binding("iteration_decision", "iteration_planner", "agent-alias"),
        _binding("protocol_design", "experiment_planner", "agent-exact"),
    )
    before = {
        "agentBindingSnapshot": [
            dict(item) for item in snapshot["agentBindingSnapshot"]
        ]
    }

    healed = team_role_source.heal_agent_binding_from_sibling_freeze(
        snapshot,
        "hypothesis_design",
    )

    assert healed is not None
    assert healed["agentId"] == "agent-exact"
    assert healed["roleKey"] == "experiment_planner"
    assert snapshot == before


def test_sibling_healing_accepts_only_one_owner_candidate_without_exact() -> None:
    healed = team_role_source.heal_agent_binding_from_sibling_freeze(
        _snapshot(
            _binding("iteration_decision", "iteration_planner", "agent-revision")
        ),
        "hypothesis_design",
    )

    assert healed is not None
    assert healed["agentId"] == "agent-revision"


def test_sibling_healing_rejects_zero_or_multiple_selected_candidates() -> None:
    assert (
        team_role_source.heal_agent_binding_from_sibling_freeze(
            _snapshot(), "hypothesis_design"
        )
        is None
    )
    assert (
        team_role_source.heal_agent_binding_from_sibling_freeze(
            _snapshot(
                _binding("protocol_design", "experiment_planner", "agent-exact-a"),
                _binding("protocol_design", "experiment_planner", "agent-exact-b"),
            ),
            "hypothesis_design",
        )
        is None
    )
    assert (
        team_role_source.heal_agent_binding_from_sibling_freeze(
            _snapshot(
                _binding(
                    "protocol_design",
                    "challenge_cup_experiment_revision",
                    "agent-owner-a",
                ),
                _binding("iteration_decision", "iteration_planner", "agent-owner-b"),
            ),
            "hypothesis_design",
        )
        is None
    )
