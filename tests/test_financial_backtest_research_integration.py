"""The preview and worker must consume the same owned, immutable research input."""
from __future__ import annotations

import json
from uuid import uuid4

import pytest

from core.web.routes.financial_backtest_models import (
    FinancialBacktestPreview,
    FinancialBacktestRun,
)
from core.web.services.financial_backtest import research_snapshot, runtime, service
from tests.test_financial_backtest_integration import (
    _AGENT_ID,
    _NOW,
    _decision,
    _install_scenario,
    _preview_payload,
)


def _research_preview(monkeypatch, tmp_path):
    store, snapshot, _ = _install_scenario(monkeypatch, tmp_path)
    loaded = []
    original = research_snapshot.freeze_announcement_research_snapshot

    def loader(stock, *, cutoff):
        loaded.append((stock, cutoff))
        return {
            "status": "available", "source": "东方财富", "fetchedAt": _NOW.isoformat(),
            "items": [{"title": "董事会决议公告", "publishedAt": "2023-12-29",
                       "articleCode": "AN202312290001", "source": "东方财富",
                       "url": "https://data.eastmoney.com/notices/detail/600000/AN202312290001.html"}],
        }

    monkeypatch.setattr(research_snapshot, "freeze_announcement_research_snapshot",
                        lambda symbols, dates: original(symbols, dates, announcement_loader=loader, now_provider=lambda: _NOW))
    plain = service.create_financial_backtest_preview(
        _AGENT_ID, _preview_payload(), store=store, now_provider=lambda: _NOW,
    )
    preview = service.create_financial_backtest_preview(
        _AGENT_ID, {**_preview_payload(), "researchInput": "announcements"},
        store=store, now_provider=lambda: _NOW,
    )
    assert preview["estimatedTokens"] > plain["estimatedTokens"]
    assert preview["comparisonProvenance"]["commonParamsHash"] != plain["comparisonProvenance"]["commonParamsHash"]
    assert FinancialBacktestPreview.model_validate(preview).researchInput == "announcements"
    return store, snapshot, preview, loaded


def test_frozen_research_survives_start_execution_fork_and_export_without_network(monkeypatch, tmp_path):
    store, snapshot, preview, loaded = _research_preview(monkeypatch, tmp_path)
    assert len(loaded) == len(preview["decisionSchedule"])
    frozen = store.load_research_snapshot(_AGENT_ID, preview["researchHash"])
    monkeypatch.setattr(research_snapshot, "freeze_announcement_research_snapshot",
                        lambda *args, **kwargs: pytest.fail("resumed or derived inputs must not refetch announcements"))
    started = service.start_financial_backtest_run(
        _AGENT_ID, str(uuid4()), preview["previewId"], store=store, now_provider=lambda: _NOW,
    )
    seen = []

    def infer(**kwargs):
        payload = kwargs["decision_input"]
        seen.append(payload)
        assert payload["researchMaterial"] == research_snapshot.decision_research_material(
            frozen, symbols=[snapshot.symbol], decision_date=payload["asOfDate"],
        )
        return _decision(payload, 0)

    worker = runtime.FinancialBacktestWorker(
        store=store, assistant_loader=lambda: [_AGENT_ID], decision_runner=infer,
    )
    assert worker.process_pending_once() == 1
    completed = service.get_financial_backtest_run(_AGENT_ID, started["runId"], store=store)
    assert completed["status"] == "completed", completed.get("terminalReason")
    assert len(seen) == len(preview["decisionSchedule"])
    assert FinancialBacktestRun.model_validate(completed).researchHash == preview["researchHash"]
    exported = service.export_financial_backtest_run(_AGENT_ID, started["runId"], "json", store=store)
    payload = json.loads(exported["content"])
    assert payload["schemaVersion"] == 3
    assert payload["researchSnapshot"] == frozen
    monkeypatch.setattr(service, "_validate_candidate_model", lambda model_id: "configured")
    fork = service.create_financial_backtest_fork_preview(
        _AGENT_ID, started["runId"], {}, store=store, now_provider=lambda: _NOW,
    )
    assert fork["researchHash"] == preview["researchHash"]
    assert fork["comparisonProvenance"]["commonParamsHash"] == preview["comparisonProvenance"]["commonParamsHash"]


def test_missing_research_artifact_blocks_start_instead_of_falling_back_to_prices(monkeypatch, tmp_path):
    store, _, preview, _ = _research_preview(monkeypatch, tmp_path)
    artifact = store.root_for(_AGENT_ID) / "research-snapshots" / f"{preview['researchHash']}.json"
    assert artifact.is_file()
    artifact.unlink()
    with pytest.raises(ValueError):
        service.start_financial_backtest_run(
            _AGENT_ID, str(uuid4()), preview["previewId"], store=store, now_provider=lambda: _NOW,
        )
    assert store.list_runs(_AGENT_ID) == []
