"""Web-layer singleton for the Agent-scoped personal affairs domain."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from core.agent_plugins.personal_affairs.service import (
    PersonalAffairsError,
    PersonalAffairsNotFoundError,
    PersonalAffairsService,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]

_SERVICE: PersonalAffairsService | None = None
_SERVICE_LOCK = threading.Lock()


def _default_agent_loader(agent_id: str, *, include_archived: bool = False) -> dict[str, Any] | None:
    from .agent_directory_service import get_agent

    return get_agent(agent_id, include_archived=include_archived)


def get_personal_affairs_service() -> PersonalAffairsService:
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            _SERVICE = PersonalAffairsService(
                PROJECT_ROOT,
                agent_loader=_default_agent_loader,
                now_provider=None,
            )
        return _SERVICE


AFFAIR_REMINDER_KIND = "affair_reminder"
AFFAIR_REMINDER_LIMIT = 5
AFFAIR_REMINDER_TARGET = "/personal-assistant"
_REMINDER_DUE_STATES = ("overdue", "today")
_REMINDER_TEXT_LIMIT = 80


def collect_affair_reminder_attention(*, limit: int = AFFAIR_REMINDER_LIMIT) -> list[dict[str, str]]:
    """Due/overdue open affairs of the personal assistant as human-attention rows.

    Rows ride the existing dual-channel notifier (assistant-window card or
    system toast) through the overview humanAttention lane; day-scoped ids let
    the web layer dedup within a day and re-surface an item on the next day
    while it stays open. Any failure resolves to no rows — reminders must not
    break the overview.
    """
    from datetime import datetime, timezone

    from . import personal_assistant_service

    try:
        agent = personal_assistant_service.profile_agent()
    except Exception:  # noqa: BLE001 - reminder source must stay read-only safe
        return []
    agent_id = str((agent or {}).get("agentId") or "").strip()
    if not agent_id:
        return []
    try:
        projection = get_personal_affairs_service().list_items(agent_id)
    except Exception:  # noqa: BLE001 - a missing ledger is not an overview error
        return []
    due_items = [
        item
        for item in projection.get("items") or []
        if str(item.get("status") or "") == "open"
        and str(item.get("dueState") or "") in _REMINDER_DUE_STATES
    ]
    due_items.sort(
        key=lambda item: (
            0 if str(item.get("dueState") or "") == "overdue" else 1,
            str(item.get("dueAt") or ""),
        )
    )
    day_key = datetime.now(timezone.utc).strftime("%Y%m%d")
    rows: list[dict[str, str]] = []
    for item in due_items[: max(0, int(limit))]:
        title = " ".join(str(item.get("title") or "").split())[:_REMINDER_TEXT_LIMIT] or "事务"
        due_text = str(item.get("dueAt") or "").strip()
        rows.append(
            {
                "id": f"affair-reminder:{item.get('itemId')}:{day_key}",
                "kind": AFFAIR_REMINDER_KIND,
                "severity": "high" if str(item.get("dueState") or "") == "overdue" else "medium",
                "title": f"事务提醒：{title}",
                "body": (f"截止 {due_text}" if due_text else "已到期")[:_REMINDER_TEXT_LIMIT],
                "targetUrl": AFFAIR_REMINDER_TARGET,
            }
        )
    return rows


__all__ = [
    "AFFAIR_REMINDER_KIND",
    "PersonalAffairsError",
    "PersonalAffairsNotFoundError",
    "collect_affair_reminder_attention",
    "get_personal_affairs_service",
]
