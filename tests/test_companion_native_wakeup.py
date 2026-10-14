"""Real native directory/admission regression for Companion work isolation."""

import threading
from datetime import datetime, timedelta, timezone

import pytest

from core.agent_plugins.virtual_human_life.service import VirtualHumanLifeService
from core.chat.conversation_ledger import load_conversation_events
from core.web.services import agent_directory_service as directory
from core.web.services import session_service
from core.web.services import virtual_human_life_service as facade
from core.web.services.session.proactive import (
    admit_session_proactive_turn,
    cancel_proactive_turn_context,
)
from tests.helpers.web_chat_state import (
    _bind_seeded_submittable_agent,
    _reset_seeded_session_runtime,
    _seed_chat_state,
)


@pytest.fixture
def native_world(tmp_path, monkeypatch):
    accepting = threading.Event()
    accepting.set()
    monkeypatch.setattr(facade, "_RUNTIME_ACCEPTING", accepting)
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(directory, "PROJECT_ROOT", tmp_path)
    _seed_chat_state(tmp_path)
    owner = _bind_seeded_submittable_agent(tmp_path)
    owner_id = owner["agentId"]
    directory.update_agent_instance(
        owner_id, tool_policy={"allowedTools": ["virtual_human_schedule_tool"]}
    )
    now = [datetime(2026, 10, 13, 8, tzinfo=timezone.utc)]
    service = VirtualHumanLifeService(
        tmp_path,
        agent_loader=directory.get_agent,
        agent_lister=lambda: [directory.get_agent(owner_id)],
        plugin_root_resolver=lambda agent_id: tmp_path / "plugins" / agent_id,
        now_provider=lambda: now[0],
        proactive_submitter=facade._default_proactive_submitter,
        self_wake_session_provider=facade._default_self_wake_session_provider,
        self_wake_canceller=facade._default_self_wake_canceller,
        auto_mailbox_dispatch=False,
    )
    monkeypatch.setattr(facade, "get_virtual_human_life_service", lambda: service)
    service.set_binding(
        owner_id,
        enabled=True,
        expected_version=0,
        config={"proactiveMessagesEnabled": False},
    )
    service.self_continuity.schedule(
        owner_id,
        session_id="session-live",
        source_turn_id="native-owner-turn",
        wake_at=(now[0] + timedelta(minutes=1)).isoformat(),
        intent="整理真实阅读笔记",
        reason="接续已有目标",
        expected_revision=0,
        idempotency_key="actual-native-wake",
    )
    scheduled = []
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: scheduled.append(context),
    )
    try:
        yield service, owner_id, now, scheduled
    finally:
        for context in scheduled:
            cancel_proactive_turn_context(context, reason="test_done")
            _reset_seeded_session_runtime(context["session_id"])
        _reset_seeded_session_runtime("session-live")


def test_worker_preserves_person_chat_and_uses_real_native_admission(
    native_world, tmp_path
):
    service, owner_id, now, scheduled = native_world
    owner_chat = directory.get_agent(owner_id)["directSessionId"]
    before_events = load_conversation_events(tmp_path, owner_chat)
    now[0] += timedelta(minutes=1)
    service.self_continuity.tick(owner_id, now=now[0])
    ref = service.store.read_json(owner_id, "autonomy/native_session.json")
    work_session, worker_id = ref["sessionId"], ref["runtimeAgentId"]
    assert worker_id != owner_id and work_session != owner_chat
    assert directory.get_agent(owner_id)["directSessionId"] == owner_chat
    assert directory.get_agent(worker_id)["directSessionId"] == work_session
    assert facade._default_self_wake_session_provider(owner_id) == work_session
    assert len(scheduled) == 1
    assert scheduled[0]["agent_id"] == worker_id
    assert admit_session_proactive_turn(scheduled[0]) == "admitted"
    events = load_conversation_events(tmp_path, work_session)
    assert "internal_turn_trigger" in [event.event_type for event in events]
    assert "user_message" not in [event.event_type for event in events]
    assert load_conversation_events(tmp_path, owner_chat) == before_events
    assert directory.get_agent(owner_id)["directSessionId"] == owner_chat
    assert work_session not in {row["id"] for row in session_service.list_sessions()}
    assert (
        facade.resolve_virtual_human_runtime_target(worker_id, session_id=work_session)[
            "targetAgentId"
        ]
        == owner_id
    )
    with pytest.raises(ValueError, match="identity"):
        facade.resolve_virtual_human_runtime_target(worker_id, session_id=owner_chat)


def test_worker_authorization_follows_owner_and_plan_and_cannot_bypass_contact(
    native_world, monkeypatch
):
    import json

    from core.agent_plugins.virtual_human_life.native_wakeup import (
        authorized_tool_names,
    )
    from core.agent_plugins.virtual_human_life.service import BindingDisabledError
    from tools import virtual_human_life_tools as tools

    service, owner_id, now, scheduled = native_world
    directory.update_agent_instance(
        owner_id,
        tool_policy={
            "allowedTools": [
                "virtual_human_schedule_tool",
                "virtual_human_proactive_message_tool",
                "file_read_tool",
                "agent_message_tool",
            ],
            "readScopes": ["repo"],
            "writeScopes": [],
            "networkAccess": "none",
            "mutationAccess": "none",
            "maxCallsPerTurn": 4,
        },
        metadata={"creationToolBundleIds": ["virtual_human_life"]},
        persona_profile={
            "identity": "独立的人物",
            "background": "真实的已确认人物背景",
        },
    )
    plan = service.self_continuity.snapshot(owner_id)
    plan["requiredToolNames"] = ["file_read_tool"]
    service.store.write_json(owner_id, "autonomy/next_wakeup.json", plan)
    now[0] += timedelta(minutes=1)
    service.self_continuity.tick(owner_id, now=now[0])
    ref = service.store.read_json(owner_id, "autonomy/native_session.json")
    worker = directory.get_agent(ref["runtimeAgentId"])
    assert worker["personaProfile"]["background"] == "真实的已确认人物背景"
    assert "agent_message_tool" not in worker["toolPolicy"]["allowedTools"]
    assert worker["toolPolicy"]["maxCallsPerTurn"] == 4
    assert worker["toolPolicy"]["writeScopes"] == []
    names = ["virtual_human_schedule_tool", "file_read_tool", "agent_message_tool"]
    assert (
        authorized_tool_names(worker["agentId"], names, session_id=ref["sessionId"])
        == names[:2]
    )
    directory.update_agent_instance(
        owner_id, tool_policy={"allowedTools": ["virtual_human_schedule_tool"]}
    )
    assert (
        authorized_tool_names(worker["agentId"], names, session_id=ref["sessionId"])
        == names[:1]
    )
    context = scheduled[0]
    assert admit_session_proactive_turn(context) == "admitted"
    from core.agent_plugins.virtual_human_life.runtime_extension import (
        VirtualHumanLifeRuntimeExtension,
    )

    assert (
        VirtualHumanLifeRuntimeExtension().blocked_tool_names(worker["agentId"]) == []
    )
    monkeypatch.setattr(
        tools,
        "_runtime_context",
        lambda: {
            "agentId": worker["agentId"],
            "sessionId": ref["sessionId"],
            "turnId": context["turn_id"],
        },
    )
    result = json.loads(
        tools.virtual_human_schedule_tool(
            action="schedule_wakeup",
            expected_version=plan["revision"],
            start_at=(now[0] + timedelta(hours=1)).isoformat(),
            title="重新安排阅读",
            reason="根据实际进度",
            idempotency_key="next-native-reading",
        )
    )
    assert result["ok"] is True
    assert (
        result["agentId"] == owner_id and result["runtimeAgentId"] == worker["agentId"]
    )
    assert result["wakePlan"]["sourceTurnId"] == context["turn_id"]
    with pytest.raises(BindingDisabledError):
        service.request_proactive_message(
            owner_id, reason="想分享", idempotency_key="actual-contact"
        )
    prompt = facade.build_virtual_human_prompt_segments(
        worker["agentId"], session_id=ref["sessionId"], run_id=context["turn_id"]
    )
    assert "internal_self_wake" in prompt[1]["block"]
    assert "virtual_human_dialogue_decision_v2_tool" not in prompt[0]["block"]


def test_host_stop_cancels_real_worker_without_touching_person_session(native_world):
    service, owner_id, now, scheduled = native_world
    now[0] += timedelta(minutes=1)
    service.self_continuity.tick(owner_id, now=now[0])
    context = scheduled[0]
    assert admit_session_proactive_turn(context) == "admitted"
    assert session_service._is_session_running(context["session_id"])
    facade.stop_virtual_human_life_runtime()
    assert not facade._RUNTIME_ACCEPTING.is_set()
    assert session_service._is_session_stop_requested(context["session_id"])
    assert directory.get_agent(owner_id)["directSessionId"] == "session-live"
    assert not service.proactive_turn_is_current(
        agent_id=owner_id,
        binding_revision=1,
        delivery_token=context["proactive_plugin"]["deliveryToken"],
    )


def test_real_authorization_executes_next_plan_and_rejects_live_owner_revocation(
    native_world,
):
    import json

    from core.agent_plugins.virtual_human_life.runtime_extension import (
        VirtualHumanLifeRuntimeExtension,
    )
    from core.authorization.tool_authorization_service import (
        clear_execution_authorization,
        install_execution_authorization,
        resolve_enforced_authorization,
    )
    from core.infrastructure.tool_executor import ToolExecutor

    service, owner_id, now, scheduled = native_world
    now[0] += timedelta(minutes=1)
    service.self_continuity.tick(owner_id, now=now[0])
    context = scheduled[0]
    assert admit_session_proactive_turn(context) == "admitted"
    with directory.active_agent_runtime(
        context["agent_id"],
        session_id=context["session_id"],
        turn_id=context["turn_id"],
        runtime_metadata=VirtualHumanLifeRuntimeExtension().proactive_runtime_metadata(
            context
        ),
    ) as runtime:
        report = resolve_enforced_authorization(runtime=runtime)
        assert "virtual_human_schedule_tool" in report.decision.executable_tools
        install_execution_authorization(report)
        try:
            result, _detail = ToolExecutor().execute(
                "virtual_human_schedule_tool",
                {
                    "action": "schedule_wakeup",
                    "expected_version": service.self_continuity.snapshot(owner_id)[
                        "revision"
                    ],
                    "start_at": (now[0] + timedelta(hours=1)).isoformat(),
                    "title": "继续自己的计划",
                    "reason": "依据实际进度",
                    "idempotency_key": "authorized-next-plan",
                },
                tool_call_id="authorized-schedule-next",
            )
            assert json.loads(result)["status"] == "applied"
            directory.update_agent_instance(owner_id, tool_policy={"allowedTools": []})
            denied, _detail = ToolExecutor().execute(
                "virtual_human_schedule_tool",
                {
                    "action": "view_wakeup",
                },
                tool_call_id="revoked-plan-read",
            )
            assert "人物授权已变化" in str(denied)
        finally:
            clear_execution_authorization()


def test_native_worker_purge_failure_retains_archived_retry_receipt(
    native_world, monkeypatch
):
    from core.agent_plugins.virtual_human_life.native_wakeup import (
        recover_pending_purges,
    )

    service, owner_id, now, _scheduled = native_world
    now[0] += timedelta(minutes=1)
    service.self_continuity.tick(owner_id, now=now[0])
    ref = service.store.read_json(owner_id, "autonomy/native_session.json")
    directory.archive_agent_instance(owner_id, repair_mode_bindings=False)
    real_purge = directory.purge_archived_agent_instance

    def flaky_purge(agent_id, **kwargs):
        if agent_id == ref["runtimeAgentId"]:
            raise OSError("controlled worker workspace failure")
        return real_purge(agent_id, **kwargs)

    monkeypatch.setattr(directory, "purge_archived_agent_instance", flaky_purge)
    directory.purge_archived_agent_instance(owner_id)
    worker = directory.get_agent(ref["runtimeAgentId"], include_archived=True)
    assert worker["status"] == "archived"
    assert worker["metadata"]["selfWakePurgePending"]["sessionId"] == ref["sessionId"]
    monkeypatch.setattr(directory, "purge_archived_agent_instance", real_purge)
    recover_pending_purges()
    assert directory.get_agent(ref["runtimeAgentId"], include_archived=True) is None


def test_archive_and_purge_manage_worker_pair_with_rollback(native_world):
    service, owner_id, now, _scheduled = native_world
    now[0] += timedelta(minutes=1)
    service.self_continuity.tick(owner_id, now=now[0])
    ref = service.store.read_json(owner_id, "autonomy/native_session.json")
    token = facade.prepare_virtual_human_agent_archive(owner_id)
    assert (
        directory.get_agent(ref["runtimeAgentId"], include_archived=True)["status"]
        == "archived"
    )
    facade.rollback_virtual_human_agent_archive(token)
    assert directory.get_agent(ref["runtimeAgentId"])["status"] == "active"
    assert service.binding_for(owner_id)["enabled"] is True
    directory.archive_agent_instance(owner_id, repair_mode_bindings=False)
    assert (
        directory.get_agent(ref["runtimeAgentId"], include_archived=True)["status"]
        == "archived"
    )
    directory.purge_archived_agent_instance(owner_id)
    assert directory.get_agent(ref["runtimeAgentId"], include_archived=True) is None
    assert (
        session_service.load_session_chat_state(
            session_service.PROJECT_ROOT, ref["sessionId"]
        )
        is None
    )
