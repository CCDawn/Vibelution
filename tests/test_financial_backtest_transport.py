"""Transient historical reads recover without retrying invalid market evidence."""

from __future__ import annotations

import json
import socket
import ssl
from io import BytesIO
from datetime import date, datetime, timedelta, timezone
from email.message import Message
from email.utils import format_datetime
from http.client import BadStatusLine, HTTPException, IncompleteRead
from urllib.error import HTTPError, URLError

import pytest

from core.web.services.financial_backtest import data, transport


def http_error(status=503, retry_after=None):
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return HTTPError("https://provider.invalid/secret", status, "private body", headers, None)


def install_reader(monkeypatch, outcomes):
    calls, sleeps = [], []

    def read(url):
        calls.append(url)
        outcome = outcomes[min(len(calls) - 1, len(outcomes) - 1)]
        if isinstance(outcome, HTTPException):
            raise outcome  # This response-read error escapes the existing market reader.
        if isinstance(outcome, Exception):
            raise transport.market.MarketDataError("private error") from outcome
        return outcome

    monkeypatch.setattr(transport.market, "_read", read)
    monkeypatch.setattr(transport.time, "sleep", sleeps.append)
    return calls, sleeps


@pytest.mark.parametrize("failure", [
    TimeoutError(), URLError(TimeoutError()), ConnectionResetError(),
    URLError(ConnectionAbortedError()), IncompleteRead(b"truncated"),
    URLError(socket.gaierror(socket.EAI_AGAIN, "temporary")),
    *[http_error(status) for status in (408, 429, 500, 502, 503, 504)],
])
def test_transient_get_recovers_once_without_changing_request(monkeypatch, failure):
    calls, sleeps = install_reader(monkeypatch, [failure, "recovered"])
    assert transport.read_historical("https://provider.invalid/query") == "recovered"
    assert calls == ["https://provider.invalid/query"] * 2
    assert sleeps == [0.5]


def test_exhaustion_is_bounded_and_does_not_expose_provider_error(monkeypatch):
    calls, sleeps = install_reader(monkeypatch, [http_error()])
    with pytest.raises(transport.HistoricalReadError) as caught:
        transport.read_historical("https://provider.invalid/query")
    assert caught.value.attempts == 2
    assert "HTTP 503" in str(caught.value)
    assert "secret" not in str(caught.value) and "private" not in str(caught.value)
    assert len(calls) == 2 and sleeps == [0.5]


@pytest.mark.parametrize("failure", [
    *[http_error(status) for status in (400, 401, 403, 404, 501)],
    URLError(ssl.SSLCertVerificationError()),
    URLError(socket.gaierror(socket.EAI_NONAME, "unknown host")),
    ValueError("bad decode"), OSError("unknown OS failure"),
    BadStatusLine("malformed status"),
])
def test_permanent_or_unclassified_failures_are_not_retried(monkeypatch, failure):
    calls, sleeps = install_reader(monkeypatch, [failure, "must not be used"])
    with pytest.raises(transport.HistoricalReadError) as caught:
        transport.read_historical("https://provider.invalid/query")
    assert caught.value.attempts == 1
    assert len(calls) == 1 and sleeps == []


@pytest.mark.parametrize("retry_after", ["3", "3600", "nan", "inf", "-1", "bad date"])
def test_long_or_invalid_server_cooldown_does_not_trigger_early_retry(monkeypatch, retry_after):
    calls, sleeps = install_reader(monkeypatch, [http_error(429, retry_after), "unused"])
    with pytest.raises(transport.HistoricalReadError):
        transport.read_historical("https://provider.invalid/query")
    assert len(calls) == 1 and sleeps == []


def test_short_server_cooldown_is_honored(monkeypatch):
    _, sleeps = install_reader(monkeypatch, [http_error(429, "2"), "ok"])
    assert transport.read_historical("https://provider.invalid/query") == "ok"
    assert sleeps == [2.0]


def test_http_date_cooldown_is_honored_without_clamping():
    now = datetime.now(timezone.utc)
    assert transport._http_delay(http_error(503, format_datetime(now - timedelta(seconds=1)))) == 0.5
    assert transport._http_delay(http_error(503, format_datetime(now + timedelta(hours=1)))) is None


def test_retry_uses_real_reader_limits_and_closes_http_error(monkeypatch):
    calls = []
    failure_body = BytesIO(b"private")

    def open_request(request, timeout):
        calls.append((request.full_url, timeout))
        if len(calls) == 1:
            raise HTTPError(request.full_url, 503, "busy", Message(), failure_body)
        return BytesIO(b'{"code":0,"data":{}}')

    monkeypatch.setattr(transport.market, "urlopen", open_request)
    monkeypatch.setattr(transport.time, "sleep", lambda seconds: None)
    assert transport.read_historical("https://provider.invalid/query") == '{"code":0,"data":{}}'
    assert calls == [("https://provider.invalid/query", 6)] * 2
    assert failure_body.closed


def test_oversized_response_is_never_retried(monkeypatch):
    calls = []

    def open_request(request, timeout):
        calls.append(request.full_url)
        return BytesIO(b"x" * 1_000_001)

    monkeypatch.setattr(transport.market, "urlopen", open_request)
    monkeypatch.setattr(transport.time, "sleep", lambda seconds: None)
    with pytest.raises(transport.HistoricalReadError) as caught:
        transport.read_historical("https://provider.invalid/query")
    assert len(calls) == 1 and caught.value.attempts == 1


def test_malformed_provider_reply_is_a_readable_http_422(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.web.routes import financial_backtests as routes

    install_reader(monkeypatch, ['{"code":0,"data":["wrong shape"]}'])
    monkeypatch.setattr(routes.service, "create_financial_backtest_preview", lambda agent_id, payload: data.prepare_data(payload))
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    with TestClient(app) as client:
        response = client.post("/api/financial-backtests/test/preview", json={
            "symbol": "sh600438", "startDate": "2025-01-01", "endDate": "2025-12-31", "strategy": "趋势",
        })
    assert response.status_code == 422
    assert "股票映射格式无效" in response.json()["detail"]
    assert "sh600438" in response.json()["detail"]


@pytest.mark.parametrize("payload", [
    "not json", "[]", '{"code":false,"data":{}}',
    *[json.dumps({"code": 0, "data": value}) for value in (None, [], [1], "unexpected", 7)],
    '{"code":0,"data":{"sh600438":[]}}',
    '{"code":0,"data":{"sh600438":{"day":{}}}}',
])
def test_invalid_provider_envelopes_are_typed_errors_without_retries(monkeypatch, payload):
    calls, sleeps = install_reader(monkeypatch, [payload])
    with pytest.raises(data.BacktestDataError) as caught:
        data._fetch_window("sh600438", date(2025, 1, 1), date(2025, 12, 31), "none")
    assert "sh600438" in str(caught.value) and "原始价格" in str(caught.value)
    assert len(calls) == 1 and sleeps == []


def test_qfq_absence_is_not_relabelled_or_retried(monkeypatch):
    payload = json.dumps({"code": 0, "data": {"sh600438": {"day": [["2025-01-02", "1", "1", "1", "1", "10"]]}}})
    calls, sleeps = install_reader(monkeypatch, [payload])
    assert data._fetch_window("sh600438", date(2025, 1, 1), date(2025, 12, 31), "qfq") == []
    assert len(calls) == 1 and sleeps == []


@pytest.mark.parametrize(("symbol", "adjustment", "label"), [
    ("sh600438", "none", "原始价格"), ("sh600438", "qfq", "前复权校验"),
    ("sh000001", "none", "交易日历"),
])
def test_terminal_error_identifies_exact_failed_window(monkeypatch, symbol, adjustment, label):
    install_reader(monkeypatch, [TimeoutError()])
    with pytest.raises(data.BacktestDataError) as caught:
        data._fetch_window(symbol, date(2025, 1, 1), date(2025, 12, 31), adjustment)
    for expected in (symbol, "2025-01-01至2025-12-31", label, "已尝试2次"):
        assert expected in str(caught.value)
