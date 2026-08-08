"""T-M1: build_package + open_evidence_graph node-command wiring.

Covers result-package assembly/idempotency/availability and the evidence-graph
projection (primary artifact dict, loop-records fallback, honest unavailable).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.services.team_workflow.research_runtime.durable_index import (
    DurableWorkflowIndex,
)
from core.web.services.team_workflow.research_runtime.evidence_graph_projection import (
    _project_from_loop_records,
    evidence_graph_availability,
    project_evidence_graph,
)
from core.web.services.team_workflow.research_runtime.node_command_adapter import (
    NodeCommandUnavailable,
    node_command_capabilities,
)
from core.web.services.team_workflow.research_runtime.result_package import (
    build_result_package,
    result_package_availability,
)
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowRuntimeService,
    reset_research_workflow_runtime_service_for_tests,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore


def _svc(tmp_path: Path) -> ResearchWorkflowRuntimeService:
    store = WorkflowRunStore(tmp_path / "runs")
    index = DurableWorkflowIndex(tmp_path / "runs" / "_index")
    ckpt = str(tmp_path / "ckpt.sqlite")
    return reset_research_workflow_runtime_service_for_tests(
        run_store=store,
        checkpoint_path=ckpt,
        durable_index=index,
    )


def _run_record(**extra) -> dict:
    record = {
        "runId": "run-1",
        "workflowId": CHALLENGE_CUP_WORKFLOW_ID,
        "teamId": "team-1",
        "projectId": "project-1",
        "status": "running",
        "langGraph": {"artifacts": {}},
        "iterationDecisions": [],
        "promotionProposals": [],
        "handoffs": [],
    }
    record.update(extra)
    return record


# --- result package ---


def test_result_package_availability_gates_on_facts() -> None:
    ok, reason = result_package_availability(_run_record())
    assert not ok
    assert "尚无迭代决策" in reason
    ok, _ = result_package_availability(_run_record(officialCandidateRef="candidate:1"))
    assert ok
    ok, _ = result_package_availability(_run_record(iterationDecisions=[{"decisionId": "dec-1"}]))
    assert ok


def test_build_result_package_assembles_run_facts() -> None:
    record = _run_record(
        status="succeeded",
        completionKind="stopped",
        terminalReason="enough_evidence",
        officialCandidateRef="candidate:2",
        iterationDecisions=[
            {
                "decisionId": "dec-1",
                "decisionKind": "rerun_same_protocol",
                "iterationAttempt": 1,
                "decidedBy": "planner",
                "decidedAt": "2026-01-01T00:00:00Z",
                "reason": "retry",
            }
        ],
        promotionProposals=[
            {
                "proposalId": "pp-1",
                "operation": "promote",
                "targetCandidateRef": "candidate:2",
                "status": "accepted",
                "reason": "best",
                "createdAt": "2026-01-01T00:00:00Z",
            }
        ],
        handoffs=[{"handoffId": "h1", "fromNodeId": "iteration_decision", "toNodeId": "controlled_run", "status": "accepted", "edgeId": "e_decision_rerun"}],
        langGraph={
            "artifacts": {
                "frozen_protocol": "hash:fp:v1",
                "research_result_package": "hash:rrp:key1",
                "run_artifacts:attempt:1": "hash:run:a1",
                "run_artifacts:attempt:2": "hash:run:a2",
            }
        },
    )
    package = build_result_package(record)
    assert package["packageId"].startswith("rrp:run-1:")
    assert package["packageRef"] == "hash:rrp:key1"
    assert package["overview"]["officialCandidateRef"] == "candidate:2"
    assert package["overview"]["completionKind"] == "stopped"
    assert package["overview"]["frozenProtocolRef"] == "hash:fp:v1"
    assert len(package["iterationDecisions"]) == 1
    assert len(package["promotionProposals"]) == 1
    refs = {ref["attempt"] for ref in package["evaluationReportRefs"]}
    assert refs == {"1", "2"}


def test_build_result_package_is_idempotent() -> None:
    existing = {"packageId": "rrp:run-1:stable", "packageRef": "rrp:run-1:stable"}
    package = build_result_package(_run_record(resultPackage=existing))
    assert package["packageId"] == "rrp:run-1:stable"


def test_capability_build_package_requires_facts() -> None:
    caps = node_command_capabilities(_run_record(), "result_package")
    build = next(c for c in caps if c["command"] == "build_package")
    assert build["available"] is False
    view = next(c for c in caps if c["command"] == "view_artifacts")
    assert view["available"] is True
    caps = node_command_capabilities(
        _run_record(iterationDecisions=[{"decisionId": "dec-1"}]),
        "result_package",
    )
    assert next(c for c in caps if c["command"] == "build_package")["available"] is True


def test_build_package_command_persists_to_store(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID, project_id="project-1")
    svc._store.update_run(
        run["runId"],
        {"iterationDecisions": [{"decisionId": "dec-1", "decisionKind": "stop"}]},
    )
    result = svc.apply_node_command(run["runId"], "result_package", "build_package")
    assert result["command"] == "build_package"
    stored = svc.get_run(run["runId"]).get("resultPackage") or {}
    assert stored.get("packageId") == result["resultPackage"]["packageId"]
    assert svc.get_run(run["runId"]).get("resultPackageRef")


def test_build_package_rejects_unavailable_without_facts(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID, project_id="project-1")
    from core.web.services.team_workflow.research_runtime.service import (
        ResearchWorkflowError,
    )

    with pytest.raises(ResearchWorkflowError) as exc:
        svc.apply_node_command(run["runId"], "result_package", "build_package")
    assert exc.value.code == "node_command_unavailable"


# --- evidence graph projection ---


def test_evidence_graph_availability_and_honest_unavailable() -> None:
    ok, reason = evidence_graph_availability(_run_record())
    assert not ok
    assert "证据关系数据" in reason
    ok, _ = evidence_graph_availability(
        _run_record(langGraph={"artifacts": {"evidence_relation_graph": {"nodes": []}}})
    )
    assert ok


def test_evidence_graph_projection_raises_when_no_data(monkeypatch) -> None:
    import core.web.services.team_workflow.research_runtime.evidence_graph_projection as egp

    monkeypatch.setattr(egp, "_loop_evidence_for_project", lambda record: [])
    with pytest.raises(NodeCommandUnavailable):
        project_evidence_graph(_run_record())


def test_evidence_graph_projection_prefers_artifact_dict() -> None:
    raw = {"nodes": [{"id": "n1"}], "edges": [{"source": "n1", "target": "n2", "kind": "k"}]}
    graph = project_evidence_graph(
        _run_record(langGraph={"artifacts": {"evidence_relation_graph": raw}})
    )
    assert graph["nodes"] == raw["nodes"]
    assert graph["runId"] == "run-1"


def test_evidence_graph_projection_from_loop_records(monkeypatch) -> None:
    import core.web.services.team_workflow.research_runtime.evidence_graph_projection as egp

    records = [
        {
            "evidenceId": "ev-1",
            "evidenceType": "benchmark_result",
            "status": "passed",
            "claim": "hypothesis A holds",
            "source": "source-1",
        },
        {"evidenceId": "ev-2", "evidenceType": "full_run_result", "status": "pending"},
    ]
    monkeypatch.setattr(egp, "_loop_evidence_for_project", lambda record: records)
    graph = project_evidence_graph(_run_record())
    assert graph["source"] == "research_loop_evidence_records"
    node_types = {n["type"] for n in graph["nodes"]}
    assert node_types == {"evidence", "source", "claim"}
    edge_kinds = {e["kind"] for e in graph["edges"]}
    assert edge_kinds == {"supports", "derives"}
    evidence = next(n for n in graph["nodes"] if n["id"] == "evidence:ev-1")
    assert evidence["claim"] == "hypothesis A holds"


def test_loop_records_projection_dedupes_and_bounds() -> None:
    graph = _project_from_loop_records(
        [
            {"evidenceId": "ev-1", "claim": "c1", "source": "s1"},
            {"evidenceId": "ev-1", "claim": "c1", "source": "s1"},
            {},
        ]
    )
    assert len([n for n in graph["nodes"] if n["id"] == "evidence:ev-1"]) == 1


def test_open_evidence_graph_command_returns_projection(monkeypatch, tmp_path: Path) -> None:
    import core.web.services.team_workflow.research_runtime.evidence_graph_projection as egp

    monkeypatch.setattr(
        egp,
        "_loop_evidence_for_project",
        lambda record: [{"evidenceId": "ev-9", "claim": "c", "source": "s"}],
    )
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID, project_id="project-1")
    result = svc.apply_node_command(run["runId"], "evidence_relations", "open_evidence_graph")
    assert result["command"] == "open_evidence_graph"
    assert result["graph"]["nodes"]
    assert result["graph"]["edges"]
