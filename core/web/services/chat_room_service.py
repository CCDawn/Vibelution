"""Chat room orchestration for multi-session agent discussion."""

from __future__ import annotations

import inspect
import json
import queue
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from core.chat.chat_task_types import trim_lines
from core.chatroom.scheduler import get_scheduler_registry
from core.chatroom.store import ChatRoomStore, utc_now_iso
from core.orchestration.context_engine import build_agent_context, record_agent_turn_result
from core.orchestration.output_boundary import sanitize_assistant_visible_text
from core.runtime_manager import work_run_store
from core.runtime_manager.work_run_leases import READONLY_CHAT_LEASE
from core.ui.chat_state import load_chat_state, normalize_chat_messages, save_chat_state

from . import agent_directory_service, session_service
from .agent_directory_service import active_agent_runtime, evaluate_agent_workspace_write, write_group_context_event
from .i18n import get_web_language, text_for
from .runtime_scene_service import record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUN_KIND = "chat_room_round"
RUN_LEASES = [READONLY_CHAT_LEASE]
DEFAULT_MODE = "round_robin"
DEFAULT_PURPOSE = "discussion"
CHAT_ROOM_PURPOSES = [
    {
        "id": "chat",
        "label": "Chat",
        "description": "Short, natural replies that follow the current topic and prior speaker.",
    },
    {
        "id": "discussion",
        "label": "Discussion",
        "description": "Point-of-view exchange with tradeoffs, disagreement, and suggestions.",
    },
    {
        "id": "meeting",
        "label": "Meeting",
        "description": "Structured meeting notes with decisions, risks, and action items.",
    },
]
RUNNING_ROUND_STATUSES = {"queued", "running", "stopping"}
_CHAT_ROOM_LOCK = threading.Lock()
_CHAT_ROOM_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="web-chat-room")
_CHAT_ROOM_STREAM_SUBSCRIBERS_LOCK = threading.Lock()
_CHAT_ROOM_STREAM_SUBSCRIBERS: dict[str, set[queue.Queue[dict[str, Any]]]] = {}
_CHAT_ROOM_STREAM_HEARTBEAT_SECONDS = 15.0
_CHAT_ROOM_STREAM_QUEUE_SIZE = 8
_SAFE_ID_FRAGMENT = re.compile(r"[^A-Za-z0-9_.-]+")

AgentRunner = Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]]
_CHAT_ROOM_ROUND_CONTROLS_LOCK = threading.Lock()
_CHAT_ROOM_ROUND_CONTROLS: dict[str, dict[str, str]] = {}


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


def list_chat_room_purposes() -> list[dict[str, str]]:
    return [dict(item) for item in CHAT_ROOM_PURPOSES]


def list_chat_rooms(
    *,
    session_summaries: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    state = _store().load()
    summaries = session_summaries if session_summaries is not None else _session_summary_index()
    if _repair_room_participants_in_state(state, session_summaries=summaries):
        _store().save(state)
    rooms = [_room_to_api(item) for item in state.get("rooms") or [] if isinstance(item, dict)]
    rooms.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
    return rooms


def get_chat_room_detail(room_id: str) -> dict[str, Any] | None:
    state = _store().load()
    session_summaries = _session_summary_index()
    if _repair_room_participants_in_state(state, session_summaries=session_summaries):
        _store().save(state)
    room = _find_room(state, room_id)
    return _room_to_api(room) if room else None


def update_chat_room(
    room_id: str,
    *,
    title: str | None = None,
    participant_session_ids: list[str] | None = None,
    mode: str | None = None,
    purpose: str | None = None,
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
        if purpose is not None:
            room["purpose"] = _normalize_purpose(purpose or room.get("purpose") or DEFAULT_PURPOSE)
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
        fields={
            "participantCount": len(room.get("participants") or []),
            "mode": room.get("mode") or DEFAULT_MODE,
            "purpose": room.get("purpose") or DEFAULT_PURPOSE,
        },
    )
    return _room_to_api(room)


def update_agent_chat_room_membership(agent_id: str, room_ids: list[str] | None) -> dict[str, Any]:
    """Update the rooms a single persistent Agent belongs to without touching peers."""

    lang = get_web_language()
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise ChatRoomValidationError(text_for(lang, zh="缺少 Agent。", en="Agent id is required."))

    target_room_ids = _dedupe_room_ids(room_ids)
    participant = _resolve_agent_participant(normalized_agent_id)
    direct_session_id = str(participant.get("sessionId") or participant.get("directSessionId") or "").strip()
    changed_rooms: list[dict[str, Any]] = []
    now = utc_now_iso()

    with _CHAT_ROOM_LOCK:
        state = _store().load()
        rooms = [item for item in list(state.get("rooms") or []) if isinstance(item, dict)]
        rooms_by_id = {
            str(room.get("roomId") or "").strip(): room
            for room in rooms
            if str(room.get("roomId") or "").strip()
        }
        missing_room_ids = [room_id for room_id in target_room_ids if room_id not in rooms_by_id]
        if missing_room_ids:
            raise ChatRoomValidationError(f"Unknown chat room: {missing_room_ids[0]}")

        target_set = set(target_room_ids)
        for room in rooms:
            room_id = str(room.get("roomId") or "").strip()
            if not room_id:
                continue
            selected = room_id in target_set
            participants = [dict(item) for item in list(room.get("participants") or []) if isinstance(item, dict)]
            currently_selected = False
            kept_selected = False
            next_participants: list[dict[str, Any]] = []
            for item in participants:
                if _participant_matches_agent(item, normalized_agent_id, direct_session_id):
                    currently_selected = True
                    if selected and not kept_selected:
                        next_participants.append(dict(participant))
                        kept_selected = True
                    continue
                next_participants.append(item)
            if selected and not kept_selected:
                next_participants.append(dict(participant))
            if not selected and currently_selected and not next_participants:
                raise ChatRoomValidationError(
                    text_for(
                        lang,
                        zh="不能移除群聊中的最后一个成员。请先在群管理中添加其他成员或删除群聊。",
                        en="Cannot remove the last room participant. Add another member or delete the room first.",
                    )
                )
            if next_participants == participants:
                continue
            _raise_if_room_busy(room)
            room["participants"] = next_participants
            room["updatedAt"] = now
            changed_rooms.append(room)

        if changed_rooms:
            _store().save(state)

    for room in changed_rooms:
        _record_room_event(
            "membership",
            "chat_room.agent_membership.updated",
            room,
            fields={
                "agentId": normalized_agent_id,
                "selected": str(room.get("roomId") or "").strip() in set(target_room_ids),
                "participantCount": len(room.get("participants") or []),
            },
        )
    rooms_payload = list_chat_rooms()
    return {
        "agentId": normalized_agent_id,
        "roomIds": [
            str(room.get("roomId") or "").strip()
            for room in rooms_payload
            if normalized_agent_id
            in {
                str(participant.get("agentId") or "").strip()
                for participant in list(room.get("participants") or [])
                if isinstance(participant, dict)
            }
        ],
        "changedRoomIds": [str(room.get("roomId") or "").strip() for room in changed_rooms],
        "chatRooms": rooms_payload,
    }


def remove_agent_from_chat_rooms(agent_id: str) -> dict[str, Any]:
    """Remove one Agent from all chat room participant lists before safe archival."""

    lang = get_web_language()
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise ChatRoomValidationError(text_for(lang, zh="缺少 Agent。", en="Agent id is required."))
    direct_session_id = ""
    agent = agent_directory_service.get_agent(normalized_agent_id, include_archived=True)
    if isinstance(agent, dict):
        direct_session_id = str(agent.get("directSessionId") or "").strip()

    changed_rooms: list[dict[str, Any]] = []
    now = utc_now_iso()
    with _CHAT_ROOM_LOCK:
        state = _store().load()
        rooms = [item for item in list(state.get("rooms") or []) if isinstance(item, dict)]
        for room in rooms:
            participants = [dict(item) for item in list(room.get("participants") or []) if isinstance(item, dict)]
            next_participants = [
                item
                for item in participants
                if not _participant_matches_agent(item, normalized_agent_id, direct_session_id)
            ]
            if next_participants == participants:
                continue
            if not next_participants:
                raise ChatRoomValidationError(
                    text_for(
                        lang,
                        zh="不能归档仍是某个群聊唯一成员的 Agent。请先删除该群聊或添加其他成员。",
                        en="Cannot archive an Agent that is the only member of a group room. Delete the room or add another member first.",
                    )
                )
            _raise_if_room_busy(room)
            room["participants"] = next_participants
            room["updatedAt"] = now
            changed_rooms.append(room)
        if changed_rooms:
            _store().save(state)

    for room in changed_rooms:
        _record_room_event(
            "membership",
            "chat_room.agent_membership.removed",
            room,
            fields={
                "agentId": normalized_agent_id,
                "participantCount": len(room.get("participants") or []),
            },
        )
    return {
        "agentId": normalized_agent_id,
        "changedRoomIds": [str(room.get("roomId") or "").strip() for room in changed_rooms],
        "chatRooms": list_chat_rooms(),
    }


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
    purpose: str = DEFAULT_PURPOSE,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lang = get_web_language()
    normalized_mode = _normalize_mode(mode or DEFAULT_MODE)
    normalized_purpose = _normalize_purpose(purpose or DEFAULT_PURPOSE)
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
            "purpose": normalized_purpose,
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
    _record_room_event(
        "room",
        "chat_room.created",
        room,
        fields={"participantCount": len(participants), "purpose": normalized_purpose},
    )
    return _room_to_api(room)


def start_chat_room_round(
    room_id: str,
    topic: str,
    *,
    mode: str = "",
    purpose: str = "",
    config: dict[str, Any] | None = None,
    agent_runner: AgentRunner | None = None,
    background: bool = False,
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
        round_purpose = _normalize_purpose(purpose or room.get("purpose") or DEFAULT_PURPOSE)
        scheduler = _require_ready_mode(round_mode)
        round_config = {**_safe_config(room.get("config")), **_safe_config(config)}
        participants = _refresh_participants(
            room.get("participants") or [],
            include_recent_messages=True,
            session_summaries=_session_summary_index(),
        )
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
            "purpose": round_purpose,
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
    _create_chat_room_round_control(normalized_room_id, round_id)
    _record_room_event(
        "round",
        "chat_room.round.started",
        room,
        round_payload,
        fields={"mode": round_mode, "purpose": round_purpose, "participantCount": len(speakers)},
        outcome="running",
        lifecycle=True,
    )
    _publish_chat_room_detail_snapshot(normalized_room_id)

    if background:
        _CHAT_ROOM_EXECUTOR.submit(
            _run_chat_room_round_background,
            normalized_room_id,
            round_id,
            room,
            round_payload,
            speakers,
            runner,
            lang,
        )
        _record_room_event(
            "round",
            "chat_room.round.background_started",
            room,
            round_payload,
            fields={"mode": round_mode, "purpose": round_purpose, "participantCount": len(speakers)},
            outcome="running",
            lifecycle=True,
        )
        detail = get_chat_room_detail(normalized_room_id)
        if detail is None:
            raise ChatRoomNotFoundError(text_for(lang, zh="未找到群聊。", en="Chat room not found."))
        return detail

    return _execute_chat_room_round(
        normalized_room_id,
        round_id,
        room,
        round_payload,
        speakers,
        runner,
        lang,
    )


def stop_chat_room_round(room_id: str, *, reason: str = "") -> dict[str, Any]:
    """Request and persist a user stop for the active chat room round."""

    lang = get_web_language()
    normalized_room_id = str(room_id or "").strip()
    if not normalized_room_id:
        raise ChatRoomNotFoundError(text_for(lang, zh="未找到群聊。", en="Chat room not found."))
    stop_reason = str(reason or "").strip() or text_for(
        lang,
        zh="用户请求停止当前群聊轮次。",
        en="The user requested the current chat room round to stop.",
    )
    stopping_at = utc_now_iso()
    with _CHAT_ROOM_LOCK:
        state = _store().load()
        room = _find_room(state, normalized_room_id)
        if room is None:
            raise ChatRoomNotFoundError(text_for(lang, zh="未找到群聊。", en="Chat room not found."))
        active_round_id = str(room.get("activeRoundId") or "").strip()
        target_round = _find_round(room, active_round_id) if active_round_id else None
        if (
            target_round is None
            or str(target_round.get("status") or "").strip().lower() not in RUNNING_ROUND_STATUSES
        ):
            raise ChatRoomBusyError(text_for(lang, zh="当前群聊没有正在运行的轮次。", en="No chat room round is running."))
        _request_chat_room_round_stop(active_round_id, stop_reason)
        session_service.cancel_agent_execution_reservation(active_round_id)
        target_round["status"] = "stopping"
        target_round["summary"] = text_for(
            lang,
            zh="正在停止当前群聊轮次，等待正在发言的 Agent 收尾。",
            en="Stopping this chat room round while the current agent finishes.",
        )
        target_round["updatedAt"] = stopping_at
        target_round["finishedAt"] = ""
        room["status"] = "stopping"
        room["activeRoundId"] = active_round_id
        room["updatedAt"] = stopping_at
        _store().save(state)
        room_payload = dict(room)
        round_payload = dict(target_round)

    _persist_chat_room_work_run(
        room_payload,
        round_payload,
        status="stopping",
        summary=str(round_payload.get("summary") or stop_reason),
    )
    _record_room_event(
        "round",
        "chat_room.round.stop_requested",
        room_payload,
        round_payload,
        fields={"reason": trim_lines(stop_reason, max_lines=2)},
        outcome="stopping",
        lifecycle=True,
    )
    _publish_chat_room_detail_snapshot(normalized_room_id)
    return _room_to_api(room_payload)


def stream_chat_room_events(room_id: str, initial_detail: dict[str, Any] | None = None):
    """Yield SSE snapshots for one chat room."""

    normalized_room_id = str(room_id or "").strip()
    if not normalized_room_id:
        raise ChatRoomNotFoundError(text_for(get_web_language(), zh="未找到群聊。", en="Chat room not found."))
    detail = initial_detail or get_chat_room_detail(normalized_room_id)
    if detail is None:
        raise ChatRoomNotFoundError(text_for(get_web_language(), zh="未找到群聊。", en="Chat room not found."))

    subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=_CHAT_ROOM_STREAM_QUEUE_SIZE)
    _register_chat_room_stream_subscriber(normalized_room_id, subscriber)
    try:
        yield _encode_chat_room_sse_event(
            "chat_room_detail",
            {
                "type": "chat_room_detail",
                "roomId": normalized_room_id,
                "detail": detail,
            },
        )
        while True:
            try:
                event = subscriber.get(timeout=_CHAT_ROOM_STREAM_HEARTBEAT_SECONDS)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            yield _encode_chat_room_sse_event(str(event.get("type") or "message"), event)
    finally:
        _unregister_chat_room_stream_subscriber(normalized_room_id, subscriber)


def _run_chat_room_round_background(
    room_id: str,
    round_id: str,
    room: dict[str, Any],
    round_payload: dict[str, Any],
    speakers: list[dict[str, Any]],
    runner: AgentRunner,
    lang: str,
) -> None:
    try:
        _execute_chat_room_round(room_id, round_id, room, round_payload, speakers, runner, lang)
    except Exception as exc:
        _fail_chat_room_round(room_id, round_id, room, round_payload, exc, lang=lang)


def _execute_chat_room_round(
    normalized_room_id: str,
    round_id: str,
    room: dict[str, Any],
    round_payload: dict[str, Any],
    speakers: list[dict[str, Any]],
    runner: AgentRunner,
    lang: str,
) -> dict[str, Any]:
    round_mode = str(round_payload.get("mode") or DEFAULT_MODE).strip() or DEFAULT_MODE
    round_purpose = _normalize_purpose(round_payload.get("purpose") or room.get("purpose") or DEFAULT_PURPOSE)
    normalized_topic = str(round_payload.get("topic") or "").strip()

    messages: list[dict[str, Any]] = []
    for index, participant in enumerate(speakers):
        stopped_detail = _stopped_chat_room_round_detail(normalized_room_id, round_id)
        if stopped_detail is not None:
            _clear_chat_room_round_control(round_id)
            return stopped_detail
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
            "purpose": round_purpose,
            "speakerIndex": index,
        }
        message = _run_one_speaker(participant, prompt, context, runner)
        stopped_detail = _stopped_chat_room_round_detail(normalized_room_id, round_id)
        if stopped_detail is not None:
            _clear_chat_room_round_control(round_id)
            return stopped_detail
        messages.append(message)
        message_time = utc_now_iso()
        with _CHAT_ROOM_LOCK:
            state = _store().load()
            live_room = _find_room(state, normalized_room_id)
            if live_room is None:
                raise ChatRoomNotFoundError(text_for(lang, zh="未找到群聊。", en="Chat room not found."))
            target_round = _find_round(live_room, round_id)
            if target_round is None:
                raise ChatRoomNotFoundError(text_for(lang, zh="未找到群聊轮次。", en="Chat room round not found."))
            if _chat_room_round_is_terminal(live_room, target_round, round_id):
                _clear_chat_room_round_control(round_id)
                return _room_to_api(live_room)
            target_round["messages"] = [dict(item) for item in messages]
            target_round["status"] = "running"
            target_round["updatedAt"] = message_time
            live_room["status"] = "running"
            live_room["activeRoundId"] = round_id
            live_room["updatedAt"] = message_time
            _store().save(state)
            room = dict(live_room)
            round_payload = dict(target_round)
        _persist_chat_room_work_run(
            room,
            round_payload,
            status="running",
            summary=text_for(
                lang,
                zh=f"群聊进行中：{len(messages)}/{len(speakers)} 位 Agent 已发言。",
                en=f"Group discussion running: {len(messages)}/{len(speakers)} agents responded.",
            ),
        )
        _publish_chat_room_detail_snapshot(normalized_room_id)
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
                "purpose": round_purpose,
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
        if _chat_room_round_is_terminal(room, target_round, round_id):
            _clear_chat_room_round_control(round_id)
            return _room_to_api(room)
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
            "purpose": round_purpose,
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
    _publish_chat_room_detail_snapshot(normalized_room_id)
    _clear_chat_room_round_control(round_id)
    return _room_to_api(room)


def load_chat_room_work_run_summary() -> dict[str, Any]:
    store = _work_run_store()
    active_items = list_active_chat_room_work_runs()
    active = store.load_active_snapshot(RUN_KIND)
    if not active and active_items:
        active = active_items[0]
    return {
        "active": active,
        "activeItems": active_items,
        "latest": store.load_latest_snapshot(RUN_KIND),
    }


def list_active_chat_room_work_runs() -> list[dict[str, Any]]:
    """Return all active chat room rounds as lightweight WorkRun snapshots."""

    try:
        state = _store().load()
    except Exception:
        return []
    items: list[dict[str, Any]] = []
    for room in list(state.get("rooms") or []):
        if not isinstance(room, dict):
            continue
        active_round_id = str(room.get("activeRoundId") or "").strip()
        for round_payload in list(room.get("rounds") or []):
            if not isinstance(round_payload, dict):
                continue
            round_id = str(round_payload.get("roundId") or "").strip()
            status = str(round_payload.get("status") or "").strip().lower()
            if status not in RUNNING_ROUND_STATUSES:
                continue
            if active_round_id and round_id != active_round_id:
                continue
            items.append(_chat_room_work_run_snapshot(room, round_payload, status=status))
    items.sort(key=lambda item: str(item.get("updatedAt") or item.get("startedAt") or ""))
    return items


def force_stop_active_chat_room_rounds_for_shutdown(reason: str) -> list[dict[str, object]]:
    """Mark active chat room rounds as stopped before the backend exits."""

    stop_reason = str(reason or "").strip() or text_for(
        get_web_language(),
        zh="工作台关闭前停止活跃群聊轮次。",
        en="Stopped active chat room rounds before workbench shutdown.",
    )
    stopped_at = utc_now_iso()
    stopped: list[dict[str, object]] = []
    changed = False
    with _CHAT_ROOM_LOCK:
        state = _store().load()
        for room in list(state.get("rooms") or []):
            if not isinstance(room, dict):
                continue
            active_round_id = str(room.get("activeRoundId") or "").strip()
            for round_payload in list(room.get("rounds") or []):
                if not isinstance(round_payload, dict):
                    continue
                round_id = str(round_payload.get("roundId") or "").strip()
                status = str(round_payload.get("status") or "").strip().lower()
                if status not in RUNNING_ROUND_STATUSES:
                    continue
                if active_round_id and round_id != active_round_id:
                    continue
                _request_chat_room_round_stop(round_id, stop_reason)
                session_service.cancel_agent_execution_reservation(round_id)
                summary = _stopped_round_summary(
                    stop_reason,
                    message_count=len(list(round_payload.get("messages") or [])),
                    speaker_count=len(list(round_payload.get("speakerOrder") or [])),
                )
                round_payload["status"] = "stopped"
                round_payload["summary"] = summary
                round_payload["updatedAt"] = stopped_at
                round_payload["finishedAt"] = stopped_at
                room["status"] = "ready"
                if active_round_id == round_id:
                    room["activeRoundId"] = ""
                room["updatedAt"] = stopped_at
                changed = True
                stopped.append(
                    {
                        "kind": RUN_KIND,
                        "roomId": str(room.get("roomId") or ""),
                        "runId": round_id,
                        "roundId": round_id,
                        "status": "stopped",
                        "_room": dict(room),
                        "_round": dict(round_payload),
                    }
                )
        if changed:
            _store().save(state)

    for item in stopped:
        room_payload = item.pop("_room", {})
        round_payload = item.pop("_round", {})
        if isinstance(room_payload, dict) and isinstance(round_payload, dict):
            _persist_chat_room_work_run(
                room_payload,
                round_payload,
                status="stopped",
                summary=str(round_payload.get("summary") or stop_reason),
            )
            _record_room_event(
                "round",
                "chat_room.round.shutdown_stopped",
                room_payload,
                round_payload,
                fields={"reason": trim_lines(stop_reason, max_lines=2)},
                outcome="stopped",
                lifecycle=True,
            )
            _publish_chat_room_detail_snapshot(str(room_payload.get("roomId") or ""))
    return stopped


def _run_one_speaker(
    participant: dict[str, Any],
    prompt: str,
    context: dict[str, Any],
    runner: AgentRunner,
) -> dict[str, Any]:
    timestamp = utc_now_iso()
    supervision_decision = _evaluate_speaker_supervision_policy(participant)
    agent_directory_service.record_supervision_policy_decision(supervision_decision)
    supervision_payload = _supervision_decision_to_message(supervision_decision)
    if not supervision_decision.allowed:
        return {
            "messageId": _new_id("message", set()),
            "participantId": participant["participantId"],
            "agentId": participant.get("agentId") or "",
            "speakerCode": participant.get("agentCode") or "",
            "sessionId": participant.get("sessionId") or "",
            "speakerTitle": _participant_speaker_label(participant),
            "status": "blocked",
            "content": "",
            "summary": supervision_decision.reason,
            "timestamp": timestamp,
            "supervision": supervision_payload,
        }
    try:
        result = runner(participant, prompt, context)
        content = _result_visible_text(result)
        if not content:
            content = _result_summary(result) or "No visible response."
        return {
            "messageId": _new_id("message", set()),
            "participantId": participant["participantId"],
            "agentId": participant.get("agentId") or "",
            "speakerCode": participant.get("agentCode") or "",
            "sessionId": participant.get("sessionId") or "",
            "speakerTitle": _participant_speaker_label(participant),
            "status": "completed",
            "content": content,
            "summary": _result_summary(result),
            "timestamp": timestamp,
            "supervision": supervision_payload,
        }
    except Exception as exc:
        stop_reason = _chat_room_round_stop_reason(str(context.get("roundId") or "").strip())
        if stop_reason:
            return {
                "messageId": _new_id("message", set()),
                "participantId": participant["participantId"],
                "agentId": participant.get("agentId") or "",
                "speakerCode": participant.get("agentCode") or "",
                "sessionId": participant.get("sessionId") or "",
                "speakerTitle": _participant_speaker_label(participant),
                "status": "stopped",
                "content": "",
                "summary": stop_reason,
                "timestamp": timestamp,
                "errorType": type(exc).__name__,
                "error": str(exc),
            }
        return {
            "messageId": _new_id("message", set()),
            "participantId": participant["participantId"],
            "agentId": participant.get("agentId") or "",
            "speakerCode": participant.get("agentCode") or "",
            "sessionId": participant.get("sessionId") or "",
            "speakerTitle": _participant_speaker_label(participant),
            "status": "failed",
            "content": "",
            "summary": f"{type(exc).__name__}: {exc}",
            "errorType": type(exc).__name__,
            "timestamp": timestamp,
            "supervision": supervision_payload,
        }


def _evaluate_speaker_supervision_policy(participant: dict[str, Any]):
    agent_id = str(participant.get("agentId") or "").strip()
    return agent_directory_service.evaluate_supervision_policy(
        agent_directory_service.resolve_supervision_policy_for_agent(agent_id),
        agent_id=agent_id,
        action="chat_room_speaker",
        human_override=False,
        user_initiated=False,
    )


def _supervision_decision_to_message(decision: Any) -> dict[str, Any]:
    return {
        "allowed": bool(getattr(decision, "allowed", True)),
        "reason": str(getattr(decision, "reason", "") or ""),
        "supervisionEnabled": bool(getattr(decision, "supervision_enabled", False)),
        "requiresReview": bool(getattr(decision, "requires_review", False)),
        "reviewMode": str(getattr(decision, "review_mode", "") or ""),
        "evidenceLevel": str(getattr(decision, "evidence_level", "") or ""),
    }


def _run_participant_agent(participant: dict[str, Any], prompt: str, context: dict[str, Any]) -> dict[str, Any]:
    session_id = str(participant.get("sessionId") or "").strip()
    session_workspace = _participant_workspace(session_id, context.get("roomId"), participant.get("participantId"))
    _sync_agent_directory_project_root()
    agent_id = str(participant.get("agentId") or "").strip()
    round_id = str(context.get("roundId") or "").strip()
    agent_context = build_agent_context(agent_id, session_id=session_id, run_id=round_id) if agent_id else None
    agent = agent_directory_service.get_agent(agent_id) if agent_id else None
    agent_workspace = (
        agent_directory_service._ensure_agent_workspace(str((agent or {}).get("workspacePath") or "")).resolve()
        if agent and str((agent or {}).get("workspacePath") or "").strip()
        else session_workspace
    )
    write_decision = evaluate_agent_workspace_write(agent_id, agent_workspace, purpose="chat_room_agent_workspace") if agent_id else None
    workspace = agent_workspace if not write_decision or write_decision.allowed else session_workspace
    agent_profile_id = (
        str((agent_context.profile_id if agent_context is not None else "") or "").strip()
        or str(participant.get("agentProfileId") or participant.get("agentTemplateId") or "primary").strip()
        or "primary"
    )
    agent_config = session_service._session_agent_config_for_profile(agent_profile_id)
    with session_service.reserve_agent_execution_slot(
        agent_id=agent_id,
        run_id=round_id,
        session_id=session_id,
        owner="chat_room_round",
    ), active_agent_runtime(
        agent_id,
        session_id=session_id,
        room_id=str(context.get("roomId") or "").strip(),
        round_id=round_id,
    ), session_service._session_tool_workspace_override(workspace):
        agent = session_service.create_chat_agent(workspace_path=workspace, config=agent_config)
        stop_configurer = getattr(agent, "set_turn_interrupt_checker", None)
        if callable(stop_configurer):
            stop_configurer(lambda: _chat_room_round_stop_reason(round_id))
        restore = getattr(agent, "seed_chat_history", None)
        if callable(restore):
            restore(participant.get("recentMessages") or [])
        seed_runtime_context = getattr(agent, "seed_runtime_context", None)
        if callable(seed_runtime_context) and agent_context is not None and agent_context.context_block:
            seed_runtime_context(agent_context.context_block)
        runner = getattr(agent, "run_single_turn")
        try:
            signature = inspect.signature(runner)
        except (TypeError, ValueError):
            signature = None
        if signature is not None and "disable_tools" in signature.parameters:
            result = runner(initial_prompt=prompt, disable_tools=True)
        else:
            result = runner(initial_prompt=prompt)
    if agent_context is not None and agent_context.agent_id:
        record_agent_turn_result(
            agent_context.agent_id,
            session_id,
            result if isinstance(result, dict) else {},
            run_id=round_id,
        )
    return result


def _build_participant_prompt(
    *,
    room: dict[str, Any],
    round_payload: dict[str, Any],
    participant: dict[str, Any],
    prior_messages: list[dict[str, Any]],
) -> str:
    recent_session_lines = _format_recent_session_messages(participant.get("recentMessages") or [])
    prior_lines = _format_prior_room_messages(prior_messages)
    purpose = _normalize_purpose(round_payload.get("purpose") or room.get("purpose") or DEFAULT_PURPOSE)
    purpose_lines = _purpose_prompt_lines(purpose)
    return "\n".join(
        [
            "你正在参加 Vibelution 的只读 Agent 群聊。",
            f"群聊: {room.get('title') or room.get('roomId')}",
            f"当前议题: {round_payload.get('topic') or ''}",
            f"调度模式: {round_payload.get('mode') or DEFAULT_MODE}",
            f"对话目的: {purpose}",
            f"你的身份: {_participant_speaker_label(participant)}",
            f"来源会话: {participant.get('sessionId') or ''}",
            "",
            "你的会话近况:",
            recent_session_lines or "- 暂无可用会话消息。",
            "",
            "本轮已经出现的群聊发言:",
            prior_lines or "- 你是本轮第一位发言者。",
            "",
            "本轮发言风格:",
            *purpose_lines,
            "",
            "请给出一段紧凑、可读、只读的群聊发言。不要修改文件、不要提交、不要启动进化或部署。",
            "如果你没有新信息，请明确说明你的确认、保留意见或下一步建议。",
        ]
    )


def _purpose_prompt_lines(purpose: str) -> list[str]:
    normalized = _normalize_purpose(purpose)
    if normalized == "chat":
        return [
            "- 像真实群聊一样回应当前用户话题，优先接住上一位发言者，不要写成任务报告。",
            "- 用 1-3 句自然短句表达；除非用户明确要求，不要使用标题、列表、表格或会议纪要格式。",
            "- 如果会话近况与当前话题无关，只保留一句必要背景，不要把旧任务上下文搬进来。",
        ]
    if normalized == "meeting":
        return [
            "- 按会议协作发言：聚焦议题、决策、风险和下一步行动。",
            "- 可以使用简短项目符号，但每条都要服务于结论、责任或待确认事项。",
            "- 明确指出需要谁确认、后续要做什么，避免闲聊式扩散。",
        ]
    return [
        "- 按讨论模式发言：回应前文观点，给出一个清晰立场、补充角度、权衡或反对意见。",
        "- 可以提出建议或分歧，但保持紧凑，不要写成长篇报告。",
        "- 让发言接在上一位之后，避免孤立复述自己的会话近况。",
    ]


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


def _participant_speaker_label(participant: dict[str, Any]) -> str:
    title = str(participant.get("title") or participant.get("participantId") or "").strip()
    code = str(participant.get("agentCode") or "").strip()
    if code and title:
        return f"{code} · {title}"
    return title or code or str(participant.get("participantId") or "").strip()


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


def _resolve_agent_participant(agent_id: str) -> dict[str, Any]:
    lang = get_web_language()
    _sync_agent_directory_project_root()
    normalized_agent_id = str(agent_id or "").strip()
    agent = agent_directory_service.get_agent(normalized_agent_id, include_archived=False)
    if not agent:
        raise ChatRoomValidationError(f"Unknown active agent: {normalized_agent_id}")
    if str(agent.get("kind") or "").strip() != agent_directory_service.DEFAULT_AGENT_KIND:
        raise ChatRoomValidationError(f"Agent is not persistent: {normalized_agent_id}")
    direct_session_id = str(agent.get("directSessionId") or "").strip()
    if not direct_session_id:
        raise ChatRoomValidationError(
            text_for(
                lang,
                zh=f"Agent 没有直连会话: {normalized_agent_id}",
                en=f"Agent has no direct chat session: {normalized_agent_id}",
            )
        )
    return _resolve_participants([direct_session_id])[0]


def _participant_matches_agent(participant: dict[str, Any], agent_id: str, direct_session_id: str) -> bool:
    participant_agent_id = str(participant.get("agentId") or "").strip()
    if participant_agent_id and participant_agent_id == agent_id:
        return True
    if not direct_session_id:
        return False
    participant_session_ids = {
        str(participant.get("sessionId") or "").strip(),
        str(participant.get("directSessionId") or "").strip(),
    }
    return direct_session_id in participant_session_ids


def _dedupe_room_ids(room_ids: list[str] | None) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for room_id in list(room_ids or []):
        normalized = str(room_id or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _participant_from_session(
    summary: dict[str, Any],
    *,
    include_recent_messages: bool = False,
    recent_messages: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    session_id = str(summary.get("id") or "").strip()
    title = str(summary.get("title") or session_id).strip() or session_id
    detail = (session_service.get_session_detail(session_id) or {}) if include_recent_messages else {}
    agent_profile_id = str(summary.get("agentProfileId") or detail.get("agentProfileId") or "primary").strip() or "primary"
    agent_missing = bool(summary.get("agentMissing") or detail.get("agentMissing"))
    agent_status_code = str(summary.get("agentStatusCode") or detail.get("agentStatusCode") or "").strip()
    agent_status_message = str(summary.get("agentStatusMessage") or detail.get("agentStatusMessage") or "").strip()
    return {
        "participantId": f"session-{_safe_fragment(session_id)}",
        "kind": "session_agent",
        "agentId": str(summary.get("agentId") or detail.get("agentId") or "").strip(),
        "agentCode": str(summary.get("agentCode") or detail.get("agentCode") or "").strip(),
        "directSessionId": session_id,
        "sessionId": session_id,
        "title": title,
        "workspacePath": str(summary.get("workspacePath") or detail.get("workspacePath") or ""),
        "agentProfileId": agent_profile_id,
        "agentTemplateId": agent_profile_id,
        "agentTemplateLabel": str(summary.get("agentTemplateLabel") or detail.get("agentTemplateLabel") or agent_profile_id),
        "agentMissing": agent_missing,
        "agentStatusCode": agent_status_code,
        "agentStatusMessage": agent_status_message,
        "enabled": not agent_missing,
        "status": str(summary.get("status") or ""),
        "recentMessages": (
            _compact_messages(detail.get("messages") or [])
            if include_recent_messages
            else list(recent_messages or [])
        ),
    }


def _refresh_participants(
    participants: list[dict[str, Any]],
    *,
    include_recent_messages: bool = False,
    session_summaries: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    refreshed: list[dict[str, Any]] = []
    for item in participants:
        if not isinstance(item, dict):
            continue
        session_id = str(item.get("sessionId") or "").strip()
        summary = _session_summary(session_id, session_summaries=session_summaries)
        if summary:
            participant = _participant_from_session(
                summary,
                include_recent_messages=include_recent_messages,
                recent_messages=list(item.get("recentMessages") or []),
            )
            participant["participantId"] = str(item.get("participantId") or participant["participantId"])
            participant["enabled"] = False if participant.get("agentMissing") else bool(item.get("enabled", True))
            participant["agentId"] = str(item.get("agentId") or participant.get("agentId") or "").strip()
            participant["agentCode"] = str(item.get("agentCode") or participant.get("agentCode") or "").strip()
            participant["directSessionId"] = str(item.get("directSessionId") or participant.get("directSessionId") or participant.get("sessionId") or "").strip()
            refreshed.append(participant)
        else:
            refreshed.append(dict(item))
    return refreshed


def _repair_room_participants_in_state(
    state: dict[str, Any],
    *,
    session_summaries: dict[str, dict[str, Any]] | None = None,
) -> bool:
    changed = False
    for room in list(state.get("rooms") or []):
        if not isinstance(room, dict):
            continue
        participants = list(room.get("participants") or [])
        refreshed = _refresh_participants(participants, session_summaries=session_summaries)
        if refreshed != participants:
            room["participants"] = refreshed
            room["updatedAt"] = utc_now_iso()
            changed = True
    return changed


def _session_summary_index() -> dict[str, dict[str, Any]]:
    return {
        str(item.get("id") or "").strip(): item
        for item in session_service.list_sessions()
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }


def _session_summary(
    session_id: str,
    *,
    session_summaries: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    if session_summaries is not None:
        return session_summaries.get(normalized_session_id)
    for item in session_service.list_sessions():
        if str(item.get("id") or "").strip() == normalized_session_id:
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


def _normalize_purpose(purpose: Any) -> str:
    normalized = str(purpose or DEFAULT_PURPOSE).strip().lower().replace("-", "_")
    allowed = {str(item["id"]) for item in CHAT_ROOM_PURPOSES}
    return normalized if normalized in allowed else DEFAULT_PURPOSE


def _safe_config(config: Any) -> dict[str, Any]:
    return dict(config) if isinstance(config, dict) else {}


def _room_to_api(room: dict[str, Any]) -> dict[str, Any]:
    payload = dict(room)
    payload["mode"] = str(payload.get("mode") or DEFAULT_MODE).strip() or DEFAULT_MODE
    payload["purpose"] = _normalize_purpose(payload.get("purpose") or DEFAULT_PURPOSE)
    payload["participants"] = [dict(item) for item in list(room.get("participants") or []) if isinstance(item, dict)]
    payload["rounds"] = [
        {
            **dict(item),
            "mode": str(dict(item).get("mode") or payload["mode"] or DEFAULT_MODE).strip() or DEFAULT_MODE,
            "purpose": _normalize_purpose(dict(item).get("purpose") or payload["purpose"] or DEFAULT_PURPOSE),
        }
        for item in list(room.get("rounds") or [])
        if isinstance(item, dict)
    ]
    payload["availableModes"] = list_chat_room_modes()
    payload["availablePurposes"] = list_chat_room_purposes()
    return payload


def _store() -> ChatRoomStore:
    return ChatRoomStore(root=PROJECT_ROOT)


def _work_run_store() -> work_run_store.WorkRunStore:
    return work_run_store.WorkRunStore(root=work_run_store.WORK_RUNS_DIR)


def _create_chat_room_round_control(room_id: str, round_id: str) -> None:
    normalized_round_id = str(round_id or "").strip()
    if not normalized_round_id:
        return
    with _CHAT_ROOM_ROUND_CONTROLS_LOCK:
        _CHAT_ROOM_ROUND_CONTROLS[normalized_round_id] = {
            "roomId": str(room_id or "").strip(),
            "roundId": normalized_round_id,
            "stopReason": "",
            "stopRequestedAt": "",
        }


def _request_chat_room_round_stop(round_id: str, reason: str) -> None:
    normalized_round_id = str(round_id or "").strip()
    if not normalized_round_id:
        return
    with _CHAT_ROOM_ROUND_CONTROLS_LOCK:
        control = _CHAT_ROOM_ROUND_CONTROLS.setdefault(
            normalized_round_id,
            {
                "roomId": "",
                "roundId": normalized_round_id,
                "stopReason": "",
                "stopRequestedAt": "",
            },
        )
        control["stopReason"] = str(reason or "").strip()
        control["stopRequestedAt"] = utc_now_iso()


def _chat_room_round_stop_reason(round_id: str) -> str:
    normalized_round_id = str(round_id or "").strip()
    if not normalized_round_id:
        return ""
    with _CHAT_ROOM_ROUND_CONTROLS_LOCK:
        control = _CHAT_ROOM_ROUND_CONTROLS.get(normalized_round_id) or {}
        return str(control.get("stopReason") or "").strip()


def _clear_chat_room_round_control(round_id: str) -> None:
    normalized_round_id = str(round_id or "").strip()
    if not normalized_round_id:
        return
    with _CHAT_ROOM_ROUND_CONTROLS_LOCK:
        _CHAT_ROOM_ROUND_CONTROLS.pop(normalized_round_id, None)


def _chat_room_work_run_snapshot(
    room: dict[str, Any],
    round_payload: dict[str, Any],
    *,
    status: str = "",
) -> dict[str, Any]:
    normalized_status = str(status or round_payload.get("status") or "running").strip().lower()
    return {
        "runId": str(round_payload.get("roundId") or "").strip(),
        "runKind": RUN_KIND,
        "track": "dialogue",
        "roomId": str(room.get("roomId") or "").strip(),
        "roundId": str(round_payload.get("roundId") or "").strip(),
        "status": normalized_status,
        "currentPhase": normalized_status,
        "leases": list(RUN_LEASES),
        "topic": str(round_payload.get("topic") or "").strip(),
        "mode": str(round_payload.get("mode") or DEFAULT_MODE).strip(),
        "purpose": _normalize_purpose(round_payload.get("purpose") or room.get("purpose") or DEFAULT_PURPOSE),
        "summary": str(round_payload.get("summary") or "").strip(),
        "startedAt": str(round_payload.get("startedAt") or "").strip(),
        "updatedAt": str(round_payload.get("updatedAt") or "").strip(),
        "finishedAt": str(round_payload.get("finishedAt") or "").strip(),
    }


def _stopped_round_summary(reason: str, *, message_count: int, speaker_count: int) -> str:
    return text_for(
        get_web_language(),
        zh=f"群聊轮次已停止：{message_count}/{speaker_count} 位 Agent 已发言。{reason}".strip(),
        en=f"Chat room round stopped: {message_count}/{speaker_count} agents responded. {reason}".strip(),
    )


def _chat_room_round_is_terminal(room: dict[str, Any], round_payload: dict[str, Any], round_id: str) -> bool:
    normalized_round_id = str(round_id or "").strip()
    status = str(round_payload.get("status") or "").strip().lower()
    if status and status not in RUNNING_ROUND_STATUSES:
        return True
    active_round_id = str(room.get("activeRoundId") or "").strip()
    return bool(active_round_id and normalized_round_id and active_round_id != normalized_round_id)


def _stopped_chat_room_round_detail(room_id: str, round_id: str) -> dict[str, Any] | None:
    stop_reason = _chat_room_round_stop_reason(round_id)
    if not stop_reason:
        return None
    stopped_at = utc_now_iso()
    changed = False
    with _CHAT_ROOM_LOCK:
        state = _store().load()
        room = _find_room(state, room_id)
        if room is None:
            return None
        target_round = _find_round(room, round_id)
        if target_round is None:
            return None
        if str(target_round.get("status") or "").strip().lower() in RUNNING_ROUND_STATUSES:
            target_round["status"] = "stopped"
            target_round["summary"] = _stopped_round_summary(
                stop_reason,
                message_count=len(list(target_round.get("messages") or [])),
                speaker_count=len(list(target_round.get("speakerOrder") or [])),
            )
            target_round["updatedAt"] = stopped_at
            target_round["finishedAt"] = stopped_at
            room["status"] = "ready"
            if str(room.get("activeRoundId") or "").strip() == str(round_id or "").strip():
                room["activeRoundId"] = ""
            room["updatedAt"] = stopped_at
            _store().save(state)
            changed = True
    if changed:
        _persist_chat_room_work_run(room, target_round, status="stopped", summary=str(target_round.get("summary") or ""))
        _record_room_event(
            "round",
            "chat_room.round.stopped",
            room,
            target_round,
            fields={"reason": trim_lines(stop_reason, max_lines=2)},
            outcome="stopped",
            lifecycle=True,
        )
        _publish_chat_room_detail_snapshot(room_id)
    return _room_to_api(room)


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
        "purpose": _normalize_purpose(round_payload.get("purpose") or room.get("purpose") or DEFAULT_PURPOSE),
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
        "purpose": _normalize_purpose(room.get("purpose") or DEFAULT_PURPOSE),
    }
    if round_payload:
        event_fields.update(
            {
                "roundId": str(round_payload.get("roundId") or "").strip(),
                "topicLength": len(str(round_payload.get("topic") or "")),
                "purpose": _normalize_purpose(round_payload.get("purpose") or room.get("purpose") or DEFAULT_PURPOSE),
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


def _fail_chat_room_round(
    room_id: str,
    round_id: str,
    room: dict[str, Any],
    round_payload: dict[str, Any],
    exc: Exception,
    *,
    lang: str,
) -> None:
    _clear_chat_room_round_control(round_id)
    failed_at = utc_now_iso()
    summary = text_for(
        lang,
        zh=f"群聊后台轮次失败：{type(exc).__name__}: {exc}",
        en=f"Chat room background round failed: {type(exc).__name__}: {exc}",
    )
    with _CHAT_ROOM_LOCK:
        state = _store().load()
        live_room = _find_room(state, room_id)
        if live_room is None:
            live_room = room
        target_round = _find_round(live_room, round_id) if isinstance(live_room, dict) else None
        if target_round is None:
            target_round = round_payload
        if str(target_round.get("status") or "").strip().lower() not in RUNNING_ROUND_STATUSES:
            _publish_chat_room_detail_snapshot(room_id)
            return
        target_round["status"] = "failed"
        target_round["summary"] = summary
        target_round["updatedAt"] = failed_at
        target_round["finishedAt"] = failed_at
        live_room["status"] = "failed"
        live_room["activeRoundId"] = ""
        live_room["updatedAt"] = failed_at
        if _find_room(state, room_id) is not None:
            _store().save(state)

    _persist_chat_room_work_run(live_room, target_round, status="failed", summary=summary)
    _record_room_event(
        "round",
        "chat_room.round.background_failed",
        live_room,
        target_round,
        fields={
            "errorType": type(exc).__name__,
            "errorPreview": trim_lines(str(exc), max_lines=2),
        },
        outcome="failed",
        level="error",
        lifecycle=True,
    )
    _publish_chat_room_detail_snapshot(room_id)


def _register_chat_room_stream_subscriber(room_id: str, subscriber: queue.Queue[dict[str, Any]]) -> None:
    with _CHAT_ROOM_STREAM_SUBSCRIBERS_LOCK:
        bucket = _CHAT_ROOM_STREAM_SUBSCRIBERS.setdefault(room_id, set())
        bucket.add(subscriber)


def _unregister_chat_room_stream_subscriber(room_id: str, subscriber: queue.Queue[dict[str, Any]]) -> None:
    with _CHAT_ROOM_STREAM_SUBSCRIBERS_LOCK:
        bucket = _CHAT_ROOM_STREAM_SUBSCRIBERS.get(room_id)
        if not bucket:
            return
        bucket.discard(subscriber)
        if not bucket:
            _CHAT_ROOM_STREAM_SUBSCRIBERS.pop(room_id, None)


def _publish_chat_room_detail_snapshot(room_id: str) -> None:
    normalized_room_id = str(room_id or "").strip()
    if not normalized_room_id:
        return
    detail = get_chat_room_detail(normalized_room_id)
    if detail is None:
        return
    event = {
        "type": "chat_room_detail",
        "roomId": normalized_room_id,
        "detail": detail,
    }
    with _CHAT_ROOM_STREAM_SUBSCRIBERS_LOCK:
        subscribers = list(_CHAT_ROOM_STREAM_SUBSCRIBERS.get(normalized_room_id) or [])
    for subscriber in subscribers:
        try:
            subscriber.put_nowait(event)
        except queue.Full:
            try:
                subscriber.get_nowait()
            except queue.Empty:
                pass
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                continue


def _encode_chat_room_sse_event(event_name: str, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False)
    return f"event: {event_name}\ndata: {body}\n\n"


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
