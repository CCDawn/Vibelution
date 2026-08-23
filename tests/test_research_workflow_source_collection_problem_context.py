"""Static contract for source-finding canonical problem context."""

from __future__ import annotations

import ast
from pathlib import Path


_SOURCE_PATH = (
    Path(__file__).parents[1]
    / "core"
    / "web"
    / "services"
    / "team_workflow"
    / "source_collection"
    / "stage_session.py"
)


def _function_source(name: str) -> str:
    tree = ast.parse(_SOURCE_PATH.read_text(encoding="utf-8"))
    node = next(
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == name
    )
    return ast.get_source_segment(_SOURCE_PATH.read_text(encoding="utf-8"), node) or ""


def test_finding_context_reads_only_source_run_workflow_scope_and_canonical_artifact(
) -> None:
    source = _function_source("_source_collection_problem_understanding_context")

    assert 'run_scope.get("workflowRunId")' in source
    assert "list_workflow_artifacts" in source
    assert "load_scoped_artifact_payload" in source
    assert "validate_problem_understanding" in source
    assert "build_canonical_ref" in source
    assert 'task.get("result")' not in source
    assert 'task.get("summary")' not in source
    assert 'task.get("score")' not in source
    assert 'task.get("receipt")' not in source
    assert 'run_metadata.get("workflowRunId")' not in source


def test_finding_session_and_task_receive_the_verified_context() -> None:
    context_source = _function_source("_source_collection_problem_understanding_context")
    seed_source = _function_source("seed_source_collection_agent_session_context")
    start_source = _function_source("start_source_collection_stage_session_task")

    assert "canonicalRef" in context_source
    assert "payload" in context_source
    for source in (seed_source, start_source):
        assert 'if stage_id == "finding"' in source
        assert "problemUnderstandingContext" in source
        assert "_source_collection_problem_understanding_context" in source
        assert "_source_collection_problem_understanding_message" in source
    assert '"workflowRunId"' in start_source
    assert '"sourceCollectionRunId"' in context_source
