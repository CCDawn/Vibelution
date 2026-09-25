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
BRANCH_GENERATION_KEY = "branchGeneration"
MAX_QUEUED_TURNS_PER_SESSION = 20
MAX_RUNTIME_NOTICES_PER_SESSION = 20
DRAINED_TURN_MESSAGE_SOURCE = "queued_turn"
KIND_USER = "user"
KIND_TASK_NOTIFICATION = "task_notification"
KIND_SUBAGENT_MESSAGE = "subagent_message"
RUNTIME_NOTICE_KINDS = frozenset({KIND_TASK_NOTIFICATION, KIND_SUBAGENT_MESSAGE})

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


def _row_kind(item: dict[str, Any]) -> str:
    kind = str(item.get("kind") or KIND_USER).strip() or KIND_USER
    if kind in RUNTIME_NOTICE_KINDS or kind == KIND_USER:
        return kind
    return KIND_USER


def _row_generation(item: dict[str, Any]) -> int | None:
    if "branchGeneration" not in item or item.get("branchGeneration") in (None, ""):
        return None
    try:
        return max(0, int(item.get("branchGeneration")))
    except (TypeError, ValueError):
        return None


def branch_generation_from_conversation(conversation: dict[str, Any] | None) -> int:
    """Current rewind generation stored on the conversation, or 0."""

    if not isinstance(conversation, dict):
        return 0
    try:
        return max(0, int(conversation.get(BRANCH_GENERATION_KEY) or 0))
    except (TypeError, ValueError):
        return 0


def _notice_is_stale(row: dict[str, Any], current_generation: int) -> bool:
    if _row_kind(row) not in RUNTIME_NOTICE_KINDS:
        return False
    generation = _row_generation(row)
    return generation is not None and generation != current_generation


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
        row["kind"] = _row_kind(item)
        row["status"] = str(item.get("status") or "queued").strip() or "queued"
        row["content"] = str(item.get("content") or "")
        row["attachments"] = _normalize_queued_attachments(item.get("attachments"))
        row["references"] = _normalize_queued_references(item.get("references"))
        generation = _row_generation(item)
        if generation is None:
            row.pop("branchGeneration", None)
        else:
            row["branchGeneration"] = generation
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
        user_count = sum(1 for row in rows if _row_kind(row) == KIND_USER)
        if user_count >= MAX_QUEUED_TURNS_PER_SESSION:
            raise s.SessionValidationError(
                s.text_for(
                    lang,
                    zh=f"排队消息最多 {MAX_QUEUED_TURNS_PER_SESSION} 条，请等前面的消息发出后再添加。",
                    en=f"At most {MAX_QUEUED_TURNS_PER_SESSION} messages can wait in the queue; wait for the earlier ones to send.",
                )
            )
        row = {
            "id": _new_queued_turn_id(),
            "kind": KIND_USER,
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
    status: str | None = None,
    lang: str = "",
) -> list[dict[str, Any]]:
    """Edit one queued turn (text, queue position, and/or pause state) without starting it.

    ``status`` toggles one row between "queued" and "paused". Pausing requires a
    "queued" row (a "blocked" row must go through the edit-retry path, and a
    "starting" row is being sent). Resuming is only valid for a "paused" row and
    re-queues it at the tail, so a resumed message cannot jump ahead of items
    that were enqueued or steered while it was held.
    """

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
        if _row_kind(row) != KIND_USER:
            raise s.SessionValidationError(
                s.text_for(
                    lang,
                    zh="这条是系统回传，不能编辑或暂停；可以撤回。",
                    en="This queued item is a system return and cannot be edited or paused; you can withdraw it.",
                )
            )
        if row["status"] == "starting":
            # claim→submit 窗口内 submit 消费的是 claim 时的快照，此时编辑会被
            # 静默丢弃（用户以为改成功了）；明确拒绝。crash 遗留的 stale
            # starting 行由 _reset_stale_starting_rows 恢复为可编辑。
            raise s.SessionValidationError(
                s.text_for(
                    lang,
                    zh="该排队消息正在发送，暂不能编辑；请等它发出后再发修改版。",
                    en="That queued message is being sent and cannot be edited; wait for it to go out, then send a corrected version.",
                )
            )
        requested_status = str(status or "").strip().lower() or None
        if requested_status is not None and requested_status not in ("queued", "paused"):
            raise s.SessionValidationError(
                s.text_for(
                    lang,
                    zh="排队消息只能暂停或恢复。",
                    en="A queued message can only be paused or resumed.",
                )
            )
        current_status = str(row.get("status") or "queued")
        if requested_status == "paused" and current_status != "queued":
            # A "blocked" row must go through the edit-retry path; a "starting"
            # row was already rejected above.
            raise s.SessionValidationError(
                s.text_for(
                    lang,
                    zh="发送失败的排队消息不能暂停；编辑后会自动重试。",
                    en="A failed queued message cannot be paused; edit it to retry.",
                )
            )
        if requested_status == "queued" and current_status != "paused":
            raise s.SessionValidationError(
                s.text_for(
                    lang,
                    zh="该排队消息没有暂停，无需恢复。",
                    en="That queued message is not paused.",
                )
            )
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
        if requested_status == "paused":
            row["status"] = "paused"
        elif requested_status == "queued":
            row["status"] = "queued"
        elif current_status != "paused":
            # Editing a blocked turn is an explicit retry: it becomes drainable
            # again. Editing a paused turn keeps it paused.
            row["status"] = "queued"
        row["lastError"] = ""
        row["updatedAt"] = s._now_timestamp()
        rows[index] = row
        if requested_status == "queued":
            # Resume re-queues at the tail; an explicit position never rides
            # along with a status flip.
            if index != len(rows) - 1:
                rows.pop(index)
                rows.append(row)
        elif position is not None:
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


def session_branch_generation(session_id: str) -> int:
    """Read the session's current rewind generation. Missing sessions are 0."""

    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return 0
    conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized_session_id)
    return branch_generation_from_conversation(conversation)


def advance_session_branch_generation(session_id: str) -> int:
    """Move the session to the next rewind generation and drop stale notices.

    User-authored queued turns stay. Background-task and child-session notices
    stamped with an older generation are removed, including ones that arrive
    after the rewind.
    """

    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return 0
    generation = 0
    with s._CHAT_STATE_LOCK:
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized_session_id)
        if conversation is None:
            return 0
        generation = branch_generation_from_conversation(conversation) + 1
        conversation[BRANCH_GENERATION_KEY] = generation
        rows = [
            row
            for row in session_queued_turn_rows(conversation)
            if not _notice_is_stale(row, generation)
        ]
        _write_queued_turn_rows(s, normalized_session_id, conversation, rows)
    s._publish_session_detail_snapshot(normalized_session_id)
    return generation


def enqueue_session_runtime_notice(
    session_id: str,
    *,
    kind: str,
    content: str,
    source_id: str,
    branch_generation: int | None = None,
    task_id: str = "",
    tool_name: str = "",
    child_session_id: str = "",
    lang: str = "",
) -> dict[str, Any]:
    """Append one background or child-session notice to the session queue.

    ``branch_generation`` is the generation captured when the work started.
    A mismatch with the session's current generation drops the notice instead
    of queueing it. The same ``source_id`` is idempotent.
    """

    s = _service()
    lang = str(lang or "").strip() or s.get_web_language()
    normalized_session_id = str(session_id or "").strip()
    normalized_kind = str(kind or "").strip()
    normalized_source_id = str(source_id or "").strip()
    text = str(content or "").strip()
    if normalized_kind not in RUNTIME_NOTICE_KINDS:
        raise s.SessionValidationError(
            s.text_for(lang, zh="未知的系统回传类型。", en="Unknown system return kind.")
        )
    if not normalized_session_id:
        raise s.SessionNotFoundError(
            s.text_for(lang, zh="未找到当前会话。", en="Session not found.")
        )
    if not normalized_source_id or not text:
        raise s.SessionValidationError(
            s.text_for(lang, zh="系统回传缺少内容或来源。", en="A system return needs text and a source id.")
        )
    stamped_generation: int | None
    if branch_generation is None:
        stamped_generation = None
    else:
        try:
            stamped_generation = max(0, int(branch_generation))
        except (TypeError, ValueError):
            stamped_generation = None
    with s._CHAT_STATE_LOCK:
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized_session_id)
        if conversation is None:
            raise s.SessionNotFoundError(
                s.text_for(lang, zh="未找到当前会话。", en="Session not found.")
            )
        s._ensure_session_mutable(normalized_session_id, conversation=conversation)
        current_generation = branch_generation_from_conversation(conversation)
        if stamped_generation is not None and stamped_generation != current_generation:
            return {
                "id": "",
                "kind": normalized_kind,
                "status": "dropped",
                "dropped": "stale_branch",
                "sourceId": normalized_source_id,
                "branchGeneration": current_generation,
            }
        rows = session_queued_turn_rows(conversation)
        for row in rows:
            if str(row.get("sourceId") or "").strip() == normalized_source_id:
                return row
        notice_count = sum(1 for row in rows if _row_kind(row) in RUNTIME_NOTICE_KINDS)
        if notice_count >= MAX_RUNTIME_NOTICES_PER_SESSION:
            return {
                "id": "",
                "kind": normalized_kind,
                "status": "dropped",
                "dropped": "queue_full",
                "sourceId": normalized_source_id,
                "branchGeneration": current_generation,
            }
        row = {
            "id": _new_queued_turn_id(),
            "kind": normalized_kind,
            "sourceId": normalized_source_id,
            "content": text,
            "attachments": [],
            "references": [],
            "status": "queued",
            "branchGeneration": current_generation if stamped_generation is None else stamped_generation,
            "taskId": str(task_id or "").strip(),
            "toolName": str(tool_name or "").strip(),
            "childSessionId": str(child_session_id or "").strip(),
            "createdAt": s._now_timestamp(),
            "updatedAt": s._now_timestamp(),
        }
        _write_queued_turn_rows(s, normalized_session_id, conversation, [*rows, row])
    s._publish_session_detail_snapshot(normalized_session_id)
    s._schedule_session_queued_turn_drain(normalized_session_id)
    row["position"] = len(rows) + 1
    return row


def notify_parent_session_of_child_return(session_id: str, *, turn_id: str) -> dict[str, Any] | None:
    """Queue a child session's finished turn onto its parent, once per turn."""

    s = _service()
    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_session_id or not normalized_turn_id:
        return None
    conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized_session_id)
    if not isinstance(conversation, dict):
        return None
    if str(conversation.get("session_kind") or conversation.get("sessionKind") or "").strip() != "child":
        return None
    parent_id = str(
        conversation.get("parent_session_id") or conversation.get("parentSessionId") or ""
    ).strip()
    if not parent_id or parent_id == normalized_session_id:
        return None
    title = str(conversation.get("task_title") or conversation.get("title") or "子对话").strip() or "子对话"
    summary = ""
    try:
        messages = s._session_ledger_visible_messages(normalized_session_id)
    except (OSError, ValueError, TypeError, RuntimeError):
        messages = []
    for item in reversed(list(messages or [])):
        if not isinstance(item, dict):
            continue
        if str(item.get("role") or "").strip().lower() != "assistant":
            continue
        summary = s.trim_lines(item.get("content") or "", max_lines=12)
        if summary:
            break
    lines = [f"子对话已返回：{title}"]
    if summary:
        lines.append(summary)
    lines.append("请吸收这个结果后再决定要不要继续。不要重复启动同一个子对话。")
    origin = conversation.get("originBranchGeneration")
    if origin in (None, ""):
        origin_generation = None
    else:
        try:
            origin_generation = max(0, int(origin))
        except (TypeError, ValueError):
            origin_generation = None
    try:
        return enqueue_session_runtime_notice(
            parent_id,
            kind=KIND_SUBAGENT_MESSAGE,
            content="\n".join(lines),
            source_id=f"child-return:{normalized_session_id}:{normalized_turn_id}",
            branch_generation=origin_generation,
            child_session_id=normalized_session_id,
        )
    except (s.SessionNotFoundError, s.SessionValidationError):
        return None


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


def _claim_drain_batch(session_id: str) -> list[dict[str, Any]]:
    """Claim the next drainable unit: one user or child return, or a notice batch.

    Contiguous queued ``task_notification`` rows leave together so one model
    turn absorbs the whole batch. Stale notices are removed before selection.
    """

    s = _service()
    claimed: list[dict[str, Any]] = []
    changed = False
    with s._CHAT_STATE_LOCK:
        if s._is_session_running(session_id):
            return []
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, session_id)
        if conversation is None:
            return []
        rows = session_queued_turn_rows(conversation)
        if _reset_stale_starting_rows(s, rows):
            changed = True
        current_generation = branch_generation_from_conversation(conversation)
        kept: list[dict[str, Any]] = []
        for row in rows:
            if row["status"] != "starting" and _notice_is_stale(row, current_generation):
                changed = True
                continue
            kept.append(row)
        rows = kept
        index = next((i for i, row in enumerate(rows) if row["status"] == "queued"), -1)
        if index >= 0:
            end = index + 1
            if _row_kind(rows[index]) == KIND_TASK_NOTIFICATION:
                while (
                    end < len(rows)
                    and rows[end]["status"] == "queued"
                    and _row_kind(rows[end]) == KIND_TASK_NOTIFICATION
                ):
                    end += 1
            claimed = [dict(row) for row in rows[index:end]]
            claimed_at = s._now_timestamp()
            for offset in range(index, end):
                rows[offset] = {**rows[offset], "status": "starting", "updatedAt": claimed_at}
            changed = True
        if changed:
            _write_queued_turn_rows(s, session_id, conversation, rows)
    if changed:
        s._publish_session_detail_snapshot(session_id)
    return claimed


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
        batch = _claim_drain_batch(normalized_session_id)
        if not batch:
            return False
        queued_turn_ids = [str(item.get("id") or "") for item in batch if str(item.get("id") or "").strip()]
        head = batch[0]
        kind = _row_kind(head)
        if kind == KIND_TASK_NOTIFICATION:
            content = "\n\n".join(
                str(item.get("content") or "").strip()
                for item in batch
                if str(item.get("content") or "").strip()
            )
            message_source = KIND_TASK_NOTIFICATION
            message_metadata = {
                "kind": KIND_TASK_NOTIFICATION,
                "sourceIds": [str(item.get("sourceId") or "") for item in batch],
                "taskIds": [str(item.get("taskId") or "") for item in batch if str(item.get("taskId") or "").strip()],
            }
            submit_kwargs = {
                "write_intent": False,
                "message_metadata": message_metadata,
            }
        elif kind == KIND_SUBAGENT_MESSAGE:
            content = str(head.get("content") or "")
            message_source = KIND_SUBAGENT_MESSAGE
            submit_kwargs = {
                "write_intent": False,
                "message_metadata": {
                    "kind": KIND_SUBAGENT_MESSAGE,
                    "sourceId": str(head.get("sourceId") or ""),
                    "childSessionId": str(head.get("childSessionId") or ""),
                },
            }
        else:
            content = str(head.get("content") or "")
            message_source = DRAINED_TURN_MESSAGE_SOURCE
            submit_kwargs = {
                "client_submission_id": str(head.get("clientSubmissionId") or ""),
                "attachment_ids": [
                    str(attachment.get("artifactId") or "")
                    for attachment in list(head.get("attachments") or [])
                    if str(attachment.get("artifactId") or "").strip()
                ],
                "references": [
                    dict(reference)
                    for reference in list(head.get("references") or [])
                    if isinstance(reference, dict)
                ],
                "mental_model_enabled": head.get("mentalModelEnabled"),
                "runtime_status_enabled": head.get("runtimeStatusEnabled"),
                "turn_mode": str(head.get("turnMode") or ""),
                "write_intent": head.get("writeIntent"),
            }
        try:
            s.submit_session_message(
                normalized_session_id,
                content,
                message_source=message_source,
                **submit_kwargs,
            )
        except s.SessionBusyError:
            # Another turn won the race: keep the item queued for the next settle.
            for queued_turn_id in queued_turn_ids:
                _settle_claimed_queued_turn(
                    normalized_session_id,
                    queued_turn_id,
                    error=None,
                    keep_queued=True,
                )
        except Exception as exc:  # noqa: BLE001 - a queued turn must fail visibly
            for queued_turn_id in queued_turn_ids:
                _settle_claimed_queued_turn(
                    normalized_session_id,
                    queued_turn_id,
                    error=exc,
                    keep_queued=False,
                )
        else:
            for queued_turn_id in queued_turn_ids:
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
