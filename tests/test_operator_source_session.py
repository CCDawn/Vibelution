"""Native source factory and worker accounting with isolated data and provider."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from core.llm.client import LLMClient, model_invocation_receipt_context_scope
from core.research.operator_optimization.contracts import CampaignBudget
from core.research.operator_optimization.knowledge import OperatorKnowledgeRequest
from core.web.services import (
    agent_directory_service,
    chat_room_service,
    session_service,
    team_service,
)
from core.web.services import team_workflow_orchestration_service as service
from core.web.services.team_workflow.operator_optimization import (
    knowledge_budget_runtime as budget_runtime,
)
from core.web.services.team_workflow.operator_optimization.knowledge import (
    knowledge_invocation_arguments,
)
from core.web.services.team_workflow.operator_optimization.source_authority import (
    build_operator_source_authority,
)
from core.web.services.team_workflow.research_runtime import formal_write_runtime
from core.web.services.team_workflow.research_runtime.knowledge_sideflow_service import (
    ensure_knowledge_invocation,
)
from core.web.services.team_workflow.research_runtime.real_domain_ports import (
    _create_real_agent_task,
)
from tests._support.team_workflow.helpers import (
    _use_fake_local_research_config,
    _use_tmp_project_root,
)
from tests._support.workflow_ledger_helpers import (
    build_attempt_record,
    build_command_record,
    build_run_record,
    open_ledger_store,
)
from tests.test_llm_client import make_config


@pytest.fixture
def native_source(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    finder = agent_directory_service.create_agent_instance(
        display_name="Operator sources"
    )
    team = team_service.create_team(
        name="Operator team",
        members=[{"agentId": finder["agentId"], "role": "source_finder"}],
    )
    team_id = team["teamId"]
    project = service.create_research_project(
        team_id, {"name": "Operator experiment", "topic": "softmax"}
    )["project"]
    service.activate_research_project(team_id, project["projectId"])
    store = open_ledger_store(tmp_path / "operator-ledger.sqlite")
    monkeypatch.setattr(formal_write_runtime, "_STORE", store)
    request = OperatorKnowledgeRequest(
        teamId=team_id,
        researchProjectId=project["projectId"],
        optimizationCampaignId="campaign1",
        roundId="round1",
        runId="parent1",
        hypothesisRef={
            "artifactId": "hyp1",
            "kind": "optimization_hypothesis",
            "sha256": "a" * 64,
        },
        observationRefs=[
            {"artifactId": "obs1", "kind": "operator_baseline", "sha256": "b" * 64}
        ],
        evidenceGaps=["Check vector load occupancy"],
        sourcePolicyVersion="2",
        sourcePolicy={},
        reuseRequirements={},
    )
    campaign = SimpleNamespace(
        authorizedBy="operator",
        budget=CampaignBudget(
            authorized=True,
            modelCostLimit=1,
            knowledge={
                "tokenLimit": 2000,
                "maxOutputTokensPerCall": 128,
                "maxCalls": 3,
                "prices": [
                    {
                        "modelRef": "default/qwen-alias",
                        "priceVersion": "v1",
                        "currency": "CNY",
                        "inputPerMillion": 1,
                        "outputPerMillion": 2,
                    }
                ],
            },
        ),
        rounds=[
            SimpleNamespace(
                runId="parent1", roundId="round1", hypothesisRef=request.hypothesisRef
            )
        ],
    )
    monkeypatch.setattr(budget_runtime, "read_campaign", lambda *args: campaign)

    def seed(u):
        u.repository.insert_run(
            replace(
                build_run_record(run_id="parent1"),
                team_id=team_id,
                project_id=project["projectId"],
                question_id="OPERATOR-SOFTMAX",
                workflow_id="operator-optimization",
                status="running",
                input_snapshot_json=json.dumps(
                    {
                        "researchObjectiveContract": {
                            "optimizationCampaignId": "campaign1",
                            "roundId": "round1",
                        }
                    }
                ),
            )
        )
        u.repository.insert_command(
            build_command_record(command_id="cmd1", run_id="parent1")
        )
        u.repository.insert_attempt(
            build_attempt_record(
                "parent-node",
                run_id="parent1",
                node_id="optimization_knowledge",
                command_id="cmd1",
                status="running",
            )
        )

    store.submit(seed, force_flush=True).result()
    result = ensure_knowledge_invocation(
        store,
        parent_run_id="parent1",
        parent_node_id="optimization_knowledge",
        parent_node_run_id="parent-node",
        parent_attempt=1,
        **knowledge_invocation_arguments(request, question_id="OPERATOR-SOFTMAX"),
    )
    run_id = result["childRunId"]
    attempt = store.latest_attempt(run_id, "source_finding")
    action = SimpleNamespace(
        run_id=run_id,
        node_run_id=attempt.node_run_id,
        node_id="source_finding",
        attempt=1,
    )
    binding = SimpleNamespace(agent_id=finder["agentId"], role_key="source_finder")

    def bind(u):
        snapshot = json.loads(u.repository.get_run(run_id).input_snapshot_json)
        snapshot["agentBindingSnapshot"] = [
            {
                "nodeId": "source_finding",
                "agentId": finder["agentId"],
                "roleKey": "source_finder",
            }
        ]
        u.repository.execute(
            "UPDATE workflow_runs SET input_snapshot_json=? WHERE run_id=?",
            (json.dumps(snapshot), run_id),
        )

    store.submit(bind, force_flush=True).result()
    budget_runtime.reserve_knowledge_budget(
        store, run_id=run_id, node_run_id=attempt.node_run_id
    )
    monkeypatch.setattr(
        chat_room_service,
        "_resolve_chat_room_agent_llm",
        lambda agent: SimpleNamespace(
            model_ref="default/qwen-alias", provider_id="default", model="qwen-plus"
        ),
    )
    submitted = []

    def submit(session_id, content, **kwargs):
        submitted.append((session_id, kwargs))
        return {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn1",
            "status": "running",
        }

    monkeypatch.setattr(session_service, "submit_session_message", submit)
    yield store, action, binding, submitted
    store.close()


def test_native_source_factory_worker_and_stream_receipt(native_source, monkeypatch):
    from core.web.services.session.stream_capture import (
        _persist_challenge_model_invocation_receipt,
    )
    from core.web.services.session.worker import _model_invocation_receipt_context
    from core.web.services.team_workflow.operator_optimization.model_budget import (
        settle_model_budget,
    )
    from core.web.services.team_workflow.research_runtime import budget_window_resolver
    from core.web.services.team_workflow.source_collection.stage_session import (
        _read_source_collection_stage_session_task_record,
    )

    store, action, binding, submitted = native_source
    snapshot = json.loads(store.get_run(action.run_id).input_snapshot_json)
    handle = _create_real_agent_task(action, binding, snapshot, store=store)
    metadata = submitted[0][1]["message_metadata"]
    task = _read_source_collection_stage_session_task_record(
        snapshot["teamId"], handle.task_id
    )
    assert task["challengeTaskContract"] == {}
    assert task["operatorSourceAuthority"]["parentRunId"] == "parent1"
    context = _model_invocation_receipt_context(
        {"message_metadata": metadata},
        session_id=handle.session_id,
        turn_id=handle.turn_id,
    )
    assert context["operatorInvocationBinding"]["formalNodeRunId"] == action.node_run_id
    calls, outcomes = [], []

    def backend(payload):
        calls.append(payload)
        return iter(
            [
                {
                    "choices": [
                        {"delta": {"content": "evidence"}, "finish_reason": "stop"}
                    ],
                    "usage": {
                        "prompt_tokens": 13,
                        "completion_tokens": 8,
                        "total_tokens": 21,
                    },
                }
            ]
        )

    client = LLMClient(config=make_config(), backend=backend)
    client._record_canonical_outcome = lambda outcome, **kwargs: outcomes.append(
        outcome
    )
    with model_invocation_receipt_context_scope(context):
        list(
            client.stream_events(
                [{"role": "user", "content": "find evidence"}],
                metadata={
                    "sessionId": handle.session_id,
                    "turnId": handle.turn_id,
                    "invocationId": "source-call-1",
                },
            )
        )
    receipt = json.loads(json.dumps(outcomes[-1].model_invocation_receipt))
    assert len(calls) == 1
    monkeypatch.setattr(
        budget_window_resolver, "injected_research_runtime_store", lambda: store
    )
    capture = SimpleNamespace(
        model_invocation_receipt_context=context, challenge_receipt_failure_code=""
    )
    assert _persist_challenge_model_invocation_receipt(
        capture, SimpleNamespace(model_invocation_receipt=receipt)
    )
    budget = settle_model_budget(
        store, reservation={"reservationId": "reservation-" + action.node_run_id}
    )
    assert budget["costStatus"] == "settled"
    assert float(budget["actualAmount"]) == pytest.approx(0.000029)
    from core.web.services.team_workflow.research_runtime import (
        real_domain_ports as ports_module,
    )
    from core.web.services.team_workflow.research_runtime.completion_dependency import (
        CompletionDependencyPending,
    )
    from core.web.services.team_workflow.research_runtime.domain_ports import (
        AgentTurnResult,
    )

    ports = ports_module.RealDomainPorts.__new__(ports_module.RealDomainPorts)
    ports._store = store
    monkeypatch.setattr(ports, "required_artifact_kinds", lambda action: ())
    monkeypatch.setattr(
        ports_module, "_bounded_agent_node_can_complete", lambda *args, **kwargs: False
    )
    completed = AgentTurnResult(materialized_refs=(), handle=handle)
    from core.web.services.team_workflow.research_runtime import agent_turn_completion

    monkeypatch.setattr(
        agent_turn_completion, "complete_agent_turn_outputs", lambda **kwargs: completed
    )
    with pytest.raises(CompletionDependencyPending, match="receipt delivery"):
        ports.execute_agent_turn(action=action, handle=handle)
    store.submit(
        lambda u: u.repository.execute(
            "UPDATE outbox_actions SET status='succeeded' WHERE run_id=? AND action_kind='reconcile'",
            (action.run_id,),
        ),
        force_flush=True,
    ).result()
    assert ports.execute_agent_turn(action=action, handle=handle) == completed
    replay = _create_real_agent_task(
        action,
        binding,
        json.loads(store.get_run(action.run_id).input_snapshot_json),
        store=store,
    )
    assert replay.task_id == handle.task_id
    assert len(submitted) == 1


def test_source_route_is_frozen_and_wrong_agent_rejected(native_source, monkeypatch):
    store, action, binding, _ = native_source
    from core.web.services.team_workflow.research_runtime.real_readiness_context import (
        RealDomainReadinessContext,
    )

    run = store.get_run(action.run_id)
    question = RealDomainReadinessContext(store).question_snapshot(
        run.team_id, run.question_id, run_id=run.run_id
    )
    assert question["operatorKnowledgeRequest"]["runId"] == "parent1"
    assert question["question"] == "Check vector load occupancy"
    authority = build_operator_source_authority(
        store, action, agent_id=binding.agent_id
    )
    monkeypatch.setattr(
        chat_room_service,
        "_resolve_chat_room_agent_llm",
        lambda agent: pytest.fail("replay must not read live route"),
    )
    assert (
        build_operator_source_authority(store, action, agent_id=binding.agent_id)
        == authority
    )
    with pytest.raises(budget_runtime.CampaignConflict, match="frozen binding"):
        build_operator_source_authority(store, action, agent_id="other")


def test_operator_task_rejects_public_start_and_forged_task_locator(
    native_source, monkeypatch
):
    from core.web.services.session.worker import _model_invocation_receipt_context
    from core.web.services.team_workflow.source_collection.stage_session import (
        start_source_collection_stage_session_task,
    )

    store, action, binding, submitted = native_source
    snapshot = json.loads(store.get_run(action.run_id).input_snapshot_json)
    handle = _create_real_agent_task(action, binding, snapshot, store=store)
    with pytest.raises(service.TeamWorkflowOrchestrationError, match="server-frozen"):
        start_source_collection_stage_session_task(
            snapshot["teamId"],
            snapshot["sourceCollectionRunId"],
            {
                "stageId": "finding",
                "agentId": binding.agent_id,
                "agentRole": binding.role_key,
            },
        )
    metadata = submitted[0][1]["message_metadata"]
    with pytest.raises(ValueError, match="canonical task"):
        _model_invocation_receipt_context(
            {"message_metadata": metadata},
            session_id="another-session",
            turn_id=handle.turn_id,
        )
    with pytest.raises(ValueError, match="canonical task"):
        _model_invocation_receipt_context(
            {"message_metadata": metadata},
            session_id=handle.session_id,
            turn_id="another-turn",
        )
    continued = _model_invocation_receipt_context(
        {"message_metadata": {**metadata, "continuationOfTurnId": handle.turn_id}},
        session_id=handle.session_id,
        turn_id="continuation-turn",
    )
    assert continued["operatorInvocationBinding"]["turnId"] == "continuation-turn"
    monkeypatch.setattr(formal_write_runtime, "_STORE", None)
    # Extraction has no first-stage problem-artifact read that could mask the
    # missing model authority; it must reject before a new Session is created.
    with pytest.raises(service.TeamWorkflowOrchestrationError, match="Workflow Ledger"):
        start_source_collection_stage_session_task(
            snapshot["teamId"],
            snapshot["sourceCollectionRunId"],
            {
                "stageId": "extraction",
                "agentId": binding.agent_id,
                "agentRole": "source_extractor",
            },
        )
    assert len(submitted) == 1


def test_new_child_consumption_requires_every_source_cost_settled(native_source):
    from core.web.services.team_workflow.operator_optimization.knowledge import (
        child_costs_settled,
    )
    from core.web.services.team_workflow.operator_optimization.model_budget import (
        record_model_invocation_usage,
        settle_model_budget,
    )

    store, action, _, _ = native_source
    first = store.latest_attempt(action.run_id, "source_finding")
    last_reservation = None
    for index, node_id in enumerate(sorted(budget_runtime.SOURCE_NODES)):
        attempt = store.latest_attempt(action.run_id, node_id)
        if attempt is None:
            attempt = build_attempt_record(
                f"cost-node-{index}",
                run_id=action.run_id,
                node_id=node_id,
                status="running",
                command_id=first.command_id,
            )
            store.submit(
                lambda u, attempt=attempt: u.repository.insert_attempt(attempt),
                force_flush=True,
            ).result()
        reservation = budget_runtime.reserve_knowledge_budget(
            store, run_id=action.run_id, node_run_id=attempt.node_run_id
        )
        record_model_invocation_usage(
            store,
            reservation=reservation,
            invocation_id=f"cost-call-{index}",
            model_ref="default/qwen-alias",
            input_tokens=13,
            output_tokens=8,
            usage_known=True,
        )
        if last_reservation is not None:
            settle_model_budget(store, reservation=last_reservation)
        last_reservation = reservation

        def finish(u, node_run_id=attempt.node_run_id):
            if u.repository.get_attempt(node_run_id).status != "running":
                u.repository.update_attempt_status(node_run_id, "running", 99)
            u.repository.update_attempt_status(node_run_id, "succeeded", 100)

        store.submit(finish, force_flush=True).result()
    store.submit(
        lambda u: u.repository.update_run_status(
            action.run_id, store.get_run(action.run_id).team_id, "succeeded", 101
        ),
        force_flush=True,
    ).result()
    assert not child_costs_settled(store, action.run_id)
    settle_model_budget(store, reservation=last_reservation)
    assert child_costs_settled(store, action.run_id)
