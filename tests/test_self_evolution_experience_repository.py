#!/usr/bin/env python3
"""Self-evolution experience repository tests."""

import json
from pathlib import Path

from core.evaluation.self_evolution_experience_repository import (
    EXPERIENCE_JSONL,
    append_experience_record,
    experience_paths,
    list_experience_records,
    record_terminal_self_evolution_experience,
)


def test_append_experience_record_materializes_bounded_candidate_source(tmp_path: Path):
    result = append_experience_record(
        {
            "kind": "failure_pattern",
            "source_run_id": "web-self-exp",
            "summary": "Run failed after a bounded tool attempt.",
            "evidence": {"status": "failed", "tool_name": "pytest"},
            "dedupe_key": "self_terminal:web-self-exp",
            "downstream_use": ["self_questioning"],
        },
        project_root=tmp_path,
    )

    path = tmp_path / EXPERIENCE_JSONL
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    assert result.created is True
    assert result.record["experience_id"].startswith("exp_")
    assert result.record["created_at"].endswith("Z")
    assert result.record["kind"] == "failure_pattern"
    assert result.record["source_run_id"] == "web-self-exp"
    assert result.record["supervised_required"] is True
    assert result.record["downstream_use"] == ["self_questioning"]
    assert rows == [result.record]


def test_append_experience_record_dedupes_by_key(tmp_path: Path):
    first = append_experience_record(
        {
            "kind": "successful_strategy",
            "source_run_id": "web-self-repeat",
            "summary": "A bounded run finished cleanly.",
            "dedupe_key": "self_terminal:web-self-repeat",
        },
        project_root=tmp_path,
    )
    second = append_experience_record(
        {
            "kind": "successful_strategy",
            "source_run_id": "web-self-repeat",
            "summary": "Duplicate terminal write should not append.",
            "dedupe_key": "self_terminal:web-self-repeat",
        },
        project_root=tmp_path,
    )

    records = list_experience_records(project_root=tmp_path)
    index = json.loads((tmp_path / "workspace" / "self_evolution" / "experience" / "index.json").read_text(encoding="utf-8"))

    assert first.created is True
    assert second.created is False
    assert second.record == first.record
    assert len(records) == 1
    assert index["record_count"] == 1
    assert index["latest_experience_id"] == first.record["experience_id"]


def test_experience_paths_resolve_under_self_evolution_workspace(tmp_path: Path):
    paths = experience_paths(project_root=tmp_path)

    assert paths.root == tmp_path / "workspace" / "self_evolution" / "experience"
    assert paths.jsonl == tmp_path / "workspace" / "self_evolution" / "experience" / "experience.jsonl"
    assert paths.index == tmp_path / "workspace" / "self_evolution" / "experience" / "index.json"


def test_record_terminal_self_evolution_experience_keeps_output_as_candidate(tmp_path: Path):
    result = record_terminal_self_evolution_experience(
        {
            "runId": "web-self-terminal",
            "status": "done",
            "phase": "completed",
            "summary": "Finished a bounded run.",
            "lastToolName": "apply_patch",
            "toolCallCount": 3,
            "turnCount": 1,
            "runtimeStatus": "idle",
            "artifacts": {
                "runDir": "logs/runtime_scenes/package/agent/self_evolution_runs/web-self-terminal.jsonl",
                "manifestPath": "workspace/self_evolution/rollback/web-self-terminal/manifest.json",
            },
        },
        rollback={"status": "available", "entryCount": 2},
        project_root=tmp_path,
    )

    record = result.record

    assert record["kind"] == "successful_strategy"
    assert record["dedupe_key"] == "self_terminal:web-self-terminal"
    assert record["supervised_required"] is True
    assert "supervised_candidate" in record["downstream_use"]
    assert record["evidence"]["rollback_entry_count"] == 2
    assert record["runtime_scene_refs"] == [
        "logs/runtime_scenes/package/agent/self_evolution_runs/web-self-terminal.jsonl"
    ]
    assert record["audit_refs"] == [
        "workspace/self_evolution/rollback/web-self-terminal/manifest.json"
    ]
