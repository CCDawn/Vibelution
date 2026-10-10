from __future__ import annotations

from datetime import date

import pytest

from core.web.services.financial_backtest import official_dividends as dividends
from core.web.services.financial_backtest.data import BacktestDataError


def _notice(notice_id: str, title: str, published: str = "2025-06-30") -> dict:
    return {
        "noticeId": notice_id,
        "symbol": "sh600036",
        "publishedDate": published,
        "title": title,
        "sourceUrl": f"https://static.cninfo.com.cn/finalpage/{published}/{notice_id}.PDF",
    }


def _event(
    notice: dict,
    *,
    record_date: str,
    ex_date: str,
    payment_date: str | None = None,
) -> dict:
    payment = payment_date or ex_date
    return {
        "actionId": f"sh600036-{notice['noticeId']}-{record_date}-{ex_date}",
        "noticeId": notice["noticeId"],
        "symbol": "sh600036",
        "publishedDate": notice["publishedDate"],
        "sourceUrl": notice["sourceUrl"],
        "pdfSha256": "a" * 64,
        "title": notice["title"],
        "recordDate": record_date,
        "exDate": ex_date,
        "paymentDate": payment,
        "cashPerShare": "1",
        "stockDividendRatio": "0",
        "capitalizationRatio": "0",
        "evidencePages": [
            {
                "page": 1,
                "excerpt": "每股现金红利1元；股权登记日、除权日和发放日已核验。",
                "excerptSha256": "b" * 64,
            }
        ],
    }


def _prepare_loader(monkeypatch, notices: list[dict], document_dates: dict[str, tuple[str, str]]):
    documents = {
        notice["noticeId"]: {"notice": notice, "noticeId": notice["noticeId"]}
        for notice in notices
    }
    monkeypatch.setattr(dividends.official_filings, "_post_json", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(dividends, "_issuer_identity", lambda *_args: ("gssh600036", "010303"))
    monkeypatch.setattr(
        dividends,
        "_query_all_announcements",
        lambda **_kwargs: (notices, 1, True),
    )
    monkeypatch.setattr(dividends, "_normalize_notice", lambda row, **_kwargs: row)
    monkeypatch.setattr(
        dividends,
        "_validated_notice_document",
        lambda notice, **_kwargs: documents[notice["noticeId"]],
    )
    monkeypatch.setattr(
        dividends,
        "_parse_implementation_dates",
        lambda document: tuple(date.fromisoformat(value) for value in document_dates[document["noticeId"]]),
    )
    parsed_events = {
        notice["noticeId"]: _event(
            notice,
            record_date=document_dates[notice["noticeId"]][0],
            ex_date=document_dates[notice["noticeId"]][1],
        )
        for notice in notices
        if "实施公告" in notice["title"] and not dividends._is_revision_title(notice["title"])
    }
    monkeypatch.setattr(
        dividends,
        "_parse_cash_dividend_document",
        lambda document: parsed_events[document["noticeId"]],
    )
    return parsed_events


def test_notice_title_filter_excludes_equity_change_but_keeps_cash_dividend() -> None:
    assert not dividends._is_dividend_notice("2025年权益变动报告书")
    assert dividends._is_dividend_notice("2024年度权益分派实施公告")
    assert dividends._is_implementation_title("2024年度权益分派实施公告")
    assert dividends._is_proposal_title("2025年度利润分配预案")
    assert dividends._is_proposal_title("2024年度利润分配实施方案公告")
    assert dividends._is_proposal_title("贵州茅台关于调整2024年年度利润分配方案每股分红金额的公告")
    assert dividends._is_proposal_title("2024年年度报告（含利润分配预案）")
    assert dividends._is_proposal_title("2024年年度报告（含利润分配方案）")
    assert dividends._is_proposal_title("贵州茅台关于2024－2026年度现金分红回报规划的公告")
    assert dividends._is_ancillary_support_title(
        "北京市金杜律师事务所关于贵州茅台酒股份有限公司差异化权益分派事项的法律意见书"
    )
    assert dividends._is_ancillary_support_title(
        "贵州茅台关于实施2024年中期权益分派后调整回购股份价格上限的公告"
    )


def test_beijing_exchange_issuer_identity_requires_matching_a_share_code() -> None:
    identity = [{"code": "920185", "category": "A股", "orgId": "nssc920185"}]

    assert dividends._issuer_identity(identity, "920185") == (
        "nssc920185",
        "bj",
    )
    assert dividends._issuer_identity(
        [{"code": "920185", "category": "B股", "orgId": "nssc920185"}],
        "920185",
    ) is None


def test_loader_parses_implementation_dates_before_filtering_window(monkeypatch) -> None:
    old = _notice("1223000001", "2023年度权益分派实施公告", "2024-03-01")
    current = _notice("1223000002", "2025年度权益分派实施公告", "2025-06-30")
    proposal = _notice("1223000003", "2025年度利润分配预案")
    annual_report = _notice("1223000004", "2024年年度报告（含利润分配预案）")
    equity_change = _notice("1223000005", "2025年权益变动报告书")
    notices = [old, current, proposal, annual_report, equity_change]
    parsed = _prepare_loader(
        monkeypatch,
        notices,
        {
            old["noticeId"]: ("2024-04-10", "2024-04-11"),
            current["noticeId"]: ("2025-07-10", "2025-07-11"),
        },
    )
    parsed_ids: list[str] = []

    def parse(document):
        parsed_ids.append(document["noticeId"])
        return parsed[document["noticeId"]]

    monkeypatch.setattr(dividends, "_parse_cash_dividend_document", parse)

    artifact = dividends.load_cash_dividend_artifact(
        "sh600036", start_date="2025-07-09", end_date="2025-07-14"
    )

    assert [event["noticeId"] for event in artifact["events"]] == [current["noticeId"]]
    assert parsed_ids == [current["noticeId"]]
    assert set(artifact["coverageEvidence"]["noticeIds"]) == {
        notice["noticeId"] for notice in notices
    }


def test_old_revision_is_skipped_only_after_linked_schedule_is_proven_outside_window(
    monkeypatch,
) -> None:
    original = _notice("1223000011", "2023年度权益分派实施公告", "2024-03-01")
    revision = _notice(
        "1223000012",
        "关于2023年度权益分派实施公告的更正公告",
        "2024-03-02",
    )
    _prepare_loader(
        monkeypatch,
        [original, revision],
        {original["noticeId"]: ("2024-04-10", "2024-04-11")},
    )
    monkeypatch.setattr(
        dividends,
        "_parse_revision_schedule_dates",
        lambda *_args, **_kwargs: (
            {date(2024, 4, 10)},
            {date(2024, 4, 11)},
        ),
    )

    artifact = dividends.load_cash_dividend_artifact(
        "sh600036", start_date="2025-07-09", end_date="2025-07-14"
    )

    assert artifact["events"] == []


def test_revision_that_moves_schedule_into_window_fails_with_exact_notice(monkeypatch) -> None:
    original = _notice("1223000021", "2024年度权益分派实施公告", "2025-03-01")
    revision = _notice(
        "1223000022",
        "2024年度权益分派实施公告的延期公告",
        "2025-07-01",
    )
    _prepare_loader(
        monkeypatch,
        [original, revision],
        {original["noticeId"]: ("2025-06-10", "2025-06-11")},
    )
    monkeypatch.setattr(
        dividends,
        "_parse_revision_schedule_dates",
        lambda *_args, **_kwargs: (
            {date(2025, 7, 10)},
            {date(2025, 7, 11)},
        ),
    )

    with pytest.raises(BacktestDataError) as caught:
        dividends.load_cash_dividend_artifact(
            "sh600036", start_date="2025-07-09", end_date="2025-07-14"
        )

    assert revision["noticeId"] in str(caught.value)
    assert revision["title"] in str(caught.value)
    assert "当前回测窗口" in str(caught.value)


def test_revision_without_unique_same_notice_link_fails_closed(monkeypatch) -> None:
    original = _notice("1223000031", "2024年度权益分派实施公告", "2025-03-01")
    revision = _notice("1223000032", "2024年度权益分派公告的更正公告", "2025-03-02")
    _prepare_loader(
        monkeypatch,
        [original, revision],
        {original["noticeId"]: ("2025-05-10", "2025-05-11")},
    )

    with pytest.raises(BacktestDataError) as caught:
        dividends.load_cash_dividend_artifact(
            "sh600036", start_date="2025-07-09", end_date="2025-07-14"
        )

    assert revision["noticeId"] in str(caught.value)
    assert revision["title"] in str(caught.value)
    assert "唯一的原实施公告" in str(caught.value)


def test_unknown_dividend_notice_fails_with_notice_id_and_title(monkeypatch) -> None:
    notice = _notice("1223000041", "2025年度利润分配进展公告")
    _prepare_loader(monkeypatch, [notice], {})

    with pytest.raises(BacktestDataError) as caught:
        dividends.load_cash_dividend_artifact(
            "sh600036", start_date="2025-07-09", end_date="2025-07-14"
        )

    assert notice["noticeId"] in str(caught.value)
    assert notice["title"] in str(caught.value)
    assert "已实施公司行动" in str(caught.value)


def test_revision_schedule_parser_requires_full_official_document(monkeypatch) -> None:
    revision = _notice("1223000051", "2024年度权益分派实施公告的更正公告")
    document = {
        "compactPages": [
            ("股权登记日除权（息）日现金红利发放日A股2024年7月10日2024年7月11日2024年7月11日", [])
        ]
    }
    monkeypatch.setattr(dividends, "_validated_notice_document", lambda *_args, **_kwargs: document)

    record_dates, ex_dates = dividends._parse_revision_schedule_dates(
        revision, expected_symbol="sh600036"
    )

    assert record_dates == {date(2024, 7, 10)}
    assert ex_dates == {date(2024, 7, 11)}


def test_real_maotai_notice_fullwidth_share_row_and_column_dates_parse() -> None:
    # Extracted from CNINFO's complete 1218606528.PDF (2023-12-14), SHA-256:
    # 6d17512b6f5a0000d53d8053201ef8a3f934714fdca31e8220ef6f1a9bb67f14.
    text = """重要内容提示：
 每股分配比例
A 股每股现金红利 19.106 元（含税）
 相关日期
股份类别 股权登记日 最后交易日 除权（息）日 现金红利发放日
Ａ股 2023/12/19 － 2023/12/20 2023/12/20
对于合格境外机构投资者（QFII）股东，按 10%的税率代扣代缴后，每股派发现金红利人民币 17.1954 元。"""
    compact = [dividends._compact_with_positions(text)]

    cash, _cash_spans = dividends._parse_cash_per_share(compact)
    record_day, _record_spans = dividends._parse_labeled_date(compact, "recordDate")
    ex_day, _ex_spans = dividends._parse_labeled_date(compact, "exDate")
    payment_day, _payment_spans = dividends._parse_labeled_date(compact, "paymentDate")

    assert str(cash) == "19.106"
    assert record_day == date(2023, 12, 19)
    assert ex_day == date(2023, 12, 20)
    assert payment_day == date(2023, 12, 20)


def test_fullwidth_a_share_cash_context_excludes_qfii_amount() -> None:
    # Mirrors the 2025-06-20 CNINFO notice's amount/QFII wording while exercising
    # its fullwidth share-category marker without Unicode normalization.
    text = (
        "Ａ股每股现金红利27.673元（含税）。"
        + "有关税收说明与分派对象" * 8
        + "按10%的税率代扣代缴企业所得税后，每股派发现金红利人民币24.9057元。"
    )
    compact = [dividends._compact_with_positions(text)]

    cash, spans = dividends._parse_cash_per_share(compact)

    assert str(cash) == "27.673"
    evidence = dividends._make_evidence_pages([text], spans)
    assert "Ａ股每股现金红利27.673元" in evidence[0]["excerpt"]


def test_loader_parses_maotai_2025_single_digit_date_table_before_window_filter(
    monkeypatch,
) -> None:
    # Exact schedule extracted from CNINFO 1223934491.PDF (2025-06-20),
    # SHA-256 8ff3e6e370c75cece700e5474337c8ecf1adb87b01a1a696bae02fd25982af3b.
    notice = {
        "symbol": "sh600519",
        "noticeId": "1223934491",
        "publishedDate": "2025-06-20",
        "title": "贵州茅台2024年年度权益分派实施公告",
        "sourceUrl": "https://static.cninfo.com.cn/finalpage/2025-06-20/1223934491.PDF",
    }
    schedule = """股份类别 股权登记日 最后交易日 除权（息）日 现金红利发放日
Ａ股 2025/6/25 － 2025/6/26 2025/6/26"""
    document = {
        "compactPages": [
            dividends._compact_with_positions(f"2024年年度权益分派实施公告\n{schedule}"),
            dividends._compact_with_positions(f"三、相关日期\n{schedule}"),
        ]
    }

    monkeypatch.setattr(dividends.official_filings, "_post_json", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(dividends, "_issuer_identity", lambda *_args: ("gssh0600519", "sse"))
    monkeypatch.setattr(
        dividends,
        "_query_all_announcements",
        lambda **_kwargs: ([notice], 1, True),
    )
    monkeypatch.setattr(dividends, "_normalize_notice", lambda *_args, **_kwargs: notice)
    monkeypatch.setattr(
        dividends,
        "_validated_notice_document",
        lambda *_args, **_kwargs: document,
    )

    artifact = dividends.load_cash_dividend_artifact(
        "sh600519", start_date="2025-07-09", end_date="2025-07-14"
    )

    assert artifact["coverageStatus"] == "complete"
    assert artifact["coverageEvidence"]["noticeIds"] == ["1223934491"]
    assert artifact["events"] == []


def test_query_requires_every_page_and_preserves_unfiltered_query_scope(monkeypatch) -> None:
    pages = [
        {"totalAnnouncement": 2, "announcements": [{"announcementId": "1"}], "hasMore": True},
        {"totalAnnouncement": 2, "announcements": [{"announcementId": "2"}], "hasMore": False},
    ]
    requests: list[dict] = []
    monkeypatch.setattr(dividends.official_filings, "_announcement_fields", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        dividends.official_filings,
        "_has_more_announcement_pages",
        lambda payload: payload["hasMore"],
    )

    def post_json(_path, fields):
        requests.append(dict(fields))
        return pages[len(requests) - 1]

    monkeypatch.setattr(dividends.official_filings, "_post_json", post_json)

    rows, pages_read, terminal = dividends._query_all_announcements(
        code="600036",
        org_id="gssh600036",
        column="010303",
        query_start=date(2023, 7, 9),
        query_end=date(2025, 7, 14),
    )

    assert [row["announcementId"] for row in rows] == ["1", "2"]
    assert pages_read == 2 and terminal is True
    assert all(request["category"] == "" and request["searchkey"] == "" for request in requests)
    assert all(request["seDate"] == "2023-07-09~2025-07-14" for request in requests)


def test_incomplete_notice_query_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(dividends.official_filings, "_announcement_fields", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(dividends.official_filings, "_has_more_announcement_pages", lambda _payload: True)
    monkeypatch.setattr(
        dividends.official_filings,
        "_post_json",
        lambda *_args, **_kwargs: {
            "totalAnnouncement": 2,
            "announcements": [{"announcementId": "1"}],
            "hasMore": True,
        },
    )

    with pytest.raises(dividends.OfficialDividendError):
        dividends._query_all_announcements(
            code="600036",
            org_id="gssh600036",
            column="010303",
            query_start=date(2023, 7, 9),
            query_end=date(2025, 7, 14),
        )
