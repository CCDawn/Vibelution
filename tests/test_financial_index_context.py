import json
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

from core.web.services.financial_market import indices

SYMBOLS = tuple(indices.INDEX_NAMES)
CUTOFF = date(2026, 6, 30)


def quote_wire(*, wrong_symbol=None, duplicate_symbol=None):
    chunks = []
    for symbol in SYMBOLS:
        fields = [""] * 35
        code = symbol[2:]
        if symbol == wrong_symbol:
            code = "000000"
        for index, value in {
            1: indices.INDEX_NAMES[symbol],
            2: code,
            3: "101.25",
            4: "100.00",
            5: "100.50",
            30: "20260630150000",
            31: "1.25",
            32: "1.25",
            33: "102.00",
            34: "100.00",
        }.items():
            fields[index] = value
        chunks.append(f'v_{symbol}="' + "~".join(fields) + '";')
        if symbol == duplicate_symbol:
            chunks.append(f'v_{symbol}="' + "~".join(fields) + '";')
    return "\n".join(chunks)


def daily_rows():
    return [
        ["2026-06-29", "100.00", "101.00", "102.00", "99.00", "unverified-volume"],
        ["2026-06-30", "101.00", "102.00", "103.00", "100.00", "unverified-volume"],
    ]


def response(symbol, rows):
    return json.dumps({"code": 0, "data": {symbol: {"day": rows}}})


def run_context(
    *, cutoff=None, rows_by_symbol=None, raw_by_symbol=None, quote=None, fail_bars=(), limit=5
):
    calls = []
    rows_by_symbol = rows_by_symbol or {}
    raw_by_symbol = raw_by_symbol or {}

    def read(url, encoding="utf-8"):
        calls.append((url, encoding))
        if "qt.gtimg.cn" in url:
            if quote is None:
                raise RuntimeError("quote offline")
            return quote
        param = parse_qs(urlsplit(url).query)["param"][0]
        symbol = param.split(",", 1)[0]
        if symbol in fail_bars:
            raise RuntimeError("daily offline")
        if symbol in raw_by_symbol:
            return raw_by_symbol[symbol]
        return response(symbol, rows_by_symbol.get(symbol, daily_rows()))

    result = indices.get_index_context(
        cutoff=cutoff,
        limit=limit,
        read=read,
        cached=lambda _key, _ttl, load: load(),
    )
    return result, calls


def by_symbol(result):
    return {item["symbol"]: item for item in result["items"]}


def test_realtime_batches_and_validates_all_five_index_quotes():
    result, calls = run_context(quote=quote_wire())
    items = by_symbol(result)

    assert result["status"] == "available"
    assert result["mode"] == "realtime"
    assert result["requestedCutoff"] is None
    assert "cutoff" not in result
    assert datetime.fromisoformat(result["fetchedAt"]).tzinfo == timezone.utc
    assert result["priceUnit"] == "points"
    assert result["adjustment"] == "raw_index"
    assert len([url for url, _ in calls if "qt.gtimg.cn" in url]) == 1
    quote_url = next(url for url, _ in calls if "qt.gtimg.cn" in url)
    assert all(symbol in quote_url for symbol in SYMBOLS)
    assert all(items[symbol]["status"] == "available" for symbol in SYMBOLS)
    assert items["sh000001"]["basis"] == "quote"
    assert items["sh000001"]["quote"] == {
        "price": 101.25,
        "previousClose": 100.0,
        "change": 1.25,
        "changePercent": 1.25,
        "open": 100.5,
        "high": 102.0,
        "low": 100.0,
        "timestamp": "2026-06-30T15:00:00+08:00",
    }
    assert items["sh000001"]["sourceUrl"] == "https://gu.qq.com/sh000001/gp"


def test_historical_cutoff_never_requests_live_quotes_and_rejects_future_rows():
    rows = daily_rows() + [["2026-07-01", "102", "103", "104", "101", "ignored"]]
    result, calls = run_context(
        cutoff=CUTOFF,
        rows_by_symbol={symbol: rows for symbol in SYMBOLS},
    )
    items = by_symbol(result)

    assert result["status"] == "partial"
    assert result["mode"] == "historical"
    assert result["requestedCutoff"] == "2026-06-30"
    assert result["priceUnit"] == "points"
    assert result["adjustment"] == "raw_index"
    assert not any("qt.gtimg.cn" in url for url, _ in calls)
    assert all(",2026-06-30,5,none" in parse_qs(urlsplit(url).query).get("param", [""])[0] for url, _ in calls)
    item = items["sh000001"]
    assert item["status"] == "partial"
    assert item["basis"] == "daily_close"
    assert item["quote"]["date"] == "2026-06-30"
    assert "timestamp" not in item["quote"]
    assert item["quote"]["previousClose"] == 101.0
    assert item["quote"]["change"] == 1.0
    assert item["quote"]["changePercent"] == pytest.approx(100 / 101)
    assert [row["date"] for row in item["candles"]] == ["2026-06-29", "2026-06-30"]
    assert item["rejectedFutureRows"] == 1


@pytest.mark.parametrize(
    "bad_rows",
    [
        [daily_rows()[1], daily_rows()[0]],
        [daily_rows()[0], daily_rows()[0]],
        [["2026-06-29", "100", "nan", "102", "99", "ignored"]],
        [["20260629", "100", "101", "102", "99", "ignored"]],
        [["2026-06-29", "100", True, "102", "99", "ignored"]],
        [["2026-06-29", "100", "103", "102", "99", "ignored"]],
        [["2026-06-29", "100", "101", "102", "101.5", "ignored"]],
    ],
)
def test_unordered_duplicate_nonfinite_or_invalid_ohlc_is_unavailable(bad_rows):
    result, _ = run_context(
        cutoff=CUTOFF,
        rows_by_symbol={SYMBOLS[0]: bad_rows},
    )
    items = by_symbol(result)

    assert result["status"] == "partial"
    assert items[SYMBOLS[0]]["status"] == "unavailable"
    assert items[SYMBOLS[0]]["candles"] == []
    assert "candlesError" in items[SYMBOLS[0]]


def test_one_bar_does_not_infer_previous_close_or_daily_change():
    one_bar = [daily_rows()[-1]]
    result, _ = run_context(
        cutoff=CUTOFF,
        rows_by_symbol={symbol: one_bar for symbol in SYMBOLS},
    )
    quote = by_symbol(result)[SYMBOLS[0]]["quote"]

    assert quote["price"] == 102.0
    assert quote["date"] == "2026-06-30"
    assert "previousClose" not in quote
    assert "change" not in quote
    assert "changePercent" not in quote


def test_future_only_historical_response_is_partial_and_reports_rejected_rows():
    future_rows = [["2026-07-01", "102", "103", "104", "101", "ignored"]]
    result, _ = run_context(
        cutoff=CUTOFF,
        rows_by_symbol={symbol: future_rows for symbol in SYMBOLS},
    )
    items = by_symbol(result)

    assert result["status"] == "partial"
    assert all(item["status"] == "partial" for item in items.values())
    assert all(item["candles"] == [] for item in items.values())
    assert all(item["rejectedFutureRows"] == 1 for item in items.values())
    assert all("quote" not in item for item in items.values())


def test_default_limit_is_two():
    calls = []

    def read(url):
        calls.append(url)
        symbol = parse_qs(urlsplit(url).query)["param"][0].split(",", 1)[0]
        return response(symbol, daily_rows())

    result = indices.get_index_context(
        cutoff=CUTOFF,
        read=read,
        cached=lambda _key, _ttl, load: load(),
    )

    assert result["limit"] == 2
    assert all(len(item["candles"]) == 2 for item in result["items"])
    assert all(",2026-06-30,2,none" in parse_qs(urlsplit(url).query)["param"][0] for url in calls)


def test_partial_quote_and_daily_failures_are_visible_per_index():
    result, _ = run_context(
        quote=quote_wire(wrong_symbol=SYMBOLS[0]),
        fail_bars={SYMBOLS[0], SYMBOLS[1]},
    )
    items = by_symbol(result)

    assert result["status"] == "partial"
    assert items[SYMBOLS[0]]["status"] == "unavailable"
    assert "basis" not in items[SYMBOLS[0]]
    assert items[SYMBOLS[0]]["quoteError"]
    assert items[SYMBOLS[0]]["candlesError"]
    assert items[SYMBOLS[1]]["status"] == "partial"
    assert items[SYMBOLS[1]]["basis"] == "quote"
    assert items[SYMBOLS[1]]["candlesError"]
    assert items[SYMBOLS[2]]["status"] == "available"


def test_live_quote_failure_can_fall_back_to_explicit_daily_close_basis():
    result, _ = run_context(quote=None)
    items = by_symbol(result)

    assert result["status"] == "partial"
    assert items[SYMBOLS[0]]["status"] == "partial"
    assert items[SYMBOLS[0]]["basis"] == "daily_close"
    assert items[SYMBOLS[0]]["quote"]["date"] == "2026-06-30"
    assert "timestamp" not in items[SYMBOLS[0]]["quote"]


def test_duplicate_quote_declaration_and_duplicate_json_keys_are_rejected():
    duplicate_json = (
        '{"code":0,"data":{"sz399001":{"day":[],'
        '"day":[]}}}'
    )
    result, _ = run_context(
        quote=quote_wire(duplicate_symbol=SYMBOLS[0]),
        raw_by_symbol={SYMBOLS[1]: duplicate_json},
    )
    items = by_symbol(result)

    assert items[SYMBOLS[0]]["status"] == "partial"
    assert items[SYMBOLS[0]]["basis"] == "daily_close"
    assert "quoteError" in items[SYMBOLS[0]]
    assert items[SYMBOLS[1]]["status"] == "partial"
    assert items[SYMBOLS[1]]["candles"] == []
    assert "candlesError" in items[SYMBOLS[1]]


def test_output_never_exposes_unverified_index_volume_or_turnover():
    result, _ = run_context(quote=quote_wire())
    forbidden = {"volume", "volumeUnit", "volumeLots", "turnover", "turnoverYuan"}

    def keys(value):
        if isinstance(value, dict):
            yield from value.keys()
            for nested in value.values():
                yield from keys(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from keys(nested)

    assert forbidden.isdisjoint(keys(result))


@pytest.mark.parametrize("limit", [1, 21, True, 2.5])
def test_limit_must_be_an_integer_between_two_and_twenty(limit):
    with pytest.raises(ValueError, match="2–20"):
        indices.get_index_context(
            limit=limit,
            read=lambda *_args: "",
            cached=lambda _key, _ttl, load: load(),
        )
