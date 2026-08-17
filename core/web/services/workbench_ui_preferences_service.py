"""Instance-local durable Workbench UI preferences (layout, shell chrome).

Stored under external project runtime state so pane widths and shell chrome
survive browser profile wipes and origin/port changes without dirtying a
checkout.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vibelution_storage import resolve_project_runtime_home

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PREFERENCES_PATH = resolve_project_runtime_home(PROJECT_ROOT) / "workbench" / "ui-preferences.json"
SCHEMA_VERSION = 1

_LOCK = threading.RLock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_payload() -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "paneLayouts": {},
        "shell": {},
        "updatedAt": None,
    }


def _write_payload_unlocked(payload: dict[str, Any]) -> None:
    PREFERENCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = PREFERENCES_PATH.with_suffix(".tmp")
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(PREFERENCES_PATH)


def _shell_has_leftover_chat_widths(raw: object) -> bool:
    if not isinstance(raw, dict):
        return False
    shell = raw.get("shell")
    return isinstance(shell, dict) and "chatPanelWidths" in shell


def _coerce_pane_layouts(value: object) -> dict[str, dict[str, int]]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, dict[str, int]] = {}
    for layout_id, panes in value.items():
        key = str(layout_id or "").strip()
        if not key or not isinstance(panes, dict):
            continue
        pane_map: dict[str, int] = {}
        for pane_id, width in panes.items():
            pane_key = str(pane_id or "").strip()
            try:
                numeric = round(float(width))
            except (TypeError, ValueError):
                continue
            if pane_key and numeric > 0:
                pane_map[pane_key] = numeric
        if pane_map:
            out[key] = pane_map
    return out


def _coerce_shell(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    shell: dict[str, Any] = {}
    chat = value.get("chatPanelWidths")
    if isinstance(chat, dict):
        widths: dict[str, int] = {}
        for field in ("leftPanelWidth", "rightPanelWidth"):
            raw = chat.get(field)
            try:
                numeric = round(float(raw))
            except (TypeError, ValueError):
                continue
            if numeric > 0:
                widths[field] = numeric
        if widths:
            shell["chatPanelWidths"] = widths
    top_bar = str(value.get("topBarMode") or "").strip().lower()
    if top_bar in {"full", "hidden"}:
        shell["topBarMode"] = top_bar
    for flag in ("leftRailCollapsed", "rightPaneCollapsed"):
        if flag in value:
            shell[flag] = bool(value.get(flag))
    return shell


def _migrate_legacy_chat_panel_widths(payload: dict[str, Any]) -> dict[str, Any]:
    """One-shot: leftover shell.chatPanelWidths → paneLayouts.chat; then drop the legacy field."""

    layouts = dict(payload.get("paneLayouts") or {})
    shell = dict(payload.get("shell") or {})
    leftover = shell.pop("chatPanelWidths", None)
    if "chat" not in layouts and isinstance(leftover, dict):
        migrated: dict[str, int] = {}
        for source, dest in (("leftPanelWidth", "left"), ("rightPanelWidth", "right")):
            raw = leftover.get(source)
            try:
                numeric = round(float(raw))
            except (TypeError, ValueError):
                continue
            if numeric > 0:
                migrated[dest] = numeric
        if migrated:
            layouts["chat"] = migrated
    payload["paneLayouts"] = layouts
    payload["shell"] = shell
    return payload


def _normalize_payload(raw: object) -> dict[str, Any]:
    base = _empty_payload()
    if not isinstance(raw, dict):
        return base
    base["paneLayouts"] = _coerce_pane_layouts(raw.get("paneLayouts"))
    base["shell"] = _coerce_shell(raw.get("shell"))
    updated = raw.get("updatedAt")
    if isinstance(updated, str) and updated.strip():
        base["updatedAt"] = updated.strip()
    return _migrate_legacy_chat_panel_widths(base)


def load_workbench_ui_preferences() -> dict[str, Any]:
    with _LOCK:
        if not PREFERENCES_PATH.is_file():
            return _empty_payload()
        try:
            payload = json.loads(PREFERENCES_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _empty_payload()
        normalized = _normalize_payload(payload)
        if _shell_has_leftover_chat_widths(payload):
            normalized["schemaVersion"] = SCHEMA_VERSION
            normalized["updatedAt"] = _utc_now()
            _write_payload_unlocked(normalized)
        return normalized


def save_workbench_ui_preferences(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Merge-write UI preferences. Partial updates keep existing keys."""

    with _LOCK:
        current = load_workbench_ui_preferences()
        incoming = payload if isinstance(payload, dict) else {}

        if "paneLayouts" in incoming:
            current["paneLayouts"] = _coerce_pane_layouts(incoming.get("paneLayouts"))
        elif isinstance(incoming.get("paneLayout"), dict):
            # Single-layout merge helper: { layoutId, widths }
            layout_id = str(incoming["paneLayout"].get("layoutId") or "").strip()
            widths = incoming["paneLayout"].get("widths")
            if layout_id and isinstance(widths, dict):
                layouts = dict(current.get("paneLayouts") or {})
                coerced = _coerce_pane_layouts({layout_id: widths}).get(layout_id)
                if coerced:
                    layouts[layout_id] = {**(layouts.get(layout_id) or {}), **coerced}
                    current["paneLayouts"] = layouts

        if "shell" in incoming and isinstance(incoming.get("shell"), dict):
            incoming_shell = _coerce_shell(incoming.get("shell"))
            leftover_chat = incoming_shell.pop("chatPanelWidths", None)
            layouts = dict(current.get("paneLayouts") or {})
            if leftover_chat and "chat" not in layouts:
                migrated: dict[str, int] = {}
                for source, dest in (("leftPanelWidth", "left"), ("rightPanelWidth", "right")):
                    raw = leftover_chat.get(source)
                    try:
                        numeric = round(float(raw))
                    except (TypeError, ValueError):
                        continue
                    if numeric > 0:
                        migrated[dest] = numeric
                if migrated:
                    layouts["chat"] = migrated
                    current["paneLayouts"] = layouts
            shell = dict(current.get("shell") or {})
            shell.pop("chatPanelWidths", None)
            shell.update(incoming_shell)
            current["shell"] = shell

        current["schemaVersion"] = SCHEMA_VERSION
        current["updatedAt"] = _utc_now()
        _write_payload_unlocked(current)
        return current


def preferences_path() -> Path:
    return PREFERENCES_PATH
