"""Team membership and contract shared helpers.

Claim scope: active-member agent/session resolution, cross-team agent lookup,
and teamKind/source contract application.
Late-binds ``team_service`` for kind helpers and defaults.
"""

from __future__ import annotations

from typing import Any

from core.chat.chat_task_types import trim_lines


def _service():
    from core.web.services import team_service

    return team_service


def _find_active_team_for_agent(agent_id: str, *, excluding_team_id: str = "") -> dict[str, Any] | None:
    s = _service()
    state = s._load_index()
    return s._find_active_team_for_agent_in_state(state, agent_id, excluding_team_id=excluding_team_id)


def _find_active_team_for_agent_in_state(state: dict[str, Any], agent_id: str, *, excluding_team_id: str = "") -> dict[str, Any] | None:
    s = _service()
    normalized_agent_id = str(agent_id or "").strip()
    normalized_excluding_team_id = str(excluding_team_id or "").strip()
    if not normalized_agent_id:
        return None
    for team in list(state.get("teams") or []):
        if not isinstance(team, dict):
            continue
        team_id = str(team.get("teamId") or "").strip()
        if team_id == normalized_excluding_team_id:
            continue
        if str(team.get("status") or s.DEFAULT_TEAM_STATUS).strip() == "archived":
            continue
        for member in list(team.get("members") or []):
            if isinstance(member, dict) and str(member.get("agentId") or "").strip() == normalized_agent_id:
                return team
    return None


def _unique_active_member_agent_ids(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> list[str]:
    s = _service()
    agent_ids: list[str] = []
    seen: set[str] = set()
    for member in list(team.get("members") or []):
        if not isinstance(member, dict):
            continue
        agent_id = str(member.get("agentId") or "").strip()
        if not agent_id or agent_id in seen:
            continue
        agent = s._agent_reference(agent_id, include_archived=True, agent_refs=agent_refs)
        if not agent or str(agent.get("status") or "active").strip() == "archived":
            continue
        seen.add(agent_id)
        agent_ids.append(agent_id)
    return agent_ids


def _active_member_agent_ids(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> list[str]:
    s = _service()
    ids: list[str] = []
    seen: set[str] = set()
    for member in list(team.get("members") or []):
        if not isinstance(member, dict):
            continue
        agent_id = str(member.get("agentId") or "").strip()
        if not agent_id or agent_id in seen:
            continue
        if not s._agent_reference(agent_id, include_archived=False, agent_refs=agent_refs):
            continue
        seen.add(agent_id)
        ids.append(agent_id)
    return ids


def _active_member_session_ids(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> list[str]:
    s = _service()
    session_ids: list[str] = []
    seen: set[str] = set()
    for agent_id in s._active_member_agent_ids(team, agent_refs=agent_refs):
        agent = s._agent_reference(agent_id, include_archived=False, agent_refs=agent_refs)
        session_id = str((agent or {}).get("directSessionId") or "").strip()
        if not session_id or session_id in seen:
            continue
        seen.add(session_id)
        session_ids.append(session_id)
    return session_ids


def _member_direct_session_kind(agent: dict[str, Any] | None) -> str:
    from core.web.services import agent_directory_service

    raw = str((agent or {}).get("conversationIndexKind") or "").strip()
    if raw == agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT:
        return raw
    return agent_directory_service.CONVERSATION_INDEX_KIND_PERSONAL_AGENT


def _ensure_active_member_direct_sessions(team: dict[str, Any]) -> dict[str, Any]:
    """Create missing member direct sessions without changing existing kind."""

    from core.web.services import session_service

    s = _service()
    created: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []
    for agent_id in s._active_member_agent_ids(team):
        agent = s._agent_reference(agent_id, include_archived=False)
        if not agent:
            continue
        current_session_id = str(agent.get("directSessionId") or "").strip()
        if current_session_id:
            continue
        kind = s._member_direct_session_kind(agent)
        try:
            session = session_service.ensure_agent_direct_session(
                agent_id=agent_id,
                title=str(agent.get("displayName") or "").strip(),
                created_by="team_member_direct_session",
                conversation_index_kind=kind,
            )
            created.append(
                {
                    "agentId": agent_id,
                    "sessionId": str(session.get("id") or "").strip(),
                    "conversationIndexKind": kind,
                }
            )
        except Exception as exc:
            failed.append({"agentId": agent_id, "error": type(exc).__name__, "message": str(exc)[:240]})
            s._record_team_event(
                "team.member.direct_session.failed",
                team,
                fields={
                    "agentId": agent_id,
                    "error": type(exc).__name__,
                    "message": str(exc)[:240],
                },
            )
    if created:
        s._record_team_event(
            "team.member.direct_session.ensured",
            team,
            fields={
                "createdCount": len(created),
                "createdAgentIds": [item["agentId"] for item in created],
                "failedCount": len(failed),
            },
        )
    return {"created": created, "failed": failed}


def build_team_roster_context_lines(agent_id: str, *, limit: int = 12) -> list[str]:
    """Read-only same-team roster for Runtime Context. Never creates sessions."""

    s = _service()
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        return ["TeamRoster: none"]
    team = s._find_active_team_for_agent(normalized_agent_id)
    if not team:
        return ["TeamRoster: none"]
    try:
        capped = max(1, min(int(limit or 12), 16))
    except (TypeError, ValueError):
        capped = 12
    lines = [
        f"TeamRoster: teamId={team.get('teamId') or ''} name={trim_lines(str(team.get('name') or ''), max_lines=1)}",
        "- Same-team peers only. Send with agent_message_tool and explicit target_session. Do not invent sessions.",
    ]
    members = [item for item in list(team.get("members") or []) if isinstance(item, dict)]
    rendered = 0
    for member in members:
        if rendered >= capped:
            break
        member_agent_id = str(member.get("agentId") or "").strip()
        if not member_agent_id:
            continue
        agent = s._agent_reference(member_agent_id, include_archived=False)
        if not agent:
            continue
        session_id = str(agent.get("directSessionId") or "").strip()
        address = session_id or "unaddressable"
        responsibilities = [
            trim_lines(str(item or ""), max_lines=1).strip()
            for item in list(member.get("responsibilities") or [])[:2]
            if str(item or "").strip()
        ]
        if not responsibilities:
            task_profile = agent.get("taskProfile") if isinstance(agent.get("taskProfile"), dict) else {}
            raw_responsibilities = task_profile.get("responsibilities")
            if isinstance(raw_responsibilities, str) and raw_responsibilities.strip():
                responsibilities = [trim_lines(raw_responsibilities, max_lines=1).strip()]
            elif isinstance(raw_responsibilities, list):
                responsibilities = [
                    trim_lines(str(item or ""), max_lines=1).strip()
                    for item in raw_responsibilities[:2]
                    if str(item or "").strip()
                ]
        marker = "you" if member_agent_id == normalized_agent_id else "peer"
        lines.append(
            "- "
            + " ".join(
                part
                for part in [
                    f"{marker}:",
                    f"name={trim_lines(str(agent.get('displayName') or member.get('agentName') or ''), max_lines=1)}",
                    f"role={trim_lines(str(member.get('role') or ''), max_lines=1) or '-'}",
                    f"agentId={member_agent_id}",
                    f"agentCode={str(agent.get('agentCode') or member.get('agentCode') or '').strip()}",
                    f"directSessionId={address}",
                    f"status={str(agent.get('status') or member.get('agentStatus') or 'active').strip()}",
                ]
                if part
            )
        )
        purpose = trim_lines(str(member.get("purpose") or ""), max_lines=2).strip()
        if purpose:
            lines.append(f"  purpose: {purpose}")
        if responsibilities:
            lines.append(f"  responsibilities: {'; '.join(responsibilities)}")
        rendered += 1
    if rendered == 0:
        lines.append("- members: none")
    return lines


def _apply_team_contract(
    team: dict[str, Any],
    *,
    team_kind: str = "",
    team_category: str = "",
    team_source: str = "",
    team_template_id: str = "",
) -> bool:
    s = _service()
    inferred_kind = s._infer_team_kind(team, fallback=team_kind)
    defaults = s.TEAM_KIND_DEFAULTS.get(inferred_kind, s.TEAM_KIND_DEFAULTS["custom"])
    expected = {
        "teamKind": inferred_kind,
        "teamCategory": trim_lines(team_category or team.get("teamCategory") or defaults["teamCategory"], max_lines=1).strip(),
        "teamSource": str(team_source or team.get("teamSource") or defaults["teamSource"]).strip(),
        "teamTemplateId": str(team_template_id or team.get("teamTemplateId") or "").strip(),
    }
    if expected["teamSource"] in s.TEAM_SOURCE_TO_KIND:
        expected["teamKind"] = s.TEAM_SOURCE_TO_KIND[expected["teamSource"]]
    if expected["teamKind"] != "template_demo":
        expected["teamTemplateId"] = ""
    elif not expected["teamTemplateId"]:
        expected["teamTemplateId"] = s._infer_team_template_id(team)
    changed = False
    for key, value in expected.items():
        if team.get(key) != value:
            team[key] = value
            changed = True
    return changed
