"""Pure working-layer outcomeGraph helpers (no official graph / steward writes)."""

from __future__ import annotations

from core.web.services.team_workflow.outcome_graph import (
    build_outcome_graph_delta,
    claim_id_for_hypothesis,
    current_edges,
    merge_registered_result,
    plan_has_outcome_graph,
    project_outcome_memory,
)
from core.web.services.team_workflow.research_memory_context import (
    _claim_map,
    build_research_memory_context,
)


def _plan(*, plan_id="plan-a", hypothesis="Weight 1.0 regresses the frozen metric.", **extra):
    plan = {
        "planId": plan_id,
        "title": "bounded ablation",
        "status": extra.pop("status", "draft"),
        "hypothesisCandidateIds": extra.pop("hypothesisCandidateIds", ["candidate-a"]),
        "selectedHypotheses": [{"hypothesis": hypothesis}],
        "experimentContract": {
            "schemaVersion": 2,
            "revision": 1,
            "researchQuestion": hypothesis,
            "methodConfig": extra.pop("methodConfig", {"candidateMaskedLossWeight": 1.0}),
            "constraints": ["same dataset", "only masked loss weight changes"],
            "decisionContract": {"failureCriteria": ["global regression exceeds 0.0005"]},
        },
    }
    plan.update(extra)
    return plan


def _result(*, result_id, status, recorded_at="2026-08-15T00:00:00Z", **extra):
    payload = {
        "smokeResultId": result_id,
        "status": status,
        "recordedAt": recorded_at,
        "notes": extra.pop("notes", f"Experiment ended with {status}."),
        "logRef": extra.pop("logRef", f"logs/{result_id}.log"),
        "resultPath": extra.pop("resultPath", f"workspace/experiments/{result_id}.json"),
        "delta": extra.pop("delta", ""),
    }
    payload.update(extra)
    return payload


def test_claim_id_matches_claim_map_hash():
    hypothesis = "Context-gated routing improves adaptation under shifting tasks."
    mapped = _claim_map([_plan(hypothesis=hypothesis)], [])
    assert mapped[0]["claimId"] == claim_id_for_hypothesis(hypothesis)


def test_failed_result_writes_current_falsifies_with_required_fields():
    plan = _plan()
    result = _result(result_id="smoke-fail", status="failed", notes="global regression")
    graph = merge_registered_result(plan, result, extra={"notes": "global regression"})
    live = current_edges(graph)
    falsifies = [edge for edge in live if edge["relation"] == "falsifies"]
    tests = [edge for edge in live if edge["relation"] == "tests"]
    assert plan_has_outcome_graph(plan)
    assert len(falsifies) == 1
    assert falsifies[0]["fromId"] == "run:smoke-fail"
    assert falsifies[0]["toId"] == claim_id_for_hypothesis(
        "Weight 1.0 regresses the frozen metric."
    )
    assert falsifies[0]["edgeState"] == "working_only"
    assert falsifies[0]["interpretation"]
    assert falsifies[0]["failedGates"] == ["global regression exceeds 0.0005"]
    assert any(ref["id"] == "smoke-fail" for ref in falsifies[0]["evidenceRefs"])
    assert tests
    assert all(edge["validUntil"] == "" for edge in live)


def test_passed_result_writes_current_supports():
    plan = _plan()
    result = _result(result_id="full-pass", status="passed")
    result["fullRunResultId"] = "full-pass"
    del result["smokeResultId"]
    graph = merge_registered_result(plan, result)
    supports = [edge for edge in current_edges(graph) if edge["relation"] == "supports"]
    assert len(supports) == 1
    assert supports[0]["fromId"] == "run:full-pass"
    assert supports[0]["failedGates"] == []


def test_later_failure_closes_prior_supports_without_deleting_the_old_edge():
    plan = _plan()
    merge_registered_result(plan, _result(result_id="smoke-pass", status="passed", recorded_at="2026-08-15T01:00:00Z"))
    graph = merge_registered_result(
        plan,
        _result(result_id="smoke-fail", status="failed", recorded_at="2026-08-15T02:00:00Z"),
    )
    supports = [edge for edge in graph["edges"] if edge["relation"] == "supports"]
    falsifies = [edge for edge in graph["edges"] if edge["relation"] == "falsifies"]
    assert len(supports) == 1
    assert supports[0]["validUntil"] == "2026-08-15T02:00:00Z"
    assert supports[0]["supersededByEdgeId"] == falsifies[0]["edgeId"]
    live = current_edges(graph)
    assert [edge["relation"] for edge in live if edge["relation"] in {"supports", "falsifies"}] == ["falsifies"]


def test_memory_context_falls_back_to_status_heuristic_without_outcome_graph():
    plan = _plan(
        status="smoke_failed",
        activeSmokeResult={"smokeResultId": "smoke-legacy", "status": "failed", "delta": "global regression"},
    )
    assert plan_has_outcome_graph(plan) is False
    context = build_research_memory_context(
        stage_type="experiment_design",
        research_question="Does weight 1.0 regress?",
        plans=[plan],
    )
    assert context["negativeExperiments"][0]["planId"] == "plan-a"
    assert context["forbiddenDuplicateExperiments"][0]["experimentSignature"]
    assert context["claimMap"][0]["status"] == "unsupported"


def test_graph_projection_prefers_current_edges_over_plan_status():
    plan = _plan(status="smoke_passed")
    merge_registered_result(plan, _result(result_id="smoke-fail", status="failed"))
    context = build_research_memory_context(
        stage_type="experiment_design",
        research_question="Does weight 1.0 regress?",
        plans=[plan],
    )
    assert context["negativeExperiments"][0]["planId"] == "plan-a"
    assert context["negativeExperiments"][0]["failedGates"] == ["global regression exceeds 0.0005"]
    assert context["forbiddenDuplicateExperiments"][0]["defaultAction"] == "exclude_from_suggestions"
    assert context["claimMap"][0]["status"] == "unsupported"
    assert context["claimMap"][0]["claimId"] == claim_id_for_hypothesis(
        "Weight 1.0 regresses the frozen metric."
    )
    assert context["priorSuccessfulRuns"] == []


def test_working_supports_do_not_qualify_claim_without_steward_item():
    plan = _plan(status="full_run_passed")
    result = _result(result_id="full-pass", status="passed")
    result["fullRunResultId"] = "full-pass"
    del result["smokeResultId"]
    merge_registered_result(plan, result)
    context = build_research_memory_context(
        stage_type="experiment_design",
        research_question="Does weight 1.0 help?",
        plans=[plan],
    )
    assert context["priorSuccessfulRuns"][0]["resultId"] == "full-pass"
    assert context["claimMap"][0]["status"] == "not_established"
    assert context["claimMap"][0]["supportEvidenceRefs"][0]["id"] == "full-pass"


def test_same_signature_peer_plan_writes_duplicates_edge():
    first = _plan(plan_id="plan-old", status="smoke_failed")
    merge_registered_result(first, _result(result_id="smoke-old", status="failed"))
    second = _plan(plan_id="plan-new")
    graph = merge_registered_result(
        second,
        _result(result_id="smoke-new", status="failed"),
        peer_plans=[first, second],
    )
    duplicates = [edge for edge in graph["edges"] if edge["relation"] == "duplicates"]
    assert duplicates
    assert duplicates[0]["fromId"] == "run:smoke-new"
    assert duplicates[0]["toId"] == "run:smoke-old"
    projected = project_outcome_memory([first, second])
    signatures = {item["experimentSignature"] for item in projected["forbiddenDuplicateExperiments"]}
    assert first["outcomeGraph"]["edges"][0]["experimentSignature"] in signatures


def test_delta_claim_id_uses_same_normalizer_as_claim_map():
    plan = _plan(hypothesis="  Mixed Case   Hypothesis. ")
    delta = build_outcome_graph_delta(plan, _result(result_id="smoke-x", status="failed"))
    mapped = _claim_map([plan], [])
    assert delta["claimId"] == mapped[0]["claimId"]
