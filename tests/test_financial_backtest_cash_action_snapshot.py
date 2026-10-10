"""Cross-surface frozen dividend provenance, slicing and replay contracts."""

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest

from core.web.routes.financial_backtest_models import (
    FinancialBacktestPreview,
    FinancialBacktestRun,
)
from core.web.services.financial_backtest import (
    cash_action_snapshot,
    data,
    decision,
    runtime,
    service,
    walk_forward_data,
)
from core.web.services.financial_backtest.corporate_actions import (
    CASH_DIVIDEND_RULE_V1,
    DividendLedger,
    freeze_cash_dividend_artifact,
)


def _prices(close: str) -> dict:
    from decimal import Decimal

    value = Decimal(close)
    return {
        "open": close,
        "close": close,
        "high": str(value + 1),
        "low": str(value - 1),
    }


def _draft() -> dict:
    excerpt = (
        "每股派发现金红利0.50元；登记日2024年4月10日，除息日4月11日，到账日4月12日。"
    )
    return {
        "schemaVersion": 1,
        "ruleVersion": CASH_DIVIDEND_RULE_V1,
        "symbol": "sh600036",
        "coverageStartDate": "2024-04-09",
        "coverageEndDate": "2024-04-12",
        "coverageStatus": "complete",
        "coverageEvidence": {
            "source": "cninfo",
            "queryStartDate": "2022-04-09",
            "queryEndDate": "2024-04-12",
            "pagesRead": 1,
            "terminalPage": True,
            "noticeIds": ["1234567"],
        },
        "events": [
            {
                "symbol": "sh600036",
                "actionId": "cash-1",
                "noticeId": "1234567",
                "publishedDate": "2024-03-20",
                "title": "年度现金分红实施公告",
                "sourceUrl": "https://static.cninfo.com.cn/finalpage/2024-03-20/1234567.PDF",
                "pdfSha256": "a" * 64,
                "recordDate": "2024-04-10",
                "exDate": "2024-04-11",
                "paymentDate": "2024-04-12",
                "cashPerShare": "0.50",
                "stockDividendRatio": "0",
                "capitalizationRatio": "0",
                "evidencePages": [
                    {
                        "page": 1,
                        "excerpt": excerpt,
                        "excerptSha256": hashlib.sha256(excerpt.encode()).hexdigest(),
                    }
                ],
            }
        ],
        "priceValidation": {
            "detectedDates": ["2024-04-11"],
            "pairs": [
                {
                    "exDate": "2024-04-11",
                    "previousDate": "2024-04-10",
                    "rawPrevious": _prices("10.00"),
                    "rawCurrent": _prices("9.50"),
                    "qfqPrevious": _prices("9.50"),
                    "qfqCurrent": _prices("9.50"),
                }
            ],
        },
    }


def _snapshot() -> data.BacktestSnapshot:
    days = ["2024-04-09", "2024-04-10", "2024-04-11", "2024-04-12"]
    candles = tuple(
        data.Candle(day, price, price + 1, price - 1, price, 1_000_000)
        for day, price in zip(days, [10, 10, 9.5, 9.5], strict=True)
    )
    actions = freeze_cash_dividend_artifact(_draft())
    coverage = data.BacktestCoverage(
        days[0],
        days[-1],
        days[0],
        days[-1],
        days[0],
        days[-1],
        4,
        0,
        (
            {
                "startDate": days[0],
                "endDate": days[-1],
                "rawBars": 4,
                "qfqBars": 4,
                "calendarBars": 4,
            },
        ),
        "tencent_index_checked",
        "sh000001",
        True,
    )
    return data.BacktestSnapshot(
        "sh600036",
        days[0],
        days[-1],
        candles,
        (),
        "frozen fixture",
        "https://gu.qq.com/sh600036/gp",
        "2024-04-13T00:00:00+08:00",
        data._stable_hash(candles, "sh600036", days[0], days[-1], actions),
        coverage,
        "verified_cash_dividends",
        (days[2],),
        (),
        actions,
    )


def test_offline_restore_preserves_actions_and_detects_event_or_candle_tampering():
    snapshot = _snapshot()
    restored = runtime._restore_snapshot(json.loads(json.dumps(snapshot.to_dict())))
    assert restored == snapshot
    tampered = snapshot.to_dict()
    tampered["corporateActions"]["events"][0]["cashPerShare"] = "0.51"
    with pytest.raises(ValueError, match="冻结"):
        runtime._restore_snapshot(tampered)
    tampered = snapshot.to_dict()
    tampered["candles"][1]["close"] = 10.1
    with pytest.raises(ValueError, match="冻结"):
        runtime._restore_snapshot(tampered)


def test_matching_ex_date_with_wrong_cash_amount_cannot_bypass_factor_guard():
    draft = _draft()
    draft["events"][0]["cashPerShare"] = "0.25"
    actions = freeze_cash_dividend_artifact(draft)
    snapshot = replace(_snapshot(), corporate_actions=actions)
    with pytest.raises(data.CorporateActionUnsupported):
        data.validate_snapshot(snapshot)


def test_cash_factor_validation_accepts_multiplicative_and_additive_rounding():
    draft = _draft()
    cash_action_snapshot._verify_pair(
        draft["priceValidation"]["pairs"][0], draft["events"][0]
    )
    pair = deepcopy(draft["priceValidation"]["pairs"][0])
    pair["qfqPrevious"] = {
        "open": "9.50",
        "close": "9.50",
        "high": "10.45",
        "low": "8.55",
    }
    cash_action_snapshot._verify_pair(pair, draft["events"][0])


@pytest.mark.parametrize("field", ["coverageEvidence", "priceValidation"])
def test_complete_label_alone_cannot_admit_actions_to_execution(field):
    draft = _draft()
    draft.pop(field)
    actions = freeze_cash_dividend_artifact(draft)
    with pytest.raises(data.BacktestInputError):
        data.validate_snapshot(replace(_snapshot(), corporate_actions=actions))


def test_detected_unmatched_action_is_rejected_even_with_valid_dividend():
    draft = _draft()
    draft["priceValidation"]["detectedDates"].append("2024-04-12")
    actions = freeze_cash_dividend_artifact(draft)
    snapshot = replace(
        _snapshot(),
        corporate_actions=actions,
        action_dates=("2024-04-11", "2024-04-12"),
    )
    with pytest.raises(data.BacktestInputError, match="逐项匹配"):
        data.validate_snapshot(snapshot)


def test_offline_window_starts_empty_and_never_inherits_prior_entitlement():
    snapshot = _snapshot()
    sliced = walk_forward_data.slice_snapshot(snapshot, 2, 3)
    assert sliced.data_hash != snapshot.data_hash
    data.validate_snapshot(sliced)
    ledger = DividendLedger(sliced.symbol, sliced.corporate_actions)
    for candle in sliced.candles:
        assert ledger.open_session(candle.date) == 0
        assert ledger.close_session(candle.date) == 0
    assert ledger.receivable == ledger.dividends_total == 0


def test_window_can_end_with_unpaid_receivable_without_discarding_future_payment():
    sliced = walk_forward_data.slice_snapshot(_snapshot(), 0, 2)
    assert sliced.corporate_actions["events"][0]["paymentDate"] > sliced.end_date
    ledger = DividendLedger(sliced.symbol, sliced.corporate_actions)
    for candle in sliced.candles:
        ledger.open_session(candle.date)
        if candle.date == "2024-04-10":
            ledger.buy(candle.date, 100)
        ledger.close_session(candle.date)
    assert ledger.receivable == 50


def test_model_receives_only_prior_published_events_and_no_spendable_receivable():
    snapshot = _snapshot()
    draft = _draft()
    draft["events"][0]["publishedDate"] = "2024-04-09"
    draft["events"][0]["sourceUrl"] = (
        "https://static.cninfo.com.cn/finalpage/2024-04-09/1234567.PDF"
    )
    snapshot = replace(snapshot, corporate_actions=freeze_cash_dividend_artifact(draft))
    portfolio = {
        "cash": 1_000,
        "equity": 1_050,
        "dividendReceivable": 50,
        "dividendTaxPayable": 0,
    }
    same_day = decision.build_decision_input(
        snapshot, {}, as_of_date="2024-04-09", portfolio=portfolio
    )
    next_day = decision.build_decision_input(
        snapshot, {}, as_of_date="2024-04-10", portfolio=portfolio
    )
    assert same_day["cashDividends"]["sh600036"] == []
    assert next_day["cashDividends"]["sh600036"][0]["cashPerShare"] == "0.5"
    assert next_day["portfolio"]["cash"] == 1_000
    assert next_day["portfolio"]["dividendReceivable"] == 50


def test_preview_worker_fork_and_exports_replay_frozen_actions_without_network(
    monkeypatch, tmp_path
):
    from tests.test_financial_backtest_integration import (
        _AGENT_ID,
        _NOW,
        _decision,
        _install_scenario,
    )

    snapshot = _snapshot()
    store, _, _ = _install_scenario(monkeypatch, tmp_path, snapshot=snapshot)
    payload = {
        "symbol": snapshot.symbol,
        "startDate": snapshot.start_date,
        "endDate": snapshot.end_date,
        "strategy": "持有50%仓位",
        "corporateActionPolicy": "verified_cash_dividends",
        "initialCash": 10_000,
        "decisionInterval": 1,
        "commissionBps": 0,
        "minimumCommission": 0,
        "slippageBps": 0,
        "maxTokens": 2_000_000,
    }
    preview = service.create_financial_backtest_preview(
        _AGENT_ID, payload, store=store, now_provider=lambda: _NOW
    )
    assert (
        FinancialBacktestPreview.model_validate(preview)
        .corporateActionCoverage[snapshot.symbol]
        .eventCount
        == 1
    )
    started = service.start_financial_backtest_run(
        _AGENT_ID,
        str(uuid4()),
        preview["previewId"],
        store=store,
        now_provider=lambda: _NOW,
    )
    worker = runtime.FinancialBacktestWorker(
        store=store,
        assistant_loader=lambda: [_AGENT_ID],
        decision_runner=lambda **kw: _decision(kw["decision_input"], 50),
        worker_id="dividend-replay",
    )
    assert worker.process_pending_once(stop_requested=lambda: False) == 1
    completed = service.get_financial_backtest_run(
        _AGENT_ID, started["runId"], store=store
    )
    assert completed["status"] == "completed", completed.get("terminalReason")
    dto = FinancialBacktestRun.model_validate(completed)
    assert dto.dividendAccounting.events[0].paymentComplete
    assert dto.metrics["grossDividends"] > 0
    monkeypatch.setattr(
        data,
        "prepare_data",
        lambda *a, **k: pytest.fail("offline replay fetched new prices"),
    )
    monkeypatch.setattr(service, "_validate_candidate_model", lambda model_id: "frozen")
    fork = service.create_financial_backtest_fork_preview(
        _AGENT_ID, started["runId"], {}, store=store, now_provider=lambda: _NOW
    )
    assert fork["dataHash"] == snapshot.data_hash
    assert fork["params"]["corporateActionPolicy"] == "verified_cash_dividends"
    exported = service.export_financial_backtest_run(
        _AGENT_ID, started["runId"], "json", store=store
    )
    result = json.loads(exported["content"])
    assert result["schemaVersion"] == 4
    assert result["snapshot"]["corporateActions"] == snapshot.corporate_actions
    csv = service.export_financial_backtest_run(
        _AGENT_ID, started["runId"], "csv", store=store
    )["content"]
    assert "ashare_cash_dividend_v1" in csv
    assert "1234567" in csv
    assert "dividendReceivable,dividendTaxPayable,benchmarkDividendReceivable,benchmarkDividendTaxPayable" in csv


@pytest.mark.parametrize("tamper", ["policy", "coverage"])
def test_start_rejects_dividend_binding_tampering(monkeypatch, tmp_path, tamper):
    from core.web.services.financial_backtest.store import FinancialBacktestStoreError
    from tests.test_financial_backtest_integration import (
        _AGENT_ID,
        _NOW,
        _install_scenario,
    )

    snapshot = _snapshot()
    store, _, _ = _install_scenario(monkeypatch, tmp_path, snapshot=snapshot)
    preview = service.create_financial_backtest_preview(
        _AGENT_ID,
        {
            "symbol": snapshot.symbol,
            "startDate": snapshot.start_date,
            "endDate": snapshot.end_date,
            "strategy": "持有50%仓位",
            "corporateActionPolicy": "verified_cash_dividends",
            "maxTokens": 2_000_000,
        },
        store=store,
        now_provider=lambda: _NOW,
    )
    stored = store.load_preview(_AGENT_ID, preview["previewId"])
    if tamper == "policy":
        stored["params"].pop("corporateActionPolicy")
    else:
        stored["corporateActionCoverage"][snapshot.symbol]["eventCount"] = 0
    monkeypatch.setattr(store, "load_preview", lambda *_: stored)
    with pytest.raises(FinancialBacktestStoreError, match="公司行动"):
        service.start_financial_backtest_run(
            _AGENT_ID,
            str(uuid4()),
            preview["previewId"],
            store=store,
            now_provider=lambda: _NOW,
        )


def test_worker_persists_dividend_tax_failure_and_stops_calls(monkeypatch, tmp_path):
    from decimal import Decimal

    from tests.test_financial_backtest_integration import (
        _AGENT_ID,
        _NOW,
        _decision,
        _install_scenario,
    )

    snapshot = _snapshot()
    store, _, _ = _install_scenario(monkeypatch, tmp_path, snapshot=snapshot)
    preview = service.create_financial_backtest_preview(
        _AGENT_ID,
        {
            "symbol": snapshot.symbol,
            "startDate": snapshot.start_date,
            "endDate": snapshot.end_date,
            "strategy": "测试卖出",
            "corporateActionPolicy": "verified_cash_dividends",
            "initialCash": 10_000,
            "decisionInterval": 1,
            "maxTokens": 2_000_000,
        },
        store=store,
        now_provider=lambda: _NOW,
    )
    started = service.start_financial_backtest_run(
        _AGENT_ID,
        str(uuid4()),
        preview["previewId"],
        store=store,
        now_provider=lambda: _NOW,
    )
    monkeypatch.setattr(DividendLedger, "sell", lambda *_: Decimal(100000))
    calls = []

    def runner(**kw):
        inputs = kw["decision_input"]
        calls.append(inputs["asOfDate"])
        return _decision(inputs, 0 if inputs["asOfDate"] == "2024-04-11" else 50)

    worker = runtime.FinancialBacktestWorker(
        store=store,
        assistant_loader=lambda: [_AGENT_ID],
        decision_runner=runner,
        worker_id="dividend-failure",
    )
    worker.process_pending_once(stop_requested=lambda: False)
    failed = service.get_financial_backtest_run(
        _AGENT_ID, started["runId"], store=store
    )
    assert failed["status"] == "failed"
    assert failed["errorCode"] == "insufficient_cash_for_dividend_tax"
    evidence = FinancialBacktestRun.model_validate(failed).executionFailure
    assert evidence.symbol == snapshot.symbol
    assert Decimal(evidence.projectedCashAfterTax) < 0
    assert evidence.order.side == evidence.trade.side == "sell"
    before = list(calls)
    worker.process_pending_once(stop_requested=lambda: False)
    assert calls == before
    exported = json.loads(
        service.export_financial_backtest_run(
            _AGENT_ID, started["runId"], "json", store=store
        )["content"]
    )
    assert exported["executionFailure"] == failed["executionFailure"]
    csv = service.export_financial_backtest_run(_AGENT_ID, started["runId"], "csv", store=store)["content"]
    assert "insufficient_cash_for_dividend_tax" in csv
    assert "projectedCashAfterTax" in csv
