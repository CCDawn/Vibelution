"""Complete existing-only Agent metadata; never initialize, hydrate or repair."""
from __future__ import annotations

import json
import re
import unicodedata

from core.web.services.external_agent.policy import external_mcp_eligibility
from core.web.services.local_assistant.eligibility import local_assistant_eligibility

from .contracts import AgentDirectoryItem, AgentDirectoryResponse
from .service import ManagementError
from .state_snapshot import ExistingStateSnapshot
from .store import digest

_MAX_ROWS = 100_000
_MAX_ITEM_CHARS = 3000
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")


def _identity(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("Invalid directory identity")
    return value


def _rows(snapshot, path, field):
    payload = snapshot.read_json(path, strict=True)
    rows = payload.get(field)
    if (not isinstance(rows, list) or len(rows) > _MAX_ROWS
            or any(not isinstance(row, dict) for row in rows)):
        raise ValueError("Invalid directory authority")
    return payload, rows


def _label(value, limit):
    if not isinstance(value, str):
        raise TypeError("Invalid directory label")
    # Metadata remains quoted untrusted data. Do not run generic free-text
    # instruction-prefix filters: they erase legitimate names such as
    # `Use agent` or `请继续研究` and change registered identity metadata.
    cleaned = ("".join(char for char in value if unicodedata.category(char) not in {"Cc", "Cf", "Cs"})
               .replace("\u2028", " ").replace("\u2029", " ").strip())
    if len(cleaned) > limit:
        raise ValueError("Directory label exceeds native contract")
    return cleaned


def _teams(rows):
    teams, memberships = {}, {}
    for row in rows:
        tid = _identity(row.get("teamId"))
        if (tid in teams or row.get("status") not in {"active", "archived"}
                or any(key in row and row[key] != tid for key in ("id", "team_id"))):
            raise ValueError("Ambiguous Team authority")
        members = row.get("members")
        if not isinstance(members, list) or len(members) > 120:
            raise ValueError("Invalid Team roster")
        public = {"teamId": tid, "name": _label(row.get("name"), 120), "status": row["status"]}
        teams[tid] = public
        seen = set()
        for member in members:
            if not isinstance(member, dict) or "agent_id" in member:
                raise ValueError("Invalid Team member")
            aid = _identity(member.get("agentId"))
            if aid in seen:
                raise ValueError("Ambiguous Team member")
            seen.add(aid)
            memberships.setdefault(aid, []).append(public)
    for members in memberships.values():
        members.sort(key=lambda item: item["teamId"])
    return teams, memberships


def _gateway(config):
    from config.models import ExternalAgentGatewayConfig
    raw = config.get("external_agent_gateway", {})
    if not isinstance(raw, dict):
        raise TypeError("Invalid gateway authority")
    # Do not let the native config model's permissive normalizers turn corrupt
    # policy into an empty allowlist. Valid values keep its exact semantics.
    if "enabled" in raw and type(raw["enabled"]) is not bool:
        raise ValueError("Invalid gateway enabled policy")
    for key in ("allowed_agent_ids", "denied_agent_ids"):
        if key in raw and (not isinstance(raw[key], list) or len(raw[key]) > _MAX_ROWS
                or any(not isinstance(value, str) for value in raw[key])):
            raise ValueError("Invalid gateway Agent policy")
    gateway = ExternalAgentGatewayConfig.model_validate(raw)
    enabled, allowed, denied = gateway.enabled, set(gateway.allowed_agent_ids), set(gateway.denied_agent_ids)
    return (lambda aid: enabled and aid not in denied and (not allowed or aid in allowed),
            lambda aid: enabled and aid in allowed and aid not in denied)


def _reference_ids(records, keys):
    return sorted({_identity(record[key]) for record in records for key in keys
                   if key in record and record[key] not in (None, "")})


def _ownership(agent, kind, mode, teams, team_index, agent_names):
    metadata = agent.get("metadata", {})
    current_ids = {team["teamId"] for team in teams}
    referenced = _reference_ids((agent, metadata), ("teamId", "challengeCupTeamId", "knowledgeExpansionTeamId"))
    recorded = [team_index.get(tid, {"teamId": tid, "name": "", "status": "unavailable"})
                for tid in referenced if tid not in current_ids]
    creation_spec = metadata.get("creationSpec")
    creation_spec = creation_spec if isinstance(creation_spec, dict) else {}
    created_by = _label(agent.get("createdBy") or creation_spec.get("source") or "", 160)
    template_id = _label(metadata.get("teamTemplateId") or "", 160)
    owners = _reference_ids((metadata,), ("lifeStewardForAgentId", "selfWakeForAgentId"))
    if len(owners) > 1:
        raise ValueError("Conflicting explicit Companion ownership")
    owner_id = owners[0] if owners else ""
    if any(metadata.get(key) or agent.get(key) for key in
           ("virtualHumanCompanion", "virtualHumanSelfWake", "virtualHumanLifeSteward", "lifeStewardForAgentId", "selfWakeForAgentId", "companion")):
        owner = "companion"
    elif teams:
        owner = "team"
    elif (any(metadata.get(key) or agent.get(key) for key in
              ("personalAssistantProfile", "protected", "system", "systemManaged", "systemRole", "researchOrgRole"))
            or agent.get("roleKey") == "personal_assistant"
            or mode in {"self_evolution", "supervised_evolution"}):
        owner = "system"
    elif kind == "personal_agent" or (agent.get("conversationIndexKind") or metadata.get("conversationIndexKind")) == "personal_agent" or (agent.get("status") == "archived" and created_by == "user" and not referenced
            and not template_id and mode not in {"research", "self_evolution", "supervised_evolution"}
            and not str(agent.get("roleKey") or "").replace("-", "_").startswith(
                ("challenge_cup_", "knowledge_expansion_", "research_team_"))
            and not any(metadata.get(key) or agent.get(key) for key in
                ("internal", "systemRole", "researchOrgRole", "researchAgentKey", "supervisedRole", "systemTeamKind"))):
        owner = "personal"
    else:
        owner = "unknown"
    return {"kind": owner, "mode": mode, "teams": teams, "recordedTeams": recorded,
            "createdBy": created_by, "templateId": template_id, "ownerAgentId": owner_id,
            "ownerAgentName": agent_names.get(owner_id, "")}


def _agents(rows, directory, memberships, operator_enabled, operator_explicitly_enabled, team_index,
            *, dispatch_context="external"):
    result, seen = [], set()
    agent_names = {_identity(row.get("agentId")): _label(row.get("displayName", ""), 120) for row in rows}
    active_teams = {aid: next((team for team in teams if team["status"] == "active"), None)
                    for aid, teams in memberships.items()}
    for row in rows:
        aid = _identity(row.get("agentId"))
        if (aid in seen or any(key in row and row[key] != aid for key in ("id", "agent_id"))
                or not isinstance(row.get("metadata", {}), dict)):
            raise ValueError("Ambiguous Agent authority")
        seen.add(aid)
        for field in ("status", "displayName", "agentCode", "primaryMode", "roleKey", "kind", "directSessionId", "createdBy"):
            if field in row and not isinstance(row[field], str):
                raise ValueError("Invalid Agent metadata")
        # Match _agent_to_api_summary's pure classification and role projection.
        # Missing/invalid conversation-index metadata becomes `invalid`; role
        # aliases and inferred Team roles retain the native dispatch rejection.
        classification = directory.agent_conversation_index_classification(row)
        index_kind = classification["kind"]
        role = directory._normalize_role_key(row.get("roleKey") or directory._infer_agent_role_key(row))
        projected = {**row, "conversationIndexKind": index_kind, "roleKey": role}
        if dispatch_context == "launcher_local":
            decision = local_assistant_eligibility(projected, active_team_lookup=active_teams.get,
                operator_enabled=operator_enabled)
        else:
            decision = external_mcp_eligibility(projected, active_team_lookup=active_teams.get,
                operator_enabled=operator_enabled, operator_explicitly_enabled=operator_explicitly_enabled)
        mode = directory._normalize_primary_mode(row.get("primaryMode") or directory._infer_agent_primary_mode(row))
        code = directory._normalize_agent_code(row.get("agentCode")) or directory._fallback_agent_code(aid)
        item = AgentDirectoryItem.model_validate({"agentId": aid, "agentCode": _label(code, 64),
            "displayName": _label(row.get("displayName", ""), 120), "status": row.get("status") or "active",
            "ownership": _ownership(row, index_kind, mode, memberships.get(aid, []), team_index, agent_names),
            "dispatchable": decision.eligible, "dispatchReason": decision.reason}).model_dump()
        # A single complete ownership row must be representable. Never truncate
        # its Team roster and claim that the remaining ownership is complete.
        if len(json.dumps(item, ensure_ascii=False)) > _MAX_ITEM_CHARS:
            raise ValueError("Agent ownership exceeds response budget")
        result.append(item)
    return sorted(result, key=lambda item: item["agentId"])


def read_agents(project_root, directory, query):
    try:
        snapshot = ExistingStateSnapshot(project_root, directory, pin_workspace=True)
        paths = (snapshot.path("agents", "agents.json"), snapshot.path("teams", "teams.json"))
        tokens = [snapshot._path_token(path) for path in paths]
        agent_payload, agents = _rows(snapshot, paths[0], "agents")
        team_payload, teams = _rows(snapshot, paths[1], "teams")
        team_index, memberships = _teams(teams)
        operator_enabled, explicitly_enabled = _gateway(snapshot.config)
        context = getattr(query, "dispatch_context", "external")
        if context == "launcher_local":
            from config.models import ExternalAgentGatewayConfig
            denied = frozenset(ExternalAgentGatewayConfig.model_validate(
                snapshot.config.get("external_agent_gateway", {})).denied_agent_ids)
            operator_enabled = lambda aid: aid not in denied
        items = _agents(agents, directory, memberships, operator_enabled, explicitly_enabled, team_index,
            dispatch_context=context)
        revision_inputs = ["all_registered_agents.v1", str(snapshot.path()), agent_payload, team_payload,
                           snapshot.config.get("external_agent_gateway", {})]
        if context != "external":
            revision_inputs.append(context)
        revision = digest(revision_inputs)
        if query.query:
            needle = query.query.casefold()
            matches = [item for item in items if any(needle in value.casefold() for value in
                (item["agentId"], item["agentCode"], item["displayName"], item["status"], item["ownership"]["kind"],
                 *(item["ownership"][key] for key in ("mode", "createdBy", "templateId", "ownerAgentId", "ownerAgentName")),
                 *(value for key in ("teams", "recordedTeams") for team in item["ownership"][key]
                   for value in (team["teamId"], team["name"]))))]
        else:
            matches = items
        selected = matches[query.offset:query.offset + query.limit]
        end = query.offset + len(selected)
        response = AgentDirectoryResponse.model_validate({"scope": "all_registered_agents", "agents": selected,
            **({"dispatchContext": context} if context != "external" else {}),
            "total": len(matches), "registryTotal": len(items), "counts": {
                "active": sum(item["status"] == "active" for item in items),
                "archived": sum(item["status"] == "archived" for item in items),
                "dispatchable": sum(item["dispatchable"] for item in items)}, "offset": query.offset,
            "nextOffset": end if end < len(matches) else None, "revision": revision,
            "untrustedContent": True}).model_dump(exclude_unset=True)
        snapshot.verify_workspace()
        if tokens != [snapshot._path_token(path) for path in paths]:
            raise ValueError("Agent directory authority changed")
        if query.expected_revision is not None and query.expected_revision != revision:
            raise ManagementError("AGENT_DIRECTORY_REVISION_CONFLICT", 409)
        return response
    except ManagementError:
        raise
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, RecursionError):
        raise ManagementError("AGENT_DIRECTORY_UNAVAILABLE", 503) from None
