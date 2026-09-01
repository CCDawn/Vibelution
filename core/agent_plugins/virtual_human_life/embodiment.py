"""Deterministic Companion embodiment with a portrait-safe fallback."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

_MODES = {"portrait", "voice", "live2d", "three_d"}
_ASSET_KINDS = {"portrait", "model", "expression", "background"}
_WEATHER_KEYS = {"weather", "weather.condition", "weather_condition"}
_WEATHER_FRESHNESS = timedelta(hours=3)


def _bounded_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _next_refresh(local_time: datetime | None) -> str:
    if local_time is None:
        return ""
    current = local_time.replace(second=0, microsecond=0)
    minutes = 15 - current.minute % 15
    return (current + timedelta(minutes=minutes)).isoformat()


def _licensed_assets(
    assets: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    licensed: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for raw in assets:
        asset_ref = str(raw.get("assetRef") or "").strip()[:400]
        receipt = str(raw.get("licenseReceipt") or "").strip()[:240]
        source_ref = str(raw.get("sourceRef") or "").strip()[:300]
        structured_entry = bool(str(raw.get("assetKind") or "").strip())
        if (
            not asset_ref
            or not receipt
            or (structured_entry and not source_ref)
            or raw.get("enabled") is False
        ):
            continue
        kind = str(raw.get("assetKind") or "model").strip().lower()[:40]
        if kind not in _ASSET_KINDS:
            continue
        state_key = str(raw.get("stateKey") or "").strip().lower()[:120]
        identity = (kind, state_key, asset_ref)
        if identity in seen:
            continue
        seen.add(identity)
        licensed.append(
            {
                "assetRef": asset_ref,
                "assetKind": kind,
                "stateKey": state_key,
                "licenseReceipt": receipt,
                "sourceRef": source_ref,
            }
        )
    return licensed


def _activity_state(activity: Mapping[str, Any] | None) -> tuple[str, str] | None:
    if not isinstance(activity, Mapping):
        return None
    text = " ".join(
        str(activity.get(key) or "").strip().lower()
        for key in ("activityKind", "kind", "title")
    )
    if any(token in text for token in ("sleep", "rest", "nap", "睡", "休息", "午觉")):
        return "tired", "resting"
    if any(
        token in text
        for token in (
            "study",
            "work",
            "focus",
            "learning",
            "read",
            "学习",
            "工作",
            "复习",
            "阅读",
            "创作",
        )
    ):
        return "focused", "attentive"
    if any(token in text for token in ("celebrate", "party", "庆祝", "聚会")):
        return "happy", "celebrating"
    if any(token in text for token in ("walk", "exercise", "sport", "散步", "运动")):
        return "happy", "breathing"
    return None


def _expression_state(
    *,
    activity: Mapping[str, Any] | None,
    affect: Mapping[str, Any],
    energy: int,
) -> tuple[str, str, str]:
    activity_state = _activity_state(activity)
    if activity_state is not None:
        return (*activity_state, "activity")
    if energy < 35:
        return "tired", "resting", "energy"
    mood = affect.get("mood") if isinstance(affect.get("mood"), Mapping) else {}
    valence = _bounded_int(mood.get("valence"), 0, -100, 100)
    arousal = _bounded_int(mood.get("arousal"), 30, 0, 100)
    if valence >= 30:
        return "happy", "celebrating" if arousal >= 45 else "breathing", "affect"
    if valence <= -20:
        return "low", "breathing", "affect"
    if arousal >= 75:
        return "surprised", "attentive", "affect"
    return "neutral", "breathing", "baseline"


def _place_kind(location: str) -> str:
    normalized = location.lower()
    if any(
        token in normalized
        for token in ("campus", "school", "university", "校园", "学校", "大学")
    ):
        return "campus"
    if any(
        token in normalized
        for token in ("office", "company", "workplace", "公司", "办公室", "单位")
    ):
        return "office"
    if any(
        token in normalized
        for token in ("outdoor", "park", "street", "cafe", "公园", "户外", "街", "咖啡")
    ):
        return "outdoors"
    return "home"


def _day_period(local_time: datetime | None) -> str:
    hour = local_time.hour if local_time is not None else 12
    if 6 <= hour < 18:
        return "day"
    if 18 <= hour < 22:
        return "evening"
    return "night"


def _weather(
    environment: Mapping[str, Any],
    *,
    local_time: datetime | None,
) -> tuple[str, str, bool]:
    facts = environment.get("currentFacts")
    if not isinstance(facts, Sequence) or isinstance(facts, (str, bytes)):
        return "", "", False
    candidates = [
        item
        for item in facts
        if isinstance(item, Mapping)
        and str(item.get("factKey") or "").strip().lower() in _WEATHER_KEYS
    ]
    if not candidates:
        return "", "", False
    fact = max(candidates, key=lambda item: str(item.get("observedAt") or ""))
    observed_at = _parse_datetime(fact.get("observedAt"))
    if local_time is None or observed_at is None:
        return "", "", True
    age = local_time.astimezone(timezone.utc) - observed_at.astimezone(timezone.utc)
    if age < timedelta(0) or age > _WEATHER_FRESHNESS:
        return "", "", True
    value = str(fact.get("value") or "").strip().lower()
    if any(token in value for token in ("rain", "shower", "雨")):
        condition = "rain"
    elif any(token in value for token in ("snow", "雪")):
        condition = "snow"
    else:
        condition = ""
    return condition, str(fact.get("factId") or "").strip()[:200], False


def _scene_key(
    state: Mapping[str, Any],
    environment: Mapping[str, Any],
    *,
    local_time: datetime | None,
) -> tuple[str, str, bool]:
    place = _place_kind(str(state.get("currentLocation") or "home"))
    condition, fact_id, stale_weather = _weather(environment, local_time=local_time)
    if place == "outdoors" and condition:
        return f"outdoors-{condition}", fact_id, stale_weather
    return f"{place}-{_day_period(local_time)}", fact_id, stale_weather


def _matching_asset(
    assets: Sequence[Mapping[str, str]],
    *,
    kind: str,
    state_key: str,
) -> Mapping[str, str] | None:
    exact = next(
        (
            item
            for item in assets
            if item.get("assetKind") == kind and item.get("stateKey") == state_key
        ),
        None,
    )
    if exact is not None:
        return exact
    return next(
        (
            item
            for item in assets
            if item.get("assetKind") == kind and not item.get("stateKey")
        ),
        None,
    )


def _primary_asset(
    assets: Sequence[Mapping[str, str]],
    asset_ref: str,
) -> Mapping[str, str] | None:
    return next(
        (
            item
            for item in assets
            if item.get("assetRef") == asset_ref
            and item.get("assetKind") in {"model", "portrait"}
        ),
        None,
    )


def resolve_embodiment(
    config: Mapping[str, Any] | None,
    *,
    authorized_assets: Sequence[Mapping[str, Any]],
    provider_health: Mapping[str, Mapping[str, Any]],
    state: Mapping[str, Any] | None = None,
    affect: Mapping[str, Any] | None = None,
    current_activity: Mapping[str, Any] | None = None,
    environment: Mapping[str, Any] | None = None,
    local_time: datetime | None = None,
    prefers_reduced_motion: bool = False,
) -> dict[str, Any]:
    """Resolve replayable visual state without gating or mutating text chat."""

    payload = config if isinstance(config, Mapping) else {}
    life_state = state if isinstance(state, Mapping) else {}
    affect_state = affect if isinstance(affect, Mapping) else {}
    environment_state = environment if isinstance(environment, Mapping) else {}
    resolved_time = _parse_datetime(local_time)
    provider_id = str(payload.get("providerId") or "").strip()[:160]
    requested_mode = str(payload.get("mode") or "portrait").strip().lower()[:40]
    requested_asset_ref = str(payload.get("assetRef") or "").strip()[:400]
    licensed = _licensed_assets(authorized_assets)
    expression_id, motion_preset, expression_source = _expression_state(
        activity=current_activity,
        affect=affect_state,
        energy=_bounded_int(life_state.get("energy"), 70, 0, 100),
    )
    scene_key, weather_fact_id, stale_weather = _scene_key(
        life_state,
        environment_state,
        local_time=resolved_time,
    )
    source_refs: list[dict[str, str]] = []
    if expression_source == "activity" and isinstance(current_activity, Mapping):
        activity_id = str(current_activity.get("activityId") or "").strip()[:200]
        if activity_id:
            source_refs.append({"kind": "activity", "ref": activity_id})
    elif expression_source == "affect":
        for episode_id in list(affect_state.get("activeEpisodeIds") or [])[:8]:
            normalized = str(episode_id or "").strip()[:200]
            if normalized:
                source_refs.append({"kind": "affect_episode", "ref": normalized})
    location_source = life_state.get("locationSource")
    if isinstance(location_source, Mapping):
        location_ref = str(location_source.get("sourceRef") or "").strip()[:300]
        if location_ref:
            source_refs.append({"kind": "location", "ref": location_ref})
    elif isinstance(life_state.get("currentGeo"), Mapping):
        geo_ref = str(
            (life_state.get("currentGeo") or {}).get("locationId") or ""
        ).strip()[:160]
        if geo_ref:
            source_refs.append({"kind": "location", "ref": geo_ref})
    if weather_fact_id:
        source_refs.append({"kind": "environment", "ref": weather_fact_id})

    asset_refs: dict[str, str] = {}
    expression_asset = _matching_asset(
        licensed,
        kind="expression",
        state_key=expression_id,
    )
    background_asset = _matching_asset(
        licensed,
        kind="background",
        state_key=scene_key,
    )
    if expression_asset is not None:
        asset_refs["expression"] = str(expression_asset["assetRef"])
    if background_asset is not None:
        asset_refs["background"] = str(background_asset["assetRef"])

    active_mode = "portrait"
    primary_asset: Mapping[str, str] | None = None
    fallback_reasons: list[str] = []
    enabled = bool(payload.get("enabled"))
    if not enabled:
        fallback_reasons.append("disabled")
    elif requested_mode not in _MODES:
        fallback_reasons.append("mode_not_supported")
    elif requested_mode != "portrait":
        if not provider_id or not bool(
            (provider_health.get(provider_id) or {}).get("available")
        ):
            fallback_reasons.append("provider_unavailable")
        else:
            primary_asset = _primary_asset(licensed, requested_asset_ref)
            if primary_asset is None:
                fallback_reasons.append("asset_not_authorized")
            else:
                active_mode = requested_mode
    elif requested_asset_ref:
        primary_asset = _primary_asset(licensed, requested_asset_ref)
        if primary_asset is None:
            fallback_reasons.append("asset_not_authorized")
    if primary_asset is not None:
        asset_refs = {"primary": str(primary_asset["assetRef"]), **asset_refs}

    selected_assets = {
        key: item
        for key, item in (
            ("primary", primary_asset),
            ("expression", expression_asset),
            ("background", background_asset),
        )
        if item is not None
    }
    asset_receipts = {
        key: {
            "licenseReceipt": str(item["licenseReceipt"]),
            "sourceRef": str(item.get("sourceRef") or ""),
        }
        for key, item in selected_assets.items()
    }

    if prefers_reduced_motion:
        motion_preset = "still"
        blink_profile = {"enabled": False, "minIntervalMs": 0, "maxIntervalMs": 0}
        fallback_reasons.insert(0, "reduced_motion")
    else:
        blink_profile = {
            "enabled": True,
            "minIntervalMs": 2800 if expression_id != "tired" else 4200,
            "maxIntervalMs": 6200 if expression_id != "tired" else 7600,
        }
    if stale_weather:
        fallback_reasons.append("stale_source")

    result = {
        "schemaVersion": 1,
        "assetManifestVersion": 1,
        "enabled": enabled,
        "requestedMode": requested_mode,
        "activeMode": active_mode,
        "providerId": provider_id,
        "assetRef": requested_asset_ref,
        "expressionId": expression_id,
        "motionPreset": motion_preset,
        "blinkProfile": blink_profile,
        "sceneKey": scene_key,
        "assetRefs": asset_refs,
        "assetReceipts": asset_receipts,
        "sourceRefs": source_refs,
        "validUntil": _next_refresh(resolved_time),
        "fallbackReason": fallback_reasons[0] if fallback_reasons else "",
        "fallbackReasons": list(dict.fromkeys(fallback_reasons)),
        "textChatUnaffected": True,
    }
    if primary_asset is not None:
        result["assetLicenseReceipt"] = str(primary_asset["licenseReceipt"])
    return result


__all__ = ["resolve_embodiment"]
