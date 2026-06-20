# -*- coding: utf-8 -*-
"""Regression checks for the external memory workspace boundary."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture()
def isolated_data_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_home = tmp_path / "operator-data"
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))

    from core.infrastructure import developer_sandbox
    from core.infrastructure import workspace_manager

    monkeypatch.setattr(developer_sandbox, "resolve_workspace_home", lambda *args, **kwargs: data_home / "workspace")
    old_workspace = workspace_manager._workspace
    old_instance = workspace_manager.WorkspaceManager._instance
    workspace_manager._workspace = None
    workspace_manager.WorkspaceManager._instance = None
    try:
        yield data_home
    finally:
        workspace_manager._workspace = old_workspace
        workspace_manager.WorkspaceManager._instance = old_instance


def test_default_storage_paths_use_external_workspace(isolated_data_home: Path, monkeypatch: pytest.MonkeyPatch):
    external_workspace = isolated_data_home / "workspace"

    from core.code_context_graph import service as code_context_graph_service
    from core.evaluation import lineage
    from core.evaluation.chat_next_state_signals import PROJECT_ROOT, resolve_chat_next_state_signal_path
    from core.evaluation.self_evolution_candidate_pool import candidate_pool_paths
    from core.evaluation.self_evolution_experience_repository import experience_paths
    from core.evaluation.self_evolution_reflection import reflection_paths
    from core.evaluation.supervised_evolution import DEFAULT_BUNDLE_NAME, resolve_supervised_bundle_path
    from core.gym.generated_cases import append_generated_case, build_generated_case
    from core.infrastructure.workspace_manager import get_workspace
    from core.research.knowledge_base import ResearchKnowledgeBase
    from core.research.repository import ResearchRepository
    from core.web.services import chat_room_service

    monkeypatch.setattr(
        lineage,
        "get_config",
        lambda: SimpleNamespace(evolution=SimpleNamespace(proposals_dir="workspace/evolution/proposals")),
    )

    assert get_workspace().root == external_workspace
    assert chat_room_service._store().state_path == external_workspace / "chat_rooms" / "chat_rooms.json"
    assert ResearchRepository().root == external_workspace / "research" / "theme_discovery"
    assert ResearchKnowledgeBase().path == external_workspace / "research" / "knowledge_base.json"
    assert code_context_graph_service.index_path() == external_workspace / "code_context_graph" / "index.json"
    assert candidate_pool_paths().root == external_workspace / "self_evolution" / "candidates"
    assert experience_paths().root == external_workspace / "self_evolution" / "experience"
    assert reflection_paths().root == external_workspace / "self_evolution" / "reflection"
    assert resolve_chat_next_state_signal_path(PROJECT_ROOT) == (
        external_workspace / "evaluation" / "chat_next_state_signals.jsonl"
    )
    assert lineage.resolve_lineage_index_path() == external_workspace / "evolution" / "proposals" / "lineage_index.json"
    assert resolve_supervised_bundle_path(DEFAULT_BUNDLE_NAME) == (
        external_workspace / "evaluation" / "bundles" / f"{DEFAULT_BUNDLE_NAME}.json"
    )

    generated_path = append_generated_case(
        build_generated_case(
            case_id="case-default",
            objective="Collect bounded evidence",
            prompt="Record the source before promoting knowledge.",
            source_trace_id="trace-1",
            source_episode_id="episode-1",
            source_harness_gap="validation",
            generation_reason="memory storage regression",
            creator_version="test",
        )
    )
    assert generated_path == external_workspace / "evaluation" / "datasets" / "generated_cases.jsonl"


def test_explicit_project_roots_keep_test_storage_isolated(tmp_path: Path):
    project_root = tmp_path / "repo"

    from core.evaluation.chat_next_state_signals import resolve_chat_next_state_signal_path
    from core.evaluation.dataset_registry import ensure_dataset_registry
    from core.evaluation.self_evolution_candidate_pool import candidate_pool_paths
    from core.evaluation.self_evolution_experience_repository import experience_paths
    from core.evaluation.self_evolution_reflection import reflection_paths
    from core.evaluation.supervised_evolution import DEFAULT_BUNDLE_NAME, resolve_supervised_bundle_path
    from core.gym.generated_cases import append_generated_case, build_generated_case

    workspace = project_root / "workspace"
    assert candidate_pool_paths(project_root=project_root).root == workspace / "self_evolution" / "candidates"
    assert experience_paths(project_root=project_root).root == workspace / "self_evolution" / "experience"
    assert reflection_paths(project_root=project_root).root == workspace / "self_evolution" / "reflection"
    assert resolve_chat_next_state_signal_path(project_root) == workspace / "evaluation" / "chat_next_state_signals.jsonl"
    assert ensure_dataset_registry(project_root=project_root) == workspace / "evaluation" / "datasets" / "registry.json"
    assert resolve_supervised_bundle_path(DEFAULT_BUNDLE_NAME, project_root=project_root) == (
        workspace / "evaluation" / "bundles" / f"{DEFAULT_BUNDLE_NAME}.json"
    )

    generated_path = append_generated_case(
        build_generated_case(
            case_id="case-explicit",
            objective="Keep explicit test roots isolated",
            prompt="Write to the provided project workspace only.",
            source_trace_id="trace-2",
            source_episode_id="episode-2",
            source_harness_gap="validation",
            generation_reason="explicit root regression",
            creator_version="test",
        ),
        project_root=project_root,
    )
    assert generated_path == workspace / "evaluation" / "datasets" / "generated_cases.jsonl"


def test_legacy_project_workspace_storage_patterns_do_not_return():
    checks = {
        "core/evaluation/chat_next_state_signals.py": ['DEFAULT_SIGNAL_PATH = Path("workspace/'],
        "core/evaluation/self_evolution_experience_repository.py": ['Path("workspace/self_evolution'],
        "core/evaluation/self_evolution_reflection.py": ['Path("workspace/self_evolution'],
        "core/gym/generated_cases.py": ['Path("workspace/evaluation/datasets/generated_cases.jsonl")'],
        "core/gym/promotion.py": ['project_root / "workspace" / "gym"'],
        "core/web/services/research_loop_service.py": ['_project_root() / "workspace"'],
        "core/web/services/team_workflow_orchestration_service.py": [
            '_project_root() / "workspace" / "data_processing"'
        ],
        "core/prompt_manager/codebase_map_builder.py": ['project_root / "workspace" / "prompts"'],
        "core/code_context_graph/service.py": ['Path("workspace") / "code_context_graph"'],
        "core/ui/cli_ui.py": ['Path("workspace") / "ui_runtime_state.json"'],
        "tools/shell_tools.py": ["PROJECT_ROOT / workspace_name"],
    }

    repo_root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for relative_path, forbidden_patterns in checks.items():
        text = (repo_root / relative_path).read_text(encoding="utf-8")
        for pattern in forbidden_patterns:
            if pattern in text:
                offenders.append(f"{relative_path}: {pattern}")

    assert offenders == []
