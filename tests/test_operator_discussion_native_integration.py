"""CPU integration: real dispatcher, Ledger, authority, room and LLM receipts.

Provider transport and pre-created participant sessions are controlled fixtures.
No first-stage artifacts or production model calls are required.
"""
from dataclasses import replace
from types import SimpleNamespace
import json
import time
import pytest

from tests.test_operator_optimization_budget import activity
from tests.test_operator_optimization_rounds import ready
from tests.test_operator_optimization_discussion import discussion_case
from tests.test_chat_room_service import _seed_chat_sessions
from tests.test_research_workflow_agent_anchor import _agent_action
from tests._support.workflow_ledger_helpers import (
    open_ledger_store, build_run_record, build_command_record, build_attempt_record, build_outbox_record,
)
from tests.test_llm_client import make_config


@pytest.mark.parametrize("viable", [True, False])
def test_native_dispatcher_discussion_receipt_wait_and_completion(activity, discussion_case, tmp_path, monkeypatch, viable):
    from core.llm.client import LLMClient, model_invocation_receipt_context_scope
    from core.research.operator_optimization.model_budget_contracts import OperatorDiscussionBudget
    from core.research.workflow.operator_optimization_definition import build_operator_definition
    from core.research.workflow.definition_registry import definition_identity
    from core.web.services import chat_room_service as rooms
    from core.web.services.team_workflow.operator_optimization import discussion, discussion_authority as authority, discussion_runtime
    from core.web.services.team_workflow.operator_optimization.store import update_campaign, read_campaign
    from core.web.services.team_workflow.research_runtime import formal_write_runtime
    from core.web.services.team_workflow.research_runtime.action_registry import ActionRegistry
    from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import AgentActionAdapter
    from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import AdapterDispatchWorker
    from core.web.services.team_workflow.research_runtime.real_domain_ports import RealDomainPorts
    from core.web.services.team_workflow.research_runtime.receipt_persistence import ReceiptPersistenceWorker, enqueue_question_model_invocation_receipt

    campaign, prepared, hypothesis = discussion_case
    policy = OperatorDiscussionBudget(tokenLimit=100000, maxOutputTokensPerCall=1000, maxCalls=2,
        prices=[dict(modelRef="default/qwen-alias", priceVersion="v1", currency="CNY",
            inputPerMillion=1, outputPerMillion=2)])
    update_campaign(*activity, expected_version=campaign.revision, command_key="discussion-policy",
        command={"fixture": "policy"}, transform=lambda c: c.model_copy(update={
            "budget": c.budget.model_copy(update={"discussion": policy})}))
    definition = definition_identity(build_operator_definition())
    snapshot = json.loads(prepared.input_snapshot_json)
    snapshot["agentBindingSnapshot"] = [{"nodeId": "optimization_discussion", "agentId": "planner",
        "roleKey": "experiment_planner"}]
    run = replace(build_run_record(run_id=prepared.run_id, team_id=activity[0], status="running",
        workflow_id="operator-optimization", workflow_version_id=definition.workflowVersionId),
        project_id=activity[1], question_id=snapshot["questionId"], input_snapshot_json=json.dumps(snapshot),
        active_node_id="optimization_discussion", structure_hash=definition.structureHash)
    action = replace(_agent_action(), run_id=run.run_id, node_run_id="node1", node_id="optimization_discussion")
    store = open_ledger_store(tmp_path / "integration.sqlite")
    now_ms = int(time.time() * 1000)
    try:
        def seed(u):
            u.repository.insert_run(run)
            u.repository.insert_command(build_command_record(command_id="cmd1", run_id=run.run_id))
            u.repository.insert_attempt(build_attempt_record("node1", run_id=run.run_id,
                node_id=action.node_id, command_id="cmd1", status="dispatching", started_at_ms=now_ms))
            u.repository.insert_outbox(replace(build_outbox_record(action_id="dispatch1", run_id=run.run_id),
                command_id="cmd1", node_run_id="node1", action_kind="adapter_dispatch",
                payload_json=json.dumps(action.to_dict()), created_at_ms=now_ms, available_at_ms=now_ms))
        store.submit(seed, force_flush=True).result()
        for module in (discussion, authority, discussion_runtime, formal_write_runtime):
            monkeypatch.setattr(module, "get_write_store", lambda: store)
        members = [{"agentId": "reviewer", "role": "reviewer"}, {"agentId": "planner", "role": "experiment_planner"}]
        monkeypatch.setattr(authority.team_service, "get_team", lambda _: {"members": members})
        monkeypatch.setattr(authority.agent_directory_service, "get_agent", lambda agent_id, **_: {"agentId": agent_id})
        route = dict(modelRef="default/qwen-alias", providerId="default", modelId="qwen-plus")
        monkeypatch.setattr(rooms, "_resolve_chat_room_agent_llm", lambda _: SimpleNamespace(
            model_ref=route["modelRef"], provider_id=route["providerId"], model=route["modelId"]))
        monkeypatch.setattr(rooms.work_run_store, "WORK_RUNS_DIR", tmp_path / "work_runs")
        _seed_chat_sessions(tmp_path)
        original_participant = rooms._participant_from_session
        def participant(summary, **kwargs):
            row = original_participant(summary, **kwargs)
            row["agentId"] = "reviewer" if row["sessionId"] == "session-alpha" else "planner"
            return row
        monkeypatch.setattr(rooms, "_participant_from_session", participant)
        monkeypatch.setattr(rooms, "_refresh_chat_room_round_participants", lambda participants, **_: participants)
        monkeypatch.setattr(discussion_runtime, "resolve_research_project_agent_session", lambda *a, **k: {
            "sessionId": "session-alpha" if k["agent_id"] == "reviewer" else "session-beta"})
        calls = []
        def runner(participant, prompt, context):
            turn = f"chat-room:{context['roundId']}:{participant['participantId']}"
            receipt_context = authority.speaker_receipt_context(participant, context,
                session_id=participant["sessionId"], turn_identity=turn, expected_model_route=route)
            payload = {"schemaVersion": 1, "contribution": "Bounded operator judgment", "result": None}
            if participant["agentId"] == "planner":
                payload["result"] = {"status": "selected" if viable else "no_viable_hypothesis",
                    "reason": "High ROI bounded change" if viable else "Insufficient evidence",
                    "hypothesis": hypothesis if viable else None}
            def backend(_):
                calls.append(participant["agentId"])
                return {"choices": [{"message": {"role": "assistant", "content": json.dumps(payload)},
                    "finish_reason": "stop"}], "usage": {"prompt_tokens": 30, "completion_tokens": 20, "total_tokens": 50}}
            client = LLMClient(config=make_config(), backend=backend)
            with model_invocation_receipt_context_scope(receipt_context):
                outcome = client.invoke_outcome([{"role": "user", "content": "test operator"}], metadata={
                    "sessionId": participant["sessionId"], "turnId": turn, "invocationId": "invoke-" + participant["agentId"]})
            enqueue_question_model_invocation_receipt(store, team_id=run.team_id, question_id=run.question_id,
                workflow_run_id=run.run_id, receipt=outcome.model_invocation_receipt)
            return {"status": "completed", "operatorDiscussionPayload": json.loads(outcome.final_text)}
        native_start = rooms.start_chat_room_round
        def start(*args, **kwargs):
            kwargs.update(background=False, agent_runner=runner)
            result = native_start(*args, **kwargs)
            assert result["rounds"][-1]["status"] == "completed", {k: result["rounds"][-1].get(k)
                for k in ("terminalReason", "summary", "messages")}
            return {"roundId": result["rounds"][-1]["roundId"]}
        monkeypatch.setattr(rooms, "start_chat_room_round", start)
        ports = RealDomainPorts(store)
        registry = ActionRegistry()
        registry.register(AgentActionAdapter(ports))
        worker = AdapterDispatchWorker(store=store, registry=registry, ports=ports)
        assert worker.run_once() == 1
        assert calls == ["reviewer", "planner"], store.submit(lambda u: u.repository.execute(
            "SELECT status,last_problem_json FROM outbox_actions WHERE action_id='dispatch1'").fetchone()).result()
        assert store.latest_attempt(run.run_id, action.node_id).status == "running", worker.last_problem
        assert ReceiptPersistenceWorker(store=store).run_once() == 2
        assert worker.run_once() == 1, store.submit(lambda u: u.repository.execute(
            "SELECT action_kind,status,last_problem_json FROM outbox_actions").fetchall()).result()
        assert store.latest_attempt(run.run_id, action.node_id).status == ("succeeded" if viable else "blocked"), store.get_run(run.run_id).blocked_problem_json
        assert calls == ["reviewer", "planner"]
        assert (read_campaign(*activity).rounds[0].hypothesisRef is not None) == viable
        result = discussion.read_discussion_result(run.team_id, run.run_id)
        assert result["discussion"]["provenance"]["costStatus"] == "settled"
        if viable:
            assert result["discussion"]["result"]["hypothesis"]["evidenceGaps"]
        else:
            assert read_campaign(*activity).status == "paused"
            assert json.loads(store.get_run(run.run_id).blocked_problem_json)["code"] == "operator_no_viable_hypothesis"
    finally:
        store.close()
