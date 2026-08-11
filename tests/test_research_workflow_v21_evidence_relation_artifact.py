"""Relation Agent output keeps gaps and explicit counter-evidence traceable."""

from __future__ import annotations

import pytest

from core.web.services.team_workflow.research_runtime.artifact_quality_gate import (
    ArtifactQualityError,
    validate_artifact_quality,
)
from core.web.services.team_workflow.research_runtime.evidence_relation_artifact import (
    build_evidence_relation_artifact,
)


def test_relation_result_maps_canonical_missing_links_and_counter_evidence() -> None:
    result = {
        "candidateRelations": [
            {
                "from": "candidate-a",
                "to": "theme-a",
                "type": "supports_background",
                "evidenceRefs": ["evidence-a"],
            }
        ],
        "missingLinks": [
            {
                "id": "gap-direct-baseline",
                "description": "No direct frozen-baseline comparison.",
                "blocksConclusion": True,
            }
        ],
        "counterEvidenceRefs": [
            {
                "evidenceRef": "evidence-negative-a",
                "disposition": "limits_claim",
                "claim": "The reported gain does not hold under the frozen baseline.",
            }
        ],
    }

    artifact = build_evidence_relation_artifact(result)

    assert artifact["evidenceGaps"] == result["missingLinks"]
    assert artifact["counterEvidenceRefs"] == result["counterEvidenceRefs"]
    assert artifact["candidateRelations"] == result["candidateRelations"]


def test_relation_result_does_not_invent_counter_evidence_from_supporting_edges() -> None:
    artifact = build_evidence_relation_artifact(
        {
            "candidateRelations": [
                {
                    "from": "candidate-a",
                    "to": "theme-a",
                    "type": "supports_background",
                    "evidenceRefs": ["evidence-a"],
                }
            ],
            "missingLinks": [{"id": "gap-a"}],
        }
    )

    assert artifact["evidenceGaps"] == [{"id": "gap-a"}]
    assert artifact["counterEvidenceRefs"] == []


def test_relation_quality_rejects_gap_and_counter_evidence_without_real_relation() -> None:
    artifact_id = "evidence_relation_graph:relation-empty"

    with pytest.raises(
        ArtifactQualityError,
        match="at least one evidence-backed relation",
    ):
        validate_artifact_quality(
            {"runId": "run-relation-empty"},
            node_id="evidence_relations",
            manifests=[{"artifactId": artifact_id}],
            payloads={
                artifact_id: {
                    "evidenceGaps": [{"id": "gap-a"}],
                    "counterEvidenceRefs": [
                        {
                            "evidenceRef": "record-negative#p2",
                            "claim": "A limitation was observed.",
                            "disposition": "limits_claim",
                        }
                    ],
                }
            },
        )


def test_relation_quality_rejects_relation_without_its_own_evidence_reference() -> None:
    artifact_id = "evidence_relation_graph:relation-unanchored"

    with pytest.raises(
        ArtifactQualityError,
        match="every evidence relation requires an evidence reference",
    ):
        validate_artifact_quality(
            {"runId": "run-relation-unanchored"},
            node_id="evidence_relations",
            manifests=[{"artifactId": artifact_id}],
            payloads={
                artifact_id: {
                    "candidateRelations": [
                        {
                            "from": "candidate-a",
                            "to": "theme-a",
                            "type": "supports_background",
                            "evidenceRefs": [],
                        }
                    ],
                    "evidenceGaps": [{"id": "gap-a"}],
                    "counterEvidenceRefs": [
                        {
                            "evidenceRef": "record-negative#p2",
                            "claim": "A limitation was observed.",
                            "disposition": "limits_claim",
                        }
                    ],
                }
            },
        )
