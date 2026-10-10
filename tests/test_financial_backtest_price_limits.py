from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta

import pytest

from core.web.services.financial_backtest.contract import sha256_json
from core.web.services.financial_backtest.data import BacktestInputError
from core.web.services.financial_backtest.price_limits import (
    LEGACY_LIMIT_MODEL,
    SUPPLIED_LIMIT_MODEL,
    freeze_price_limits,
    locked_reason,
    normalize_limit_model,
    slice_price_limits,
    validate_price_limits,
)

_SYMBOL = "sh600519"
_DATES = ["2026-01-05", "2026-01-06"]
_CANDLES = [
    {
        "date": _DATES[0],
        "open": 10.00,
        "high": 10.60,
        "low": 9.40,
        "close": 10.20,
        "volume": 100_000,
    },
    {
        "date": _DATES[1],
        "open": 10.20,
        "high": 10.80,
        "low": 9.80,
        "close": 10.40,
        "volume": 90_000,
    },
]


def _draft(
    *,
    symbol: str = _SYMBOL,
    url: str = "https://static.cninfo.com.cn/notices/limits.csv",
    records: list[dict] | None = None,
) -> dict:
    return {
        "schemaVersion": 1,
        "symbol": symbol,
        "source": {
            "url": url,
            "sha256": "a" * 64,
            "fetchedAt": "2026-01-07T02:30:00Z",
        },
        "records": deepcopy(
            records
            if records is not None
            else [
                {"date": _DATES[0], "upper": "12.31", "lower": "8.79"},
                {"date": _DATES[1], "upper": None, "lower": None},
            ]
        ),
    }


def _rehash(artifact: dict) -> None:
    artifact["artifactHash"] = sha256_json(
        {
            "schemaVersion": artifact["schemaVersion"],
            "symbol": artifact["symbol"],
            "source": artifact["source"],
            "records": artifact["records"],
        }
    )


def test_freeze_copies_and_hashes_user_limits_without_deriving_bands() -> None:
    draft = _draft()
    frozen = freeze_price_limits(draft, _SYMBOL, _DATES, _CANDLES)

    assert frozen["schemaVersion"] == 1
    assert frozen["symbol"] == _SYMBOL
    assert frozen["records"][0] == {
        "date": _DATES[0],
        "upper": "12.31",
        "lower": "8.79",
    }
    assert frozen["records"][1]["upper"] is None
    assert frozen["records"][1]["lower"] is None
    assert frozen["artifactHash"] == sha256_json(
        {key: frozen[key] for key in ("schemaVersion", "symbol", "source", "records")}
    )
    assert validate_price_limits(frozen, _SYMBOL, _DATES, _CANDLES) == frozen

    draft["records"][0]["upper"] = "11.00"
    assert frozen["records"][0]["upper"] == "12.31"


def test_limit_model_defaults_and_explicit_legacy_keep_the_legacy_model() -> None:
    assert normalize_limit_model(None) == LEGACY_LIMIT_MODEL
    assert normalize_limit_model({}) == LEGACY_LIMIT_MODEL
    assert normalize_limit_model({"priceLimitModel": None}) == LEGACY_LIMIT_MODEL
    assert normalize_limit_model({"price_limit_model": LEGACY_LIMIT_MODEL}) == LEGACY_LIMIT_MODEL
    assert normalize_limit_model({"priceLimitModel": SUPPLIED_LIMIT_MODEL}) == SUPPLIED_LIMIT_MODEL


def test_freeze_requires_exact_sorted_snapshot_coverage() -> None:
    missing = _draft(records=[{"date": _DATES[0], "upper": "12.31", "lower": "8.79"}])
    with pytest.raises(BacktestInputError, match="日期"):
        freeze_price_limits(missing, _SYMBOL, _DATES, _CANDLES)

    with pytest.raises(BacktestInputError, match="排序"):
        freeze_price_limits(_draft(), _SYMBOL, list(reversed(_DATES)), _CANDLES)


def test_frozen_hash_rejects_tampering_and_rehashed_ohlc_violation() -> None:
    frozen = freeze_price_limits(_draft(), _SYMBOL, _DATES, _CANDLES)
    tampered = deepcopy(frozen)
    tampered["records"][0]["upper"] = "12.30"
    with pytest.raises(BacktestInputError, match="摘要"):
        validate_price_limits(tampered, _SYMBOL, _DATES, _CANDLES)

    rehashed = deepcopy(frozen)
    rehashed["records"][0]["upper"] = "10.00"
    rehashed["records"][0]["lower"] = "9.00"
    _rehash(rehashed)
    with pytest.raises(BacktestInputError, match="OHLC"):
        validate_price_limits(rehashed, _SYMBOL, _DATES, _CANDLES)


def test_freeze_rejects_wrong_symbol_and_untrusted_or_ambiguous_source() -> None:
    with pytest.raises(BacktestInputError, match="标的"):
        freeze_price_limits(_draft(), "sz000001", _DATES, _CANDLES)

    for url in (
        "http://cninfo.com.cn/limits.csv",
        "https://example.com/limits.csv",
        "https://user@cninfo.com.cn/limits.csv",
        "https://cninfo.com.cn/limits.csv#fragment",
        "https://cninfo.com.cn.evil.test/limits.csv",
    ):
        with pytest.raises(BacktestInputError, match="URL"):
            freeze_price_limits(_draft(url=url), _SYMBOL, _DATES, _CANDLES)


@pytest.mark.parametrize(
    ("upper", "lower"),
    [
        (None, "9.00"),
        ("10.00", None),
        ("9.00", "10.00"),
        ("0", "0.01"),
        ("1e1", "1.00"),
        ("10000000.01", "1.00"),
        ("10.001", "1.00"),
    ],
)
def test_freeze_rejects_invalid_limit_pairs(upper: str | None, lower: str | None) -> None:
    draft = _draft(
        records=[
            {"date": _DATES[0], "upper": upper, "lower": lower},
            {"date": _DATES[1], "upper": None, "lower": None},
        ]
    )
    with pytest.raises(BacktestInputError):
        freeze_price_limits(draft, _SYMBOL, _DATES, _CANDLES)


def test_slice_rehashes_exact_coverage_and_blocks_outside_dates() -> None:
    frozen = freeze_price_limits(_draft(), _SYMBOL, _DATES, _CANDLES)
    sliced = slice_price_limits(frozen, [_DATES[1]])

    assert sliced["records"] == [frozen["records"][1]]
    assert sliced["artifactHash"] != frozen["artifactHash"]
    assert validate_price_limits(sliced, _SYMBOL, [_DATES[1]], [_CANDLES[1]]) == sliced
    with pytest.raises(BacktestInputError, match="超出"):
        slice_price_limits(frozen, ["2026-01-07"])


def test_locked_reason_checks_open_price_equality_without_one_price_rule() -> None:
    record = {"date": _DATES[0], "upper": "10.60", "lower": "9.00"}
    buy_candle = {**_CANDLES[0], "open": 10.60}
    sell_candle = {**_CANDLES[0], "open": 9.00, "high": 10.60}

    assert locked_reason(buy_candle, "buy", record) == "open_at_supplied_limit_up"
    assert locked_reason(sell_candle, "sell", record) == "open_at_supplied_limit_down"
    assert locked_reason(_CANDLES[0], "buy", record) is None
    assert locked_reason(_CANDLES[0], "sell", {**record, "upper": None, "lower": None}) is None


def test_freeze_rejects_unknown_fields_and_more_than_5000_records() -> None:
    with_unknown = _draft()
    with_unknown["verified"] = True
    with pytest.raises(BacktestInputError, match="未知字段"):
        freeze_price_limits(with_unknown, _SYMBOL, _DATES, _CANDLES)

    count = 5_001
    dates = [(date(2026, 1, 1) + timedelta(days=index)).isoformat() for index in range(count)]
    records = [
        {"date": day, "upper": "11.00", "lower": "9.00"} for day in dates
    ]
    candles = [
        {"date": day, "open": 10, "high": 10.5, "low": 9.5, "close": 10, "volume": 1}
        for day in dates
    ]
    with pytest.raises(BacktestInputError, match="5000"):
        freeze_price_limits(_draft(records=records), _SYMBOL, dates, candles)


def test_full_5000_session_artifacts_fit_bounded_desktop_import_and_storage() -> None:
    import json

    count = 5_000
    dates = [(date(2006, 1, 1) + timedelta(days=index)).isoformat() for index in range(count)]
    records = [{"date": day, "upper": "11.00", "lower": "9.00"} for day in dates]
    candles = [
        {"date": day, "open": 10, "high": 10.5, "low": 9.5, "close": 10, "volume": 100_000}
        for day in dates
    ]
    frozen = freeze_price_limits(_draft(records=records), _SYMBOL, dates, candles)
    assert len(frozen["records"]) == 5000
    assert validate_price_limits(frozen, _SYMBOL, dates, candles) == frozen
    # Ten assets at the maximum supported window fit compact input and frozen storage.
    drafts = [{**_draft(records=records), "symbol": f"sh600{index:03d}"} for index in range(10)]
    assert len(json.dumps(drafts, separators=(",", ":")).encode("utf-8")) < 4_000_000
    assets = [{"candles": candles, "priceLimits": frozen} for _ in range(10)]
    assert len(json.dumps(assets, separators=(",", ":"))) < 8_000_000
