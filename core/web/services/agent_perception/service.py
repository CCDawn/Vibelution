"""Scoped perception configuration and bounded, read-only discovery.

Policy is part of the existing Agent configuration, not a parallel registry.
The service intersects policy scope with current MemoryPolicy and owner ACL.
No source body, user prompt, or conversation is persisted here.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from .policy import (
    AgentPerceptionPolicyError,
    agent_perception_policy_fingerprint,
    decide_agent_perception,
    default_agent_perception_policy,
    normalize_agent_perception_policy,
)

POLICY_METADATA_KEY = "perceptionPolicy"
SOURCE_NAMES = ("personal", "team", "knowledge", "projects")
MAX_QUERY_CHARS = 1000
MAX_VISIBLE_BASES = 128
TASK_SEARCH_MAX_CALLS_PER_RUN = 8
TASK_SEARCH_MAX_RESULT_CHARS = 12_000
_TOOL_SOURCE_ALLOWLIST = {
    "unified_memory_search_tool": frozenset({"team", "knowledge"}),
    "search_agent_private_memory_tool": frozenset({"personal"}),
    "github_project_library_search_tool": frozenset({"projects"}),
}


class AgentPerceptionError(ValueError):
    pass


class AgentPerceptionDenied(AgentPerceptionError):
    pass


def _directory():
    from core.web.services import agent_directory_service

    return agent_directory_service


def _agent(agent_id: str) -> dict[str, Any]:
    if not isinstance(agent_id, str) or not agent_id.strip():
        raise AgentPerceptionError("Agent identity is required.")
    agent = _directory().get_agent(agent_id.strip())
    if not agent:
        raise _directory().AgentNotFoundError("Agent not found.")
    if agent.get("status") == "archived":
        raise AgentPerceptionDenied("Archived Agents cannot start perception.")
    return agent


def configured_policy(agent: dict[str, Any]) -> dict[str, Any] | None:
    metadata = agent.get("metadata")
    if not isinstance(metadata, dict) or POLICY_METADATA_KEY not in metadata:
        return None
    # A corrupt persisted policy fails closed; it never restores legacy access.
    value = metadata[POLICY_METADATA_KEY]
    if not isinstance(value, dict):
        raise AgentPerceptionDenied("Stored perception policy is invalid.")
    try:
        return normalize_agent_perception_policy(value)
    except AgentPerceptionPolicyError as exc:
        raise AgentPerceptionDenied("Stored perception policy is invalid.") from exc


def get_perception_configuration(agent_id: str) -> dict[str, Any]:
    agent = _agent(agent_id)
    policy = configured_policy(agent)
    visible = _visible_bases(agent)
    teams: dict[str, dict[str, str]] = {}
    knowledge_bases: list[dict[str, str]] = []
    for base in visible:
        if base.get("ownerType") != "team" or str(base.get("status") or "active") != "active":
            continue
        owner_id = str(base.get("ownerId") or "").strip()
        scoped_id = str(base.get("scopedKnowledgeBaseId") or "").strip()
        if not owner_id or not scoped_id:
            continue
        owner_label = str(base.get("ownerName") or base.get("teamName") or owner_id).strip()
        teams.setdefault(owner_id, {"id": owner_id, "label": owner_label, "detail": ""})
        label = str(base.get("displayName") or base.get("name") or base.get("knowledgeBaseName") or base.get("knowledgeBaseId") or scoped_id).strip()
        knowledge_bases.append({
            "id": scoped_id,
            "label": label,
            "detail": owner_label,
        })
    return {
        "schemaVersion": 1,
        "agentId": str(agent["agentId"]),
        "configured": policy is not None,
        "policy": policy if policy is not None else default_agent_perception_policy(),
        "policyFingerprint": agent_perception_policy_fingerprint(policy) if policy is not None else "",
        "agentUpdatedAt": str(agent.get("updatedAt") or ""),
        "configurationRevision": int(agent.get("configRevision") or 0),
        # These are configuration decisions, not an ACL grant or live status.
        "sourceDecisions": [
            decide_agent_perception(policy, source=source, trigger="task")
            for source in SOURCE_NAMES
        ],
        "availableScopes": {
            "teams": [teams[key] for key in sorted(teams)],
            "knowledgeBases": knowledge_bases,
        },
    }


def save_perception_configuration(
    agent_id: str, policy: dict[str, Any], *, expected_agent_updated_at: str,
) -> dict[str, Any]:
    """Operator configuration; Agent calls cannot enlarge persistent scope."""
    _require_privileged_operator("configure_agent_perception")
    agent = _agent(agent_id)
    if not isinstance(expected_agent_updated_at, str) or not expected_agent_updated_at.strip():
        raise AgentPerceptionError("Expected Agent updatedAt is required.")
    normalized = normalize_agent_perception_policy(policy)
    _directory().update_agent_instance(
        str(agent["agentId"]),
        metadata={POLICY_METADATA_KEY: normalized},
        expected_updated_at=expected_agent_updated_at.strip(),
        allow_agent_perception_policy=True,
    )
    _event("configuration.saved", agent_id, {
        "enabled": normalized["enabled"],
        "policyFingerprint": agent_perception_policy_fingerprint(normalized),
    })
    try:
        from .runtime import on_agent_perception_policy_saved

        on_agent_perception_policy_saved(str(agent["agentId"]))
    except Exception:
        # The policy is the durable authority. A runtime wake-up is best-effort
        # and must not turn a successful CAS write into an apparent failure.
        pass
    return get_perception_configuration(agent_id)


def _require_privileged_operator(command: str) -> None:
    from core.web.services.team_workflow.research_runtime.operator_authorization import (
        require_privileged_server_operator,
    )

    require_privileged_server_operator(command=command)


def _event(code: str, agent_id: str, fields: dict[str, Any]) -> None:
    from core.web.services.runtime_scene_service import record_runtime_scene_event_quietly

    record_runtime_scene_event_quietly(
        "agent_perception", "control", "agent.perception." + code,
        fields={"agentId": agent_id, **fields},
    )


def _visible_bases(agent: dict[str, Any]) -> list[dict[str, Any]]:
    from core.web.services import team_knowledge_service as knowledge

    memory = _directory().resolve_memory_policy_for_agent(str(agent["agentId"]))
    allowed = list(memory.get("readKnowledgeBaseIds") or [])
    overview = knowledge.list_knowledge_overview(agent_id=str(agent["agentId"]), sync_roots=False)
    rows = []
    for base in list(overview.get("knowledgeBases") or []):
        base_id = str(base.get("scopedKnowledgeBaseId") or "").strip()
        if not base_id or not (base.get("permissions") or {}).get("canRead"):
            continue
        if base.get("ownerType") == "agent" and memory.get("enabled") is False:
            continue
        if allowed and not knowledge.knowledge_base_policy_allows(base_id, allowed):
            continue
        rows.append(base)
    return sorted(rows, key=lambda row: str(row["scopedKnowledgeBaseId"]))[:MAX_VISIBLE_BASES]


def _selected_bases(
    agent: dict[str, Any], policy: dict[str, Any], source: str, visible: list[dict[str, Any]],
    scope: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    config = policy["sources"][source]
    if source == "personal":
        return [row for row in visible if row.get("ownerType") == "agent" and row.get("ownerId") == agent["agentId"]]
    if source == "team":
        selected = set(scope["ids"] if scope and scope.get("kind") == "selected" else config["teamIds"])
        return [row for row in visible if row.get("ownerType") == "team" and row.get("ownerId") in selected]
    if source == "knowledge":
        selected = scope["ids"] if scope and scope.get("kind") == "selected" else config["knowledgeBaseIds"]
        all_authorized = config["scope"] == "all_authorized" and not (scope and scope.get("kind") == "selected")
        excluded = config["excludedKnowledgeBaseIds"]
        return [
            row for row in visible
            # Personal data always stays under the separate personal gate.
            if not (row.get("ownerType") == "agent" and row.get("ownerId") == agent["agentId"])
            # New selections use owner-scoped identities. A raw name must not
            # accidentally select identically named bases owned by other teams.
            and (all_authorized or row["scopedKnowledgeBaseId"] in selected)
            and row["scopedKnowledgeBaseId"] not in excluded
        ]
    return []


def _assert_policy_current(agent_id: str, expected_fingerprint: str) -> dict[str, Any]:
    agent = _agent(agent_id)
    current = configured_policy(agent)
    if current is None or agent_perception_policy_fingerprint(current) != expected_fingerprint:
        raise AgentPerceptionDenied("Perception configuration changed; start a new scoped request.")
    return agent


def begin_knowledge_item_read(agent_id: str, base_id: str) -> dict[str, Any] | None:
    """Authorize and charge one configured Agent knowledge-item read.

    ``None`` preserves the legacy path for Agents that have never configured
    perception. The returned short-lived ticket carries no knowledge content.
    """
    agent = _agent(str(agent_id or "").strip())
    policy = configured_policy(agent)
    if policy is None:
        return None

    from .access import current_perception_turn
    from core.authorization.tool_authorization_service import current_execution_authorization

    turn = current_perception_turn()
    if turn is None or turn.agent_id != str(agent["agentId"]):
        raise AgentPerceptionDenied("No trusted perception context is bound to this Agent turn.")
    authorization = current_execution_authorization()
    if (
        authorization is None
        or str(getattr(authorization, "agent_id", "")).strip() != str(agent["agentId"])
        or "read_knowledge_item_tool" not in set(getattr(authorization, "executable_tools", ()))
    ):
        raise AgentPerceptionDenied("The current Agent turn did not authorize knowledge-item reads.")
    _assert_tool_authorization_current(str(agent["agentId"]), "read_knowledge_item_tool", authorization)
    authorized_turn_id = str(getattr(authorization, "turn_id", "") or "").strip()
    if turn.turn_id and authorized_turn_id and turn.turn_id != authorized_turn_id:
        raise AgentPerceptionDenied("The perception context does not match the authorized Agent turn.")

    visible = _visible_bases(agent)
    supplied_base_id = str(base_id or "").strip()
    matched = [
        row for row in visible
        if supplied_base_id in {str(row.get("scopedKnowledgeBaseId") or ""), str(row.get("knowledgeBaseId") or "")}
    ]
    if len(matched) != 1:
        raise AgentPerceptionDenied("Knowledge scope must resolve to one currently readable owner.")
    canonical_id = str(matched[0].get("scopedKnowledgeBaseId") or "").strip()
    selected_source = ""
    for source in ("personal", "team", "knowledge"):
        decision = decide_agent_perception(
            policy,
            source=source,
            trigger=turn.trigger,
            requested_by_user=source in turn.requested_sources,
        )
        if decision.get("allowed") is True and any(
            str(row.get("scopedKnowledgeBaseId") or "") == canonical_id
            for row in _selected_bases(agent, policy, source, visible, decision.get("scope"))
        ):
            selected_source = source
            break
    if not selected_source:
        raise AgentPerceptionDenied("The current perception policy does not allow this knowledge item.")

    # This also requires the durable matching runtime permit for background
    # turns. Charge before entering the underlying knowledge read service.
    _consume_read_permit()
    auth_snapshot = {
        "agentId": str(getattr(authorization, "agent_id", "") or ""),
        "turnId": str(getattr(authorization, "turn_id", "") or ""),
        "decisionFingerprint": str(getattr(authorization, "decision_fingerprint", "") or ""),
        "configRevision": int(getattr(authorization, "config_revision", -1)),
        "configHash": str(getattr(authorization, "config_hash", "") or ""),
        "permissionPreset": str(getattr(authorization, "permission_preset", "") or ""),
        "executableTools": tuple(sorted(str(name) for name in getattr(authorization, "executable_tools", ()))),
    }
    return {
        "ticketVersion": 1,
        "agentId": str(agent["agentId"]),
        "knowledgeBaseId": canonical_id,
        "source": selected_source,
        "policyFingerprint": agent_perception_policy_fingerprint(policy),
        "trigger": turn.trigger,
        "requestedSources": tuple(sorted(str(name) for name in turn.requested_sources)),
        "sessionId": str(turn.session_id or ""),
        "turnId": authorized_turn_id or str(turn.turn_id or ""),
        "authorization": auth_snapshot,
    }


def finish_knowledge_item_read(
    ticket: dict[str, Any] | None,
    *,
    result_count: int,
    result_chars: int = 0,
) -> bool:
    """Recheck a configured read ticket before exposing the item result.

    A stale ticket raises ``AgentPerceptionDenied`` so callers can discard the
    just-read payload. Legacy reads have no perception ticket and pass through.
    """
    if ticket is None:
        return True
    if not isinstance(ticket, dict) or ticket.get("ticketVersion") != 1:
        raise AgentPerceptionDenied("Knowledge read ticket is invalid.")
    try:
        normalized_result_count = max(0, min(int(result_count), 1_000))
        normalized_result_chars = max(0, min(int(result_chars), 100_000))
    except (TypeError, ValueError) as exc:
        raise AgentPerceptionError("Knowledge read result counters are invalid.") from exc

    agent_id = str(ticket.get("agentId") or "").strip()
    source = str(ticket.get("source") or "").strip()
    canonical_id = str(ticket.get("knowledgeBaseId") or "").strip()
    fingerprint = str(ticket.get("policyFingerprint") or "")
    if not agent_id or source not in {"personal", "team", "knowledge"} or not canonical_id or not fingerprint:
        raise AgentPerceptionDenied("Knowledge read ticket is incomplete.")

    final_agent = _assert_policy_current(agent_id, fingerprint)
    from .access import current_perception_turn
    from core.authorization.tool_authorization_service import current_execution_authorization

    turn = current_perception_turn()
    authorization = current_execution_authorization()
    if (
        turn is None
        or turn.agent_id != agent_id
        or turn.trigger != str(ticket.get("trigger") or "")
        or tuple(sorted(str(name) for name in turn.requested_sources)) != tuple(ticket.get("requestedSources") or ())
        or (ticket.get("sessionId") and turn.session_id != ticket.get("sessionId"))
        or (ticket.get("turnId") and turn.turn_id and turn.turn_id != ticket.get("turnId"))
    ):
        raise AgentPerceptionDenied("The trusted perception turn changed during the knowledge read.")
    expected_auth = ticket.get("authorization") if isinstance(ticket.get("authorization"), dict) else {}
    if (
        authorization is None
        or str(getattr(authorization, "agent_id", "") or "") != expected_auth.get("agentId")
        or str(getattr(authorization, "turn_id", "") or "") != expected_auth.get("turnId")
        or str(getattr(authorization, "decision_fingerprint", "") or "") != expected_auth.get("decisionFingerprint")
        or int(getattr(authorization, "config_revision", -1)) != expected_auth.get("configRevision")
        or str(getattr(authorization, "config_hash", "") or "") != expected_auth.get("configHash")
        or str(getattr(authorization, "permission_preset", "") or "") != expected_auth.get("permissionPreset")
        or tuple(sorted(str(name) for name in getattr(authorization, "executable_tools", ()))) != tuple(expected_auth.get("executableTools") or ())
    ):
        raise AgentPerceptionDenied("The tool authorization changed during the knowledge read.")
    _assert_tool_authorization_current(agent_id, "read_knowledge_item_tool", authorization)
    _require_runtime_permit(authorization)

    policy = configured_policy(final_agent)
    if policy is None:
        raise AgentPerceptionDenied("Perception configuration changed during the knowledge read.")
    visible = _visible_bases(final_agent)
    matched = [row for row in visible if str(row.get("scopedKnowledgeBaseId") or "") == canonical_id]
    if len(matched) != 1:
        raise AgentPerceptionDenied("Knowledge scope was revoked during the knowledge read.")
    decision = decide_agent_perception(
        policy,
        source=source,
        trigger=turn.trigger,
        requested_by_user=source in turn.requested_sources,
    )
    if decision.get("allowed") is not True or not any(
        str(row.get("scopedKnowledgeBaseId") or "") == canonical_id
        for row in _selected_bases(final_agent, policy, source, visible, decision.get("scope"))
    ):
        raise AgentPerceptionDenied("Knowledge scope was revoked during the knowledge read.")

    _record_activity(
        agent_id,
        sources=[source],
        read_count=1,
        result_count=normalized_result_count,
        session_id=str(ticket.get("sessionId") or ""),
        turn_id=str(ticket.get("turnId") or ""),
        trigger=turn.trigger,
    )
    _event("read.completed", agent_id, {
        "source": source,
        "resultCount": normalized_result_count,
        "resultChars": normalized_result_chars,
    })
    return True


def search_perception_sources(
    agent_id: str, *, query: str, trigger: str = "task",
    sources: list[str] | None = None, requested_by_user: bool = False,
    source_scopes: dict[str, list[str]] | None = None,
    limit: int = 8,
    invoked_tool: str = "unified_memory_search_tool",
) -> dict[str, Any]:
    """Platform-owned retrieval, always bounded and ACL-filtered before reads.

    The ``trigger`` and ``requested_by_user`` compatibility arguments are not
    authority. Current-turn facts and user intent come only from the host's
    perception context; each source receives its own manual-request bit.
    Source excerpts are untrusted tool-tail data, not static system rules.
    """
    agent = _agent(agent_id)
    policy = configured_policy(agent)
    if policy is None:
        raise AgentPerceptionDenied("Perception has not been configured for this Agent.")
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_CHARS:
        raise AgentPerceptionError("Query must contain 1-1000 characters.")
    from .access import current_perception_turn

    turn = current_perception_turn()
    if turn is None or turn.agent_id != str(agent["agentId"]):
        raise AgentPerceptionDenied("No trusted perception context is bound to this Agent turn.")
    effective_trigger = turn.trigger
    requested_sources = turn.requested_sources if effective_trigger == "task" else frozenset()
    if type(limit) is not int or not 1 <= limit <= 25:
        raise AgentPerceptionError("limit must be an integer between 1 and 25.")
    if sources is not None and (not isinstance(sources, list) or any(not isinstance(name, str) for name in sources)):
        raise AgentPerceptionError("sources must be a list of source names.")
    authorized_sources = _TOOL_SOURCE_ALLOWLIST.get(str(invoked_tool or "").strip())
    if authorized_sources is None:
        raise AgentPerceptionDenied("The invoking tool is not an authorized perception reader.")
    from core.authorization.tool_authorization_service import current_execution_authorization

    authorization = current_execution_authorization()
    if (
        authorization is None
        or str(getattr(authorization, "agent_id", "")).strip() != str(agent["agentId"])
        or str(invoked_tool) not in set(getattr(authorization, "executable_tools", ()))
    ):
        raise AgentPerceptionDenied("The current Agent turn did not authorize this perception tool.")
    selected = [name for name in SOURCE_NAMES if name in authorized_sources] if sources is None else list(dict.fromkeys(sources))
    if not selected or any(name not in SOURCE_NAMES for name in selected):
        raise AgentPerceptionError("Unknown or empty perception source selection.")
    if any(name not in authorized_sources for name in selected):
        raise AgentPerceptionDenied("This tool cannot read the requested perception source.")
    scopes = {} if source_scopes is None else source_scopes
    if not isinstance(scopes, dict) or any(name not in ("team", "knowledge") or name not in selected for name in scopes):
        raise AgentPerceptionError("Only selected team and knowledge sources support temporary scopes.")
    decisions = [decide_agent_perception(
        policy, source=name, trigger=effective_trigger, requested_by_user=name in requested_sources,
        requested_scope_ids=scopes.get(name),
    ) for name in selected]
    permitted = [row["source"] for row in decisions if row["allowed"] is True]
    if not permitted:
        raise AgentPerceptionDenied("No selected source is allowed for this trigger.")
    if effective_trigger == "background":
        _require_runtime_permit(authorization)
    selected_scopes = {row["source"]: row["scope"] for row in decisions if row["allowed"] is True}
    visible = _visible_bases(agent) if any(name != "projects" for name in permitted) else []
    fingerprint = agent_perception_policy_fingerprint(policy)
    if effective_trigger == "background":
        maximum_calls = policy["background"]["maxCallsPerRun"]
        max_chars = policy["background"]["maxResultChars"]
    else:
        # Task-triggered discovery is governed by a fixed bounded allowance.
        # Editing background-run quotas must not change ordinary task search.
        maximum_calls = TASK_SEARCH_MAX_CALLS_PER_RUN
        max_chars = TASK_SEARCH_MAX_RESULT_CHARS
    results: list[dict[str, Any]] = []
    read_sources: set[str] = set()
    seen_bases: set[str] = set()
    calls = 0
    for source in permitted:
        if source == "projects":
            _assert_policy_current(agent_id, fingerprint)
            _assert_tool_authorization_current(agent_id, invoked_tool, authorization)
            from core.web.services.github_project_library_service import search_github_project_cards

            if calls < maximum_calls:
                _consume_read_permit()
                calls += 1
                cards = search_github_project_cards(query=query.strip(), limit=min(limit, 5))
                read_sources.add(source)
                for card in cards:
                    metadata = card.get("metadata") if isinstance(card.get("metadata"), dict) else {}
                    review = metadata.get("governanceReview") if isinstance(metadata.get("governanceReview"), dict) else {}
                    results.append({
                        "source": source, "kind": "project_card", "resultId": card.get("resultId", ""),
                        "title": card.get("title", ""), "fullName": metadata.get("fullName", ""),
                        "headSha": metadata.get("headSha", ""),
                        "license": metadata.get("license", ""),
                        "reviewStatus": review.get("status", "not_reviewed"),
                        "reviewReason": review.get("reason", ""),
                        "reuseBoundary": review.get("reuseBoundary", ""),
                        "evidenceRefs": list(review.get("evidenceRefs") or [])[:4],
                        "excerpt": str(metadata.get("description") or "")[:1200],
                        "untrusted": True,
                    })
            continue
        from core.web.services.unified_knowledge_search_service import search_unified_memory

        memory_policy = _directory().resolve_memory_policy_for_agent(agent_id) or {}
        if source == "personal" and memory_policy.get("enabled") is not False:
            _assert_policy_current(agent_id, fingerprint)
            if calls < maximum_calls:
                _assert_tool_authorization_current(agent_id, invoked_tool, authorization)
                _consume_read_permit()
                calls += 1
                memory_policy = _directory().resolve_memory_policy_for_agent(agent_id) or {}
                if memory_policy.get("enabled") is not False:
                    episodes = _directory().list_current_episodic_events(agent_id, limit=100)
                    results.extend(_search_episodic_events(query, episodes, limit=limit))
                    read_sources.add(source)

        for base in _selected_bases(agent, policy, source, visible, selected_scopes[source]):
            base_id = base["scopedKnowledgeBaseId"]
            if base_id in seen_bases or calls >= maximum_calls:
                continue
            # A queued request is not a durable access grant. Re-read policy
            # and ACL before each call so closing a source blocks later calls.
            current_agent = _assert_policy_current(agent_id, fingerprint)
            _assert_tool_authorization_current(agent_id, invoked_tool, authorization)
            current_visible = _visible_bases(current_agent)
            if base_id not in {row["scopedKnowledgeBaseId"] for row in _selected_bases(current_agent, policy, source, current_visible, selected_scopes[source])}:
                continue
            seen_bases.add(base_id)
            _consume_read_permit()
            calls += 1
            # An explicit base also prevents project discovery from leaking into
            # a personal/team-only request through unified search's defaults.
            payload = search_unified_memory(
                agent_id=str(agent["agentId"]), query=query.strip(), query_mode="bm25",
                knowledge_base_id=base_id, allowed_knowledge_base_ids=[base_id],
                include_user_content=False, limit=min(limit, 8), max_context_chars=min(1200, max_chars),
                private_memory_enabled=_directory().resolve_memory_policy_for_agent(agent_id).get("enabled") is not False,
            )
            read_sources.add(source)
            for item in list(payload.get("results") or []):
                results.append({**item, "source": source, "knowledgeBaseId": base_id, "untrusted": True})
    # Authorization at read start is not a durable grant. A knowledge ACL or
    # MemoryPolicy can change while the underlying search is running, so
    # validate the exact source/base pairs again before exposing any excerpt.
    final_agent = _assert_policy_current(agent_id, fingerprint)
    _assert_tool_authorization_current(agent_id, invoked_tool, authorization)
    final_memory_policy = _directory().resolve_memory_policy_for_agent(agent_id) or {}
    final_visible = _visible_bases(final_agent) if any(name != "projects" for name in permitted) else []
    final_base_sources: set[tuple[str, str]] = set()
    final_allowed_sources: set[str] = set()
    for source in permitted:
        decision = decide_agent_perception(
            policy,
            source=source,
            trigger=effective_trigger,
            requested_by_user=source in requested_sources,
            requested_scope_ids=scopes.get(source),
        )
        if decision.get("allowed") is not True:
            continue
        final_allowed_sources.add(source)
        if source == "personal" and final_memory_policy.get("enabled") is False:
            continue
        if source in {"personal", "team", "knowledge"}:
            final_base_sources.update(
                (source, str(base.get("scopedKnowledgeBaseId") or ""))
                for base in _selected_bases(final_agent, policy, source, final_visible, decision.get("scope"))
                if str(base.get("scopedKnowledgeBaseId") or "")
            )

    current_results: list[dict[str, Any]] = []
    for item in results:
        source = str(item.get("source") or "")
        if source not in final_allowed_sources:
            continue
        if source == "personal" and final_memory_policy.get("enabled") is False:
            continue
        base_id = str(item.get("knowledgeBaseId") or "")
        if base_id and (source, base_id) not in final_base_sources:
            continue
        current_results.append(item)

    bounded: list[dict[str, Any]] = []
    remaining = max_chars
    string_fields = ("resultId", "resultType", "kind", "projectId", "fullName", "title", "occurredAt", "headSha", "license", "reviewStatus", "reviewReason", "reuseBoundary", "source", "knowledgeBaseId", "knowledgeItemId", "scopedKnowledgeBaseId", "ownerType", "ownerId", "searchBackend")
    for item in current_results[:limit]:
        excerpt = str(item.get("excerpt") or item.get("content") or "")[:min(1200, remaining)]
        remaining -= len(excerpt)
        safe_item = {key: str(item.get(key) or "")[:240] for key in string_fields if key in item}
        safe_item["sourceArtifactIds"] = [str(value)[:160] for value in list(item.get("sourceArtifactIds") or [])[:8]]
        safe_item["evidenceRefs"] = [
            {key: str(ref[key])[:512] for key in ("path", "line", "startLine", "endLine", "kind", "headSha") if key in ref}
            for ref in list(item.get("evidenceRefs") or [])[:4] if isinstance(ref, dict)
        ]
        bounded.append({**safe_item, "excerpt": excerpt, "untrusted": True})
    runtime_context = _active_agent_runtime()
    _record_activity(
        agent_id,
        sources=sorted(read_sources),
        read_count=calls,
        result_count=len(bounded),
        session_id=str(runtime_context.get("sessionId") or ""),
        turn_id=str(getattr(authorization, "turn_id", "") or runtime_context.get("turnId") or ""),
        trigger=effective_trigger,
    )
    _event("search.completed", agent_id, {
        "trigger": effective_trigger, "sources": permitted, "queryHash": hashlib.sha256(query.encode("utf-8")).hexdigest()[:16],
        "queryLength": len(query), "readCount": calls, "resultCount": len(bounded),
    })
    return {
        "schemaVersion": 1, "agentId": agent_id, "trigger": effective_trigger,
        "policyFingerprint": fingerprint,
        "decisions": decisions, "results": bounded, "readCount": calls,
        "resultChars": max_chars - remaining, "untrusted": True,
    }


def _require_runtime_permit(authorization: Any | None = None) -> None:
    from .access import current_perception_turn

    turn = current_perception_turn()
    if turn is None or turn.trigger != "background":
        return
    runtime_context = _active_agent_runtime()
    if authorization is None:
        from core.authorization.tool_authorization_service import current_execution_authorization

        authorization = current_execution_authorization()
    try:
        from .runtime import require_agent_perception_permit

        require_agent_perception_permit(
            session_id=str(runtime_context.get("sessionId") or turn.session_id or ""),
            turn_id=str(getattr(authorization, "turn_id", "") or runtime_context.get("turnId") or turn.turn_id or ""),
        )
    except Exception as exc:
        raise AgentPerceptionDenied("Background perception requires a matching durable runtime permit.") from exc


def _consume_read_permit() -> None:
    _require_runtime_permit()
    from .runtime import consume_agent_perception_calls

    if not consume_agent_perception_calls(1):
        raise AgentPerceptionDenied("The current perception run has no remaining source-read budget.")


def _active_agent_runtime() -> dict[str, Any]:
    current_runtime = getattr(_directory(), "current_agent_runtime", None)
    runtime = current_runtime() if callable(current_runtime) else {}
    return runtime if isinstance(runtime, dict) else {}


def _assert_tool_authorization_current(agent_id: str, invoked_tool: str, authorization: Any) -> None:
    current_agent = _agent(agent_id)
    if (
        str(getattr(authorization, "agent_id", "")).strip() != str(current_agent.get("agentId") or "")
        or str(invoked_tool) not in set(getattr(authorization, "executable_tools", ()))
    ):
        raise AgentPerceptionDenied("The current Agent turn did not authorize this perception tool.")
    try:
        revision = int(current_agent.get("configRevision") or 0)
        authorized_revision = int(getattr(authorization, "config_revision", -1))
    except (TypeError, ValueError):
        raise AgentPerceptionDenied("The current tool authorization snapshot is invalid.")
    if revision != authorized_revision or str(current_agent.get("configHash") or "") != str(getattr(authorization, "config_hash", "") or ""):
        raise AgentPerceptionDenied("Agent tool configuration changed; start a new authorized turn.")
    runtime = _active_agent_runtime()
    runtime_agent_id = str(runtime.get("agentId") or "").strip()
    runtime_turn_id = str(runtime.get("turnId") or "").strip()
    authorized_turn_id = str(getattr(authorization, "turn_id", "") or "").strip()
    if runtime_agent_id and runtime_agent_id != str(current_agent.get("agentId") or ""):
        raise AgentPerceptionDenied("The current runtime Agent identity does not match this perception read.")
    if runtime_turn_id and runtime_turn_id != authorized_turn_id:
        raise AgentPerceptionDenied("The current runtime turn does not match this tool authorization.")


def _record_activity(
    agent_id: str,
    *,
    sources: list[str],
    read_count: int,
    result_count: int,
    session_id: str,
    turn_id: str,
    trigger: str,
) -> None:
    if not sources:
        return
    try:
        from .runtime import record_perception_activity

        record_perception_activity(
            agent_id,
            sources=sources,
            read_count=max(0, int(read_count)),
            result_count=max(0, int(result_count)),
            session_id=session_id[:160],
            turn_id=turn_id[:160],
            trigger=trigger,
        )
    except Exception:
        # Activity is a source/count projection only and must not turn a read
        # that already passed every gate into a failed tool response.
        pass


def _search_episodic_events(
    query: str,
    events: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    terms = _episodic_query_terms(query)
    if not terms:
        return []
    phrase = " ".join(str(query or "").casefold().split())
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for item in events:
        if not isinstance(item, dict) or str(item.get("validUntil") or "").strip():
            continue
        text = str(item.get("text") or "")
        normalized = " ".join(text.casefold().split())
        score = sum(1 for term in terms if term in normalized)
        if phrase and len(phrase) >= 3 and phrase in normalized:
            score += 2
        if score:
            ranked.append((score, str(item.get("occurredAt") or ""), item))
    ranked.sort(key=lambda row: (row[0], row[1], str(row[2].get("episodeId") or "")), reverse=True)
    return [
        {
            "kind": "episodic_memory",
            "source": "personal",
            "resultId": str(item.get("episodeId") or item.get("eventId") or "")[:160],
            "title": str(item.get("kind") or "personal memory")[:120],
            "occurredAt": str(item.get("occurredAt") or "")[:64],
            "excerpt": str(item.get("text") or "")[:1200],
            "untrusted": True,
        }
        for _, _, item in ranked[:max(1, min(int(limit), 25))]
    ]


def _episodic_query_terms(query: str) -> set[str]:
    normalized = str(query or "").casefold()
    terms = set(re.findall(r"[a-z0-9][a-z0-9._-]{1,}", normalized))
    for run in re.findall(r"[\u3400-\u9fff]+", normalized):
        if len(run) == 1:
            terms.add(run)
        else:
            terms.update(run[index:index + 2] for index in range(len(run) - 1))
    return terms
