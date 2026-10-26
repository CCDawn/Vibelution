"""Pure Team/room directory projections; never repair or hydrate their members."""
from __future__ import annotations

import json
import re
import unicodedata

from core.infrastructure.developer_sandbox import formal_workspace_path
from core.infrastructure.tool_result import project_tool_result_for_model
from core.web.services.team.kind_helpers import (
    TEAM_KIND_DEFAULTS, TEAM_SOURCE_TO_KIND, team_is_system_managed,
)

from .service import ManagementError
from .state_snapshot import ExistingStateSnapshot


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")
_OWNED_SOURCE = re.compile(r"(?:external_team|personal_assistant_action):[a-f0-9]{40}\Z")
_PRIVATE_FLAGS = ("internal", "system", "systemManaged", "protected", "hidden", "hiddenFromIndex",
                  "virtualHumanCompanion", "virtualHumanSelfWake", "personalAssistantProfile",
                  "lifeStewardForAgentId", "companion", "systemRole", "researchOrgRole")
_BOOLEAN_FLAGS = {"internal", "system", "systemManaged", "protected", "hidden", "hiddenFromIndex"}
_ROOM_PURPOSES = {"chat", "discussion", "meeting", "medical_triage"}
_SYSTEM_PURPOSES = {"research_coordination", "knowledge_expansion", "ai_search", "self_evolution", "supervised_evolution"}
_SYSTEM_ROOM_SOURCES = {"challenge_workflow", "hypothesis_first_candidate_review.v1",
                        "hypothesis_first_candidate_generation.v1"}


def _identity(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("Invalid directory identity")
    if json.loads(project_tool_result_for_model(json.dumps({"value": value})))["value"] != value:
        raise ValueError("Unrepresentable directory identity")
    return value


def _text(value, limit):
    if not isinstance(value, str):
        raise ValueError("Invalid directory text")
    # Apply the native safety projection both before and after truncation.
    def clean(text):
        projected = json.loads(project_tool_result_for_model(json.dumps({"value": text}, ensure_ascii=False)))["value"]
        return "".join(char for char in projected if unicodedata.category(char) not in {"Cc", "Cf"}).strip()
    return clean(clean(value)[:limit])


def _private(record):
    private = False
    for key in _PRIVATE_FLAGS:
        if key in record:
            value = record[key]
            if (key in _BOOLEAN_FLAGS and type(value) is not bool
                or key not in _BOOLEAN_FLAGS and type(value) is not bool and not isinstance(value, str) and value is not None):
                raise ValueError("Invalid visibility marker")
            private = private or bool(value)
    for key in ("visibility", "conversationIndexVisibility", "conversation_index_visibility"):
        if key in record:
            if record[key] not in {"user_visible", "public", "default", "hidden", "internal", "private"}:
                raise ValueError("Unknown directory visibility")
            private = private or record[key] in {"hidden", "internal", "private"}
    metadata = record.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("Invalid directory metadata")
    if metadata:
        # Markers may be stored in metadata; do not interpret arbitrary content.
        private = _private({key: value for key, value in metadata.items() if key != "metadata"}) or private
    return private


def _rows(snapshot, path, field):
    rows = snapshot.read_json(path, strict=True).get(field)
    if not isinstance(rows, list) or len(rows) > 100_000 or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Invalid directory authority")
    return rows


def _team_classification(record):
    kind, source, legacy = (record.get(key, "") for key in ("teamKind", "teamSource", "systemTeamKind"))
    if not isinstance(kind, str) or kind and kind not in TEAM_KIND_DEFAULTS:
        raise ValueError("Unknown Team kind")
    if not isinstance(source, str) or source and source not in TEAM_SOURCE_TO_KIND and not _OWNED_SOURCE.fullmatch(source):
        raise ValueError("Unknown Team source")
    if not isinstance(legacy, str) or legacy and legacy not in TEAM_KIND_DEFAULTS and legacy not in TEAM_SOURCE_TO_KIND:
        raise ValueError("Unknown legacy Team kind")
    inferred = [value for value in (kind, TEAM_SOURCE_TO_KIND.get(source),
                "template_demo" if _OWNED_SOURCE.fullmatch(source) else "",
                TEAM_SOURCE_TO_KIND.get(legacy, legacy)) if value]
    if len(set(inferred)) > 1:
        raise ValueError("Conflicting Team classification")
    return inferred[0] if inferred else ""


def _teams(snapshot):
    result = {}
    for row in _rows(snapshot, snapshot.path("teams", "teams.json"), "teams"):
        tid = _identity(row.get("teamId"))
        if tid in result or "id" in row and row["id"] != tid or "team_id" in row and row["team_id"] != tid:
            raise ValueError("Ambiguous Team identity")
        if row.get("status") not in {"active", "archived"}:
            raise ValueError("Unknown Team status")
        if "archived" in row and (type(row["archived"]) is not bool or row["archived"] != (row["status"] == "archived")):
            raise ValueError("Conflicting Team archive marker")
        kind, source = row.get("teamKind", ""), row.get("teamSource", "")
        legacy = row.get("systemTeamKind", "")
        resolved_kind = _team_classification(row)
        for key, expected in (("kind", kind), ("source", source), ("team_kind", kind), ("team_source", source)):
            if key in row and row[key] != expected:
                raise ValueError("Conflicting Team classification alias")
        if not kind and not source and not legacy:
            raise ValueError("Missing Team classification")
        if _OWNED_SOURCE.fullmatch(source) and kind != "template_demo":
            raise ValueError("Conflicting template owner source")
        private = _private(row) or team_is_system_managed({**row, "teamKind": resolved_kind})
        members = row.get("members")
        if not isinstance(members, list) or len(members) > 120:
            raise ValueError("Invalid Team roster")
        ids = []
        for member in members:
            if not isinstance(member, dict) or "agent_id" in member:
                raise ValueError("Invalid Team member")
            aid = _identity(member.get("agentId"))
            if aid in ids:
                raise ValueError("Ambiguous Team member")
            ids.append(aid)
            private = _private(member) or private
        linked = row.get("linkedChatRoomId", "")
        if linked:
            _identity(linked)
        elif not isinstance(linked, str):
            raise ValueError("Invalid room link")
        result[tid] = {"row": row, "private": private, "members": ids,
                       "public": {"id": tid, "name": _text(row.get("name"), 120),
                                  "status": row["status"], "purpose": _text(row.get("purpose", ""), 240)}}
    return result


def _page(items, query, key):
    if query.query:
        needle = query.query.casefold()
        items = [item for item in items if any(needle in str(value).casefold() for value in item.values())]
    items.sort(key=lambda item: item["id"])
    selected = items[query.offset:query.offset + query.limit]
    end = query.offset + len(selected)
    return {key: selected, "total": len(items), "offset": query.offset,
            "nextOffset": end if end < len(items) else None, "untrustedContent": True}


def read_teams(project_root, directory, query):
    try:
        teams = _teams(ExistingStateSnapshot(project_root, directory))
        items = [{**team["public"], "name": _text(team["public"]["name"], 32),
                  "purpose": _text(team["public"]["purpose"], 64), "memberCount": len(team["members"])} for team in teams.values()
                 if not team["private"] and (query.archived or team["row"]["status"] != "archived")]
        return _page(items, query, "teams")
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, RecursionError):
        raise ManagementError("TEAM_LIST_UNAVAILABLE", 503) from None


def read_team(project_root, directory, team_id, query):
    try:
        team = _teams(ExistingStateSnapshot(project_root, directory)).get(_identity(team_id))
        if team is None or team["private"]:
            raise ValueError("Unavailable Team")
        selected = team["members"][query.member_offset:query.member_offset + query.limit]
        end = query.member_offset + len(selected)
        return {"team": {**team["public"], "members": [{"agentId": aid} for aid in selected],
                         "memberOffset": query.member_offset,
                         "memberTotal": len(team["members"]),
                         "nextMemberOffset": end if end < len(team["members"]) else None}, "untrustedContent": True}
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, RecursionError):
        raise ManagementError("TEAM_UNAVAILABLE", 404) from None


def _rooms(snapshot):
    # The native room store is always formal, even while Team state is sandboxed.
    # This physical JSON also contains rounds: decode once, never inspect their
    # messages, search them, hydrate participants, or include them in a projection.
    rows = _rows(snapshot, formal_workspace_path(snapshot.project_root, "chat_rooms", "chat_rooms.json"), "rooms")
    teams = _teams(snapshot)
    result, links = {}, {}
    for tid, team in teams.items():
        linked = team["row"].get("linkedChatRoomId")
        if linked:
            if linked in links:
                raise ValueError("Ambiguous Team room link")
            links[linked] = tid
    for row in rows:
        rid = _identity(row.get("roomId"))
        if rid in result or "id" in row and row["id"] != rid or "room_id" in row and row["room_id"] != rid:
            raise ValueError("Ambiguous room identity")
        if row.get("status") not in {"ready", "running", "stopping", "failed", "archived"}:
            raise ValueError("Unknown room status")
        if "archived" in row and (type(row["archived"]) is not bool or row["archived"] != (row["status"] == "archived")):
            raise ValueError("Conflicting room archive marker")
        config = row.get("config")
        if not isinstance(config, dict):
            raise ValueError("Invalid room config")
        row_private, config_private = _private(row), _private(config)
        private = row_private or config_private
        purpose = row.get("purpose", "")
        if purpose not in _ROOM_PURPOSES | _SYSTEM_PURPOSES:
            raise ValueError("Unknown room purpose")
        private = private or purpose in _SYSTEM_PURPOSES
        source = config.get("source", "")
        if not isinstance(source, str):
            raise ValueError("Invalid room source")
        if "source" in row and row["source"] != source:
            raise ValueError("Conflicting room source alias")
        if source not in {"", "manual", "team", "team_template"} | _SYSTEM_ROOM_SOURCES and not _OWNED_SOURCE.fullmatch(source):
            raise ValueError("Unknown room source")
        for record in (row, config):
            for key in ("teamId", "researchTeamId"):
                if key in record and not isinstance(record[key], str):
                    raise ValueError("Invalid room Team marker")
            for alias, canonical in (("team_id", "teamId"), ("research_team_id", "researchTeamId")):
                if alias in record and (not isinstance(record[alias], str) or record[alias] != record.get(canonical)):
                    raise ValueError("Conflicting room Team alias")
            for key in ("teamKind", "teamSource", "teamTemplateId"):
                if key in record and not isinstance(record[key], str):
                    raise ValueError("Invalid room Team classification")
            _team_classification(record)
        team_ids = [record[key] for record in (row, config) for key in ("teamId", "researchTeamId") if key in record and record[key]]
        if any(not isinstance(tid, str) for tid in team_ids) or len(set(team_ids)) > 1:
            raise ValueError("Conflicting room Team binding")
        tid = team_ids[0] if team_ids else ""
        if tid:
            _identity(tid)
            team = teams.get(tid)
            if team is None:
                raise ValueError("Missing room Team authority")
            classifications = [_team_classification(record) for record in (row, config, team["row"])]
            if len({value for value in classifications if value}) > 1:
                raise ValueError("Conflicting room Team classification")
            for key in ("teamKind", "teamSource", "teamTemplateId"):
                values = [record[key] for record in (row, config, team["row"]) if key in record]
                if len(set(values)) > 1:
                    raise ValueError("Conflicting room Team metadata")
            if team["private"]:
                # Scoped research workflow rooms share a system Team, but are
                # intentionally distinct from its canonical linked room. Their
                # existing source constants plus the Team index prove privacy.
                # Complete common shape/identity checks above still apply.
                result[rid] = {"private": True, "archived": team["row"]["status"] == "archived",
                               "public": {"id": rid, "title": _text(row.get("title"), 120), "status": row["status"]}}
                continue
            if links.get(rid) != tid:
                raise ValueError("Unproven room Team binding")
            if source not in {"team", team["row"].get("teamSource")}:
                raise ValueError("Conflicting room owner source")
            private = private or team["private"]
            archived = team["row"]["status"] == "archived"
        else:
            if rid in links or source not in {"", "manual"}:
                raise ValueError("Missing room Team binding")
            if any(key in record and record[key] for record in (row, config)
                   for key in ("teamKind", "teamSource", "teamTemplateId", "systemTeamKind")):
                raise ValueError("Unbound room Team classification")
            archived = False
        result[rid] = {"private": private, "archived": archived or row["status"] == "archived",
                       "public": {"id": rid, "title": _text(row.get("title"), 120), "status": row["status"]}}
    return result


def read_rooms(project_root, directory, query):
    try:
        rooms = _rooms(ExistingStateSnapshot(project_root, directory))
        return _page([room["public"] for room in rooms.values() if not room["private"]
                      and (query.archived or not room["archived"])], query, "rooms")
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, RecursionError):
        raise ManagementError("ROOM_LIST_UNAVAILABLE", 503) from None


def read_room(project_root, directory, room_id):
    try:
        room = _rooms(ExistingStateSnapshot(project_root, directory)).get(_identity(room_id))
        if room is None or room["private"]:
            raise ValueError("Unavailable room")
        return {"room": room["public"], "untrustedContent": True}
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, RecursionError):
        raise ManagementError("ROOM_UNAVAILABLE", 404) from None
