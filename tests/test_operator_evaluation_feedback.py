"""Numerical decisions and next-round evidence over real artifacts and SQLite."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from core.research.operator_optimization.measurement import (
    CaseMeasurement,
    PairedTiming,
)
from core.web.services.team_workflow.operator_optimization import (
    dispatch,
    execution,
    evaluation,
    feedback,
    rounds,
    discussion,
)
from core.web.services.team_workflow.operator_optimization.knowledge import read_ref
from core.web.services.team_workflow.operator_optimization.store import (
    read_campaign,
    CampaignConflict,
)
from core.web.services.team_workflow.research_runtime.real_domain_ports import (
    RealDomainPorts,
)
from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import (
    SystemActionAdapter,
)
from core.research.workflow.models import ActorKind
from tests import test_operator_plan_execution as fixtures
from tests._support.workflow_ledger_helpers import (
    build_attempt_record,
    build_command_record,
)
from tests.test_research_workflow_agent_anchor import _agent_action

activity = fixtures.activity
baseline_ready = fixtures.baseline_ready
ready = fixtures.ready
discussion_case = fixtures.discussion_case
handoff = fixtures.handoff
proposal = fixtures.proposal
prepared = fixtures.prepared


def node(prepared, name):
    action, _, _, store = prepared
    store.submit(
        lambda u: u.repository.insert_command(
            replace(
                build_command_record(run_id=action.run_id, command_id=name),
                idempotency_key=name,
            )
        ),
        force_flush=True,
    ).result()
    store.submit(
        lambda u: u.repository.insert_attempt(
            build_attempt_record(
                name,
                run_id=action.run_id,
                node_id=name,
                status="running",
                command_id=name,
            )
        ),
        force_flush=True,
    ).result()
    return SimpleNamespace(
        run_id=action.run_id, node_run_id=name, node_id=name, action_id=name
    )


def measure(prepared, monkeypatch, outcomes):
    action, snapshot, _, _ = prepared
    original = dispatch.execute_cuda_trial
    pending = iter(outcomes)

    def controlled(request, **kwargs):
        raw = original(request, **kwargs)
        outcome = next(pending)
        if outcome == "failed":
            return raw
        correct = outcome != "incorrect"
        value = 0.5 if outcome in {"fast", "incorrect", "missing_error"} else 1.1
        return raw.model_copy(
            update={
                "status": "succeeded",
                "failureReason": "",
                "cases": tuple(
                    CaseMeasurement(
                        caseId=c.caseId,
                        correctnessPassed=correct,
                        maxAbsoluteError=None
                        if outcome == "missing_error"
                        else 0
                        if correct
                        else 1,
                        timings=tuple(
                            PairedTiming(baselineMs=1, parentMs=1, candidateMs=value)
                            for _ in range(request.protocol.pairs)
                        ),
                    )
                    for c in request.protocol.cases
                ),
            }
        )

    monkeypatch.setattr(dispatch, "execute_cuda_trial", controlled)
    return execution.execute_plan(action, snapshot)


@pytest.mark.parametrize(
    "outcomes,promote",
    [
        (["fast", "fast"], True),
        (["fast", "slow"], False),
        (["failed", "fast"], False),
        (["incorrect", "fast"], False),
        (["missing_error", "fast"], False),
    ],
)
def test_all_repeats_must_pass_and_feedback_replays(
    activity, prepared, monkeypatch, outcomes, promote
):
    _, snapshot, calls, _ = prepared
    before = read_campaign(*activity)
    measure(prepared, monkeypatch, outcomes)
    evaluate = node(prepared, "operator_evaluation")
    ref = evaluation.publish_evaluation(evaluate, snapshot)
    result = read_ref(activity[0], evaluate.run_id, ref)
    assert result["promote"] is promote
    assert len(result["trials"]) == 2
    assert read_campaign(*activity).bestCandidateRef == before.bestCandidateRef
    feed = node(prepared, "optimization_feedback")
    first = feedback.publish_feedback(feed, snapshot)
    current = read_campaign(*activity)
    expected = result["candidateRef"] if promote else result["parentCandidateRef"]
    assert current.bestCandidateRef.model_dump(mode="json") == expected
    assert current.baselineRef == before.baselineRef
    assert current.rounds[0].evaluationRef == ref
    assert current.rounds[0].feedbackRef == first
    assert feedback.publish_feedback(feed, snapshot) == first
    assert read_campaign(*activity).revision == current.revision
    assert len(calls) == 2
    payload = read_ref(activity[0], feed.run_id, first)
    assert payload["hypothesisAssessment"]["status"] == "requires_discussion"
    assert [r["executionStatus"] for r in payload["trialResults"]] == [
        "failed" if x == "failed" else "succeeded" for x in outcomes
    ]


def test_no_measurements_cannot_be_evaluated(prepared):
    evaluate = node(prepared, "operator_evaluation")
    with pytest.raises(CampaignConflict, match="every planned trial"):
        evaluation.publish_evaluation(evaluate, prepared[1])


def test_receipt_with_wrong_candidate_cannot_be_promoted(prepared, monkeypatch):
    measure(prepared, monkeypatch, ["fast", "fast"])
    actual = evaluation.read_ref

    def changed(*args):
        payload = actual(*args)
        return payload | {"candidateSourceHash": "f" * 64}

    monkeypatch.setattr(evaluation, "read_ref", changed)
    with pytest.raises(CampaignConflict, match="differs"):
        evaluation.publish_evaluation(
            node(prepared, "operator_evaluation"), prepared[1]
        )


def test_feedback_recovers_after_artifact_before_atomic_selection(
    activity, prepared, monkeypatch
):
    measure(prepared, monkeypatch, ["fast", "fast"])
    evaluation.publish_evaluation(node(prepared, "operator_evaluation"), prepared[1])
    feed = node(prepared, "optimization_feedback")
    original = feedback.update_campaign
    monkeypatch.setattr(
        feedback,
        "update_campaign",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("interrupted")),
    )
    with pytest.raises(RuntimeError, match="interrupted"):
        feedback.publish_feedback(feed, prepared[1])
    assert read_campaign(*activity).rounds[0].feedbackRef is None
    monkeypatch.setattr(feedback, "update_campaign", original)
    ref = feedback.publish_feedback(feed, prepared[1])
    assert read_campaign(*activity).rounds[0].feedbackRef == ref


def test_system_adapters_verify_evaluation_and_feedback(prepared, monkeypatch):
    measure(prepared, monkeypatch, ["failed", "failed"])
    store = prepared[3]
    adapter = SystemActionAdapter(RealDomainPorts(store))
    for name in ("operator_evaluation", "optimization_feedback"):
        simple = node(prepared, name)
        action = replace(
            _agent_action(),
            run_id=simple.run_id,
            node_run_id=simple.node_run_id,
            node_id=name,
            actor_kind=ActorKind.SYSTEM,
            input_snapshot_hash="",
        )
        result = adapter.execute(action)
        assert adapter.verify(action, result).outcome == "succeeded"


@pytest.mark.parametrize("outcomes", [["failed", "fast"], ["fast", "fast"]])
def test_next_round_inherits_selected_candidate_and_failure_evidence(
    activity, prepared, baseline_ready, tmp_path, monkeypatch, outcomes
):
    from core.research.workflow.models import AgentBindingLayers
    from tests.test_operator_optimization_rounds import actual_create_run as create_run

    measure(prepared, monkeypatch, outcomes)
    evaluate = node(prepared, "operator_evaluation")
    evaluation.publish_evaluation(evaluate, prepared[1])
    feedback.publish_feedback(node(prepared, "optimization_feedback"), prepared[1])
    store = prepared[3]
    baseline_run = baseline_ready[1]

    class Store:
        def get_run(self, run_id):
            return (
                baseline_run if run_id == baseline_run.run_id else store.get_run(run_id)
            )

        def __getattr__(self, name):
            return getattr(store, name)

    monkeypatch.setattr(rounds.run_creation, "get_write_store", lambda: Store())
    monkeypatch.setattr(discussion, "get_write_store", lambda: Store())
    monkeypatch.setattr(rounds.run_creation, "create_run", create_run)
    monkeypatch.setattr(
        rounds.run_creation, "research_workflow_data_root", lambda: tmp_path
    )
    monkeypatch.setattr(
        rounds.run_creation,
        "effective_binding_layers",
        lambda *a: AgentBindingLayers(
            workflowDefaults={"experiment_planner": "planner-fixture"}
        ),
    )
    current = read_campaign(*activity)
    with pytest.raises(CampaignConflict, match="terminal"):
        rounds.prepare_round(
            *activity, expected_version=current.revision, command_key="next"
        )
    store.submit(
        lambda u: u.repository.execute(
            "UPDATE workflow_runs SET status='succeeded' WHERE run_id=?",
            (evaluate.run_id,),
        ),
        force_flush=True,
    ).result()
    after = rounds.prepare_round(
        *activity, expected_version=current.revision, command_key="next"
    )
    assert (
        rounds.prepare_round(
            *activity, expected_version=current.revision, command_key="next"
        )
        == after
    )
    assert len(after.rounds) == 2
    assert after.rounds[-1].parentCandidateRef == current.bestCandidateRef
    evidence = discussion.discussion_input(activity[0], after.activeRunId)["evidence"]
    assert {e["ref"]["kind"] for e in evidence} >= {
        "operator_evaluation",
        "optimization_feedback",
        "operator_measurement",
    }
    assert any(e["summary"].get("status") == "failed" for e in evidence) == (
        "failed" in outcomes
    )
