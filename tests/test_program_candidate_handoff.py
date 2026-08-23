"""Focused contract tests for the result-package -> Challenge Program bridge."""

from __future__ import annotations

from copy import deepcopy

import pytest

from core.web.services.team_workflow import challenge_question_runs
from core.web.services.team_workflow.research_runtime import (
    program_candidate_handoff,
)
from tests.test_challenge_question_runs import _citation_checks, _isolate_store, _output


def _package(*, output: dict, package_hash: str = "a" * 64) -> dict:
    return {
        "teamId": "research-team",
        "workflowRunId": "workflow-sci-096",
        "sourceCollectionRunId": "workflow-sci-096",
        "package": {
            "runId": "workflow-sci-096",
            "questionId": "SCI-096",
            "contentHash": package_hash,
        },
        "challengeQuestionOutput": output,
        "citationChecks": _citation_checks(output),
    }


def test_missing_v2_authority_returns_needs_context_without_registering(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(
        program_candidate_handoff,
        "load_scoped_artifact_payload",
        lambda *args, **kwargs: {
            "teamId": "research-team",
            "workflowRunId": "workflow-sci-096",
            "sourceCollectionRunId": "workflow-sci-096",
            "payload": {
                "package": {
                    "runId": "workflow-sci-096",
                    "questionId": "SCI-096",
                    "contentHash": "a" * 64,
                }
            },
        },
    )
    monkeypatch.setattr(
        challenge_question_runs,
        "register_challenge_question_output",
        lambda *args, **kwargs: calls.append(kwargs) or {},
    )

    result = program_candidate_handoff.handoff_result_package_to_challenge_program(
        team_id="research-team",
        workflow_run_id="workflow-sci-096",
    )

    assert result["status"] == program_candidate_handoff.NEEDS_CONTEXT
    assert "canonical_challenge_question_output.v2" in result["missingAuthorities"]
    assert "package.challengeQuestionOutput" in result["missingFields"]
    assert calls == []


def test_complete_v2_authority_registers_review_required_and_replays_idempotently(
    tmp_path, monkeypatch
):
    _isolate_store(tmp_path, monkeypatch)
    output = _output()
    output["run"]["run_id"] = "workflow-sci-096"
    artifact = _package(output=output)
    monkeypatch.setattr(
        program_candidate_handoff,
        "load_scoped_artifact_payload",
        lambda *args, **kwargs: {
            "teamId": "research-team",
            "workflowRunId": "workflow-sci-096",
            "sourceCollectionRunId": "workflow-sci-096",
            "payload": artifact,
        },
    )

    first = program_candidate_handoff.handoff_result_package_to_challenge_program(
        team_id="research-team",
        workflow_run_id="workflow-sci-096",
    )
    replay = program_candidate_handoff.handoff_result_package_to_challenge_program(
        team_id="research-team",
        workflow_run_id="workflow-sci-096",
    )

    assert first["status"] == "registered"
    assert first["reviewStatus"] == "review_required"
    assert replay["status"] == "idempotent"
    assert replay["sourceResultPackageHash"] == "a" * 64
    records = challenge_question_runs._load_store("research-team")["records"]
    assert len(records) == 1
    assert records[0]["sourceResultPackageHash"] == "a" * 64

    changed = deepcopy(artifact)
    changed["package"]["contentHash"] = "b" * 64
    monkeypatch.setattr(
        program_candidate_handoff,
        "load_scoped_artifact_payload",
        lambda *args, **kwargs: {
            "teamId": "research-team",
            "workflowRunId": "workflow-sci-096",
            "sourceCollectionRunId": "workflow-sci-096",
            "payload": changed,
        },
    )
    with pytest.raises(ValueError, match="source result package binding"):
        program_candidate_handoff.handoff_result_package_to_challenge_program(
            team_id="research-team",
            workflow_run_id="workflow-sci-096",
        )
