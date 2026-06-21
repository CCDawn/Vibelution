from pathlib import Path

from core.chat.conversation_ledger import (
    EVENT_ASSISTANT_MESSAGE,
    EVENT_TOOL_RESULT,
    EVENT_USER_MESSAGE,
    append_conversation_event,
)
from core.evaluation.chat_next_state_signals import list_chat_next_state_signals
from core.ui.chat_state import load_chat_state, save_chat_state
from core.web.services import session_service


def _seed_chat_state(project_root, *, task_status="reading", active_task=None, conversations=None):
    seeded_conversations = conversations
    if seeded_conversations is None:
        seeded_conversations = [
            {
                "conversation_id": "session-live",
                "title": "真实会话",
                "updated_at": "2026-05-18T12:00:00",
                "last_turn_status": "failed" if task_status == "failed" else "ready",
                "active_task": active_task,
                "messages": [
                    {
                        "role": "user",
                        "content": "继续前端开发",
                        "timestamp": "2026-05-18T11:55:00",
                    },
                    {
                        "role": "assistant",
                        "content": "<think>internal</think>\n\n已经接到真实状态了。",
                        "timestamp": "2026-05-18T11:56:00",
                        "tool_calls": [
                            {"name": "read_file_tool"},
                            {"function": {"name": "search_code_tool"}},
                        ],
                    },
                ],
            }
        ]
    persisted_conversations = []
    for conversation in seeded_conversations:
        if not isinstance(conversation, dict):
            persisted_conversations.append(conversation)
            continue
        prepared = dict(conversation)
        conversation_id = str(
            prepared.get("conversation_id")
            or prepared.get("conversationId")
            or prepared.get("id")
            or ""
        ).strip()
        _reset_seeded_session_runtime(conversation_id)
        for index, message in enumerate(list(prepared.get("messages") or []), start=1):
            _append_seed_message_to_ledger(project_root, conversation_id, index, message)
        prepared.pop("messages", None)
        persisted_conversations.append(prepared)
    save_chat_state(
        project_root,
        {
            "version": 1,
            "active_conversation_id": "session-live",
            "updated_at": "2026-05-18T12:00:00",
            "conversations": persisted_conversations,
        },
    )
    session_service._invalidate_session_list_cache()


def _reset_seeded_session_runtime(conversation_id: str) -> None:
    if not conversation_id:
        return
    with session_service._RUNNING_SESSIONS_LOCK:
        session_service._RUNNING_SESSION_IDS.discard(conversation_id)
        session_service._SESSION_ACTIVE_TURN_IDS.pop(conversation_id, None)
        session_service._SESSION_ACTIVE_TURN_LEASES.pop(conversation_id, None)
    with session_service._SESSION_TURN_CONTROLS_LOCK:
        session_service._SESSION_TURN_CONTROLS.pop(conversation_id, None)
    with session_service._SESSION_LIVE_OUTPUTS_LOCK:
        session_service._SESSION_LIVE_OUTPUTS.pop(conversation_id, None)
    with session_service._SESSION_LIVE_OUTPUT_CHECKPOINT_LOCK:
        session_service._SESSION_LIVE_OUTPUT_CHECKPOINT_LAST_AT.pop(conversation_id, None)
    with session_service._SESSION_STREAM_LAST_SNAPSHOT_LOCK:
        session_service._SESSION_STREAM_LAST_SNAPSHOT_AT.pop(conversation_id, None)
        session_service._SESSION_STREAM_THROTTLED_COUNTS.pop(conversation_id, None)


def _append_seed_message_to_ledger(project_root: Path, conversation_id: str, index: int, message: dict) -> None:
    if not conversation_id or not isinstance(message, dict):
        return
    role = str(message.get("role") or "").strip().lower()
    turn_id = f"{conversation_id}-seed-{index:03d}"
    timestamp = str(message.get("timestamp") or "").strip()
    if role == "user":
        append_conversation_event(
            project_root,
            conversation_id,
            turn_id,
            EVENT_USER_MESSAGE,
            status="recorded",
            payload={
                "content": message.get("content") or "",
                "attachments": list(message.get("attachments") or []),
                "metadata": dict(message.get("metadata") or {}) if isinstance(message.get("metadata"), dict) else {},
            },
            timestamp=timestamp,
        )
        return
    if role == "assistant":
        mental_snapshot = message.get("mentalSnapshot") or message.get("mental_snapshot")
        append_conversation_event(
            project_root,
            conversation_id,
            turn_id,
            EVENT_ASSISTANT_MESSAGE,
            status="completed",
            payload={
                "content": message.get("content") or "",
                "thought": message.get("thought") or "",
                "toolCalls": list(message.get("toolCalls") or message.get("tool_calls") or []),
                "feedbackEvents": list(message.get("feedbackEvents") or message.get("feedback_events") or []),
                "mentalSnapshot": dict(mental_snapshot) if isinstance(mental_snapshot, dict) else None,
                "metadata": dict(message.get("metadata") or {}) if isinstance(message.get("metadata"), dict) else {},
            },
            timestamp=timestamp,
        )
        return
    if role == "tool":
        metadata = dict(message.get("metadata") or {}) if isinstance(message.get("metadata"), dict) else {}
        tool_call_id = str(message.get("tool_call_id") or message.get("toolCallId") or metadata.get("toolCallId") or "").strip()
        append_conversation_event(
            project_root,
            conversation_id,
            turn_id,
            EVENT_TOOL_RESULT,
            status=str(metadata.get("status") or metadata.get("toolStatus") or "done").strip() or "done",
            payload={
                "toolCall": {
                    "id": tool_call_id,
                    "name": str(metadata.get("toolName") or metadata.get("tool_name") or "tool").strip() or "tool",
                    "result": message.get("content") or "",
                }
            },
            timestamp=timestamp,
            tool_call_id=tool_call_id,
        )


def _bind_seeded_session_agent(project_root: Path, agent: dict, *, session_id: str = "session-live") -> None:
    state = load_chat_state(project_root)
    agent_id = str(agent.get("agentId") or "").strip()
    for conversation in state.get("conversations") or []:
        if str(conversation.get("conversation_id") or "").strip() == session_id:
            conversation["agent_id"] = agent_id
            conversation["agentId"] = agent_id
            break
    save_chat_state(project_root, state)
def _read_next_state_signals(project_root: Path, *, session_id: str = "", turn_id: str = "") -> list[dict]:
    return list_chat_next_state_signals(project_root=project_root, session_id=session_id, turn_id=turn_id)
