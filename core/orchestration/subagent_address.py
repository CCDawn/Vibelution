# -*- coding: utf-8 -*-
"""Address one subagent run and continue that same child session.

The child session journal is the transcript. This file only remembers which
child session belongs to an agent id, and the arrival order of messages that
show up while that run is still going. Parent progress is a status event on
the parent session. It does not carry the message body and it does not open
another session.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping


_LOCK = threading.Lock()
_PENDING_LIMIT = 20
_SAFE_TOKEN = re.compile(r"[^A-Za-z0-9._-]+")

NO_ACTIVE_AGENT = "NO_ACTIVE_AGENT"
MISSING_CHILD_SESSION = "MISSING_CHILD_SESSION"
RESUME_FAILED = "RESUME_FAILED"


def address_directory(project_root: Path | str | None = None) -> Path:
    override = str(os.environ.get("VIBELUTION_SUBAGENT_ADDRESS_ROOT") or "").strip()
    if override:
        return Path(override)
    root = Path(project_root) if project_root else _default_project_root()
    from core.chat.turn_journal import turn_journal_workspace_root

    return turn_journal_workspace_root(root) / "subagent-addresses"


def get_subagent_address(agent_id: str, *, project_root: Path | str | None = None) -> dict[str, Any] | None:
    path = _address_path(agent_id, project_root=project_root)
    if path is None or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return dict(payload) if isinstance(payload, dict) else None


def open_subagent_address(
    *,
    agent_id: str,
    task: str = "",
    task_type: str = "",
    status: str = "running",
) -> dict[str, Any]:
    """Register a run once it has actually started. No parent chat session means no record."""

    identity = parent_chat_identity()
    if identity is None:
        return {}
    project_root, parent_session_id, parent_turn_id = identity
    normalized_id = str(agent_id or "").strip()
    if not normalized_id:
        return {}
    child_session_id = _ensure_child_session(
        parent_session_id,
        task=task,
        task_type=task_type,
    )
    record = {
        "agentId": normalized_id,
        "subRunId": normalized_id,
        "parentSessionId": parent_session_id,
        "parentTurnId": parent_turn_id,
        "childSessionId": child_session_id,
        "projectRoot": str(project_root),
        "status": str(status or "running").strip() or "running",
        "previousStatus": "",
        "resumeClaimed": False,
        "pending": [],
        "activeMessages": [],
        "taskType": str(task_type or "").strip(),
        "summary": "",
    }
    _save_record(record)
    note_subagent_progress(
        project_root,
        parent_session_id,
        parent_turn_id,
        agent_id=normalized_id,
        child_session_id=child_session_id,
        status=record["status"],
        delivery="started" if record["status"] == "running" else record["status"],
    )
    return record


def settle_subagent_address(
    agent_id: str,
    *,
    status: str,
    summary: str = "",
    user_text: str = "",
    assistant_text: str = "",
) -> None:
    """Mark the run finished and append the exchange on the same child session."""

    with _LOCK:
        record = get_subagent_address(agent_id)
        if record is None:
            return
        record["status"] = str(status or "").strip() or "completed"
        record["resumeClaimed"] = False
        record["previousStatus"] = ""
        record["activeMessages"] = []
        record["summary"] = str(summary or "").strip()[:500]
        _save_record(record)
    project_root = _record_root(record)
    child_session_id = str(record.get("childSessionId") or "").strip()
    assistant = str(assistant_text or summary or "").strip()
    user = str(user_text or "").strip()
    if project_root is not None and child_session_id and (user or assistant):
        append_child_exchange(
            project_root,
            child_session_id,
            user_text=user,
            assistant_text=assistant,
            status=str(record.get("status") or ""),
        )
    if project_root is not None:
        note_subagent_progress(
            project_root,
            str(record.get("parentSessionId") or ""),
            str(record.get("parentTurnId") or ""),
            agent_id=str(record.get("agentId") or agent_id),
            child_session_id=child_session_id,
            status=str(record.get("status") or ""),
            delivery="finished",
        )


def begin_resume(
    agent_id: str,
    *,
    ready: bool,
    message: str,
    summary: str = "",
) -> dict[str, Any]:
    """Claim a terminal agent, or queue when it is still running.

    ``ready`` is the internal resume path. A direct call without it only
    queues, so a second process cannot start on the same id.
    """

    normalized_id = str(agent_id or "").strip()
    text = str(message or "").strip()
    with _LOCK:
        record = get_subagent_address(normalized_id)
        if record is None:
            return _error(NO_ACTIVE_AGENT, "没有找到这个子代理。", normalized_id)
        child_session_id = str(record.get("childSessionId") or "").strip()
        if not child_session_id:
            return _error(MISSING_CHILD_SESSION, "这个子代理没有可续的会话。", normalized_id)
        status = str(record.get("status") or "").strip()
        if status == "running" or not ready:
            pending = [item for item in list(record.get("pending") or []) if isinstance(item, dict)]
            if text:
                pending.append({"message": text, "summary": str(summary or "").strip()[:240]})
            record["pending"] = pending[-_PENDING_LIMIT:]
            _save_record(record)
            queued = dict(record)
        else:
            pending = [item for item in list(record.get("pending") or []) if isinstance(item, dict)]
            texts = [
                str(item.get("message") or "").strip()
                for item in pending
                if str(item.get("message") or "").strip()
            ]
            if text:
                texts.append(text)
            record["pending"] = []
            record["activeMessages"] = texts
            record["previousStatus"] = status or "completed"
            record["status"] = "running"
            record["resumeClaimed"] = True
            _save_record(record)
            queued = None
            claimed = dict(record)
            claimed_texts = list(texts)
    if queued is not None:
        root = _record_root(queued)
        if root is not None:
            note_subagent_progress(
                root,
                str(queued.get("parentSessionId") or ""),
                str(queued.get("parentTurnId") or ""),
                agent_id=normalized_id,
                child_session_id=str(queued.get("childSessionId") or ""),
                status="running",
                delivery="queued",
            )
        return {
            "status": "ok",
            "delivery": "queued",
            "code": "QUEUED",
            "agentId": normalized_id,
            "subRunId": normalized_id,
            "childSessionId": str(queued.get("childSessionId") or ""),
            "message": "子代理还在跑，这句话已排在同一场会话后面。",
        }
    return {
        "status": "ok",
        "delivery": "resume",
        "agentId": normalized_id,
        "subRunId": normalized_id,
        "childSessionId": str(claimed.get("childSessionId") or ""),
        "parentSessionId": str(claimed.get("parentSessionId") or ""),
        "parentTurnId": str(claimed.get("parentTurnId") or ""),
        "projectRoot": str(claimed.get("projectRoot") or ""),
        "previousStatus": str(claimed.get("previousStatus") or ""),
        "messages": claimed_texts,
    }


def restore_subagent_status(agent_id: str) -> None:
    """Put a claimed resume back if the process never started."""

    with _LOCK:
        record = get_subagent_address(agent_id)
        if record is None or not bool(record.get("resumeClaimed")):
            return
        previous = str(record.get("previousStatus") or "").strip() or "completed"
        pending = [item for item in list(record.get("pending") or []) if isinstance(item, dict)]
        for text in list(record.get("activeMessages") or []):
            cleaned = str(text or "").strip()
            if cleaned:
                pending.append({"message": cleaned, "summary": ""})
        record["pending"] = pending[-_PENDING_LIMIT:]
        record["activeMessages"] = []
        record["status"] = previous
        record["previousStatus"] = ""
        record["resumeClaimed"] = False
        _save_record(record)


def continue_addressed(
    agent_id: str,
    message: str,
    *,
    summary: str = "",
    resume: Callable[[str], Any] | None = None,
) -> Any:
    """Queue onto a running agent, or resume the same child session when it is done."""

    normalized_id = str(agent_id or "").strip()
    record = get_subagent_address(normalized_id)
    if record is None:
        return _error(NO_ACTIVE_AGENT, "没有找到这个子代理。", normalized_id)
    if not str(record.get("childSessionId") or "").strip():
        return _error(MISSING_CHILD_SESSION, "这个子代理没有可续的会话。", normalized_id)
    if str(record.get("status") or "").strip() == "running":
        return begin_resume(normalized_id, ready=False, message=message, summary=summary)
    if not callable(resume):
        return _error(RESUME_FAILED, "这次续聊没有开始。", normalized_id)
    try:
        return resume(str(message or ""))
    except Exception as exc:
        restore_subagent_status(normalized_id)
        return _error(RESUME_FAILED, f"续聊没有开始：{type(exc).__name__}", normalized_id)


def note_subagent_progress(
    project_root: Path | str,
    parent_session_id: str,
    parent_turn_id: str,
    *,
    agent_id: str,
    child_session_id: str = "",
    status: str = "",
    delivery: str = "",
) -> None:
    """Write status onto the parent journal. The message body stays out."""

    session_id = str(parent_session_id or "").strip()
    if not session_id:
        return
    turn_id = str(parent_turn_id or "").strip() or "subagent-progress"
    from core.chat.conversation_ledger import append_conversation_event
    from core.chat.turn_journal import EVENT_SUBAGENT_PROGRESS

    append_conversation_event(
        Path(project_root),
        session_id,
        turn_id,
        EVENT_SUBAGENT_PROGRESS,
        status=str(status or "").strip(),
        payload={
            "agentId": str(agent_id or "").strip(),
            "childSessionId": str(child_session_id or "").strip(),
            "status": str(status or "").strip(),
            "delivery": str(delivery or "").strip(),
        },
        source="subagent_address",
        visible_in_model=False,
        projection_kind="subagent_progress",
        source_kind="subagent_progress",
    )


def append_child_exchange(
    project_root: Path | str,
    child_session_id: str,
    *,
    user_text: str,
    assistant_text: str,
    status: str = "completed",
) -> str:
    """Append one new turn on the existing child session. Does not allocate a session."""

    session_id = str(child_session_id or "").strip()
    if not session_id:
        return ""
    turn_id = f"subagent-{uuid.uuid4().hex[:12]}"
    from core.chat.conversation_ledger import append_conversation_event
    from core.chat.turn_journal import (
        EVENT_ASSISTANT_MESSAGE,
        EVENT_TURN_COMPLETED,
        EVENT_TURN_FAILED,
        EVENT_TURN_STARTED,
        EVENT_USER_MESSAGE,
    )

    root = Path(project_root)
    append_conversation_event(
        root,
        session_id,
        turn_id,
        EVENT_TURN_STARTED,
        status="started",
        payload={"source": "subagent_address"},
        source="subagent_address",
        visible_in_model=False,
        source_kind="subagent_address",
    )
    user = str(user_text or "").strip()
    if user:
        append_conversation_event(
            root,
            session_id,
            turn_id,
            EVENT_USER_MESSAGE,
            status="completed",
            payload={"content": user},
            source="subagent_address",
            visible_in_model=True,
            source_kind="subagent_address",
        )
    assistant = str(assistant_text or "").strip()
    if assistant:
        append_conversation_event(
            root,
            session_id,
            turn_id,
            EVENT_ASSISTANT_MESSAGE,
            status="completed",
            payload={"content": assistant},
            source="subagent_address",
            visible_in_model=True,
            source_kind="subagent_address",
        )
    terminal = EVENT_TURN_COMPLETED if _successful_status(status) else EVENT_TURN_FAILED
    append_conversation_event(
        root,
        session_id,
        turn_id,
        terminal,
        status=str(status or "").strip() or "completed",
        payload={"source": "subagent_address"},
        source="subagent_address",
        visible_in_model=False,
        source_kind="subagent_address",
    )
    return turn_id


def child_history_preamble(project_root: Path | str, child_session_id: str) -> str:
    """Project the child journal into the resume prompt. The journal stays the authority."""

    session_id = str(child_session_id or "").strip()
    if not session_id:
        return ""
    from core.chat.conversation_ledger import load_conversation_events
    from core.chat.turn_journal import model_messages_from_events

    events = load_conversation_events(Path(project_root), session_id)
    lines: list[str] = []
    for message in model_messages_from_events(events)[-8:]:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip()
        if role not in {"user", "assistant"}:
            continue
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"{role}: {content[:800]}")
    if not lines:
        return ""
    return "以下是这场子会话里已经发生过的内容。接着做，不要另开一场。\n" + "\n".join(lines)


def parent_chat_identity() -> tuple[Path, str, str] | None:
    try:
        from core.web.services.agent_directory_service import current_agent_runtime

        runtime = current_agent_runtime() or {}
    except Exception:
        return None
    if not isinstance(runtime, Mapping):
        return None
    session_id = str(runtime.get("sessionId") or "").strip()
    turn_id = str(runtime.get("turnId") or "").strip()
    root = str(runtime.get("projectRoot") or runtime.get("workspaceRoot") or "").strip()
    if not root:
        try:
            from core.runtime_manager.constants import PROJECT_ROOT

            root = str(PROJECT_ROOT or "").strip()
        except Exception:
            root = ""
    if not session_id or not root:
        return None
    return Path(root), session_id, turn_id


def _ensure_child_session(parent_session_id: str, *, task: str, task_type: str) -> str:
    request = str(task or "").strip() or "子代理任务"
    title = request.replace("\n", " ")[:80] or "子代理"
    try:
        from core.web.services.session.agent_sessions import create_child_session

        created = create_child_session(
            parent_session_id,
            user_request=request,
            task_title=title,
            split_reason=str(task_type or "subagent").strip() or "subagent",
            auto_start=False,
            switch_to_child=False,
            source="subagent_address",
            announce_on_parent=False,
            track_active_child=False,
        )
    except Exception:
        return ""
    if not isinstance(created, Mapping):
        return ""
    return str(created.get("childSessionId") or "").strip()


def _save_record(record: Mapping[str, Any]) -> None:
    agent_id = str(record.get("agentId") or "").strip()
    path = _address_path(agent_id, project_root=record.get("projectRoot"))
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(dict(record), ensure_ascii=False, indent=2)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def _address_path(agent_id: str, *, project_root: Path | str | None = None) -> Path | None:
    token = _safe_agent_token(agent_id)
    if not token:
        return None
    return address_directory(project_root) / f"{token}.json"


def _safe_agent_token(agent_id: str) -> str:
    cleaned = _SAFE_TOKEN.sub("-", str(agent_id or "").strip()).strip(".-")
    return cleaned[:120]


def _record_root(record: Mapping[str, Any]) -> Path | None:
    raw = str(record.get("projectRoot") or "").strip()
    if raw:
        return Path(raw)
    return None


def _default_project_root() -> Path:
    try:
        from core.runtime_manager.constants import PROJECT_ROOT

        if PROJECT_ROOT:
            return Path(str(PROJECT_ROOT))
    except Exception:
        pass
    return Path.cwd()


def _successful_status(status: str) -> bool:
    return str(status or "").strip().lower() in {"completed", "success", "ok", "partial", "started"}


def _error(code: str, message: str, agent_id: str) -> dict[str, Any]:
    return {
        "status": "error",
        "code": code,
        "message": message,
        "agentId": str(agent_id or "").strip(),
        "subRunId": str(agent_id or "").strip(),
    }


__all__ = [
    "MISSING_CHILD_SESSION",
    "NO_ACTIVE_AGENT",
    "RESUME_FAILED",
    "address_directory",
    "append_child_exchange",
    "begin_resume",
    "child_history_preamble",
    "continue_addressed",
    "get_subagent_address",
    "note_subagent_progress",
    "open_subagent_address",
    "parent_chat_identity",
    "restore_subagent_status",
    "settle_subagent_address",
]
