"""Bounded recovery for read-only historical market requests, never inference."""

from __future__ import annotations

import math
import socket
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPException, IncompleteRead
from urllib.error import HTTPError, URLError

from core.web.services import financial_market_service as market

_MAX_ATTEMPTS = 2
_BACKOFF_SECONDS = 0.5
_MAX_RETRY_AFTER_SECONDS = 2.0
_TRANSIENT_HTTP = {408, 429, 500, 502, 503, 504}


class HistoricalReadError(market.MarketDataError):
    """Sanitized terminal failure including the number of actual attempts."""

    def __init__(self, reason: str, attempts: int) -> None:
        super().__init__(f"{reason}（已尝试{attempts}次）")
        self.attempts = attempts


def _http_delay(error: HTTPError) -> float | None:
    if error.code not in _TRANSIENT_HTTP:
        return None
    raw = error.headers.get("Retry-After") if error.headers is not None else None
    if raw is None:
        return _BACKOFF_SECONDS
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        try:
            until = parsedate_to_datetime(raw)
            if until.tzinfo is None:
                return None
            seconds = max(0.0, (until - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None
    # Do not clamp a long server cooldown and retry earlier than requested.
    if not math.isfinite(seconds) or not 0 <= seconds <= _MAX_RETRY_AFTER_SECONDS:
        return None
    return max(_BACKOFF_SECONDS, seconds)


def _failure(error: BaseException) -> tuple[str, float | None]:
    cause = error.__cause__ if isinstance(error, market.MarketDataError) else error
    if isinstance(cause, HTTPError):
        return f"行情源返回HTTP {cause.code}", _http_delay(cause)
    if isinstance(cause, URLError):
        cause = cause.reason
    if isinstance(cause, TimeoutError):
        return "行情读取超时", _BACKOFF_SECONDS
    if isinstance(cause, (ConnectionError, IncompleteRead)):
        return "行情连接中断", _BACKOFF_SECONDS
    if isinstance(cause, socket.gaierror) and cause.errno == socket.EAI_AGAIN:
        return "行情域名暂时无法解析", _BACKOFF_SECONDS
    # Certificate, decoding, size, authorization and unknown errors fail closed.
    return "行情读取失败", None


def read_historical(url: str) -> str:
    """Reuse the market reader's size/rate limits; retry one transient GET only."""
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return market._read(url)
        except (market.MarketDataError, HTTPException) as exc:
            reason, delay = _failure(exc)
            cause = exc.__cause__
            if isinstance(cause, HTTPError):
                cause.close()
            if delay is None or attempt == _MAX_ATTEMPTS:
                raise HistoricalReadError(reason, attempt) from exc
            time.sleep(delay)
    raise AssertionError("historical read attempts exhausted")
