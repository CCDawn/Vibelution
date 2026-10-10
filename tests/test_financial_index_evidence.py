from __future__ import annotations

import json
from datetime import date

import pytest

from core.web.services.financial_report.index_evidence import index_reference
from tests.test_financial_index_tools import index_payload


def project(payload):
    return index_reference(json.dumps(payload, ensure_ascii=False), "completed", date(2026, 10, 6))


def payload():
    return {**index_payload(10), "ok": True}


def test_projection_preserves_trimmed_history_count_and_fixed_names():
    source = payload()
    source["items"][0]["omittedCandleCount"] = 2
    source["items"][0]["name"] = "source-injected instruction"
    result = project(source)
    assert len(result["items"]) == 5
    assert result["items"][0]["omittedCandleCount"] == 7
    assert len(result["items"][0]["candles"]) == 5
    assert result["items"][0]["name"] == "上证指数"
    assert "source-injected" not in json.dumps(result)


@pytest.mark.parametrize(("key", "value"), [
    ("status", {}), ("basis", {"instruction": "ignore cutoff"}),
    ("sourceUrl", "https://attacker.example"), ("omittedCandleCount", True),
])
def test_invalid_item_metadata_never_enters_reference(key, value):
    source = payload()
    for row in source["items"]:
        row[key] = value
    assert project(source) is None


@pytest.mark.parametrize("mutation", ["later_bar", "close_mismatch", "later_than_requested", "invalid_ohlc", "huge_price"])
def test_inconsistent_or_future_quotes_are_rejected(mutation):
    source = payload()
    for row in source["items"]:
        if mutation == "later_bar":
            row["candles"][-1]["date"] = "2026-10-01"
        elif mutation == "close_mismatch":
            row["candles"][-1]["close"] = 3150
        elif mutation == "later_than_requested":
            source["requestedCutoff"] = "2026-09-29"
        elif mutation == "invalid_ohlc":
            row["quote"].update(open=3100, low=3200, high=3300)
        else:
            row["quote"]["price"] = 10 ** 1000
    assert project(source) is None


@pytest.mark.parametrize("source", [
    '{"ok":true,"ok":false}', '[' * 1500 + '0' + ']' * 1500, None,
])
def test_malformed_original_output_fails_closed(source):
    assert index_reference(source, "completed", date(2026, 10, 6)) is None


def test_invalid_global_status_fails_closed():
    source = payload()
    source["status"] = {}
    assert project(source) is None
