"""Chat room orchestration for multi-session agent discussion."""

from __future__ import annotations

import inspect
import re
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from core.chat.chat_task_types import trim_lines
from core.chatroom.scheduler import get_scheduler_registry
from core.chatroom.store import ChatRoomStore, utc_now_iso
from core.orchestration.output_boundary import sanitize_assistant_visible_text
from core.runtime_manager import work_run_store
from core.runtime_manager.work_run_leases import READONLY_CHAT_LEASE
from core.ui.chat_state import load_chat_state, normalize_chat_messages, save_chat_state

from . import agent_directory_service, session_service
from .agent_directory_service import active_agent_runtime, write_group_context_event
from .i18n import get_web_language, text_for
from .runtime_scene_service import record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUN_KIND = "chat_room_round"
RUN_LEASES = [READONLY_CHAT_LEASE]
DEFAULT_MODE = "round_robin"
RUNNING_ROUND_STATUSES = {"queued", "running", "stopping"}
_CHAT_ROOM_LOCK = threading.Lock()
_SAFE_ID_FRAGMENT = re.compile(r"[^A-Za-z0-9_.-]+")

AgentRunner = Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]]


def _sync_agent_directory_project_root() -> None:
    if agent_directory_service.PROJECT_ROOT != PROJECT_ROOT:
        agent_directory_service.PROJECT_ROOT = PROJECT_ROOT


class ChatRoomNotFoundError(ValueError):
    """Raised when a chat room does not exist."""


class ChatRoomValidationError(ValueError):
    """Raised when a chat room request is invalid."""


class ChatRoomBusyError(RuntimeError):
    """Raised when a chat room already has an active round."""


def list_chat_room_modes() -> list[dict[str, str]]:
    return get_scheduler_registry().list_modes()


def list_chat_rooms() -> list[dict[str, Any]]:
    state = _store().load()
    if _repair_room_participants_in_state(state):
        _store().save(state)
    rooms = [_room_to_api(item) for item in state.get("rooms") or [] if isinstance(item, dict)]
    rooms.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
    return rooms


def get_chat_room_detail(room_id: str) -> dict[str, Any] | None:
    state = _store().load()
    if _repair_room_participants_in_state(state):
        _store().save(state)
    room = _find_room(state, room_id)
    return _room_to_api(room) if room else None


def update_chat_room(
    room_id: str,
    *,
    title: str | None = None,
    participant_session_ids: list[str] | None = None,
    mode: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lang = get_web_language()
    normalized_room_id = str(room_id or "").strip()
    with _CHAT_ROOM_LOCK:
        state = _store().load()
        room = _find_room(state, normalized_room_id)
        if room is None:
            raise ChatRoomNotFoundError(text_for(lang, zh="未找到群聊。", en="Chat room not found."))
        _raise_if_room_busy(room)

        if title is not None:
            normalized_title = trim_lines(title or "", max_lines=1).strip()
            if normalized_title:
                room["title"] = normalized_title
        if mode is not None:
            normalized_mode = _normalize_mode(mode or room.get("mode") or DEFAULT_MODE)
            _require_ready_mode(normalized_mode)
            room["mode"] = normalized_mode
        if config is not None:
            room["config"] = _safe_config(config)
        if participant_session_ids is not None:
            participants = _resolve_participants(participant_session_ids)
            if not participants:
                raise ChatRoomValidationError(
                    text_for(lang, zh="至少需要一个可用会话才能更新群聊。", en="At least one session is required.")
                )
            room["participants"] = participants

        room["updatedAt"] = utc_now_iso()
        _store().save(state)

    _record_room_event(
        "room",
        "chat_room.updated",
        room,
        fields={"participantCount": len(room.get("participants") or []), "mode": room.get("mode") or DEFAULT_MODE},
    )
    return _room_to_api(room)


def delete_chat_room(room_id: str) -> dict[str, Any]:
    lang = get_web_language()
    normalized_room_id = str(room_id or "").strip()
    with _CHAT_ROOM_LOCK:
        state = _store().load()
        rooms = [item for item in list(state.get("rooms") or []) if isinstance(item, dict)]
        room = _find_room(state, normalized_room_id)
        if room is None:
            raise ChatRoomNotFoundError(text_for(lang, zh="未找到群聊。", en="Chat room not found."))
        _raise_if_room_busy(room)
        state["rooms"] = [
            item
            for item in rooms
            if str(item.get("roomId") or "").strip() != normalized_room_id
        ]
        _store().save(state)

    _record_room_event("room", "chat_room.deleted", room, fields={"roundCount": len(room.get("rounds") or [])})
    return {"deleted": True, "roomId": normalized_room_id}


def create_chat_room(
    *,
    title: str = "",
    participant_session_ids: list[str] | None = None,
    participant_agent_ids: list[str] | None = None,
    mode: str = DEFAULT_MODE,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lang = get_web_language()
    normalized_mode = _normalize_mode(mode or DEFAULT_MODE)
    _require_ready_mode(normalized_mode)
    with _CHAT_ROOM_LOCK:
        state = _store().load()
        existing_room_ids = {
            str(item.get("roomId") or "").strip()
            for item in state.get("rooms") or []
            if isinstance(item, dict)
        }
        room_id = _new_id("room", existing_room_ids)
        participants = (
            _resolve_agent_participants(participant_agent_ids)
            if participant_agent_ids
            else _resolve_participants(participant_session_ids)
        )
        if not participants:
            raise ChatRoomValidationError(
                text_for(lang, zh="至少需要一个可用会话才能创建群聊。", en="At least one session is required.")
            )
        now = utc_now_iso()
        room = {
            "roomId": room_id,
            "title": trim_lines(title or "", max_lines=1).strip()
            or text_for(lang, zh="Agent 群聊", en="Agent room"),
            "mode": normalized_mode,
            "config": _safe_config(config),
            "participants": participants,
            "rounds": [],
            "status": "ready",
            "activeRoundId": "",
            "createdAt": now,
            "updatedAt": now,
        }
        state["rooms"] = list(state.get("rooms") or []) + [room]
        _store().save(state)
    _record_room_event("room", "chat_room.created", room, fields={"participantCount": len(participants)})
    return _room_to_api(room)


def start_chat_room_round(
    room_id: str,
    topic: str,
    *,
    mode: str = "",
    config: dict[str, Any] | None = None,
    agent_runner: AgentRunner | None = None,
) -> dict[str, Any]:
    lang = get_web_language()
    normalized_room_id = str(room_id or "").strip()
    normalized_topic = trim_lines(topic or "", max_lines=6).strip()
    if not normalized_topic:
        raise ChatRoomValidationError(text_for(lang, zh="请输入本轮群聊议题。", en="Enter a room topic."))

    runner = agent_runner or _run_participant_agent
    with _CHAT_ROOM_LOCK:
        state = _store().load()
        room = _find_room(state, normalized_room_id)
        if room is None:
            raise ChatRoomNotFoundError(text_for(lang, zh="未找到群聊。", en="Chat room not found."))
        _raise_if_room_busy(room)
        round_mode = _normalize_mode(mode or room.get("mode") or DEFAULT_MODE)
        scheduler = _require_ready_mode(round_mode)
        round_config = {**_safe_config(room.get("config")), **_safe_config(config)}
        participants = _refresh_participants(room.get("participants") or [])
        speakers = scheduler.select_speakers(
            participants,
            topic=normalized_topic,
            history=list(room.get("rounds") or []),
            config=round_config,
        )
        if not speakers:
            raise ChatRoomValidationError(
                text_for(lang, zh="群聊没有可发言的参与者。", en="The chat room has no enabled speakers.")
            )
        round_id = _new_id(
            "round",
            {
                str(item.get("roundId") or "").strip()
                for item in list(room.get("rounds") or [])
                if isinstance(item, dict)
            },
        )
        now = utc_now_iso()
        round_payload = {
            "roundId": round_id,
            "roomId": normalized_room_id,
            "topic": normalized_topic,
            "mode": round_mode,
            "config": round_config,
            "status": "running",
            "speakerOrder": [item["participantId"] for item in speakers],
            "messages": [],
            "summary": "",
            "startedAt": now,
            "updatedAt": now,
            "finishedAt": "",
        }
        room["participants"] = participants
        room["rounds"] = list(room.get("rounds") or []) + [round_payload]
        room["status"] = "running"
        room["activeRoundId"] = round_id
        room["updatedAt"] = now
        _store().save(state)

    _persist_chat_room_work_run(room, round_payload, status="running", summary="")
    _record_room_event(
        "round",
        "chat_room.round.started",
        room,
        round_payload,
        fields={"mode": round_mode, "participantCount": len(speakers)},
        outcome="running",
        lifecycle=True,
    )

    messages: list[dict[str, Any]] = []
    for index, participant in enumerate(speakers):
        prompt = _build_participant_prompt(
            room=room,
            round_payload=round_payload,
            participant=participant,
            prior_messages=messages,
        )
        context = {
            "roomId": normalized_room_id,
            "roundId": round_id,
            "topic": normalized_topic,
            "mode": round_mode,
            "speakerIndex": index,
        }
        message = _run_one_speaker(participant, prompt, context, runner)
        messages.append(message)
        _record_room_event(
            "speaker",
            "chat_room.speaker.completed" if message["status"] == "completed" else "chat_room.speaker.failed",
            room,
            round_payload,
            fields={
                "participantId": participant["participantId"],
                "sessionId": participant.get("sessionId") or "",
                "speakerIndex": index,
                "status": message["status"],
                "contentChars": len(message.get("content") or ""),
                "errorType": message.get("errorType") or "",
            },
            outcome=message["status"],
            level="info" if message["status"] == "completed" else "warning",
        )

    completed_count = sum(1 for item in messages if item.get("status") == "completed")
    final_status = "completed" if completed_count > 0 else "failed"
    summary = _round_summary(messages, lang=lang)
    finished_at = utc_now_iso()
    with _CHAT_ROOM_LOCK:
        state = _store().load()
        room = _find_room(state, normalized_room_id)
        if room is None:
            raise ChatRoomNotFoundError(text_for(lang, zh="未找到群聊。", en="Chat room not found."))
        target_round = _find_round(room, round_id)
        if target_round is None:
            raise ChatRoomNotFoundError(text_for(lang, zh="未找到群聊轮次。", en="Chat room round not found."))
        target_round["messages"] = messages
        target_round["summary"] = summary
        target_round["status"] = final_status
        target_round["updatedAt"] = finished_at
        target_round["finishedAt"] = finished_at
        room["status"] = "ready" if final_status == "completed" else "failed"
        room["activeRoundId"] = ""
        room["updatedAt"] = finished_at
        _store().save(state)

    _persist_chat_room_work_run(room, target_round, status=final_status, summary=summary)
    _record_room_event(
        "round",
        "chat_room.round.completed" if final_status == "completed" else "chat_room.round.failed",
        room,
        target_round,
        fields={
            "mode": round_mode,
            "messageCount": len(messages),
            "completedCount": completed_count,
            "failedCount": len(messages) - completed_count,
        },
        outcome=final_status,
        level="info" if final_status == "completed" else "error",
        lifecycle=True,
    )
    if completed_count > 0:
        _sync_group_context_events(room, target_round)
        _sync_group_round_to_participant_sessions(room, target_round)
    return _room_to_api(room)


def load_chat_room_work_run_summary() -> dict[str, Any]:
    store = _work_run_store()
    return {
        "active": store.load_active_snapshot(RUN_KIND),
        "latest": store.load_latest_snapshot(RUN_KIND),
    }


def _run_one_speaker(
    participant: dict[str, Any],
    prompt: str,
    context: dict[str, Any],
    runner: AgentRunner,
) -> dict[str, Any]:
    timestamp = utc_now_iso()
    try:
        result = runner(participant, prompt, context)
        content = _result_visible_text(result)
        if not content:
            content = _result_summary(result) or "No visible response."
        return {
            "messageId": _new_id("message", set()),
            "participantId": participant["participantId"],
            "agentId": participant.get("agentId") or "",
            "sessionId": participant.get("sessionId") or "",
            "speakerTitle": participant.get("title") or participant["participantId"],
            "status": "completed",
            "content": content,
            "summary": _result_summary(result),
            "timestamp": timestamp,
        }
    except Exception as exc:
        return {
            "messageId": _new_id("message", set()),
            "participantId": participant["participantId"],
            "agentId": participant.get("agentId") or "",
            "sessionId": participant.get("sessionId") or "",
            "speakerTitle": participant.get("title") or participant["participantId"],
            "status": "failed",
            "content": "",
            "summary": f"{type(exc).__name__}: {exc}",
            "errorType": type(exc).__name__,
            "timestamp": timestamp,
        }


def _run_participant_agent(participant: dict[str, Any], prompt: str, context: dict[str, Any]) -> dict[str, Any]:
    session_id = str(participant.get("sessionId") or "").strip()
    workspace = _participant_workspace(session_id, context.get("roomId"), participant.get("participantId"))
    agent_profile_id = str(participant.get("agentProfileId") or participant.get("agentTemplateId") or "primary").strip() or "primary"
    agent_config = session_service._session_agent_config_for_profile(agent_profile_id)
    _sync_agent_directory_project_root()
    with active_agent_runtime(
        str(participant.get("agentId") or "").strip(),
        session_id=session_id,
        room_id=str(context.get("roomId") or "").strip(),
        round_id=str(context.get("roundId") or "").strip(),
    ):
        agent = session_service.create_chat_agent(workspace_path=workspace, config=agent_config)
        restore = getattr(agent, "seed_chat_history", None)
        if callable(restore):
            restore(participant.get("recentMessages") or [])
        runner = getattr(agent, "run_single_turn")
        try:
            signature = inspect.signature(runner)
        except (TypeError, ValueError):
            signature = None
        if signature is not None and "disable_tools" in signature.parameters:
            return runner(initial_prompt=prompt, disable_tools=True)
        return runner(initial_prompt=prompt)


def _build_participant_prompt(
    *,
    room: dict[str, Any],
    round_payload: dict[str, Any],
    participant: dict[str, Any],
    prior_messages: list[dict[str, Any]],
) -> str:
    recent_session_lines = _format_recent_session_messages(participant.get("recentMessages") or [])
    prior_lines = _format_prior_room_messages(prior_messages)
    return "\n".join(
        [
            "你正在参加 Vibelution 的只读 Agent 群聊。",
            f"群聊: {room.get('title') or room.get('roomId')}",
            f"当前议题: {round_payload.get('topic') or ''}",
            f"调度模式: {round_payload.get('mode') or DEFAULT_MODE}",
            f"你的身份: {participant.get('title') or participant.get('participantId')}",
            f"来源会话: {participant.get('sessionId') or ''}",
            "",
            "你的会话近况:",
            recent_session_lines or "- 暂无可用会话消息。",
            "",
            "本轮已经出现的群聊发言:",
            prior_lines or "- 你是本轮第一位发言者。",
            "",
            "请给出一段紧凑、可读、只读的群聊发言。不要修改文件、不要提交、不要启动进化或部署。",
            "如果你没有新信息，请明确说明你的确认、保留意见或下一步建议。",
        ]
    )


def _format_recent_session_messages(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in messages[-6:]:
        role = str(item.get("role") or "").strip() or "message"
        content = trim_lines(str(item.get("content") or ""), max_lines=2)
        if content:
            lines.append(f"- {role}: {content}")
    return "\n".join(lines)


def _format_prior_room_messages(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in messages[-8:]:
        speaker = str(item.get("speakerTitle") or item.get("participantId") or "speaker").strip()
        content = trim_lines(str(item.get("content") or item.get("summary") or ""), max_lines=3)
        if content:
            lines.append(f"- {speaker}: {content}")
    return "\n".join(lines)


def _result_visible_text(result: Any) -> str:
    if isinstance(result, dict):
        raw = result.get("raw_output") or result.get("content") or result.get("response") or ""
    else:
        raw = str(result or "")
    return sanitize_assistant_visible_text(trim_lines(str(raw or ""), max_lines=20)).strip()


def _result_summary(result: Any) -> str:
    if isinstance(result, dict):
        return trim_lines(str(result.get("summary") or result.get("message") or ""), max_lines=4)
    return ""


def _round_summary(messages: list[dict[str, Any]], *, lang: str) -> str:
    total = len(messages)
    completed = sum(1 for item in messages if item.get("status") == "completed")
    failed = total - completed
    return text_for(
        lang,
        zh=f"本轮群聊完成：{completed}/{total} 位参与者成功发言，{failed} 位失败。",
        en=f"Chat room round finished: {completed}/{total} participants responded, {failed} failed.",
    )


def _sync_group_context_events(room: dict[str, Any], round_payload: dict[str, Any]) -> None:
    _sync_agent_directory_project_root()
    participants = [
        item for item in list(room.get("participants") or [])
        if isinstance(item, dict) and str(item.get("agentId") or "").strip()
    ]
    messages = [
        item for item in list(round_payload.get("messages") or [])
        if isinstance(item, dict) and str(item.get("status") or "").strip().lower() == "completed"
    ]
    if not participants or not messages:
        return
    room_id = str(room.get("roomId") or "").strip()
    round_id = str(round_payload.get("roundId") or "").strip()
    topic = str(round_payload.get("topic") or "").strip()
    summary = str(round_payload.get("summary") or "").strip()
    message_by_participant = {
        str(message.get("participantId") or "").strip(): message
        for message in messages
    }
    peer_highlights_by_participant: dict[str, list[str]] = {}
    for participant in participants:
        participant_id = str(participant.get("participantId") or "").strip()
        highlights: list[str] = []
        for message in messages:
            if str(message.get("participantId") or "").strip() == participant_id:
                continue
            speaker = str(message.get("speakerTitle") or message.get("participantId") or "").strip()
            content = trim_lines(str(message.get("content") or message.get("summary") or ""), max_lines=2)
            if content:
                highlights.append(f"{speaker}: {content}" if speaker else content)
        peer_highlights_by_participant[participant_id] = highlights[:8]

    synced_count = 0
    for participant in participants:
        agent_id = str(participant.get("agentId") or "").strip()
        participant_id = str(participant.get("participantId") or "").strip()
        own_message = message_by_participant.get(participant_id) or {}
        try:
            write_group_context_event(
                agent_id,
                {
                    "sourceRoomId": room_id,
                    "sourceRoundId": round_id,
                    "targetSessionId": participant.get("sessionId") or participant.get("directSessionId") or "",
                    "topic": topic,
                    "summary": summary,
                    "ownMessage": own_message.get("content") or own_message.get("summary") or "",
                    "peerHighlights": peer_highlights_by_participant.get(participant_id) or [],
                    "promptEligible": True,
                    "createdAt": utc_now_iso(),
                },
            )
            synced_count += 1
        except Exception as exc:
            _record_room_event(
                "group_context",
                "group_context.sync_failed",
                room,
                round_payload,
                fields={
                    "agentId": agent_id,
                    "participantId": participant_id,
                    "errorType": type(exc).__name__,
                    "errorPreview": trim_lines(str(exc), max_lines=2),
                },
                outcome="failed",
                level="warning",
                lifecycle=True,
            )
    _record_room_event(
        "group_context",
        "group_context.synced",
        room,
        round_payload,
        fields={"syncedCount": synced_count, "participantCount": len(participants)},
        outcome="written",
        lifecycle=True,
    )


def _sync_group_round_to_participant_sessions(room: dict[str, Any], round_payload: dict[str, Any]) -> None:
    participants = [
        item for item in list(room.get("participants") or [])
        if isinstance(item, dict) and str(item.get("sessionId") or item.get("directSessionId") or "").strip()
    ]
    messages = [
        item for item in list(round_payload.get("messages") or [])
        if isinstance(item, dict) and str(item.get("status") or "").strip().lower() == "completed"
    ]
    room_id = str(room.get("roomId") or round_payload.get("roomId") or "").strip()
    round_id = str(round_payload.get("roundId") or "").strip()
    if not participants or not messages or not room_id or not round_id:
        return

    timestamp = (
        str(round_payload.get("finishedAt") or round_payload.get("updatedAt") or "").strip()
        or utc_now_iso()
    )
    synced_count = 0
    skipped_count = 0
    missing_count = 0
    with session_service._CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversations = payload.get("conversations")
        if not isinstance(conversations, list):
            return
        for participant in participants:
            session_id = str(participant.get("sessionId") or participant.get("directSessionId") or "").strip()
            if not session_id:
                continue
            conversation = session_service._find_conversation_entry(payload, session_id)
            if conversation is None:
                missing_count += 1
                continue
            raw_messages = list(conversation.get("messages") or [])
            if _has_group_round_session_sync(raw_messages, room_id=room_id, round_id=round_id):
                skipped_count += 1
                continue
            raw_messages.append(
                _build_group_round_session_message(
                    room,
                    round_payload,
                    participant,
                    messages,
                    timestamp=timestamp,
                )
            )
            conversation["messages"] = normalize_chat_messages(raw_messages)
            conversation["updated_at"] = timestamp
            synced_count += 1
        if synced_count:
            payload["updated_at"] = timestamp
            save_chat_state(PROJECT_ROOT, payload)

    _record_room_event(
        "group_context",
        "group_context.session_transcript_synced",
        room,
        round_payload,
        fields={
            "syncedSessionCount": synced_count,
            "skippedSessionCount": skipped_count,
            "missingSessionCount": missing_count,
            "participantCount": len(participants),
        },
        outcome="written" if synced_count else "skipped",
        lifecycle=True,
    )


def _has_group_round_session_sync(messages: list[dict[str, Any]], *, room_id: str, round_id: str) -> bool:
    marker = f"sourceRoundId: {round_id}"
    for item in list(messages or []):
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata")
        if isinstance(metadata, dict):
            if (
                str(metadata.get("kind") or "").strip() == "group_room_transcript"
                and str(metadata.get("sourceRoomId") or "").strip() == room_id
                and str(metadata.get("sourceRoundId") or "").strip() == round_id
            ):
                return True
        content = str(item.get("content") or "")
        if room_id in content and marker in content:
            return True
    return False


def _build_group_round_session_message(
    room: dict[str, Any],
    round_payload: dict[str, Any],
    participant: dict[str, Any],
    messages: list[dict[str, Any]],
    *,
    timestamp: str,
) -> dict[str, Any]:
    room_id = str(room.get("roomId") or round_payload.get("roomId") or "").strip()
    round_id = str(round_payload.get("roundId") or "").strip()
    participant_id = str(participant.get("participantId") or "").strip()
    own_lines: list[str] = []
    peer_lines: list[str] = []
    for message in messages:
        speaker = str(message.get("speakerTitle") or message.get("participantId") or "").strip()
        content = trim_lines(str(message.get("content") or message.get("summary") or ""), max_lines=4)
        if not content:
            continue
        line = f"- {speaker}: {content}" if speaker else f"- {content}"
        if str(message.get("participantId") or "").strip() == participant_id:
            own_lines.append(line)
        else:
            peer_lines.append(line)
    content_lines = [
        "[群聊同步]",
        f"群聊: {room.get('title') or room_id}",
        f"议题: {round_payload.get('topic') or ''}",
        f"摘要: {round_payload.get('summary') or ''}",
        "",
        "你的发言:",
        *(own_lines or ["- 本轮你没有发言。"]),
        "",
        "其他 Agent 发言:",
        *(peer_lines or ["- 本轮暂无其他 Agent 发言。"]),
    ]
    return {
        "role": "assistant",
        "content": "\n".join(str(line) for line in content_lines if str(line).strip() or line == ""),
        "timestamp": str(timestamp or utc_now_iso()).strip(),
        "metadata": {
            "kind": "group_room_transcript",
            "sourceRoomId": room_id,
            "sourceRoundId": round_id,
            "sourceRoomTitle": str(room.get("title") or "").strip(),
            "targetSessionId": str(participant.get("sessionId") or participant.get("directSessionId") or "").strip(),
            "targetAgentId": str(participant.get("agentId") or "").strip(),
            "participantId": participant_id,
        },
    }


def _resolve_participants(session_ids: list[str] | None) -> list[dict[str, Any]]:
    summaries = session_service.list_sessions()
    by_id = {str(item.get("id") or "").strip(): item for item in summaries}
    requested = [str(item or "").strip() for item in list(session_ids or []) if str(item or "").strip()]
    if not requested:
        requested = [str(item.get("id") or "").strip() for item in summaries if str(item.get("id") or "").strip()]
    participants: list[dict[str, Any]] = []
    seen: set[str] = set()
    for session_id in requested:
        if session_id in seen:
            continue
        seen.add(session_id)
        summary = by_id.get(session_id)
        if not summary:
            raise ChatRoomValidationError(f"Unknown chat session: {session_id}")
        participants.append(_participant_from_session(summary))
    return participants


def _resolve_agent_participants(agent_ids: list[str] | None) -> list[dict[str, Any]]:
    lang = get_web_language()
    _sync_agent_directory_project_root()
    requested = [str(item or "").strip() for item in list(agent_ids or []) if str(item or "").strip()]
    deduped: list[str] = []
    seen: set[str] = set()
    for agent_id in requested:
        if agent_id in seen:
            continue
        seen.add(agent_id)
        deduped.append(agent_id)
    if len(deduped) < 2:
        raise ChatRoomValidationError(
            text_for(lang, zh="群聊至少需要选择两个可用 Agent。", en="Choose at least two available agents.")
        )

    active_agents = {
        str(item.get("agentId") or "").strip(): item
        for item in agent_directory_service.list_agents(include_archived=False)
        if isinstance(item, dict)
    }
    session_ids: list[str] = []
    for agent_id in deduped:
        agent = active_agents.get(agent_id)
        if not agent:
            raise ChatRoomValidationError(f"Unknown active agent: {agent_id}")
        if str(agent.get("kind") or "").strip() != agent_directory_service.DEFAULT_AGENT_KIND:
            raise ChatRoomValidationError(f"Agent is not persistent: {agent_id}")
        direct_session_id = str(agent.get("directSessionId") or "").strip()
        if not direct_session_id:
            raise ChatRoomValidationError(f"Agent has no direct chat session: {agent_id}")
        session_ids.append(direct_session_id)

    return _resolve_participants(session_ids)


def _participant_from_session(summary: dict[str, Any]) -> dict[str, Any]:
    session_id = str(summary.get("id") or "").strip()
    title = str(summary.get("title") or session_id).strip() or session_id
    detail = session_service.get_session_detail(session_id) or {}
    agent_profile_id = str(summary.get("agentProfileId") or detail.get("agentProfileId") or "primary").strip() or "primary"
    return {
        "participantId": f"session-{_safe_fragment(session_id)}",
        "kind": "session_agent",
        "agentId": str(summary.get("agentId") or detail.get("agentId") or "").strip(),
        "directSessionId": session_id,
        "sessionId": session_id,
        "title": title,
        "workspacePath": str(summary.get("workspacePath") or detail.get("workspacePath") or ""),
        "agentProfileId": agent_profile_id,
        "agentTemplateId": agent_profile_id,
        "agentTemplateLabel": str(summary.get("agentTemplateLabel") or detail.get("agentTemplateLabel") or agent_profile_id),
        "enabled": True,
        "status": str(summary.get("status") or ""),
        "recentMessages": _compact_messages(detail.get("messages") or []),
    }


def _refresh_participants(participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refreshed: list[dict[str, Any]] = []
    for item in participants:
        if not isinstance(item, dict):
            continue
        session_id = str(item.get("sessionId") or "").strip()
        summary = _session_summary(session_id)
        if summary:
            participant = _participant_from_session(summary)
            participant["participantId"] = str(item.get("participantId") or participant["participantId"])
            participant["enabled"] = bool(item.get("enabled", True))
            participant["agentId"] = str(item.get("agentId") or participant.get("agentId") or "").strip()
            participant["directSessionId"] = str(item.get("directSessionId") or participant.get("directSessionId") or participant.get("sessionId") or "").strip()
            refreshed.append(participant)
        else:
            refreshed.append(dict(item))
    return refreshed


def _repair_room_participants_in_state(state: dict[str, Any]) -> bool:
    changed = False
    for room in list(state.get("rooms") or []):
        if not isinstance(room, dict):
            continue
        participants = list(room.get("participants") or [])
        refreshed = _refresh_participants(participants)
        if refreshed != participants:
            room["participants"] = refreshed
            room["updatedAt"] = utc_now_iso()
            changed = True
    return changed


def _session_summary(session_id: str) -> dict[str, Any] | None:
    for item in session_service.list_sessions():
        if str(item.get("id") or "").strip() == session_id:
            return item
    return None


def _compact_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    compact: list[dict[str, str]] = []
    for item in list(messages or [])[-8:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        content = trim_lines(str(item.get("content") or ""), max_lines=3)
        if role and content:
            compact.append({"role": role, "content": content})
    return compact


def _require_ready_mode(mode: str):
    scheduler = get_scheduler_registry().get(mode)
    if scheduler is None:
        raise ChatRoomValidationError(f"Unknown chat room mode: {mode}")
    if scheduler.status != "ready":
        raise ChatRoomValidationError(f"Chat room mode {mode} is not ready.")
    return scheduler


def _normalize_mode(mode: str) -> str:
    normalized = str(mode or DEFAULT_MODE).strip().lower().replace("-", "_")
    return normalized or DEFAULT_MODE


def _safe_config(config: Any) -> dict[str, Any]:
    return dict(config) if isinstance(config, dict) else {}


def _room_to_api(room: dict[str, Any]) -> dict[str, Any]:
    payload = dict(room)
    payload["participants"] = [dict(item) for item in list(room.get("participants") or []) if isinstance(item, dict)]
    payload["rounds"] = [dict(item) for item in list(room.get("rounds") or []) if isinstance(item, dict)]
    payload["availableModes"] = list_chat_room_modes()
    return payload


def _store() -> ChatRoomStore:
    return ChatRoomStore(root=PROJECT_ROOT)


def _work_run_store() -> work_run_store.WorkRunStore:
    return work_run_store.WorkRunStore(root=work_run_store.WORK_RUNS_DIR)


def _persist_chat_room_work_run(
    room: dict[str, Any],
    round_payload: dict[str, Any],
    *,
    status: str,
    summary: str,
) -> None:
    round_id = str(round_payload.get("roundId") or "").strip()
    if not round_id:
        return
    normalized_status = str(status or "running").strip().lower()
    now = utc_now_iso()
    payload = {
        "runId": round_id,
        "runKind": RUN_KIND,
        "track": "dialogue",
        "roomId": str(room.get("roomId") or "").strip(),
        "roundId": round_id,
        "status": normalized_status,
        "currentPhase": normalized_status,
        "leases": list(RUN_LEASES),
        "topic": str(round_payload.get("topic") or "").strip(),
        "mode": str(round_payload.get("mode") or DEFAULT_MODE).strip(),
        "summary": str(summary or round_payload.get("summary") or "").strip(),
        "startedAt": str(round_payload.get("startedAt") or now).strip(),
        "updatedAt": now,
        "finishedAt": str(round_payload.get("finishedAt") or "").strip()
        if normalized_status not in RUNNING_ROUND_STATUSES
        else "",
    }
    active_run_id = round_id if normalized_status in RUNNING_ROUND_STATUSES else ""
    _work_run_store().persist_snapshot(RUN_KIND, payload, active_run_id=active_run_id)


def _record_room_event(
    phase: str,
    event_code: str,
    room: dict[str, Any],
    round_payload: dict[str, Any] | None = None,
    *,
    fields: dict[str, Any] | None = None,
    outcome: str = "observed",
    level: str = "info",
    lifecycle: bool = False,
) -> None:
    event_fields = {
        "roomId": str(room.get("roomId") or "").strip(),
        "roomTitle": str(room.get("title") or "").strip(),
    }
    if round_payload:
        event_fields.update(
            {
                "roundId": str(round_payload.get("roundId") or "").strip(),
                "topicLength": len(str(round_payload.get("topic") or "")),
            }
        )
    if fields:
        event_fields.update(fields)
    try:
        record_runtime_scene_event(
            "chat_room",
            phase,
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields=event_fields,
            lifecycle=lifecycle,
        )
    except Exception:
        return


def _find_room(state: dict[str, Any], room_id: str) -> dict[str, Any] | None:
    normalized = str(room_id or "").strip()
    for item in state.get("rooms") or []:
        if isinstance(item, dict) and str(item.get("roomId") or "").strip() == normalized:
            return item
    return None


def _find_round(room: dict[str, Any], round_id: str) -> dict[str, Any] | None:
    normalized = str(round_id or "").strip()
    for item in room.get("rounds") or []:
        if isinstance(item, dict) and str(item.get("roundId") or "").strip() == normalized:
            return item
    return None


def _raise_if_room_busy(room: dict[str, Any]) -> None:
    active_round_id = str(room.get("activeRoundId") or "").strip()
    for item in room.get("rounds") or []:
        if not isinstance(item, dict):
            continue
        if active_round_id and str(item.get("roundId") or "").strip() != active_round_id:
            continue
        if str(item.get("status") or "").strip().lower() in RUNNING_ROUND_STATUSES:
            raise ChatRoomBusyError("Chat room already has an active round.")


def _participant_workspace(session_id: Any, room_id: Any, participant_id: Any) -> Path:
    normalized_session_id = str(session_id or "").strip()
    if normalized_session_id:
        return session_service._ensure_session_workspace(normalized_session_id)
    base = (PROJECT_ROOT / "workspace" / "chat_rooms" / _safe_fragment(room_id) / _safe_fragment(participant_id)).resolve()
    root = (PROJECT_ROOT / "workspace" / "chat_rooms").resolve()
    if not base.is_relative_to(root):
        raise ChatRoomValidationError("Invalid chat room workspace path.")
    base.mkdir(parents=True, exist_ok=True)
    return base


def _new_id(prefix: str, existing: set[str]) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    base = f"{prefix}-{stamp}-{uuid.uuid4().hex[:8]}"
    candidate = base
    suffix = 2
    while candidate in existing:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _safe_fragment(value: Any) -> str:
    fragment = _SAFE_ID_FRAGMENT.sub("-", str(value or "").strip()).strip("._-")
    return fragment[:96] or "item"
