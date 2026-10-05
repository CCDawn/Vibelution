"""Portfolio exposure and correlation use bounded paper-ledger evidence only."""

import threading
import time
from datetime import date, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.routes.financial_portfolio import router
from core.web.services import financial_market_service as market
from core.web.services import financial_paper_service as paper
from core.web.services import financial_portfolio_service as portfolio


def _position(symbol: str, name: str, market_value: str | None) -> dict:
    ticker = symbol[2:]
    return {
        "symbol": symbol,
        "ticker": ticker,
        "name": name,
        "market": "上交所" if symbol.startswith("sh") else "深交所",
        "quantity": 100,
        "markPriceYuan": "100.00" if market_value else None,
        "marketValueYuan": market_value,
        "unrealizedPnlYuan": "5.00" if market_value else None,
        "valuationStatus": "fresh" if market_value else "unavailable",
        "quoteTimestamp": "2026-10-05T15:00:00+08:00" if market_value else "",
        "quoteFetchedAt": "2026-10-05T07:00:02+00:00" if market_value else "",
        "source": "腾讯财经",
        "sourceUrl": f"https://gu.qq.com/{symbol}/gp",
    }


def _account(
    positions: list[dict], *, cash: str = "20000.00", equity: str = "100000.00"
) -> dict:
    return {
        "agentId": "agent-one",
        "accountId": "paper-account-one",
        "cashYuan": cash,
        "marketValueYuan": "80000.00",
        "equityYuan": equity,
        "valuationStatus": "fresh",
        "positions": positions,
    }


def _series(values: list[float], *, offset: int = 0) -> dict[str, float]:
    first = date(2026, 9, 1)
    return {
        (first + timedelta(days=offset + index)).isoformat(): value
        for index, value in enumerate(values)
    }


def test_exposure_and_correlations_use_common_daily_return_dates(monkeypatch):
    positions = [
        _position("sh600519", "贵州茅台", "50000.00"),
        _position("sz000001", "平安银行", "20000.00"),
        _position("sh600036", "招商银行", "10000.00"),
    ]
    monkeypatch.setattr(
        portfolio.paper,
        "get_account_snapshot",
        lambda *_args, **_kwargs: _account(positions),
    )
    values = [index / 10_000 for index in range(25)]
    series_by_symbol = {
        "sh600519": _series(values),
        "sz000001": _series([value * 2 for value in values]),
        "sh600036": _series([-value for value in values]),
    }
    monkeypatch.setattr(
        portfolio, "_load_daily_return_series", lambda symbol: series_by_symbol[symbol]
    )

    result = portfolio.get_portfolio_research("agent-one")

    assert result["summary"]["cashWeightPercent"] == "20.00"
    assert result["summary"]["maxPositionWeightPercent"] == "50.00"
    assert result["summary"]["topThreeWeightPercent"] == "80.00"
    assert result["summary"]["correlationPairCount"] == 3
    assert result["summary"]["highCorrelationPairCount"] == 3
    assert result["correlations"][0]["correlation"] == 1.0
    assert result["correlations"][0]["observations"] == 25
    assert result["correlations"][0]["startDate"] == "2026-09-01"
    assert result["notice"].find("模拟账本") >= 0
    assert result["coverage"]["candleLoadedPositionCount"] == 3


def test_unvalued_holding_suppresses_misleading_weights_and_correlations(monkeypatch):
    positions = [
        _position("sh600519", "贵州茅台", "50000.00"),
        _position("sz000001", "平安银行", None),
    ]
    monkeypatch.setattr(
        portfolio.paper,
        "get_account_snapshot",
        lambda *_args, **_kwargs: _account(positions),
    )
    monkeypatch.setattr(
        portfolio,
        "_load_daily_return_series",
        lambda _symbol: _series([index / 1000 for index in range(25)]),
    )

    result = portfolio.get_portfolio_research("agent-one")

    assert result["summary"]["valuationComplete"] is False
    assert result["summary"]["cashWeightPercent"] is None
    assert result["positions"][0]["weightPercent"] is None
    assert result["positions"][1]["returnSeriesStatus"] == "not_valued"
    assert result["coverage"]["unvaluedPositionCount"] == 1
    assert result["correlations"] == []


def test_missing_candle_series_is_counted_as_unavailable_pair(monkeypatch):
    positions = [
        _position("sh600519", "贵州茅台", "50000.00"),
        _position("sz000001", "平安银行", "30000.00"),
    ]
    monkeypatch.setattr(
        portfolio.paper,
        "get_account_snapshot",
        lambda *_args, **_kwargs: _account(positions),
    )

    def load(symbol: str) -> dict[str, float]:
        if symbol == "sz000001":
            raise market.MarketDataError("provider unavailable")
        return _series([index / 1000 for index in range(25)])

    monkeypatch.setattr(portfolio, "_load_daily_return_series", load)
    result = portfolio.get_portfolio_research("agent-one")

    assert result["summary"]["correlationPairCount"] == 0
    assert result["summary"]["unavailableCorrelationPairCount"] == 1
    assert result["coverage"]["candleUnavailablePositionCount"] == 1
    assert result["coverage"]["unavailableSymbols"] == ["sz000001"]


def test_series_and_pair_budget_are_explicit(monkeypatch):
    positions = [
        _position(f"sz{i:06d}", f"股票{i}", f"{20_000 - i:.2f}") for i in range(1, 15)
    ]
    monkeypatch.setattr(
        portfolio.paper,
        "get_account_snapshot",
        lambda *_args, **_kwargs: _account(positions),
    )
    active = 0
    peak = 0
    lock = threading.Lock()

    def load(_symbol: str) -> dict[str, float]:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        return _series([index / 1000 for index in range(25)])

    monkeypatch.setattr(portfolio, "_load_daily_return_series", load)

    result = portfolio.get_portfolio_research("agent-one")

    assert result["coverage"]["eligiblePositionCount"] == 14
    assert (
        result["coverage"]["selectedPositionCount"] == portfolio.MAX_ANALYZED_POSITIONS
    )
    assert result["coverage"]["budgetSkippedPositionCount"] == 2
    assert result["coverage"]["budgetSkippedSymbols"] == ["sz000013", "sz000014"]
    assert all(
        row["returnSeriesStatus"] == "limit_skipped" for row in result["positions"][-2:]
    )
    assert peak <= portfolio.MAX_CONCURRENT_CANDLE_FETCHES


def test_correlation_pairs_below_common_date_threshold_are_not_displayed(monkeypatch):
    positions = [
        _position("sh600519", "贵州茅台", "50000.00"),
        _position("sz000001", "平安银行", "30000.00"),
    ]
    monkeypatch.setattr(
        portfolio.paper,
        "get_account_snapshot",
        lambda *_args, **_kwargs: _account(positions),
    )
    start = date(2026, 9, 1)
    shared = {
        (start + timedelta(days=index)).isoformat(): index / 1000 for index in range(5)
    }
    right_only = {
        (date(2026, 10, 1) + timedelta(days=index)).isoformat(): (index + 2) / 1000
        for index in range(20)
    }
    monkeypatch.setattr(
        portfolio,
        "_load_daily_return_series",
        lambda symbol: shared if symbol == "sh600519" else shared | right_only,
    )

    result = portfolio.get_portfolio_research("agent-one")

    assert result["correlations"] == []
    assert result["summary"]["insufficientCorrelationPairCount"] == 1
    assert result["summary"]["unavailableCorrelationPairCount"] == 0


def test_expired_analysis_budget_marks_selected_series_without_starting_fetch(
    monkeypatch,
):
    positions = [_position("sh600519", "贵州茅台", "50000.00")]
    monkeypatch.setattr(
        portfolio.paper,
        "get_account_snapshot",
        lambda *_args, **_kwargs: _account(positions),
    )
    monkeypatch.setattr(portfolio, "ANALYSIS_DEADLINE_SECONDS", -1.0)
    monkeypatch.setattr(
        portfolio,
        "_load_daily_return_series",
        lambda _symbol: (_ for _ in ()).throw(
            AssertionError("fetch should be skipped")
        ),
    )

    result = portfolio.get_portfolio_research("agent-one")

    assert result["positions"][0]["returnSeriesStatus"] == "deadline"
    assert result["coverage"]["deadlineSkippedPositionCount"] == 1
    assert result["coverage"]["candleLoadedPositionCount"] == 0


def test_route_returns_typed_research_and_maps_missing_account(monkeypatch):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)
    empty_account = _account([], cash="1000000.00", equity="1000000.00")
    monkeypatch.setattr(
        portfolio.paper, "get_account_snapshot", lambda *_args, **_kwargs: empty_account
    )

    response = client.get("/api/financial-portfolios/agent-one/research")

    assert response.status_code == 200
    assert response.json()["simulationOnly"] is True
    assert response.json()["summary"]["cashWeightPercent"] == "100.00"
    assert response.json()["positions"] == []

    monkeypatch.setattr(
        portfolio.paper,
        "get_account_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            paper.AccountNotOpenedError("尚未开设模拟账户")
        ),
    )
    missing = client.get("/api/financial-portfolios/agent-one/research")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "尚未开设模拟账户"
