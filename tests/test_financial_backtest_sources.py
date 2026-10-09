"""Alternative A-share data retains identity, units and whole-source validation."""
import json
from datetime import date
from urllib.parse import parse_qs, urlsplit

import pytest

from core.web.services.financial_backtest import data, eastmoney


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
