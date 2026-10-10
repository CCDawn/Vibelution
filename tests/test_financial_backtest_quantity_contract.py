"""Execution-rule versions survive preview, persisted forks and HTTP projections."""
from copy import deepcopy
from uuid import uuid4

import pytest

from core.web.routes.financial_backtest_models import FinancialBacktestPreview
from core.web.services.financial_backtest import service
from core.web.services.financial_backtest.comparisons import build_comparison_provenance, compare_runs
from core.web.services.financial_backtest.contract import normalize_preview_request
from core.web.services.financial_backtest.data import BacktestInputError
from tests.test_financial_backtest_comparison import _record
from tests.test_financial_backtest_fork import _candidate_payload, _install_candidate
from tests.test_financial_backtest_integration import (
    _AGENT_ID, _MODEL_ID, _NOW, _install_scenario, _new_preview, _preview_payload,
)


def test_new_preview_defaults_to_board_rules_and_rejects_unknown_version():
    assert normalize_preview_request(_preview_payload())["params"]["quantityRuleVersion"] == "ashare_quantity_v2"
    with pytest.raises(BacktestInputError, match="quantityRuleVersion"):
        normalize_preview_request({**_preview_payload(), "quantityRuleVersion": "future"})


@pytest.mark.parametrize("version", [None, "legacy_100_v1", "ashare_quantity_v2"])
def test_fork_preserves_source_quantity_contract(monkeypatch, tmp_path, version):
    store, _, _ = _install_scenario(monkeypatch, tmp_path)
    preview = _new_preview(store, data_loader=service.data.prepare_data)
    assert preview["params"]["quantityRuleVersion"] == "ashare_quantity_v2"
    assert FinancialBacktestPreview.model_validate(preview).params.quantityRuleVersion == "ashare_quantity_v2"
    stored = store.load_preview(_AGENT_ID, preview["previewId"])
    stored["previewId"] = str(uuid4())
    if version is None:
        stored["params"].pop("quantityRuleVersion")
    else:
        stored["params"]["quantityRuleVersion"] = version
    stored["comparisonProvenance"] = service._build_comparison_provenance(stored)
    store.save_preview(_AGENT_ID, stored)
    source = service.start_financial_backtest_run(
        _AGENT_ID, str(uuid4()), stored["previewId"], store=store, now_provider=lambda: _NOW,
    )
    _install_candidate(monkeypatch, _candidate_payload(_MODEL_ID))
    fork = service.create_financial_backtest_fork_preview(
        _AGENT_ID, source["runId"], {}, store=store, now_provider=lambda: _NOW,
    )
    assert fork["params"].get("quantityRuleVersion") == version
    assert ("quantityRuleVersion" in fork["params"]) == (version is not None)


@pytest.mark.parametrize("axis,parameter", [("strategy", None), ("parameter", "maxPositionPct")])
def test_quantity_rule_difference_cannot_be_ranked_as_strategy_or_parameter(axis, parameter):
    old = _record()
    old_hash = build_comparison_provenance(old)
    new = deepcopy(old)
    new["runId"] = "new-rule-run"
    new["params"]["quantityRuleVersion"] = "ashare_quantity_v2"
    if parameter:
        new["params"][parameter] = 50
    new["comparisonProvenance"] = build_comparison_provenance(new)
    result = compare_runs([old, new], axis, parameter)
    assert result["status"] == "incompatible"
    assert "quantity_rule_mismatch" in {row["code"] for row in result["reasons"]}
    assert build_comparison_provenance(old) == old_hash
