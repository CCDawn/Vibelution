"""Evidence graph command coverage plus Result Package availability projection.

Strict terminal Result Package construction and its system-adapter lifecycle
live in the canonical v2.1 stream/iteration suites. This file deliberately
covers the remaining read-model and command surfaces without reintroducing the
obsolete pre-v2.1 auto-advance contract.
"""

from __future__ import annotations

import json
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
    result_package_availability,
)
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowRuntimeService,
    reset_research_workflow_runtime_service_for_tests,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore


_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "research_workflow_v21_baseline_case.json"


def _svc(tmp_path: Path) -> ResearchWorkflowRuntimeService:
    store = WorkflowRunStore(tmp_path / "runs")
    index = DurableWorkflowIndex(tmp_path / "runs" / "_index")
    ckpt = str(tmp_path / "ckpt.sqlite")
    return reset_research_workflow_runtime_service_for_tests(
        run_store=store,
        checkpoint_path=ckpt,
        durable_index=index,
    )


def _run_input() -> dict:
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))["runInput"]


def _run_record(**extra) -> dict:
    record = {
        "runId": "run-1",
        "workflowId": CHALLENGE_CUP_WORKFLOW_ID,
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
    assert {node["type"] for node in graph["nodes"]} == {"evidence", "source", "claim"}
    assert {edge["kind"] for edge in graph["edges"]} == {"supports", "derives"}
    evidence = next(node for node in graph["nodes"] if node["id"] == "evidence:ev-1")
    assert evidence["claim"] == "hypothesis A holds"


def test_loop_records_projection_dedupes_and_bounds() -> None:
    graph = _project_from_loop_records(
        [
            {"evidenceId": "ev-1", "claim": "c1", "source": "s1"},
            {"evidenceId": "ev-1", "claim": "c1", "source": "s1"},
            {},
        ]
    )
    assert len([node for node in graph["nodes"] if node["id"] == "evidence:ev-1"]) == 1


def test_open_evidence_graph_command_returns_projection(monkeypatch, tmp_path: Path) -> None:
    import core.web.services.team_workflow.research_runtime.evidence_graph_projection as egp

    monkeypatch.setattr(
        egp,
        "_loop_evidence_for_project",
        lambda record: [{"evidenceId": "ev-9", "claim": "c", "source": "s"}],
    )
    service = _svc(tmp_path)
    run = service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=_run_input(),
        idempotency_key="evidence-graph-command",
    )

    result = service.apply_node_command(
        run["runId"],
        "evidence_relations",
        "open_evidence_graph",
    )

    assert result["command"] == "open_evidence_graph"
    assert result["graph"]["nodes"]
    assert result["graph"]["edges"]
