"""Canonical relation readback must retain and authenticate its evidence."""

from copy import deepcopy

import pytest

from core.web.services.team_workflow.research_runtime import (
    artifact_readback_registry as registry,
)
from core.web.services.team_workflow.research_runtime.human_gate_artifacts import (
    canonical_sha256,
)
from core.web.services.team_workflow.source_collection import (
    candidates,
    writeback_materialize as materialize,
)
from core.web.services.team_workflow.source_collection_context import (
    compact_source_collection_stage_task_context,
)


@pytest.fixture
def graph_store(monkeypatch):
    graph = {
        "nodes": [{"candidateId": "a"}, {"candidateId": "b"}],
        "edges": [
            {
                "sourceCandidateId": "a",
                "targetCandidateId": "b",
                "relation": "supports",
                "evidenceRefs": ["claim-1"],
            }
        ],
        "evidenceGaps": [{"description": "No independent replication"}],
        "counterEvidenceRefs": [{"evidenceRef": "claim-2", "reason": "Null result"}],
    }
    row = {
        "candidateId": "graph-1",
        "teamId": "team",
        "sourceCollectionRunId": "sc",
        "workflowRunId": "wf",
        "metadata": {"graph": graph},
    }
    monkeypatch.setattr(
        candidates, "list_candidate_store", lambda *a, **k: {"candidates": [row]}
    )
    monkeypatch.setattr(
        registry,
        "_load_scoped_evidence",
        lambda **k: [{"claimEvidenceId": "claim-1"}, {"claimEvidenceId": "claim-2"}],
    )
    return graph


def load_graph():
    return registry.load_scoped_artifact_payload(
        "evidence_relation_graph",
        team_id="team",
        authority_run_id="sc",
        workflow_run_id="wf",
    )


@pytest.mark.parametrize("field", ["relation", "counter", "mixed", "empty"])
def test_forged_evidence_rejected(graph_store, field):
    if field == "counter":
        graph_store["counterEvidenceRefs"][0]["evidenceRef"] = "fabricated-ref"
    else:
        graph_store["edges"][0]["evidenceRefs"] = {
            "relation": ["fabricated-ref"],
            "mixed": ["claim-1", "fabricated-ref"],
            "empty": [],
        }[field]
    assert load_graph() is None


def test_canonical_graph_preserves_fields_and_hash(graph_store):
    payload = load_graph()
    assert payload["evidenceGaps"] == graph_store["evidenceGaps"]
    assert payload["counterEvidenceRefs"] == graph_store["counterEvidenceRefs"]
    ref = registry.build_canonical_ref(
        kind="evidence_relation_graph",
        team_id="team",
        authority_run_id="sc",
        content_hash=canonical_sha256(payload),
    )
    assert registry.read_domain_artifact(ref).content_hash == canonical_sha256(payload)
    graph_store["evidenceGaps"] = []
    assert registry.read_domain_artifact(ref) is None


def test_graph_materialization_preserves_evidence_fields(graph_store):
    raw = deepcopy(graph_store)
    agent_graph = materialize._source_collection_stage_writeback_agent_graph_payload(
        raw
    )
    merged = materialize._merge_source_collection_stage_writeback_agent_graph(
        {"nodes": raw["nodes"]}, agent_graph
    )
    assert merged["evidenceGaps"] == raw["evidenceGaps"]
    assert merged["counterEvidenceRefs"] == raw["counterEvidenceRefs"]


@pytest.mark.parametrize("mode", ["compact", "minimal", "evidence"])
def test_context_compaction_preserves_canonical_whitelist(mode):
    result = compact_source_collection_stage_task_context(
        {"contextMode": mode, "allowedEvidenceRefs": ["claim-1", "claim-2"]}
    )
    assert result["allowedEvidenceRefs"] == ["claim-1", "claim-2"]


def test_other_run_evidence_cannot_authorize_graph(graph_store, monkeypatch):
    from core.research.evidence import ClaimEvidenceStore

    monkeypatch.undo()
    monkeypatch.setattr(
        candidates,
        "list_candidate_store",
        lambda *a, **k: {
            "candidates": [
                {
                    "candidateId": "graph-1",
                    "sourceCollectionRunId": "sc",
                    "workflowRunId": "wf",
                    "metadata": {"graph": graph_store},
                }
            ]
        },
    )
    monkeypatch.setattr(
        ClaimEvidenceStore,
        "list",
        lambda *a, **k: [
            {
                "claimEvidenceId": "claim-1",
                "sourceCollectionRunId": "other-sc",
                "workflowRunId": "other-wf",
            }
        ],
    )
    assert load_graph() is None


def test_quality_gate_checks_canonical_membership(graph_store, monkeypatch):
    from core.web.services.team_workflow.research_runtime.artifact_quality_gate import (
        ArtifactQualityError,
        validate_artifact_quality,
    )

    artifact_id = "evidence_relation_graph:test"
    record = {"runId": "wf", "teamId": "team", "sourceCollectionRunId": "sc"}
    graph_store["edges"][0]["evidenceRefs"] = ["forged"]
    with pytest.raises(ArtifactQualityError, match="canonical claimEvidenceId"):
        validate_artifact_quality(
            record,
            node_id="evidence_relations",
            manifests=[{"artifactId": artifact_id}],
            payloads={artifact_id: graph_store},
        )
