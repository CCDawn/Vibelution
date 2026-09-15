"""Native decision Agent admission, receipt accounting and artifact recovery."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from core.chat.turn_journal import (
    EVENT_ASSISTANT_MESSAGE,
    EVENT_TURN_COMPLETED,
    append_turn_event,
)
from core.llm.client import LLMClient, model_invocation_receipt_context_scope
from core.research.operator_optimization.decision import (
    OperatorIterationDecisionArtifact,
    OperatorIterationDecisionProposal,
)
from core.research.operator_optimization.model_budget_contracts import (
    OperatorModelCallBudget,
)
from core.web.services import (
    agent_directory_service,
    chat_room_service,
    session_service,
)
from core.web.services.session.worker import (
    _model_invocation_receipt_context,
    _research_task_structured_output_contract,
)
from core.web.services.team_workflow.operator_optimization import (
    decision_authority as authority,
)
from core.web.services.team_workflow.operator_optimization import (
    decision_output,
    decision_task,
    evaluation,
    feedback,
)
from core.web.services.team_workflow.operator_optimization.store import (
    CampaignConflict,
    read_campaign,
    update_campaign,
)
from core.web.services.team_workflow.research_runtime import formal_write_runtime
from core.web.services.team_workflow.research_runtime.completion_dependency import (
    CompletionDependencyPending,
)
from core.web.services.team_workflow.research_runtime.receipt_persistence import (
    ReceiptPersistenceWorker,
)
from core.web.services.team_workflow.research_runtime.workflow_artifact_store import (
    list_workflow_artifacts,
)
from tests import test_operator_evaluation_feedback as fixtures
from tests._support.team_workflow.helpers import _use_fake_local_research_config
from tests._support.workflow_ledger_helpers import (
    build_attempt_record,
    build_command_record,
)
from tests.test_llm_client import make_config

activity = fixtures.activity
baseline_ready = fixtures.baseline_ready
ready = fixtures.ready
discussion_case = fixtures.discussion_case
handoff = fixtures.handoff
proposal = fixtures.proposal
prepared = fixtures.prepared


@pytest.fixture
def native_decision(activity, prepared, monkeypatch):
    _use_fake_local_research_config(monkeypatch)
    fixtures.measure(prepared, monkeypatch, ["failed", "fast"])
    evaluation.publish_evaluation(
        fixtures.node(prepared, "operator_evaluation"), prepared[1]
    )
    feedback.publish_feedback(
        fixtures.node(prepared, "optimization_feedback"), prepared[1]
    )
    run_id = prepared[0].run_id
    store = prepared[3]
    monkeypatch.setattr(formal_write_runtime, "_STORE", store)
    agent_id = agent_directory_service.create_agent_instance(
        display_name="Native decision Agent",
        llm_bindings={
            "dialogue": {"modelId": "houmo_qwen35_9b_agent"}
        },
    )["agentId"]
    budget = OperatorModelCallBudget(
        tokenLimit=20000,
        maxCalls=3,
        maxOutputTokensPerCall=512,
        prices=[{
            "modelRef": "default/qwen-alias",
            "priceVersion": "v1",
            "currency": "CNY",
            "inputPerMillion": 1,
            "outputPerMillion": 2,
        }],
    )
    campaign = read_campaign(*activity)
    update_campaign(
        *activity,
        expected_version=campaign.revision,
        command_key="decision-budget",
        command={},
        transform=lambda c: c.model_copy(
            update={"budget": c.budget.model_copy(update={"decision": budget})}
        ),
    )

    def seed(u):
        u.repository.insert_command(
            replace(
                build_command_record(
                    run_id=run_id, command_id="decision-command"
                ),
                idempotency_key="decision-command",
            )
        )
        u.repository.insert_attempt(
            build_attempt_record(
                "decision-node",
                run_id=run_id,
                node_id="optimization_decision",
                status="running",
                command_id="decision-command",
            )
        )
        snapshot = json.loads(u.repository.get_run(run_id).input_snapshot_json)
        snapshot["agentBindingSnapshot"] = [{
            "nodeId": "optimization_decision",
            "agentId": agent_id,
            "roleKey": "iteration_planner",
        }]
        u.repository.execute(
            "UPDATE workflow_runs SET input_snapshot_json=? WHERE run_id=?",
            (json.dumps(snapshot), run_id),
        )

    store.submit(seed, force_flush=True).result()
    monkeypatch.setattr(
        chat_room_service,
        "_resolve_chat_room_agent_llm",
        lambda agent: SimpleNamespace(
            model_ref="default/qwen-alias",
            provider_id="default",
            model="qwen-plus",
        ),
    )
    scheduled = []
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: scheduled.append(context),
    )
    monkeypatch.setattr(
        session_service,
        "_enqueue_direct_session_submit_kernel_trace",
        lambda **kwargs: None,
    )
    inputs = decision_output.decision_task_input(activity[0], run_id)
    assert inputs["actionPolicy"]["availableActions"] == [
        "discuss",
        "collect_knowledge",
        "plan_candidate",
        "retest",
        "stop",
    ]
    output = OperatorIterationDecisionProposal(
        inputHash=inputs["inputHash"],
        kind="discuss",
        reason="The failed first trial and faster retry justify one bounded iteration",
    )
    action = SimpleNamespace(
        run_id=run_id,
        node_run_id="decision-node",
        node_id="optimization_decision",
    )
    yield store, action, agent_id, scheduled, output
    for context in scheduled:
        sid = context.get("session_id") or context.get("conversation_id")
        if sid:
            session_service._set_session_running(sid, False)
            session_service._clear_session_turn_control(sid)


def _complete_model_turn(native_decision, handle, *, usage=True):
    _, _, _, scheduled, output = native_decision
    metadata = scheduled[0]["message_metadata"]
    context = _model_invocation_receipt_context(
        {"message_metadata": metadata},
        session_id=handle.session_id,
        turn_id=handle.turn_id,
    )
    schema = _research_task_structured_output_contract(
        {"message_metadata": metadata},
        session_id=handle.session_id,
        turn_id=handle.turn_id,
    )
    assert schema.name == "operator_iteration_decision_proposal_v2"
    text = output.model_dump_json()
    outcomes = []

    def backend(payload):
        chunk = {"choices": [{"delta": {"content": text}, "finish_reason": "stop"}]}
        if usage:
            chunk["usage"] = {
                "prompt_tokens": 100,
                "completion_tokens": 40,
                "total_tokens": 140,
            }
        return iter([chunk])

    client = LLMClient(config=make_config(), backend=backend)
    client._record_canonical_outcome = lambda outcome, **kwargs: outcomes.append(outcome)
    with model_invocation_receipt_context_scope(context):
        probe = client._receipt_context(
            {
                "sessionId": handle.session_id,
                "turnId": handle.turn_id,
                "invocationId": "decision-call",
            },
            SimpleNamespace(session_id=handle.session_id, turn_id=handle.turn_id),
        )
        assert probe is not None, context
        list(client.stream_events(
            [{"role": "user", "content": "Decide the next action"}],
            metadata={
                "sessionId": handle.session_id,
                "turnId": handle.turn_id,
                "invocationId": "decision-call",
            },
        ))
    receipt = json.loads(json.dumps(outcomes[-1].model_invocation_receipt))
    context["operatorInvocationReceiptCallback"](receipt)
    append_turn_event(
        session_service.PROJECT_ROOT,
        handle.session_id,
        handle.turn_id,
        EVENT_ASSISTANT_MESSAGE,
        payload={"content": text, "metadata": {"turnId": handle.turn_id}},
    )
    append_turn_event(
        session_service.PROJECT_ROOT,
        handle.session_id,
        handle.turn_id,
        EVENT_TURN_COMPLETED,
        status="completed",
    )
    session_service._set_session_running(handle.session_id, False)
    session_service._clear_session_turn_control(handle.session_id)
    return receipt


def test_native_decision_is_receipted_once_and_materializes_server_identity(
    native_decision, activity
):
    store, action, agent_id, scheduled, _ = native_decision
    handle = decision_task.create_decision_task(store, action, agent_id)
    assert decision_task.create_decision_task(store, action, agent_id) == handle
    assert len(scheduled) == 1
    with pytest.raises(decision_task.TurnNotReadyError):
        decision_task.execute_decision_task(store, action, handle)
    receipt = _complete_model_turn(native_decision, handle)
    assert receipt["scope"]["accountingKind"] == "operator_decision"
    assert receipt["metadata"]["outcomeKinds"] == [
        "optimization_iteration_decision"
    ]
    with pytest.raises(CompletionDependencyPending):
        decision_task.execute_decision_task(store, action, handle)
    assert ReceiptPersistenceWorker(store=store).run_once() == 1
    result = decision_task.execute_decision_task(store, action, handle)
    assert result.materialized_refs[0]["kind"] == "optimization_iteration_decision"
    rows = list_workflow_artifacts(
        activity[0],
        kind="optimization_iteration_decision",
        workflow_run_id=action.run_id,
    )
    assert len(rows) == 1
    payload = rows[0]["payload"]
    artifact = OperatorIterationDecisionArtifact.model_validate(payload)
    assert artifact.schemaVersion == 2
    assert artifact.decision.schemaVersion == 2
    assert artifact.decision.decidedBy == agent_id
    assert len(scheduled) == 1


def test_unknown_decision_cost_cannot_complete(native_decision):
    store, action, agent_id, _, _ = native_decision
    handle = decision_task.create_decision_task(store, action, agent_id)
    _complete_model_turn(native_decision, handle, usage=False)
    ReceiptPersistenceWorker(store=store).run_once()
    with pytest.raises(CampaignConflict, match="cost remains unknown"):
        decision_task.execute_decision_task(store, action, handle)


def test_decision_input_drift_is_rejected_before_another_call(
    native_decision, monkeypatch
):
    store, action, agent_id, scheduled, _ = native_decision
    handle = decision_task.create_decision_task(store, action, agent_id)
    original = decision_output.decision_task_input
    monkeypatch.setattr(
        authority,
        "decision_task_input",
        lambda *args: {**original(*args), "inputHash": "f" * 64},
    )
    metadata = scheduled[0]["message_metadata"]
    with pytest.raises(CampaignConflict, match="no longer valid"):
        context = _model_invocation_receipt_context(
            {"message_metadata": metadata},
            session_id=handle.session_id,
            turn_id=handle.turn_id,
        )
        context["invocationBudgetPreflight"](
            invocation_id="drift-call",
            estimated_input_tokens=10,
            max_output_tokens=10,
        )
