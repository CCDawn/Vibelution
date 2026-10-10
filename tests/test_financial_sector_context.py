from __future__ import annotations

import json
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

from core.web.services.financial_market import sectors

NOW = datetime(2026, 10, 10, 6, 20, tzinfo=timezone.utc)


def test_peer_sample_does_not_claim_full_constituent_coverage():
    value = json.loads(peer_wire())
    value["data"]["total"] = 37
    peers, coverage, reason = sectors._parse_peers(
        json_wire(value), requested_symbol="sz300750", now=NOW
    )
    assert len(peers) == 5 and coverage == "partial" and reason == "bounded_member_sample"


def epoch(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp())


def json_wire(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def stock_wire(
    *,
    code: str = "300750",
    market: str = "0",
    name: str = "宁德时代",
    industry: str = "电池",
    quote_time: object = epoch("2026-10-09T15:34:33+08:00"),
) -> str:
    return json_wire(
        {
            "data": {
                "total": 1,
                "diff": [
                    {
                        "f12": code,
                        "f13": market,
                        "f14": name,
                        "f100": industry,
                        "f124": quote_time,
                    }
                ],
            }
        }
    )


def directory_wire(rows: list[dict] | None = None) -> str:
    if rows is None:
        rows = [
            {
                "f12": "BK1172",
                "f14": "电池",
                "f2": "1234.56",
                "f3": "1.25",
                "f86": epoch("2026-10-09T15:39:30+08:00"),
            }
        ]
    return json_wire({"data": {"total": len(rows), "diff": rows}})


def peer_wire(rows: list[dict] | None = None) -> str:
    if rows is None:
        rows = [
            {
                "f12": code,
                "f13": "0",
                "f14": name,
                "f2": str(price),
                "f3": str(change),
                "f124": epoch("2026-10-09T15:34:33+08:00"),
            }
            for code, name, price, change in [
                ("300750", "宁德时代", 297.75, 3.84),
                ("300001", "特锐德", 25.18, 1.22),
                ("300002", "神州泰岳", 12.21, -0.35),
                ("300003", "乐普医疗", 11.08, 0.82),
                ("300004", "南风股份", 6.31, -1.14),
                ("300005", "探路者", 8.18, 0.5),
            ]
        ]
    return json_wire({"data": {"total": len(rows), "diff": rows}})


def fake_market(monkeypatch, *, stock=None, directory=None, peers=None):
    monkeypatch.setattr(sectors, "_now_utc", lambda: NOW)
    calls: list[str] = []
    stock_value = stock if stock is not None else stock_wire()
    directory_value = directory if directory is not None else directory_wire()
    peer_value = peers if peers is not None else peer_wire()

    def read(url: str) -> str:
        calls.append(url)
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        if parsed.path.endswith("ulist.np/get"):
            return stock_value
        if query.get("fs") == ["m:90+t:2"]:
            return directory_value
        if query.get("fs") == ["b:BK1172"]:
            return peer_value
        raise AssertionError(f"unexpected source URL: {url}")

    def cached(_key, _ttl, loader):
        return loader()

    return calls, lambda symbol="300750", cutoff=None: sectors.get_sector_context(
        symbol, cutoff=cutoff, read=read, cached=cached
    )


@pytest.mark.parametrize(
    "symbol",
    ["hk00700", "usNVDA", "../../secret", "sh600519?x=1", ""],
)
def test_rejects_non_a_share_or_non_code_without_network(monkeypatch, symbol):
    calls, get_context = fake_market(monkeypatch)

    result = get_context(symbol)

    assert calls == []
    assert result["status"] == "unavailable"
    assert result["reasonCode"] == "invalid_a_share_symbol"


@pytest.mark.parametrize("cutoff", [date(2026, 10, 9), date(2026, 10, 11)])
def test_past_and_future_cutoffs_fail_closed_before_any_read(monkeypatch, cutoff):
    calls, get_context = fake_market(monkeypatch)

    result = get_context("300750", cutoff=cutoff)

    assert calls == []
    assert result["status"] == "unavailable"
    assert result["requestedCutoff"] == cutoff.isoformat()
    assert result["reasonCode"] == "cutoff_outside_realtime_window"


def test_read_crossing_china_midnight_discards_all_sector_data(monkeypatch):
    calls, get_context = fake_market(monkeypatch)
    clock = iter(
        [
            datetime(2026, 10, 10, 15, 59, 59, tzinfo=timezone.utc),
            datetime(2026, 10, 10, 16, 0, 1, tzinfo=timezone.utc),
        ]
    )
    monkeypatch.setattr(sectors, "_now_utc", lambda: next(clock))

    result = get_context("300750")

    assert len(calls) == 3
    assert result["status"] == "unavailable"
    assert result["reasonCode"] == "china_date_changed_during_read"
    assert result["industry"] is None
    assert result["board"] is None
    assert result["peers"] == []


def test_current_sector_context_has_exact_mapping_and_timestamped_peer_rows(monkeypatch):
    calls, get_context = fake_market(monkeypatch)

    result = get_context("300750", cutoff=date(2026, 10, 10))

    assert len(calls) == 3
    assert result["status"] == "partial"
    assert result["symbol"] == "sz300750"
    assert result["source"] == "东方财富"
    assert result["requestedCutoff"] == "2026-10-10"
    assert result["industry"] == {
        "label": "电池",
        "taxonomy": "eastmoney",
        "stockQuoteTimestamp": "2026-10-09T15:34:33+08:00",
        "classificationObservedAt": result["fetchedAt"],
    }
    assert result["board"] == {
        "code": "BK1172",
        "name": "电池",
        "price": 1234.56,
        "changePercent": 1.25,
        "timestamp": "2026-10-09T15:39:30+08:00",
        "sourceUrl": calls[1],
    }
    assert 1 <= len(result["peers"]) <= 5
    assert all(peer["timestamp"] == "2026-10-09T15:34:33+08:00" for peer in result["peers"])
    assert result["peerCoverage"] == {
        "status": "partial",
        "reasonCode": "peer_output_limit",
        "synchronous": False,
    }
    assert result["conceptCoverage"]["status"] == "unavailable"
    assert result["historyCoverage"]["status"] == "unavailable"
    encoded = json_wire(result)
    assert len(encoded) <= 1_600
    assert "amount" not in encoded.lower() and "turnover" not in encoded.lower()


def test_industry_label_must_map_to_one_exact_board(monkeypatch):
    duplicate = [
        {
            "f12": "BK1172",
            "f14": "电池",
            "f2": "1234.56",
            "f3": "1.25",
            "f86": epoch("2026-10-09T15:39:30+08:00"),
        },
        {
            "f12": "BK1173",
            "f14": "电池",
            "f2": "2234.56",
            "f3": "2.25",
            "f86": epoch("2026-10-09T15:40:30+08:00"),
        },
    ]
    calls, get_context = fake_market(monkeypatch, directory=directory_wire(duplicate))

    result = get_context()

    assert len(calls) == 2
    assert result["status"] == "partial"
    assert result["reasonCode"] == "industry_board_ambiguous"
    assert result["board"] is None and result["peers"] == []
    assert result["industry"]["label"] == "电池"


def test_vendor_roman_numeral_industry_maps_to_one_exact_board(monkeypatch):
    directory = directory_wire(
        [
            {
                "f12": "BK1172",
                "f14": "白酒Ⅱ",
                "f2": "1234.56",
                "f3": "1.25",
                "f86": epoch("2026-10-09T15:39:30+08:00"),
            },
            {
                "f12": "BK1173",
                "f14": "白酒",
                "f2": "2234.56",
                "f3": "2.25",
                "f86": epoch("2026-10-09T15:40:30+08:00"),
            },
        ]
    )
    calls, get_context = fake_market(
        monkeypatch,
        stock=stock_wire(code="600519", market="1", name="贵州茅台", industry="白酒Ⅱ"),
        directory=directory,
    )

    result = get_context("600519")

    assert len(calls) == 3
    assert result["industry"]["label"] == "白酒Ⅱ"
    assert result["board"]["code"] == "BK1172"
    assert result["board"]["name"] == "白酒Ⅱ"


@pytest.mark.parametrize("industry", ["白\u0001酒", "<script>alert(1)</script>"])
def test_vendor_industry_label_rejects_control_characters_and_html(monkeypatch, industry):
    calls, get_context = fake_market(monkeypatch, stock=stock_wire(industry=industry))

    result = get_context()

    assert len(calls) == 1
    assert result["status"] == "unavailable"
    assert result["reasonCode"] == "stock_quote_unavailable"
    assert result["industry"] is None


def test_incomplete_directory_cannot_prove_unique_board_match(monkeypatch):
    partial = json_wire(
        {
            "data": {
                "total": 2,
                "diff": [
                    {
                        "f12": "BK1172",
                        "f14": "电池",
                        "f2": "1234.56",
                        "f3": "1.25",
                        "f86": epoch("2026-10-09T15:39:30+08:00"),
                    }
                ],
            }
        }
    )
    calls, get_context = fake_market(monkeypatch, directory=partial)

    result = get_context()

    assert len(calls) == 2
    assert result["reasonCode"] == "industry_directory_incomplete"
    assert result["board"] is None and result["peers"] == []


def test_board_quote_requires_valid_f86_timestamp_but_peer_quote_is_independent(monkeypatch):
    no_board_time = directory_wire(
        [
            {
                "f12": "BK1172",
                "f14": "电池",
                "f2": "1234.56",
                "f3": "1.25",
                "f86": 0,
            }
        ]
    )
    calls, get_context = fake_market(monkeypatch, directory=no_board_time)

    result = get_context()

    assert len(calls) == 3
    assert result["board"] is None
    assert result["reasonCode"] == "board_quote_unavailable"
    assert result["peerCoverage"]["status"] == "available"
    assert len(result["peers"]) == 5


def test_missing_stock_quote_timestamp_is_null_and_never_relabelled_as_historical(monkeypatch):
    calls, get_context = fake_market(monkeypatch, stock=stock_wire(quote_time=0))

    result = get_context()

    assert len(calls) == 3
    assert result["industry"]["stockQuoteTimestamp"] is None
    assert result["industry"]["classificationObservedAt"] == result["fetchedAt"]
    assert result["status"] == "partial"


def test_future_or_invalid_peer_quotes_are_not_returned(monkeypatch):
    rows = [
        {
            "f12": "300750",
            "f13": "0",
            "f14": "宁德时代",
            "f2": "297.75",
            "f3": "3.84",
            "f124": epoch("2026-10-09T15:34:33+08:00"),
        },
        {
            "f12": "300001",
            "f13": "0",
            "f14": "特锐德",
            "f2": "25.18",
            "f3": "1.22",
            "f124": epoch("2026-10-11T09:30:00+08:00"),
        },
    ]
    _calls, get_context = fake_market(monkeypatch, peers=peer_wire(rows))

    result = get_context()

    assert result["peers"] == []
    assert result["peerCoverage"]["status"] == "partial"
    assert result["peerCoverage"]["reasonCode"] == "peer_rows_incomplete"
    assert "2026-10-11" not in json_wire(result)


def test_duplicate_json_keys_and_mismatched_stock_identity_fail_closed(monkeypatch):
    duplicated = '{"data":{"total":1,"diff":[{"f12":"300750","f12":"300001"}]}}'
    calls, get_context = fake_market(monkeypatch, stock=duplicated)
    result = get_context()
    assert result["status"] == "unavailable"
    assert result["reasonCode"] == "stock_quote_unavailable"
    assert len(calls) == 1

    calls, get_context = fake_market(monkeypatch, stock=stock_wire(code="300001"))
    result = get_context()
    assert result["status"] == "unavailable"
    assert result["board"] is None and len(calls) == 1


def test_duplicate_peer_rows_cannot_be_used(monkeypatch):
    rows = [
        {
            "f12": "300750",
            "f13": "0",
            "f14": "宁德时代",
            "f2": "297.75",
            "f3": "3.84",
            "f124": epoch("2026-10-09T15:34:33+08:00"),
        },
        {
            "f12": "300001",
            "f13": "0",
            "f14": "特锐德",
            "f2": "25.18",
            "f3": "1.22",
            "f124": epoch("2026-10-09T15:34:33+08:00"),
        },
        {
            "f12": "300001",
            "f13": "0",
            "f14": "重复行",
            "f2": "25.18",
            "f3": "1.22",
            "f124": epoch("2026-10-09T15:34:33+08:00"),
        },
    ]
    _calls, get_context = fake_market(monkeypatch, peers=peer_wire(rows))

    result = get_context()

    assert result["peers"] == []
    assert result["peerCoverage"] == {
        "status": "unavailable",
        "reasonCode": "peer_data_unavailable",
    }


def test_sector_source_urls_are_fixed_eastmoney_hosts(monkeypatch):
    calls, get_context = fake_market(monkeypatch)

    result = get_context()

    assert all(urlsplit(url).scheme == "https" for url in calls)
    assert all(urlsplit(url).hostname == "push2.eastmoney.com" for url in calls)
    assert result["sourceUrl"] == "https://quote.eastmoney.com/sz300750.html"
    assert result["board"]["sourceUrl"] == calls[1]
    assert result["peerCoverage"]["synchronous"] is False
    assert all(peer["sourceUrl"].startswith("https://quote.eastmoney.com/") for peer in result["peers"])
