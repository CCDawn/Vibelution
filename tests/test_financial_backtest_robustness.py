"""Completed-run robustness slices stay bounded, explicit and retrospective."""

from __future__ import annotations

import copy
from datetime import date, timedelta

import pytest

from core.web.services.financial_backtest.data import BacktestInputError
from core.web.services.financial_backtest.robustness import evaluate_robustness


def _sessions(count: int, start: date = date(2023, 12, 1)) -> list[str]:
    result: list[str] = []
    current = start
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current.isoformat())
        current += timedelta(days=1)
    return result


def _curve(count: int, *, start: date = date(2023, 12, 1)) -> list[dict[str, object]]:
    return [
        {
            "date": session,
            "equity": 1_000 + index,
            "benchmarkEquity": 1_000,
        }
        for index, session in enumerate(_sessions(count, start))
    ]


def test_four_full_63_session_windows_exclude_partial_tail_from_rate():
    result = evaluate_robustness(_curve(63 * 4 + 8), [], initial_cash=1_000)

    assert result["schemaVersion"] == 1
    assert result["status"] == "available"
    assert result["scope"] == "full_period"
    assert result["completeWindowCount"] == 4
    assert result["partialWindowCount"] == 1
    assert [row["tradingDays"] for row in result["fixedWindows"]] == [63, 63, 63, 63, 8]
    assert [row["complete"] for row in result["fixedWindows"]] == [True] * 4 + [False]
    assert result["outperformingWindowRatePct"] == pytest.approx(100)
    assert set(result["fixedWindows"][0]["metrics"]) == {
        "totalReturnPct",
        "benchmarkReturnPct",
        "excessReturnPct",
        "maxDrawdownPct",
        "fees",
        "tradeCount",
    }
    assert "全区间回顾" in result["notice"]


def test_three_complete_windows_report_insufficient_sample_and_no_rate():
    result = evaluate_robustness(_curve(63 * 3 + 12), [], initial_cash=1_000)

    assert result["status"] == "insufficient_sample"
    assert result["completeWindowCount"] == 3
    assert result["partialWindowCount"] == 1
    assert result["outperformingWindowRatePct"] is None


def test_frozen_oos_scope_ignores_earlier_curve_changes_and_uses_prior_close():
    original = _curve(63 * 4 + 16)
    boundary_index = 12
    boundary = str(original[boundary_index]["date"])
    changed = copy.deepcopy(original)
    for row in changed[: boundary_index - 1]:
        row["equity"] = 10_000
        row["benchmarkEquity"] = 1

    args = {
        "initial_cash": 1_000,
        "out_of_sample_start_date": boundary,
    }
    first = evaluate_robustness(original, [], **args)
    second = evaluate_robustness(changed, [], **args)

    assert first["scope"] == "out_of_sample"
    assert first["evaluatedStartDate"] == boundary
    assert first["tradingDays"] == len(original) - boundary_index
    assert first["fixedWindows"] == second["fixedWindows"]
    assert first["annualWindows"] == second["annualWindows"]
    assert first["fixedWindows"][0]["baselineDate"] == str(original[boundary_index - 1]["date"])


def test_fill_fees_are_attributed_to_their_fixed_window_only():
    curve = _curve(64)
    first_date = str(curve[62]["date"])
    tail_date = str(curve[63]["date"])
    orders = [
        {
            "date": first_date,
            "status": "filled",
            "filledShares": 100,
            "notional": 100,
            "fee": 3,
            "commission": 3,
            "stampDuty": 0,
        },
        {
            "date": tail_date,
            "status": "partial_fill",
            "filledShares": 100,
            "notional": 110,
            "fee": 7,
            "commission": 5,
            "stampDuty": 2,
        },
    ]

    result = evaluate_robustness(curve, orders, initial_cash=1_000)

    assert result["fixedWindows"][0]["metrics"]["fees"] == 3
    assert result["fixedWindows"][0]["metrics"]["tradeCount"] == 1
    assert result["fixedWindows"][1]["metrics"]["fees"] == 7
    assert result["fixedWindows"][1]["metrics"]["tradeCount"] == 1
    assert result["outperformingWindowRatePct"] is None


def test_annual_slices_cross_calendar_year_with_previous_close_baseline():
    result = evaluate_robustness(_curve(300), [], initial_cash=1_000)

    annual = {row["label"]: row for row in result["annualWindows"]}
    assert set(annual) == {"2023", "2024", "2025"}
    assert annual["2024"]["startDate"] == "2024-01-01"
    assert annual["2024"]["baselineDate"] == "2023-12-29"
    assert annual["2024"]["complete"] is None
    assert annual["2024"]["metrics"]["totalReturnPct"] > 0
    assert result["evaluatedStartDate"] == "2023-12-01"
    assert result["evaluatedEndDate"].startswith("2025-")


@pytest.mark.parametrize(
    "mutate, boundary_index",
    [
        (lambda rows: rows[9].update(equity=0), 10),
        (lambda rows: rows[62].update(benchmarkEquity=0), None),
    ],
)
def test_zero_window_baseline_is_a_domain_input_error(mutate, boundary_index):
    curve = _curve(130)
    mutate(curve)
    args = {"initial_cash": 1_000}
    if boundary_index is not None:
        args["out_of_sample_start_date"] = str(curve[boundary_index]["date"])

    with pytest.raises(BacktestInputError):
        evaluate_robustness(curve, [], **args)


@pytest.mark.parametrize(
    "curve,orders,initial_cash,boundary",
    [
        (_curve(70), [], float("nan"), None),
        ([{**_curve(70)[0], "equity": float("inf")}, *_curve(70)[1:]], [], 1_000, None),
        (
            _curve(70),
            [{"date": _curve(70)[0]["date"], "status": "filled", "filledShares": 100, "fee": float("nan")}],
            1_000,
            None,
        ),
        (_curve(70), [], 1_000, "2023-12-01"),
        (_curve(70), [], 1_000, "2023-12-02T15:00:00"),
    ],
)
def test_malformed_inputs_raise_backtest_input_error(curve, orders, initial_cash, boundary):
    kwargs = {"initial_cash": initial_cash}
    if boundary is not None:
        kwargs["out_of_sample_start_date"] = boundary
    with pytest.raises(BacktestInputError):
        evaluate_robustness(curve, orders, **kwargs)
