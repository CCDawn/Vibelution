"""Native planning admission, journal identity and controlled provider receipts."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from core.chat.turn_journal import (
    append_turn_event,
    EVENT_ASSISTANT_MESSAGE,
    EVENT_TURN_COMPLETED,
)
from core.llm.client import LLMClient, model_invocation_receipt_context_scope
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
    planning_authority as authority,
    planning_task as planner,
)
from core.web.services.team_workflow.operator_optimization.store import (
    read_campaign,
    update_campaign,
    CampaignConflict,
)
from core.web.services.team_workflow.research_runtime import formal_write_runtime
from core.web.services.team_workflow.research_runtime.completion_dependency import (
    CompletionDependencyPending,
)
from core.web.services.team_workflow.research_runtime.receipt_persistence import (
    ReceiptPersistenceWorker,
)
from tests import test_operator_planning as fixtures
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


@pytest.fixture
def native(activity, handoff, proposal, monkeypatch):
    _use_fake_local_research_config(monkeypatch)
    run_id, output = proposal
    store = handoff[2]
    monkeypatch.setattr(formal_write_runtime, "_STORE", store)
    agent = agent_directory_service.create_agent_instance(
        display_name="Native planner",
        llm_bindings={
            "dialogue": {"modelId": "houmo_qwen35_9b_agent"}
        },
    )
    agent_id = agent["agentId"]
    budget = OperatorModelCallBudget(
        tokenLimit=20000,
        maxCalls=3,
        maxOutputTokensPerCall=2048,
        prices=[
            {
                "modelRef": "default/qwen-alias",
                "priceVersion": "v1",
                "currency": "CNY",
                "inputPerMillion": 1,
                "outputPerMillion": 2,
            }
        ],
    )
    campaign = read_campaign(*activity)
    update_campaign(
        *activity,
        expected_version=campaign.revision,
        command_key="planning-budget",
        command={},
        transform=lambda c: c.model_copy(
            update={"budget": c.budget.model_copy(update={"planning": budget})}
        ),
    )

    def seed(u):
        u.repository.insert_command(
            build_command_record(run_id=run_id, command_id="plan-command")
        )
        u.repository.insert_attempt(
            build_attempt_record(
                "plan-node",
                run_id=run_id,
                node_id="optimization_plan",
                status="running",
                command_id="plan-command",
            )
        )
        snapshot = json.loads(u.repository.get_run(run_id).input_snapshot_json)
        snapshot["agentBindingSnapshot"] = [
            {
                "nodeId": "optimization_plan",
                "agentId": agent_id,
                "roleKey": "experiment_planner",
            }
        ]
        u.repository.execute(
            "UPDATE workflow_runs SET input_snapshot_json=? WHERE run_id=?",
            (json.dumps(snapshot), run_id),
        )

    store.submit(seed, force_flush=True).result()
    monkeypatch.setattr(
        chat_room_service,
        "_resolve_chat_room_agent_llm",
        lambda agent: SimpleNamespace(
            model_ref="default/qwen-alias", provider_id="default", model="qwen-plus"
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
    action = SimpleNamespace(
        run_id=run_id, node_run_id="plan-node", node_id="optimization_plan"
    )
    yield store, action, agent_id, scheduled, output
    for context in scheduled:
        sid = context.get("session_id") or context.get("conversation_id")
        if sid:
            session_service._set_session_running(sid, False)
            session_service._clear_session_turn_control(sid)


def model_output(native, handle, *, usage=True):
    store, action, _, scheduled, output = native
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
    assert schema.name == "operator_plan_proposal_v1"
    outcomes = []
    text = output.model_dump_json()

    def backend(payload):
        chunk = {"choices": [{"delta": {"content": text}, "finish_reason": "stop"}]}
        if usage:
            chunk["usage"] = {
                "prompt_tokens": 100,
                "completion_tokens": 80,
                "total_tokens": 180,
            }
        return iter([chunk])

    client = LLMClient(config=make_config(), backend=backend)
    client._record_canonical_outcome = lambda outcome, **kwargs: outcomes.append(
        outcome
    )
    with model_invocation_receipt_context_scope(context):
        list(
            client.stream_events(
                [{"role": "user", "content": "Plan the experiment"}],
                metadata={
                    "sessionId": handle.session_id,
                    "turnId": handle.turn_id,
                    "invocationId": "plan-call",
                },
            )
        )
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
    return receipt, context


def test_native_submit_receipt_delivery_and_plan_recovery(native, activity):
    store, action, agent, scheduled, _ = native
    handle = planner.create_planning_task(store, action, agent)
    assert planner.create_planning_task(store, action, agent) == handle
    assert len(scheduled) == 1
    task = store.read(
        lambda repo: authority.read_planning_task(
            repo, action.run_id, action.node_run_id
        )
    )
    assert task["turnId"] == handle.turn_id
    with pytest.raises(planner.TurnNotReadyError):
        planner.execute_planning_task(store, action, handle)
    receipt, _ = model_output(native, handle)
    assert receipt["scope"]["accountingKind"] == "operator_planning"
    assert "participantId" not in receipt["scope"]
    with pytest.raises(CompletionDependencyPending, match="not delivered"):
        planner.execute_planning_task(store, action, handle)
    assert ReceiptPersistenceWorker(store=store).run_once() == 1
    result = planner.execute_planning_task(store, action, handle)
    assert result.materialized_refs[0]["kind"] == "optimization_plan"
    assert (
        planner.execute_planning_task(store, action, handle).materialized_refs
        == result.materialized_refs
    )
    assert len(scheduled) == 1
    assert read_campaign(*activity).rounds[0].planRef is not None


def test_unknown_usage_never_completes_plan(native, activity):
    store, action, agent, _, _ = native
    handle = planner.create_planning_task(store, action, agent)
    model_output(native, handle, usage=False)
    ReceiptPersistenceWorker(store=store).run_once()
    with pytest.raises(CampaignConflict, match="cost remains unknown"):
        planner.execute_planning_task(store, action, handle)
    assert read_campaign(*activity).rounds[0].planRef is None


def test_canonical_task_rejects_cross_turn_and_stale_attempt(native):
    store, action, agent, scheduled, _ = native
    handle = planner.create_planning_task(store, action, agent)
    metadata = scheduled[0]["message_metadata"]
    with pytest.raises(CampaignConflict, match="locator differs"):
        _model_invocation_receipt_context(
            {"message_metadata": metadata},
            session_id=handle.session_id,
            turn_id="other-turn",
        )
    store.submit(
        lambda u: u.repository.execute(
            "UPDATE node_attempts SET finished_at_ms=123 WHERE node_run_id=?",
            (action.node_run_id,),
        ),
        force_flush=True,
    ).result()
    with pytest.raises(CampaignConflict, match="no longer active"):
        planner.execute_planning_task(store, action, handle)


def test_missing_planning_budget_does_not_submit(native, activity):
    store, action, agent, scheduled, _ = native
    campaign = read_campaign(*activity)
    update_campaign(
        *activity,
        expected_version=campaign.revision,
        command_key="remove-planning",
        command={},
        transform=lambda c: c.model_copy(
            update={"budget": c.budget.model_copy(update={"planning": None})}
        ),
    )
    with pytest.raises(CampaignConflict, match="explicit authorized"):
        planner.create_planning_task(store, action, agent)
    assert scheduled == []


def test_submit_crash_recovers_journal_without_second_turn(native, monkeypatch):
    store, action, agent, scheduled, _ = native
    update = planner._update_task

    def interrupt(store, task, changes):
        if "turnId" in changes:
            raise RuntimeError("interrupted after native submit")
        return update(store, task, changes)

    monkeypatch.setattr(planner, "_update_task", interrupt)
    with pytest.raises(RuntimeError, match="after native submit"):
        planner.create_planning_task(store, action, agent)
    assert len(scheduled) == 1
    monkeypatch.setattr(planner, "_update_task", update)
    handle = planner.create_planning_task(store, action, agent)
    assert handle.turn_id == scheduled[0]["turn_id"]
    assert len(scheduled) == 1


def test_worker_can_bind_turn_before_submit_returns(native, monkeypatch):
    store, action, agent, scheduled, _ = native
    bound = []

    def schedule(context):
        scheduled.append(context)
        bound.append(
            _model_invocation_receipt_context(
                context,
                session_id=context["session_id"],
                turn_id=context["turn_id"],
            )
        )

    monkeypatch.setattr(session_service, "_schedule_session_turn", schedule)
    handle = planner.create_planning_task(store, action, agent)
    assert bound[0]["operatorInvocationBinding"]["turnId"] == handle.turn_id


def test_changed_output_has_no_matching_receipt(native, activity, monkeypatch):
    store, action, agent, _, output = native
    handle = planner.create_planning_task(store, action, agent)
    model_output(native, handle)
    ReceiptPersistenceWorker(store=store).run_once()
    snapshot = session_service.get_session_turn_completion_snapshot(
        handle.session_id, handle.turn_id
    )
    snapshot["assistantText"] = output.model_copy(
        update={"prediction": "unreceipted modification"}
    ).model_dump_json()
    monkeypatch.setattr(
        session_service, "get_session_turn_completion_snapshot", lambda *args: snapshot
    )
    with pytest.raises(CampaignConflict, match="no matching delivered"):
        planner.execute_planning_task(store, action, handle)
    assert read_campaign(*activity).rounds[0].planRef is None


def test_retry_requires_terminal_predecessor_and_gets_new_session(native):
    from core.chat.turn_journal import EVENT_TURN_FAILED

    store, action, agent, scheduled, _ = native
    first = planner.create_planning_task(store, action, agent)

    def retry(u):
        u.repository.execute(
            "UPDATE node_attempts SET status='failed', finished_at_ms=123 WHERE node_run_id=?",
            (action.node_run_id,),
        )
        u.repository.insert_attempt(
            replace(
                build_attempt_record(
                    "plan-retry",
                    run_id=action.run_id,
                    node_id="optimization_plan",
                    status="running",
                    command_id="plan-command",
                ),
                attempt=2,
            )
        )

    store.submit(retry, force_flush=True).result()
    next_action = SimpleNamespace(
        run_id=action.run_id, node_run_id="plan-retry", node_id="optimization_plan"
    )
    with pytest.raises(CampaignConflict, match="must finish"):
        planner.create_planning_task(store, next_action, agent)
    append_turn_event(
        session_service.PROJECT_ROOT,
        first.session_id,
        first.turn_id,
        EVENT_TURN_FAILED,
        status="failed",
    )
    session_service._set_session_running(first.session_id, False)
    session_service._clear_session_turn_control(first.session_id)
    second = planner.create_planning_task(store, next_action, agent)
    assert second.session_id != first.session_id
    assert second.turn_id != first.turn_id
    assert len(scheduled) == 2


def test_real_adapter_resumes_same_action_after_receipt_delivery(native, monkeypatch):
    from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import (
        AgentActionAdapter,
    )
    from core.web.services.team_workflow.research_runtime.real_domain_ports import (
        RealDomainPorts,
    )
    from core.web.services.team_workflow.research_runtime.challenge_turn_policy import (
        challenge_task_deadline_scope,
    )
    from core.web.services.team_workflow.research_runtime.completion_dependency import (
        COMPLETION_PENDING,
    )
    from core.web.services.team_workflow.research_runtime.domain_ports import (
        AgentTaskHandle,
    )
    from tests.test_research_workflow_agent_anchor import _agent_action

    store, simple_action, _, scheduled, _ = native
    action = replace(
        _agent_action(),
        run_id=simple_action.run_id,
        node_id="optimization_plan",
        node_run_id=simple_action.node_run_id,
        input_snapshot_hash="",
    )
    ports = RealDomainPorts(store)
    adapter = AgentActionAdapter(ports)
    with pytest.raises(planner.TurnNotReadyError):
        adapter.execute(action)
    task = store.read(
        lambda repo: authority.read_planning_task(
            repo, action.run_id, action.node_run_id
        )
    )
    handle = AgentTaskHandle(task["sessionId"], 1, task["taskId"], task["turnId"])
    model_output(native, handle)
    with pytest.raises(CompletionDependencyPending) as waiting:
        adapter.execute(action)
    resume = waiting.value.resume
    assert resume["actionId"] == action.action_id
    ReceiptPersistenceWorker(store=store).run_once()

    def forbidden(**kwargs):
        raise AssertionError("Completion recovery must not create another task")

    monkeypatch.setattr(ports, "create_agent_task", forbidden)
    with challenge_task_deadline_scope(
        0, resume_problem={"code": COMPLETION_PENDING, "completionResume": resume}
    ):
        result = adapter.execute(action)
    assert result.outcome == "succeeded"
    assert result.anchor["turnId"] == handle.turn_id
    assert len(scheduled) == 1
    assert adapter.verify(action, result).outcome == "succeeded"
