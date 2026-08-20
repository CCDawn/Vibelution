"""Clarity P5/B6: facade should re-export pack modules rather than grow new mega-logic."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FACADE = ROOT / "core" / "web" / "services" / "team_workflow_orchestration_service.py"
PACK = ROOT / "core" / "web" / "services" / "team_workflow"
ROUTES = ROOT / "core" / "web" / "routes" / "team_workflows"


def test_team_workflow_routes_are_package_split() -> None:
    assert (ROUTES / "__init__.py").is_file()
    for name in (
        "orchestration.py",
        "research_projects.py",
        "source_collection.py",
        "stage_rounds.py",
        "experiment.py",
        "knowledge.py",
        "research_ops.py",
    ):
        assert (ROUTES / name).is_file(), name


def test_facade_imports_from_team_workflow_pack() -> None:
    source = FACADE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    pack_imports = []
    for node in tree.body:
        if isinstance(node, (ast.ImportFrom,)) and node.module and "team_workflow" in node.module:
            pack_imports.append(node.module)
    assert pack_imports, "facade must import from team_workflow pack modules"
    # Prefer pack modules over only local mega-defs
    assert any(
        m.endswith(suffix)
        for m in pack_imports
        for suffix in (
            "orchestration_core",
            "research_projects",
            "source_collection",
            "experiment",
            "knowledge",
            "research_loop",
        )
    ) or any("team_workflow" in m for m in pack_imports)


def test_facade_public_surface_includes_key_exports() -> None:
    # Import surface stays available for routes
    from core.web.services import team_workflow_orchestration_service as facade

    for name in (
        "ensure_team_workflow_orchestration",
        "start_source_collection_run",
        "start_source_collection_stage_session_task",
        "create_experiment_plan",
        "run_experiment_smoke_run",
    ):
        assert hasattr(facade, name), name


def test_facade_reexports_challenge_cup_dev_controls() -> None:
    """D14A: the facade re-exports the DEV control behavior so routes import
    through the stable facade instead of reaching into the pack module."""
    from core.web.services import team_workflow_orchestration_service as facade

    for name in (
        "get_challenge_cup_dev_control_snapshot",
        "run_challenge_cup_dev_readiness",
        "run_challenge_cup_dev_batch",
        "get_challenge_cup_catalog_overview",
        "get_challenge_cup_token_usage",
        "ChallengeCupDevControlsError",
    ):
        assert hasattr(facade, name), name

    facade_src = FACADE.read_text(encoding="utf-8")
    assert "challenge_cup_dev_controls" in facade_src

    route_src = (ROUTES / "challenge_cup_dev_controls.py").read_text(encoding="utf-8")
    assert "team_workflow_orchestration_service" in route_src
    assert "team_workflow.challenge_cup_dev_controls" not in route_src


def test_source_collection_stages_package_split() -> None:
    """Clarity B6: stages re-exports stage_session + stage_writeback."""
    sc = PACK / "source_collection"
    assert (sc / "stages.py").is_file()
    assert (sc / "stage_session.py").is_file()
    assert (sc / "stage_writeback.py").is_file()
    stages_src = (sc / "stages.py").read_text(encoding="utf-8")
    assert "stage_session" in stages_src
    assert "stage_writeback" in stages_src
    from core.web.services.team_workflow.source_collection import stages as stages_mod

    for name in (
        "start_source_collection_stage_session_task",
        "writeback_source_collection_stage_session_task",
        "seed_source_collection_agent_session_context",
        "assert_source_collection_stage_advance_ready",
    ):
        assert hasattr(stages_mod, name), name


def test_experiment_api_package_owns_implementations() -> None:
    """Clarity B6: experiment ops live under experiment_api/; experiment.py re-exports."""
    api = PACK / "experiment_api"
    assert (api / "__init__.py").is_file()
    for name in ("plan.py", "hypothesis.py", "smoke.py", "full_run.py", "knowledge.py"):
        assert (api / name).is_file(), name
    experiment_mod = (PACK / "experiment.py").read_text(encoding="utf-8")
    assert "experiment_api.plan" in experiment_mod
    assert "experiment_api.smoke" in experiment_mod
    # Public import path stays stable
    from core.web.services.team_workflow import experiment as exp

    for name in (
        "create_experiment_plan",
        "run_experiment_smoke_run",
        "prepare_experiment_full_run",
        "request_experiment_result_knowledge_ingestion",
        "materialize_experiment_proxy_hypothesis",
    ):
        assert hasattr(exp, name), name
