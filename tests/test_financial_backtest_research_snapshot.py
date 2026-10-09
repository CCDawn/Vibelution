from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from core.web.services import financial_research_service
from core.web.services.financial_backtest import decision
from core.web.services.financial_backtest.contract import FinancialBacktestStoreError
from core.web.services.financial_backtest.data import BacktestInputError, Candle
from core.web.services.financial_backtest.research_snapshot import (
    decision_research_material,
    freeze_announcement_research_snapshot,
    research_coverage_summary,
    validate_research_snapshot,
)
from core.web.services.financial_backtest.store import FinancialBacktestStore


def _announcement_payload(*, error: str | None = None) -> dict[str, Any]:
    return {
        "status": "available",
        "source": "东方财富",
        "sourceUrl": "https://data.eastmoney.com/notices/",
        "fetchedAt": "2024-01-04T10:00:00+00:00",
        "error": error,
        "items": [
            {
                "title": "此前公告",
                "publishedAt": "2024-01-02",
                "articleCode": "AN000000000000000001",
                "url": "https://data.eastmoney.com/notices/detail/600000/AN000000000000000001.html",
                "publisher": "东方财富",
            },
            {
                "title": "决策日公告不得进入",
                "publishedAt": "2024-01-03",
                "articleCode": "AN000000000000000002",
                "url": "https://data.eastmoney.com/notices/detail/600000/AN000000000000000002.html",
                "publisher": "东方财富",
            },
            {
                "title": "未来公告不得进入",
                "publishedAt": "2024-01-04",
                "articleCode": "AN000000000000000003",
                "url": "https://data.eastmoney.com/notices/detail/600000/AN000000000000000003.html",
                "publisher": "东方财富",
            },
        ],
    }


def test_freeze_uses_only_prior_day_announcement_titles_and_stable_hash(monkeypatch):
    calls: list[tuple[str, date]] = []

    def load(stock: dict[str, str], *, cutoff: date | None = None) -> dict[str, Any]:
        assert cutoff is not None
        calls.append((stock["symbol"], cutoff))
        return _announcement_payload()

    monkeypatch.setattr(financial_research_service, "_load_announcements", load)

    snapshot = freeze_announcement_research_snapshot(["sh600000"], ["2024-01-03"])
    restored = validate_research_snapshot(
        snapshot,
        expected_hash=snapshot["researchHash"],
        symbols=["sh600000"],
        decision_dates=["2024-01-03"],
    )

    assert calls == [("sh600000", date(2024, 1, 2))]
    group = restored["groups"][0]
    assert group["decisionDate"] == "2024-01-03"
    assert group["coverageStatus"] == "partial"
    assert [item["title"] for item in group["items"]] == ["此前公告"]
    item = group["items"][0]
    assert item["symbol"] == "sh600000"
    assert item["code"] == "AN000000000000000001"
    assert item["publishedDate"] == "2024-01-02"
    assert item["source"] == "东方财富"
    assert item["fetchedAt"] == "2024-01-04T10:00:00+00:00"
    assert item["coverageStatus"] == "partial"
    assert set(item) == {
        "symbol",
        "code",
        "publishedDate",
        "title",
        "url",
        "source",
        "fetchedAt",
        "coverageStatus",
    }
    assert snapshot["researchHash"] == restored["researchHash"]
    assert research_coverage_summary(snapshot)["status"] == "partial"


@pytest.mark.parametrize(
    ("symbols", "decision_dates"),
    [
        (["sh600000", "sz000001", "bj430047", "sh600519"], ["2024-01-03"]),
        (["sh600000", "sz000001", "bj430047"], [f"2024-01-{day:02d}" for day in range(1, 8)]),
        (["hk00700"], ["2024-01-03"]),
    ],
    ids=["too-many-symbols", "too-many-groups", "non-a-share"],
)
def test_freeze_rejects_out_of_scope_request_before_source_reads(
    monkeypatch, symbols: list[str], decision_dates: list[str]
):
    calls: list[bool] = []
    monkeypatch.setattr(
        financial_research_service,
        "_load_announcements",
        lambda *args, **kwargs: calls.append(True),
    )

    with pytest.raises(BacktestInputError):
        freeze_announcement_research_snapshot(symbols, decision_dates)

    assert calls == []


def test_freeze_keeps_partial_coverage_but_blocks_when_every_group_read_fails(monkeypatch):
    def partly_available(stock: dict[str, str], *, cutoff: date | None = None) -> dict[str, Any]:
        if stock["symbol"] == "sz000001":
            raise RuntimeError("source unavailable")
        return _announcement_payload(error="部分来源分页未穷尽")

    monkeypatch.setattr(financial_research_service, "_load_announcements", partly_available)
    partial = freeze_announcement_research_snapshot(
        ["sh600000", "sz000001"], ["2024-01-03"]
    )
    summary = research_coverage_summary(partial)
    assert summary["status"] == "partial"
    assert summary["groupCount"] == 2
    assert summary["itemCount"] == 1
    assert summary["warnings"]

    monkeypatch.setattr(
        financial_research_service,
        "_load_announcements",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("source unavailable")),
    )
    with pytest.raises(BacktestInputError, match="全部失败"):
        freeze_announcement_research_snapshot(["sh600000"], ["2024-01-03"])


def test_empty_source_result_is_partial_and_uses_real_frozen_time():
    frozen_at = datetime(2024, 1, 5, 12, 30, tzinfo=timezone.utc)
    payload = {
        "status": "available",
        "source": "东方财富",
        "fetchedAt": "",
        "items": [],
    }

    snapshot = freeze_announcement_research_snapshot(
        ["sh600000"],
        ["2024-01-03"],
        announcement_loader=lambda stock, *, cutoff: payload,
        now_provider=lambda: frozen_at,
    )

    group = snapshot["groups"][0]
    assert group["coverageStatus"] == "partial"
    assert group["fetchedAt"] == "2024-01-05T12:30:00+00:00"
    assert group["items"] == []
    assert snapshot["frozenAt"] == group["fetchedAt"]
    assert research_coverage_summary(snapshot)["status"] == "partial"


def test_source_rows_with_an_explicit_other_security_are_excluded(monkeypatch):
    payload = _announcement_payload()
    payload["items"] = [
        {
            **payload["items"][0],
            "symbol": "sz000001",
            "ticker": "000001",
        }
    ]
    monkeypatch.setattr(
        financial_research_service,
        "_load_announcements",
        lambda stock, *, cutoff=None: payload,
    )

    snapshot = freeze_announcement_research_snapshot(["sh600000"], ["2024-01-03"])

    assert snapshot["groups"][0]["items"] == []
    assert snapshot["groups"][0]["coverageStatus"] == "partial"


def test_research_material_selects_exact_date_and_separates_it_from_portfolio(monkeypatch):
    monkeypatch.setattr(
        financial_research_service,
        "_load_announcements",
        lambda stock, *, cutoff=None: _announcement_payload(),
    )
    snapshot = freeze_announcement_research_snapshot(
        ["sh600000"], ["2024-01-03", "2024-01-04"]
    )
    material = decision_research_material(
        snapshot, symbols=["sh600000"], decision_date="2024-01-04"
    )
    market_snapshot = SimpleNamespace(
        symbol="sh600000",
        warmup_candles=(Candle("2024-01-01", 10, 10, 10, 10, 100),),
        candles=(
            Candle("2024-01-03", 10, 10, 10, 10, 100),
            Candle("2024-01-04", 10, 10, 10, 10, 100),
        ),
    )

    built = decision.build_decision_input(
        market_snapshot,
        {"strategy": "test", "maxPositionPct": 80},
        as_of_date="2024-01-04",
        portfolio={"date": "2024-01-04", "cash": 100},
        research_material=material,
    )

    assert built["researchMaterial"]["asOfDate"] == "2024-01-04"
    assert built["researchMaterial"]["groups"][0]["items"][0]["publishedDate"] == "2024-01-03"
    assert built["portfolio"]["date"] == "2024-01-04"
    assert built["portfolio"]["cash"] == 100
    assert "researchMaterial" not in built["portfolio"]
    assert "发布日期严格早于asOfDate" in decision.build_messages(built)[0]["content"]
    price_only = decision.build_decision_input(
        market_snapshot,
        {"strategy": "test", "maxPositionPct": 80},
        as_of_date="2024-01-04",
        portfolio={"date": "2024-01-04", "cash": 100},
    )
    assert "researchMaterial" not in price_only
    assert decision.build_messages(price_only)[0]["content"] == decision._SYSTEM_PROMPT


def test_store_freezes_snapshot_and_revalidates_content_hash(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        financial_research_service,
        "_load_announcements",
        lambda stock, *, cutoff=None: _announcement_payload(),
    )
    snapshot = freeze_announcement_research_snapshot(["sh600000"], ["2024-01-03"])
    store = FinancialBacktestStore(path_resolver=lambda _agent_id: tmp_path)

    saved_hash = store.save_research_snapshot("agent-1", snapshot)
    loaded = store.load_research_snapshot("agent-1", saved_hash)
    assert saved_hash == snapshot["researchHash"]
    assert loaded == snapshot

    path = tmp_path / "research-snapshots" / f"{saved_hash}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["groups"][0]["items"][0]["title"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FinancialBacktestStoreError):
        store.load_research_snapshot("agent-1", saved_hash)


def test_decision_material_rejects_symbol_or_date_mismatch(monkeypatch):
    monkeypatch.setattr(
        financial_research_service,
        "_load_announcements",
        lambda stock, *, cutoff=None: _announcement_payload(),
    )
    snapshot = freeze_announcement_research_snapshot(["sh600000"], ["2024-01-03"])

    with pytest.raises(BacktestInputError):
        validate_research_snapshot(snapshot, symbols=["sz000001"])
    with pytest.raises(BacktestInputError):
        decision_research_material(
            snapshot, symbols=["sh600000"], decision_date="2024-01-04"
        )
