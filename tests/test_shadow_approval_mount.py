"""Shadow-approval mount (批四 Lane S) red lines.

逐条断言红线：影子 on/off 时真实审批行为零差异（authorize 链结果与审批事件
序列逐字段一致）；影子不写 _TURN_DECISION_TEMPLATES 缓存；不进额度/计数/
预算路径；台账写失败静默（monkeypatch 抛异常 → 主链保持绿）；真实终态由
挂载点事后回填进台账。
"""

from __future__ import annotations

import sqlite3
import threading
import time
from copy import deepcopy
from types import SimpleNamespace

import pytest

from core.authorization import shadow_approval_evaluator as ev
from core.authorization import tool_authorization_service
from core.web.services import agent_directory_service
from core.web.services import shadow_approval_ledger as ledger
from core.web.services.session import tool_approvals
from tests.test_financial_knowledge_service import finance_env  # noqa: F401 - workspace isolation fixture

finance_env = finance_env

AGENT_ID = "agent-a"


@pytest.fixture(autouse=True)
def _reset_all(monkeypatch):
    monkeypatch.delenv(ev.SHADOW_APPROVALS_ENV, raising=False)
    ev.reset_shadow_telemetry()
    tool_approvals.reset_tool_approval_state(clear_durable=False)
    tool_authorization_service.clear_execution_authorization()
    yield
    ev.reset_shadow_telemetry()
    tool_approvals.reset_tool_approval_state(clear_durable=False)
    tool_authorization_service.clear_execution_authorization()


def _runtime(monkeypatch, *, session_id="session-a", turn_id="turn-a",
             permission_preset="request_approval"):
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {
            "agentId": AGENT_ID,
            "sessionId": session_id,
            "turnId": turn_id,
            "agentConfigSnapshot": {
                "agentId": AGENT_ID,
                "configRevision": 3,
                "configHash": "config-hash-a",
            },
            "permissionPreset": permission_preset,
            "toolPolicy": {
                "policyId": "tool-agent-a",
                "allowedTools": ["web_search_tool", "agent_message_tool"],
                "preferredTools": [],
                "blockedTools": [],
                "maxCallsPerTurn": 20,
            },
        },
    )


def _install(*requirements, policy_id="tool-agent-a", descriptor_approvals=()):
    tool_authorization_service.install_execution_authorization(
        SimpleNamespace(
            decision=SimpleNamespace(
                agent_id=AGENT_ID,
                turn_id="turn-a",
                decision_fingerprint="decision-a",
                policy_id=policy_id,
                executable_tools=tuple(item[0] for item in requirements),
                approval_requirements=tuple(requirements),
            ),
            shadow_descriptor_approvals=tuple(descriptor_approvals),
        )
    )


def _stable_events(monkeypatch):
    """Capture the approval event stream's stable fields (audit sequence)."""

    events: list[tuple] = []

    def _capture(event_code, request, *, outcome):
        projection = request.public_projection()
        events.append(
            (
                event_code,
                str(outcome),
                projection["status"],
                projection["decision"] or "",
                projection["toolName"],
                projection["callId"],
                projection["approval"],
                projection["risk"],
            )
        )

    monkeypatch.setattr(tool_approvals, "_record_approval_event", _capture)
    return events


def _wait_for_pending(session_id="session-a"):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        requests = tool_approvals.list_tool_approval_requests(session_id, status="pending")
        if requests:
            return requests[0]
        time.sleep(0.02)
    raise AssertionError("approval request did not become pending")


def _ledger_rows():
    path = ledger.ledger_database_path()
    if not path.exists():
        return []
    connection = sqlite3.connect(str(path))
    try:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(
            "SELECT * FROM shadow_approvals ORDER BY created_at_ms, call_id"
        )]
    finally:
        connection.close()


def _decline_flow(monkeypatch, *, call_id="call-audit", install=None):
    """Full human-decline approval flow; returns the authorization result.

    授权上下文是 ContextVar，工作线程不继承：与现有审批流测试同形制，在线程
    内重新安装同一份决策快照。
    """

    events = _stable_events(monkeypatch)
    result_box: dict = {}
    install = install or (lambda: _install(("web_search_tool", "on_request", "network")))

    def _worker():
        install()
        result_box.setdefault(
            "value",
            tool_authorization_service.authorize_tool_execution(
                tool_name="web_search_tool",
                tool_call_id=call_id,
                tool_args={"query": "same"},
            ),
        )

    worker = threading.Thread(target=_worker)
    worker.start()
    request = _wait_for_pending()
    tool_approvals.resolve_tool_approval_request("session-a", request["requestId"], decision="decline")
    worker.join(timeout=5)
    result = result_box["value"]
    return result, tuple(events)


# ---------------------------------------------------------------------------
# Red line 1: zero behavior difference, shadow on vs off
# ---------------------------------------------------------------------------


def test_decline_flow_identical_with_shadow_on_and_off(monkeypatch, finance_env):
    monkeypatch.setenv(ev.SHADOW_APPROVALS_ENV, "off")
    _runtime(monkeypatch)
    _install(("web_search_tool", "on_request", "network"))
    baseline_result, baseline_events = _decline_flow(monkeypatch, call_id="call-off")

    tool_approvals.reset_tool_approval_state(clear_durable=False)
    monkeypatch.delenv(ev.SHADOW_APPROVALS_ENV, raising=False)
    _runtime(monkeypatch)
    _install(("web_search_tool", "on_request", "network"))
    shadow_result, shadow_events = _decline_flow(monkeypatch, call_id="call-off")

    assert shadow_result == baseline_result
    assert baseline_result.allowed is False
    assert baseline_result.code == "approval_declined"
    # 审批事件序列逐字段一致（含请求/决议状态机轨迹）。
    assert shadow_events == baseline_events
    assert [event[0] for event in baseline_events] == [
        "tool.approval.requested",
        "tool.approval.resolved",
    ]


def test_session_grant_flow_identical_with_shadow_on_and_off(monkeypatch, finance_env):
    def _grant_flow():
        events = _stable_events(monkeypatch)
        first_box: dict = {}

        def _worker():
            _install(("web_search_tool", "on_request", "network"))
            first_box.setdefault(
                "value",
                tool_authorization_service.authorize_tool_execution(
                    tool_name="web_search_tool",
                    tool_call_id="call-grant",
                    tool_args={"query": "same"},
                ),
            )

        worker = threading.Thread(target=_worker)
        worker.start()
        request = _wait_for_pending()
        tool_approvals.resolve_tool_approval_request(
            "session-a", request["requestId"], decision="acceptForSession"
        )
        worker.join(timeout=5)
        first = first_box["value"]
        second, _ = (
            tool_authorization_service.authorize_tool_execution(
                tool_name="web_search_tool",
                tool_call_id="call-same",
                tool_args={"query": "same"},
            ),
            None,
        )
        return (first, second, tuple(events))

    monkeypatch.setenv(ev.SHADOW_APPROVALS_ENV, "off")
    _runtime(monkeypatch)
    _install(("web_search_tool", "on_request", "network"))
    baseline = _grant_flow()

    tool_approvals.reset_tool_approval_state(clear_durable=False)
    monkeypatch.delenv(ev.SHADOW_APPROVALS_ENV, raising=False)
    _runtime(monkeypatch)
    _install(("web_search_tool", "on_request", "network"))
    shadow = _grant_flow()

    assert shadow[0] == baseline[0]
    assert shadow[1] == baseline[1]
    assert shadow[2] == baseline[2]
    assert baseline[1].code == "approved_for_session"


def test_never_approval_flow_identical_with_shadow_on_and_off(monkeypatch, finance_env):
    def _never_flow():
        events = _stable_events(monkeypatch)
        result = tool_authorization_service.authorize_tool_execution(
            tool_name="agent_message_tool",
            tool_call_id="call-msg",
            tool_args={"target_session": "peer", "content": "PING"},
        )
        return result, tuple(events)

    monkeypatch.setenv(ev.SHADOW_APPROVALS_ENV, "off")
    _runtime(monkeypatch)
    _install(("agent_message_tool", "never", "write"))
    baseline = _never_flow()

    monkeypatch.delenv(ev.SHADOW_APPROVALS_ENV, raising=False)
    _runtime(monkeypatch)
    _install(("agent_message_tool", "never", "write"))
    shadow = _never_flow()

    assert shadow == baseline
    assert baseline[0].allowed is True
    assert baseline[0].code == "approval_not_required"
    assert baseline[1] == ()  # 免批链无审批事件


# ---------------------------------------------------------------------------
# Red line 2: real-outcome backfill into the ledger
# ---------------------------------------------------------------------------


def test_real_outcome_backfilled_with_hypotheses_and_rule_ids(monkeypatch, finance_env):
    _runtime(monkeypatch)

    def _install_both():
        _install(
            ("web_search_tool", "on_request", "network"),
            ("agent_message_tool", "never", "write"),
            descriptor_approvals=(("agent_message_tool", "on_request"),),
        )

    _install_both()
    result, _events = _decline_flow(monkeypatch, call_id="call-declined", install=_install_both)
    assert result.code == "approval_declined"

    never_result = tool_authorization_service.authorize_tool_execution(
        tool_name="agent_message_tool",
        tool_call_id="call-msg",
        tool_args={"target_session": "peer", "content": "PING"},
    )
    assert never_result.code == "approval_not_required"

    rows = {row["call_id"]: row for row in _ledger_rows()}
    declined_row = rows["call-declined"]
    assert declined_row["real_outcome"] == "approval_declined"
    assert declined_row["real_outcome_category"] == "declined"
    assert declined_row["baseline_outcome"] == "needs_human"
    assert declined_row["baseline_rule_id"] == "tool-agent-a:shadow.approval.pending:needs_human"
    assert declined_row["baseline_replica_agrees"] == 1
    assert declined_row["agent_id"] == AGENT_ID
    assert declined_row["turn_id"] == "turn-a"
    assert declined_row["session_id"] == "session-a"
    assert declined_row["tool_name"] == "web_search_tool"

    # PA 派发豁免假设：基线免批（never）→ 假设（on_request）需人工。
    msg_row = rows["call-msg"]
    assert msg_row["real_outcome"] == "approval_not_required"
    assert msg_row["baseline_outcome"] == "approved_auto"
    assert msg_row["baseline_rule_id"] == "tool-agent-a:shadow.approval.never:approved_auto"
    assert msg_row["approval_baseline"] == "never"
    assert msg_row["approval_descriptor"] == "on_request"
    assert msg_row["hyp_no_pa_message_override"] == "needs_human"
    assert msg_row["hyp_no_pa_message_override_rule_id"] == (
        "tool-agent-a:shadow.approval.pending:needs_human"
    )


def test_shadow_off_records_nothing(monkeypatch, finance_env):
    monkeypatch.setenv(ev.SHADOW_APPROVALS_ENV, "off")
    _runtime(monkeypatch)
    _install(("agent_message_tool", "never", "write"))
    result = tool_authorization_service.authorize_tool_execution(
        tool_name="agent_message_tool",
        tool_call_id="call-msg",
        tool_args={"target_session": "peer", "content": "PING"},
    )
    assert result.code == "approval_not_required"
    assert _ledger_rows() == []
    assert ev.shadow_approval_telemetry()["engaged"] == 0


# ---------------------------------------------------------------------------
# Red line 3: no decision-template-cache writes from the shadow
# ---------------------------------------------------------------------------


def _registry_payload():
    return {
        "registryVersion": 1,
        "registryFingerprint": "registry-1",
        "descriptors": [
            {
                "name": "grep_search_tool",
                "enabled": True,
                "capabilities": ["read"],
                "risk": "read",
                "approval": "never",
                "aliases": [],
            },
        ],
        "tools": [
            {"name": "grep_search_tool", "enabled": True, "runtimeActive": True, "llmVisible": True},
        ],
    }


def _cache_snapshot():
    with tool_authorization_service._TURN_DECISION_TEMPLATE_LOCK:
        return {
            key: (deepcopy(decision), deepcopy(projection))
            for key, (decision, projection) in tool_authorization_service._TURN_DECISION_TEMPLATES.items()
        }


def test_shadow_does_not_pollute_turn_decision_template_cache(monkeypatch):
    from core.authorization.tool_authorization_service import (
        _resolve_authorization,
        clear_turn_decision_template_cache,
    )

    runtime = {
        "agentId": "agent-cache",
        "turnId": "turn-cache",
        "agent": {"agentId": "agent-cache", "primaryMode": "chat"},
        "toolPolicy": {"policyId": "tool-agent-cache", "allowedTools": ["grep_search_tool"]},
    }
    payload = _registry_payload()

    monkeypatch.delenv(ev.SHADOW_APPROVALS_ENV, raising=False)
    clear_turn_decision_template_cache()
    first = _resolve_authorization(runtime=runtime, registry_payload=payload, generated_at="2026-11-01T00:00:00Z")
    second = _resolve_authorization(runtime=runtime, registry_payload=payload, generated_at="2026-11-01T00:00:00Z")
    assert first.decision_cache_hit is False
    assert second.decision_cache_hit is True
    shadow_on_cache = _cache_snapshot()

    monkeypatch.setenv(ev.SHADOW_APPROVALS_ENV, "off")
    clear_turn_decision_template_cache()
    first_off = _resolve_authorization(runtime=runtime, registry_payload=payload, generated_at="2026-11-01T00:00:00Z")
    second_off = _resolve_authorization(runtime=runtime, registry_payload=payload, generated_at="2026-11-01T00:00:00Z")
    shadow_off_cache = _cache_snapshot()

    # 缓存内容逐字段一致；命中行为一致；影子报文字段不进入缓存键/决策。
    assert list(shadow_on_cache) == list(shadow_off_cache)
    assert shadow_on_cache == shadow_off_cache
    assert first_off.decision.decision_fingerprint == first.decision.decision_fingerprint
    assert second_off.decision_cache_key == second.decision_cache_key
    assert len(shadow_on_cache) == 1


# ---------------------------------------------------------------------------
# Red line 4: never enters quota / counter / budget paths
# ---------------------------------------------------------------------------


def test_call_budget_path_identical_and_shadow_free(monkeypatch, finance_env):
    def _budget_flow():
        _runtime(monkeypatch)
        _install(("agent_message_tool", "never", "write"))
        context = tool_authorization_service.current_execution_authorization()
        assert context is not None
        context.max_calls_per_turn = 1
        first = tool_authorization_service.authorize_tool_execution(
            tool_name="agent_message_tool",
            tool_call_id="call-budget-1",
            tool_args={"target_session": "peer", "content": "PING"},
        )
        count_after_first = context.call_count
        second = tool_authorization_service.authorize_tool_execution(
            tool_name="agent_message_tool",
            tool_call_id="call-budget-2",
            tool_args={"target_session": "peer", "content": "PING"},
        )
        return first, second, count_after_first, context.call_count

    monkeypatch.setenv(ev.SHADOW_APPROVALS_ENV, "off")
    baseline = _budget_flow()
    tool_approvals.reset_tool_approval_state(clear_durable=False)
    monkeypatch.delenv(ev.SHADOW_APPROVALS_ENV, raising=False)
    shadow = _budget_flow()

    assert shadow == baseline
    assert baseline[0].code == "approval_not_required"
    assert baseline[1].code == "call_budget_exhausted"
    assert baseline[2] == 1 and baseline[3] == 1
    # 影子只在审批判定点落账：预算耗尽的第二次调用不产生台账行。
    assert [row["call_id"] for row in _ledger_rows()] == ["call-budget-1"]


# ---------------------------------------------------------------------------
# Red line 5: ledger failure stays silent; the real chain stays green
# ---------------------------------------------------------------------------


def test_ledger_write_failure_keeps_authorization_green(monkeypatch, finance_env):
    def _explode(_record):
        raise RuntimeError("ledger exploded")

    monkeypatch.setattr(ledger, "record_shadow_approval", _explode)
    _runtime(monkeypatch)
    _install(("agent_message_tool", "never", "write"))
    result = tool_authorization_service.authorize_tool_execution(
        tool_name="agent_message_tool",
        tool_call_id="call-msg",
        tool_args={"target_session": "peer", "content": "PING"},
    )
    assert result.allowed is True
    assert result.code == "approval_not_required"
    assert ev.shadow_approval_telemetry()["evaluation_failures"] == 1
    assert ev.shadow_approval_telemetry()["engaged"] == 1


def test_evaluator_failure_keeps_authorization_green(monkeypatch, finance_env):
    from core.authorization import shadow_approval_evaluator as evaluator_module

    def _explode(*_args, **_kwargs):
        raise RuntimeError("evaluator exploded")

    monkeypatch.setattr(evaluator_module, "evaluate_shadow_approvals", _explode)
    _runtime(monkeypatch)
    _install(("agent_message_tool", "never", "write"))
    result = tool_authorization_service.authorize_tool_execution(
        tool_name="agent_message_tool",
        tool_call_id="call-msg",
        tool_args={"target_session": "peer", "content": "PING"},
    )
    assert result.allowed is True
    assert result.code == "approval_not_required"
    assert ev.shadow_approval_telemetry()["evaluation_failures"] == 1


# ---------------------------------------------------------------------------
# Purity at the mount: no storage reads on the shadow side
# ---------------------------------------------------------------------------


def test_mount_shadow_does_not_reach_agent_storage(monkeypatch, finance_env):
    def _explode(*_args, **_kwargs):
        raise RuntimeError("shadow must not read agent storage")

    monkeypatch.setattr(tool_approvals, "_canonical_agent_configs", _explode)
    _runtime(monkeypatch)
    _install(
        ("agent_message_tool", "never", "write"),
        descriptor_approvals=(("agent_message_tool", "on_request"),),
    )
    result = tool_authorization_service.authorize_tool_execution(
        tool_name="agent_message_tool",
        tool_call_id="call-msg",
        tool_args={"target_session": "peer", "content": "PING"},
    )
    assert result.code == "approval_not_required"
    rows = _ledger_rows()
    assert rows and rows[0]["hyp_no_pa_message_override"] == "needs_human"
