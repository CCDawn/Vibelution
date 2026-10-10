from __future__ import annotations

import csv
import json
from copy import deepcopy
from dataclasses import replace
from io import StringIO
from uuid import uuid4

import pytest

from core.web.services.financial_backtest import (
    basket_data,
    data,
    engine,
    limit_snapshot,
    portfolio_engine,
    runtime,
    service,
    walk_forward_data,
    walk_forward_service,
)
from core.web.services.financial_backtest.contract import (
    FinancialBacktestConflict,
    normalize_preview_request,
)
from core.web.services.financial_backtest.price_limits import (
    LEGACY_LIMIT_MODEL,
    SUPPLIED_LIMIT_MODEL,
)
from tests import test_financial_backtest_basket_integration as basket_fixtures
from tests import test_financial_backtest_execution as execution_fixtures
from tests import test_financial_backtest_integration as single_fixtures
from tests import test_financial_backtest_portfolio as portfolio_fixtures


def _limit_artifact(
    snapshot: data.BacktestSnapshot,
    *,
    upper: str | None = "99.00",
    lower: str | None = "0.01",
    overrides: dict[str, tuple[str | None, str | None]] | None = None,
) -> dict:
    overrides = overrides or {}
    return {
        "schemaVersion": 1,
        "symbol": snapshot.symbol,
        "source": {
            "url": f"https://static.cninfo.com.cn/daily-limits/{snapshot.symbol}.csv",
            "sha256": "a" * 64,
            "fetchedAt": "2024-01-09T16:00:00Z",
        },
        "records": [
            {
                "date": candle.date,
                "upper": overrides.get(candle.date, (upper, lower))[0],
                "lower": overrides.get(candle.date, (upper, lower))[1],
            }
            for candle in snapshot.candles
        ],
    }


def _bind_single(
    snapshot: data.BacktestSnapshot,
    artifact: dict | None = None,
) -> data.BacktestSnapshot:
    return limit_snapshot.bind_price_limits(
        snapshot,
        {
            "params": {"priceLimitModel": SUPPLIED_LIMIT_MODEL},
            "dailyPriceLimits": [artifact or _limit_artifact(snapshot)],
        },
    )


def _simulation_snapshot(candles: list[data.Candle]) -> data.BacktestSnapshot:
    snapshot = execution_fixtures._snapshot(candles)
    return replace(
        snapshot,
        data_hash=data._stable_hash(
            tuple(candles), snapshot.symbol, snapshot.start_date, snapshot.end_date
        ),
    )


def _basket_with_candles(
    snapshot: basket_data.BasketSnapshot,
    symbol: str,
    candles: tuple[data.Candle, ...],
) -> basket_data.BasketSnapshot:
    asset = snapshot.assets[symbol]
    updated_asset = replace(
        asset,
        candles=candles,
        data_hash=data._stable_hash(
            candles, symbol, asset.start_date, asset.end_date
        ),
    )
    assets = {**snapshot.assets, symbol: updated_asset}
    return replace(
        snapshot,
        assets=assets,
        data_hash=basket_data._stable_basket_hash(
            snapshot.symbols,
            assets,
            snapshot.session_dates,
            snapshot.start_date,
            snapshot.end_date,
        ),
    )


def _bind_basket(
    snapshot: basket_data.BasketSnapshot,
    artifacts: list[dict],
) -> basket_data.BasketSnapshot:
    return limit_snapshot.bind_price_limits(
        snapshot,
        {
            "params": {"priceLimitModel": SUPPLIED_LIMIT_MODEL},
            "dailyPriceLimits": artifacts,
        },
    )


def test_legacy_and_explicit_candidate_keep_the_same_parameters_and_snapshot_hash(
    monkeypatch, tmp_path
):
    store, snapshot, _prepared = single_fixtures._install_scenario(
        monkeypatch, tmp_path
    )
    default_preview = single_fixtures._new_preview(
        store, data_loader=service.data.prepare_data
    )
    explicit_preview = service.create_financial_backtest_preview(
        single_fixtures._AGENT_ID,
        {
            **single_fixtures._preview_payload(),
            "priceLimitModel": LEGACY_LIMIT_MODEL,
        },
        store=store,
        data_loader=service.data.prepare_data,
        now_provider=lambda: single_fixtures._NOW,
    )

    assert default_preview["dataHash"] == explicit_preview["dataHash"] == snapshot.data_hash
    assert default_preview["paramsHash"] == explicit_preview["paramsHash"]
    assert "priceLimitModel" not in default_preview["params"]
    assert "priceLimitModel" not in explicit_preview["params"]
    assert normalize_preview_request(
        {**single_fixtures._preview_payload(), "priceLimitModel": LEGACY_LIMIT_MODEL}
    )["params"] == normalize_preview_request(single_fixtures._preview_payload())["params"]


def test_supplied_limit_preview_rejects_missing_file_or_date_before_creating_preview(
    monkeypatch, tmp_path
):
    store, snapshot, prepared = single_fixtures._install_scenario(
        monkeypatch, tmp_path
    )
    base = single_fixtures._preview_payload()

    with pytest.raises(data.BacktestInputError, match="dailyPriceLimits"):
        service.create_financial_backtest_preview(
            single_fixtures._AGENT_ID,
            {**base, "priceLimitModel": SUPPLIED_LIMIT_MODEL},
            store=store,
            data_loader=service.data.prepare_data,
            now_provider=lambda: single_fixtures._NOW,
        )
    assert prepared == []

    incomplete = _limit_artifact(snapshot)
    incomplete["records"].pop()
    with pytest.raises(data.BacktestInputError, match="日期"):
        service.create_financial_backtest_preview(
            single_fixtures._AGENT_ID,
            {
                **base,
                "priceLimitModel": SUPPLIED_LIMIT_MODEL,
                "dailyPriceLimits": [incomplete],
            },
            store=store,
            data_loader=service.data.prepare_data,
            now_provider=lambda: single_fixtures._NOW,
        )
    previews_dir = store.root_for(single_fixtures._AGENT_ID) / "previews"
    assert not previews_dir.exists() or list(previews_dir.glob("*.json")) == []


def test_frozen_limit_tampering_is_rejected_when_start_restores_snapshot(
    monkeypatch, tmp_path
):
    store, snapshot, _prepared = single_fixtures._install_scenario(
        monkeypatch, tmp_path
    )
    preview = service.create_financial_backtest_preview(
        single_fixtures._AGENT_ID,
        {
            **single_fixtures._preview_payload(),
            "priceLimitModel": SUPPLIED_LIMIT_MODEL,
            "dailyPriceLimits": [_limit_artifact(snapshot)],
        },
        store=store,
        data_loader=service.data.prepare_data,
        now_provider=lambda: single_fixtures._NOW,
    )
    original_load = store.load_snapshot

    def tampered_load(agent_id: str, data_hash: str) -> dict:
        payload = original_load(agent_id, data_hash)
        payload = deepcopy(payload)
        payload["priceLimits"]["records"][0]["upper"] = "98.00"
        return payload

    monkeypatch.setattr(store, "load_snapshot", tampered_load)
    with pytest.raises((FinancialBacktestConflict, data.BacktestInputError)):
        service.start_financial_backtest_run(
            single_fixtures._AGENT_ID,
            str(uuid4()),
            preview["previewId"],
            store=store,
            now_provider=lambda: single_fixtures._NOW,
        )
    assert store.list_runs(single_fixtures._AGENT_ID) == []


def test_params_and_frozen_artifact_must_select_the_same_limit_model():
    snapshot = single_fixtures._snapshot()
    supplied = _bind_single(snapshot)

    with pytest.raises(data.BacktestInputError, match="不匹配"):
        limit_snapshot.validate_limit_binding(
            supplied, {"priceLimitModel": LEGACY_LIMIT_MODEL}
        )
    with pytest.raises(data.BacktestInputError, match="不匹配"):
        limit_snapshot.validate_limit_binding(
            snapshot, {"priceLimitModel": SUPPLIED_LIMIT_MODEL}
        )
    with pytest.raises(data.BacktestInputError, match="显式选择"):
        normalize_preview_request(
            {
                **single_fixtures._preview_payload(),
                "dailyPriceLimits": [_limit_artifact(snapshot)],
            }
        )


def test_imported_limits_cannot_rehash_a_corrupt_original_snapshot():
    snapshot = single_fixtures._snapshot()
    corrupt = replace(snapshot, data_hash="corrupted-original-hash")

    with pytest.raises(data.BacktestDataError, match="摘要校验失败"):
        _bind_single(corrupt)


def test_walk_forward_staging_carries_the_frozen_supplied_limit_artifact():
    snapshot = _bind_single(single_fixtures._snapshot())
    staged = walk_forward_service._stage_request(
        {
            "plan": {
                "sourceParams": {
                    "strategy": "限价滚动验证",
                    "priceLimitModel": SUPPLIED_LIMIT_MODEL,
                },
                "sourceModelId": "fixture-model",
            }
        },
        snapshot,
        {"maxPositionPct": 80},
        1024,
    )

    assert staged["params"]["priceLimitModel"] == SUPPLIED_LIMIT_MODEL
    assert staged["dailyPriceLimits"][0]["symbol"] == snapshot.symbol
    assert staged["dailyPriceLimits"][0]["records"] == snapshot.price_limits["records"]
    assert "artifactHash" not in staged["dailyPriceLimits"][0]


def test_user_unlimited_session_overrides_legacy_five_percent_flat_bar_rejection():
    candles = [
        data.Candle("2024-01-02", 10.0, 10.2, 9.8, 10.0, 100_000),
        data.Candle("2024-01-03", 10.5, 10.5, 10.5, 10.5, 100_000),
        data.Candle("2024-01-04", 10.6, 10.8, 10.4, 10.6, 100_000),
    ]
    snapshot = _simulation_snapshot(candles)
    params = {"decisionInterval": 1, "slippageBps": 0}
    decisions = execution_fixtures._decisions(snapshot, [1, 1])

    legacy = engine.simulate(
        snapshot,
        {**params, "priceLimitModel": LEGACY_LIMIT_MODEL},
        decisions,
    )
    imported_snapshot = _bind_single(
        snapshot,
        _limit_artifact(snapshot, upper=None, lower=None),
    )
    imported = engine.simulate(
        imported_snapshot,
        {**params, "priceLimitModel": SUPPLIED_LIMIT_MODEL},
        decisions,
    )

    assert legacy["orders"][0]["reason"] == "one_price_at_candidate_limit_up"
    assert legacy["benchmarkOrders"][0]["reason"] == "one_price_at_candidate_limit_up"
    assert imported["orders"][0]["status"] == "filled"
    assert imported["benchmarkOrders"][0]["status"] == "filled"


def test_imported_upper_and_lower_touch_block_orders_for_non_one_price_bars():
    upper_candles = [
        data.Candle("2024-01-02", 10.0, 10.2, 9.8, 10.0, 100_000),
        data.Candle("2024-01-03", 10.5, 10.5, 10.2, 10.4, 100_000),
        data.Candle("2024-01-04", 10.6, 10.8, 10.4, 10.6, 100_000),
    ]
    upper_snapshot = _simulation_snapshot(upper_candles)
    upper_rules = _limit_artifact(
        upper_snapshot,
        overrides={"2024-01-03": ("10.50", "9.00")},
    )
    upper_result = engine.simulate(
        _bind_single(upper_snapshot, upper_rules),
        {"decisionInterval": 1, "slippageBps": 0, "priceLimitModel": SUPPLIED_LIMIT_MODEL},
        execution_fixtures._decisions(upper_snapshot, [1, 1]),
    )
    strategy_up = upper_result["orders"][0]
    benchmark_up = upper_result["benchmarkOrders"][0]
    assert strategy_up["status"] == benchmark_up["status"] == "rejected"
    assert strategy_up["reason"] == benchmark_up["reason"] == "open_at_supplied_limit_up"
    assert upper_candles[1].low < upper_candles[1].high

    lower_candles = [
        data.Candle("2024-01-02", 10.0, 10.2, 9.8, 10.0, 100_000),
        data.Candle("2024-01-03", 10.1, 10.3, 9.9, 10.1, 100_000),
        data.Candle("2024-01-04", 9.5, 9.8, 9.5, 9.6, 100_000),
    ]
    lower_snapshot = _simulation_snapshot(lower_candles)
    lower_rules = _limit_artifact(
        lower_snapshot,
        overrides={"2024-01-04": ("11.00", "9.50")},
    )
    lower_result = engine.simulate(
        _bind_single(lower_snapshot, lower_rules),
        {"decisionInterval": 1, "slippageBps": 0, "priceLimitModel": SUPPLIED_LIMIT_MODEL},
        execution_fixtures._decisions(lower_snapshot, [1, 0]),
    )
    assert lower_result["orders"][0]["status"] == "filled"
    assert lower_result["orders"][1]["reason"] == "open_at_supplied_limit_down"
    assert lower_candles[2].low < lower_candles[2].high


def test_portfolio_blocks_strategy_and_benchmark_buys_at_imported_limit_up():
    symbol = "sh600000"
    raw = portfolio_fixtures._basket({symbol: [10.0, 10.4, 10.3]})
    original_asset = raw.assets[symbol]
    upper_day = original_asset.candles[1].date
    candles = (
        original_asset.candles[0],
        data.Candle(upper_day, 10.5, 10.5, 10.2, 10.4, 100_000),
        original_asset.candles[2],
    )
    raw = _basket_with_candles(raw, symbol, candles)
    rules = _limit_artifact(
        raw.assets[symbol],
        overrides={upper_day: ("10.50", "9.00")},
    )
    snapshot = _bind_basket(raw, [rules])
    params = portfolio_fixtures._params(
        priceLimitModel=SUPPLIED_LIMIT_MODEL,
    )
    decisions = portfolio_fixtures._decisions(
        snapshot,
        [{symbol: 1.0}, {symbol: 1.0}],
        params=params,
    )

    result = portfolio_engine.simulate(snapshot, params, decisions)

    strategy_order = result["orders"][0]
    benchmark_order = result["benchmarkOrders"][0]
    assert strategy_order["side"] == benchmark_order["side"] == "buy"
    assert strategy_order["status"] == benchmark_order["status"] == "rejected"
    assert strategy_order["reason"] == benchmark_order["reason"] == "open_at_supplied_limit_up"
    assert candles[1].low < candles[1].high


def test_portfolio_rejects_strategy_sell_at_imported_limit_down():
    symbol = "sh600000"
    raw = portfolio_fixtures._basket({symbol: [10.0, 10.4, 9.6]})
    original_asset = raw.assets[symbol]
    lower_day = original_asset.candles[2].date
    candles = (
        original_asset.candles[0],
        original_asset.candles[1],
        data.Candle(lower_day, 9.5, 9.8, 9.5, 9.6, 100_000),
    )
    raw = _basket_with_candles(raw, symbol, candles)
    rules = _limit_artifact(
        raw.assets[symbol],
        overrides={lower_day: ("11.00", "9.50")},
    )
    snapshot = _bind_basket(raw, [rules])
    params = portfolio_fixtures._params(
        priceLimitModel=SUPPLIED_LIMIT_MODEL,
    )
    decisions = portfolio_fixtures._decisions(
        snapshot,
        [{symbol: 1.0}, {symbol: 0.0}],
        params=params,
    )

    result = portfolio_engine.simulate(snapshot, params, decisions)

    assert result["orders"][0]["side"] == "buy"
    assert result["orders"][0]["status"] == "filled"
    sell = next(order for order in result["orders"] if order["side"] == "sell")
    assert sell["status"] == "rejected"
    assert sell["reason"] == "open_at_supplied_limit_down"
    assert candles[2].low < candles[2].high


def test_single_and_portfolio_results_include_limit_notice_once():
    single = _simulation_snapshot(
        [
            data.Candle("2024-01-02", 10.0, 10.2, 9.8, 10.0, 100_000),
            data.Candle("2024-01-03", 10.1, 10.3, 9.9, 10.1, 100_000),
            data.Candle("2024-01-04", 10.2, 10.4, 10.0, 10.2, 100_000),
        ]
    )
    single = _bind_single(single)
    single_params = {
        "decisionInterval": 1,
        "slippageBps": 0,
        "priceLimitModel": SUPPLIED_LIMIT_MODEL,
    }
    single_decisions = [
        {"date": day, "targetWeight": 1.0, "reason": "限价通知测试"}
        for day in engine.build_decision_schedule(single, single_params)
    ]
    single_result = engine.simulate(
        single,
        single_params,
        single_decisions,
    )

    symbol = "sh600000"
    raw_basket = portfolio_fixtures._basket({symbol: [10.0, 10.1, 10.2]})
    basket = _bind_basket(
        raw_basket,
        [_limit_artifact(raw_basket.assets[symbol])],
    )
    params = portfolio_fixtures._params(priceLimitModel=SUPPLIED_LIMIT_MODEL)
    basket_result = portfolio_engine.simulate(
        basket,
        params,
        portfolio_fixtures._decisions(
            basket,
            [{symbol: 1.0}, {symbol: 1.0}],
            params=params,
        ),
    )

    assert single_result["notice"].count(limit_snapshot.LIMIT_NOTICE) == 1
    assert basket_result["notice"].count(limit_snapshot.LIMIT_NOTICE) == 1


def test_single_and_basket_restore_and_walk_forward_slicing_keep_limit_provenance():
    single = _bind_single(single_fixtures._snapshot())
    restored_single = runtime._restore_snapshot(single.to_dict())
    assert restored_single.price_limits == single.price_limits
    assert restored_single.data_hash == single.data_hash

    basket = basket_fixtures._basket_snapshot()
    artifacts = [_limit_artifact(basket.assets[symbol]) for symbol in basket.symbols]
    bound_basket = limit_snapshot.bind_price_limits(
        basket,
        {
            "params": {"priceLimitModel": SUPPLIED_LIMIT_MODEL},
            "dailyPriceLimits": artifacts,
        },
    )
    restored_basket = runtime._restore_snapshot(
        {
            "dataHash": bound_basket.data_hash,
            "basketSnapshot": bound_basket.to_dict(),
        }
    )
    assert isinstance(restored_basket, basket_data.BasketSnapshot)
    assert restored_basket.data_hash == bound_basket.data_hash
    for symbol in restored_basket.symbols:
        assert restored_basket.assets[symbol].price_limits == bound_basket.assets[symbol].price_limits
        assert restored_basket.assets[symbol].price_limits["source"] == artifacts[
            list(restored_basket.symbols).index(symbol)
        ]["source"]

    window = walk_forward_data.slice_snapshot(restored_basket, 1, 3)
    assert isinstance(window, basket_data.BasketSnapshot)
    assert window.data_hash != restored_basket.data_hash
    for symbol in window.symbols:
        original = restored_basket.assets[symbol].price_limits
        sliced = window.assets[symbol].price_limits
        assert sliced["source"] == original["source"]
        assert sliced["artifactHash"] != original["artifactHash"]
        assert [item["date"] for item in sliced["records"]] == list(window.session_dates)


def test_preview_worker_json_csv_and_fork_reuse_frozen_limits_offline(
    monkeypatch, tmp_path
):
    store, snapshot, prepared = single_fixtures._install_scenario(
        monkeypatch, tmp_path
    )
    preview = service.create_financial_backtest_preview(
        single_fixtures._AGENT_ID,
        {
            **single_fixtures._preview_payload(),
            "priceLimitModel": SUPPLIED_LIMIT_MODEL,
            "dailyPriceLimits": [_limit_artifact(snapshot)],
        },
        store=store,
        data_loader=service.data.prepare_data,
        now_provider=lambda: single_fixtures._NOW,
    )
    assert preview["dataHash"] != snapshot.data_hash
    stored_snapshot = store.load_snapshot(single_fixtures._AGENT_ID, preview["dataHash"])
    assert stored_snapshot["priceLimits"]["artifactHash"]
    assert preview["params"]["priceLimitModel"] == SUPPLIED_LIMIT_MODEL

    started = service.start_financial_backtest_run(
        single_fixtures._AGENT_ID,
        str(uuid4()),
        preview["previewId"],
        store=store,
        now_provider=lambda: single_fixtures._NOW,
    )
    calls: list[str] = []

    def decision_runner(**kwargs):
        decision_input = dict(kwargs["decision_input"])
        calls.append(decision_input["asOfDate"])
        source = stored_snapshot["priceLimits"]["source"]
        serialized_input = json.dumps(decision_input, ensure_ascii=False, sort_keys=True)
        assert all(
            value not in serialized_input
            for value in (source["url"], source["sha256"], source["fetchedAt"])
        )
        return single_fixtures._decision(decision_input, 100)

    worker = runtime.FinancialBacktestWorker(
        store=store,
        assistant_loader=lambda: [single_fixtures._AGENT_ID],
        decision_runner=decision_runner,
        worker_id="daily-limit-integration-worker",
    )
    assert worker.process_pending_once(stop_requested=lambda: False) == 1
    completed = service.get_financial_backtest_run(
        single_fixtures._AGENT_ID, started["runId"], store=store
    )
    assert completed["status"] == "completed"
    assert calls == preview["decisionSchedule"]

    json_export = service.export_financial_backtest_run(
        single_fixtures._AGENT_ID, started["runId"], "json", store=store
    )
    body = json.loads(json_export["content"])
    assert body["schemaVersion"] == 6
    assert body["snapshot"]["priceLimits"] == stored_snapshot["priceLimits"]
    assert body["params"]["priceLimitModel"] == SUPPLIED_LIMIT_MODEL

    csv_export = service.export_financial_backtest_run(
        single_fixtures._AGENT_ID, started["runId"], "csv", store=store
    )
    rows = list(csv.reader(StringIO(csv_export["content"])))
    assert ["priceLimitModel", SUPPLIED_LIMIT_MODEL] in rows
    assert any(row[:4] == ["dailyPriceLimits", "symbol", "date", "upper"] for row in rows)
    assert any(
        row
        and row[0] == "dailyPriceLimits"
        and row[1] == snapshot.symbol
        and row[-1] == "supplied_not_independently_verified"
        for row in rows
    )
    assert any(
        row
        and row[0] == "dailyPriceLimits"
        and row[7] == stored_snapshot["priceLimits"]["source"]["sha256"]
        for row in rows
    )

    original_limit = service.MAX_RESULT_CHARS
    monkeypatch.setattr(service, "MAX_RESULT_CHARS", 100)
    with pytest.raises(FinancialBacktestConflict, match="CSV导出超过安全大小限制"):
        service.export_financial_backtest_run(
            single_fixtures._AGENT_ID, started["runId"], "csv", store=store
        )
    monkeypatch.setattr(service, "MAX_RESULT_CHARS", original_limit)

    monkeypatch.setattr(
        service.data,
        "prepare_data",
        lambda *args, **kwargs: pytest.fail("fork must restore the frozen limit snapshot offline"),
    )
    monkeypatch.setattr(service, "_validate_candidate_model", lambda _model_id: "pinned")
    fork = service.create_financial_backtest_fork_preview(
        single_fixtures._AGENT_ID,
        started["runId"],
        {"strategy": "派生限价回测"},
        store=store,
        now_provider=lambda: single_fixtures._NOW,
    )
    fork_snapshot = store.load_snapshot(single_fixtures._AGENT_ID, fork["dataHash"])
    assert len(prepared) == 1
    assert fork["dataHash"] == completed["dataHash"]
    assert fork_snapshot["priceLimits"] == stored_snapshot["priceLimits"]
