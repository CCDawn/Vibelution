"""Evidence graph command coverage plus Result Package availability projection.

Strict terminal Result Package construction and its system-adapter lifecycle
live in the canonical workflow suites. This file covers the remaining
read-model and command surfaces for the latest definitions.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.research.workflow.definition import (
    CHALLENGE_CUP_WORKFLOW_ID,
    build_challenge_cup_workflow_definition,
)
from core.research.workflow.definition_registry import definition_identity
from core.research.workflow.knowledge_sideflow_definition import (
    KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,
    build_knowledge_sideflow_workflow_definition,
)
from core.web.services.team_workflow.research_runtime.evidence_graph_projection import (
    evidence_graph_availability,
    project_evidence_graph,
)
from core.web.services.team_workflow.research_runtime.node_command_adapter import (
    NodeCommandUnavailable,
    apply_node_command,
    node_command_capabilities,
)
from core.web.services.team_workflow.research_runtime.result_package import (
    result_package_availability,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore


_MAIN_DEFINITION = build_challenge_cup_workflow_definition()
_MAIN_IDENTITY = definition_identity(_MAIN_DEFINITION)
_KNOWLEDGE_DEFINITION = build_knowledge_sideflow_workflow_definition()
_KNOWLEDGE_IDENTITY = definition_identity(_KNOWLEDGE_DEFINITION)


def _run_record(**extra) -> dict:
    record = {
        "runId": "run-1",
        "workflowId": CHALLENGE_CUP_WORKFLOW_ID,
        "workflowVersionId": _MAIN_IDENTITY.workflowVersionId,
        "structureHash": _MAIN_IDENTITY.structureHash,
        "teamId": "team-1",
        "projectId": "project-1",
        "status": "running",
        "runtimeCurrentNodeIds": ["result_package"],
        "nodeRuns": [],
        "langGraph": {"artifacts": {}},
        "iterationDecisions": [],
        "promotionProposals": [],
        "handoffs": [],
    }
    record.update(extra)
    return record


def _knowledge_run_record(**extra) -> dict:
    return _run_record(
        workflowId=KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,
        workflowVersionId=_KNOWLEDGE_IDENTITY.workflowVersionId,
        structureHash=_KNOWLEDGE_IDENTITY.structureHash,
        runtimeCurrentNodeIds=["evidence_relations"],
        **extra,
    )


def test_result_package_availability_reports_terminal_gate_first() -> None:
    ok, reason = result_package_availability(_run_record())

    assert not ok
    assert "succeeded terminal WorkflowRun" in reason


def test_result_package_command_stays_unavailable_without_ready_terminal_node() -> None:
    capabilities = node_command_capabilities(_run_record(), "result_package")

    build = next(item for item in capabilities if item["command"] == "build_package")
    view = next(item for item in capabilities if item["command"] == "view_artifacts")
    assert build["available"] is False
    assert "sole ready terminal node" in build["reason"]
    assert view["available"] is True


def _bound_graph_record(monkeypatch):
    from core.web.services.team_workflow.research_runtime import artifact_readback_registry as registry
    raw = {"nodes": [{"candidateId": "n1", "candidateType": "source"}, {"candidateId": "n2", "candidateType": "source"}], "edges": [{"sourceCandidateId": "n1", "targetCandidateId": "n2", "relation": "supports"}]}
    digest = registry.canonical_sha256(raw)
    ref = registry.build_canonical_ref(kind="evidence_relation_graph", team_id="team-1", authority_run_id="sc-1", content_hash=digest)
    monkeypatch.setattr(registry, "load_scoped_artifact_payload", lambda *a, **k: raw)
    return _knowledge_run_record(artifactSummary={"refs": [{"kind": "evidence_relation_graph", "canonicalRef": ref,
        "sha256": digest, "materialized": True, "verifiedAtMs": 10}]})


def test_evidence_graph_availability_requires_current_receipt(monkeypatch):
    ok, reason = evidence_graph_availability(_run_record())
    assert not ok and "证据关系数据" in reason
    assert evidence_graph_availability(_bound_graph_record(monkeypatch)) == (True, "")


def test_evidence_graph_projection_rejects_inline_history():
    with pytest.raises(NodeCommandUnavailable):
        project_evidence_graph(_run_record(langGraph={"artifacts": {"evidence_relation_graph": {"nodes": [{"id": "old"}]}}}))


def test_open_evidence_graph_command_returns_bound_projection(monkeypatch, tmp_path):
    result = apply_node_command(store=WorkflowRunStore(tmp_path / "runs"),
        checkpoint_path=str(tmp_path / "ckpt.sqlite"), record=_bound_graph_record(monkeypatch),
        node_id="evidence_relations", command="open_evidence_graph")
    assert result["command"] == "open_evidence_graph"
    assert result["graph"]["source"] == "canonical_artifact"
    assert result["graph"]["nodes"]
    assert result["graph"]["edges"]
