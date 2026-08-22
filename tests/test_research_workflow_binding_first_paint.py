"""First-paint bindings must not hydrate full Team canvas or Agent APIs."""

from __future__ import annotations

from pathlib import Path

from core.research.workflow.bindings import build_run_binding_snapshots
from core.research.workflow.models import AgentBindingLayers
from core.web.services.team_workflow.research_runtime.team_role_source import (
    effective_binding_layers,
    resolve_team_role_bindings,
)

ROLE_SOURCE = Path("core/web/services/team_workflow/research_runtime/team_role_source.py")
RUNTIME_SERVICE = Path("core/web/services/team_workflow/research_runtime/service.py")
QUERY_SERVICE = Path("core/web/services/team_workflow/research_runtime/query_service.py")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_role_source_uses_light_binding_records() -> None:
    source = _read(ROLE_SOURCE)
    assert "list_team_role_binding_sources" in source
    assert "get_team_canvas" not in source
    assert "from core.web.services.team_service import get_team, get_team_canvas" not in source


def test_display_name_lookup_skips_full_agent_api() -> None:
    runtime = _read(RUNTIME_SERVICE)
    query = _read(QUERY_SERVICE)
    assert "lookup_agent_display_name_map" in runtime
    assert "def _agent_display_name(" in runtime
    assert "from core.web.services.agent_directory_service import get_agent" not in runtime
    assert "lookup_agent_display_name_map" in query
    assert "from core.web.services.agent_directory_service import get_agent" not in query


def test_resolve_team_role_bindings_prefers_canvas_without_full_hydration(monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise AssertionError("full team/canvas hydration must not run")

    monkeypatch.setattr("core.web.services.team_service.get_team", boom)
    monkeypatch.setattr("core.web.services.team_service.get_team_canvas", boom)
    monkeypatch.setattr(
        "core.web.services.team_service.list_team_role_binding_sources",
        lambda _team_id: {
            "canvas_nodes": [{"role": "source_finder", "agentId": "agent-canvas"}],
            "members": [
                {"role": "source_finder", "agentId": "agent-member"},
                {"role": "source_extractor", "agentId": "agent-extract"},
            ],
        },
    )

    assert resolve_team_role_bindings("research-team") == {
        "source_finder": "agent-canvas",
        "source_extractor": "agent-extract",
    }


def test_resolve_team_role_bindings_empty_on_lookup_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.web.services.team_service.list_team_role_binding_sources",
        lambda _team_id: (_ for _ in ()).throw(RuntimeError("unavailable")),
    )
    assert resolve_team_role_bindings("research-team") == {}
    assert resolve_team_role_bindings("") == {}


def test_canonical_six_role_team_projects_legacy_workflow_bindings(monkeypatch) -> None:
    canonical = {
        "challenge_cup_search": "agent-search",
        "challenge_cup_extractor": "agent-extractor",
        "challenge_cup_knowledge_manager": "agent-knowledge",
        "challenge_cup_execution_steward": "agent-execution",
        "challenge_cup_experiment_revision": "agent-revision",
        "challenge_cup_evaluator": "agent-evaluator",
    }
    monkeypatch.setattr(
        "core.web.services.team_service.list_team_role_binding_sources",
        lambda _team_id: {
            "canvas_nodes": [
                {"role": "source_finder", "agentId": "agent-old-search"},
                {"role": "iteration_versioning", "agentId": "agent-old-versioning"},
            ],
            "members": [
                {"role": role_key, "agentId": agent_id}
                for role_key, agent_id in canonical.items()
            ],
        },
    )

    role_bindings = resolve_team_role_bindings("research-team")

    assert role_bindings["source_finder"] == "agent-search"
    assert role_bindings["source_extractor"] == "agent-extractor"
    assert role_bindings["source_relation_mapper"] == "agent-knowledge"
    assert role_bindings["source_ingestor"] == "agent-knowledge"
    assert role_bindings["experiment_planner"] == "agent-revision"
    assert role_bindings["iteration_planner"] == "agent-revision"
    assert role_bindings["experiment_ledger"] == "agent-evaluator"
    assert role_bindings["execution_steward"] == "agent-execution"
    assert "iteration_versioning" not in role_bindings

    layers = effective_binding_layers("research-team", AgentBindingLayers())
    snapshots = build_run_binding_snapshots(
        run_id="run-canonical-six",
        workflow_version_id="workflow-v2",
        layers=layers,
        captured_at="2026-08-23T00:00:00Z",
    )
    agent_by_node = {item.nodeId: item.agentId for item in snapshots}
    assert agent_by_node == {
        "source_finding": "agent-search",
        "source_extraction": "agent-extractor",
        "evidence_relations": "agent-knowledge",
        "knowledge_ingestion": "agent-knowledge",
        "hypothesis_design": "agent-revision",
        "protocol_design": "agent-revision",
        "protocol_review": "agent-evaluator",
        "result_evaluation": "agent-evaluator",
        "iteration_decision": "agent-revision",
        "version_governance": "",
    }
