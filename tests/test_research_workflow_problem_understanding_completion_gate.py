from __future__ import annotations

import pytest

from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.web.services.team_workflow.research_runtime import workflow_artifact_store
from core.web.services.team_workflow.research_runtime.agent_task_artifact_builder import (
    build_agent_task_artifacts,
)
from core.web.services.team_workflow.research_runtime.artifact_quality_gate import (
    ArtifactQualityError,
    validate_artifact_quality,
)
from core.web.services.team_workflow.research_runtime.problem_understanding_artifact_writer import (
    write_problem_understanding_artifact,
)


def _problem_understanding() -> dict[str, object]:
    return {
        "scope": "只讨论可证伪的记忆提取机制",
        "subquestions": ["哪些机制可以被对照实验区分？"],
        "assumptions": ["输入数据能够覆盖对照条件"],
        "known_unknowns": ["跨任务泛化仍未知"],
        "human_gate": {
            "required": True,
            "decision": "pending",
            "rationale": "等待研究负责人确认问题边界。",
        },
    }


def _record(node_run_id: str = "nr-problem-a1") -> dict[str, object]:
    return {
        "teamId": "team-a",
        "runId": "run-a",
        "workflowVersionId": "challenge-cup-research@2.1.0",
        "inputSnapshot": {},
        "nodeRuns": [
            {
                "nodeId": "problem_understanding",
                "nodeRunId": node_run_id,
                "attempt": 1,
                "inputSnapshotHash": "a" * 64,
                "status": "running",
            }
        ],
    }


def _task() -> dict[str, object]:
    return {
        "taskId": "task-problem-a1",
        "summary": "forged summary must not become the canonical artifact",
        "score": 0.99,
        "result": {
            "artifactPayloads": {
                "problem_understanding": {
                    **_problem_understanding(),
                    "scope": "forged task-result scope",
                }
            }
        },
    }


def _node_spec():
    return next(
        item
        for item in build_challenge_cup_workflow_definition().nodes
        if item.nodeId == "problem_understanding"
    )


def _write_canonical(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    *,
    node_run_id: str,
) -> None:
    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    write_problem_understanding_artifact(
        team_id="team-a",
        workflow_run_id="run-a",
        source_collection_run_id="sc-a",
        node_run_id=node_run_id,
        problem_understanding=_problem_understanding(),
    )


def test_builder_uses_current_node_run_canonical_payload_not_task_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    record = _record()
    node_run = record["nodeRuns"][0]
    _write_canonical(monkeypatch, tmp_path, node_run_id=node_run["nodeRunId"])

    manifests, payloads = build_agent_task_artifacts(
        record=record,
        node_spec=_node_spec(),
        node_run=node_run,
        task=_task(),
        created_at="2026-08-24T00:00:00Z",
    )

    manifest = manifests[0]
    assert manifest.artifactId.startswith("problem_understanding:")
    assert payloads[manifest.artifactId]["scope"] == _problem_understanding()["scope"]


def test_builder_fails_closed_when_current_node_run_has_no_canonical_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    record = _record()
    node_run = record["nodeRuns"][0]

    with pytest.raises(ValueError, match="canonical artifact is missing"):
        build_agent_task_artifacts(
            record=record,
            node_spec=_node_spec(),
            node_run=node_run,
            task=_task(),
            created_at="2026-08-24T00:00:00Z",
        )


def test_quality_gate_reloads_canonical_payload_and_rejects_task_payload_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    record = _record()
    node_run = record["nodeRuns"][0]
    _write_canonical(monkeypatch, tmp_path, node_run_id=node_run["nodeRunId"])
    manifests, payloads = build_agent_task_artifacts(
        record=record,
        node_spec=_node_spec(),
        node_run=node_run,
        task=_task(),
        created_at="2026-08-24T00:00:00Z",
    )
    manifest = manifests[0].to_dict()

    quality, records = validate_artifact_quality(
        record,
        node_id="problem_understanding",
        manifests=[manifest],
        payloads={manifest["artifactId"]: _task()["result"]["artifactPayloads"]["problem_understanding"]},
    )

    assert quality is not None
    assert quality["details"]["humanGateDecision"] == "pending"
    assert records == {}
    assert payloads[manifest["artifactId"]]["scope"] == _problem_understanding()["scope"]


def test_quality_gate_rejects_artifact_from_another_node_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    record = _record(node_run_id="nr-problem-current")
    _write_canonical(monkeypatch, tmp_path, node_run_id="nr-problem-other")
    manifest = {
        "artifactId": "problem_understanding:forged",
        "producerNodeRunId": "nr-problem-current",
        "producerAttempt": 1,
        "inputSnapshotHash": "a" * 64,
        "contentHash": "forged",
    }

    with pytest.raises(ArtifactQualityError, match="canonical artifact is missing"):
        validate_artifact_quality(
            record,
            node_id="problem_understanding",
            manifests=[manifest],
            payloads={manifest["artifactId"]: _problem_understanding()},
        )
