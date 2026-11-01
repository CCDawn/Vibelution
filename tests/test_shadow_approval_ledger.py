"""Shadow-approval ledger: STRICT/CHECK hygiene, real-outcome merge,
never-raise writes, one-time quick_check gate, row-cap truncation, and the
read-only summary aggregation feeding the endpoint."""

from __future__ import annotations

import sqlite3

import pytest

from core.authorization import shadow_approval_evaluator as ev
from core.web.services import shadow_approval_ledger as ledger
from tests.test_financial_knowledge_service import finance_env  # noqa: F401 - workspace isolation fixture

finance_env = finance_env

AGENT_ID = "agent-a"
TURN_ID = "turn-a"


@pytest.fixture(autouse=True)
def _reset_shadow_state(monkeypatch):
    monkeypatch.delenv(ev.SHADOW_APPROVALS_ENV, raising=False)
    ev.reset_shadow_telemetry()
    yield
    ev.reset_shadow_telemetry()


def _record(call_id: str, *, baseline="approved_auto", h1="approved_auto", h2="approved_auto",
            h3="approved_auto", real="approval_not_required", tool="agent_message_tool",
            baseline_rule="tool-agent-a:shadow.approval.never:approved_auto",
            h1_rule="", h2_rule="", h3_rule="") -> dict:
    return {
        "agentId": AGENT_ID,
        "turnId": TURN_ID,
        "callId": call_id,
        "sessionId": "session-a",
        "toolName": tool,
        "risk": "write",
        "permissionPreset": "request_approval",
        "approvalBaseline": "never",
        "approvalDescriptor": "on_request",
        "baselineOutcome": baseline,
        "baselineRuleId": baseline_rule or f"tool-agent-a:gate:{baseline}",
        "hypNoPaMessageOverride": h1,
        "hypNoPaMessageOverrideRuleId": h1_rule or f"tool-agent-a:gate:{h1}",
        "hypNoExternalWriteOverride": h2,
        "hypNoExternalWriteOverrideRuleId": h2_rule or f"tool-agent-a:gate:{h2}",
        "hypNoActionWindow": h3,
        "hypNoActionWindowRuleId": h3_rule or f"tool-agent-a:gate:{h3}",
        "realOutcome": real,
        "baselineReplicaAgrees": True,
    }


# ---------------------------------------------------------------------------
# Schema hygiene
# ---------------------------------------------------------------------------


def test_record_and_read_roundtrip(finance_env):
    ledger.record_shadow_approval(_record("call-1"))
    summary = ledger.read_shadow_approval_summary()
    assert summary["degraded"] is False
    assert summary["rowCount"] == 1
    assert summary["enabled"] is True
    row_checked = False
    for hypothesis in summary["hypotheses"]:
        if hypothesis["key"] == ev.HYPOTHESIS_NO_PA_MESSAGE_OVERRIDE:
            row_checked = True
    assert row_checked


def test_strict_table_rejects_unknown_outcome(finance_env):
    ledger.record_shadow_approval(_record("call-ok"))
    path = ledger.ledger_database_path()
    with sqlite3.connect(str(path)) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO shadow_approvals (agent_id, turn_id, call_id, baseline_outcome,"
                " hyp_no_pa_message_override, hyp_no_external_write_override,"
                " hyp_no_action_window, baseline_replica_agrees, created_at, created_at_ms)"
                " VALUES ('a','t','bad','approved_forever','approved_auto','approved_auto',"
                "'approved_auto',1,'2026-01-01T00:00:00Z',0)"
            )


def test_real_outcome_backfill_merge_is_idempotent(finance_env):
    ledger.record_shadow_approval(
        _record("call-1", baseline="needs_human", real="approval_declined", tool="web_search_tool")
    )
    # 同一 (agent, turn, call) 重放以最新值合并（真实终态回填口径）。
    ledger.record_shadow_approval(
        _record("call-1", baseline="needs_human", real="approval_declined", tool="web_search_tool")
    )
    summary = ledger.read_shadow_approval_summary()
    assert summary["rowCount"] == 1


def test_quick_check_marker_set_once_after_first_read(finance_env):
    ledger.record_shadow_approval(_record("call-1"))
    assert ledger.read_shadow_approval_summary()["rowCount"] == 1
    path = ledger.ledger_database_path()
    with sqlite3.connect(str(path)) as connection:
        marker = connection.execute(
            "SELECT quick_check_at FROM ledger_meta WHERE singleton=1"
        ).fetchone()[0]
    assert str(marker).strip()


# ---------------------------------------------------------------------------
# Aggregation correctness (per-hypothesis pending deltas + samples)
# ---------------------------------------------------------------------------


def test_summary_counts_extra_and_avoided_pending_per_hypothesis(finance_env):
    # PA 豁免假设会多出的 pending：基线免批 → 假设需人工。
    ledger.record_shadow_approval(_record("call-pa", h1="needs_human"))
    # 外部写假设反而免掉的 pending：基线人工超时 → 假设自动批准。
    ledger.record_shadow_approval(
        _record(
            "call-ext",
            baseline="needs_human",
            h1="needs_human",
            h2="approved_auto",
            h3="needs_human",
            real="approval_timeout",
            tool="write_file_tool",
            baseline_rule="tool-agent-a:shadow.approval.pending:needs_human",
        )
    )
    # action window 假设会多出的 pending：基线窗口直批 → 假设需人工。
    ledger.record_shadow_approval(
        _record(
            "call-window",
            baseline="approved_auto",
            h3="needs_human",
            real="approved_for_action_window",
            tool="personal_assistant_manage_tool",
            baseline_rule="tool-agent-a:shadow.approval.action_window:approved_auto",
        )
    )
    # 无区分度行：不计数。
    ledger.record_shadow_approval(_record("call-flat"))

    summary = ledger.read_shadow_approval_summary()
    assert summary["rowCount"] == 4
    by_key = {item["key"]: item for item in summary["hypotheses"]}
    pa = by_key[ev.HYPOTHESIS_NO_PA_MESSAGE_OVERRIDE]
    ext = by_key[ev.HYPOTHESIS_NO_EXTERNAL_WRITE_OVERRIDE]
    window = by_key[ev.HYPOTHESIS_NO_ACTION_WINDOW]
    assert pa["extraPendingCount"] == 1 and pa["avoidedPendingCount"] == 0
    assert ext["extraPendingCount"] == 0 and ext["avoidedPendingCount"] == 1
    assert window["extraPendingCount"] == 1 and window["avoidedPendingCount"] == 0

    extra_sample = pa["recentSamples"]["extraPending"][0]
    assert extra_sample["toolName"] == "agent_message_tool"
    assert extra_sample["baselineOutcome"] == "approved_auto"
    assert extra_sample["hypothesisOutcome"] == "needs_human"
    assert extra_sample["ruleId"] == "tool-agent-a:gate:needs_human"
    assert extra_sample["realOutcome"] == "approval_not_required"
    avoided_sample = ext["recentSamples"]["avoidedPending"][0]
    assert avoided_sample["realOutcome"] == "approval_timeout"

    # 遥测计数进入聚合响应（有界固定键 + 失败率）。
    assert summary["telemetry"]["engaged"] == 0  # 台账直测不经过挂载点
    ledger.record_shadow_approval(_record("call-x"))
    assert ledger.read_shadow_approval_summary()["rowCount"] == 5


def test_summary_degrades_to_empty_view_when_ledger_missing(finance_env):
    # 未写过任何行的全新 workspace：库不存在 → 静默空视图 + 降级标记。
    summary = ledger.read_shadow_approval_summary()
    assert summary["rowCount"] == 0
    assert summary["hypotheses"] == []
    assert summary["degraded"] is True


def test_summary_degrades_when_database_corrupted(finance_env):
    ledger.record_shadow_approval(_record("call-1"))
    path = ledger.ledger_database_path()
    connection = sqlite3.connect(str(path))
    connection.execute("PRAGMA writable_schema=ON")
    connection.execute("UPDATE sqlite_master SET sql='CREATE TABLE shadow_approvals(x)'"
                       " WHERE name='shadow_approvals'")
    connection.commit()
    connection.close()
    summary = ledger.read_shadow_approval_summary()
    assert summary["rowCount"] == 0
    assert summary["degraded"] is True


# ---------------------------------------------------------------------------
# Never-raise writes
# ---------------------------------------------------------------------------


def test_record_failure_is_silent_and_counted(finance_env, monkeypatch):
    def _explode():
        raise RuntimeError("disk gone")

    monkeypatch.setattr(ledger, "_open_writable", _explode)
    ledger.record_shadow_approval(_record("call-1"))  # 不得抛出
    telemetry = ev.shadow_approval_telemetry()
    assert telemetry["ledger_write_failures"] == 1
    assert telemetry["recorded"] == 0


def test_reset_failure_is_silent(finance_env, monkeypatch):
    def _explode():
        raise RuntimeError("disk gone")

    monkeypatch.setattr(ledger, "_open_writable", _explode)
    ledger.reset_shadow_approval_ledger()  # 不得抛出


def test_record_with_invalid_shape_is_silent(finance_env):
    ledger.record_shadow_approval(None)
    ledger.record_shadow_approval({"agentId": "", "callId": ""})
    ledger.record_shadow_approval(_record("call-bad", baseline="bogus_outcome"))
    assert ev.shadow_approval_telemetry()["ledger_write_failures"] >= 1


# ---------------------------------------------------------------------------
# Row-cap truncation
# ---------------------------------------------------------------------------


def test_row_cap_truncates_oldest_rows(finance_env, monkeypatch):
    monkeypatch.setattr(ledger, "MAX_LEDGER_ROWS", 3)
    for index in range(5):
        ledger.record_shadow_approval(_record(f"call-{index}"))
    summary = ledger.read_shadow_approval_summary()
    assert summary["rowCount"] == 3
    rows = []
    connection = sqlite3.connect(str(ledger.ledger_database_path()))
    try:
        rows = list(connection.execute("SELECT call_id FROM shadow_approvals ORDER BY call_id"))
    finally:
        connection.close()
    assert [row[0] for row in rows] == ["call-2", "call-3", "call-4"]


# ---------------------------------------------------------------------------
# Endpoint projection (read-only aggregation; no action semantics)
# ---------------------------------------------------------------------------


def test_summary_endpoint_projects_readonly_response(finance_env):
    from core.web.routes import shadow_approvals as route

    ledger.record_shadow_approval(_record("call-pa", h1="needs_human"))
    payload = route.shadow_approvals_summary()
    assert payload["enabled"] is True
    assert payload["degraded"] is False
    assert payload["rowCount"] == 1
    assert "actions" not in payload
    assert "humanAttention" not in payload
    pa = [item for item in payload["hypotheses"] if item["key"] == ev.HYPOTHESIS_NO_PA_MESSAGE_OVERRIDE][0]
    assert pa["extraPendingCount"] == 1
    assert pa["recentSamples"]["extraPending"][0]["ruleId"].startswith("tool-agent-a:")
    assert payload["telemetry"]["failureRateMilli"] == 0


def test_summary_endpoint_degrades_silently(finance_env, monkeypatch):
    from core.web.routes import shadow_approvals as route

    def _explode():
        raise RuntimeError("ledger gone")

    monkeypatch.setattr(ledger, "read_shadow_approval_summary", _explode)
    payload = route.shadow_approvals_summary()
    assert payload == {
        "enabled": True,
        "rowCount": 0,
        "hypotheses": [],
        "degraded": True,
    }


def test_router_module_is_registered():
    from core.web import router_registry

    assert "core.web.routes.shadow_approvals" in router_registry._ROUTE_MODULE_NAMES
