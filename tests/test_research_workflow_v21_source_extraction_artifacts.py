"""Source-extraction Agent results must become canonical evidence cards."""

from __future__ import annotations

from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.web.services.team_workflow.research_runtime.agent_task_artifact_builder import (
    build_agent_task_artifacts,
)
from core.web.services.team_workflow.research_runtime.artifact_quality_gate import (
    validate_artifact_quality,
)
from core.web.services.team_workflow.research_runtime.source_extraction_evidence_cards import (
    build_source_extraction_evidence_cards,
)


def test_nested_key_findings_become_traceable_evidence_cards() -> None:
    result = {
        "candidateExtractions": [
            {
                "candidateId": "candidate-a",
                "decision": "keep",
                "evidenceStatus": "missing_evidence_anchor",
                "relevance": "high",
                "keyFindings": [
                    {
                        "evidenceRef": "record-a",
                        "finding": "Dynamic thresholds reduce redundant updates.",
                        "sourceRef": "https://example.test/a",
                    },
                    {
                        "citationLocator": {"page": "12"},
                        "finding": "The effect remains under a frozen baseline.",
                    },
                ],
            }
        ]
    }

    cards = build_source_extraction_evidence_cards(result)

    assert cards == [
        {
            "sourceId": "candidate-a",
            "claim": "Dynamic thresholds reduce redundant updates.",
            "citationLocator": {
                "evidenceRef": "record-a",
                "sourceRef": "https://example.test/a",
            },
            "decision": "keep",
            "evidenceStatus": "missing_evidence_anchor",
            "relevance": "high",
        },
        {
            "sourceId": "candidate-a",
            "claim": "The effect remains under a frozen baseline.",
            "citationLocator": {"page": "12"},
            "decision": "keep",
            "evidenceStatus": "missing_evidence_anchor",
            "relevance": "high",
        },
    ]


def test_flat_extraction_contract_remains_canonical() -> None:
    result = {
        "recordExtractions": [
            {
                "recordId": "record-b",
                "conclusion": "Ablation B improves the primary metric.",
                "evidenceRef": "fixture://record-b#table-2",
                "confidence": 0.91,
            }
        ]
    }

    cards = build_source_extraction_evidence_cards(result)

    assert cards == [
        {
            "recordId": "record-b",
            "conclusion": "Ablation B improves the primary metric.",
            "evidenceRef": "fixture://record-b#table-2",
            "confidence": 0.91,
            "sourceId": "record-b",
            "claim": "Ablation B improves the primary metric.",
            "citationLocator": {
                "evidenceRef": "fixture://record-b#table-2"
            },
        }
    ]


def test_nested_agent_result_passes_the_source_extraction_quality_contract() -> None:
    definition = build_challenge_cup_workflow_definition()
    node_spec = next(
        node for node in definition.nodes if node.nodeId == "source_extraction"
    )
    record = {
        "runId": "run-extraction",
        "workflowVersionId": f"{definition.workflowId}@{definition.schemaVersion}",
        "inputSnapshot": {"environmentSnapshotRef": "fixture://environment"},
        "artifactManifests": [
            {"artifactId": "source_candidate_batch:input"}
        ],
    }
    task = {
        "taskId": "task-extraction",
        "sessionId": "session-extraction",
        "result": {
            "candidateExtractions": [
                {
                    "candidateId": "candidate-a",
                    "keyFindings": [
                        {
                            "evidenceRef": "record-a",
                            "finding": "Dynamic thresholds reduce redundant updates.",
                            "sourceRef": "https://example.test/a",
                        }
                    ],
                }
            ]
        },
    }
    manifests, payloads = build_agent_task_artifacts(
        record=record,
        node_spec=node_spec,
        node_run={
            "nodeRunId": "node-run-extraction",
            "attempt": 1,
            "inputSnapshotHash": "a" * 64,
            "agentId": "agent-extraction",
            "modelRef": "fixture-model",
        },
        task=task,
        created_at="2026-08-10T00:00:00Z",
    )

    quality, records = validate_artifact_quality(
        record,
        node_id="source_extraction",
        manifests=[item.to_dict() for item in manifests],
        payloads=payloads,
    )

    assert quality is not None
    assert quality["status"] == "passed"
    assert quality["details"] == {"evidenceCardCount": 1}
    assert records == {}
