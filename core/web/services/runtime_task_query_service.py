"""Read-only query projection over the unified runtime task registry.

The registry (``runtime_task_registry``) is the lifecycle ledger for child
sessions, CLI Agent terminal tasks and research project Agent tasks. It owns
mutable snapshots but has no HTTP surface. This service is the single read
side for the /aux (辅助对话中心) page:

- ``list_tasks``: one projection shaped for a list/detail UI — currently
  running tasks up front, finished tasks behind a keyset cursor.
- ``get_task``: one task plus the best timeline the snapshot can offer.
- ``stop_task``: the only verb, a thin pass-through to
  ``RuntimeTaskStore.request_stop`` so the route layer stays a DTO mapper.

Reuse decision: the registry already persists snapshots, stamps fencing and
normalizes statuses; re-implementing any of that here would create a second
writer/ledger. This module therefore imports the registry read-only and adds
only projection glue (cards, filters, pagination cursor, revision
fingerprint). It never writes snapshots itself — the stop verb delegates to
the registry's own ``request_stop``.

Revision: the registry has no monotonic version, so the revision is a content
fingerprint (sha256 over every task's ``taskId|status|updatedAt``). It is
guaranteed to change whenever any visible list content changes, and stable
otherwise, which is the /aux page's change-detection signal.

Stop semantics: ``request_stop`` records the stop *intent* (``stopInitiator``
+ ``stopRequestedAt``); it does not itself cancel an in-flight child-session
turn. Terminal tasks return ``accepted=false`` (idempotent: a settled task is
never re-armed) instead of an error, so retries after a race are safe.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from core.web.services import runtime_task_registry

DEFAULT_ENDED_LIMIT = 50
MAX_ENDED_LIMIT = 200
TITLE_FALLBACK_MAX_CHARS = 120
SUMMARY_MAX_CHARS = 300

STATUS_ACTIVE = "active"
STATUS_ENDED = "ended"
STATUS_ALL = "all"
_LIST_STATUS_FILTERS = frozenset({STATUS_ACTIVE, STATUS_ENDED, STATUS_ALL})

_STOP_INITIATORS = runtime_task_registry.STOP_INITIATORS


class RuntimeTaskQueryError(ValueError):
    """Raised for invalid query arguments (maps to HTTP 400/422 upstream)."""


def default_query_service() -> "RuntimeTaskQueryService":
    """Service bound to the shared runtime_tasks store of the active project."""

    return RuntimeTaskQueryService(runtime_task_registry.default_store())


class RuntimeTaskQueryService:
    """Read-only projections plus the stop verb over one registry store."""

    def __init__(self, store: Any) -> None:
        self._store = store

    # -- list -------------------------------------------------------------

    def list_tasks(
        self,
        *,
        status: str = STATUS_ALL,
        kind: str = "",
        parent_session_id: str = "",
        cursor: str = "",
        limit: int = DEFAULT_ENDED_LIMIT,
    ) -> dict[str, Any]:
        """Project the ledger into the /aux list shape.

        ``status`` picks which buckets are populated: ``active`` fills only
        ``running``, ``ended`` only ``ended``, ``all`` both. ``kind`` /
        ``parent_session_id`` filter both buckets. ``cursor``/``limit`` page
        the ended bucket only (keyset cursor over the ended sort key).
        """

        status_filter = str(status or STATUS_ALL).strip().lower()
        if status_filter not in _LIST_STATUS_FILTERS:
            raise RuntimeTaskQueryError(
                f"Unknown status filter: {status_filter or '(empty)'}"
            )
        kind_filter = str(kind or "").strip().lower()
        if kind_filter and kind_filter not in runtime_task_registry.TASK_KINDS:
            raise RuntimeTaskQueryError(f"Unknown task kind: {kind_filter}")
        parent_filter = str(parent_session_id or "").strip()
        try:
            page_limit = int(limit)
        except (TypeError, ValueError) as exc:
            raise RuntimeTaskQueryError("limit must be an integer.") from exc
        page_limit = max(1, min(page_limit, MAX_ENDED_LIMIT))

        states = self._store.iter_task_states()
        running: list[dict[str, Any]] = []
        ended: list[dict[str, Any]] = []
        for state in states:
            if kind_filter and str(state.get("kind") or "") != kind_filter:
                continue
            if parent_filter and str(state.get("parentSessionId") or "") != parent_filter:
                continue
            if runtime_task_registry.is_terminal_status(str(state.get("status") or "")):
                ended.append(state)
            else:
                running.append(state)

        running_cards = [self._card(state) for state in self._sorted_running(running)]
        ended_sorted = self._sorted_ended(ended)
        ended_page, next_cursor = _page_ended(ended_sorted, cursor, page_limit)
        revision = _revision_fingerprint(states)

        payload: dict[str, Any] = {
            "revision": revision,
            "running": running_cards,
            "ended": {
                "items": [self._card(state) for state in ended_page],
                "total": len(ended_sorted),
                "nextCursor": next_cursor,
            },
        }
        if status_filter == STATUS_ACTIVE:
            payload["ended"] = {"items": [], "total": 0, "nextCursor": ""}
        elif status_filter == STATUS_ENDED:
            payload["running"] = []
        return payload

    # -- detail -----------------------------------------------------------

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """One task card plus the snapshot-derived timeline, or None."""

        normalized_id = str(task_id or "").strip()
        if not normalized_id:
            return None
        state = self._store.load_state(normalized_id)
        if not state:
            return None
        card = self._card(state)
        card["stopInitiator"] = str(state.get("stopInitiator") or "") or None
        card["pendingMessageCount"] = len(state.get("pendingMessages") or [])
        card["timeline"] = _timeline(state)
        return card

    # -- stop verb --------------------------------------------------------

    def stop_task(self, task_id: str, initiator: str = "user") -> dict[str, Any] | None:
        """Delegate the stop intent to the registry; None for unknown tasks.

        Returns ``{"accepted": bool, "taskId": str, "status": str}``. An
        already-terminal task yields ``accepted=false`` with its terminal
        status (idempotent no-op), an active task yields ``accepted=true``.
        """

        normalized_initiator = str(initiator or "user").strip().lower() or "user"
        if normalized_initiator not in _STOP_INITIATORS:
            raise RuntimeTaskQueryError(
                f"Unknown stop initiator: {normalized_initiator}"
            )
        normalized_id = str(task_id or "").strip()
        if not normalized_id:
            return None
        current = self._store.load_state(normalized_id)
        if not current:
            return None
        updated = self._store.request_stop(normalized_id, normalized_initiator)
        if updated:
            return {
                "accepted": True,
                "taskId": normalized_id,
                "status": str(updated.get("status") or ""),
                "stopInitiator": normalized_initiator,
            }
        # request_stop returns None both for "already terminal" and (race)
        # "turned terminal between our read and the write": either way the
        # task is settled now, which is the idempotent outcome.
        latest = self._store.load_state(normalized_id) or current
        return {
            "accepted": False,
            "taskId": normalized_id,
            "status": str(latest.get("status") or ""),
            "stopInitiator": str(latest.get("stopInitiator") or "") or None,
        }

    # -- projection -------------------------------------------------------

    def _card(self, state: dict[str, Any]) -> dict[str, Any]:
        kind = str(state.get("kind") or "")
        status = str(state.get("status") or "")
        terminal = runtime_task_registry.is_terminal_status(status)
        card: dict[str, Any] = {
            "taskId": str(state.get("taskId") or ""),
            "kind": kind,
            "status": status,
            "title": _title(state),
            "parentSessionId": str(state.get("parentSessionId") or ""),
            "startedAt": str(state.get("startedAt") or ""),
            "endedAt": _ended_at(state) if terminal else "",
            "summary": _summary(state),
        }
        # Child sessions register with the child session id as taskId, so the
        # child surface id is derivable; other kinds have none.
        if kind == runtime_task_registry.KIND_CHILD_SESSION:
            card["childSessionId"] = str(state.get("taskId") or "")
        output_path = str(state.get("outputPath") or "").strip()
        if output_path:
            card["outputPath"] = output_path
        return card

    # -- ordering ---------------------------------------------------------

    @staticmethod
    def _sorted_running(states: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            states,
            key=lambda s: (
                str(s.get("startedAt") or s.get("createdAt") or ""),
                str(s.get("taskId") or ""),
            ),
            reverse=True,
        )

    @staticmethod
    def _sorted_ended(states: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            states,
            key=lambda s: (_ended_at(s), str(s.get("taskId") or "")),
            reverse=True,
        )


# -- helpers (pure functions, no store access) ----------------------------


def _title(state: dict[str, Any]) -> str:
    label = str(state.get("label") or "").strip()
    if label:
        return label
    output = str(state.get("output") or "").strip()
    for line in output.splitlines():
        line = line.strip()
        if line:
            return line[:TITLE_FALLBACK_MAX_CHARS]
    return ""


def _summary(state: dict[str, Any]) -> str:
    summary = str(state.get("resultSummary") or "").strip()
    if summary:
        return summary
    output = str(state.get("output") or "").strip()
    if len(output) > SUMMARY_MAX_CHARS:
        return output[:SUMMARY_MAX_CHARS]
    return output


def _ended_at(state: dict[str, Any]) -> str:
    return str(state.get("completedAt") or state.get("updatedAt") or "")


def _timeline(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Best-effort timeline from the timestamp fields the snapshot carries.

    The registry keeps no event log, so this is a synthesized view of the
    lifecycle timestamps that exist on every snapshot (plus the optional
    stop/background stamps and the terminal reason).
    """

    entries: list[dict[str, Any]] = []
    simple = (
        ("createdAt", "created"),
        ("startedAt", "started"),
        ("stopRequestedAt", "stop_requested"),
        ("backgroundedAt", "backgrounded"),
        ("completedAt", "completed"),
    )
    for key, event in simple:
        at = str(state.get(key) or "").strip()
        if at:
            entry: dict[str, Any] = {"at": at, "event": event}
            entries.append(entry)
    reason = str(state.get("terminalReason") or "").strip()
    if reason:
        completed_at = str(state.get("completedAt") or "").strip()
        if completed_at:
            for entry in entries:
                if entry["event"] == "completed":
                    entry["detail"] = reason
                    break
    entries.sort(key=lambda e: e["at"])
    return entries


def _revision_fingerprint(states: list[dict[str, Any]]) -> str:
    """Content fingerprint of the whole ledger (changes on any content change)."""

    parts = sorted(
        f"{state.get('taskId') or ''}|{state.get('status') or ''}|{state.get('updatedAt') or ''}"
        for state in states
        if isinstance(state, dict)
    )
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return f"rev-{digest[:16]}"


def _page_ended(
    ended_sorted: list[dict[str, Any]], cursor: str, limit: int
) -> tuple[list[dict[str, Any]], str]:
    """Keyset page over the desc-sorted ended list.

    The cursor encodes ``(endedAt, taskId)`` of the last returned item; the
    next page continues strictly after it, so inserts of newer finished tasks
    never shift items across page boundaries.
    """

    if not ended_sorted:
        return [], ""
    start = 0
    token = str(cursor or "").strip()
    if token:
        key, task_id = _decode_cursor(token)
        # Strictly after the cursor item: it was the previous page's last
        # entry, so including it again would duplicate it across pages.
        start = len(ended_sorted)
        for index, state in enumerate(ended_sorted):
            if (_ended_at(state), str(state.get("taskId") or "")) < (key, task_id):
                start = index
                break
    page = ended_sorted[start : start + limit]
    next_cursor = ""
    if start + limit < len(ended_sorted) and page:
        last = page[-1]
        next_cursor = _encode_cursor(_ended_at(last), str(last.get("taskId") or ""))
    return page, next_cursor


def _encode_cursor(ended_at: str, task_id: str) -> str:
    raw = json.dumps({"e": ended_at, "t": task_id}, ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(token: str) -> tuple[str, str]:
    try:
        padded = token + "=" * (-len(token) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, UnicodeDecodeError):
        raise RuntimeTaskQueryError("Invalid pagination cursor.") from None
    if not isinstance(payload, dict):
        raise RuntimeTaskQueryError("Invalid pagination cursor.")
    return str(payload.get("e") or ""), str(payload.get("t") or "")
