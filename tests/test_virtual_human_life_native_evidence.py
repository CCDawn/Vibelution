"""Companion receipts are scoped native facts, never model autobiographies."""

from types import SimpleNamespace

import pytest

from core.agent_plugins.virtual_human_life.native_activity_evidence import (
    native_activity_evidence,
)
from core.chat.turn_journal import EVENT_TOOL_RESULT


def _request(**changes):
    return {
        "runtimeAgentId": "companion",
        "sessionId": "chat",
        "turnId": "turn",
        "requiredToolNames": ["read_file"],
        "startedAt": "2026-10-14T10:00:00+00:00",
        **changes,
    }


def _event(*, name="read_file", call="call", receipt="receipt", tool=None, **changes):
    return SimpleNamespace(
        **{
            "event_type": EVENT_TOOL_RESULT,
            "session_id": "chat",
            "turn_id": "turn",
            "event_id": receipt,
            "tool_call_id": call,
            "status": "done",
            "timestamp": "2026-10-14T10:01:00+00:00",
            "payload": {
                "toolCall": {
                    "name": name,
                    "callId": call,
                    "status": "done",
                    "result": '{"ok": true}',
                    **(tool or {}),
                }
            },
            **changes,
        }
    )


def test_success_keeps_only_bounded_native_identifiers():
    result = native_activity_evidence(
        _request(), [_event(tool={"arguments": {"secret": "hidden"}})]
    )
    assert result == {
        "kind": "native_tool_execution",
        "sessionId": "chat",
        "turnId": "turn",
        "toolCallIds": ["call"],
        "toolNames": ["read_file"],
        "receiptEventIds": ["receipt"],
    }
    assert "hidden" not in str(result)


@pytest.mark.parametrize("field", ["excludedToolCallIds", "excludedReceiptEventIds"])
def test_consumed_receipts_cannot_prove_another_activity(field):
    excluded = "call" if field == "excludedToolCallIds" else "receipt"
    request = _request(**{field: [excluded]})
    assert native_activity_evidence(request, [_event()]) is None
    evidence = native_activity_evidence(request, [_event(), _event(call="new-call", receipt="new-receipt")])
    assert evidence["toolCallIds"] == ["new-call"]
    assert evidence["receiptEventIds"] == ["new-receipt"]


@pytest.mark.parametrize("value", ["call", [{}], [2], [""], ["x"] * 513])
def test_malformed_exclusion_requests_fail_closed(value):
    assert native_activity_evidence(_request(excludedToolCallIds=value), [_event()]) is None


@pytest.mark.parametrize(
    "tool",
    [
        {"error": "failure"},
        {"timedOut": True},
        {"exitCode": 1},
        {"exit_code": "-1"},
        {"exitCode": "unknown"},
        {"failureClass": "process_exit"},
        {"exitCode": 0.5},
        {"semanticStatus": "failed"},
        {"semanticStatus": "blocked"},
        {"semanticStatus": "degraded"},
        {"semanticStatus": "observed"},
        {"semanticStatus": "unknown"},
        {"semanticStatus": "no_result"},
        {"transportStatus": "failed"},
        {"resultKind": "no_result"},
        {"result": '{"ok": false}'},
        {"result": '{"success": false}'},
        {"result": '{"status": "failed"}'},
        {"result": '{"status": "blocked"}'},
        {"result": '{"status": "degraded"}'},
        {"result": '{"status": "observed"}'},
        {"result": '{"status": "unknown"}'},
        {"result": '{"status": "no_result"}'},
        {"result": '{"ok": true, "error": "failure"}'},
        {"result": '{"status": "completed", "exitCode": 2}'},
        {"result": '{"status": "completed", "timedOut": true}'},
        {"result": "完成了所有活动"},
        {"result": "{}"},
        {"result": ""},
    ],
)
def test_explicit_failure_and_unproven_results_fail_closed(tool):
    assert native_activity_evidence(_request(), [_event(tool=tool)]) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "failed"},
        {"status": "unknown"},
        {"status": "observed"},
        {"session_id": "other"},
        {"turn_id": "other"},
        {"event_type": "assistant_message"},
        {"timestamp": "2026-10-14T09:59:59+00:00"},
        {"timestamp": ""},
        {"timestamp": "2026-10-14T10:01:00"},
        {"event_id": ""},
        {"tool_call_id": ""},
    ],
)
def test_native_scope_and_time_fail_closed(changes):
    assert native_activity_evidence(_request(), [_event(**changes)]) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"sessionId": ""},
        {"turnId": ""},
        {"executionTurnId": "other"},
        {"startedAt": ""},
        {"startedAt": "bad"},
        {"startedAt": "2026-10-14T10:00:00"},
        {"requiredToolNames": []},
        {"requiredToolNames": ["other"]},
        {"requiredToolNames": ["read_file", "write_file"]},
        {"requiredToolNames": ["virtual_human_activity_tool"]},
    ],
)
def test_missing_declared_proof_cannot_be_replaced_by_any_same_turn_tool(changes):
    assert native_activity_evidence(_request(**changes), [_event()]) is None


def test_required_tools_all_need_distinct_successful_receipts_in_actual_turn():
    request = _request(
        requiredToolNames=["READ_FILE", "write_file"], executionTurnId="turn"
    )
    events = [
        _event(),
        _event(name="write_file", call="write", receipt="written", turn_id="other"),
    ]
    assert native_activity_evidence(request, events) is None
    events.append(_event(name="write_file", call="write", receipt="written"))
    assert native_activity_evidence(request, events)["toolNames"] == [
        "read_file",
        "write_file",
    ]


def test_bookkeeping_and_model_self_report_never_supply_execution():
    assert (
        native_activity_evidence(
            _request(),
            [
                _event(name="virtual_human_activity_tool"),
                _event(
                    event_type="assistant_message", payload={"text": "我已读取文件。"}
                ),
            ],
        )
        is None
    )


def test_later_failure_for_same_call_cannot_reuse_earlier_success():
    assert (
        native_activity_evidence(
            _request(), [_event(), _event(receipt="failed", tool={"error": "bad"})]
        )
        is None
    )


def test_conflicting_call_identity_cannot_supply_receipt():
    assert (
        native_activity_evidence(_request(), [_event(tool={"callId": "other"})]) is None
    )


def test_native_default_success_does_not_prove_opaque_business_result():
    assert (
        native_activity_evidence(
            _request(),
            [_event(tool={"result": "content", "semanticStatus": "succeeded"})],
        )
        is None
    )
    assert (
        native_activity_evidence(_request(), [_event(tool={"result": "content"})])
        is None
    )


@pytest.fixture
def adapter(monkeypatch):
    from core.web.services import agent_directory_service
    from core.web.services import virtual_human_life_service as facade
    from core.web.services.session import journal_bridge

    binding = {
        "enabled": True,
        "steward": {
            "provisioningState": "ready",
            "agentId": "steward",
            "sessionId": "steward-session",
        },
    }
    agents = {
        "companion": {"status": "active", "directSessionId": "chat"},
        "other": {"status": "active", "directSessionId": "other-chat"},
        "steward": {
            "status": "active",
            "directSessionId": "steward-session",
            "metadata": {"lifeStewardForAgentId": "companion"},
        },
        "worker": {
            "status": "active",
            "directSessionId": "worker-session",
            "metadata": {"virtualHumanSelfWake": True},
        },
    }
    service = SimpleNamespace(
        binding_for=lambda key: binding if key == "companion" else None,
        require_agent=lambda key, **_: agents[key],
    )
    runtime = _request()
    runtime["agentId"] = runtime["runtimeAgentId"]
    events = [_event()]
    monkeypatch.setattr(facade, "get_virtual_human_life_service", lambda: service)
    monkeypatch.setattr(
        agent_directory_service, "current_agent_runtime", lambda: runtime
    )
    monkeypatch.setattr(
        journal_bridge, "load_session_conversation_events_snapshot", lambda _: events
    )
    return facade, runtime, events, agents


def test_direct_companion_requires_exact_direct_session_and_current_runtime(adapter):
    facade, _runtime, _events, agents = adapter
    assert facade._default_activity_evidence_resolver("companion", _request())
    agents["companion"]["directSessionId"] = "other-chat"
    assert facade._default_activity_evidence_resolver("companion", _request()) is None


@pytest.mark.parametrize(
    "key,value",
    [("agentId", "other"), ("sessionId", "other"), ("turnId", "other"), ("turnId", "")],
)
def test_request_cannot_borrow_another_runtime_identity(adapter, key, value):
    facade, runtime, *_ = adapter
    runtime[key] = value
    assert facade._default_activity_evidence_resolver("companion", _request()) is None


def test_paired_steward_can_only_supply_its_own_bound_session(adapter):
    facade, runtime, events, agents = adapter
    runtime.update(agentId="steward", sessionId="steward-session")
    events[:] = [_event(session_id="steward-session")]
    request = _request(runtimeAgentId="steward", sessionId="steward-session")
    assert facade._default_activity_evidence_resolver("companion", request)
    agents["steward"]["metadata"]["lifeStewardForAgentId"] = "other"
    assert facade._default_activity_evidence_resolver("companion", request) is None


def test_self_wake_uses_existing_verified_worker_binding(adapter, monkeypatch):
    from core.agent_plugins.virtual_human_life import native_wakeup

    facade, runtime, events, _ = adapter
    seen = []

    def resolve(agent_id, *, session_id):
        seen.append((agent_id, session_id))
        return "companion"

    monkeypatch.setattr(native_wakeup, "resolve_worker", resolve)
    runtime.update(agentId="worker", sessionId="worker-session")
    events[:] = [_event(session_id="worker-session")]
    request = _request(runtimeAgentId="worker", sessionId="worker-session")
    assert facade._default_activity_evidence_resolver("companion", request)
    assert seen == [("worker", "worker-session")]
    monkeypatch.setattr(native_wakeup, "resolve_worker", lambda *a, **k: "other")
    assert facade._default_activity_evidence_resolver("companion", request) is None


def test_episode_filter_reads_native_history_once_before_applying_limit(monkeypatch):
    from core.web.services import virtual_human_life_service as facade
    from core.web.services.agent_directory import episodic_memory

    calls = []

    def native(agent_id, *, include_superseded):
        calls.append((agent_id, include_superseded))
        return [{"episodeId": f"new-{i}"} for i in range(800)] + [
            {"episodeId": "legacy", "text": "native only"}
        ]

    monkeypatch.setattr(episodic_memory, "list_episodic_events", native)
    assert facade._default_episodic_history_lister(
        "companion", limit=1, episode_ids=["legacy"]
    ) == [{"episodeId": "legacy", "text": "native only"}]
    assert calls == [("companion", False)]
    assert (
        len(
            facade._default_episodic_history_lister(
                "companion", limit=999, include_superseded=True
            )
        )
        == 500
    )
    assert calls[-1] == ("companion", True)
    assert facade._default_episodic_history_lister("companion", episode_ids=[]) == []


def test_memory_reconciliation_happens_before_native_admission(monkeypatch):
    from core.web.services import session_service
    from core.web.services import virtual_human_life_service as facade

    calls = []
    service = SimpleNamespace(
        reconcile_life_memory_sources=lambda agent: calls.append(("reconcile", agent))
    )
    monkeypatch.setattr(facade, "get_virtual_human_life_service", lambda: service)
    monkeypatch.setattr(
        session_service,
        "submit_session_proactive_turn",
        lambda **payload: (
            calls.append(("admit", payload["agent_id"])) or {"accepted": True}
        ),
    )
    was_accepting = facade._RUNTIME_ACCEPTING.is_set()
    facade._RUNTIME_ACCEPTING.set()
    try:
        assert facade._default_proactive_submitter(
            agent_id="companion", session_id="chat"
        )["accepted"]
    finally:
        if not was_accepting:
            facade._RUNTIME_ACCEPTING.clear()
    assert calls == [("reconcile", "companion"), ("admit", "companion")]
