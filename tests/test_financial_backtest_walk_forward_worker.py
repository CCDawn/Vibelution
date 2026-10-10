"""Run the master plan through the real child worker and deterministic engine."""
from core.web.routes.financial_walk_forward_models import WalkForwardWorkflow
from core.web.services.financial_backtest import runtime, walk_forward_service as wf
from tests.test_financial_backtest_integration import _AGENT_ID, _NOW, _decision
from tests.test_financial_backtest_walk_forward import (
    _candidate_rows, _completed_source_run, _create_workflow,
    _install_candidates, _quiet_workflow_runtime, _weekdays,
)


def test_real_worker_completes_two_folds_offline_and_restores_between_ticks(monkeypatch, tmp_path):
    store, source_id, _ = _completed_source_run(monkeypatch, tmp_path, _weekdays("2024-01-02", 6))
    _install_candidates(monkeypatch)
    _quiet_workflow_runtime(monkeypatch)
    preview = _create_workflow(store, source_id, candidates=_candidate_rows(40, 80))
    wf.start_walk_forward(_AGENT_ID, preview["workflowId"], store=store, now_provider=lambda: _NOW)
    seen = []

    def infer(**kwargs):
        value = kwargs["decision_input"]
        assert all(row["date"] <= value["asOfDate"] for row in value["dailyBars"])
        assert value["portfolio"]["shares"] == 0
        seen.append(value)
        return _decision(value, value["maxPositionPct"] / 100)

    for _ in range(10):
        # A new worker per tick proves progress comes from disk, not object state.
        worker = runtime.FinancialBacktestWorker(store=store, assistant_loader=lambda: [_AGENT_ID],
            decision_runner=infer, now_provider=lambda: _NOW)
        worker.process_pending_once()
        current = wf.get_walk_forward(_AGENT_ID, preview["workflowId"], store=store)
        if current["status"] == "completed":
            break
    assert current["status"] == "completed", current.get("terminalReason")
    assert len(seen) == 6
    assert len(store.list_runs(_AGENT_ID)) == 7
    assert WalkForwardWorkflow.model_validate(current).tokensUsed == 6 * 37
    assert all(fold["status"] == "completed" for fold in current["folds"])
    exported = wf.export_walk_forward(_AGENT_ID, preview["workflowId"], store=store)
    assert len(exported["childResults"]) == 6


def test_stop_between_child_completion_and_master_tick_prevents_next_child(monkeypatch, tmp_path):
    store, source_id, _ = _completed_source_run(monkeypatch, tmp_path, _weekdays("2024-01-02", 4))
    _install_candidates(monkeypatch)
    _quiet_workflow_runtime(monkeypatch)
    preview = _create_workflow(store, source_id, candidates=_candidate_rows(40, 80))
    wf.start_walk_forward(_AGENT_ID, preview["workflowId"], store=store, now_provider=lambda: _NOW)
    calls = []

    def infer(**kwargs):
        value = kwargs["decision_input"]
        calls.append(value)
        return _decision(value, 0)

    worker = runtime.FinancialBacktestWorker(store=store, assistant_loader=lambda: [_AGENT_ID],
        decision_runner=infer, now_provider=lambda: _NOW)
    worker.process_pending_once()
    assert len(calls) == 1
    wf.stop_walk_forward(_AGENT_ID, preview["workflowId"], store=store, now_provider=lambda: _NOW)
    worker.process_pending_once()
    assert len(calls) == 1
    assert wf.get_walk_forward(_AGENT_ID, preview["workflowId"], store=store)["status"] == "stopped"
    wf.resume_walk_forward(_AGENT_ID, preview["workflowId"], store=store, now_provider=lambda: _NOW)
    for _ in range(5):
        worker.process_pending_once()
    assert wf.get_walk_forward(_AGENT_ID, preview["workflowId"], store=store)["status"] == "completed"
    assert len(calls) == 3
