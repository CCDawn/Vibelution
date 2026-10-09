from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest

from core.web.routes.financial_backtest_models import FinancialBacktestComparison
from core.web.services import agent_model_candidate_service
from core.web.services import financial_backtest_service as api
from core.web.services.financial_backtest import runtime, service
from core.web.services.financial_backtest.contract import (
    FinancialBacktestConflict,
    FinancialBacktestNotFound,
    FinancialBacktestStoreError,
)
from tests.test_financial_backtest_integration import (
    _AGENT_ID,
    _MODEL_ID,
    _NOW,
    _decision,
    _install_scenario,
    _new_preview,
    _preview_payload,
)


def _candidate_payload(
    model_id: str,
    *,
    selectable: bool = True,
    dialogue_allowed: bool = True,
    source: str = "pinned",
    operator_config_hash: str = "operator-config-v1",
) -> dict:
    return {
        "operatorConfigHash": operator_config_hash,
        "candidates": [
            {
                "modelId": model_id,
                "modelRef": model_id,
                "model": model_id.split("/", 1)[-1],
                "providerId": model_id.split("/", 1)[0],
                "source": source,
                "runtimeSelectable": selectable,
                "slotCompatibility": {"dialogue": {"allowed": dialogue_allowed}},
            }
        ],
    }


def test_upgrade_replays_pre_comparison_run_without_new_usage(monkeypatch, tmp_path):
    store, _snapshot, _prepared = _install_scenario(monkeypatch, tmp_path)
    preview = _new_preview(store, data_loader=service.data.prepare_data)
    legacy = store.load_preview(_AGENT_ID, preview["previewId"])
    legacy["previewId"] = str(uuid4())
    legacy.pop("comparisonProvenance")
    legacy.pop("_modelCandidateSource")
    store.save_preview(_AGENT_ID, legacy)
    request_id = str(uuid4())
    run = api.start_financial_backtest_run(
        _AGENT_ID, request_id, legacy["previewId"], store=store, now_provider=lambda: _NOW
    )
    # Persist the fingerprint and usage written by the pre-comparison release.
    legacy_hash = service.sha256_json({
        "paramsHash": legacy["paramsHash"],
        "dataHash": legacy["dataHash"],
        "modelFingerprint": legacy["_modelFingerprint"],
    })
    store.update_run(_AGENT_ID, run["runId"], lambda state: state.update(
        requestHash=legacy_hash, callsUsed=2, tokensUsed=300, status="stopped"
    ))
    replay = api.start_financial_backtest_run(
        _AGENT_ID, request_id, legacy["previewId"], store=store, now_provider=lambda: _NOW
    )
    assert replay["runId"] == run["runId"]
    assert (replay["callsUsed"], replay["tokensUsed"], replay["status"]) == (2, 300, "stopped")
    assert len(store.list_runs(_AGENT_ID)) == 1


def _install_candidate(monkeypatch: pytest.MonkeyPatch, payload: dict) -> dict:
    current = deepcopy(payload)
    monkeypatch.setattr(
        agent_model_candidate_service,
        "list_agent_model_candidates",
        lambda: deepcopy(current),
    )
    return current


def _fork_preview(monkeypatch, tmp_path, *, candidate_payload=None, record_events=None):
    store, _snapshot, prepared_requests = _install_scenario(monkeypatch, tmp_path)
    if record_events is not None:
        monkeypatch.setattr(
            runtime,
            "_record_event",
            lambda *args: record_events.append(args),
        )
    source_preview = _new_preview(store, data_loader=service.data.prepare_data)
    source_run = api.start_financial_backtest_run(
        _AGENT_ID,
        str(uuid4()),
        source_preview["previewId"],
        store=store,
        now_provider=lambda: _NOW,
    )
    model_id = "provider/model-fork"
    candidate_state = _install_candidate(
        monkeypatch,
        candidate_payload or _candidate_payload(model_id),
    )
    fork = api.create_financial_backtest_fork_preview(
        _AGENT_ID,
        source_run["runId"],
        {"strategy": "派生策略", "modelId": model_id, "maxTokens": 1_900_000},
        store=store,
        now_provider=lambda: _NOW,
    )
    return store, prepared_requests, source_preview, source_run, fork, candidate_state, model_id


def test_fork_preview_reuses_frozen_snapshot_and_source_schedule(monkeypatch, tmp_path):
    events = []
    store, prepared, source_preview, source_run, fork, _candidate_state, model_id = _fork_preview(
        monkeypatch, tmp_path, record_events=events
    )

    assert len(prepared) == 1
    assert fork["dataHash"] == source_preview["dataHash"] == source_run["dataHash"]
    assert fork["symbols"] == source_preview["symbols"]
    assert fork["decisionSchedule"] == source_preview["decisionSchedule"]
    assert fork["outOfSampleStartDate"] == source_preview["outOfSampleStartDate"]
    assert fork["params"]["strategy"] == "派生策略"
    assert fork["maxTokens"] == 1_900_000
    assert fork["modelId"] == model_id
    assert fork["comparisonProvenance"]["sourceRunId"] == source_run["runId"]
    assert events == [
        (
            _AGENT_ID,
            source_run["runId"],
            "financial_backtest.preview.forked",
            "previewed",
            "",
        )
    ]
    stored = store.load_preview(_AGENT_ID, fork["previewId"])
    assert stored["_modelFingerprint"]
    assert stored["_modelCandidateSource"]
    assert stored["dataHash"] == fork["dataHash"]


@pytest.mark.parametrize(
    ("selectable", "dialogue_allowed"),
    [(False, True), (True, False)],
)
def test_fork_preview_requires_authoritative_dialogue_candidate(
    monkeypatch, tmp_path, selectable, dialogue_allowed
):
    model_id = "provider/model-fork"
    candidate = _candidate_payload(
        model_id,
        selectable=selectable,
        dialogue_allowed=dialogue_allowed,
    )
    store, _snapshot, _prepared = _install_scenario(monkeypatch, tmp_path)
    source = _new_preview(store, data_loader=service.data.prepare_data)
    source_run = api.start_financial_backtest_run(
        _AGENT_ID, str(uuid4()), source["previewId"], store=store, now_provider=lambda: _NOW
    )
    _install_candidate(monkeypatch, candidate)

    with pytest.raises(FinancialBacktestConflict, match="不可作为对话模型"):
        api.create_financial_backtest_fork_preview(
            _AGENT_ID, source_run["runId"], {"modelId": model_id}, store=store
        )


def test_start_rejects_candidate_source_drift_after_fork_preview(monkeypatch, tmp_path):
    store, _prepared, _source_preview, _source_run, fork, candidate, _model_id = _fork_preview(
        monkeypatch, tmp_path
    )
    candidate["operatorConfigHash"] = "operator-config-v2"

    with pytest.raises(FinancialBacktestConflict, match="候选来源已变化"):
        api.start_financial_backtest_run(
            _AGENT_ID,
            str(uuid4()),
            fork["previewId"],
            store=store,
            now_provider=lambda: _NOW,
        )


def test_worker_and_resume_revalidate_derived_model_without_changing_agent_binding(
    monkeypatch, tmp_path
):
    store, _prepared, _source_preview, _source_run, fork, candidate, model_id = _fork_preview(
        monkeypatch, tmp_path
    )
    fork_run = api.start_financial_backtest_run(
        _AGENT_ID,
        str(uuid4()),
        fork["previewId"],
        store=store,
        now_provider=lambda: _NOW,
    )
    worker = runtime.FinancialBacktestWorker(
        store=store,
        assistant_loader=lambda: [_AGENT_ID],
        decision_runner=lambda **_kwargs: {},
        worker_id="fork-validation-worker",
    )
    worker._validate_frozen_model(_AGENT_ID, store.load_run(_AGENT_ID, fork_run["runId"]))
    assert model_id != _MODEL_ID

    api.request_financial_backtest_stop(_AGENT_ID, fork_run["runId"], store=store)
    candidate["candidates"][0]["runtimeSelectable"] = False
    with pytest.raises(FinancialBacktestConflict, match="不可作为对话模型"):
        api.resume_financial_backtest_run(_AGENT_ID, fork_run["runId"], store=store)


def test_worker_blocks_derived_run_when_candidate_loses_dialogue_eligibility(
    monkeypatch, tmp_path
):
    store, _prepared, _source_preview, _source_run, fork, candidate, _model_id = _fork_preview(
        monkeypatch, tmp_path
    )
    fork_run = api.start_financial_backtest_run(
        _AGENT_ID,
        str(uuid4()),
        fork["previewId"],
        store=store,
        now_provider=lambda: _NOW,
    )
    candidate["candidates"][0]["slotCompatibility"]["dialogue"]["allowed"] = False
    worker = runtime.FinancialBacktestWorker(
        store=store,
        assistant_loader=lambda: [_AGENT_ID],
        decision_runner=lambda **_kwargs: {},
        worker_id="fork-block-worker",
    )

    with pytest.raises(runtime._AlreadySettled):
        worker._validate_frozen_model(_AGENT_ID, store.load_run(_AGENT_ID, fork_run["runId"]))
    blocked = store.load_run(_AGENT_ID, fork_run["runId"])
    assert blocked["status"] == "blocked"
    assert blocked["errorCode"] == "model_candidate_changed"


def test_compare_service_owner_loads_runs_and_verifies_frozen_snapshot(monkeypatch, tmp_path):
    store, _snapshot, _prepared = _install_scenario(monkeypatch, tmp_path)
    first = _new_preview(store, data_loader=service.data.prepare_data)
    second_payload = {**_preview_payload(), "strategy": "另一个策略"}
    second = api.create_financial_backtest_preview(
        _AGENT_ID,
        second_payload,
        store=store,
        data_loader=service.data.prepare_data,
        now_provider=lambda: _NOW,
    )
    first_run = api.start_financial_backtest_run(
        _AGENT_ID, str(uuid4()), first["previewId"], store=store, now_provider=lambda: _NOW
    )
    second_run = api.start_financial_backtest_run(
        _AGENT_ID, str(uuid4()), second["previewId"], store=store, now_provider=lambda: _NOW
    )
    run_count = len(store.list_runs(_AGENT_ID))
    preview_count = len(list((store.root_for(_AGENT_ID) / "previews").glob("*.json")))

    comparison = api.compare_financial_backtest_runs(
        _AGENT_ID, [first_run["runId"], second_run["runId"]], "strategy", store=store
    )

    assert comparison["status"] == "incomplete"
    assert [row["runId"] for row in comparison["rows"]] == [first_run["runId"], second_run["runId"]]
    assert len(store.list_runs(_AGENT_ID)) == run_count
    assert len(list((store.root_for(_AGENT_ID) / "previews").glob("*.json"))) == preview_count
    with pytest.raises(FinancialBacktestNotFound):
        api.compare_financial_backtest_runs(
            "different-owner", [first_run["runId"], second_run["runId"]], "strategy", store=store
        )


def test_completed_baseline_and_fork_compare_through_owner_scoped_service(monkeypatch, tmp_path):
    store, _snapshot, prepared_requests = _install_scenario(monkeypatch, tmp_path)
    baseline_preview = _new_preview(store, data_loader=service.data.prepare_data)
    baseline_run = api.start_financial_backtest_run(
        _AGENT_ID,
        str(uuid4()),
        baseline_preview["previewId"],
        store=store,
        now_provider=lambda: _NOW,
    )
    _install_candidate(monkeypatch, _candidate_payload(_MODEL_ID))
    fork_preview = api.create_financial_backtest_fork_preview(
        _AGENT_ID,
        baseline_run["runId"],
        {"strategy": "在同一冻结数据上验证的新策略"},
        store=store,
        now_provider=lambda: _NOW,
    )
    fork_run = api.start_financial_backtest_run(
        _AGENT_ID,
        str(uuid4()),
        fork_preview["previewId"],
        store=store,
        now_provider=lambda: _NOW,
    )
    worker = runtime.FinancialBacktestWorker(
        store=store,
        assistant_loader=lambda: [_AGENT_ID],
        decision_runner=lambda **kwargs: _decision(kwargs["decision_input"], 0),
        worker_id="baseline-fork-compare-worker",
    )
    assert worker.process_pending_once(stop_requested=lambda: False) == 1
    assert worker.process_pending_once(stop_requested=lambda: False) == 1
    assert len(prepared_requests) == 1
    store.update_run(
        _AGENT_ID,
        fork_run["runId"],
        lambda run: run.pop("sourceRunId", None),
    )

    comparison = api.compare_financial_backtest_runs(
        _AGENT_ID,
        [baseline_run["runId"], fork_run["runId"]],
        "strategy",
        store=store,
    )

    assert comparison["status"] == "comparable"
    assert comparison["dataHash"] == baseline_run["dataHash"] == fork_run["dataHash"]
    assert comparison["rows"][0]["strategy"] != comparison["rows"][1]["strategy"]
    assert store.load_run(_AGENT_ID, fork_run["runId"])["comparisonProvenance"]["sourceRunId"] == baseline_run["runId"]
    dto = FinancialBacktestComparison.model_validate(comparison)
    assert dto.rows[0].metrics is not None
    assert dto.rows[0].metrics.totalReturnPct is not None
    assert dto.rows[0].evaluation is not None
    assert dto.rows[0].evaluation.outOfSample.metrics.totalReturnPct is not None


def test_compare_service_rejects_run_whose_data_hash_has_no_frozen_snapshot(monkeypatch, tmp_path):
    store, _snapshot, _prepared = _install_scenario(monkeypatch, tmp_path)
    preview = _new_preview(store, data_loader=service.data.prepare_data)
    run = api.start_financial_backtest_run(
        _AGENT_ID, str(uuid4()), preview["previewId"], store=store, now_provider=lambda: _NOW
    )
    store.update_run(
        _AGENT_ID,
        run["runId"],
        lambda state: state.update({"dataHash": "e" * 64}),
    )
    second = api.start_financial_backtest_run(
        _AGENT_ID, str(uuid4()), preview["previewId"], store=store, now_provider=lambda: _NOW
    )

    with pytest.raises(FinancialBacktestNotFound):
        api.compare_financial_backtest_runs(
            _AGENT_ID, [run["runId"], second["runId"]], "strategy", store=store
        )


@pytest.mark.parametrize("tamper", ["dateCoverage", "decisionSchedule"])
def test_compare_service_rechecks_coverage_and_schedule_against_frozen_snapshot(
    monkeypatch, tmp_path, tamper
):
    store, _snapshot, _prepared = _install_scenario(monkeypatch, tmp_path)
    first_preview = _new_preview(store, data_loader=service.data.prepare_data)
    second_preview = api.create_financial_backtest_preview(
        _AGENT_ID,
        {**_preview_payload(), "strategy": "第二策略"},
        store=store,
        data_loader=service.data.prepare_data,
        now_provider=lambda: _NOW,
    )
    first = api.start_financial_backtest_run(
        _AGENT_ID, str(uuid4()), first_preview["previewId"], store=store, now_provider=lambda: _NOW
    )
    second = api.start_financial_backtest_run(
        _AGENT_ID, str(uuid4()), second_preview["previewId"], store=store, now_provider=lambda: _NOW
    )

    def corrupt(run):
        if tamper == "dateCoverage":
            run["dateCoverage"]["actualEndDate"] = "2024-01-02"
        else:
            run["decisionSchedule"] = ["2024-01-02"]

    store.update_run(_AGENT_ID, first["runId"], corrupt)
    with pytest.raises(FinancialBacktestStoreError):
        api.compare_financial_backtest_runs(
            _AGENT_ID, [first["runId"], second["runId"]], "strategy", store=store
        )
