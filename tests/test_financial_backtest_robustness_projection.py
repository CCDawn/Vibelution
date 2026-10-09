from copy import deepcopy

import pytest

from core.web.routes.financial_backtest_models import FinancialBacktestRobustness
from core.web.services.financial_backtest.service import project_run


def record():
    return {
        "status": "completed", "params": {"initialCash": 1000},
        "dateCoverage": {"complete": True, "tradingDays": 2,
                         "actualStartDate": "2025-01-02", "actualEndDate": "2025-01-03"},
        "equity": [{"date": "2025-01-02", "equity": 1000, "benchmarkEquity": 1000},
                   {"date": "2025-01-03", "equity": 1010, "benchmarkEquity": 1005}],
        "orders": [],
    }


def test_projection_is_additive_and_does_not_write_or_certify_a_short_run():
    run = record()
    saved = deepcopy(run)
    result = project_run(run)["robustness"]
    assert run == saved
    dto = FinancialBacktestRobustness.model_validate(result)
    assert dto.status == "insufficient_sample"
    assert dto.scope == "full_period"
    assert dto.outperformingWindowRatePct is None
    assert dto.annualWindows[0].complete is None


@pytest.mark.parametrize("status", ["running", "queued", "stopped", "failed", "paused_unknown"])
def test_incomplete_runs_have_no_robustness_claim(status):
    run = record()
    run["status"] = status
    assert project_run(run)["robustness"] is None


@pytest.mark.parametrize("change", [
    {"dateCoverage": {}}, {"equity": []},
    {"dateCoverage": {**record()["dateCoverage"], "complete": "false"}},
    {"equity": ["invalid"]},
    {"params": {"initialCash": 1000, "outOfSampleStartDate": "2025-01-03"},
     "outOfSampleStartDate": "2025-01-02"},
    {"orders": [{"status": "filled", "date": "2025-01-03", "filledShares": 100, "fee": -1}]},
])
def test_legacy_or_damaged_evidence_is_explicitly_unavailable(change):
    run = {**record(), **change}
    result = project_run(run)["robustness"]
    dto = FinancialBacktestRobustness.model_validate(result)
    assert dto.status == "unavailable"
    assert dto.error
    assert not dto.fixedWindows
    assert dto.outperformingWindowRatePct is None
