"""Server-side queued user turns for one session (Codex thread/queue parity).

Claim scope: persist, edit, remove, project, and drain user turns that a client
accepted while the session still had an active turn.

Queued turns live in the conversation state so they survive reloads and backend
restarts. They carry resolved attachment metadata (never filesystem ``path``) so
the projection can render thumbnails without re-reading the workspace.

Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from core.web.services.session.timebase import parse_timestamp_utc

QUEUED_TURN_STATE_KEY = "queued_turns"
MAX_QUEUED_TURNS_PER_SESSION = 20
DRAINED_TURN_MESSAGE_SOURCE = "queued_turn"

# A claim normally settles within seconds: the submit either accepts the turn,
# keeps the row queued on a busy race, or fails it into "blocked". Only a
# process crash between claim and settle leaves a row in "starting" forever,
# and selection only takes "queued" rows, so such a row would never drain
# again. Ten minutes is far above any legitimate claim->settle window, so a
# reset at that age cannot race a live claim, while the zombie row is
# recovered on the next drain instead of blocking the queue permanently.
STARTING_CLAIM_STALE_SECONDS = 600

_DRAIN_LOCK = threading.Lock()
_DRAINING_SESSIONS: set[str] = set()


def _service():
    from core.web.services import session_service

    return session_service


def _new_queued_turn_id() -> str:
    return f"queued-{uuid.uuid4().hex[:12]}"


def _normalize_queued_attachments(items: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in list(items or []):
        if not isinstance(item, dict):
            continue
        artifact_id = str(item.get("artifactId") or "").strip()
        if not artifact_id:
            continue
        row = {key: value for key, value in item.items() if key != "path"}
        row["artifactId"] = artifact_id
        rows.append(row)
    return rows


def _normalize_queued_references(items: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(items or []) if isinstance(item, dict)]


def session_queued_turn_rows(conversation: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Normalized queued-turn rows for one conversation, in queue order."""

    if not isinstance(conversation, dict):
        return []
    raw = conversation.get(QUEUED_TURN_STATE_KEY)
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        queued_turn_id = str(item.get("id") or "").strip()
        if not queued_turn_id:
            continue
        row = {key: value for key, value in item.items() if key != "path"}
        row["id"] = queued_turn_id
        row["position"] = index + 1
        row["status"] = str(item.get("status") or "queued").strip() or "queued"
        row["content"] = str(item.get("content") or "")
        row["attachments"] = _normalize_queued_attachments(item.get("attachments"))
        row["references"] = _normalize_queued_references(item.get("references"))
        rows.append(row)
    return rows


def list_session_queued_turns(session_id: str) -> list[dict[str, Any]]:
    """Read-only projection helper: queued turns of one session."""

    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return []
    conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized_session_id)
    return session_queued_turn_rows(conversation)


def _write_queued_turn_rows(
    s: Any,
    session_id: str,
    conversation: dict[str, Any],
    rows: list[dict[str, Any]],
) -> None:
    if rows:
        conversation[QUEUED_TURN_STATE_KEY] = rows
    else:
        conversation.pop(QUEUED_TURN_STATE_KEY, None)
    conversation["updated_at"] = s._now_timestamp()
    s.save_session_chat_state(s.PROJECT_ROOT, session_id, conversation)


def enqueue_session_queued_turn(
    session_id: str,
    *,
    content: str,
    attachments: list[dict[str, Any]],
    references: list[dict[str, Any]],
    mental_model_enabled: bool | None,
    runtime_status_enabled: bool | None,
    turn_mode: str,
    write_intent: bool | None,
    client_submission_id: str,
    lang: str = "",
) -> dict[str, Any]:
    """Append one validated user turn to the session queue (idempotent per submission id)."""

    s = _service()
    lang = str(lang or "").strip() or s.get_web_language()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise s.SessionNotFoundError(
            s.text_for(lang, zh="未找到当前会话。", en="Session not found.")
        )
    normalized_client_submission_id = str(client_submission_id or "").strip()
    with s._CHAT_STATE_LOCK:
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized_session_id)
        if conversation is None:
            raise s.SessionNotFoundError(
                s.text_for(lang, zh="未找到当前会话。", en="Session not found.")
            )
        s._ensure_session_mutable(normalized_session_id, conversation=conversation)
        rows = session_queued_turn_rows(conversation)
        if normalized_client_submission_id:
            for row in rows:
                if str(row.get("clientSubmissionId") or "").strip() == normalized_client_submission_id:
                    return row
        if len(rows) >= MAX_QUEUED_TURNS_PER_SESSION:
            raise s.SessionValidationError(
                s.text_for(
                    lang,
                    zh=f"排队消息最多 {MAX_QUEUED_TURNS_PER_SESSION} 条，请等前面的消息发出后再添加。",
                    en=f"At most {MAX_QUEUED_TURNS_PER_SESSION} messages can wait in the queue; wait for the earlier ones to send.",
                )
            )
        row = {
            "id": _new_queued_turn_id(),
            "clientSubmissionId": normalized_client_submission_id,
            "content": str(content or ""),
            "attachments": _normalize_queued_attachments(attachments),
            "references": _normalize_queued_references(references),
            "mentalModelEnabled": mental_model_enabled,
            "runtimeStatusEnabled": runtime_status_enabled,
            "turnMode": str(turn_mode or ""),
            "writeIntent": write_intent,
            "status": "queued",
            "createdAt": s._now_timestamp(),
            "updatedAt": s._now_timestamp(),
        }
        _write_queued_turn_rows(s, normalized_session_id, conversation, [*rows, row])
    s._publish_session_detail_snapshot(normalized_session_id)
    s._schedule_session_queued_turn_drain(normalized_session_id)
    row["position"] = len(rows) + 1
    return row


def update_session_queued_turn(
    session_id: str,
    queued_turn_id: str,
    *,
    content: str | None = None,
    position: int | None = None,
    lang: str = "",
) -> list[dict[str, Any]]:
    """Edit one queued turn (text and/or queue position) without starting it."""

    s = _service()
    lang = str(lang or "").strip() or s.get_web_language()
    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(queued_turn_id or "").strip()
    if not normalized_session_id or not normalized_turn_id:
        raise s.SessionValidationError(
            s.text_for(lang, zh="请选择要修改的排队消息。", en="Choose a queued message to update.")
        )
    with s._CHAT_STATE_LOCK:
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized_session_id)
        if conversation is None:
            raise s.SessionNotFoundError(
                s.text_for(lang, zh="未找到当前会话。", en="Session not found.")
            )
        s._ensure_session_mutable(normalized_session_id, conversation=conversation)
        rows = session_queued_turn_rows(conversation)
        index = next((i for i, row in enumerate(rows) if row["id"] == normalized_turn_id), -1)
        if index < 0:
            raise s.SessionValidationError(
                s.text_for(lang, zh="该排队消息已不在队列中。", en="That queued message is no longer in the queue.")
            )
        row = rows[index]
        if content is not None:
            next_content = str(content or "").strip()
            if not next_content and not row["attachments"]:
                raise s.SessionValidationError(
                    s.text_for(
                        lang,
                        zh="排队消息不能改成空内容，请保留文字或图片。",
                        en="A queued message cannot become empty; keep text or an image.",
                    )
                )
            row["content"] = str(content or "")
        # Editing a blocked turn is an explicit retry: it becomes drainable again.
        row["status"] = "queued"
        row["lastError"] = ""
        row["updatedAt"] = s._now_timestamp()
        rows[index] = row
        if position is not None:
            target = max(0, min(len(rows) - 1, int(position) - 1))
            if target != index:
                rows.pop(index)
                rows.insert(target, row)
        _write_queued_turn_rows(s, normalized_session_id, conversation, rows)
        normalized_rows = session_queued_turn_rows(conversation)
    s._publish_session_detail_snapshot(normalized_session_id)
    s._schedule_session_queued_turn_drain(normalized_session_id)
    return normalized_rows


def remove_session_queued_turn(
    session_id: str,
    queued_turn_id: str,
    *,
    lang: str = "",
) -> list[dict[str, Any]]:
    """Withdraw one queued turn."""

    s = _service()
    lang = str(lang or "").strip() or s.get_web_language()
    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(queued_turn_id or "").strip()
    if not normalized_session_id or not normalized_turn_id:
        raise s.SessionValidationError(
            s.text_for(lang, zh="请选择要撤回的排队消息。", en="Choose a queued message to withdraw.")
        )
    with s._CHAT_STATE_LOCK:
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized_session_id)
        if conversation is None:
            raise s.SessionNotFoundError(
                s.text_for(lang, zh="未找到当前会话。", en="Session not found.")
            )
        s._ensure_session_mutable(normalized_session_id, conversation=conversation)
        rows = session_queued_turn_rows(conversation)
        remaining = [row for row in rows if row["id"] != normalized_turn_id]
        if len(remaining) == len(rows):
            raise s.SessionValidationError(
                s.text_for(lang, zh="该排队消息已不在队列中。", en="That queued message is no longer in the queue.")
            )
        _write_queued_turn_rows(s, normalized_session_id, conversation, remaining)
        normalized_rows = session_queued_turn_rows(conversation)
    s._publish_session_detail_snapshot(normalized_session_id)
    s._schedule_session_queued_turn_drain(normalized_session_id)
    return normalized_rows


def _reset_stale_starting_rows(s: Any, rows: list[dict[str, Any]]) -> bool:
    """Reset rows stuck in "starting" beyond ``STARTING_CLAIM_STALE_SECONDS``.

    Returns True when at least one row was reset back to "queued" (with a
    refreshed ``updatedAt``). Rows whose ``updatedAt`` is missing or
    unparseable are treated as stale: the claim path always writes a fresh
    timestamp, so an unreadable one cannot belong to a live claim. The caller
    owns locking and persistence; this helper only mutates ``rows``.
    """

    now = datetime.now(timezone.utc)
    changed = False
    for index, row in enumerate(rows):
        if row["status"] != "starting":
            continue
        updated = parse_timestamp_utc(row.get("updatedAt"))
        if updated is not None and (now - updated).total_seconds() < STARTING_CLAIM_STALE_SECONDS:
            continue
        rows[index] = {**row, "status": "queued", "updatedAt": s._now_timestamp()}
        changed = True
    return changed


def _claim_next_queued_turn(session_id: str) -> dict[str, Any] | None:
    """Mark the first drainable queued turn as starting; None when nothing may start.

    The item stays in the queue until its turn is actually accepted, so a failed
    or rejected start never drops a user message.
    """

    s = _service()
    reset_stale = False
    item: dict[str, Any] | None = None
    with s._CHAT_STATE_LOCK:
        if s._is_session_running(session_id):
            return None
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, session_id)
        if conversation is None:
            return None
        rows = session_queued_turn_rows(conversation)
        # Recover rows abandoned in "starting" by a crash between claim and
        # settle before selecting; otherwise they would never drain again.
        reset_stale = _reset_stale_starting_rows(s, rows)
        if reset_stale:
            _write_queued_turn_rows(s, session_id, conversation, rows)
        index = next((i for i, row in enumerate(rows) if row["status"] == "queued"), -1)
        if index >= 0:
            item = rows[index]
            rows[index] = {**item, "status": "starting", "updatedAt": s._now_timestamp()}
            _write_queued_turn_rows(s, session_id, conversation, rows)
    if item is not None or reset_stale:
        s._publish_session_detail_snapshot(session_id)
    return item


def _settle_claimed_queued_turn(
    session_id: str,
    queued_turn_id: str,
    *,
    error: Exception | None,
    keep_queued: bool,
) -> None:
    s = _service()
    changed = False
    with s._CHAT_STATE_LOCK:
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, session_id)
        if conversation is None:
            return
        rows = session_queued_turn_rows(conversation)
        for index, row in enumerate(rows):
            if row["id"] != queued_turn_id:
                continue
            if error is None:
                rows.pop(index)
            else:
                rows[index] = {
                    **row,
                    "status": "queued" if keep_queued else "blocked",
                    "lastError": "" if keep_queued else s.trim_lines(str(error), max_lines=2),
                    "updatedAt": s._now_timestamp(),
                }
            changed = True
            break
        if changed:
            _write_queued_turn_rows(s, session_id, conversation, rows)
    if changed:
        s._publish_session_detail_snapshot(session_id)


def drain_session_queued_turns(session_id: str) -> bool:
    """Start the next queued turn once the session is idle.

    Single-flight per session: settlement can fire this from several cleanup
    paths, and only one of them may turn the queue head into a real turn.
    """

    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return False
    with _DRAIN_LOCK:
        if normalized_session_id in _DRAINING_SESSIONS:
            return False
        _DRAINING_SESSIONS.add(normalized_session_id)
    try:
        item = _claim_next_queued_turn(normalized_session_id)
        if not item:
            return False
        queued_turn_id = str(item.get("id") or "")
        try:
            s.submit_session_message(
                normalized_session_id,
                str(item.get("content") or ""),
                client_submission_id=str(item.get("clientSubmissionId") or ""),
                attachment_ids=[
                    str(attachment.get("artifactId") or "")
                    for attachment in list(item.get("attachments") or [])
                    if str(attachment.get("artifactId") or "").strip()
                ],
                references=[
                    dict(reference)
                    for reference in list(item.get("references") or [])
                    if isinstance(reference, dict)
                ],
                mental_model_enabled=item.get("mentalModelEnabled"),
                runtime_status_enabled=item.get("runtimeStatusEnabled"),
                turn_mode=str(item.get("turnMode") or ""),
                write_intent=item.get("writeIntent"),
                message_source=DRAINED_TURN_MESSAGE_SOURCE,
            )
        except s.SessionBusyError:
            # Another turn won the race: keep the item queued for the next settle.
            _settle_claimed_queued_turn(
                normalized_session_id,
                queued_turn_id,
                error=None,
                keep_queued=True,
            )
        except Exception as exc:  # noqa: BLE001 - a queued turn must fail visibly
            _settle_claimed_queued_turn(
                normalized_session_id,
                queued_turn_id,
                error=exc,
                keep_queued=False,
            )
        else:
            _settle_claimed_queued_turn(
                normalized_session_id,
                queued_turn_id,
                error=None,
                keep_queued=False,
            )
        return True
    finally:
        with _DRAIN_LOCK:
            _DRAINING_SESSIONS.discard(normalized_session_id)


def schedule_session_queued_turn_drain(session_id: str) -> None:
    """Queue a drain on the shared session executor (never blocks settlement)."""

    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return
    try:
        s._SESSION_EXECUTOR.submit(s._drain_session_queued_turns, normalized_session_id)
    except Exception:  # noqa: BLE001 - shutdown or saturated executor: next settle retries
        return
