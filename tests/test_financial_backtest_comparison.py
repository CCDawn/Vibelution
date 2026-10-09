from __future__ import annotations

from copy import deepcopy

import pytest

from core.web.services.financial_backtest.comparisons import (
    COMPARISON_CONTRACT_VERSION,
    build_comparison_provenance,
    compare_runs,
)


def _record(
    run_id: str = "run-1",
    *,
    status: str = "completed",
    model_id: str = "agent-model-a",
    model_config_hash: str = "a" * 64,
    strategy: str = "Buy when momentum is positive",
) -> dict:
    record = {
        "agentId": "agent-1",
        "runId": run_id,
        "status": status,
        "symbol": None,
        "symbols": ["sz000001", "sh600036"],
        "dataHash": "d" * 64,
        "dateCoverage": {
            "requestedStartDate": "2024-01-02",
            "requestedEndDate": "2024-01-10",
            "actualStartDate": "2024-01-02",
            "actualEndDate": "2024-01-10",
            "availableStartDate": "2023-01-02",
            "availableEndDate": "2024-01-10",
            "tradingDays": 7,
            "warmupBars": 252,
            "tradingCalendarStatus": "complete",
            "calendarSymbol": "sh000001",
            "complete": True,
        },
        "decisionSchedule": ["2024-01-02", "2024-01-05", "2024-01-09"],
        "outOfSampleStartDate": "2024-01-09",
        "adjustment": "raw",
        "maxTokens": 50_000,
        "modelId": model_id,
        "modelConfigHash": model_config_hash,
        "callsUsed": 3,
        "tokensUsed": 1_230,
        "params": {
            "strategy": strategy,
            "initialCash": 100_000,
            "maxPositionPct": 80,
            "decisionInterval": 3,
            "commissionBps": 3,
            "minimumCommission": 5,
            "slippageBps": 5,
            "maxDecisions": 200,
            "maxTokens": 50_000,
            "outOfSampleStartDate": "2024-01-09",
        },
        "metrics": {"totalReturnPct": 2.3, "maxDrawdownPct": 4.1},
        "evaluation": {
            "inSample": {"metrics": {"totalReturnPct": 1.1}},
            "outOfSample": {"metrics": {"totalReturnPct": 1.2}},
        },
    }
    record["comparisonProvenance"] = build_comparison_provenance(record)
    return record


def _reason_codes(result: dict) -> set[str]:
    return {reason["code"] for reason in result["reasons"]}


@pytest.mark.parametrize("axis", ["strategy", "model"])
@pytest.mark.parametrize("missing_field", ["modelId", "modelConfigHash"])
def test_each_comparison_axis_requires_recorded_model_identity(axis, missing_field) -> None:
    baseline = _record()
    candidate = _record("run-2")
    candidate.pop(missing_field)

    result = compare_runs([baseline, candidate], axis)

    assert result["status"] == "incompatible"
    assert "model_identity_missing" in _reason_codes(result)


def test_provenance_separates_strategy_and_model_from_shared_parameters() -> None:
    baseline = _record()
    other_strategy = deepcopy(baseline)
    other_strategy["params"]["strategy"] = "Sell when momentum is negative"
    other_model = deepcopy(baseline)
    other_model["modelId"] = "agent-model-b"
    other_model["modelConfigHash"] = "b" * 64

    baseline_provenance = build_comparison_provenance(baseline)
    strategy_provenance = build_comparison_provenance(other_strategy)
    model_provenance = build_comparison_provenance(other_model)

    assert baseline_provenance["contractVersion"] == COMPARISON_CONTRACT_VERSION
    assert strategy_provenance["commonParamsHash"] == baseline_provenance["commonParamsHash"]
    assert strategy_provenance["strategyHash"] != baseline_provenance["strategyHash"]
    assert model_provenance == baseline_provenance


@pytest.mark.parametrize(
    ("change", "expected_difference"),
    [
        (lambda row: row.__setitem__("dataHash", "e" * 64), "dataHash"),
        (lambda row: row["params"].__setitem__("minimumCommission", 6), "fee parameter"),
        (lambda row: row["params"].__setitem__("initialCash", 120_000), "initial cash"),
        (lambda row: row["params"].__setitem__("maxPositionPct", 60), "position limit"),
        (lambda row: row["params"].__setitem__("decisionInterval", 4), "decision cadence"),
        (lambda row: row["params"].__setitem__("maxDecisions", 199), "decision limit"),
        (lambda row: (row.__setitem__("outOfSampleStartDate", "2024-01-05"), row["params"].__setitem__("outOfSampleStartDate", "2024-01-05")), "holdout boundary"),
        (lambda row: row["decisionSchedule"].append("2024-01-10"), "decision schedule"),
        (lambda row: (row.__setitem__("maxTokens", 50_001), row["params"].__setitem__("maxTokens", 50_001)), "token budget"),
        (lambda row: row.__setitem__("adjustment", "qfq"), "adjustment"),
        (lambda row: row.__setitem__("symbols", ["sz000001"]), "symbols"),
        (lambda row: row["dateCoverage"].__setitem__("actualEndDate", "2024-01-11"), "date coverage"),
    ],
)
def test_provenance_binds_every_shared_data_and_execution_input(change, expected_difference) -> None:
    baseline = _record()
    changed = deepcopy(baseline)
    change(changed)

    assert build_comparison_provenance(changed)["commonParamsHash"] != build_comparison_provenance(baseline)["commonParamsHash"], expected_difference


def test_provenance_canonicalizes_symbols_strategy_spacing_and_optional_source_id() -> None:
    baseline = _record()
    reordered = deepcopy(baseline)
    reordered["symbols"] = ["SH600036", "SZ000001"]
    reordered["params"]["strategy"] = "\nBuy when momentum is positive\r\n"
    sourced = deepcopy(reordered)
    sourced["sourceRunId"] = "run-seed"

    expected = build_comparison_provenance(baseline)
    assert build_comparison_provenance(reordered) == expected
    sourced_provenance = build_comparison_provenance(sourced)
    assert sourced_provenance["commonParamsHash"] == expected["commonParamsHash"]
    assert sourced_provenance["strategyHash"] == expected["strategyHash"]
    assert sourced_provenance["sourceRunId"] == "run-seed"


def test_provenance_rejects_incomplete_or_out_of_range_date_schedules() -> None:
    incomplete = _record()
    incomplete["dateCoverage"]["complete"] = False
    out_of_range = _record()
    out_of_range["decisionSchedule"][-1] = "2024-01-11"

    with pytest.raises(ValueError):
        build_comparison_provenance(incomplete)
    with pytest.raises(ValueError):
        build_comparison_provenance(out_of_range)


def test_strategy_comparison_accepts_only_same_model_and_preserves_actual_results() -> None:
    first = _record("run-1", strategy="First strategy")
    second = _record("run-2", strategy="Second strategy")
    result = compare_runs([first, second], "strategy")

    assert result["status"] == "comparable"
    assert result["dataHash"] == first["dataHash"]
    assert result["commonParamsHash"] == first["comparisonProvenance"]["commonParamsHash"]
    assert result["outOfSampleStartDate"] == "2024-01-09"
    assert [row["runId"] for row in result["rows"]] == ["run-1", "run-2"]
    assert result["rows"][0]["strategy"] == "First strategy"
    assert result["rows"][0]["strategyHash"] == first["comparisonProvenance"]["strategyHash"]
    assert result["rows"][0]["metrics"] == first["metrics"]
    assert result["rows"][0]["evaluation"] == first["evaluation"]
    assert result["rows"][0]["callsUsed"] == 3
    assert result["rows"][0]["tokensUsed"] == 1_230
    assert result["rows"][0]["maxTokens"] == 50_000
    assert result["reasons"] == []
    assert "winner" not in result["notice"].lower()


def test_model_comparison_accepts_only_same_strategy_and_does_not_rank_runs() -> None:
    first = _record("run-1", model_id="model-a", model_config_hash="a" * 64)
    second = _record("run-2", model_id="model-b", model_config_hash="b" * 64)
    result = compare_runs([first, second], "model")

    assert result["status"] == "comparable"
    assert [row["modelId"] for row in result["rows"]] == ["model-a", "model-b"]
    assert result["rows"][0]["strategyHash"] == result["rows"][1]["strategyHash"]
    assert "winner" not in result["notice"].lower()


def test_strategy_axis_rejects_model_identity_mismatch_with_displayable_reason() -> None:
    first = _record("run-1")
    second = _record("run-2", model_config_hash="b" * 64)
    result = compare_runs([first, second], "strategy")

    assert result["status"] == "incompatible"
    assert "model_config_mismatch" in _reason_codes(result)
    assert any(reason.get("message") for reason in result["reasons"])


def test_strategy_axis_rejects_model_id_mismatch_even_when_config_hash_matches() -> None:
    first = _record("run-1", model_id="model-a", model_config_hash="a" * 64)
    second = _record("run-2", model_id="model-b", model_config_hash="a" * 64)

    result = compare_runs([first, second], "strategy")

    assert result["status"] == "incompatible"
    assert "model_id_mismatch" in _reason_codes(result)


def test_model_axis_rejects_strategy_mismatch_with_displayable_reason() -> None:
    first = _record("run-1", model_id="model-a")
    second = _record("run-2", model_id="model-b", strategy="Different strategy")
    result = compare_runs([first, second], "model")

    assert result["status"] == "incompatible"
    assert "strategy_mismatch" in _reason_codes(result)


def test_different_data_oos_boundary_and_execution_costs_are_explained() -> None:
    first = _record("run-1")
    second = _record("run-2", strategy="Another strategy")
    second["dataHash"] = "e" * 64
    second["outOfSampleStartDate"] = "2024-01-05"
    second["params"]["outOfSampleStartDate"] = "2024-01-05"
    second["params"]["commissionBps"] = 4
    second["comparisonProvenance"] = build_comparison_provenance(second)

    result = compare_runs([first, second], "strategy")
    codes = _reason_codes(result)
    assert result["status"] == "incompatible"
    assert "data_hash_mismatch" in codes
    assert "out_of_sample_boundary_mismatch" in codes
    assert "cost_model_mismatch" in codes
    assert all(reason.get("message") for reason in result["reasons"])


def test_legacy_unknown_version_and_tampered_provenance_fail_closed() -> None:
    current = _record("run-current")
    legacy = _record("run-legacy")
    legacy.pop("comparisonProvenance")
    unknown = _record("run-unknown")
    unknown["comparisonProvenance"]["contractVersion"] = "future-contract"
    tampered = _record("run-tampered")
    tampered["params"]["minimumCommission"] = 10

    for records, expected_code in (
        ([current, legacy], "provenance_missing"),
        ([current, unknown], "unsupported_contract_version"),
        ([current, tampered], "provenance_mismatch"),
    ):
        result = compare_runs(records, "strategy")
        assert result["status"] == "incompatible"
        assert expected_code in _reason_codes(result)


@pytest.mark.parametrize(
    ("status", "missing_field"),
    [("running", None), ("completed", "metrics"), ("completed", "evaluation")],
)
def test_comparison_is_incomplete_until_runs_and_holdout_evaluation_finish(status, missing_field) -> None:
    first = _record("run-1")
    second = _record("run-2", strategy="Another strategy")
    second["status"] = status
    if missing_field:
        second[missing_field] = None

    result = compare_runs([first, second], "strategy")

    assert result["status"] == "incomplete"
    assert "run_incomplete" in _reason_codes(result) or "evaluation_incomplete" in _reason_codes(result)


def test_comparison_manifest_id_is_stable_for_ordered_evidence_and_changes_with_order() -> None:
    first = _record("run-1", strategy="First")
    second = _record("run-2", strategy="Second")

    original = compare_runs([first, second], "strategy")
    repeated = compare_runs([first, second], "strategy")
    reversed_order = compare_runs([second, first], "strategy")

    assert original["comparisonId"] == repeated["comparisonId"]
    assert original["comparisonId"] != reversed_order["comparisonId"]


def test_comparison_manifest_id_changes_when_model_evidence_changes() -> None:
    first = _record("run-1", model_id="model-a", model_config_hash="a" * 64)
    second = _record("run-2", model_id="model-b", model_config_hash="b" * 64)
    changed = deepcopy(second)
    changed["modelConfigHash"] = "c" * 64

    assert compare_runs([first, second], "model")["comparisonId"] != compare_runs([first, changed], "model")["comparisonId"]


@pytest.mark.parametrize(
    ("records", "axis", "expected_code"),
    [([], "strategy", "run_count_out_of_range"), ([{}], "strategy", "run_count_out_of_range"), ([{}, {}, {}, {}, {}], "model", "run_count_out_of_range"), ([_record("same"), _record("same")], "strategy", "duplicate_run_ids"), ([_record("run-1"), _record("run-2")], "return", "invalid_axis")],
)
def test_comparison_rejects_invalid_selection_shape(records, axis, expected_code) -> None:
    result = compare_runs(records, axis)

    assert result["status"] == "incompatible"
    assert expected_code in _reason_codes(result)
