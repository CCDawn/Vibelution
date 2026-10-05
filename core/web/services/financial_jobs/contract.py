"""Shared finance-job request validation and Beijing-time recurrence rules."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from core.web.services import financial_market_service as market

from .errors import FinancialJobValidationError

BEIJING = ZoneInfo("Asia/Shanghai")
ALLOWED_PERIODS = frozenset({7, 30, 90})
ALLOWED_DEPTHS = frozenset({"brief", "basic", "standard", "detailed", "exhaustive"})
EXECUTION_KINDS = frozenset({"now", "once", "daily", "weekdays"})
MAX_SYMBOLS = 10


def normalize_create_request(
    payload: dict[str, Any], *, now: datetime, allow_past_once: bool = False
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise FinancialJobValidationError("研究计划内容无效")
    raw_symbols = payload.get("symbols")
    if not isinstance(raw_symbols, list) or not raw_symbols:
        raise FinancialJobValidationError("至少选择一只 A 股")
    symbols: list[str] = []
    for raw in raw_symbols:
        try:
            normalized = market.normalize_symbol(str(raw or ""))
        except (market.MarketDataError, TypeError, ValueError) as exc:
            raise FinancialJobValidationError("股票代码无效，请使用沪深 A 股代码") from exc
        if not normalized.startswith(("sh", "sz")):
            raise FinancialJobValidationError("股票代码无效，请使用沪深 A 股代码")
        if normalized not in symbols:
            symbols.append(normalized)
    if len(symbols) > MAX_SYMBOLS:
        raise FinancialJobValidationError("每批最多研究 10 只股票")

    try:
        period_days = int(payload.get("periodDays"))
    except (TypeError, ValueError) as exc:
        raise FinancialJobValidationError("资料范围只能选择 7、30 或 90 天") from exc
    if period_days not in ALLOWED_PERIODS:
        raise FinancialJobValidationError("资料范围只能选择 7、30 或 90 天")
    depth = str(payload.get("depth") or "").strip().lower()
    if depth not in ALLOWED_DEPTHS:
        raise FinancialJobValidationError("研究深度无效")

    raw_execution = payload.get("execution")
    if not isinstance(raw_execution, dict):
        raise FinancialJobValidationError("执行方式无效")
    kind = str(raw_execution.get("kind") or "").strip().lower()
    if kind not in EXECUTION_KINDS:
        raise FinancialJobValidationError("执行方式无效")
    if str(raw_execution.get("timezone") or "").strip() != "Asia/Shanghai":
        raise FinancialJobValidationError("执行时区必须是 Asia/Shanghai")

    scheduled_at: str | None = None
    time_of_day: str | None = None
    raw_scheduled = raw_execution.get("scheduledAt")
    raw_time = raw_execution.get("timeOfDay")
    raw_research_date = payload.get("researchDate")
    research_date: str | None = None
    if raw_research_date not in (None, ""):
        try:
            parsed_date = date.fromisoformat(str(raw_research_date))
        except (TypeError, ValueError) as exc:
            raise FinancialJobValidationError("研究日期必须是 YYYY-MM-DD") from exc
        if parsed_date > now.astimezone(BEIJING).date():
            raise FinancialJobValidationError("研究日期不能晚于今天")
        research_date = parsed_date.isoformat()

    if kind == "now":
        if raw_scheduled not in (None, "") or raw_time not in (None, ""):
            raise FinancialJobValidationError("立即研究不能包含计划执行时间")
    elif kind == "once":
        if raw_time not in (None, ""):
            raise FinancialJobValidationError("单次计划不能同时设置每日运行时间")
        scheduled_at = _parse_beijing_datetime(
            raw_scheduled, now=now, allow_past=allow_past_once
        )
        if not allow_past_once and datetime.fromisoformat(scheduled_at) <= now.astimezone(BEIJING):
            raise FinancialJobValidationError("单次计划必须设置为未来的北京时间")
    else:
        if raw_scheduled not in (None, ""):
            raise FinancialJobValidationError("每日计划不能设置固定日期时间")
        if research_date is not None:
            raise FinancialJobValidationError("每日计划按触发日研究，不能固定历史日期")
        time_of_day = str(raw_time or "").strip()
        if not _valid_time_of_day(time_of_day):
            raise FinancialJobValidationError("运行时间必须使用 HH:MM 格式")

    return {
        "symbols": symbols,
        "periodDays": period_days,
        "depth": depth,
        "execution": {
            "kind": kind,
            "scheduledAt": scheduled_at,
            "timeOfDay": time_of_day,
            "timezone": "Asia/Shanghai",
        },
        "researchDate": research_date,
    }


def schedule_next_run(
    schedule: dict[str, Any], *, now: datetime, strictly_future: bool = True
) -> str | None:
    execution = schedule.get("execution") if isinstance(schedule.get("execution"), dict) else {}
    kind = str(execution.get("kind") or "")
    if kind == "now" or not bool(schedule.get("enabled")):
        return None
    if kind == "once":
        raw = str(execution.get("scheduledAt") or "").strip()
        try:
            candidate = datetime.fromisoformat(raw.replace("Z", "+00:00")) if raw else None
        except ValueError:
            return None
        if candidate is None or candidate.tzinfo is None:
            return None
        local_candidate = candidate.astimezone(BEIJING)
        local_now = now.astimezone(BEIJING)
        if local_candidate > local_now if strictly_future else local_candidate >= local_now:
            return _iso_beijing(local_candidate)
        return None
    time_of_day = str(execution.get("timeOfDay") or "")
    if not _valid_time_of_day(time_of_day):
        return None
    hour, minute = (int(part) for part in time_of_day.split(":"))
    local_now = now.astimezone(BEIJING)
    start_day = local_now.date()
    for offset in range(8):
        candidate_day = start_day + timedelta(days=offset)
        if kind == "weekdays" and candidate_day.weekday() >= 5:
            continue
        candidate = datetime.combine(candidate_day, time(hour, minute), tzinfo=BEIJING)
        if candidate > local_now if strictly_future else candidate >= local_now:
            return _iso_beijing(candidate)
    return None


def due_occurrence(schedule: dict[str, Any], *, now: datetime) -> datetime | None:
    if not bool(schedule.get("enabled")):
        return None
    execution = schedule.get("execution") if isinstance(schedule.get("execution"), dict) else {}
    kind = str(execution.get("kind") or "")
    local_now = now.astimezone(BEIJING)
    if kind == "once":
        raw = str(execution.get("scheduledAt") or "").strip()
        try:
            parsed_candidate = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed_candidate.tzinfo is None:
            return None
        candidate = parsed_candidate.astimezone(BEIJING)
    elif kind in {"daily", "weekdays"}:
        time_of_day = str(execution.get("timeOfDay") or "")
        if not _valid_time_of_day(time_of_day):
            return None
        if kind == "weekdays" and local_now.weekday() >= 5:
            return None
        hour, minute = (int(part) for part in time_of_day.split(":"))
        candidate = datetime.combine(local_now.date(), time(hour, minute), tzinfo=BEIJING)
    else:
        return None
    if candidate > local_now:
        return None
    raw_next_run = str(schedule.get("nextRunAt") or "").strip()
    if not raw_next_run:
        return None
    try:
        next_run = datetime.fromisoformat(raw_next_run.replace("Z", "+00:00"))
    except ValueError:
        return None
    if next_run.tzinfo is None or candidate < next_run.astimezone(BEIJING):
        return None
    last = schedule.get("lastOccurrence") if isinstance(schedule.get("lastOccurrence"), dict) else {}
    last_scheduled = str(last.get("scheduledAt") or "").strip()
    if last_scheduled and _same_instant(last_scheduled, candidate):
        return None
    return candidate


def occurrence_batch_id(schedule_id: str, scheduled_at: datetime) -> str:
    try:
        namespace = UUID(str(schedule_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise FinancialJobValidationError("计划标识无效") from exc
    return str(uuid5(namespace, _iso_beijing(scheduled_at)))


def occurrence_research_date(
    schedule: dict[str, Any], *, scheduled_at: datetime, triggered_at: datetime
) -> str:
    fixed = str(schedule.get("researchDate") or "").strip()
    if fixed:
        return fixed
    # Recurring jobs always use the date actually triggered in Beijing time.
    if str((schedule.get("execution") or {}).get("kind") or "") in {"daily", "weekdays"}:
        return triggered_at.astimezone(BEIJING).date().isoformat()
    return triggered_at.astimezone(BEIJING).date().isoformat()


def parse_now(value: datetime | None = None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None:
        return result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    """Legacy name retained for callers; persisted product timestamps use Beijing time."""

    return _iso_beijing(value)


def iso_beijing(value: datetime) -> str:
    return _iso_beijing(value)


def canonical_schedule_id(value: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise FinancialJobValidationError("计划标识无效") from exc


def canonical_batch_id(value: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise FinancialJobValidationError("批次标识无效") from exc


def _parse_beijing_datetime(
    value: Any, *, now: datetime, allow_past: bool = False
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FinancialJobValidationError("单次计划必须指定执行时间")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise FinancialJobValidationError("执行时间必须是有效的 ISO 日期时间") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(hours=8):
        raise FinancialJobValidationError("执行时间必须带北京时间 +08:00 时区")
    result = parsed.astimezone(BEIJING)
    if not allow_past and result <= now.astimezone(BEIJING):
        raise FinancialJobValidationError("单次计划必须设置为未来的北京时间")
    return _iso_beijing(result)


def _valid_time_of_day(value: str) -> bool:
    if len(value) != 5 or value[2] != ":":
        return False
    try:
        hour, minute = (int(part) for part in value.split(":"))
    except (TypeError, ValueError):
        return False
    return 0 <= hour <= 23 and 0 <= minute <= 59


def _iso_beijing(value: datetime) -> str:
    return value.astimezone(BEIJING).isoformat(timespec="seconds")


def _same_instant(raw: str, candidate: datetime) -> bool:
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        return False
    return parsed.astimezone(timezone.utc) == candidate.astimezone(timezone.utc)


__all__ = [
    "ALLOWED_DEPTHS",
    "ALLOWED_PERIODS",
    "BEIJING",
    "EXECUTION_KINDS",
    "MAX_SYMBOLS",
    "canonical_batch_id",
    "canonical_schedule_id",
    "due_occurrence",
    "iso_beijing",
    "iso_utc",
    "normalize_create_request",
    "occurrence_batch_id",
    "occurrence_research_date",
    "parse_now",
    "schedule_next_run",
]
