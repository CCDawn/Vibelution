"""Source-extraction Agent results must become canonical evidence cards."""

from __future__ import annotations

import pytest

from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.definition_registry import register_or_resolve
from core.web.services.team_workflow.research_runtime.agent_task_artifact_builder import (
    build_agent_task_artifacts,
)
from core.web.services.team_workflow.research_runtime.artifact_quality_gate import (
    validate_artifact_quality,
)
from core.web.services.team_workflow.research_runtime.source_extraction_evidence_cards import (
    build_source_extraction_evidence_cards,
)


def _source_fields(**overrides: object) -> dict[str, object]:
    return {
        "title": "Dynamic threshold study",
        "source_type": "peer_reviewed_paper",
        "source_url": "https://example.test/a",
        "retrieved_at": "2026-08-10T00:00:00Z",
        "fact": "Dynamic thresholds reduce redundant updates.",
        "relation": "supports",
        "verification_status": "full_text_checked",
        **overrides,
    }


def _pinned_record(definition) -> dict[str, object]:
    """Run record pinned to the resolved definition identity.

    Production runs bind ``workflowId``/``workflowVersionId``/``structureHash``
    at run creation via ``register_or_resolve``; hand-built records must pin
    the same way or the fail-closed definition resolver refuses to compile the
    graph (the legacy ``workflowId@schemaVersion`` spelling is not a version
    id the registry knows).
    """
    identity = register_or_resolve(definition)
    return {
        "runId": "run-extraction",
        "workflowId": identity.workflowId,
        "workflowVersionId": identity.workflowVersionId,
        "structureHash": identity.structureHash,
        "inputSnapshot": {"environmentSnapshotRef": "fixture://environment"},
        "artifactManifests": [
            {"artifactId": "source_candidate_batch:input"}
        ],
    }


def test_nested_key_findings_become_traceable_evidence_cards() -> None:
    result = {
        "candidateExtractions": [
            {
                "candidateId": "candidate-a",
                "decision": "keep",
                "evidenceStatus": "missing_evidence_anchor",
                "relevance": "high",
                **_source_fields(),
                "keyFindings": [
                    {
                        "evidenceRef": "record-a",
                        "fact": "Dynamic thresholds reduce redundant updates.",
                        "sourceRef": "https://example.test/a",
                    },
                    {
                        "citationLocator": {"page": "12"},
                        "fact": "The effect remains under a frozen baseline.",
                        "relation": "boundary",
                    },
                ],
            }
        ]
    }

    cards = build_source_extraction_evidence_cards(result)

    assert cards == [
        {
            "sourceId": "candidate-a",
            "candidateId": "candidate-a",
            "title": "Dynamic threshold study",
            "source_type": "peer_reviewed_paper",
            "source_url": "https://example.test/a",
            "retrieved_at": "2026-08-10T00:00:00Z",
            "fact": "Dynamic thresholds reduce redundant updates.",
            "relation": "supports",
            "verification_status": "full_text_checked",
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
            "candidateId": "candidate-a",
            "title": "Dynamic threshold study",
            "source_type": "peer_reviewed_paper",
            "source_url": "https://example.test/a",
            "retrieved_at": "2026-08-10T00:00:00Z",
            "fact": "The effect remains under a frozen baseline.",
            "relation": "boundary",
            "verification_status": "full_text_checked",
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
                **_source_fields(
                    title="Ablation B study",
                    source_url="https://example.test/b",
                    fact="Ablation B improves the primary metric.",
                ),
                "evidenceRef": "fixture://record-b#table-2",
                "confidence": 0.91,
            }
        ]
    }

    cards = build_source_extraction_evidence_cards(result)

    assert cards == [
        {
            "sourceId": "record-b",
            "recordId": "record-b",
            "title": "Ablation B study",
            "source_type": "peer_reviewed_paper",
            "source_url": "https://example.test/b",
            "retrieved_at": "2026-08-10T00:00:00Z",
            "fact": "Ablation B improves the primary metric.",
            "relation": "supports",
            "verification_status": "full_text_checked",
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
    record = _pinned_record(definition)
    task = {
        "taskId": "task-extraction",
        "sessionId": "session-extraction",
        "result": {
                "candidateExtractions": [
                    {
                        "candidateId": "candidate-a",
                        **_source_fields(),
                        "keyFindings": [
                            {
                                "evidenceRef": "record-a",
                                "fact": "Dynamic thresholds reduce redundant updates.",
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


def test_real_agent_writeback_claim_anchor_passes_the_quality_contract() -> None:
    definition = build_challenge_cup_workflow_definition()
    node_spec = next(
        node for node in definition.nodes if node.nodeId == "source_extraction"
    )
    record = _pinned_record(definition)
    task = {
        "taskId": "task-extraction",
        "sessionId": "session-extraction",
        "result": {
                "candidateExtractions": [
                    {
                        "candidateId": "candidate-a",
                        **_source_fields(),
                        "valueSummary": "Controlled thresholding reduces redundant updates.",
                        "sourceRefs": ["https://example.test/a"],
                        "claims": [
                            {
                                "fact": "Controlled thresholding reduces redundant updates.",
                                "title": "Controlled threshold study",
                                "source_type": "peer_reviewed_paper",
                                "source_url": "https://example.test/a",
                                "retrieved_at": "2026-08-10T00:00:00Z",
                                "relation": "supports",
                                "verification_status": "metadata_checked",
                                "sourceRef": "https://example.test/a",
                                "evidenceRef": "record-anchor-a",
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

    cards = payloads[next(
        item.artifactId
        for item in manifests
        if item.artifactId.startswith("evidence_card_batch:")
    )]["evidenceCards"]
    assert cards[0]["citationLocator"] == {
        "evidenceRef": "record-anchor-a",
        "sourceRef": "https://example.test/a",
    }
    assert quality is not None
    assert quality["status"] == "passed"
    assert records == {}


def test_artifact_builder_backfills_retrieved_at_at_the_read_point() -> None:
    """A persisted task predating the writeback backfill must still build cards.

    The writeback boundary and the claim materializer read point both run the
    single-authoritative ``retrieved_at`` backfill; the artifact builder read
    point fed the raw persisted result straight into the fail-closed card
    contract and raised on the missing timestamp.  It must normalize through
    the same backfill — on a detached copy, without mutating the caller's
    canonical task object.
    """
    from core.web.services.team_workflow.source_collection.extraction_retrieved_at_backfill import (
        is_timezone_aware_rfc3339_timestamp,
    )

    definition = build_challenge_cup_workflow_definition()
    node_spec = next(
        node for node in definition.nodes if node.nodeId == "source_extraction"
    )
    record = _pinned_record(definition)
    legacy_fields = {
        key: value for key, value in _source_fields().items() if key != "retrieved_at"
    }
    task = {
        "taskId": "task-extraction-legacy",
        "sessionId": "session-extraction",
        "stageId": "extraction",
        "result": {
            "candidateExtractions": [
                {
                    "candidateId": "candidate-legacy",
                    "decision": "keep",
                    "evidenceStatus": "verified_abstract",
                    **legacy_fields,
                    "evidenceRefs": [
                        {
                            "id": "record-anchor-legacy",
                            "quote": "Dynamic thresholds reduce redundant updates.",
                            "type": "abstract",
                        }
                    ],
                    "claims": [
                        {
                            "fact": "Dynamic thresholds reduce redundant updates.",
                            "quote": "Dynamic thresholds reduce redundant updates.",
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

    cards = payloads[next(
        item.artifactId
        for item in manifests
        if item.artifactId.startswith("evidence_card_batch:")
    )]["evidenceCards"]
    assert cards
    assert all(
        is_timezone_aware_rfc3339_timestamp(card["retrieved_at"]) for card in cards
    )
    # Read-point purity: the caller's canonical task object is untouched.
    entry = task["result"]["candidateExtractions"][0]
    assert "retrieved_at" not in entry
    assert "retrieved_at" not in entry["claims"][0]


def test_formal_cards_fail_closed_without_explicit_facts_or_source_type() -> None:
    with pytest.raises(ValueError, match=r"missing explicit (source_type|fact)"):
        build_source_extraction_evidence_cards(
            {
                "candidateExtractions": [
                    {
                        "candidateId": "candidate-a",
                        "title": "A source",
                        "source_url": "https://example.test/a",
                        "retrieved_at": "2026-08-10T00:00:00Z",
                        "summary": "A summary must not become a fact.",
                        "sourceKind": "paper",
                        "keyFindings": [
                            {
                                "finding": "Legacy summary",
                                "evidenceRef": "record-a",
                            }
                        ],
                    }
                ]
            }
        )


def test_formal_cards_reject_url_as_source_identity_and_legacy_mode_is_explicit() -> None:
    with pytest.raises(ValueError, match="sourceId must equal"):
        build_source_extraction_evidence_cards(
            {
                "candidateExtractions": [
                    {
                        **_source_fields(),
                        "candidateId": "candidate-a",
                        "sourceId": "https://example.test/a",
                        "evidenceRef": "record-a",
                    }
                ]
            }
        )

    legacy = build_source_extraction_evidence_cards(
        {
            "candidateExtractions": [
                {
                    "candidateId": "candidate-a",
                    "keyFindings": [
                        {
                            "finding": "Legacy projection",
                            "sourceRef": "https://example.test/a",
                        }
                    ],
                }
            ]
        },
        mode="legacy",
    )
    assert legacy[0]["claim"] == "Legacy projection"
