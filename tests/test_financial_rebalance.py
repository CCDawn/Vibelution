"""Research proposal approval fences and deterministic portfolio risk."""

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from core.web.services.financial_paper import ledger
from core.web.services.financial_paper import rebalance as paper
from core.web.services.financial_rebalance import decision, service, store
from core.web.services.financial_rebalance.risk import (
    DEFAULT_POLICY,
    RebalanceConflict,
    RebalanceError,
    build_plan,
    normalize_targets,
)
from tests.test_financial_paper_service import finance_env as _finance_env
from tests.test_financial_paper_service import paper_env as _paper_env

finance_env = _finance_env
paper_env = _paper_env
NOW = datetime(2026, 10, 5, 7, 0, 30, tzinfo=timezone.utc)


@pytest.fixture
def proposal_env(paper_env, monkeypatch):
    agent_id = paper_env["agent"]["agentId"]
    ledger.open_account(agent_id)
    monkeypatch.setattr(service, "_now", lambda: NOW)
    monkeypatch.setattr(ledger, "_utc_now", lambda: NOW)
    monkeypatch.setattr(decision, "resolve_model", lambda _: ("test/model", object()))
    monkeypatch.setattr(service.reports, "export_financial_report", lambda *args, **kwargs: {"content": json.dumps({"content": "测试报告仅作为研究资料", "completedAt": "2026-10-05T06:00:00+00:00"})})
    calls = []

    def infer(*args):
        calls.append(args[-1])
        return {"targets": [{"symbol": symbol, "weightPct": 20.0, "reason": "研究依据支持小仓位模拟"} for symbol in args[-1]["symbols"]], "summaryReason": "保留现金，限制单股仓位"}

    monkeypatch.setattr(decision, "infer", infer)
    payload = {"clientRequestId": str(uuid4()), "symbols": ["sh600519"], "reports": [{"sessionId": "report-session", "turnId": "report-turn"}], "instruction": "控制回撤的模拟组合", "policy": dict(DEFAULT_POLICY)}
    return {**paper_env, "agentId": agent_id, "calls": calls, "payload": payload}


def test_generation_is_read_only_and_idempotent_then_approval_executes_once(proposal_env):
    agent_id, payload = proposal_env["agentId"], proposal_env["payload"]
    before = paper.read_rebalance_context(agent_id)
    proposal = service.create_proposal(agent_id, payload)
    assert proposal["status"] == "ready"
    assert proposal["proposalId"] == payload["clientRequestId"]
    assert not any(key.startswith("_") for key in proposal)
    assert paper.read_rebalance_context(agent_id) == before
    assert service.create_proposal(agent_id, payload) == proposal
    assert len(proposal_env["calls"]) == 1
    assert proposal_env["calls"][0]["reports"][0]["turnId"] == "report-turn"
    approved = service.approve_proposal(agent_id, proposal["proposalId"], {"planHash": proposal["planHash"], "confirmSimulation": True})
    assert approved["status"] == "executed"
    assert approved["execution"]["batchId"] == proposal["proposalId"]
    after = paper.read_rebalance_context(agent_id)
    assert after["ledgerFingerprint"] != before["ledgerFingerprint"]
    assert after["cashYuan"] == proposal["metrics"]["cashAfterYuan"]
    assert service.approve_proposal(agent_id, proposal["proposalId"], {"planHash": proposal["planHash"], "confirmSimulation": True}) == approved
    assert paper.read_rebalance_context(agent_id) == after


def test_request_conflict_does_not_call_model_again(proposal_env):
    service.create_proposal(proposal_env["agentId"], proposal_env["payload"])
    with pytest.raises(RebalanceConflict):
        service.create_proposal(proposal_env["agentId"], {**proposal_env["payload"], "instruction": "另一请求"})
    assert len(proposal_env["calls"]) == 1


def test_unknown_inference_is_not_automatically_retried(proposal_env, monkeypatch):
    calls = []

    def fail(*args):
        calls.append(1)
        raise TimeoutError("private provider details")

    monkeypatch.setattr(decision, "infer", fail)
    first = service.create_proposal(proposal_env["agentId"], proposal_env["payload"])
    assert first["status"] == "failed"
    assert "private" not in first["error"]
    second = service.create_proposal(proposal_env["agentId"], proposal_env["payload"])
    assert second == first
    assert len(calls) == 1


def test_stale_market_data_is_rejected_before_model_call(proposal_env, monkeypatch):
    monkeypatch.setattr(service, "_now", lambda: NOW + timedelta(days=5))
    with pytest.raises(RebalanceError, match="尚未调用模型"):
        service.create_proposal(proposal_env["agentId"], proposal_env["payload"])
    assert proposal_env["calls"] == []


def test_report_access_failure_never_creates_orders_or_calls_model(proposal_env, monkeypatch):
    def reject(*args, **kwargs):
        raise service.reports.FinancialReportNotFound("报告不属于该Agent")

    monkeypatch.setattr(service.reports, "export_financial_report", reject)
    before = paper.read_rebalance_context(proposal_env["agentId"])
    with pytest.raises(service.reports.FinancialReportNotFound):
        service.create_proposal(proposal_env["agentId"], proposal_env["payload"])
    assert proposal_env["calls"] == []
    assert paper.read_rebalance_context(proposal_env["agentId"]) == before


def test_same_report_with_whitespace_is_still_a_duplicate(proposal_env):
    payload = {**proposal_env["payload"], "reports": [{"sessionId": "s", "turnId": "t"}, {"sessionId": " s ", "turnId": " t "}]}
    with pytest.raises(RebalanceError, match="不能重复"):
        service.create_proposal(proposal_env["agentId"], payload)
    assert proposal_env["calls"] == []


def test_approval_rejects_changed_account_and_expired_quotes(proposal_env, monkeypatch):
    agent_id = proposal_env["agentId"]
    proposal = service.create_proposal(agent_id, proposal_env["payload"])
    body = {"planHash": proposal["planHash"], "confirmSimulation": True}
    monkeypatch.setattr(service, "_now", lambda: NOW + timedelta(minutes=3))
    with pytest.raises(RebalanceConflict, match="过期"):
        service.approve_proposal(agent_id, proposal["proposalId"], body)
    monkeypatch.setattr(service, "_now", lambda: NOW)
    ledger.submit_order(agent_id, client_order_id=str(uuid4()), symbol="sh600519", side="buy", quantity=100, reason="改变账户")
    before = paper.read_rebalance_context(agent_id)
    with pytest.raises(RebalanceConflict, match="账户已变化"):
        service.approve_proposal(agent_id, proposal["proposalId"], body)
    assert paper.read_rebalance_context(agent_id) == before


def test_modified_sources_block_approval(proposal_env, monkeypatch):
    agent_id = proposal_env["agentId"]
    proposal = service.create_proposal(agent_id, proposal_env["payload"])
    monkeypatch.setattr(service.reports, "export_financial_report", lambda *args, **kwargs: {"content": json.dumps({"content": "依据已变更", "completedAt": "2026-10-05T06:00:00+00:00"})})
    with pytest.raises(RebalanceConflict, match="研究依据已变化"):
        service.approve_proposal(agent_id, proposal["proposalId"], {"planHash": proposal["planHash"], "confirmSimulation": True})


def test_approval_recomputes_hash_of_persisted_plan(proposal_env):
    agent_id = proposal_env["agentId"]
    proposal = service.create_proposal(agent_id, proposal_env["payload"])
    saved = store.read(agent_id, proposal["proposalId"])
    saved["policy"]["maxTurnoverPct"] = 200.0
    store.write(agent_id, saved)
    before = paper.read_rebalance_context(agent_id)
    with pytest.raises(RebalanceConflict, match="内容校验失败"):
        service.approve_proposal(agent_id, proposal["proposalId"], {"planHash": proposal["planHash"], "confirmSimulation": True})
    assert paper.read_rebalance_context(agent_id) == before


def test_new_preview_invalidates_old_approval_and_applies_risk(proposal_env):
    agent_id = proposal_env["agentId"]
    proposal = service.create_proposal(agent_id, proposal_env["payload"])
    changed = service.preview_proposal(agent_id, proposal["proposalId"], {"targets": [{"symbol": "sh600519", "weightPct": 50.0, "reason": "过高目标"}], "policy": DEFAULT_POLICY})
    assert changed["status"] == "blocked"
    assert "手动调整" in changed["summaryReason"]
    assert changed["summaryReason"] != proposal["summaryReason"]
    assert not next(check for check in changed["riskChecks"] if check["code"] == "target_concentration")["passed"]
    with pytest.raises(RebalanceConflict, match="方案已变化"):
        service.approve_proposal(agent_id, proposal["proposalId"], {"planHash": proposal["planHash"], "confirmSimulation": True})
    assert len(proposal_env["calls"]) == 1


def test_ledger_result_recovers_proposal_after_artifact_write_failure(proposal_env, monkeypatch):
    agent_id = proposal_env["agentId"]
    proposal = service.create_proposal(agent_id, proposal_env["payload"])
    original = store.write
    monkeypatch.setattr(store, "write", lambda *args: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        service.approve_proposal(agent_id, proposal["proposalId"], {"planHash": proposal["planHash"], "confirmSimulation": True})
    monkeypatch.setattr(store, "write", original)
    recovered = service.get_proposal(agent_id, proposal["proposalId"])
    assert recovered["status"] == "executed"
    before = paper.read_rebalance_context(agent_id)
    assert service.approve_proposal(agent_id, proposal["proposalId"], {"planHash": proposal["planHash"], "confirmSimulation": True})["status"] == "executed"
    assert paper.read_rebalance_context(agent_id) == before


def test_risk_refuses_missing_stale_quotes_and_locked_shares(proposal_env):
    context = {"cashYuan": "0.00", "positions": [{"symbol": "sh600519", "quantity": 1000, "sellableQuantity": 0}]}
    targets = [{"symbol": "sh600519", "weightPct": 0.0, "reason": "清仓"}]
    assert not build_plan(context, targets, {}, DEFAULT_POLICY, now=NOW)["canApprove"]
    quotes = service._quotes(["sh600519"])
    plan = build_plan(context, targets, quotes, DEFAULT_POLICY, now=NOW + timedelta(days=5))
    failed = {row["code"] for row in plan["riskChecks"] if not row["passed"]}
    assert {"quote_freshness", "sellable"} <= failed


@pytest.mark.parametrize("weights", [[True], [float("nan")], [float("inf")], [-1], [101]])
def test_target_numbers_fail_closed(weights):
    with pytest.raises(RebalanceError):
        normalize_targets([{"symbol": "sh600519", "weightPct": weights[0], "reason": "test"}], ["sh600519"])


def test_build_plan_exposes_deterministic_current_account_valuation():
    context = {
        "cashYuan": "704320.32",
        "positions": [
            {"symbol": "sh600519", "quantity": 100, "sellableQuantity": 100}
        ],
    }
    quotes = {
        "sh600519": {
            "name": "测试股票",
            "priceYuan": "2955.91",
            "timestamp": NOW.isoformat(),
            "fetchedAt": NOW.isoformat(),
        }
    }
    plan = build_plan(
        context,
        [{"symbol": "sh600519", "weightPct": 20.0, "reason": "控制风险"}],
        quotes,
        DEFAULT_POLICY,
        now=NOW,
    )

    valuation = plan["accountValuation"]
    assert valuation["cashYuan"] == "704320.32"
    assert valuation["marketValueYuan"] == "295591.00"
    assert valuation["equityYuan"] == "999911.32"
    assert valuation["cashWeightPct"] == "70.44"
    assert valuation["positions"] == [
        {
            "symbol": "sh600519",
            "quantity": 100,
            "sellableQuantity": 100,
            "priceYuan": "2955.91",
            "marketValueYuan": "295591.00",
            "weightPct": "29.56",
        }
    ]


def test_model_receives_build_plan_account_valuation_instead_of_raw_context(
    proposal_env, monkeypatch
):
    context = {
        "ledgerFingerprint": "f" * 64,
        "cashYuan": "704320.32",
        "positions": [
            {"symbol": "sh600519", "quantity": 100, "sellableQuantity": 100}
        ],
    }
    quote = {
        "name": "测试股票",
        "priceYuan": "2955.91",
        "timestamp": NOW.isoformat(),
        "fetchedAt": NOW.isoformat(),
    }
    monkeypatch.setattr(service.paper, "read_rebalance_context", lambda _agent_id: context)
    monkeypatch.setattr(service, "_quotes", lambda symbols: {symbol: quote for symbol in symbols})

    proposal = service.create_proposal(proposal_env["agentId"], proposal_env["payload"])

    model_input = proposal_env["calls"][0]
    assert proposal["status"] == "ready"
    assert model_input["account"]["equityYuan"] == "999911.32"
    assert model_input["account"]["cashYuan"] == "704320.32"
    assert model_input["account"]["positions"][0]["weightPct"] == "29.56"
    assert "ledgerFingerprint" not in model_input["account"]
    assert "ledgerFingerprint" not in json.dumps(model_input, ensure_ascii=False)


def test_infer_keeps_numeric_target_fields_and_requires_qualitative_reasons(monkeypatch):
    from types import SimpleNamespace

    response_body = {
        "targets": [
            {"symbol": "sh600519", "weightPct": 20.0, "reason": "关注单一股票的经营质量和风险暴露"}
        ],
        "summaryReason": "从业绩韧性和流动性两个方面，对统一标的采取审慎建议",
    }
    seen_messages = []
    monkeypatch.setattr(decision, "get_llm_client", lambda **_kwargs: object())

    def invoke(_client, messages, **_kwargs):
        seen_messages.extend(messages)
        return SimpleNamespace(
            content=json.dumps(response_body, ensure_ascii=False),
            response_metadata={},
        )

    monkeypatch.setattr(decision, "invoke_llm", invoke)
    result = decision.infer(
        "agent",
        "proposal",
        "test/model",
        object(),
        {
            "symbols": ["sh600519"],
            "account": {
                "cashYuan": "704320.32",
                "marketValueYuan": "295591.00",
                "equityYuan": "999911.32",
                "cashWeightPct": "70.44",
                "positions": [{"symbol": "sh600519", "weightPct": "29.56"}],
            },
        },
    )

    assert result["targets"][0]["weightPct"] == 20.0
    assert "权威" in seen_messages[0]["content"]
    assert "定性" in seen_messages[0]["content"]


@pytest.mark.parametrize(
    ("summary_reason", "target_reason"),
    [
        ("净值约84.9万元，保留现金", "控制波动"),
        ("保留现金，控制风险", "当前仓位34.8%，建议降低"),
        ("配置保持谨慎", "仓位约三成，控制风险"),
    ],
)
def test_infer_rejects_numeric_claims_in_visible_reasons(
    summary_reason, target_reason, monkeypatch
):
    from types import SimpleNamespace

    response_body = {
        "targets": [
            {"symbol": "sh600519", "weightPct": 20.0, "reason": target_reason}
        ],
        "summaryReason": summary_reason,
    }
    monkeypatch.setattr(decision, "get_llm_client", lambda **_kwargs: object())
    monkeypatch.setattr(
        decision,
        "invoke_llm",
        lambda *_args, **_kwargs: SimpleNamespace(
            content=json.dumps(response_body, ensure_ascii=False),
            response_metadata={},
        ),
    )

    with pytest.raises(RebalanceError, match="定性说明"):
        decision.infer(
            "agent", "proposal", "test/model", object(), {"symbols": ["sh600519"]}
        )
