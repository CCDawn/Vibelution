"""Alternative A-share data retains identity, units and whole-source validation."""
import json
from datetime import date
from urllib.parse import parse_qs, urlsplit

import pytest

from core.web.services.financial_backtest import basket_data, data, eastmoney, sina


def test_rounded_prices_keep_both_transform_hypotheses_without_inventing_actions():
    # Sina bj920185: the published factor is constant across these sessions.
    days = ["2025-11-05", "2025-11-06", "2025-11-07"]
    fields = ("open", "high", "low", "close")
    raw = {day: {"_providerPrices": dict(zip(fields, prices))} for day, prices in zip(days, [
        ("34.220", "36.500", "34.220", "35.740"),
        ("35.700", "36.800", "35.400", "35.850"),
        ("35.850", "38.600", "35.020", "37.370"),
    ])}
    qfq = {day: {"_providerPrices": dict(zip(fields, prices))} for day, prices in zip(days, [
        ("33.85", "36.10", "33.85", "35.35"),
        ("35.31", "36.40", "35.01", "35.46"),
        ("35.46", "38.18", "34.64", "36.96"),
    ])}
    assert data._action_dates(raw, qfq, date(2025, 11, 6), date(2025, 11, 7)) == ()
    # A material factor change still fails even when the preceding bar admits
    # both an additive and multiplicative explanation.
    qfq[days[-1]]["_providerPrices"] = dict(zip(fields, ("32.27", "34.74", "31.52", "33.63")))
    assert data._action_dates(raw, qfq, date(2025, 11, 6), date(2025, 11, 7)) == ("2025-11-07",)


def wire(**overrides):
    return json.dumps({"rc": 0, "data": {"code": "600438", "market": 1,
        "klines": ["2025-01-02,22.16,22.09,22.70,21.82,479841"], **overrides}})


@pytest.mark.parametrize(("mode", "fqt"), [("none", "0"), ("qfq", "1")])
def test_explicit_adjustment_and_provider_volume_units(monkeypatch, mode, fqt):
    urls = []
    monkeypatch.setattr(eastmoney, "read_historical", lambda url: urls.append(url) or wire())
    rows = eastmoney.fetch_window("sh600438", date(2025, 1, 1), date(2025, 12, 31), mode)
    assert parse_qs(urlsplit(urls[0]).query)["fqt"] == [fqt]
    assert parse_qs(urlsplit(urls[0]).query)["secid"] == ["1.600438"]
    assert data._parse_rows(rows, "sh600438")[0]["volume"] == 47_984_100


@pytest.mark.parametrize("payload", [
    wire(code="600000"), wire(market=0), wire(market=True), wire(klines="bad"),
    wire(klines=["2025-01-02,1"]), '{"rc":false,"data":{}}',
    '{"rc":0,"data":[]}', 'invalid json',
])
def test_alternative_envelope_rejects_wrong_identity_or_shape(monkeypatch, payload):
    monkeypatch.setattr(eastmoney, "read_historical", lambda url: payload)
    with pytest.raises(data.BacktestDataError):
        eastmoney.fetch_window("sh600438", date(2025, 1, 1), date(2025, 12, 31), "qfq")


def test_whole_snapshot_fallback_never_bypasses_corporate_actions(monkeypatch):
    calls = []
    def prepare(payload, **kwargs):
        calls.append(kwargs.get("provider", "tencent"))
        raise data.CorporateActionUnsupported(("2025-06-01",))
    monkeypatch.setattr(data, "_prepare_data", prepare)
    with pytest.raises(data.CorporateActionUnsupported):
        data.prepare_data({"dataSource": "auto"})
    assert calls == ["tencent"]


def test_exhausted_sources_preserve_all_failures_and_secondary_action_guard(monkeypatch):
    def failed(payload, **kwargs):
        provider = kwargs.get("provider", "tencent")
        raise data.BacktestDataError("missing raw series" if provider == "tencent" else "connection interrupted")
    monkeypatch.setattr(data, "_prepare_data", failed)
    with pytest.raises(data.BacktestDataError) as failure:
        data.prepare_data({"dataSource": "auto"})
    assert "missing raw series" in str(failure.value)
    assert "connection interrupted" in str(failure.value)
    assert set(failure.value.metadata["sourceFailures"]) == {"tencent", "eastmoney", "sina"}

    def action(payload, **kwargs):
        if kwargs.get("provider") == "eastmoney":
            raise data.CorporateActionUnsupported(("2025-06-01",))
        raise data.BacktestDataError("missing raw series")
    monkeypatch.setattr(data, "_prepare_data", action)
    with pytest.raises(data.CorporateActionUnsupported):
        data.prepare_data({"dataSource": "auto"})


def test_fallback_restarts_each_window_and_keeps_alternative_provenance(monkeypatch):
    primary, secondary = [], []
    def failing(symbol, start, end, adjustment):
        primary.append((symbol, start, adjustment))
        raise data.BacktestDataError("transient source gap")
    def alternate(symbol, start, end, adjustment):
        secondary.append((symbol, start, adjustment))
        dates = ["2025-01-02", "2025-01-03", "2025-01-06"]
        return [[day,"10","10","11","9","100"] for day in dates]
    monkeypatch.setattr(data, "_fetch_window", failing)
    monkeypatch.setattr(eastmoney, "fetch_window", alternate)
    result=data.prepare_data({"symbol":"600438", "startDate":"2025-01-03", "endDate":"2025-01-06", "warmupBars":1, "dataSource":"auto"}, today="2026-01-01")
    assert len(primary)==1 and len(secondary)==3
    assert result.source=="东方财富"
    assert result.coverage.tradingCalendarStatus=="eastmoney_index_checked"
    assert "未混用" in result.notice[-1]
    data.validate_snapshot(result)


def test_sina_fallback_keeps_whole_snapshot_and_action_guard(monkeypatch):
    calls = []
    original = data._prepare_data
    def prepare(payload, **kwargs):
        provider = kwargs.get("provider", "tencent")
        calls.append(provider)
        if provider != "sina":
            raise data.BacktestDataError("provider unavailable")
        return original(payload, **kwargs)
    def rows(symbol, start, end, adjustment):
        return [[day, "10", "10", "11", "9", "100.01"] for day in ["2025-01-02", "2025-01-03", "2025-01-06"]]
    monkeypatch.setattr(data, "_prepare_data", prepare)
    monkeypatch.setattr(sina, "fetch_window", rows)
    payload = {"symbol": "600438", "startDate": "2025-01-03", "endDate": "2025-01-06", "warmupBars": 1, "dataSource": "auto"}
    result = data.prepare_data(payload, today="2026-01-01")
    assert calls == ["tencent", "eastmoney", "sina"]
    assert result.source == "新浪财经"
    assert result.coverage.tradingCalendarStatus == "sina_index_checked"
    assert result.candles[0].volume == 10001
    data.validate_snapshot(result)
    def action(*args, **kwargs):
        raise data.CorporateActionUnsupported(("2025-01-03",))
    monkeypatch.setattr(sina, "fetch_window", action)
    with pytest.raises(data.CorporateActionUnsupported):
        data.prepare_data(payload, today="2026-01-01")


def test_basket_restarts_all_assets_on_sina_without_mixing_sources(monkeypatch):
    calls = []
    original = data._prepare_data
    def prepare(payload, **kwargs):
        provider = kwargs.get("provider", "tencent")
        calls.append((provider, payload["symbol"]))
        if provider != "sina" and payload["symbol"] == "sz000001":
            raise data.BacktestDataError("second asset unavailable")
        return original(payload, **kwargs)
    def rows(*args):
        return [[day, "10", "10", "11", "9", "100"] for day in ["2025-01-02", "2025-01-03", "2025-01-06"]]
    monkeypatch.setattr(data, "_prepare_data", prepare)
    monkeypatch.setattr(data, "_fetch_window", rows)
    monkeypatch.setattr(eastmoney, "fetch_window", rows)
    monkeypatch.setattr(sina, "fetch_window", rows)
    result = basket_data.prepare_basket_data(["sh600438", "sz000001"], "2025-01-03", "2025-01-06", warmup_bars=1, today="2026-01-01", data_source="auto")
    assert calls == [(provider, symbol) for provider in ("tencent", "eastmoney", "sina") for symbol in ("sh600438", "sz000001")]
    assert {asset.source for asset in result.assets.values()} == {"新浪财经"}
    assert "未跨来源拼接" in result.notice[-1]
