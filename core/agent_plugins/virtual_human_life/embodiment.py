"""Optional desktop embodiment resolution with a portrait-safe fallback."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_MODES = {"portrait", "voice", "live2d", "three_d"}


def resolve_embodiment(
    config: Mapping[str, Any] | None,
    *,
    authorized_assets: Sequence[Mapping[str, Any]],
    provider_health: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Resolve optional presentation; text chat is never gated by the provider."""

    payload = config if isinstance(config, Mapping) else {}
    provider_id = str(payload.get("providerId") or "").strip()[:160]
    requested_mode = str(payload.get("mode") or "portrait").strip().lower()[:40]
    asset_ref = str(payload.get("assetRef") or "").strip()[:400]
    base = {
        "enabled": bool(payload.get("enabled")),
        "requestedMode": requested_mode,
        "activeMode": "portrait",
        "providerId": provider_id,
        "assetRef": asset_ref,
        "fallbackReason": "",
        "textChatUnaffected": True,
    }
    if not base["enabled"] or requested_mode == "portrait":
        base["fallbackReason"] = "disabled" if not base["enabled"] else ""
        return base
    if requested_mode not in _MODES:
        base["fallbackReason"] = "mode_not_supported"
        return base
    if not provider_id or not bool((provider_health.get(provider_id) or {}).get("available")):
        base["fallbackReason"] = "provider_unavailable"
        return base
    asset = next(
        (
            item
            for item in authorized_assets
            if str(item.get("assetRef") or "").strip() == asset_ref
            and str(item.get("licenseReceipt") or "").strip()
        ),
        None,
    )
    if asset is None:
        base["fallbackReason"] = "asset_not_authorized"
        return base
    base["activeMode"] = requested_mode
    base["assetLicenseReceipt"] = str(asset.get("licenseReceipt") or "").strip()[:240]
    return base


__all__ = ["resolve_embodiment"]
