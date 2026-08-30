"""Deterministic city-level geography for virtual-human-life.

The catalog contains public city-centre coordinates only.  It never reads a
device location and never accepts an address or arbitrary latitude/longitude
from the client.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo


CITY_CATALOG_VERSION = "2026.08"

_CITY_ROWS: tuple[dict[str, Any], ...] = (
    {
        "locationId": "CN-BEIJING",
        "countryCode": "CN",
        "countryName": "中国",
        "regionCode": "BJ",
        "regionName": "北京",
        "cityCode": "BJS",
        "cityName": "北京",
        "timezone": "Asia/Shanghai",
        "locale": "zh-CN",
        "latitude": 39.9042,
        "longitude": 116.4074,
    },
    {
        "locationId": "CN-SHANGHAI",
        "countryCode": "CN",
        "countryName": "中国",
        "regionCode": "SH",
        "regionName": "上海",
        "cityCode": "SHA",
        "cityName": "上海",
        "timezone": "Asia/Shanghai",
        "locale": "zh-CN",
        "latitude": 31.2304,
        "longitude": 121.4737,
    },
    {
        "locationId": "CN-GUANGZHOU",
        "countryCode": "CN",
        "countryName": "中国",
        "regionCode": "GD",
        "regionName": "广东",
        "cityCode": "CAN",
        "cityName": "广州",
        "timezone": "Asia/Shanghai",
        "locale": "zh-CN",
        "latitude": 23.1291,
        "longitude": 113.2644,
    },
    {
        "locationId": "CN-SHENZHEN",
        "countryCode": "CN",
        "countryName": "中国",
        "regionCode": "GD",
        "regionName": "广东",
        "cityCode": "SZX",
        "cityName": "深圳",
        "timezone": "Asia/Shanghai",
        "locale": "zh-CN",
        "latitude": 22.5431,
        "longitude": 114.0579,
    },
    {
        "locationId": "CN-HANGZHOU",
        "countryCode": "CN",
        "countryName": "中国",
        "regionCode": "ZJ",
        "regionName": "浙江",
        "cityCode": "HGH",
        "cityName": "杭州",
        "timezone": "Asia/Shanghai",
        "locale": "zh-CN",
        "latitude": 30.2741,
        "longitude": 120.1551,
    },
    {
        "locationId": "CN-CHENGDU",
        "countryCode": "CN",
        "countryName": "中国",
        "regionCode": "SC",
        "regionName": "四川",
        "cityCode": "CTU",
        "cityName": "成都",
        "timezone": "Asia/Shanghai",
        "locale": "zh-CN",
        "latitude": 30.5728,
        "longitude": 104.0668,
    },
    {
        "locationId": "CN-WUHAN",
        "countryCode": "CN",
        "countryName": "中国",
        "regionCode": "HB",
        "regionName": "湖北",
        "cityCode": "WUH",
        "cityName": "武汉",
        "timezone": "Asia/Shanghai",
        "locale": "zh-CN",
        "latitude": 30.5928,
        "longitude": 114.3055,
    },
    {
        "locationId": "CN-XIAN",
        "countryCode": "CN",
        "countryName": "中国",
        "regionCode": "SN",
        "regionName": "陕西",
        "cityCode": "SIA",
        "cityName": "西安",
        "timezone": "Asia/Shanghai",
        "locale": "zh-CN",
        "latitude": 34.3416,
        "longitude": 108.9398,
    },
    {
        "locationId": "JP-TOKYO",
        "countryCode": "JP",
        "countryName": "日本",
        "regionCode": "13",
        "regionName": "东京都",
        "cityCode": "TYO",
        "cityName": "东京",
        "timezone": "Asia/Tokyo",
        "locale": "ja-JP",
        "latitude": 35.6762,
        "longitude": 139.6503,
    },
    {
        "locationId": "SG-SINGAPORE",
        "countryCode": "SG",
        "countryName": "新加坡",
        "regionCode": "SG",
        "regionName": "新加坡",
        "cityCode": "SIN",
        "cityName": "新加坡",
        "timezone": "Asia/Singapore",
        "locale": "en-SG",
        "latitude": 1.3521,
        "longitude": 103.8198,
    },
    {
        "locationId": "GB-LONDON",
        "countryCode": "GB",
        "countryName": "英国",
        "regionCode": "ENG",
        "regionName": "英格兰",
        "cityCode": "LON",
        "cityName": "伦敦",
        "timezone": "Europe/London",
        "locale": "en-GB",
        "latitude": 51.5072,
        "longitude": -0.1276,
    },
    {
        "locationId": "FR-PARIS",
        "countryCode": "FR",
        "countryName": "法国",
        "regionCode": "IDF",
        "regionName": "法兰西岛",
        "cityCode": "PAR",
        "cityName": "巴黎",
        "timezone": "Europe/Paris",
        "locale": "fr-FR",
        "latitude": 48.8566,
        "longitude": 2.3522,
    },
    {
        "locationId": "US-NEW-YORK",
        "countryCode": "US",
        "countryName": "美国",
        "regionCode": "NY",
        "regionName": "纽约州",
        "cityCode": "NYC",
        "cityName": "纽约",
        "timezone": "America/New_York",
        "locale": "en-US",
        "latitude": 40.7128,
        "longitude": -74.006,
    },
)

_CITY_BY_ID = {str(row["locationId"]): row for row in _CITY_ROWS}


def _projection(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **deepcopy(row),
        "precision": "city_center",
        "sourceKind": "builtin_city_catalog",
        "sourceVersion": CITY_CATALOG_VERSION,
    }


def list_city_locations() -> list[dict[str, Any]]:
    """Return canonical city choices in stable display order."""

    return [_projection(row) for row in _CITY_ROWS]


def resolve_city_location(value: object) -> dict[str, Any]:
    """Resolve a client location id or canonical object through the catalog."""

    location_id = (
        str(value.get("locationId") or "").strip()
        if isinstance(value, dict)
        else str(value or "").strip()
    )
    row = _CITY_BY_ID.get(location_id)
    if row is None:
        raise ValueError(f"Unsupported city location: {location_id or '<empty>'}")
    return _projection(row)


def derive_environment_context(
    location: dict[str, Any],
    *,
    at: datetime | None = None,
) -> dict[str, Any]:
    """Project deterministic local-time facts without inventing external facts."""

    canonical = resolve_city_location(location)
    observed_at = at or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    local = observed_at.astimezone(ZoneInfo(str(canonical["timezone"])))
    month = local.month
    latitude = float(canonical.get("latitude") or 0.0)
    if month in {12, 1, 2}:
        northern_season = "winter"
    elif month in {3, 4, 5}:
        northern_season = "spring"
    elif month in {6, 7, 8}:
        northern_season = "summer"
    else:
        northern_season = "autumn"
    if latitude < 0:
        season = {
            "winter": "summer",
            "spring": "autumn",
            "summer": "winter",
            "autumn": "spring",
        }[northern_season]
    else:
        season = northern_season
    hour = local.hour
    if 5 <= hour < 12:
        day_period = "morning"
    elif 12 <= hour < 18:
        day_period = "afternoon"
    elif 18 <= hour < 23:
        day_period = "evening"
    else:
        day_period = "night"
    return {
        "location": canonical,
        "timezone": str(canonical["timezone"]),
        "locale": str(canonical["locale"]),
        "localDate": local.date().isoformat(),
        "localTime": local.strftime("%H:%M"),
        "season": season,
        "dayPeriod": day_period,
        "weather": None,
        "localNews": [],
        "localEvents": [],
        "externalFactsStatus": "source_required",
        "observedAt": observed_at.astimezone(timezone.utc).isoformat(),
    }


__all__ = [
    "CITY_CATALOG_VERSION",
    "derive_environment_context",
    "list_city_locations",
    "resolve_city_location",
]
