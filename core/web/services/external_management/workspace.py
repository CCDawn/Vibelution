"""Metadata-only Session read through existing native readers, with no repair."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from .service import ManagementError


def _deny(*, known_private=False):
    error = ManagementError("SESSION_UNAVAILABLE", 404)
    error.known_private = known_private
    raise error


def _aliases_agree(record):
    for aliases in (("agent_id", "agentId"), ("session_kind", "sessionKind"), ("session_role", "sessionRole"),
                    ("conversation_index_kind", "conversationIndexKind"),
                    ("conversation_index_visibility", "conversationIndexVisibility")):
        values = [record[key] for key in aliases if record.get(key)]
        if values and any(value != values[0] for value in values):
            _deny()


def _ordinary(record: dict, *, listing=False):
    """Reject every explicit private/lifecycle marker, including conflicting aliases."""
    _aliases_agree(record)
    for key in ("archived", "read_only", "readOnly", "hidden_from_index", "hiddenFromIndex"):
        if record.get(key):
            _deny(known_private=record[key] is True)
    for key in ("archive_state", "archiveState"):
        if key in record and (not isinstance(record[key], dict) or record[key].get("status") == "archived"):
            _deny(known_private=isinstance(record[key], dict) and record[key].get("status") == "archived")
    for key in ("parent_session_id", "parentSessionId", "team_id", "teamId", "agent_profile_id", "agentProfileId",
                "personalAssistantProfile", "virtualHumanCompanion", "virtualHumanSelfWake", "lifeStewardForAgentId"):
        if record.get(key):
            _deny(known_private=isinstance(record[key], str) or record[key] is True)
    for key in ("session_kind", "sessionKind"):
        if key in record and record[key] != "main":
            _deny(known_private=record[key] == "child" or listing and record[key] == "supervised")
    for key in ("conversation_index_kind", "conversationIndexKind"):
        if key in record and record[key] not in {"user_chat", "personal_agent"}:
            _deny(known_private=record[key] in {"hidden", "team_agent"})
    for key in ("conversation_index_visibility", "conversationIndexVisibility"):
        if key in record and record[key] != "user_visible":
            _deny(known_private=record[key] == "hidden")
    if record.get("status") == "archived":
        _deny(known_private=True)


def _registry_agents(project_root, directory):
    with directory.scoped_project_root(project_root):
        path = directory._workspace_path("agents", "agents.json", intent="state", seed=False)
        payload = json.loads(path.read_text(encoding="utf-8"))
    agents = payload["agents"]
    if not isinstance(agents, list) or len(agents) > 100_000 or any(not isinstance(item, dict) for item in agents):
        _deny()
    return agents


def _team_member_ids(project_root):
    from core.web.services.team import team_projection, team_store
    result = set()
    for team in team_store.read_index_snapshot(project_root=project_root)["teams"]:
        members = team.get("members")
        if (not isinstance(members, list) or len(members) > 120
            or any(not isinstance(member, dict) or "agent_id" in member
                   or not isinstance(member.get("agentId"), str) or not member["agentId"].strip()
                   for member in members)):
            _deny()
        projected = team_projection._members_to_api(members)
        if len(projected) != len(members):
            _deny()
        result.update(member["agentId"] for member in projected)
    return result


def _session_identity(row, runtime, session_id):
    records = (row,) if runtime is None else (row, runtime)
    agent_id = row.get("agentId")
    if not isinstance(agent_id, str) or not agent_id or row.get("sessionId") != session_id:
        _deny()
    for record in records:
        for key in ("agent_id", "agentId"):
            if record.get(key) and record[key] != agent_id:
                _deny()
    if runtime is not None and not any(runtime.get(key) == agent_id for key in ("agent_id", "agentId")):
        _deny()
    for record in records:
        for key in ("id", "sessionId", "conversation_id", "conversationId", "root_session_id", "rootSessionId"):
            if record.get(key) and record[key] != session_id:
                _deny()
    return agent_id


def _list_record_shape(record):
    # The list distinguishes malformed authority from an explicitly private row.
    # Single-record reads retain their existing rejection policy and ordering.
    from core.web.services import agent_directory_service as directory

    for key in ("agent_id", "agentId", "session_kind", "sessionKind", "session_role", "sessionRole",
                "conversation_index_kind", "conversationIndexKind", "conversation_index_visibility", "conversationIndexVisibility",
                "id", "sessionId", "conversation_id", "conversationId", "root_session_id", "rootSessionId",
                "parent_session_id", "parentSessionId", "team_id", "teamId", "agent_profile_id", "agentProfileId",
                "source", "created_by", "createdBy"):
        if key in record and not isinstance(record[key], str):
            _deny()
    for key in ("archived", "read_only", "readOnly", "hidden_from_index", "hiddenFromIndex"):
        if key in record and type(record[key]) is not bool:
            _deny()
    for key in ("archive_state", "archiveState"):
        if key in record and not isinstance(record[key], dict):
            _deny()
    for key in ("personalAssistantProfile", "virtualHumanCompanion", "virtualHumanSelfWake", "lifeStewardForAgentId"):
        value = record.get(key)
        # Preserve _ordinary's existing falsey/unset boundary, including None.
        # Native producers use string profile/owner IDs and boolean flags.
        if value and not isinstance(value, str) and value is not True:
            _deny()
    # Canonical conversation values, not Launcher/Workbench window roles:
    # runtime_glue._normalize_session_kind; conversation_index's native create
    # paths write primary/workspace; directory_bridge persists unset role as "".
    # Do not call normalizers here: unknown input must not fall back to main.
    domains = (
        (("session_kind", "sessionKind"), {"main", "child", "supervised"}),
        (("session_role", "sessionRole"), {"", "primary", "workspace"}),
        (("conversation_index_kind", "conversationIndexKind"),
         directory.CONVERSATION_INDEX_KINDS - {directory.CONVERSATION_INDEX_KIND_INVALID}),
        (("conversation_index_visibility", "conversationIndexVisibility"), directory.CONVERSATION_INDEX_VISIBILITIES),
    )
    for aliases, allowed in domains:
        if any(key in record and record[key] not in allowed for key in aliases):
            _deny()


def _agent_visibility(directory, agent):
    metadata = agent.get("metadata", {})
    if (not isinstance(metadata, dict) or agent.get("status") != "active"
        or not isinstance(agent.get("roleKey"), str) or not agent["roleKey"]):
        _deny(known_private=agent.get("status") == "archived" and isinstance(metadata, dict))
    if (agent.get("kind") != directory.DEFAULT_AGENT_KIND or agent.get("roleKey") == "personal_assistant"
        or agent["roleKey"].startswith(("challenge_cup_", "knowledge_expansion_"))
        or metadata.get("personalAssistantProfile") or metadata.get("protected")
        or metadata.get("systemRole") or metadata.get("researchOrgRole")
        or any(metadata.get(key) for key in ("teamId", "challengeCupTeamId", "knowledgeExpansionTeamId",
            "virtualHumanCompanion", "virtualHumanSelfWake", "lifeStewardForAgentId"))):
        private = (agent.get("kind") == "ephemeral" or agent.get("roleKey") == "personal_assistant"
            or agent["roleKey"].startswith(("challenge_cup_", "knowledge_expansion_"))
            or any(metadata.get(key) for key in ("personalAssistantProfile", "protected", "systemRole", "researchOrgRole",
                "teamId", "challengeCupTeamId", "knowledgeExpansionTeamId", "virtualHumanCompanion", "virtualHumanSelfWake", "lifeStewardForAgentId")))
        _deny(known_private=bool(private))
    creation = metadata.get("creationSpec") or {}
    if not isinstance(creation, dict):
        _deny()
    source = agent.get("createdBy") or creation.get("source")
    if source in directory.TEAM_PRIVATE_DIRECT_SESSION_CREATED_BY | directory.INTERNAL_RECOVERY_DIRECT_SESSION_CREATED_BY:
        _deny(known_private=True)
    agent_classification = directory.agent_conversation_index_classification(agent, hidden_team_member_agent_ids=set())
    if agent_classification["kind"] != "personal_agent" or agent_classification["errors"]:
        _deny(known_private=not agent_classification["errors"] and agent_classification["kind"] in {"hidden", "team_agent"})
    return metadata, agent_classification


def _binding_snapshot(project_root, agent_id, cache=None):
    from core.agent_plugins.virtual_human_life.storage import VirtualHumanLifeStore
    from core.infrastructure import developer_sandbox
    cache = {} if cache is None else cache
    if agent_id not in cache:
        plugin = VirtualHumanLifeStore(project_root, plugin_root_resolver=lambda owner:
            developer_sandbox.route_workspace_path(project_root, "agent_directory", "agents", owner,
                "plugins", "virtual-human-life", intent="state", seed=False))
        cache[agent_id] = plugin.read_json(agent_id, "binding.json")
    return cache[agent_id]


def _validated_session_snapshot(project_root: Path, directory, session_id: str, *, _context=None):
    from core.agent_plugins.virtual_human_life.storage import VirtualHumanLifeStore
    from core.infrastructure import developer_sandbox
    from core.web.services.team import team_projection, team_store
    from core.web.services.session import conversation_index, directory_runtime

    # Never open a fallback store, wait for bootstrap, or reconcile a directory.
    store = _context["store"] if _context is not None else directory_runtime.get_open_directory_store()
    root = project_root if _context is not None else directory_runtime.directory_store_project_root()
    if root is not None and Path(root).resolve() != project_root:
        raise ManagementError("TARGET_BINDING_CHANGED", 409)
    if store is None or root is None:
        raise ManagementError("SESSION_DIRECTORY_UNAVAILABLE", 503)
    row = _context["rows"][session_id] if _context is not None else store.repository.get_session(session_id, include_archived=False)
    runtime = _context["runtimes"][session_id] if _context is not None else store.repository.get_session_runtime_state(session_id)
    if not isinstance(row, dict) or not isinstance(runtime, dict):
        _deny()
    if _context is not None:
        _list_record_shape(row)
        _list_record_shape(runtime)
    _ordinary(row)
    _ordinary(runtime)
    agent_id = _session_identity(row, runtime, session_id)
    # Default single-read order stays row/runtime -> registry -> roster -> binding.
    try:
        if _context is not None:
            agent = _context["agents_by_id"].get(agent_id)
            if agent is None or _context["direct_owners"].get(session_id, agent_id) != agent_id:
                _deny()
        else:
            agents = _registry_agents(project_root, directory)
            matches = [item for item in agents if item.get("agentId") == agent_id]
            if len(matches) != 1:
                _deny()
            agent = matches[0]
            if any(item is not agent and item.get("directSessionId") == session_id for item in agents):
                _deny()
        team_ids = _context["team_ids"] if _context is not None else _team_member_ids(project_root)
        if agent_id in team_ids:
            _deny(known_private=True)
        metadata, agent_classification = _agent_visibility(directory, agent)
        for record in (row, runtime):
            if any(record.get(key) in directory.TEAM_PRIVATE_DIRECT_SESSION_CREATED_BY | directory.INTERNAL_RECOVERY_DIRECT_SESSION_CREATED_BY
                   for key in ("source", "created_by", "createdBy")):
                _deny(known_private=True)
        for key in ("conversationIndexKind", "conversation_index_kind"):
            if metadata.get(key) and metadata[key] != agent_classification["kind"]:
                _deny()
        if not conversation_index._conversation_agent_direct_session_is_allowed(
            conversation=runtime, conversation_id=session_id, direct_session_id=agent.get("directSessionId", "")):
            _deny()
        for record in (row, runtime):
            classification = conversation_index._conversation_index_classification(record, agent, hidden_team_member_agent_ids=set())
            if classification["kind"] not in {"user_chat", "personal_agent"} or classification["errors"]:
                _deny()
        binding = _binding_snapshot(project_root, agent_id, _context["bindings"] if _context is not None else None)
        if binding is not None and (binding.get("enabled") is not False or binding.get("agentId") not in (None, agent_id)):
            _deny(known_private=binding.get("enabled") is True and binding.get("agentId") in (None, agent_id))
    except ManagementError:
        raise
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        _deny()
    return store.repository, deepcopy(row), {
        "last_turn_status": runtime.get("last_turn_status"), "lastTurnStatus": runtime.get("lastTurnStatus")}


def read_session(project_root: Path, directory, session_id: str) -> dict:
    from tools.pa_workspace_actions import _session_public

    _repository, row, runtime = _validated_session_snapshot(project_root, directory, session_id)
    # Frozen directory title/pin and runtime phase only. No messages, previews,
    # paths, config snapshots, worker objects or active operator selection.
    public = _session_public({**row, "phase": runtime.get("last_turn_status") or runtime.get("lastTurnStatus") or row.get("status")})
    pinned_at = row.get("pinnedAtMs")
    public["pinnedAtMs"] = pinned_at if type(pinned_at) is int and pinned_at > 0 else None
    return {"session": public, "untrustedContent": True}


def _compiled_model_fields(snapshot, *, session_id: str, agent_id: str, expected_revision_id: str | None = None) -> dict:
    """Pure projection shared by history and comparison; no current/default read."""
    from core.llm.agent_model_parameters import resolve_agent_model_parameters
    from .contracts import SessionConfigView

    if not isinstance(snapshot, dict):
        raise ValueError("Missing compiled configuration")
    revision_id = snapshot.get("configRevisionId")
    if expected_revision_id is not None and revision_id != expected_revision_id:
        raise ValueError("Mismatched revision")
    config = snapshot["config"]
    model_id = config["llmBindings"]["dialogue"]["modelId"]
    by_model = config.get("modelParametersByRef", {})
    if not isinstance(by_model, dict):
        raise ValueError("Invalid model parameters map")
    entry = by_model.get(model_id, {})
    if not isinstance(entry, dict):
        raise ValueError("Invalid model parameters entry")
    if any(key in entry and entry[key] is None for key in ("contextWindow", "reasoningEffort")):
        raise ValueError("Invalid null stored override")
    legacy = {}
    if "reasoningEffort" not in entry:
        legacy = config.get("reasoningEffortBySlot", {})
        if not isinstance(legacy, dict) or ("dialogue" in legacy and legacy["dialogue"] is None):
            raise ValueError("Invalid legacy reasoning map")
    # Validate before the compatibility resolver can coerce strings/booleans.
    view = SessionConfigView.model_validate({"sessionId": session_id, "agentId": agent_id,
        "agentConfigRevisionId": revision_id, "modelId": model_id,
        "contextWindow": entry.get("contextWindow"),
        "reasoningEffort": entry["reasoningEffort"] if "reasoningEffort" in entry else legacy.get("dialogue")})
    selected = {key: entry[key] for key in ("contextWindow", "reasoningEffort") if key in entry}
    resolved = resolve_agent_model_parameters({"metadata": {"llmModelParameters": {view.modelId: selected},
        "llmReasoningEffort": {"dialogue": view.reasoningEffort} if "dialogue" in legacy else {}}}, view.modelId)
    return {"agentConfigRevisionId": view.agentConfigRevisionId, "modelId": view.modelId,
        "contextWindow": resolved["context_window"] if "contextWindow" in selected else None,
        "reasoningEffort": (resolved["reasoning_effort"] if "reasoningEffort" in selected
                            else resolved["legacy_reasoning_effort"] if "dialogue" in legacy else None)}


def _pinned_model_fields(repository, row: dict, session_id: str) -> dict:
    revision_id = row.get("agentConfigRevisionId")
    if not isinstance(revision_id, str) or not revision_id:
        raise ValueError("Missing pinned revision")
    snapshot = repository.get_agent_config_revision(row["agentId"], revision_id)
    return _compiled_model_fields(snapshot, session_id=session_id, agent_id=row["agentId"], expected_revision_id=revision_id)


def read_session_config(project_root: Path, directory, session_id: str) -> dict:
    """Stored historical fields only. This path never asks for current config."""
    from .contracts import SessionConfigResponse

    repository, row, _runtime = _validated_session_snapshot(project_root, directory, session_id)
    try:
        values = {"sessionId": session_id, "agentId": row["agentId"], **_pinned_model_fields(repository, row, session_id)}
        return SessionConfigResponse.model_validate({"source": "session_agent_config_revision",
            "untrustedContent": True, "config": values}).model_dump()
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        raise ManagementError("SESSION_CONFIG_UNAVAILABLE", 404) from None


def read_session_config_comparison(project_root: Path, directory, session_id: str) -> dict:
    """Compare two native stored snapshots, never effective/active-Turn values."""
    from .contracts import SessionConfigComparisonResponse

    repository, row, _runtime = _validated_session_snapshot(project_root, directory, session_id)
    try:
        pinned = _pinned_model_fields(repository, row, session_id)
        current = _compiled_model_fields(repository.get_current_agent_config(row["agentId"]),
                                         session_id=session_id, agent_id=row["agentId"])
        changed = [key for key in ("modelId", "contextWindow", "reasoningEffort") if pinned[key] != current[key]]
        return SessionConfigComparisonResponse.model_validate({"source": "session_agent_config_comparison",
            "untrustedContent": True, "sessionId": session_id, "agentId": row["agentId"],
            "pinned": pinned, "current": current,
            "sameRevision": pinned["agentConfigRevisionId"] == current["agentConfigRevisionId"],
            "changedFields": changed}).model_dump()
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        raise ManagementError("SESSION_CONFIG_COMPARISON_UNAVAILABLE", 404) from None


def _list_private_candidate(project_root, directory, context, session_id):
    """Validate every available identity before filtering an established private row."""
    from core.web.services.session import conversation_index
    row = context["store"].repository.get_session(session_id, include_archived=False)
    runtime = context["store"].repository.get_session_runtime_state(session_id)
    if not isinstance(row, dict) or runtime is not None and not isinstance(runtime, dict):
        _deny()
    _list_record_shape(row)
    _aliases_agree(row)
    if runtime is not None:
        _list_record_shape(runtime)
        _aliases_agree(runtime)
    agent_id = _session_identity(row, runtime, session_id)
    agent = context["agents_by_id"].get(agent_id)
    if agent is None or context["direct_owners"].get(session_id, agent_id) != agent_id:
        _deny()
    metadata = agent.get("metadata", {})
    if (not isinstance(metadata, dict) or not isinstance(agent.get("roleKey"), str) or not agent["roleKey"]
        or agent.get("status") not in {"active", "archived"}
        or agent.get("kind") not in {directory.DEFAULT_AGENT_KIND, "ephemeral"}
        or not isinstance(metadata.get("creationSpec") or {}, dict)):
        _deny()
    creation = metadata.get("creationSpec") or {}
    if ("createdBy" in agent and not isinstance(agent["createdBy"], str)
        or "source" in creation and not isinstance(creation["source"], str)):
        _deny()
    classification = directory.agent_conversation_index_classification(agent, hidden_team_member_agent_ids=set())
    if classification["errors"]:
        _deny()
    for key in ("conversationIndexKind", "conversation_index_kind"):
        if metadata.get(key) and metadata[key] != classification["kind"]:
            _deny()
    for record in (row,) if runtime is None else (row, runtime):
        record_class = conversation_index._conversation_index_classification(record, agent, hidden_team_member_agent_ids=set())
        if record_class["errors"]:
            _deny()
    # Even a PA/Team marker cannot mask corrupt or cross-actor binding authority.
    binding = _binding_snapshot(project_root, agent_id, context["bindings"])
    if binding is not None and (type(binding.get("enabled")) is not bool or binding.get("agentId") not in (None, agent_id)):
        _deny()
    if binding is not None:
        context["bindings"][agent_id] = {"enabled": binding["enabled"], "agentId": binding.get("agentId")}
    private = agent_id in context["team_ids"] or binding is not None and binding["enabled"] is True
    for check in (lambda: _ordinary(row, listing=True), lambda: _agent_visibility(directory, agent),
                  *((lambda: _ordinary(runtime, listing=True),) if runtime is not None else ())):
        try:
            check()
        except ManagementError as exc:
            if not getattr(exc, "known_private", False):
                raise
            private = True
    if runtime is None and not private:
        _deny()
    # Retain only the current candidate, not a request-sized transcript cache.
    context["rows"], context["runtimes"] = {session_id: row}, {session_id: runtime}
    return private


_SESSION_LIST_SCAN_LIMIT = 10_000


def read_sessions(project_root: Path, directory, query) -> dict:
    """Discover ordinary sessions; no repair, preview search or partial authority."""
    import unicodedata
    from core.chat.conversation_store import parse_directory_cursor_entry
    from core.infrastructure.tool_result import project_tool_result_for_model
    from core.web.services.session import directory_runtime
    from .contracts import SessionListItem, SessionListResponse, SessionMetadataQuery

    try:
        store = directory_runtime.get_open_directory_store()
        root = directory_runtime.directory_store_project_root()
        if store is None or root is None or Path(root).resolve() != project_root:
            raise ValueError("Unavailable bound directory")
        agents = _registry_agents(project_root, directory)
        agents_by_id, direct_owners = {}, {}
        for agent in agents:
            aid, sid = agent.get("agentId"), agent.get("directSessionId")
            if not isinstance(aid, str) or not aid or aid in agents_by_id:
                raise ValueError("Ambiguous Agent registry")
            agents_by_id[aid] = agent
            if sid:
                if not isinstance(sid, str) or sid in direct_owners:
                    raise ValueError("Ambiguous direct Session")
                direct_owners[sid] = aid
        context = {"store": store, "agents_by_id": agents_by_id, "direct_owners": direct_owners,
                   "team_ids": _team_member_ids(project_root), "bindings": {}, "rows": {}, "runtimes": {}}
        seen, visible, before = set(), [], None
        while True:
            # DAO query also searches last_preview. It must always remain empty.
            page = store.repository.list_directory_page(include_hidden=False, query="", limit=200, before=before)
            batch = page["rows"]
            if not isinstance(batch, list) or page["total"] > _SESSION_LIST_SCAN_LIMIT:
                raise ValueError("Session scan bound exceeded")
            for candidate in batch:
                sid = SessionMetadataQuery.model_validate({"session_id": candidate["sessionId"]}).session_id
                if sid in seen or len(seen) >= _SESSION_LIST_SCAN_LIMIT:
                    raise ValueError("Duplicate or excessive Session candidates")
                seen.add(sid)
                if _list_private_candidate(project_root, directory, context, sid):
                    continue
                try:
                    _repo, row, _runtime = _validated_session_snapshot(project_root, directory, sid, _context=context)
                except ManagementError as exc:
                    if getattr(exc, "known_private", False):
                        continue
                    raise
                title = row.get("title")
                if not isinstance(title, str):
                    raise ValueError("Invalid directory title")
                cleaned = json.loads(project_tool_result_for_model(json.dumps({"value": title}, ensure_ascii=False)))["value"]
                cleaned = "".join(char for char in cleaned if unicodedata.category(char) != "Cc")
                # Truncation is another text boundary: run the same native
                # safety projection on the complete preview before returning it.
                preview = json.loads(project_tool_result_for_model(json.dumps({"value": cleaned[:48]}, ensure_ascii=False)))["value"]
                preview = "".join(char for char in preview if unicodedata.category(char) != "Cc").strip()
                item = SessionListItem.model_validate({"id": sid, "agentId": row["agentId"],
                    "titlePreview": preview, "titleTruncated": preview != title}).model_dump()
                identity = {"id": item["id"], "agentId": item["agentId"]}
                if json.loads(project_tool_result_for_model(json.dumps(identity))) != identity:
                    # A valid legacy identifier can still resemble workflow text.
                    # Fail closed rather than silently changing its address.
                    raise ValueError("Unrepresentable model-visible identity")
                if query.agent_id and query.agent_id != item["agentId"]:
                    continue
                if query.query and not any(query.query.casefold() in text.casefold() for text in (cleaned, sid, item["agentId"])):
                    continue
                visible.append(item)
            cursor = page.get("nextCursor")
            if not cursor:
                break
            before = parse_directory_cursor_entry(cursor)
            if not batch or before is None:
                raise ValueError("Invalid directory cursor")
        visible.sort(key=lambda item: item["id"])
        selected = visible[query.offset:query.offset + query.limit]
        end = query.offset + len(selected)
        return SessionListResponse.model_validate({"source": "native-session-directory", "untrustedContent": True,
            "sessions": selected, "offset": query.offset, "limit": len(selected), "total": len(visible),
            "nextOffset": end if end < len(visible) else None}).model_dump()
    except (ManagementError, OSError, ValueError, TypeError, KeyError, RuntimeError):
        raise ManagementError("SESSION_LIST_UNAVAILABLE", 503) from None
