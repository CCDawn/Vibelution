from copy import deepcopy

import pytest

from core.web.services.team_workflow import meeting_runtime
from core.web.services.team_workflow.research_runtime import candidate_screening_artifact_writer as screening


def _record():
    return {"workflowRunId": "run-1", "payload": {
        "questionId": "SCI-098", "screeningId": "screen-1",
        "candidates": [{"candidateId": cid, "axisProfile": {"mechanism": "same"}}
                       for cid in ["a", "b", "c"]],
        "pairwiseCandidateIds": ["a"],
    }}


@pytest.mark.parametrize("change", ["none", "run", "question", "pool", "passed"])
def test_screening_recovery_uses_only_exact_failed_pool(change):
    record = _record()
    if change == "run":
        record["workflowRunId"] = "older-run"
    elif change == "question":
        record["payload"]["questionId"] = "SCI-003"
    elif change == "pool":
        record["payload"]["candidates"].pop()
    elif change == "passed":
        record["payload"]["pairwiseCandidateIds"] = ["a", "b"]
        record["payload"]["candidates"][1]["axisProfile"]["mechanism"] = "different"
    result = screening.collapsed_screening_for_candidates(
        [record], question_id="SCI-098", workflow_run_id="run-1", candidate_ids=["c", "a", "b"],
    )
    assert (result is not None) is (change == "none")


def test_regeneration_opening_carries_failed_axes_without_calling_them_evidence():
    topic = meeting_runtime._generation_opening_topic(
        "meeting-2", "SCI-098", [], generation_context={
            "screeningFeedback": {"code": "diversity_collapse", "previousAxes": [{"mechanism": "old-axis"}]},
        },
    )
    assert "old-axis" in topic
    assert "不作为证据" in topic
    assert "不得编造" in topic


def test_closed_collapsed_generation_opens_new_attempt_instead_of_replaying(tmp_path, monkeypatch):
    from tests.test_research_workflow_hypothesis_first_chain import _hf_env, _QUESTION_ID, server_operator_scope
    from core.web.services.team_workflow.research_runtime import hypothesis_first_chain as chain

    team_id, _ = _hf_env(tmp_path, monkeypatch)
    meeting = {"meetingRoundId": "old-meeting", "status": "closed",
               "candidateAuthority": "formal_grounded_candidate"}
    monkeypatch.setattr(chain, "_question_generation_meetings", lambda *args, **kwargs: [meeting])
    monkeypatch.setattr(chain, "_heal_generation_candidates", lambda *args: None)
    monkeypatch.setattr(chain, "list_hypothesis_candidates", lambda *args, **kwargs: {
        "candidates": [{"candidateId": cid} for cid in ["a", "b", "c"]],
    })
    monkeypatch.setattr(screening, "read_collapsed_screening", lambda *args, **kwargs: deepcopy(_record()["payload"]))

    class FreshAttemptReached(Exception):
        pass

    def append_attempt(*args, **kwargs):
        assert kwargs["lifecycle"] == "queued"
        assert kwargs["meeting_round_id"] != "old-meeting"
        raise FreshAttemptReached

    monkeypatch.setattr(chain, "_append_generation_attempt_state", append_attempt)
    with server_operator_scope("u-1", roles=("operator",)), pytest.raises(FreshAttemptReached):
        chain.open_candidate_generation_meeting(
            team_id, _QUESTION_ID, _candidate_authority="formal_grounded_candidate",
            _model_invocation_receipt_authority={"workflowRunId": "run-1"},
            _generation_context={"status": "ready", "allowedEvidenceRefs": ["accepted-evidence"]},
        )
