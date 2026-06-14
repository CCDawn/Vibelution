from pathlib import Path

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
    save_chat_state(
        project_root,
        {
            "version": 1,
            "active_conversation_id": "session-live",
            "updated_at": "2026-05-18T12:00:00",
            "conversations": seeded_conversations,
        },
    )
    session_service._invalidate_session_list_cache()
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
