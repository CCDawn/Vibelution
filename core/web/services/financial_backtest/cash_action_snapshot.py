"""Bind official cash actions to rounded raw/qfq evidence, including offline replay."""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from datetime import date
from decimal import Decimal
from typing import Any

from . import data

_PRICE = re.compile(r"\d{1,12}(?:\.\d{1,8})?\Z")
_FIELDS = {"open", "high", "low", "close"}


def _prices(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != _FIELDS:
        raise data.BacktestInputError("公司行动价差证据缺少完整OHLC")
    result = dict(value)
    if any(
        not isinstance(item, str) or not _PRICE.fullmatch(item) or Decimal(item) <= 0
        for item in result.values()
    ):
        raise data.BacktestInputError("公司行动价差证据价格无效")
    if Decimal(result["low"]) > min(
        Decimal(result["open"]), Decimal(result["close"])
    ) or Decimal(result["high"]) < max(
        Decimal(result["open"]), Decimal(result["close"])
    ):
        raise data.BacktestInputError("公司行动价差证据OHLC关系无效")
    return result


def _overlap(left: tuple[Decimal, Decimal], right: tuple[Decimal, Decimal]) -> bool:
    return max(left[0], right[0]) <= min(left[1], right[1])


def _verify_pair(pair: Mapping[str, Any], event: Mapping[str, Any]) -> None:
    raw_previous = _prices(pair.get("rawPrevious"))
    raw_current = _prices(pair.get("rawCurrent"))
    qfq_previous = _prices(pair.get("qfqPrevious"))
    qfq_current = _prices(pair.get("qfqCurrent"))
    previous = data._transformation_intervals(raw_previous, qfq_previous)
    current = data._transformation_intervals(raw_current, qfq_current)
    cash = Decimal(event["cashPerShare"])
    previous_close = Decimal(raw_previous["close"])
    if cash >= previous_close:
        raise data.BacktestInputError("现金分红金额不支持当前除息价格")
    additive = (
        "additive" in previous
        and "additive" in current
        and _overlap(
            previous["additive"],
            (current["additive"][0] - cash, current["additive"][1] - cash),
        )
    )
    ratio = (previous_close - cash) / previous_close
    multiplicative = (
        "multiplicative" in previous
        and "multiplicative" in current
        and _overlap(
            previous["multiplicative"],
            (
                current["multiplicative"][0] * ratio,
                current["multiplicative"][1] * ratio,
            ),
        )
    )
    if not (additive or multiplicative):
        raise data.CorporateActionUnsupported((event["exDate"],))


def prepare_action_snapshot(
    symbol: str,
    start: str,
    end: str,
    raw: Mapping[str, Mapping[str, Any]],
    qfq: Mapping[str, Mapping[str, Any]],
    detected: tuple[str, ...],
) -> dict[str, Any]:
    from .corporate_actions import freeze_cash_dividend_artifact
    from .official_dividends import load_cash_dividend_artifact

    draft = load_cash_dividend_artifact(symbol, start_date=start, end_date=end)
    dates = sorted(set(raw) & set(qfq))
    pairs = []
    events = draft.get("events", [])
    by_ex = {
        event["exDate"]: event for event in events if start <= event["exDate"] <= end
    }
    unmatched = sorted(set(detected) - set(by_ex))
    if unmatched:
        raise data.CorporateActionUnsupported(tuple(unmatched))
    for ex_date in sorted(by_ex):
        earlier = [day for day in dates if day < ex_date]
        if ex_date not in dates or not earlier:
            raise data.BacktestInputError("官方除息日缺少完整raw/qfq及前日价格")
        previous_date = earlier[-1]
        pair = {"exDate": ex_date, "previousDate": previous_date}
        for name, rows, day in (
            ("rawPrevious", raw, previous_date),
            ("rawCurrent", raw, ex_date),
            ("qfqPrevious", qfq, previous_date),
            ("qfqCurrent", qfq, ex_date),
        ):
            pair[name] = dict(rows[day].get("_providerPrices") or {})
        _verify_pair(pair, by_ex[ex_date])
        pairs.append(pair)
    draft["priceValidation"] = {"detectedDates": list(detected), "pairs": pairs}
    draft.pop("artifactHash", None)
    return freeze_cash_dividend_artifact(draft)


def validate_action_snapshot(snapshot: data.BacktestSnapshot) -> None:
    from .corporate_actions import validate_cash_dividend_artifact

    artifact = validate_cash_dividend_artifact(
        snapshot.corporate_actions, expected_symbol=snapshot.symbol
    )
    if (
        snapshot.actions_status != "verified_cash_dividends"
        or artifact["coverageStartDate"] != snapshot.start_date
        or artifact["coverageEndDate"] != snapshot.end_date
    ):
        raise data.BacktestInputError("公司行动账本与价格窗口不一致")
    coverage = artifact.get("coverageEvidence")
    if (
        not isinstance(coverage, Mapping)
        or coverage.get("source") != "cninfo"
        or coverage.get("terminalPage") is not True
    ):
        raise data.BacktestInputError("公司行动公告覆盖缺少完整分页证据")
    query_start = data._parse_date(
        coverage.get("queryStartDate"), "queryStartDate"
    ).isoformat()
    query_end = data._parse_date(
        coverage.get("queryEndDate"), "queryEndDate"
    ).isoformat()
    if (
        query_start > snapshot.start_date
        or query_end < snapshot.end_date
        or type(coverage.get("pagesRead")) is not int
        or not 1 <= coverage["pagesRead"] <= 100
    ):
        raise data.BacktestInputError("公司行动公告查询范围未覆盖价格窗口")
    notice_ids = coverage.get("noticeIds")
    if (
        not isinstance(notice_ids, list)
        or len(notice_ids) > 3000
        or any(not isinstance(item, str) or not item for item in notice_ids)
        or len(notice_ids) != len(set(notice_ids))
    ):
        raise data.BacktestInputError("公司行动公告ID证据无效")
    events = artifact["events"]
    if any(
        event["noticeId"] not in notice_ids
        or not query_start <= event["publishedDate"] <= query_end
        for event in events
    ):
        raise data.BacktestInputError("公司行动事件不属于冻结公告查询")
    sessions = {row.date for row in snapshot.candles}
    all_rows = snapshot.warmup_candles + snapshot.candles
    by_date = {row.date: row for row in all_rows}
    for event in events:
        for field in ("recordDate", "exDate", "paymentDate"):
            day = event[field]
            if snapshot.start_date <= day <= snapshot.end_date and day not in sessions:
                raise data.BacktestInputError("公司行动日期缺少对应交易日行情")
    proof = artifact.get("priceValidation")
    if (
        not isinstance(proof, Mapping)
        or set(proof) != {"detectedDates", "pairs"}
        or proof["detectedDates"] != list(snapshot.action_dates)
    ):
        raise data.BacktestInputError("公司行动价格校验依据不一致")
    detected = proof["detectedDates"]
    if (
        not isinstance(detected, list)
        or detected != sorted(set(detected))
        or any(day not in sessions for day in detected)
    ):
        raise data.BacktestInputError("公司行动检测日无效")
    by_ex = {
        event["exDate"]: event
        for event in events
        if snapshot.start_date <= event["exDate"] <= snapshot.end_date
    }
    pairs = proof["pairs"]
    if (
        not isinstance(pairs, list)
        or len(pairs) != len(by_ex)
        or [pair.get("exDate") for pair in pairs if isinstance(pair, Mapping)]
        != sorted(by_ex)
        or set(detected) - set(by_ex)
    ):
        raise data.BacktestInputError("公司行动价格变化与官方事件未逐项匹配")
    for pair in pairs:
        if set(pair) != {
            "exDate",
            "previousDate",
            "rawPrevious",
            "rawCurrent",
            "qfqPrevious",
            "qfqCurrent",
        }:
            raise data.BacktestInputError("公司行动价格校验证据字段无效")
        previous_day = data._parse_date(
            pair["previousDate"], "previousDate"
        ).isoformat()
        earlier = [day for day in by_date if day < pair["exDate"]]
        if (
            previous_day >= pair["exDate"]
            or (earlier and previous_day != max(earlier))
            or (
                date.fromisoformat(pair["exDate"]) - date.fromisoformat(previous_day)
            ).days
            > 10
        ):
            raise data.BacktestInputError("公司行动前交易日证据不连续")
        for key, day in (("rawPrevious", previous_day), ("rawCurrent", pair["exDate"])):
            prices = _prices(pair[key])
            if day in by_date and any(
                Decimal(prices[field]) != Decimal(str(getattr(by_date[day], field)))
                for field in _FIELDS
            ):
                raise data.BacktestInputError("公司行动raw证据与冻结行情不一致")
        _verify_pair(pair, by_ex[pair["exDate"]])


def slice_action_snapshot(
    artifact: Mapping[str, Any], start: str, end: str
) -> dict[str, Any]:
    from .corporate_actions import freeze_cash_dividend_artifact

    draft = deepcopy(dict(artifact))
    draft.pop("artifactHash", None)
    draft["coverageStartDate"], draft["coverageEndDate"] = start, end
    draft["events"] = [
        event
        for event in draft["events"]
        if event["recordDate"] <= end and event["exDate"] >= start
    ]
    draft["priceValidation"]["detectedDates"] = [
        day for day in draft["priceValidation"]["detectedDates"] if start <= day <= end
    ]
    draft["priceValidation"]["pairs"] = [
        pair
        for pair in draft["priceValidation"]["pairs"]
        if start <= pair["exDate"] <= end
    ]
    return freeze_cash_dividend_artifact(draft)
