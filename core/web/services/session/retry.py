"""Native failed-turn CAS retry. Journal remains the sole acceptance receipt."""

from __future__ import annotations

import json
from typing import Any

from core.agent_plugins.virtual_human_life.storage import VirtualHumanLifeStore
from core.chat.conversation_branches import analyze_conversation_branches, resolve_active_user_node_id
from core.chat.turn_journal import TERMINAL_EVENTS, fold_active_events, latest_open_turn_id
from core.infrastructure import developer_sandbox

from . import journal_bridge
from .admission_lock import session_has_active_work_run
from .queued_turns import session_queued_turn_rows


def retry_session_message(
    session_id: str, *, client_submission_id: str, expected_turn_id: str,
    expected_head_id: str, expected_ledger_seq: int, expected_agent_id: str,
    base_message_id: str,
) -> dict[str, Any]:
    """Retry exactly this failed snapshot; never supersede a newer turn."""
    from core.web.services import session_service as s
    from .submit import _resubmit_session_user_message

    values = (client_submission_id, expected_turn_id, expected_head_id, expected_agent_id, base_message_id)
    if (any(not isinstance(value, str) or not value.strip() for value in values)
            or len(client_submission_id) > 128
            or isinstance(expected_ledger_seq, bool) or not isinstance(expected_ledger_seq, int)
            or expected_ledger_seq < 1):
        raise s.SessionValidationError("安全重试需要完整的会话快照与固定提交标识。")
    expected = {
        "turnId": expected_turn_id.strip(), "headId": expected_head_id.strip(),
        "ledgerSeq": expected_ledger_seq, "agentId": expected_agent_id.strip(),
    }
    return _resubmit_session_user_message(
        session_id, "", content="", content_utf8_base64="",
        mental_model_enabled=None, runtime_status_enabled=None, turn_status_tail=None,
        client_submission_id=client_submission_id.strip(), turn_mode="", write_intent=None,
        trace_context_carrier=None, operation="regenerate", base_message_id=base_message_id,
        _safe_retry_expected=expected,
    )


def _conflict(s):
    raise s.SessionBusyError("会话已推进或当前状态不能安全重试，请刷新后重试。")


def _ensure_ordinary_owner(s, conversation: dict, expected: dict) -> None:
    owners = [conversation[key] for key in ("agent_id", "agentId") if conversation.get(key)]
    if not owners or any(owner != expected["agentId"] for owner in owners):
        _conflict(s)
    # Directory convenience APIs can repair state. Rejection must remain read-only.
    directory = s.agent_directory_service
    try:
        with directory.scoped_project_root(s.PROJECT_ROOT):
            path = directory._workspace_path("agents", "agents.json", intent="state", seed=False)
            agents = json.loads(path.read_text(encoding="utf-8")).get("agents") or []
        matches = [agent for agent in agents if isinstance(agent, dict) and agent.get("agentId") == expected["agentId"]]
        if len(matches) != 1 or matches[0].get("status") == "archived":
            _conflict(s)
        metadata = matches[0].get("metadata") or {}
        plugin = VirtualHumanLifeStore(s.PROJECT_ROOT, plugin_root_resolver=lambda agent_id:
            developer_sandbox.route_workspace_path(s.PROJECT_ROOT, "agent_directory", "agents", agent_id,
                "plugins", "virtual-human-life", intent="state", seed=False))
        binding = plugin.read_json(expected["agentId"], "binding.json") or {}
        if (metadata.get("virtualHumanCompanion") is True or metadata.get("virtualHumanSelfWake") is True
                or metadata.get("lifeStewardForAgentId") or binding.get("enabled") is True):
            _conflict(s)
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise s.SessionBusyError("无法确认普通Session身份，请刷新后重试。") from exc



def validate_safe_retry(s, session_id: str, conversation: dict, expected: dict, base_message_id: str) -> None:
    """Caller holds admission then CHAT_STATE_LOCK through acceptance preparation."""
    _ensure_ordinary_owner(s, conversation, expected)
    events = journal_bridge.load_session_conversation_events_snapshot(session_id, project_root=s.PROJECT_ROOT)
    if (not events or events[-1].sequence != expected["ledgerSeq"]
            or s._is_session_running(session_id) or latest_open_turn_id(events)
            or session_queued_turn_rows(conversation)
            or session_has_active_work_run(s, session_id, expected["turnId"])):
        _conflict(s)
    view = analyze_conversation_branches(events)
    target = resolve_active_user_node_id(view, base_message_id)
    if view.active_leaf_id != expected["headId"] or not target:
        _conflict(s)
    active = fold_active_events(events)
    terminals = [event for event in active if event.event_type in TERMINAL_EVENTS]
    if (not terminals or terminals[-1].event_type != "turn_failed"
            or terminals[-1].turn_id != expected["turnId"]):
        _conflict(s)
    users = [event for event in active if event.event_type == "user_message"
             and (event.payload.get("metadata") or {}).get("kind") not in {"user_guidance", "user_interrupt_guidance"}]
    if not users or users[-1].turn_id != expected["turnId"]:
        _conflict(s)
    # Startup-resume children must prove their ancestry back to a real user request.
    cursor = users[-1]
    seen = set()
    while (cursor.payload.get("metadata") or {}).get("kind") == "hot_restart_resume":
        metadata = cursor.payload.get("metadata") or {}
        parent_id = metadata.get("recoveredTurnId")
        if (cursor.turn_id in seen or len(seen) >= 32 or cursor.payload.get("source") != "hot_restart_resume"
                or metadata.get("recoverySource") != "startup_sweep"
                or cursor.correlation_id != f"resume:{parent_id}"):
            _conflict(s)
        seen.add(cursor.turn_id)
        predecessors = [event for event in users if event.turn_id == parent_id and event.sequence < cursor.sequence]
        index = users.index(cursor)
        if (len(predecessors) != 1 or index < 1 or users[index - 1] != predecessors[0]
                or any(event.turn_id == parent_id and event.event_type != "turn_interrupted" for event in terminals)):
            _conflict(s)
        cursor = predecessors[0]
    if view.nodes[target].event_id != cursor.event_id:
        _conflict(s)


def with_retry_receipt(s, session_id: str, detail: dict, submission_id: str) -> dict:
    events = journal_bridge.load_session_conversation_events_by_correlation(
        session_id, event_type=s.EVENT_USER_MESSAGE, correlation_id=submission_id, project_root=s.PROJECT_ROOT)
    event = events[-1]
    return {**detail, "retryReceipt": {"clientSubmissionId": submission_id,
        "turnId": event.turn_id, "journalEventId": event.event_id, "journalSequence": event.sequence}}
