"""Pure structured-life draft generation and validation rules."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, time
from typing import Any


IDENTITY_KINDS = frozenset({"student", "employee", "freelancer", "unemployed", "retired"})
DAY_TYPES = frozenset({"weekday", "weekend", "holiday"})
ITEM_STATUSES = frozenset({"active", "repairing", "stored", "disposed"})

_CURRENCY_BY_COUNTRY = {
    "CN": "CNY",
    "JP": "JPY",
    "SG": "SGD",
    "GB": "GBP",
    "FR": "EUR",
    "US": "USD",
}

_ROLE_PRESETS: dict[str, dict[str, Any]] = {
    "student": {
        "roleTitle": "本科生",
        "stage": "undergraduate",
        "affiliation": {
            "organizationKind": "school",
            "name": "栖光学院",
            "department": "数字媒体专业",
            "role": "学生",
        },
        "routines": [
            ("weekday", "07:30", "08:10", "通勤去学校", "commute"),
            ("weekday", "08:30", "16:30", "上课与完成课程任务", "上课"),
            ("weekday", "19:30", "21:00", "复习和个人创作", "study"),
            ("weekend", "10:00", "12:00", "整理课程与自由阅读", "personal"),
            ("holiday", "10:30", "12:00", "假期个人安排", "personal"),
        ],
        "incomeTitle": "虚构奖学金与生活补助",
        "incomeMinor": 150_000,
        "expenseTitle": "虚构居住与日常预算",
        "expenseMinor": -120_000,
        "bankBalanceMinor": 420_000,
    },
    "employee": {
        "roleTitle": "视觉设计师",
        "stage": "full_time",
        "affiliation": {
            "organizationKind": "company",
            "name": "栖光创意工作室",
            "department": "品牌设计组",
            "role": "视觉设计师",
        },
        "routines": [
            ("weekday", "08:10", "08:50", "通勤去单位", "commute"),
            ("weekday", "09:00", "17:30", "上班处理设计工作", "上班"),
            ("weekday", "19:30", "21:00", "晚间个人生活", "personal"),
            ("weekend", "10:00", "12:00", "周末采购与整理", "personal"),
            ("holiday", "10:30", "12:00", "假期休息与出行", "personal"),
        ],
        "incomeTitle": "虚构月度工资",
        "incomeMinor": 820_000,
        "expenseTitle": "虚构居住与固定支出",
        "expenseMinor": -260_000,
        "bankBalanceMinor": 1_280_000,
    },
    "freelancer": {
        "roleTitle": "自由插画师",
        "stage": "independent",
        "affiliation": {
            "organizationKind": "studio",
            "name": "个人创作工作室",
            "department": "独立项目",
            "role": "自由职业者",
        },
        "routines": [
            ("weekday", "09:30", "12:00", "自由职业项目创作", "自由职业项目"),
            ("weekday", "14:00", "17:30", "客户沟通与项目交付", "focus"),
            ("weekend", "10:30", "12:00", "作品整理与自由活动", "personal"),
            ("holiday", "11:00", "12:30", "假期灵感记录", "creative"),
        ],
        "incomeTitle": "虚构项目收入预算",
        "incomeMinor": 600_000,
        "expenseTitle": "虚构工作室与生活支出",
        "expenseMinor": -220_000,
        "bankBalanceMinor": 960_000,
    },
    "unemployed": {
        "roleTitle": "待业探索期",
        "stage": "between_roles",
        "affiliation": {
            "organizationKind": "community",
            "name": "个人发展计划",
            "department": "求职与学习",
            "role": "待业者",
        },
        "routines": [
            ("weekday", "09:30", "11:30", "求职与个人安排", "求职与个人安排"),
            ("weekday", "14:00", "16:00", "技能学习与资料整理", "learning"),
            ("weekend", "10:30", "12:00", "周末休息与社交", "personal"),
            ("holiday", "11:00", "12:00", "假期生活整理", "personal"),
        ],
        "incomeTitle": "虚构家庭支持预算",
        "incomeMinor": 180_000,
        "expenseTitle": "虚构基础生活支出",
        "expenseMinor": -160_000,
        "bankBalanceMinor": 360_000,
    },
    "retired": {
        "roleTitle": "退休生活者",
        "stage": "retired",
        "affiliation": {
            "organizationKind": "community",
            "name": "社区文化活动中心",
            "department": "兴趣活动",
            "role": "退休成员",
        },
        "routines": [
            ("weekday", "08:30", "10:00", "晨间锻炼与采购", "wellness"),
            ("weekday", "14:00", "16:00", "退休生活安排与兴趣活动", "退休生活安排"),
            ("weekend", "09:30", "11:30", "家人朋友与社区活动", "social"),
            ("holiday", "10:00", "12:00", "假期家庭活动", "social"),
        ],
        "incomeTitle": "虚构月度退休金",
        "incomeMinor": 420_000,
        "expenseTitle": "虚构居住与健康预算",
        "expenseMinor": -210_000,
        "bankBalanceMinor": 1_860_000,
    },
}


def currency_for_location(home_location: dict[str, Any]) -> str:
    return _CURRENCY_BY_COUNTRY.get(
        str(home_location.get("countryCode") or "").strip().upper(),
        "USD",
    )


def build_default_life_draft(
    *,
    draft_id: str,
    home_location: dict[str, Any],
    identity_kind: str,
    local_date: date,
) -> dict[str, Any]:
    """Build an editable fictional draft; it is not a committed fact set."""

    kind = str(identity_kind or "").strip().lower()
    if kind not in IDENTITY_KINDS:
        raise ValueError(f"Unsupported life identity kind: {kind or '<empty>'}")
    preset = _ROLE_PRESETS[kind]
    currency = currency_for_location(home_location)
    city_name = str(home_location.get("cityName") or "").strip()
    identity_id = f"identity-{draft_id}"
    affiliation_id = f"affiliation-{draft_id}"
    account_cash_id = f"account-cash-{draft_id}"
    account_bank_id = f"account-bank-{draft_id}"
    routines = [
        {
            "routineId": f"routine-{draft_id}-{index}",
            "dayType": day_type,
            "startTime": start,
            "endTime": end,
            "title": title,
            "activityKind": activity_kind,
            "affiliationId": affiliation_id if day_type == "weekday" else "",
            "timezone": str(home_location.get("timezone") or "UTC"),
        }
        for index, (day_type, start, end, title, activity_kind) in enumerate(
            preset["routines"], start=1
        )
    ]
    return {
        "draftId": str(draft_id),
        "homeLocation": deepcopy(home_location),
        "currency": currency,
        "fictionalData": True,
        "identity": {
            "identityId": identity_id,
            "kind": kind,
            "roleTitle": str(preset["roleTitle"]),
            "stage": str(preset["stage"]),
            "effectiveFrom": local_date.isoformat(),
            "effectiveTo": "",
            "sourceKind": "user_confirmed_life_draft",
        },
        "affiliations": [
            {
                "affiliationId": affiliation_id,
                **deepcopy(preset["affiliation"]),
                "cityLocationId": str(home_location.get("locationId") or ""),
                "effectiveFrom": local_date.isoformat(),
                "effectiveTo": "",
                "sourceKind": "user_confirmed_life_draft",
            }
        ],
        "routines": routines,
        "items": [
            {
                "itemId": f"item-phone-{draft_id}",
                "category": "phone",
                "name": "日常使用的手机",
                "brand": "星屿",
                "model": "S1",
                "status": "active",
                "currentLocation": f"{city_name}的住处",
                "acquiredAt": local_date.isoformat(),
            },
            {
                "itemId": f"item-computer-{draft_id}",
                "category": "computer",
                "name": "个人电脑",
                "brand": "澄光",
                "model": "Air 14",
                "status": "active",
                "currentLocation": f"{city_name}的住处",
                "acquiredAt": local_date.isoformat(),
            },
        ],
        "accounts": [
            {
                "accountId": account_cash_id,
                "name": "随身现金",
                "accountType": "cash",
                "currency": currency,
                "balanceMinor": 18_000,
            },
            {
                "accountId": account_bank_id,
                "name": "虚构生活账户",
                "accountType": "bank",
                "currency": currency,
                "balanceMinor": int(preset["bankBalanceMinor"]),
            },
        ],
        "recurringRules": [
            {
                "ruleId": f"rule-income-{draft_id}",
                "kind": "income",
                "accountId": account_bank_id,
                "title": str(preset["incomeTitle"]),
                "amountMinor": int(preset["incomeMinor"]),
                "currency": currency,
                "frequency": "monthly",
                "nextDueOn": local_date.replace(day=1).isoformat(),
                "status": "active",
            },
            {
                "ruleId": f"rule-expense-{draft_id}",
                "kind": "expense",
                "accountId": account_bank_id,
                "title": str(preset["expenseTitle"]),
                "amountMinor": int(preset["expenseMinor"]),
                "currency": currency,
                "frequency": "monthly",
                "nextDueOn": local_date.replace(day=1).isoformat(),
                "status": "active",
            },
        ],
        "disclaimer": "以上学校、单位、物品和金额均为虚构人物的世界内数据。",
    }


def merge_life_draft_patch(
    payload: dict[str, Any],
    patch: dict[str, Any],
) -> dict[str, Any]:
    """Apply a bounded editable-draft patch without replacing stable ids."""

    merged = deepcopy(payload)
    identity_patch = patch.get("identity")
    if isinstance(identity_patch, dict):
        for key in ("roleTitle", "stage", "effectiveFrom", "effectiveTo"):
            if key in identity_patch:
                merged["identity"][key] = str(identity_patch.get(key) or "").strip()[:160]
    for list_key, editable_fields in (
        (
            "affiliations",
            (
                "organizationKind",
                "name",
                "department",
                "role",
                "effectiveFrom",
                "effectiveTo",
            ),
        ),
        (
            "routines",
            ("dayType", "startTime", "endTime", "title", "activityKind"),
        ),
        (
            "items",
            ("category", "name", "brand", "model", "status", "currentLocation"),
        ),
        (
            "accounts",
            ("name", "accountType", "balanceMinor"),
        ),
        (
            "recurringRules",
            ("kind", "title", "amountMinor", "frequency", "nextDueOn", "status"),
        ),
    ):
        rows_patch = patch.get(list_key)
        if not isinstance(rows_patch, list):
            continue
        rows = list(merged.get(list_key) or [])
        for index, raw_patch in enumerate(rows_patch):
            if index >= len(rows) or not isinstance(raw_patch, dict):
                continue
            row = dict(rows[index])
            for key in editable_fields:
                if key not in raw_patch:
                    continue
                if key in {"balanceMinor", "amountMinor"}:
                    value = raw_patch.get(key)
                    if isinstance(value, bool) or not isinstance(value, int):
                        raise ValueError(f"{key} must use integer minor currency units.")
                    row[key] = value
                else:
                    row[key] = str(raw_patch.get(key) or "").strip()[:200]
            rows[index] = row
        merged[list_key] = rows
    validate_life_draft(merged)
    return merged


def validate_life_draft(payload: dict[str, Any]) -> None:
    identity = payload.get("identity") if isinstance(payload.get("identity"), dict) else {}
    kind = str(identity.get("kind") or "").strip().lower()
    if kind not in IDENTITY_KINDS:
        raise ValueError("Life draft identity kind is invalid.")
    if not str(identity.get("roleTitle") or "").strip():
        raise ValueError("Life draft role title is required.")
    currency = str(payload.get("currency") or "").strip().upper()
    if len(currency) != 3:
        raise ValueError("Life draft currency must use ISO 4217 code.")
    for row in list(payload.get("affiliations") or []):
        if not isinstance(row, dict) or not str(row.get("name") or "").strip():
            raise ValueError("Life draft affiliation name is required.")
    for row in list(payload.get("routines") or []):
        if not isinstance(row, dict) or str(row.get("dayType") or "") not in DAY_TYPES:
            raise ValueError("Life draft routine day type is invalid.")
        start = str(row.get("startTime") or "")
        end = str(row.get("endTime") or "")
        try:
            start_time = time.fromisoformat(start)
            end_time = time.fromisoformat(end)
        except ValueError as exc:
            raise ValueError("Life draft routine time window is invalid.") from exc
        if start_time >= end_time:
            raise ValueError("Life draft routine time window is invalid.")
    for row in list(payload.get("items") or []):
        if not isinstance(row, dict) or str(row.get("status") or "") not in ITEM_STATUSES:
            raise ValueError("Life draft item status is invalid.")
    for row in list(payload.get("accounts") or []):
        if not isinstance(row, dict):
            raise ValueError("Life draft account is invalid.")
        amount = row.get("balanceMinor")
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise ValueError("Life draft account balance must use integer minor units.")
        if str(row.get("currency") or "").upper() != currency:
            raise ValueError("Life draft account currency must match the draft currency.")
    for row in list(payload.get("recurringRules") or []):
        amount = row.get("amountMinor") if isinstance(row, dict) else None
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise ValueError("Life draft recurring amount must use integer minor units.")
        if str(row.get("currency") or "").upper() != currency:
            raise ValueError("Life draft recurring currency must match the draft currency.")
        if str(row.get("frequency") or "").strip().lower() not in {
            "daily",
            "weekly",
            "monthly",
        }:
            raise ValueError("Life draft recurring frequency is invalid.")
        try:
            date.fromisoformat(str(row.get("nextDueOn") or ""))
        except ValueError as exc:
            raise ValueError("Life draft recurring due date is invalid.") from exc


__all__ = [
    "DAY_TYPES",
    "IDENTITY_KINDS",
    "ITEM_STATUSES",
    "build_default_life_draft",
    "currency_for_location",
    "merge_life_draft_patch",
    "validate_life_draft",
]
