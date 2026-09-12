"""Controlled provider + real child Ledger accounting, without paid calls."""
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from core.llm.client import LLMClient, model_invocation_receipt_context_scope
from core.llm.errors import LLMError
from core.research.operator_optimization.contracts import CampaignBudget
from core.research.operator_optimization.knowledge import OperatorKnowledgeRequest
from core.research.operator_optimization.knowledge_invocation import OperatorKnowledgeInvocationBinding
from core.web.services.team_workflow.operator_optimization import knowledge_budget_runtime as runtime
from core.web.services.team_workflow.operator_optimization.knowledge import knowledge_invocation_arguments
from core.web.services.team_workflow.operator_optimization.model_budget import settle_model_budget
from core.web.services.team_workflow.research_runtime.knowledge_sideflow_service import ensure_knowledge_invocation
from core.web.services.team_workflow.research_runtime.receipt_persistence import enqueue_question_model_invocation_receipt
from tests._support.workflow_ledger_helpers import open_ledger_store, build_run_record, build_command_record, build_attempt_record
from tests.test_llm_client import make_config


@pytest.fixture
def child_case(tmp_path, monkeypatch):
    store = open_ledger_store(tmp_path / "ledger.sqlite")
    request = OperatorKnowledgeRequest(teamId="team1", researchProjectId="project1",
        optimizationCampaignId="campaign1", roundId="round1", runId="parent1",
        hypothesisRef={"artifactId": "hyp1", "kind": "optimization_hypothesis", "sha256": "a" * 64},
        observationRefs=[{"artifactId": "obs1", "kind": "operator_baseline", "sha256": "b" * 64}],
        evidenceGaps=["Check vector load occupancy"], sourcePolicyVersion="2", sourcePolicy={}, reuseRequirements={})
    budget = CampaignBudget(authorized=True, modelCostLimit=1, knowledge={
        "tokenLimit": 2000, "maxOutputTokensPerCall": 128, "maxCalls": 3,
        "prices": [{"modelRef": "default/qwen-alias", "priceVersion": "v1", "currency": "CNY",
                    "inputPerMillion": 1, "outputPerMillion": 2}]})
    campaign = SimpleNamespace(authorizedBy="operator", budget=budget,
        rounds=[SimpleNamespace(runId="parent1", roundId="round1", hypothesisRef=request.hypothesisRef)])
    monkeypatch.setattr(runtime, "read_campaign", lambda *args: campaign)
    def seed(u):
        u.repository.insert_run(replace(build_run_record(run_id="parent1"), team_id="team1", project_id="project1",
            question_id="OPERATOR-SOFTMAX", workflow_id="operator-optimization", status="running",
            input_snapshot_json=json.dumps({"researchObjectiveContract": {"optimizationCampaignId": "campaign1", "roundId": "round1"}})))
        u.repository.insert_command(build_command_record(command_id="cmd1", run_id="parent1"))
        u.repository.insert_attempt(build_attempt_record("parent-node", run_id="parent1",
            node_id="optimization_knowledge", command_id="cmd1", status="running"))
    store.submit(seed, force_flush=True).result()
    result = ensure_knowledge_invocation(store, parent_run_id="parent1", parent_node_id="optimization_knowledge",
        parent_node_run_id="parent-node", parent_attempt=1,
        **knowledge_invocation_arguments(request, question_id="OPERATOR-SOFTMAX"))
    child = store.get_run(result["childRunId"])
    attempt = store.latest_attempt(child.run_id, "source_finding")
    binding = OperatorKnowledgeInvocationBinding(teamId="team1", researchProjectId="project1",
        optimizationCampaignId="campaign1", roundId="round1", parentRunId="parent1", parentNodeRunId="parent-node",
        knowledgeInvocationId=result["invocation"].invocation_id, requestHash=result["invocation"].request_hash,
        workflowRunId=child.run_id, workflowVersionId=child.workflow_version_id,
        formalNodeId="source_finding", formalNodeRunId=attempt.node_run_id, formalNodeAttempt=attempt.attempt,
        sessionId="session1", taskId="task1", turnId="turn1", modelPolicySha256="a" * 64)
    yield store, binding, campaign
    store.close()


def context_for(store, binding):
    runtime.reserve_knowledge_budget(store, run_id=binding.workflowRunId, node_run_id=binding.formalNodeRunId)
    return runtime.knowledge_receipt_context(store, binding, expected_model_route={
        "modelRef": "default/qwen-alias", "providerId": "default", "modelId": "qwen-plus"})


def invoke(context, *, fail_first=False, stream=False):
    calls = []
    def backend(payload):
        calls.append(payload)
        if fail_first and len(calls) == 1:
            raise LLMError("server_error", "temporary", retryable=True)
        if stream:
            return iter([{"choices": [{"delta": {"content": "evidence"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 13, "completion_tokens": 8, "total_tokens": 21}}])
        return {"choices": [{"message": {"role": "assistant", "content": "evidence"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 13, "completion_tokens": 8, "total_tokens": 21}}
    client = LLMClient(config=make_config(**{"llm.profiles.primary.retry_policy.max_attempts": 2}), backend=backend)
    with model_invocation_receipt_context_scope(context):
        metadata = {"sessionId": "session1", "turnId": "turn1", "invocationId": "inv1"}
        if stream:
            outcomes = []
            client._record_canonical_outcome = lambda outcome, **kwargs: outcomes.append(outcome)
            list(client.stream_events([{"role": "user", "content": "find evidence"}], metadata=metadata))
            outcome = outcomes[-1]
        else:
            outcome = client.invoke_outcome([{"role": "user", "content": "find evidence"}], metadata=metadata)
    return json.loads(json.dumps(outcome.model_invocation_receipt)), calls


@pytest.mark.parametrize("stream", [False, True])
def test_child_receipt_retains_identity_and_charges_campaign_once(child_case, stream):
    store, binding, _ = child_case
    receipt, calls = invoke(context_for(store, binding), stream=stream)
    assert len(calls) == 1
    assert receipt["scope"]["workflowId"] == "challenge-cup-knowledge-sideflow"
    assert receipt["scope"]["formalNodeId"] == "source_finding"
    assert tuple(receipt["metadata"]["outcomeKinds"]) == ("source_evidence",)
    assert "participantId" not in receipt["scope"]
    args = dict(team_id="team1", question_id="OPERATOR-SOFTMAX", workflow_run_id=binding.workflowRunId, receipt=receipt)
    assert enqueue_question_model_invocation_receipt(store, **args)["created"]
    assert not enqueue_question_model_invocation_receipt(store, **args)["created"]
    result = settle_model_budget(store, reservation={"reservationId": "reservation-" + binding.formalNodeRunId})
    assert result["status"] == "settled"
    assert float(result["actualAmount"]) == pytest.approx(0.000029)
    assert not enqueue_question_model_invocation_receipt(store, **args)["created"]


@pytest.mark.parametrize("stream", [False, True])
def test_failed_child_attempt_keeps_unknown_charge_and_retry_receipt(child_case, monkeypatch, stream):
    store, binding, _ = child_case
    monkeypatch.setattr("core.llm.client._sleep_with_llm_cancel_check", lambda _: None)
    context = context_for(store, binding)
    receipt, calls = invoke(context, fail_first=True, stream=stream)
    assert len(calls) == 2
    assert receipt["evidenceLocator"]["invocationId"] == "inv1:attempt-2"
    context["operatorInvocationReceiptCallback"](receipt)
    result = settle_model_budget(store, reservation={"reservationId": "reservation-" + binding.formalNodeRunId})
    assert result["costStatus"] == "unsettled"
    assert result["callsUsed"] == 2
    from core.web.services.team_workflow.research_runtime.receipt_persistence import RECEIPT_PERSISTENCE_OUTBOX_KIND
    rows = store.read(lambda repo: repo.execute("SELECT payload_json FROM outbox_actions WHERE action_kind=?", (RECEIPT_PERSISTENCE_OUTBOX_KIND,)).fetchall())
    assert len(rows) == 2


@pytest.mark.parametrize("field,value", [("optimizationCampaignId", "other"), ("requestHash", "b" * 64), ("parentRunId", "other")])
def test_receipt_cannot_charge_another_campaign_or_request(child_case, field, value):
    store, binding, _ = child_case
    receipt, _ = invoke(context_for(store, binding))
    receipt["scope"][field] = value
    with pytest.raises(runtime.CampaignConflict):
        enqueue_question_model_invocation_receipt(store, team_id="team1", question_id="OPERATOR-SOFTMAX",
            workflow_run_id=binding.workflowRunId, receipt=receipt)


def test_real_domain_reservation_rejects_missing_knowledge_budget(child_case):
    from core.research.workflow.models import ActorKind
    from core.web.services.team_workflow.research_runtime.real_domain_ports import RealDomainPorts
    store, binding, campaign = child_case
    campaign.budget = campaign.budget.model_copy(update={"knowledge": None})
    ports = RealDomainPorts.__new__(RealDomainPorts)
    ports._store = store
    action = SimpleNamespace(run_id=binding.workflowRunId, node_run_id=binding.formalNodeRunId,
        node_id=binding.formalNodeId, actor_kind=ActorKind.AGENT)
    with pytest.raises(runtime.CampaignConflict, match="explicit authorized budget"):
        ports.reserve_budget(action=action, estimate_tokens=2000000)


def test_real_domain_routes_child_to_campaign_reservation(child_case):
    from core.research.workflow.models import ActorKind
    from core.web.services.team_workflow.research_runtime.real_domain_ports import RealDomainPorts
    store, binding, _ = child_case
    ports = RealDomainPorts.__new__(RealDomainPorts)
    ports._store = store
    action = SimpleNamespace(run_id=binding.workflowRunId, node_run_id=binding.formalNodeRunId,
        node_id=binding.formalNodeId, actor_kind=ActorKind.AGENT)
    first = ports.reserve_budget(action=action, estimate_tokens=2000000)
    second = ports.reserve_budget(action=action, estimate_tokens=2000000)
    assert first["reservationId"] == second["reservationId"]
    assert first["optimizationCampaignId"] == "campaign1"
    assert first["tokenLimit"] == 2000
    assert second["idempotent"] is True


def test_operator_child_receipt_cannot_fall_back_to_generic_tokens(child_case):
    store, binding, _ = child_case
    receipt, _ = invoke(context_for(store, binding))
    del receipt["scope"]["accountingKind"]
    with pytest.raises(ValueError, match="accounting identity is missing"):
        enqueue_question_model_invocation_receipt(store, team_id="team1", question_id="OPERATOR-SOFTMAX",
            workflow_run_id=binding.workflowRunId, receipt=receipt)
