from datetime import datetime, timedelta, timezone

import pytest

from core.agent_plugins.virtual_human_life.service import (
    BindingDisabledError,
    VirtualHumanLifeService,
)


@pytest.fixture
def world(tmp_path):
    now = [datetime(2026, 10, 13, 8, tzinfo=timezone.utc)]
    accepting = [True]
    busy = [False]
    submitted = []
    agent = {
        "agentId": "person",
        "status": "active",
        "directSessionId": "session-person",
    }

    def submit(**payload):
        submitted.append(payload)
        return {
            "accepted": True,
            "turnId": f"turn-{len(submitted)}",
            "acceptedAt": now[0].isoformat(),
        }

    service = VirtualHumanLifeService(
        tmp_path,
        agent_loader=lambda agent_id, **_: agent if agent_id == "person" else None,
        agent_lister=lambda: [agent],
        plugin_root_resolver=lambda agent_id: tmp_path / agent_id,
        now_provider=lambda: now[0],
        runtime_acceptance_provider=lambda: accepting[0],
        proactive_submitter=submit,
        conversation_busy_provider=lambda _: busy[0],
        self_wake_session_provider=lambda _: "work-person",
        auto_mailbox_dispatch=False,
    )
    service.store.write_json(
        "person",
        "autonomy/native_session.json",
        {
            "agentId": "person",
            "runtimeAgentId": "worker-person",
            "sessionId": "work-person",
        },
    )
    service.set_binding(
        "person",
        enabled=True,
        expected_version=0,
        config={"proactiveMessagesEnabled": False},
    )
    return service, now, accepting, busy, submitted


def schedule(service, now, **overrides):
    return service.self_continuity.schedule(
        "person",
        session_id="session-person",
        source_turn_id="native-user-turn",
        wake_at=(now + timedelta(minutes=10)).isoformat(),
        intent="继续整理自己的阅读笔记",
        reason="完成当前章节以后继续",
        expected_revision=service.self_continuity.snapshot("person")["revision"],
        idempotency_key="next-reading",
        **overrides,
    )


def test_self_plan_wakes_once_at_due_time_without_proactive_message_permission(world):
    service, now, _, _, submitted = world
    plan = schedule(service, now[0])
    service.self_continuity.tick("person", now=now[0])
    assert submitted == []
    now[0] += timedelta(minutes=10)
    service.self_continuity.tick("person", now=now[0])
    service.self_continuity.tick("person", now=now[0])
    assert len(submitted) == 1
    assert submitted[0]["trigger"]["deliveryKind"] == "self_wake"
    assert submitted[0]["trigger"]["selfWake"]["wakeId"] == plan["wakeId"]
    assert submitted[0]["session_id"] == "work-person"
    assert "user_message" not in submitted[0]


def test_busy_person_waits_and_host_stop_fences_scheduling(world):
    service, now, accepting, busy, submitted = world
    schedule(service, now[0])
    now[0] += timedelta(minutes=10)
    busy[0] = True
    service.self_continuity.tick("person", now=now[0])
    assert submitted == []
    busy[0] = False
    accepting[0] = False
    service.self_continuity.tick("person", now=now[0])
    assert submitted == []
    with pytest.raises(ValueError, match="stopping"):
        schedule(service, now[0])


def test_restart_replaces_overdue_plan_with_review_without_offline_work(world):
    service, now, _, _, submitted = world
    old = schedule(service, now[0])
    now[0] += timedelta(hours=3)
    service.self_continuity.tick("person", now=now[0], restarted=True)
    recovered = service.self_continuity.snapshot("person")
    assert submitted == []
    assert recovered["wakeId"] != old["wakeId"]
    assert datetime.fromisoformat(recovered["wakeAt"]) > now[0]
    assert recovered["reason"] == "restart_review"
    assert service.list_events("person") == []


def test_person_can_chain_three_self_planned_actions(world):
    service, now, _, _, submitted = world
    for index in range(3):
        service.self_continuity.schedule(
            "person",
            session_id="session-person",
            source_turn_id=f"native-turn-{index}",
            wake_at=(now[0] + timedelta(minutes=10)).isoformat(),
            intent=f"推进自己的创作第 {index + 1} 步",
            reason="接续长期创作目标",
            expected_revision=service.self_continuity.snapshot("person")["revision"],
            idempotency_key=f"creative-{index}",
        )
        now[0] += timedelta(minutes=10)
        service.self_continuity.tick("person", now=now[0])
        service.dispatch_conversation_mailbox_once("person", session_id="work-person")
        # Model/tool execution is represented by a native terminal receipt, not by timer success.
        service.conversation_receipt_resolver = lambda *args: {
            "terminal": True,
            "status": "completed",
        }
    assert len(submitted) == 3


def test_wake_plan_identity_revision_and_time_are_checked(world):
    service, now, _, _, _ = world
    with pytest.raises(ValueError, match="direct Session"):
        service.self_continuity.schedule(
            "person",
            session_id="someone-else",
            source_turn_id="native-turn",
            wake_at=now[0].isoformat(),
            intent="read",
            reason="read",
            expected_revision=0,
            idempotency_key="bad",
        )
    schedule(service, now[0])
    with pytest.raises(ValueError, match="revision"):
        service.self_continuity.schedule(
            "person",
            session_id="session-person",
            source_turn_id="native-turn",
            wake_at=(now[0] + timedelta(hours=1)).isoformat(),
            intent="read",
            reason="read",
            expected_revision=0,
            idempotency_key="stale",
        )


def test_restart_preserves_future_plan_and_cancellation(world):
    service, now, _, _, submitted = world
    plan = schedule(service, now[0])
    now[0] += timedelta(minutes=3)
    assert (
        service.self_continuity.tick("person", now=now[0], restarted=True)["wakeId"]
        == plan["wakeId"]
    )
    service.self_continuity.cancel(
        "person", session_id="session-person", expected_revision=plan["revision"]
    )
    now[0] += timedelta(hours=3)
    assert (
        service.self_continuity.tick("person", now=now[0], restarted=True)["status"]
        == "cancelled"
    )
    assert submitted == []


def test_native_callback_can_replace_next_plan_without_old_dispatch_overwriting_it(
    world,
):
    service, now, _, _, submitted = world

    def model_turn(**payload):
        submitted.append(payload)
        service.self_continuity.schedule(
            "person",
            session_id="work-person",
            source_turn_id=f"native-action-{len(submitted)}",
            wake_at=(now[0] + timedelta(minutes=10)).isoformat(),
            intent="接着完成下一段创作",
            reason="依据刚完成的实际工作调整下一步",
            expected_revision=service.self_continuity.snapshot("person")["revision"],
            idempotency_key=f"model-next-{len(submitted)}",
        )
        return {
            "accepted": True,
            "turnId": f"native-action-{len(submitted)}",
            "acceptedAt": now[0].isoformat(),
        }

    service.proactive_submitter = model_turn
    schedule(service, now[0])
    for _ in range(3):
        now[0] += timedelta(minutes=10)
        service.self_continuity.tick("person", now=now[0])
        service.conversation_receipt_resolver = lambda *args: {
            "terminal": True,
            "status": "completed",
        }
    assert len(submitted) == 3
    assert service.self_continuity.snapshot("person")["status"] == "scheduled"
    assert (
        service.list_events("person") == []
    )  # No fabricated outcomes from scheduler success.


def test_model_can_stop_loop_during_native_dispatch_and_restart_cannot_revive_it(world):
    service, now, _, _, submitted = world

    def model_turn(**payload):
        submitted.append(payload)
        service.self_continuity.cancel(
            "person",
            session_id="work-person",
            expected_revision=service.self_continuity.snapshot("person")["revision"],
        )
        return {
            "accepted": True,
            "turnId": "cancelled-loop-turn",
            "acceptedAt": now[0].isoformat(),
        }

    service.proactive_submitter = model_turn
    schedule(service, now[0])
    now[0] += timedelta(minutes=10)
    assert service.self_continuity.tick("person", now=now[0])["status"] == "cancelled"
    binding = service.binding_for("person")
    service.set_binding(
        "person",
        enabled=True,
        expected_version=binding["configVersion"],
        config={"proactiveDailyLimit": 1},
    )
    now[0] += timedelta(days=1)
    assert (
        service.self_continuity.tick("person", now=now[0], restarted=True)["status"]
        == "cancelled"
    )
    assert len(submitted) == 1


def test_hidden_native_session_creation_is_inactive_idempotent_and_identity_checked(
    world, monkeypatch
):
    from types import SimpleNamespace

    from core.agent_plugins.virtual_human_life import native_wakeup
    from core.web.services import session_service
    from core.web.services import virtual_human_life_service as facade

    service, *_ = world
    service.store.write_json("person", "autonomy/native_session.json", {})
    calls = []
    state = {
        "agent_id": "worker-person",
        "metadata": {"source": "virtual_human_self_wake", "externalTaskId": "person"},
    }

    def create(**kwargs):
        calls.append(kwargs)
        return {"id": "native-work", "agentId": "worker-person"}

    worker = {
        "agentId": "worker-person",
        "status": "active",
        "directSessionId": "native-work",
    }

    def update(_agent_id, **kwargs):
        worker["metadata"] = kwargs["metadata"]
        return worker

    directory = SimpleNamespace(
        get_agent=lambda *args, **kwargs: worker,
        update_agent_instance=update,
        CONVERSATION_INDEX_KIND_HIDDEN="hidden",
        CONVERSATION_INDEX_VISIBILITY_HIDDEN="hidden",
    )

    monkeypatch.setattr(facade, "get_virtual_human_life_service", lambda: service)
    monkeypatch.setattr(session_service, "create_chat_session", create)
    monkeypatch.setattr(session_service, "load_session_chat_state", lambda *args: state)
    monkeypatch.setattr(
        native_wakeup, "_services", lambda: (service, directory, session_service)
    )
    assert facade._default_self_wake_session_provider("person") == "native-work"
    assert facade._default_self_wake_session_provider("person") == "native-work"
    assert len(calls) == 1
    assert calls[0]["activate"] is False
    assert "agent_id" not in calls[0]
    assert calls[0]["conversation_index_kind"] == "hidden"
    state["agent_id"] = "foreign-agent"
    with pytest.raises(ValueError, match="identity"):
        facade._default_self_wake_session_provider("person")


def test_user_interrupt_cancels_only_autonomous_native_work(world):
    service, now, _, _, submitted = world
    stopped = []
    service.self_wake_canceller = lambda *identity: stopped.append(identity)
    schedule(service, now[0])
    now[0] += timedelta(minutes=10)
    service.self_continuity.tick("person", now=now[0])
    service.self_continuity.interrupt_for_user("person")
    assert stopped == [("person", "work-person", "turn-1")]
    assert (
        service.proactive_attempt("person", submitted[0]["delivery_token"])["status"]
        == "cancelled"
    )


def test_settled_native_stop_race_does_not_reject_user_interruption(world):
    service, now, _, _, submitted = world
    schedule(service, now[0])
    now[0] += timedelta(minutes=10)
    service.self_continuity.tick("person", now=now[0])

    def settled(*_):
        raise RuntimeError("Native work settled before the stop request.")

    service.self_wake_canceller = settled
    service.self_continuity.interrupt_for_user("person")
    assert (
        service.proactive_attempt("person", submitted[0]["delivery_token"])["status"]
        == "cancelled"
    )


def test_self_wake_receipts_do_not_consume_contact_quota_or_interval(world):
    service, now, _, _, submitted = world
    schedule(service, now[0])
    now[0] += timedelta(minutes=10)
    service.self_continuity.tick("person", now=now[0])
    service._update_attempt(
        "person",
        submitted[0]["delivery_token"],
        status="delivered",
        deliveredAt=now[0].isoformat(),
    )
    assert (
        service.proactive_usage(
            "person",
            service._local_now(service.binding_for("person")).date().isoformat(),
        )["delivered"]
        == 0
    )
    assert service._latest_delivered_attempt("person") is None
    with pytest.raises(BindingDisabledError, match="disabled"):
        service.request_proactive_message(
            "person", reason="普通主动聊天", idempotency_key="contact"
        )


@pytest.mark.parametrize("delay", [timedelta(0), timedelta(days=8)])
def test_self_wake_time_budget_rejects_past_or_unbounded_future(world, delay):
    service, now, *_ = world
    with pytest.raises(ValueError, match="minute"):
        service.self_continuity.schedule(
            "person",
            session_id="session-person",
            source_turn_id="native-turn",
            wake_at=(now[0] + delay).isoformat(),
            intent="read",
            reason="read",
            expected_revision=0,
            idempotency_key="bad-time",
        )


def test_self_wake_daily_budget_defers_without_starting_more_native_work(world):
    service, now, _, _, submitted = world
    plan = schedule(service, now[0])
    plan["wakeRequests"] = [now[0].isoformat()] * 24
    service.store.write_json("person", "autonomy/next_wakeup.json", plan)
    now[0] += timedelta(minutes=10)
    assert (
        service.self_continuity.tick("person", now=now[0])["waitReason"]
        == "wake_budget"
    )
    assert submitted == []


def test_real_schedule_tool_chains_native_work_and_keeps_toolpolicy_intersection(
    world, monkeypatch
):
    import json

    from core.agent_plugins.virtual_human_life.runtime_extension import (
        VIRTUAL_HUMAN_LIFE_RUNTIME_EXTENSION,
    )
    from core.web.services import agent_directory_service
    from core.web.services import virtual_human_life_service as facade
    from tools.virtual_human_life_tools import virtual_human_schedule_tool

    service, now, _, _, submitted = world
    runtime = {
        "agentId": "person",
        "sessionId": "session-person",
        "turnId": "native-user",
    }
    monkeypatch.setattr(facade, "get_virtual_human_life_service", lambda: service)
    monkeypatch.setattr(
        agent_directory_service, "current_agent_runtime", lambda: runtime
    )

    def arrange(index):
        observed = json.loads(virtual_human_schedule_tool(action="view_wakeup"))
        result = json.loads(
            virtual_human_schedule_tool(
                action="schedule_wakeup",
                expected_version=observed["wakePlan"]["revision"],
                title="根据自己的进展继续创作",
                start_at=(now[0] + timedelta(minutes=10)).isoformat(),
                reason="继续自己的长期目标",
                required_tool_names=["read_file_tool", "unauthorized_tool"],
                idempotency_key=f"tool-next-{index}",
            )
        )
        assert result["ok"] is True

    def native_work(**payload):
        submitted.append(payload)
        runtime.update(sessionId="work-person", turnId=f"native-work-{len(submitted)}")
        metadata = VIRTUAL_HUMAN_LIFE_RUNTIME_EXTENSION.proactive_runtime_metadata(
            {
                "proactive_plugin": {"trigger": payload["trigger"]},
            }
        )
        visible = service.filter_tool_names(
            "person",
            ["virtual_human_schedule_tool", "read_file_tool"],
            runtime_context={"runtimeMetadata": metadata},
        )
        assert visible == ["virtual_human_schedule_tool", "read_file_tool"]
        arrange(len(submitted))
        return {
            "accepted": True,
            "turnId": runtime["turnId"],
            "acceptedAt": now[0].isoformat(),
        }

    service.proactive_submitter = native_work
    arrange(0)
    for _ in range(3):
        now[0] += timedelta(minutes=10)
        service.self_continuity.tick("person", now=now[0])
    assert len(submitted) == 3
    assert service.self_continuity.snapshot("person")["idempotencyKey"] == "tool-next-3"
    runtime.update(
        agentId="unknown-person", sessionId="someone-else", turnId="foreign-turn"
    )
    assert json.loads(virtual_human_schedule_tool(action="view_wakeup"))["ok"] is False
