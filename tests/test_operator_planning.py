"""Real artifact publication and recovery; no production model or GPU calls."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from core.research.operator_optimization.candidate import CudaCandidate, ensure_current_source_hash
from core.research.operator_optimization.plan import OptimizationPlan, OptimizationPlanProposal
from core.web.services.team_workflow.operator_optimization import (
    knowledge,
    planning,
    planning_output,
    planning_task,
)
from core.web.services.team_workflow.operator_optimization.store import CampaignConflict, read_campaign
from core.web.services.team_workflow.research_runtime.workflow_artifact_store import list_workflow_artifacts
from tests import test_operator_knowledge_plan as fixtures

activity = fixtures.activity
baseline_ready = fixtures.baseline_ready
ready = fixtures.ready
discussion_case = fixtures.discussion_case
handoff = fixtures.handoff


@pytest.fixture
def proposal(activity, handoff):
    run, _, _ = fixtures.selected(activity, handoff)
    knowledge.publish_knowledge_snapshot(activity[0], run.run_id)
    inputs = planning_output.planning_task_input(activity[0], run.run_id)
    return run.run_id, OptimizationPlanProposal(
        inputHash=inputs["inputHash"],
        candidate=CudaCandidate(implementation="triton_row_softmax", numWarps=8),
        objective="Test whether eight warps improve row softmax latency",
        evaluation="Paired measurements under the frozen tuning protocol",
        prediction="Lower latency while retaining the frozen correctness tolerance",
        counterevidence="Incorrect output or repeatable slowdown rejects the change",
        evidenceAssessment="Existing observations motivate a test, not a performance claim",
        trialCount=1, trialTimeoutSeconds=30,
    )


def artifacts(team_id, run_id, kind="operator_candidate"):
    return list_workflow_artifacts(team_id, kind=kind, workflow_run_id=run_id)


def test_materializes_reconstructible_candidate_and_idempotent_plan(activity, proposal):
    run_id, output = proposal
    ref = planning_output.materialize_optimization_plan(activity[0], run_id, output)
    assert planning_output.materialize_optimization_plan(activity[0], run_id,
        output.model_dump_json()) == ref
    plan = OptimizationPlan.model_validate(knowledge.read_ref(activity[0], run_id, ref))
    assert read_campaign(*activity).rounds[0].planRef == ref
    assert plan.candidateRef.candidate == output.candidate
    assert plan.candidateRef.runId == run_id
    ensure_current_source_hash(plan.candidateRef.candidate, plan.candidateRef.sourceHash)
    rows = artifacts(activity[0], run_id)
    assert len(rows) == 1
    assert rows[0]["payload"]["roundId"] == plan.roundId
    assert rows[0]["payload"]["optimizationCampaignId"] == plan.optimizationCampaignId
    assert len(artifacts(activity[0], run_id, "optimization_plan")) == 1


def test_reuses_parent_for_confirmatory_rerun(activity, proposal):
    run_id, output = proposal
    inputs = planning.planning_input(activity[0], run_id)
    output = output.model_copy(update={"candidate": CudaCandidate.model_validate(
        inputs["parentCandidateRef"]["candidate"])})
    ref = planning_output.materialize_optimization_plan(activity[0], run_id, output)
    assert knowledge.read_ref(activity[0], run_id, ref)["candidateRef"] == inputs["parentCandidateRef"]
    assert artifacts(activity[0], run_id) == []


@pytest.mark.parametrize("change", [
    {"inputHash": "f" * 64}, {"trialCount": 12}, {"trialTimeoutSeconds": 3600},
    {"gapChecks": [{"gap": "invented gap", "experimentCheck": "invented check"}]},
])
def test_invalid_decisions_publish_nothing(activity, proposal, change):
    run_id, output = proposal
    value = output.model_dump(mode="json") | change
    with pytest.raises(CampaignConflict):
        planning_output.materialize_optimization_plan(activity[0], run_id, value)
    assert artifacts(activity[0], run_id) == []
    assert read_campaign(*activity).rounds[0].planRef is None


@pytest.mark.parametrize("change", [
    {"candidate": {"implementation": "custom_kernel", "sourcePath": "C:/kernel.py"}},
    {"candidateRef": {"artifactId": "fake"}}, {"protocolRef": {"artifactId": "fake"}},
    {"candidate": {"implementation": "triton_row_softmax", "numWarps": 32}},
    {"trialCount": True},
])
def test_model_cannot_supply_identities_or_unmanaged_code(activity, proposal, change):
    run_id, output = proposal
    with pytest.raises(ValidationError):
        planning_output.materialize_optimization_plan(activity[0], run_id,
            output.model_dump(mode="json") | change)
    assert artifacts(activity[0], run_id) == []


def test_provider_contract_validates_structured_payload(proposal):
    _, output = proposal
    contract = planning_output.planning_output_contract()
    assert contract.schema["additionalProperties"] is False
    assert contract.validator(output.model_dump(mode="json")) == json.loads(output.model_dump_json())
    with pytest.raises(ValueError):
        planning_output.parse_planning_output("The experiment plan is ready")
    with pytest.raises(ValidationError):
        planning_output.parse_planning_output(output.model_copy(update={"trialCount": 0}))


def test_planner_prompt_requires_verbatim_ordered_knowledge_gaps(activity, proposal):
    run_id, _ = proposal
    inputs = planning_output.planning_task_input(activity[0], run_id)
    prompt = planning_task._planning_prompt(inputs)
    assert "第 i 项的 gap 必须逐字复制 knowledge.evidenceGaps[i]" in prompt
    assert "禁止合并、拆分、摘要或改写 gap" in prompt


def test_planner_prompt_binds_trial_decisions_to_current_budget(activity, proposal):
    run_id, _ = proposal
    inputs = planning_output.planning_task_input(activity[0], run_id)
    inputs["budget"] = {
        **inputs["budget"],
        "maxTrialsPerRound": 3,
        "trialTimeoutSeconds": 120,
    }
    inputs["remainingBudget"] = {
        **inputs["remainingBudget"],
        "gpuTuningAvailableSeconds": 300,
    }

    prompt = planning_task._planning_prompt(inputs)

    assert "trialCount 必须是 1 到 3 的整数" in prompt
    assert "trialTimeoutSeconds 不得超过 120" in prompt
    assert "剩余 GPU 调优时长 300 秒" in prompt
    assert "选择能够区分假设的最少 trialCount" in prompt


def test_crash_after_candidate_write_recovers_without_duplicate(activity, proposal, monkeypatch):
    run_id, output = proposal
    freeze = planning.freeze_optimization_plan
    def crash(*args, **kwargs):
        raise RuntimeError("simulated interruption before plan publication")
    monkeypatch.setattr(planning, "freeze_optimization_plan", crash)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        planning_output.materialize_optimization_plan(activity[0], run_id, output)
    first_rows = artifacts(activity[0], run_id)
    assert len(first_rows) == 1
    assert read_campaign(*activity).rounds[0].planRef is None
    monkeypatch.setattr(planning, "freeze_optimization_plan", freeze)
    ref = planning_output.materialize_optimization_plan(activity[0], run_id, output)
    assert artifacts(activity[0], run_id) == first_rows
    assert read_campaign(*activity).rounds[0].planRef == ref


def test_changed_output_cannot_replace_frozen_plan_or_add_candidate(activity, proposal):
    run_id, output = proposal
    ref = planning_output.materialize_optimization_plan(activity[0], run_id, output)
    before = artifacts(activity[0], run_id)
    for change in ({"prediction": "A different claim"},
        {"candidate": CudaCandidate(implementation="triton_row_softmax", numWarps=16)}):
        with pytest.raises(CampaignConflict, match="differs from the frozen plan"):
            planning_output.materialize_optimization_plan(activity[0], run_id, output.model_copy(update=change))
    assert artifacts(activity[0], run_id) == before
    assert read_campaign(*activity).rounds[0].planRef == ref


def test_concurrent_duplicate_completion_binds_one_plan(activity, proposal):
    run_id, output = proposal
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: planning_output.materialize_optimization_plan(
            activity[0], run_id, output), range(2)))
    assert results[0] == results[1]
    assert len(artifacts(activity[0], run_id)) == 1
    assert len(artifacts(activity[0], run_id, "optimization_plan")) == 1


def test_source_unavailable_blocks_before_candidate_publication(activity, proposal, monkeypatch):
    run_id, output = proposal
    def revoked(*args):
        raise CampaignConflict("Accepted knowledge source is no longer readable or accepted")
    monkeypatch.setattr(planning, "load_knowledge_snapshot", revoked)
    with pytest.raises(CampaignConflict, match="no longer readable"):
        planning_output.materialize_optimization_plan(activity[0], run_id, output)
    assert artifacts(activity[0], run_id) == []
    assert read_campaign(*activity).rounds[0].planRef is None
