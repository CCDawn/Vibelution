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
    real_infer = decision.infer
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
    return {
        **paper_env,
        "agentId": agent_id,
        "calls": calls,
        "payload": payload,
        "real_infer": real_infer,
    }


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


def test_failed_proposal_readback_keeps_account_equity(proposal_env, monkeypatch):
    calls = []

    def fail(*args):
        calls.append(args[-1])
        raise RebalanceError("模型暂时不可用")

    monkeypatch.setattr(decision, "infer", fail)
    failed = service.create_proposal(proposal_env["agentId"], proposal_env["payload"])
    reread = service.get_proposal(proposal_env["agentId"], failed["proposalId"])

    assert failed["status"] == "failed"
    assert len(calls) == 1
    assert failed["metrics"]["equityYuan"] == calls[0]["account"]["equityYuan"]
    assert reread["metrics"]["equityYuan"] == calls[0]["account"]["equityYuan"]
    assert failed["metrics"]["cashAfterYuan"] == calls[0]["account"]["cashYuan"]


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


def _mock_model_response(monkeypatch, response_body):
    from types import SimpleNamespace

    calls = []
    monkeypatch.setattr(decision, "get_llm_client", lambda **_kwargs: object())

    def invoke(*_args, **_kwargs):
        calls.append(1)
        return SimpleNamespace(
            content=json.dumps(response_body, ensure_ascii=False),
            response_metadata={},
        )

    monkeypatch.setattr(decision, "invoke_llm", invoke)
    return calls


def test_infer_filters_numeric_sentences_and_preserves_qualitative_text(monkeypatch):
    response_body = {
        "targets": [
            {
                "symbol": "sh600519",
                "weightPct": 20.0,
                "reason": "当前仓位34.8%，建议降低。基本面证据仍不充分，应限制集中暴露。",
            }
        ],
        "summaryReason": "预计净值84.9万元，现金保留。研究报告显示经营稳健。组合需保持谨慎。",
    }
    calls = _mock_model_response(monkeypatch, response_body)

    result = decision.infer(
        "agent", "proposal", "test/model", object(), {"symbols": ["sh600519"]}
    )

    assert result["targets"][0]["weightPct"] == 20.0
    assert result["summaryReason"].startswith("研究报告显示经营稳健。组合需保持谨慎。")
    assert result["targets"][0]["reason"] == "基本面证据仍不充分，应限制集中暴露。"
    assert "84.9万元" not in result["summaryReason"]
    assert "34.8%" not in result["targets"][0]["reason"]
    assert "未核验数值" in result["summaryReason"]
    assert len(calls) == 1


def test_numeric_reason_filter_does_not_change_allocation_or_paper_ledger(
    proposal_env, monkeypatch
):
    response_body = {
        "targets": [
            {
                "symbol": "sh600519",
                "weightPct": 20.0,
                "reason": "经营质量稳健。当前仓位34.8%，建议降低。",
            }
        ],
        "summaryReason": "组合分散并保留现金。",
    }
    calls = _mock_model_response(monkeypatch, response_body)
    monkeypatch.setattr(decision, "infer", proposal_env["real_infer"])
    agent_id = proposal_env["agentId"]
    before = paper.read_rebalance_context(agent_id)

    proposal = service.create_proposal(agent_id, proposal_env["payload"])
    saved = store.read(agent_id, proposal["proposalId"])
    expected = build_plan(
        saved["_context"],
        [{"symbol": "sh600519", "weightPct": 20.0, "reason": "无数值说明"}],
        saved["_quotes"],
        saved["policy"],
        now=NOW,
    )
    order_fields = (
        "symbol",
        "side",
        "quantity",
        "priceYuan",
        "grossAmountYuan",
        "feeYuan",
    )

    assert proposal["status"] == "ready"
    assert proposal["targets"][0]["weightPct"] == 20.0
    assert proposal["targets"][0]["reason"] == "经营质量稳健。"
    assert "未核验数值" in proposal["summaryReason"]
    assert all("34.8%" not in order["reason"] for order in proposal["orders"])
    assert [tuple(order[field] for field in order_fields) for order in proposal["orders"]] == [
        tuple(order[field] for field in order_fields) for order in expected["orders"]
    ]
    assert proposal["metrics"] == expected["metrics"]
    assert paper.read_rebalance_context(agent_id) == before
    assert len(calls) == 1


def test_infer_shows_explicit_notice_when_all_reason_sentences_are_filtered(monkeypatch):
    notice = "模型说明含未核验数值，已省略；请核对研究报告与风控。"
    response_body = {
        "targets": [
            {"symbol": "sh600519", "weightPct": 20.0, "reason": "当前仓位三成，应减仓。"}
        ],
        "summaryReason": "净值84.9万元。现金比例25%。",
    }
    calls = _mock_model_response(monkeypatch, response_body)

    result = decision.infer(
        "agent", "proposal", "test/model", object(), {"symbols": ["sh600519"]}
    )

    assert result["summaryReason"] == notice
    assert result["targets"][0]["reason"] == notice
    assert result["targets"][0]["weightPct"] == 20.0
    assert len(calls) == 1


def test_infer_still_rejects_invalid_structured_target_weight(monkeypatch):
    response_body = {
        "targets": [
            {"symbol": "sh600519", "weightPct": 101.0, "reason": "当前仓位三成，应减仓。"}
        ],
        "summaryReason": "保留现金并控制风险。",
    }
    _mock_model_response(monkeypatch, response_body)

    with pytest.raises(RebalanceError, match="目标仓位须在0到100之间"):
        decision.infer(
            "agent", "proposal", "test/model", object(), {"symbols": ["sh600519"]}
        )
