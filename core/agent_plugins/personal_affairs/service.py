"""Agent-scoped personal affairs domain: todos, schedules and goals.

One append-only JSONL ledger per Agent under plugins/personal-affairs. The
personal assistant owns its user's affairs with the same store discipline as
the virtual-human-life plugin: atomic writes, bounded history, no LLM inside
this module. Reminders and proactive delivery are a later layer and are not
modeled here — this module only keeps an honest, reviewable ledger.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.agent_plugins.virtual_human_life.storage import VirtualHumanLifeStore

AFFAIRS_SCHEMA_VERSION = 1
AFFAIR_KINDS = ("todo", "schedule", "goal")
AFFAIR_STATUSES = ("open", "done", "cancelled")
AFFAIR_LEDGER_LIMIT = 2048

_ISO_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$"
)


class PersonalAffairsError(ValueError):
    """Raised when an affairs payload is outside the closed contract."""


class PersonalAffairsNotFoundError(PersonalAffairsError):
    """Raised when the referenced affair item does not exist."""


def _iso(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).isoformat()


def _parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00").replace(" ", "T", 1))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_due_at(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not _ISO_DATETIME.match(text):
        raise PersonalAffairsError(
            f"dueAt must be an ISO date or datetime, got: {text[:60]}"
        )
    parsed = _parse_datetime(text)
    if parsed is None:
        raise PersonalAffairsError(f"dueAt is not parseable: {text[:60]}")
    return _iso(parsed)


def _normalize_kind(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in AFFAIR_KINDS:
        raise PersonalAffairsError(
            f"Unsupported personal affair kind: {value}; expected one of {AFFAIR_KINDS}"
        )
    return normalized


def _normalize_status(value: object, *, default: str = "open") -> str:
    normalized = str(value or "").strip().lower() or default
    if normalized not in AFFAIR_STATUSES:
        raise PersonalAffairsError(
            f"Unsupported personal affair status: {value}; expected one of {AFFAIR_STATUSES}"
        )
    return normalized


def _due_state(item: dict[str, Any], *, now: datetime) -> str:
    if str(item.get("status") or "") != "open":
        return "none"
    due = _parse_datetime(item.get("dueAt"))
    if due is None:
        return "none"
    if due < now:
        return "overdue"
    if due.date() == now.date():
        return "today"
    return "upcoming"


def project_affairs(
    rows: list[dict[str, Any]],
    *,
    agent_id: str,
    now: datetime,
    kind: str = "",
    status: str = "",
) -> dict[str, Any]:
    """Deterministic read projection: filters, due state and bounded counts."""
    normalized_kind = str(kind or "").strip().lower()
    normalized_status = str(status or "").strip().lower()
    items: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if normalized_kind and str(item.get("kind") or "") != normalized_kind:
            continue
        if normalized_status and str(item.get("status") or "") != normalized_status:
            continue
        item["dueState"] = _due_state(item, now=now)
        items.append(item)

    def sort_key(item: dict[str, Any]) -> tuple:
        due = _parse_datetime(item.get("dueAt"))
        created = _parse_datetime(item.get("createdAt")) or now
        is_open = str(item.get("status") or "") == "open"
        overdue = item.get("dueState") == "overdue"
        updated = _parse_datetime(item.get("updatedAt")) or now
        return (
            0 if is_open else 1,
            0 if overdue else 1,
            due.timestamp() if due else float("inf"),
            -created.timestamp(),
            -updated.timestamp(),
        )

    items.sort(key=sort_key)
    counts = {
        "open": sum(1 for row in rows if str(row.get("status") or "") == "open"),
        "overdue": sum(
            1
            for row in rows
            if _due_state(row, now=now) == "overdue"
        ),
        "done": sum(1 for row in rows if str(row.get("status") or "") == "done"),
    }
    return {
        "schemaVersion": AFFAIRS_SCHEMA_VERSION,
        "agentId": str(agent_id),
        "items": items,
        "counts": counts,
        "updatedAt": _iso(now),
    }


class PersonalAffairsService:
    def __init__(
        self,
        project_root: Path,
        *,
        agent_loader: Callable[..., dict[str, Any] | None] | None = None,
        plugin_root_resolver: Callable[[str], Path] | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        def affairs_root(agent_id: str) -> Path:
            if plugin_root_resolver is not None:
                base = Path(plugin_root_resolver(agent_id)).resolve()
            else:
                base = Path(project_root).resolve() / "agents" / agent_id / "plugins"
            return base / "personal-affairs"

        self.store = VirtualHumanLifeStore(
            Path(project_root), plugin_root_resolver=affairs_root
        )
        self._agent_loader = agent_loader
        self._now_provider = now_provider or (
            lambda: datetime.now(timezone.utc)
        )

    def _now(self) -> datetime:
        return self._now_provider().astimezone(timezone.utc)

    def _require_agent(self, agent_id: str) -> dict[str, Any]:
        normalized = str(agent_id or "").strip()
        if not normalized:
            raise PersonalAffairsError("agentId is required.")
        if self._agent_loader is None:
            return {"agentId": normalized}
        agent = self._agent_loader(normalized, include_archived=False)
        if not agent:
            from core.web.services.agent_directory_service import AgentUnavailableError

            raise AgentUnavailableError(f"Agent is not available: {normalized}")
        return agent

    def _rows(self, agent_id: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.store.read_jsonl(agent_id, "affairs/items.jsonl")
            if isinstance(row, dict)
        ]

    def _write_rows(self, agent_id: str, rows: list[dict[str, Any]]) -> None:
        self.store.write_jsonl(agent_id, "affairs/items.jsonl", rows[-AFFAIR_LEDGER_LIMIT:])

    def _find(self, rows: list[dict[str, Any]], item_id: str) -> tuple[int, dict[str, Any]]:
        normalized = str(item_id or "").strip()
        for index, row in enumerate(rows):
            if str(row.get("itemId") or "") == normalized:
                return index, dict(row)
        raise PersonalAffairsNotFoundError(f"Personal affair item was not found: {item_id}")

    def add_item(
        self,
        agent_id: str,
        *,
        kind: str,
        title: str,
        note: str = "",
        due_at: object = "",
        source_turn_id: str = "",
    ) -> dict[str, Any]:
        self._require_agent(agent_id)
        normalized_kind = _normalize_kind(kind)
        normalized_title = " ".join(str(title or "").split())
        if not normalized_title or len(normalized_title) > 160:
            raise PersonalAffairsError(
                "A personal affair requires a title of 1-160 characters."
            )
        normalized_note = str(note or "").strip()[:600]
        normalized_due = _normalize_due_at(due_at)
        now = self._now()
        digest = hashlib.sha256(
            f"{agent_id}:{normalized_kind}:{normalized_title}:{now.isoformat()}".encode("utf-8")
        ).hexdigest()[:16]
        item = {
            "schemaVersion": AFFAIRS_SCHEMA_VERSION,
            "itemId": f"affair-{digest}",
            "kind": normalized_kind,
            "title": normalized_title,
            "note": normalized_note,
            "status": "open",
            "dueAt": normalized_due,
            "createdAt": _iso(now),
            "updatedAt": _iso(now),
            "completedAt": "",
            "sourceTurnId": str(source_turn_id or "").strip()[:200],
        }
        rows = self._rows(agent_id)
        rows.append(item)
        self._write_rows(agent_id, rows)
        return deepcopy_item(item)

    def complete_item(self, agent_id: str, *, item_id: str) -> dict[str, Any]:
        return self._transition(
            agent_id,
            item_id=item_id,
            status="done",
            extra={"completedAt": _iso(self._now())},
        )

    def cancel_item(self, agent_id: str, *, item_id: str) -> dict[str, Any]:
        return self._transition(agent_id, item_id=item_id, status="cancelled")

    def reopen_item(self, agent_id: str, *, item_id: str) -> dict[str, Any]:
        return self._transition(
            agent_id,
            item_id=item_id,
            status="open",
            extra={"completedAt": ""},
        )

    def set_due(self, agent_id: str, *, item_id: str, due_at: object) -> dict[str, Any]:
        self._require_agent(agent_id)
        normalized_due = _normalize_due_at(due_at)
        rows = self._rows(agent_id)
        index, item = self._find(rows, item_id)
        item["dueAt"] = normalized_due
        item["updatedAt"] = _iso(self._now())
        rows[index] = item
        self._write_rows(agent_id, rows)
        return deepcopy_item(item)

    def _transition(
        self,
        agent_id: str,
        *,
        item_id: str,
        status: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_agent(agent_id)
        normalized_status = _normalize_status(status)
        rows = self._rows(agent_id)
        index, item = self._find(rows, item_id)
        if str(item.get("status") or "") == normalized_status:
            return deepcopy_item(item)
        item["status"] = normalized_status
        item["updatedAt"] = _iso(self._now())
        for key, value in (extra or {}).items():
            item[key] = value
        rows[index] = item
        self._write_rows(agent_id, rows)
        return deepcopy_item(item)

    def list_items(
        self,
        agent_id: str,
        *,
        kind: str = "",
        status: str = "",
    ) -> dict[str, Any]:
        self._require_agent(agent_id)
        return project_affairs(
            self._rows(agent_id),
            agent_id=str(agent_id).strip(),
            now=self._now(),
            kind=kind,
            status=status,
        )


def deepcopy_item(item: dict[str, Any]) -> dict[str, Any]:
    import copy

    return copy.deepcopy(item)


__all__ = [
    "AFFAIR_KINDS",
    "AFFAIR_STATUSES",
    "PersonalAffairsError",
    "PersonalAffairsNotFoundError",
    "PersonalAffairsService",
    "project_affairs",
]
