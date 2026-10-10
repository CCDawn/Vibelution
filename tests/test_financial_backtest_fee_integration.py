from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest

from core.web.routes.financial_backtest_models import FinancialBacktestRun
from core.web.services import financial_backtest_service as api
from core.web.services.financial_backtest import (
    runtime,
    walk_forward_service,
)
from core.web.services.financial_backtest import (
    service as backtest_service,
)
from core.web.services.financial_backtest.comparisons import (
    build_comparison_provenance,
    compare_runs,
)
from core.web.services.financial_backtest.contract import (
    FinancialBacktestStoreError,
    normalize_preview_request,
    sha256_json,
)
from core.web.services.financial_backtest.fees import (
    LEGACY_FEE_MODEL,
    VERIFIED_FEE_MODEL,
    fee_model_audit,
)
from core.web.services.financial_backtest.walk_forward_store import WalkForwardStore
from tests.test_financial_backtest_comparison import _record
from tests.test_financial_backtest_integration import (
    _AGENT_ID,
    _NOW,
    _decision,
    _install_scenario,
    _preview_payload,
)
from tests.test_financial_backtest_walk_forward import (
    _install_candidates,
    _quiet_workflow_runtime,
    _weekdays,
)
from tests.test_financial_backtest_walk_forward import (
    _snapshot as _walk_snapshot,
)


def _preview(store, *, fee_model: str = VERIFIED_FEE_MODEL, days=None):
    payload = {**_preview_payload(), "feeModel": fee_model}
    if days:
        payload.update(startDate=days[0], endDate=days[-1])
    return api.create_financial_backtest_preview(
        _AGENT_ID,
        payload,
        store=store,
        data_loader=backtest_service.data.prepare_data,
        now_provider=lambda: _NOW,
    )


def _start(store, preview):
    return api.start_financial_backtest_run(
        _AGENT_ID,
        str(uuid4()),
        preview["previewId"],
        store=store,
        now_provider=lambda: _NOW,
    )


def _tamper_audit(record: dict) -> None:
    record["feePolicyAudit"]["rates"][0]["rateBps"] = "2.99"


def _verified_record(run_id: str) -> dict:
    record = _record(run_id)
    record["params"]["feeModel"] = VERIFIED_FEE_MODEL
    record["feePolicyAudit"] = fee_model_audit(
        record["params"], record["symbols"], "2024-01-02", "2024-01-10"
    )
    record["comparisonProvenance"] = build_comparison_provenance(record)
    return record


def test_comparison_rejects_fee_model_mix_and_tampered_fee_evidence():
    verified = _verified_record("verified")
    legacy = _record("legacy")
    mixed = compare_runs([legacy, verified], "strategy")
    assert mixed["status"] == "incompatible"
    assert "fee_model_mismatch" in {row["code"] for row in mixed["reasons"]}
    unchanged = _verified_record("same-fees")
    assert compare_runs([verified, unchanged], "strategy")["status"] == "comparable"
    _tamper_audit(unchanged)
    assert compare_runs([verified, unchanged], "strategy")["status"] == "incompatible"


@pytest.mark.parametrize("parameter,value", [("commissionBps", 4), ("minimumCommission", 6)])
def test_fee_parameter_comparison_keeps_other_fee_assumptions_fixed(parameter, value):
    first = _verified_record("first")
    second = _verified_record("second")
    second["params"][parameter] = value
    second["feePolicyAudit"] = fee_model_audit(
        second["params"], second["symbols"], "2024-01-02", "2024-01-10"
    )
    second["comparisonProvenance"] = build_comparison_provenance(second)
    result = compare_runs([first, second], "parameter", parameter)
    assert result["status"] == "comparable"
    assert result["rows"][1]["parameterValue"] == value


def test_frozen_fee_params_hash_binds_audit_and_explicit_legacy_keeps_old_hash(
    monkeypatch, tmp_path
):
    store, _snapshot, _prepared = _install_scenario(monkeypatch, tmp_path)
    legacy = api.create_financial_backtest_preview(
        _AGENT_ID,
        _preview_payload(),
        store=store,
        data_loader=backtest_service.data.prepare_data,
        now_provider=lambda: _NOW,
    )
    explicit_legacy = api.create_financial_backtest_preview(
        _AGENT_ID,
        {**_preview_payload(), "feeModel": LEGACY_FEE_MODEL},
        store=store,
        data_loader=backtest_service.data.prepare_data,
        now_provider=lambda: _NOW,
    )
    verified = _preview(store)

    assert legacy["paramsHash"] == explicit_legacy["paramsHash"]
    assert "feeModel" not in explicit_legacy["params"]
    assert verified["paramsHash"] != legacy["paramsHash"]

    normalized = normalize_preview_request(
        {**_preview_payload(), "feeModel": VERIFIED_FEE_MODEL}
    )
    expected_hash_input = {
        "symbol": verified["symbol"],
        "symbols": verified["symbols"],
        "startDate": normalized["startDate"],
        "endDate": normalized["endDate"],
        "outOfSampleStartDate": verified["outOfSampleStartDate"],
        "strategy": normalized["strategy"],
        "params": normalized["params"],
        "maxTokens": normalized["maxTokens"],
        "modelId": verified["modelId"],
        "researchInput": verified["researchInput"],
        "researchHash": verified["researchHash"],
        "feePolicyAudit": verified["feePolicyAudit"],
    }
    assert verified["paramsHash"] == sha256_json(expected_hash_input)


@pytest.mark.parametrize("tamper", ["audit", "paramsHash"])
def test_start_rejects_tampered_frozen_fee_binding(monkeypatch, tmp_path, tamper):
    store, _snapshot, _prepared = _install_scenario(monkeypatch, tmp_path)
    preview = _preview(store)
    stored = store.load_preview(_AGENT_ID, preview["previewId"])
    if tamper == "audit":
        _tamper_audit(stored)
    else:
        stored["paramsHash"] = "0" * 64
    monkeypatch.setattr(store, "load_preview", lambda *_args: deepcopy(stored))

    with pytest.raises(FinancialBacktestStoreError, match="费用"):
        _start(store, preview)


def test_resume_rejects_tampered_fee_params_hash(monkeypatch, tmp_path):
    store, _snapshot, _prepared = _install_scenario(monkeypatch, tmp_path)
    run = _start(store, _preview(store))
    store.update_run(
        _AGENT_ID,
        run["runId"],
        lambda state: state.update(status="stopped", paramsHash="0" * 64),
    )

    with pytest.raises(FinancialBacktestStoreError, match="费用参数摘要"):
        api.resume_financial_backtest_run(_AGENT_ID, run["runId"], store=store)


def test_worker_blocks_tampered_fee_audit_before_any_model_call(monkeypatch, tmp_path):
    store, _snapshot, _prepared = _install_scenario(monkeypatch, tmp_path)
    run = _start(store, _preview(store))
    store.update_run(
        _AGENT_ID,
        run["runId"],
        lambda state: _tamper_audit(state),
    )
    calls = []
    worker = runtime.FinancialBacktestWorker(
        store=store,
        assistant_loader=lambda: [_AGENT_ID],
        decision_runner=lambda **kwargs: calls.append(kwargs) or {},
        worker_id="fee-integrity-worker",
    )

    assert worker.process_pending_once(stop_requested=lambda: False) == 1
    blocked = store.load_run(_AGENT_ID, run["runId"])
    assert blocked["status"] == "blocked"
    assert blocked["errorCode"] == "fee_policy_mismatch"
    assert blocked["callsUsed"] == 0
    assert calls == []


def test_fork_inherits_verified_fee_model_and_rebuilds_its_audit(monkeypatch, tmp_path):
    store, _snapshot, _prepared = _install_scenario(monkeypatch, tmp_path)
    source = _start(store, _preview(store))
    fork_model_id = "provider/fee-fork-model"
    _install_candidates(monkeypatch, model_id=fork_model_id)

    fork = api.create_financial_backtest_fork_preview(
        _AGENT_ID,
        source["runId"],
        {"modelId": fork_model_id, "strategy": "派生费用策略"},
        store=store,
        now_provider=lambda: _NOW,
    )

    assert fork["params"]["feeModel"] == VERIFIED_FEE_MODEL
    assert fork["feePolicyAudit"] == source["feePolicyAudit"]
    assert fork["comparisonProvenance"]["sourceRunId"] == source["runId"]
    fork_run = _start(store, fork)
    persisted = store.load_run(_AGENT_ID, fork_run["runId"])
    assert persisted["feePolicyAudit"] == source["feePolicyAudit"]
    assert persisted["comparisonProvenance"]["feePolicyAuditHash"] == fork[
        "comparisonProvenance"
    ]["feePolicyAuditHash"]


def test_walk_forward_freezes_source_fee_audit_and_rebuilds_window_audits(
    monkeypatch, tmp_path
):
    days = _weekdays("2024-01-02", 4)
    snapshot = _walk_snapshot(days)
    store, _snapshot_value, _prepared = _install_scenario(
        monkeypatch, tmp_path, snapshot=snapshot
    )
    source_preview = _preview(store, days=days)
    source = _start(store, source_preview)
    store.update_run(
        _AGENT_ID,
        source["runId"],
        lambda state: state.update(
            status="completed",
            metrics={
                "totalReturnPct": 1.0,
                "benchmarkReturnPct": 0.5,
                "excessReturnPct": 0.5,
                "maxDrawdownPct": 0.0,
            },
            tokensUsed=0,
            budgetTokensCommitted=0,
            tokenAccounting="measured",
        ),
    )
    _install_candidates(monkeypatch)
    _quiet_workflow_runtime(monkeypatch)
    preview = walk_forward_service.create_walk_forward_preview(
        _AGENT_ID,
        source["runId"],
        {
            "trainSessions": 2,
            "testSessions": 2,
            "stepSessions": 2,
            "maxTokens": 2_000_000,
            "candidates": [
                {"candidateId": "cap-40", "maxPositionPct": 40},
                {"candidateId": "cap-60", "maxPositionPct": 60},
            ],
        },
        store=store,
        now_provider=lambda: _NOW,
    )
    workflow_store = WalkForwardStore(store)
    frozen_workflow = workflow_store.load(_AGENT_ID, preview["workflowId"])
    assert frozen_workflow["plan"]["sourceFeePolicyAudit"] == source[
        "feePolicyAudit"
    ]
    assert sha256_json(frozen_workflow["plan"]) == frozen_workflow["planHash"]

    walk_forward_service.start_walk_forward(
        _AGENT_ID,
        preview["workflowId"],
        store=store,
        now_provider=lambda: _NOW,
    )
    walk_forward_service.advance_walk_forward_workflows(
        _AGENT_ID, store=store, now_provider=lambda: _NOW
    )
    started_workflow = workflow_store.load(_AGENT_ID, preview["workflowId"])
    child = store.load_run(_AGENT_ID, str(started_workflow["activeRunId"]))

    assert child["params"]["feeModel"] == VERIFIED_FEE_MODEL
    expected_child_audit = fee_model_audit(
        child["params"],
        child["symbols"],
        child["dateCoverage"]["requestedStartDate"],
        child["dateCoverage"]["requestedEndDate"],
    )
    assert child["feePolicyAudit"] == expected_child_audit
    backtest_service._validate_fee_binding(child)


def test_verified_run_and_advanced_metrics_dto_preserve_fee_breakdown(
    monkeypatch, tmp_path
):
    store, _snapshot, _prepared = _install_scenario(monkeypatch, tmp_path)
    started = _start(store, _preview(store))

    def infer(**kwargs):
        decision_input = dict(kwargs["decision_input"])
        return _decision(
            decision_input,
            100 if decision_input["asOfDate"] == "2024-01-02" else 0,
        )

    worker = runtime.FinancialBacktestWorker(
        store=store,
        assistant_loader=lambda: [_AGENT_ID],
        decision_runner=infer,
        worker_id="verified-fee-dto-worker",
    )
    assert worker.process_pending_once(stop_requested=lambda: False) == 1
    projected = api.get_financial_backtest_run(
        _AGENT_ID, started["runId"], store=store
    )
    dto = FinancialBacktestRun.model_validate(projected)

    trade = next(row for row in dto.trades if row.side == "buy")
    order = next(row for row in dto.orders if row.side == "buy")
    for row in (trade, order):
        assert row.transferFee is not None and row.transferFee > 0
        assert row.handlingFee is not None and row.handlingFee > 0
        assert row.regulatoryFee is not None and row.regulatoryFee > 0
        assert row.brokerCommission is not None and row.brokerCommission > 0

    assert dto.advancedEvaluation is not None
    baseline = next(
        row
        for row in dto.advancedEvaluation.costStress.scenarios
        if row.id == "baseline"
    )
    assert baseline.metrics is not None
    assert baseline.metrics.transferFees is not None
    assert baseline.metrics.handlingFees is not None
    assert baseline.metrics.regulatoryFees is not None
    assert baseline.metrics.brokerCommissionFees is not None
    assert baseline.metrics.benchmarkTransferFees is not None
