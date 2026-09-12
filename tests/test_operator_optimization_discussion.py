import json
from types import SimpleNamespace

import pytest

from tests.test_operator_optimization_budget import activity
from tests.test_operator_optimization_rounds import ready
from core.web.services.team_workflow.operator_optimization import discussion, rounds
from core.web.services.team_workflow.operator_optimization.store import read_campaign, CampaignConflict


def _save_selected(team_id, run_id, payload, *, provenance):
    from core.research.operator_optimization.contracts import ArtifactRef
    result = discussion.save_discussion_result(team_id, run_id,
        {"status": "selected", "reason": "Selected through structured discussion", "hypothesis": payload},
        provenance=provenance)
    return ArtifactRef.model_validate(result["hypothesisRef"])


@pytest.fixture
def discussion_case(activity, ready, monkeypatch):
    campaign, baseline_run, calls = ready
    created = rounds.prepare_round(*activity, expected_version=campaign.revision, command_key="round1")
    run = SimpleNamespace(run_id=created.activeRunId, team_id=activity[0], project_id=activity[1],
        workflow_id="operator-optimization", input_snapshot_json=json.dumps(calls[0][1]["run_input"]))
    monkeypatch.setattr(discussion, "get_write_store", lambda: SimpleNamespace(get_run=lambda _: run))
    payload = {"hypothesisId": "hypothesis1", "optimizationCampaignId": activity[2],
        "roundId": created.rounds[0].roundId,
        "parentCandidateRef": created.rounds[0].parentCandidateRef.model_dump(),
        "observationRefs": [campaign.baselineRef.model_dump()], "proposedChange": "Fuse row softmax",
        "mechanism": "Reduce global memory traffic", "prediction": "Lower paired latency on large rows",
        "counterevidence": "Register pressure can slow wide rows", "roi": "high",
        "roiReason": "Small bounded implementation and measurable latency", "evidenceGaps": ["Check occupancy guidance"]}
    return created, run, payload


def test_discussion_reads_frozen_evidence_and_saves_one_hypothesis(activity, discussion_case):
    campaign, run, payload = discussion_case
    inputs = discussion.discussion_input(activity[0], run.run_id)
    assert inputs["evidence"][0]["sourceRunId"] == "run1"
    assert inputs["context"]["roundId"] == campaign.rounds[0].roundId
    ref = _save_selected(activity[0], run.run_id, payload, provenance={})
    assert _save_selected(activity[0], run.run_id, payload, provenance={}) == ref
    assert read_campaign(*activity).rounds[0].hypothesisRef == ref
    assert ref.kind == "optimization_hypothesis"


def test_hypothesis_cannot_cite_unprovided_evidence(activity, discussion_case):
    campaign, run, payload = discussion_case
    payload["observationRefs"][0]["sha256"] = "f" * 64
    with pytest.raises(CampaignConflict, match="outside the discussion"):
        _save_selected(activity[0], run.run_id, payload, provenance={})
    assert read_campaign(*activity).rounds[0].hypothesisRef is None


def test_hypothesis_cannot_cross_rounds(activity, discussion_case):
    _, run, payload = discussion_case
    payload["roundId"] = "other-round"
    with pytest.raises(CampaignConflict, match="frozen discussion"):
        _save_selected(activity[0], run.run_id, payload, provenance={})


def test_same_discussion_cannot_overwrite_hypothesis(activity, discussion_case):
    from core.web.services.team_workflow.research_runtime.workflow_artifact_store import WorkflowArtifactConflictError
    _, run, payload = discussion_case
    _save_selected(activity[0], run.run_id, payload, provenance={})
    with pytest.raises(WorkflowArtifactConflictError):
        _save_selected(activity[0], run.run_id, {**payload, "prediction": "different prediction"}, provenance={})


def test_discussion_summary_keeps_failures_without_copying_raw_timings():
    payload = {"status": "failed", "failureReason": "case two failed", "cases": [
        {"caseId": "one", "correctnessPassed": True, "timings": [
            {"baselineMs": 4, "parentMs": 3, "candidateMs": 2},
            {"baselineMs": 6, "parentMs": 5, "candidateMs": 4}]}]}
    summary = discussion._evidence_summary("operator_measurement", payload)
    assert summary["failureReason"] == "case two failed"
    assert summary["cases"][0]["medianMs"]["candidateMs"] == 3
    assert summary["cases"][0]["sampleCount"] == 2
    assert "timings" not in summary["cases"][0]
    assert len(payload["cases"][0]["timings"]) == 2


@pytest.mark.parametrize("failure_kind", ["optimization_discussion", "optimization_hypothesis"])
def test_publication_keeps_provenance_before_attachment_and_recovers(activity, discussion_case, monkeypatch, failure_kind):
    _, run, payload = discussion_case
    original = discussion.artifacts.put_workflow_artifact
    written = []
    def fail_once(*args, **kwargs):
        written.append(kwargs["kind"])
        if kwargs["kind"] == failure_kind:
            raise OSError("publication interrupted")
        return original(*args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(discussion.artifacts, "put_workflow_artifact", fail_once)
        with pytest.raises(OSError, match="interrupted"):
            _save_selected(activity[0], run.run_id, payload, provenance={"messageRefs": []})
    assert written[0] == "optimization_discussion"
    assert read_campaign(*activity).rounds[0].hypothesisRef is None
    ref = _save_selected(activity[0], run.run_id, payload, provenance={"messageRefs": []})
    assert read_campaign(*activity).rounds[0].hypothesisRef == ref
