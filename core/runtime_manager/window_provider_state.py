"""Compatibility projection for managed workbench window state."""

from __future__ import annotations

from typing import Any, Mapping

WINDOW_PROVIDERS = {"none", "edge_app", "electron"}


def _coerce_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _normalize_provider(value: Any, *, legacy_browser_managed: bool) -> str:
    provider = str(value or "").strip()
    if not provider:
        return "edge_app" if legacy_browser_managed else "none"
    return provider if provider in WINDOW_PROVIDERS else "none"


def window_provider_projection(workbench: Mapping[str, Any]) -> dict[str, Any]:
    legacy_browser_managed = bool(workbench.get("browserManaged", False))
    window_provider = _normalize_provider(workbench.get("windowProvider"), legacy_browser_managed=legacy_browser_managed)
    window_managed = bool(
        workbench.get("windowManaged", legacy_browser_managed if window_provider == "edge_app" else False)
    )
    window_id = _coerce_int(workbench.get("windowId"))
    renderer_process_id = _coerce_int(workbench.get("rendererProcessId") or workbench.get("windowProcessId"))
    window_profile_dir = str(workbench.get("windowProfileDir") or workbench.get("browserProfileDir") or "").strip()
    browser_window_pid = _coerce_int(workbench.get("browserWindowPid"))
    browser_managed = bool(window_provider == "edge_app" and window_managed)
    return {
        "windowProvider": window_provider,
        "windowManaged": window_managed,
        "windowId": window_id,
        "rendererProcessId": renderer_process_id,
        "windowProfileDir": window_profile_dir,
        "browserManaged": browser_managed,
        "browserWindowPid": browser_window_pid,
        "browserProfileDir": window_profile_dir,
    }


def with_window_provider_projection(workbench: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(workbench)
    payload.update(window_provider_projection(payload))
    return payload
