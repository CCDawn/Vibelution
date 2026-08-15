"""Same-team point-to-point delivery index.

Claim scope: record/list member-to-member collaboration deliveries for a Team.
Index only — no second message body. Late-binds ``team_service``.
"""

from __future__ import annotations

import json
from typing import Any

from core.chat.chat_task_types import trim_lines
from core.logging import debug as _debug_logger


def _service():
    from core.web.services import team_service

    return team_service


def shared_active_team_for_agents(source_agent_id: str, target_agent_id: str) -> dict[str, Any] | None:
    s = _service()
    source_id = str(source_agent_id or "").strip()
    target_id = str(target_agent_id or "").strip()
    if not source_id or not target_id:
        return None
    source_team = s._find_active_team_for_agent(source_id)
    if not source_team:
        return None
    target_team = s._find_active_team_for_agent(target_id)
    if not target_team:
        return None
    if str(source_team.get("teamId") or "").strip() != str(target_team.get("teamId") or "").strip():
        return None
    return source_team


def _member_messages_path(team_id: str):
    s = _service()
    normalized = s._normalize_required_id(team_id, "Team id is required.")
    return s._teams_root() / s._safe_token(normalized, default="team", max_length=96) / "member_messages.jsonl"


def record_team_member_message(
    team_id: str,
    *,
    message_id: str,
    source_agent_id: str,
    source_agent_name: str = "",
    target_agent_id: str,
    target_agent_name: str = "",
    target_session_id: str,
    summary: str = "",
    created_at: str = "",
) -> dict[str, Any]:
    s = _service()
    team = s._get_team_record(team_id)
    entry = {
        "messageId": str(message_id or "").strip(),
        "teamId": str(team.get("teamId") or "").strip(),
        "sourceAgentId": str(source_agent_id or "").strip(),
        "sourceAgentName": trim_lines(source_agent_name or "", max_lines=1).strip(),
        "targetAgentId": str(target_agent_id or "").strip(),
        "targetAgentName": trim_lines(target_agent_name or "", max_lines=1).strip(),
        "targetSessionId": str(target_session_id or "").strip(),
        "summary": trim_lines(summary or "", max_lines=4).strip(),
        "createdAt": str(created_at or s.utc_now_iso()).strip(),
    }
    path = _member_messages_path(entry["teamId"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def list_team_member_messages(team_id: str, *, limit: int = 40) -> dict[str, Any]:
    s = _service()
    team = s._get_team_record(team_id)
    try:
        capped = max(1, min(int(limit or 40), 120))
    except (TypeError, ValueError):
        capped = 40
    path = _member_messages_path(str(team.get("teamId") or ""))
    items: list[dict[str, Any]] = []
    if path.exists():
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except OSError as exc:
            _debug_logger.warning(f"Failed to read team member messages. path={path} error={exc}")
            lines = []
        for raw in reversed(lines):
            if len(items) >= capped:
                break
            text = str(raw or "").strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            items.append(
                {
                    "messageId": str(payload.get("messageId") or "").strip(),
                    "teamId": str(payload.get("teamId") or team.get("teamId") or "").strip(),
                    "sourceAgentId": str(payload.get("sourceAgentId") or "").strip(),
                    "sourceAgentName": str(payload.get("sourceAgentName") or "").strip(),
                    "targetAgentId": str(payload.get("targetAgentId") or "").strip(),
                    "targetAgentName": str(payload.get("targetAgentName") or "").strip(),
                    "targetSessionId": str(payload.get("targetSessionId") or "").strip(),
                    "summary": str(payload.get("summary") or "").strip(),
                    "createdAt": str(payload.get("createdAt") or "").strip(),
                }
            )
    return {
        "teamId": str(team.get("teamId") or "").strip(),
        "teamName": str(team.get("name") or "").strip(),
        "messages": items,
    }
