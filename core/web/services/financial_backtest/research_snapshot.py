"""Immutable, point-in-time A-share announcement evidence for AI backtests."""

from __future__ import annotations

import copy
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

from core.web.services import financial_market_service as market
from core.web.services.financial_backtest.contract import sha256_json
from core.web.services.financial_backtest.data import BacktestInputError
from core.web.services.financial_research.as_of import published_date

_SCHEMA_VERSION = 1
_MAX_SYMBOLS = 3
_MAX_DECISION_DATES = 20
_MAX_GROUPS = 20
_MAX_ITEMS_PER_GROUP = 5
_MAX_TITLE_CHARS = 240
_MAX_CODE_CHARS = 96
_MAX_SOURCE_CHARS = 80
_MAX_FETCHED_AT_CHARS = 64
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ALLOWED_NOTICE_HOSTS = {
    "data.eastmoney.com",
    "finance.eastmoney.com",
    "static.cninfo.com.cn",
    "www.cninfo.com.cn",
    "www.sse.com.cn",
    "static.sse.com.cn",
    "query.sse.com.cn",
    "www.szse.cn",
    "disc.static.szse.cn",
    "www.bse.cn",
}
_MARKET_NAMES = {"sh": "上交所", "sz": "深交所", "bj": "北交所"}
_SNAPSHOT_KEYS = {"schemaVersion", "symbols", "decisionDates", "groups", "frozenAt", "researchHash"}
_GROUP_KEYS = {"symbol", "decisionDate", "coverageStatus", "source", "fetchedAt", "warnings", "items"}
_ITEM_KEYS = {"symbol", "code", "publishedDate", "title", "url", "source", "fetchedAt", "coverageStatus"}
_PARTIAL_WARNING = "部分公告来源读取失败或历史覆盖不完整。"
_INVALID_ITEM_WARNING = "部分公告记录缺少可信发布日期、标题、编号或安全链接，已排除。"
_NO_ITEM_WARNING = "当前决策日未取得可复核的历史公告标题。"


def freeze_announcement_research_snapshot(
    symbols: Sequence[str],
    decision_dates: Sequence[str],
    *,
    announcement_loader: Callable[..., Mapping[str, Any]] | None = None,
    now_provider: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Read bounded A-share announcement metadata before each decision date."""
    canonical_symbols = _canonical_symbols(symbols)
    dates = _canonical_dates(decision_dates)
    group_count = len(canonical_symbols) * len(dates)
    if group_count > _MAX_GROUPS:
        raise BacktestInputError("历史公告研究最多支持20个股票与决策日组合")

    # Validate the entire scope above before any public-source read starts.
    from core.web.services import financial_research_service

    load_announcements = announcement_loader or financial_research_service._load_announcements
    frozen_at = _freeze_time(now_provider)

    groups: list[dict[str, Any]] = []
    for symbol in canonical_symbols:
        stock = {
            "symbol": symbol,
            "ticker": symbol[-6:],
            "name": symbol[-6:],
            "market": _MARKET_NAMES[symbol[:2]],
        }
        for decision_date in dates:
            cutoff = date.fromisoformat(decision_date) - timedelta(days=1)
            try:
                payload = load_announcements(stock, cutoff=cutoff)
            except Exception:  # noqa: BLE001 - one provider failure cannot fake evidence
                groups.append(
                    _failed_group(symbol, decision_date)
                )
                continue
            groups.append(
                _freeze_group(
                    symbol,
                    decision_date,
                    payload,
                    default_fetched_at=frozen_at,
                )
            )

    if all(group["coverageStatus"] == "failed" for group in groups):
        raise BacktestInputError("历史公告读取全部失败，无法冻结研究证据")

    snapshot: dict[str, Any] = {
        "schemaVersion": _SCHEMA_VERSION,
        "symbols": list(canonical_symbols),
        "decisionDates": list(dates),
        "groups": groups,
        "frozenAt": frozen_at,
    }
    snapshot["researchHash"] = _snapshot_hash(snapshot)
    return validate_research_snapshot(
        snapshot,
        symbols=canonical_symbols,
        decision_dates=dates,
    )


def validate_research_snapshot(
    payload: Mapping[str, Any],
    *,
    expected_hash: str | None = None,
    symbols: Sequence[str] | None = None,
    decision_dates: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Validate scope, point-in-time metadata and content-addressed identity."""
    if (
        not isinstance(payload, Mapping)
        or set(payload) != _SNAPSHOT_KEYS
        or int(payload.get("schemaVersion") or 0) != _SCHEMA_VERSION
    ):
        raise BacktestInputError("历史公告快照格式或版本无效")
    actual_symbols = _canonical_symbols(payload.get("symbols"))
    actual_dates = _canonical_dates(payload.get("decisionDates"))
    if len(actual_symbols) * len(actual_dates) > _MAX_GROUPS:
        raise BacktestInputError("历史公告快照超过20个股票与决策日组合")
    if symbols is not None and actual_symbols != _canonical_symbols(symbols):
        raise BacktestInputError("历史公告快照标的与回测不匹配")
    if decision_dates is not None and actual_dates != _canonical_dates(decision_dates):
        raise BacktestInputError("历史公告快照决策日与回测不匹配")

    frozen_at = _validated_text(payload.get("frozenAt"), 64)
    if not _valid_timestamp(frozen_at):
        raise BacktestInputError("历史公告快照缺少冻结时间")
    raw_groups = payload.get("groups")
    expected_pairs = {(symbol, day) for symbol in actual_symbols for day in actual_dates}
    if not isinstance(raw_groups, list) or len(raw_groups) != len(expected_pairs):
        raise BacktestInputError("历史公告快照分组不完整")

    seen_pairs: set[tuple[str, str]] = set()
    normalized_groups: list[dict[str, Any]] = []
    for raw_group in raw_groups:
        if not isinstance(raw_group, Mapping):
            raise BacktestInputError("历史公告快照分组格式无效")
        symbol = _canonical_symbols([raw_group.get("symbol")])[0]
        decision_date = _canonical_dates([raw_group.get("decisionDate")])[0]
        pair = (symbol, decision_date)
        if pair not in expected_pairs or pair in seen_pairs:
            raise BacktestInputError("历史公告快照分组标识重复或不匹配")
        seen_pairs.add(pair)
        normalized_groups.append(_validate_group(raw_group, symbol, decision_date))
    if seen_pairs != expected_pairs:
        raise BacktestInputError("历史公告快照分组缺失")
    normalized_groups.sort(key=lambda item: (item["symbol"], item["decisionDate"]))

    normalized: dict[str, Any] = {
        "schemaVersion": _SCHEMA_VERSION,
        "symbols": list(actual_symbols),
        "decisionDates": list(actual_dates),
        "groups": normalized_groups,
        "frozenAt": frozen_at,
    }
    raw_hash = str(payload.get("researchHash") or "")
    computed_hash = _snapshot_hash(normalized)
    if raw_hash != computed_hash:
        raise BacktestInputError("历史公告快照摘要校验失败")
    if expected_hash is not None and raw_hash != str(expected_hash).strip():
        raise BacktestInputError("历史公告快照与回测引用摘要不匹配")
    normalized["researchHash"] = raw_hash
    return normalized


def decision_research_material(
    snapshot: Mapping[str, Any],
    *,
    symbols: Sequence[str],
    decision_date: str,
) -> dict[str, Any]:
    """Project only the frozen A-share notices eligible for one decision."""
    canonical_symbols = _canonical_symbols(symbols)
    canonical_date = _canonical_dates([decision_date])[0]
    valid = validate_research_snapshot(
        snapshot,
        symbols=canonical_symbols,
    )
    if canonical_date not in valid["decisionDates"]:
        raise BacktestInputError("历史公告快照不包含当前决策日")
    groups = [
        group
        for group in valid["groups"]
        if group["decisionDate"] == canonical_date
        and group["symbol"] in canonical_symbols
    ]
    if {group["symbol"] for group in groups} != set(canonical_symbols):
        raise BacktestInputError("历史公告快照缺少当前决策标的")
    groups.sort(key=lambda item: item["symbol"])
    status = (
        "partial"
        if any(group["coverageStatus"] != "available" for group in groups)
        else "available"
    )
    items = sum(len(group["items"]) for group in groups)
    return {
        "asOfDate": canonical_date,
        "symbols": list(canonical_symbols),
        "status": status,
        "groupCount": len(groups),
        "itemCount": items,
        "groups": [
            {
                "symbol": group["symbol"],
                "coverageStatus": group["coverageStatus"],
                "warnings": list(group["warnings"]),
                "items": copy.deepcopy(group["items"]),
            }
            for group in groups
        ],
    }


def research_coverage_summary(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Return the small preview/run coverage projection."""
    valid = validate_research_snapshot(snapshot)
    groups = valid["groups"]
    warnings = _unique(
        warning
        for group in groups
        for warning in group["warnings"]
    )
    status = (
        "partial"
        if any(group["coverageStatus"] != "available" for group in groups)
        else "available"
    )
    item_count = sum(len(group["items"]) for group in groups)
    if status == "partial":
        notice = "历史公告已冻结，部分股票或日期覆盖不完整；决策只使用可验证的已冻结标题。"
    elif item_count:
        notice = f"已冻结{item_count}条决策日前公告标题；不包含公告全文或财务数值。"
    else:
        notice = "历史公告查询已完成，未发现决策日前可用公告标题。"
    return {
        "status": status,
        "groupCount": len(groups),
        "availableGroupCount": sum(
            group["coverageStatus"] == "available" for group in groups
        ),
        "partialGroupCount": sum(
            group["coverageStatus"] == "partial" for group in groups
        ),
        "failedGroupCount": sum(
            group["coverageStatus"] == "failed" for group in groups
        ),
        "itemCount": item_count,
        "notice": notice,
        "warnings": warnings,
    }


def _freeze_group(
    symbol: str,
    decision_date: str,
    payload: Any,
    *,
    default_fetched_at: str,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or str(payload.get("status") or "") != "available":
        return _failed_group(symbol, decision_date)
    fetched_at = _bounded_text(
        payload.get("fetchedAt"), _MAX_FETCHED_AT_CHARS
    ) or default_fetched_at
    source = _bounded_text(payload.get("source"), _MAX_SOURCE_CHARS)
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return _failed_group(symbol, decision_date)
    warnings: list[str] = []
    if not source:
        warnings.append(_PARTIAL_WARNING)
    if payload.get("error"):
        warnings.append(_PARTIAL_WARNING)
    if not _valid_timestamp(fetched_at):
        fetched_at = default_fetched_at
        warnings.append(_PARTIAL_WARNING)
    eligible: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    decision_day = date.fromisoformat(decision_date)
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            warnings.append(_INVALID_ITEM_WARNING)
            continue
        published = _published_day(raw_item.get("publishedAt"))
        if published is None:
            warnings.append(_INVALID_ITEM_WARNING)
            continue
        # Dates from these public endpoints are day-level only. Exclude the
        # whole decision day, even if its row lacks a trustworthy timestamp.
        if published >= decision_day:
            warnings.append(_PARTIAL_WARNING)
            continue
        if not _item_matches_symbol(raw_item, symbol):
            warnings.append(_INVALID_ITEM_WARNING)
            continue
        title = _bounded_text(raw_item.get("title"), _MAX_TITLE_CHARS)
        code = _bounded_text(raw_item.get("articleCode") or raw_item.get("code"), _MAX_CODE_CHARS)
        url = _safe_notice_url(raw_item.get("url"))
        item_source = _bounded_text(
            raw_item.get("publisher") or raw_item.get("source") or source,
            _MAX_SOURCE_CHARS,
        )
        if not title or not code or not url or not item_source:
            warnings.append(_INVALID_ITEM_WARNING)
            continue
        if code in seen_codes:
            continue
        seen_codes.add(code)
        eligible.append(
            {
                "symbol": symbol,
                "code": code,
                "publishedDate": published.isoformat(),
                "title": title,
                "url": url,
                "source": item_source,
                "fetchedAt": fetched_at or "unknown",
                "coverageStatus": "partial" if warnings else "available",
            }
        )
    eligible.sort(key=lambda item: (item["publishedDate"], item["code"]), reverse=True)
    group_status = "partial" if warnings else "available"
    items = eligible[:_MAX_ITEMS_PER_GROUP]
    if not items:
        warnings.append(_NO_ITEM_WARNING)
        group_status = "partial"
    # Keep item-level coverage in sync with the final group status, including
    # warnings that arrived after the first eligible item was normalized.
    for item in items:
        item["coverageStatus"] = group_status
    return {
        "symbol": symbol,
        "decisionDate": decision_date,
        "coverageStatus": group_status,
        "source": source,
        "fetchedAt": fetched_at or "unknown",
        "warnings": _unique(warnings),
        "items": items,
    }


def _item_matches_symbol(raw_item: Mapping[str, Any], symbol: str) -> bool:
    """Reject explicit security identity mismatches from injected source rows."""
    for key in ("symbol", "ticker", "stockCode", "stock_code"):
        raw_identity = raw_item.get(key)
        if raw_identity in (None, ""):
            continue
        text = str(raw_identity).strip()
        try:
            normalized = market.normalize_a_share_symbol(text)
        except (market.MarketDataError, TypeError, ValueError):
            return False
        if normalized != symbol:
            return False
    raw_code = raw_item.get("code")
    if raw_code not in (None, ""):
        text = str(raw_code).strip()
        if re.fullmatch(r"\d{6}", text) or re.fullmatch(r"(?:sh|sz|bj)\d{6}", text, re.IGNORECASE):
            try:
                if market.normalize_a_share_symbol(text) != symbol:
                    return False
            except market.MarketDataError:
                return False
    return True


def _failed_group(symbol: str, decision_date: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "decisionDate": decision_date,
        "coverageStatus": "failed",
        "source": "",
        "fetchedAt": "",
        "warnings": [_PARTIAL_WARNING],
        "items": [],
    }


def _validate_group(
    payload: Mapping[str, Any], symbol: str, decision_date: str
) -> dict[str, Any]:
    if set(payload) != _GROUP_KEYS:
        raise BacktestInputError("历史公告分组包含不支持的字段")
    status = str(payload.get("coverageStatus") or "")
    if status not in {"available", "partial", "failed"}:
        raise BacktestInputError("历史公告分组覆盖状态无效")
    source = _validated_text(payload.get("source"), _MAX_SOURCE_CHARS)
    fetched_at = _validated_text(payload.get("fetchedAt"), _MAX_FETCHED_AT_CHARS)
    if status == "failed":
        if payload.get("items") != [] or not isinstance(payload.get("items"), list):
            raise BacktestInputError("失败的历史公告分组不能包含公告")
        if not isinstance(payload.get("warnings"), list):
            raise BacktestInputError("历史公告分组警告格式无效")
        warnings = _validated_warnings(payload.get("warnings"))
        if not warnings:
            raise BacktestInputError("失败的历史公告分组必须说明覆盖失败")
        return {
            "symbol": symbol,
            "decisionDate": decision_date,
            "coverageStatus": status,
            "source": source,
            "fetchedAt": fetched_at,
            "warnings": warnings,
            "items": [],
        }
    if (status == "available" and not source) or not _valid_timestamp(fetched_at):
        raise BacktestInputError("成功的历史公告分组缺少来源或获取时间")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or len(raw_items) > _MAX_ITEMS_PER_GROUP:
        raise BacktestInputError("每个历史公告分组最多冻结5条公告")
    if status == "available" and not raw_items:
        raise BacktestInputError("没有公告条目的历史分组不能标记为完整覆盖")
    warnings = _validated_warnings(payload.get("warnings"))
    if status == "partial" and not warnings:
        raise BacktestInputError("不完整的历史公告分组必须说明覆盖缺口")
    items: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    decision_day = date.fromisoformat(decision_date)
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            raise BacktestInputError("历史公告条目格式无效")
        if set(raw_item) != _ITEM_KEYS:
            raise BacktestInputError("历史公告条目包含不支持的字段")
        item_symbol = _canonical_symbols([raw_item.get("symbol")])[0]
        code = _validated_text(raw_item.get("code"), _MAX_CODE_CHARS)
        published = _published_day(raw_item.get("publishedDate"))
        title = _validated_text(raw_item.get("title"), _MAX_TITLE_CHARS)
        url = _safe_notice_url(_validated_text(raw_item.get("url"), 2_000))
        item_source = _validated_text(raw_item.get("source"), _MAX_SOURCE_CHARS)
        item_fetched_at = _validated_text(raw_item.get("fetchedAt"), _MAX_FETCHED_AT_CHARS)
        item_status = str(raw_item.get("coverageStatus") or "")
        if (
            item_symbol != symbol
            or not code
            or code in seen_codes
            or published is None
            or published >= decision_day
            or not title
            or not url
            or not item_source
            or not _valid_timestamp(item_fetched_at)
            or item_fetched_at != fetched_at
            or item_status != status
        ):
            raise BacktestInputError("历史公告条目来源、日期或标的无效")
        seen_codes.add(code)
        items.append(
            {
                "symbol": item_symbol,
                "code": code,
                "publishedDate": published.isoformat(),
                "title": title,
                "url": url,
                "source": item_source,
                "fetchedAt": item_fetched_at,
                "coverageStatus": item_status,
            }
        )
    items.sort(key=lambda item: (item["publishedDate"], item["code"]), reverse=True)
    return {
        "symbol": symbol,
        "decisionDate": decision_date,
        "coverageStatus": status,
        "source": source,
        "fetchedAt": fetched_at,
        "warnings": warnings,
        "items": items,
    }


def _canonical_symbols(values: Any) -> tuple[str, ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or not values:
        raise BacktestInputError("历史公告研究必须指定A股标的")
    if len(values) > _MAX_SYMBOLS:
        raise BacktestInputError("历史公告研究最多支持3只A股")
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise BacktestInputError("历史公告研究包含无效A股代码")
        try:
            normalized.append(market.normalize_a_share_symbol(value))
        except market.MarketDataError as exc:
            raise BacktestInputError("历史公告研究仅支持A股") from exc
    if len(set(normalized)) != len(normalized):
        raise BacktestInputError("历史公告研究标的不能重复")
    return tuple(sorted(normalized))


def _canonical_dates(values: Any) -> tuple[str, ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or not values:
        raise BacktestInputError("历史公告研究必须指定决策日")
    if len(values) > _MAX_DECISION_DATES:
        raise BacktestInputError("历史公告研究最多支持20个决策日")
    dates: list[str] = []
    for value in values:
        if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
            raise BacktestInputError("历史公告研究决策日必须是YYYY-MM-DD日期")
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise BacktestInputError("历史公告研究决策日无效") from exc
        if parsed.isoformat() != value:
            raise BacktestInputError("历史公告研究决策日无效")
        dates.append(value)
    if len(set(dates)) != len(dates) or dates != sorted(dates):
        raise BacktestInputError("历史公告研究决策日必须按时间递增且不重复")
    return tuple(dates)


def _published_day(value: Any) -> date | None:
    return published_date(value)


def _safe_notice_url(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) > 2_000 or any(char.isspace() for char in text):
        return ""
    try:
        parsed = urlsplit(text)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return ""
    if (
        parsed.scheme.lower() != "https"
        or host not in _ALLOWED_NOTICE_HOSTS
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or parsed.fragment
        or not parsed.path
    ):
        return ""
    return text


def _bounded_text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    return text[:limit]


def _validated_text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if value != text or len(text) > limit:
        raise BacktestInputError("历史公告快照文本字段不符合长度或格式限制")
    return text


def _validated_warnings(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise BacktestInputError("历史公告分组警告格式无效")
    warnings: list[str] = []
    for item in value:
        text = _validated_text(item, 240)
        if not text:
            raise BacktestInputError("历史公告分组警告不能为空")
        warnings.append(text)
    if len(set(warnings)) != len(warnings):
        raise BacktestInputError("历史公告分组警告不能重复")
    return warnings


def _unique(values: Any) -> list[str]:
    return list(dict.fromkeys(str(item) for item in values if str(item)))


def _snapshot_hash(snapshot: Mapping[str, Any]) -> str:
    return sha256_json({key: value for key, value in snapshot.items() if key != "researchHash"})


def _freeze_time(now_provider: Callable[[], datetime] | None) -> str:
    current = now_provider() if now_provider is not None else datetime.now(timezone.utc)
    if not isinstance(current, datetime):
        raise BacktestInputError("历史公告快照冻结时间无效")
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec="seconds")


def _valid_timestamp(value: str) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


__all__ = [
    "decision_research_material",
    "freeze_announcement_research_snapshot",
    "research_coverage_summary",
    "validate_research_snapshot",
]
