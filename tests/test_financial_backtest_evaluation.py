"""Held-out periods use their own prior-close strategy and benchmark capital."""

import copy

import pytest

from core.web.services.financial_backtest.data import BacktestInputError
from core.web.services.financial_backtest.evaluation import evaluate_windows


def curve():
    return [
        {"date": "2026-09-01", "equity": 1000, "benchmarkEquity": 1000},
        {"date": "2026-09-02", "equity": 1200, "benchmarkEquity": 800},
        {"date": "2026-09-03", "equity": 1260, "benchmarkEquity": 840},
        {"date": "2026-09-04", "equity": 1320, "benchmarkEquity": 840},
    ]


def test_each_window_has_its_own_capital_and_benchmark_baseline():
    result = evaluate_windows(
        curve(), [], initial_cash=1000, out_of_sample_start_date="2026-09-03"
    )
    before, after = result["inSample"], result["outOfSample"]
    assert before["endDate"] < after["startDate"]
    assert after["baselineDate"] == "2026-09-02"
    assert after["startingEquity"] == 1200
    assert after["startingBenchmarkEquity"] == 800
    assert after["tradingDays"] == 2
    assert before["metrics"]["totalReturnPct"] == pytest.approx(20)
    assert after["metrics"]["totalReturnPct"] == pytest.approx(10)
    assert after["metrics"]["benchmarkReturnPct"] == pytest.approx(5)
    assert after["metrics"]["excessReturnPct"] == pytest.approx(5)
    assert after["metrics"]["benchmarkFinalEquity"] == 840


def test_costs_and_fills_are_attributed_only_to_their_execution_window():
    orders = [
        {
            "date": "2026-09-02",
            "status": "filled",
            "filledShares": 100,
            "notional": 100,
            "fee": 5,
            "commission": 5,
            "stampDuty": 0,
        },
        {
            "date": "2026-09-03",
            "status": "filled",
            "filledShares": 100,
            "notional": 110,
            "fee": 6,
            "commission": 5,
            "stampDuty": 1,
        },
        {
            "date": "2026-09-04",
            "status": "rejected",
            "filledShares": 0,
            "notional": 0,
            "fee": 0,
            "commission": 0,
            "stampDuty": 0,
        },
    ]
    result = evaluate_windows(
        curve(), orders, initial_cash=1000, out_of_sample_start_date="2026-09-03"
    )
    assert result["inSample"]["metrics"]["fees"] == 5
    assert result["outOfSample"]["metrics"]["fees"] == 6
    assert result["outOfSample"]["metrics"]["grossTurnover"] == 110
    assert result["outOfSample"]["metrics"]["tradeCount"] == 1
    assert "winRatePct" not in result["outOfSample"]["metrics"]


def test_future_curve_changes_do_not_change_in_sample_evaluation():
    original = curve()
    future_changed = copy.deepcopy(original)
    future_changed[-1].update(equity=900, benchmarkEquity=1400)
    args = {"initial_cash": 1000, "out_of_sample_start_date": "2026-09-03"}
    assert (
        evaluate_windows(original, [], **args)["inSample"]
        == evaluate_windows(future_changed, [], **args)["inSample"]
    )
    assert original == curve()


@pytest.mark.parametrize(
    "boundary", ["2026-09-01", "2026-09-05", "2026-09-03T15:00:00"]
)
def test_split_requires_an_exact_session_and_a_previous_close(boundary):
    with pytest.raises(BacktestInputError):
        evaluate_windows(
            curve(), [], initial_cash=1000, out_of_sample_start_date=boundary
        )


def test_invalid_or_reordered_equity_is_not_silently_evaluated():
    for rows in [
        list(reversed(curve())),
        [curve()[0], curve()[0]],
        [{**curve()[0], "equity": float("nan")}, *curve()[1:]],
    ]:
        with pytest.raises(BacktestInputError):
            evaluate_windows(
                rows, [], initial_cash=1000, out_of_sample_start_date="2026-09-03"
            )
