from types import SimpleNamespace

import pytest

from core.web.services.team_workflow.research_runtime import evidence_graph_projection as graphs
from core.web.services.team_workflow.research_runtime import artifact_readback_registry as artifacts
from core.web.services.team_workflow.research_runtime.real_domain_ports import RealDomainPorts
from core.web.services.team_workflow.research_runtime.real_readiness_context import RealDomainReadinessContext


@pytest.mark.parametrize("bindings", [[], [{"nodeId": "hypothesis_design", "agentId": ""}]])
def test_missing_frozen_binding_never_reads_current_team(monkeypatch, bindings):
    from core.web.services.team_workflow.research_runtime import team_role_source
    monkeypatch.setattr(team_role_source, "resolve_team_role_bindings", lambda *_: pytest.fail("live Team cannot repair a frozen run"))
    snapshot = {"teamId": "team-1", "agentBindingSnapshot": bindings}
    ports = object.__new__(RealDomainPorts)
    monkeypatch.setattr(ports, "_run_input_snapshot", lambda _: snapshot)
    ctx = object.__new__(RealDomainReadinessContext)
    monkeypatch.setattr(ctx, "_input_snapshot", lambda _: snapshot)
    action = SimpleNamespace(run_id="run-1", node_id="hypothesis_design")
    assert not ports.resolve_binding(action).agent_id
    assert not (ctx.binding_snapshot("run-1", "hypothesis_design") or {}).get("agentId")


def graph_record(payload, *, team_id="team-1"):
    digest = artifacts.canonical_sha256(payload)
    ref = artifacts.build_canonical_ref(kind="evidence_relation_graph", team_id=team_id,
        authority_run_id="sc-1", content_hash=digest)
    return {"runId": "run-1", "teamId": "team-1", "projectId": "project-1",
        "artifactSummary": {"refs": [{"kind": "evidence_relation_graph", "canonicalRef": ref,
            "sha256": digest, "verifiedAtMs": 10, "materialized": True}]}}


def test_graph_uses_bound_ref_and_exact_run(monkeypatch):
    payload = {"nodes": [{"candidateId": "e1", "candidateType": "source"}], "edges": [], "teamId": "team-1", "sourceCollectionRunId": "sc-1"}
    calls = []
    def load(kind, **scope):
        calls.append((kind, scope))
        return payload
    monkeypatch.setattr(artifacts, "load_scoped_artifact_payload", load)
    graph = graphs.project_evidence_graph(graph_record(payload))
    assert graph["nodes"][0]["id"] == payload["nodes"][0]["candidateId"]
    assert calls[0][1]["workflow_run_id"] == "run-1"
    assert calls[0][1]["authority_run_id"] == "sc-1"


@pytest.mark.parametrize("change", ["hash", "team", "no_ref"])
def test_graph_rejects_unbound_or_changed_artifacts(monkeypatch, change):
    payload = {"nodes": [{"candidateId": "e1", "candidateType": "source"}], "edges": []}
    record = graph_record(payload, team_id="other-team" if change == "team" else "team-1")
    if change == "no_ref":
        record["artifactSummary"]["refs"] = []
        record["langGraph"] = {"artifacts": {"evidence_relation_graph": payload}}
    monkeypatch.setattr(artifacts, "load_scoped_artifact_payload", lambda *a, **k: {**payload, "changed": True} if change == "hash" else payload)
    with pytest.raises(graphs.NodeCommandUnavailable):
        graphs.project_evidence_graph(record)


def test_ledger_keeps_evidence_envelope_separate_from_bound_graph(monkeypatch):
    from core.web.services import research_evidence_service, team_knowledge_service
    from core.web.services.team_workflow.experiment_api import plan
    from core.web.services.team_workflow.research_runtime import ledger_domain_projections as projections
    graph = {"nodes": [{"candidateId": "current-evidence", "candidateType": "evidence"}], "edges": []}
    record = {**graph_record(graph), "runVersion": 1}
    evidence = [{"evidenceId": "team-evidence"}]
    monkeypatch.setattr(projections, "snapshot_projection_record", lambda _: record)
    monkeypatch.setattr(research_evidence_service, "list_claim_evidence", lambda _: {"evidence": evidence})
    monkeypatch.setattr(team_knowledge_service, "list_team_knowledge_bases", lambda *a, **k: {"bases": []})
    monkeypatch.setattr(plan, "get_experiment_planning_status", lambda _: {})
    monkeypatch.setattr(artifacts, "load_scoped_artifact_payload", lambda *a, **k: graph)
    result = projections.project_research_ledger_from_snapshot(None)
    assert result["claimEvidence"] == evidence
    assert result["graph"]["nodes"][0]["id"] == "current-evidence"
    assert "team-evidence" not in str(result["graph"])


def test_snapshot_projection_preserves_artifact_receipt_binding(monkeypatch):
    from core.web.services.team_workflow.research_runtime import ledger_domain_projections as projections
    summary = {"refs": [{"kind": "evidence_relation_graph", "canonicalRef": "bound-ref"}]}
    snapshot = SimpleNamespace(run=SimpleNamespace(to_dict=lambda: {"runId": "r", "teamId": "t", "runVersion": 1, "projectId": "p"}),
        handoff_summary=SimpleNamespace(refs=[]), pending_human_tasks=[], artifact_summary=summary)
    monkeypatch.setattr(projections, "_budget_records", lambda _: ([], []))
    assert projections.snapshot_projection_record(snapshot)["artifactSummary"] == summary


def test_existing_frozen_binding_is_used_without_team_lookup(monkeypatch):
    from core.web.services.team_workflow.research_runtime import team_role_source, real_domain_ports
    monkeypatch.setattr(team_role_source, "resolve_team_role_bindings", lambda *_: pytest.fail("unexpected live lookup"))
    monkeypatch.setattr(real_domain_ports, "_binding_session_scope", lambda *a: None)
    binding = {"nodeId": "hypothesis_design", "agentId": "frozen-agent", "roleKey": "hypothesis_designer", "snapshotId": "frozen-id"}
    snapshot = {"teamId": "team-1", "agentBindingSnapshot": [binding]}
    ports = object.__new__(RealDomainPorts)
    monkeypatch.setattr(ports, "_run_input_snapshot", lambda _: snapshot)
    ctx = object.__new__(RealDomainReadinessContext)
    monkeypatch.setattr(ctx, "_input_snapshot", lambda _: snapshot)
    assert ports.resolve_binding(SimpleNamespace(run_id="r", node_id="hypothesis_design")).agent_id == "frozen-agent"
    assert ctx.binding_snapshot("r", "hypothesis_design") == binding


def test_graph_projects_real_readback_and_rejects_post_receipt_mutation(monkeypatch):
    raw = {"nodes": [{"candidateId": "a", "candidateType": "source"}, {"candidateId": "b", "candidateType": "source"}],
        "edges": [{"sourceCandidateId": "a", "targetCandidateId": "b", "evidenceRefs": ["claim-1"]}],
        "evidenceGaps": [{"description": "Independent replication missing"}],
        "counterEvidenceRefs": [{"evidenceRef": "claim-2", "claim": "Null result"}]}
    monkeypatch.setattr(artifacts, "_load_scoped_relation_graph", lambda **_: raw)
    monkeypatch.setattr(artifacts, "load_allowed_evidence_refs", lambda **_: ["claim-1", "claim-2"])
    payload = artifacts.load_scoped_artifact_payload("evidence_relation_graph", team_id="team-1", authority_run_id="sc-1", workflow_run_id="run-1")
    record = graph_record(payload)
    projected = graphs.project_evidence_graph(record)
    assert projected["edges"][0]["source"] == "a"
    assert projected["edges"][0]["target"] == "b"
    assert projected["nodes"][0]["id"] == "a"
    assert "id" not in raw["nodes"][0]
    assert "source" not in raw["edges"][0]
    raw["evidenceGaps"][0]["description"] = "Changed after receipt"
    assert graphs.evidence_graph_availability(record)[0] is False
    with pytest.raises(graphs.NodeCommandUnavailable):
        graphs.project_evidence_graph(record)


def test_missing_current_graph_does_not_fall_back_to_prior_receipt(monkeypatch):
    old = {"nodes": [{"candidateId": "old"}], "edges": []}
    new = {"nodes": [{"candidateId": "new"}], "edges": []}
    record = graph_record(old)
    newest = graph_record(new)["artifactSummary"]["refs"][0]
    newest["verifiedAtMs"] = 20
    record["artifactSummary"]["refs"].append(newest)
    monkeypatch.setattr(artifacts, "load_scoped_artifact_payload", lambda *a, **k: old)
    with pytest.raises(graphs.NodeCommandUnavailable):
        graphs.project_evidence_graph(record)
