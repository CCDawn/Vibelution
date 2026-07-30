"""Append-only private drafts and revision evidence for Agent configuration.

`agents.json` remains the only writable Agent configuration source. This module
stores no alternate live configuration: it records a bounded, secret-free
snapshot of an editor's draft and the configuration revision that was actually
published through the existing Agent mutation path.
"""

from __future__ import annotations

import copy
from typing import Any

from . import agent_directory_service
from .agent_config_authority import normalize_permission_preset


CHANGE_EVENT_FILE = "config_changes.jsonl"
SCHEMA_VERSION = 2
MAX_SUMMARY_LINES = 4
MAX_SUMMARY_CHARS = 480
ALLOWED_REASONING_EFFORTS = {"low", "medium", "high"}


def config_snapshot_from_agent(agent: dict[str, Any] | None) -> dict[str, Any]:
    """Return the non-secret fields edited by the Agent core-config surface."""

    payload = dict(agent or {})
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    return {
        "displayName": str(payload.get("displayName") or "").strip(),
        "llmBindings": agent_directory_service.normalize_agent_llm_bindings(
            payload.get("llmBindings") if isinstance(payload.get("llmBindings"), dict) else {},
        ),
        "reasoningEffortBySlot": _normalize_reasoning_effort(
            metadata.get("llmReasoningEffort") if isinstance(metadata, dict) else {},
        ),
        "promptTemplateId": str(payload.get("promptTemplateId") or "").strip(),
        "toolPolicyId": str(payload.get("toolPolicyId") or "").strip(),
        "toolPolicy": agent_directory_service.normalize_tool_policy(
            payload.get("toolPolicy")
            if isinstance(payload.get("toolPolicy"), dict)
            else {},
            str(payload.get("toolPolicyId") or "").strip(),
        ),
        "memoryPolicyId": str(payload.get("memoryPolicyId") or "").strip(),
        "memoryPolicy": agent_directory_service.normalize_memory_policy(
            payload.get("memoryPolicy")
            if isinstance(payload.get("memoryPolicy"), dict)
            else {},
            str(payload.get("memoryPolicyId") or "").strip(),
            str(payload.get("workspacePath") or "").strip(),
        ),
        "contextCompressionPolicy": agent_directory_service.normalize_agent_context_compression_policy(
            payload.get("contextCompressionPolicy") if isinstance(payload.get("contextCompressionPolicy"), dict) else {},
        ),
        "delegationPolicy": agent_directory_service.normalize_delegation_policy(
            metadata.get("delegationPolicy")
            if isinstance(metadata.get("delegationPolicy"), dict)
            else {},
        ),
        "supervisionPolicy": agent_directory_service.normalize_supervision_policy(
            metadata.get("supervisionPolicy")
            if isinstance(metadata.get("supervisionPolicy"), dict)
            else {},
        ),
        "permissionPreset": normalize_permission_preset(
            payload.get("permissionPreset"),
        ),
        "status": str(payload.get("status") or "active").strip() or "active",
    }


def save_agent_config_draft(
    agent_id: str,
    *,
    base_updated_at: str,
    snapshot: dict[str, Any],
    summary: str = "",
) -> dict[str, Any]:
    """Persist one draft against the current Agent revision.

    A later draft supersedes the previous active draft. It never alters
    ``agents.json`` and therefore cannot affect a running Agent by itself.
    """

    normalized_agent_id = _required_agent_id(agent_id)
    with agent_directory_service._STATE_LOCK:
        agent = _raw_agent(normalized_agent_id)
        current_updated_at = str(agent.get("updatedAt") or "").strip()
        normalized_base = str(base_updated_at or "").strip()
        if not normalized_base:
            raise agent_directory_service.AgentStateConflictError("Agent draft requires the current configuration revision.")
        if normalized_base != current_updated_at:
            raise agent_directory_service.AgentStateConflictError(
                "Agent configuration changed after this draft was opened. Refresh and retry."
            )
        path = _change_path(agent)
        events = agent_directory_service._read_jsonl(path)
        active_draft = _fold_change_events(events)["activeDraft"]
        now = agent_directory_service.utc_now_iso()
        if active_draft:
            agent_directory_service._append_jsonl(
                path,
                {
                    "schemaVersion": SCHEMA_VERSION,
                    "eventId": agent_directory_service._new_event_id("agentcfg"),
                    "eventType": "draft_superseded",
                    "draftId": active_draft["draftId"],
                    "createdAt": now,
                },
            )
        draft = {
            "schemaVersion": SCHEMA_VERSION,
            "eventId": agent_directory_service._new_event_id("agentcfg"),
            "eventType": "draft_saved",
            "draftId": agent_directory_service._new_event_id("draft"),
            "agentId": normalized_agent_id,
            "baseUpdatedAt": current_updated_at,
            "createdAt": now,
            "summary": _normalize_summary(summary),
            "snapshot": _normalize_snapshot(snapshot, fallback=agent),
        }
        draft["changedFields"] = _changed_fields(
            config_snapshot_from_agent(agent),
            draft["snapshot"],
        )
        agent_directory_service._append_jsonl(path, draft)
    _record_change_event("agent.config_draft.saved", draft, outcome="saved")
    return _public_draft(draft)


def discard_agent_config_draft(agent_id: str, draft_id: str) -> dict[str, Any]:
    """Mark the current private draft discarded without deleting audit evidence."""

    normalized_agent_id = _required_agent_id(agent_id)
    normalized_draft_id = str(draft_id or "").strip()
    if not normalized_draft_id:
        raise agent_directory_service.AgentDirectoryError("Agent draft id is required.")
    with agent_directory_service._STATE_LOCK:
        agent = _raw_agent(normalized_agent_id)
        path = _change_path(agent)
        active_draft = _fold_change_events(agent_directory_service._read_jsonl(path))["activeDraft"]
        if not active_draft or active_draft["draftId"] != normalized_draft_id:
            raise agent_directory_service.AgentDirectoryError("Only the active Agent draft can be discarded.")
        event = {
            "schemaVersion": SCHEMA_VERSION,
            "eventId": agent_directory_service._new_event_id("agentcfg"),
            "eventType": "draft_discarded",
            "draftId": normalized_draft_id,
            "agentId": normalized_agent_id,
            "createdAt": agent_directory_service.utc_now_iso(),
        }
        agent_directory_service._append_jsonl(path, event)
    _record_change_event("agent.config_draft.discarded", event, outcome="discarded")
    return {"draftId": normalized_draft_id, "status": "discarded"}


def record_agent_config_revision(
    agent_id: str,
    *,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    source: str,
    source_draft_id: str = "",
) -> dict[str, Any] | None:
    """Append one published revision after the canonical Agent write succeeds."""

    normalized_agent_id = _required_agent_id(agent_id)
    before_snapshot = config_snapshot_from_agent(before)
    after_snapshot = config_snapshot_from_agent(after)
    changed_fields = _changed_fields(before_snapshot, after_snapshot)
    if not changed_fields:
        return None
    with agent_directory_service._STATE_LOCK:
        agent = _raw_agent(normalized_agent_id)
        path = _change_path(agent)
        folded = _fold_change_events(agent_directory_service._read_jsonl(path))
        active_draft = folded["activeDraft"]
        normalized_source_draft_id = str(source_draft_id or "").strip()
        base_revision = str(before.get("updatedAt") or "").strip() if before else ""
        linked_draft_id = (
            normalized_source_draft_id
            if active_draft
            and active_draft["draftId"] == normalized_source_draft_id
            and active_draft["baseUpdatedAt"] == base_revision
            and active_draft.get("snapshot") == after_snapshot
            else ""
        )
        event = {
            "schemaVersion": SCHEMA_VERSION,
            "eventId": agent_directory_service._new_event_id("agentcfg"),
            "eventType": "revision_published",
            "revisionId": agent_directory_service._new_event_id("configrev"),
            "revisionNumber": len(folded["revisions"]) + 1,
            "agentId": normalized_agent_id,
            "publishedAt": agent_directory_service.utc_now_iso(),
            "source": _normalize_source(source),
            "sourceDraftId": linked_draft_id,
            "baseUpdatedAt": str(before.get("updatedAt") or "").strip() if before else "",
            "updatedAt": str(after.get("updatedAt") or "").strip() if after else "",
            "changedFields": changed_fields,
            "before": before_snapshot,
            "after": after_snapshot,
            "runtimeBinding": {
                "directSessionId": str(agent.get("directSessionId") or "").strip(),
                "workspacePath": str(agent.get("workspacePath") or "").strip(),
            },
        }
        agent_directory_service._append_jsonl(path, event)
    _record_change_event("agent.config_revision.published", event, outcome="published")
    return _public_revision(event)


def list_agent_config_changes(agent_id: str, *, limit: int = 12) -> dict[str, Any]:
    """Return the active private draft plus latest published revisions."""

    normalized_agent_id = _required_agent_id(agent_id)
    with agent_directory_service._STATE_LOCK:
        agent = _raw_agent(normalized_agent_id)
        folded = _fold_change_events(agent_directory_service._read_jsonl(_change_path(agent)))
        current_updated_at = str(agent.get("updatedAt") or "").strip()
    active = folded["activeDraft"]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": normalized_agent_id,
        "activeDraft": _public_draft(active, current_updated_at=current_updated_at) if active else None,
        "revisions": [
            _public_revision(item)
            for item in reversed(folded["revisions"][-max(1, min(int(limit or 12), 50)):])
        ],
    }


def _raw_agent(agent_id: str) -> dict[str, Any]:
    state, _ = agent_directory_service._load_repaired_state_for_read()
    agent = agent_directory_service._find_agent(state, agent_id)
    if not agent:
        raise agent_directory_service.AgentNotFoundError(f"Agent not found: {agent_id}")
    return copy.deepcopy(agent)


def _change_path(agent: dict[str, Any]):
    return agent_directory_service._agent_workspace_event_path(agent, CHANGE_EVENT_FILE)


def _required_agent_id(agent_id: str) -> str:
    normalized = str(agent_id or "").strip()
    if not normalized:
        raise agent_directory_service.AgentNotFoundError("Agent id is required.")
    return normalized


def _normalize_snapshot(snapshot: dict[str, Any], *, fallback: dict[str, Any]) -> dict[str, Any]:
    candidate = snapshot if isinstance(snapshot, dict) else {}
    base = config_snapshot_from_agent(fallback)
    display_name = agent_directory_service.trim_lines(
        str(candidate.get("displayName", base["displayName"]) or ""),
        max_lines=1,
    ).strip()[:120]
    return {
        "displayName": display_name,
        "llmBindings": agent_directory_service.normalize_agent_llm_bindings(
            candidate.get("llmBindings") if isinstance(candidate.get("llmBindings"), dict) else base["llmBindings"],
        ),
        "reasoningEffortBySlot": _normalize_reasoning_effort(candidate.get("reasoningEffortBySlot", base["reasoningEffortBySlot"])),
        "promptTemplateId": _short_string(candidate.get("promptTemplateId", base["promptTemplateId"]), limit=160),
        "toolPolicyId": _short_string(candidate.get("toolPolicyId", base["toolPolicyId"]), limit=160),
        "toolPolicy": agent_directory_service.normalize_tool_policy(
            candidate.get("toolPolicy")
            if isinstance(candidate.get("toolPolicy"), dict)
            else base["toolPolicy"],
            _short_string(candidate.get("toolPolicyId", base["toolPolicyId"]), limit=160),
        ),
        "memoryPolicyId": _short_string(candidate.get("memoryPolicyId", base["memoryPolicyId"]), limit=160),
        "memoryPolicy": agent_directory_service.normalize_memory_policy(
            candidate.get("memoryPolicy")
            if isinstance(candidate.get("memoryPolicy"), dict)
            else base["memoryPolicy"],
            _short_string(candidate.get("memoryPolicyId", base["memoryPolicyId"]), limit=160),
            str(fallback.get("workspacePath") or "").strip(),
        ),
        "contextCompressionPolicy": agent_directory_service.normalize_agent_context_compression_policy(
            candidate.get("contextCompressionPolicy")
            if isinstance(candidate.get("contextCompressionPolicy"), dict)
            else base["contextCompressionPolicy"],
        ),
        "delegationPolicy": agent_directory_service.normalize_delegation_policy(
            candidate.get("delegationPolicy")
            if isinstance(candidate.get("delegationPolicy"), dict)
            else base["delegationPolicy"],
        ),
        "supervisionPolicy": agent_directory_service.normalize_supervision_policy(
            candidate.get("supervisionPolicy")
            if isinstance(candidate.get("supervisionPolicy"), dict)
            else base["supervisionPolicy"],
        ),
        "permissionPreset": normalize_permission_preset(
            candidate.get("permissionPreset", base["permissionPreset"]),
        ),
        "status": _normalize_status(candidate.get("status", base["status"])),
    }


def _normalize_reasoning_effort(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(slot).strip()[:80]: str(effort).strip()
        for slot, effort in value.items()
        if str(slot).strip() and str(effort).strip() in ALLOWED_REASONING_EFFORTS
    }


def _normalize_status(value: Any) -> str:
    normalized = str(value or "active").strip().lower()
    return normalized if normalized in {"active", "archived"} else "active"


def _short_string(value: Any, *, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _normalize_summary(value: str) -> str:
    summary = agent_directory_service.trim_lines(str(value or ""), max_lines=MAX_SUMMARY_LINES).strip()
    return summary[:MAX_SUMMARY_CHARS]


def _normalize_source(value: str) -> str:
    normalized = _short_string(value, limit=80).lower()
    return normalized or "direct_patch"


def _changed_fields(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    return [key for key in before if before.get(key) != after.get(key)]


def _fold_change_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    drafts: dict[str, dict[str, Any]] = {}
    active_draft_id = ""
    revisions: list[dict[str, Any]] = []
    for event in events:
        event_type = str(event.get("eventType") or "").strip()
        draft_id = str(event.get("draftId") or "").strip()
        if event_type == "draft_saved" and draft_id:
            drafts[draft_id] = event
            active_draft_id = draft_id
        elif event_type in {"draft_discarded", "draft_superseded"} and draft_id and active_draft_id == draft_id:
            active_draft_id = ""
        elif event_type == "revision_published":
            revisions.append(event)
            source_draft_id = str(event.get("sourceDraftId") or "").strip()
            if source_draft_id and active_draft_id == source_draft_id:
                active_draft_id = ""
    return {"activeDraft": drafts.get(active_draft_id), "revisions": revisions}


def _public_draft(draft: dict[str, Any] | None, *, current_updated_at: str = "") -> dict[str, Any] | None:
    if not draft:
        return None
    base_updated_at = str(draft.get("baseUpdatedAt") or "").strip()
    return {
        "draftId": str(draft.get("draftId") or "").strip(),
        "status": "active",
        "baseUpdatedAt": base_updated_at,
        "createdAt": str(draft.get("createdAt") or "").strip(),
        "summary": str(draft.get("summary") or "").strip(),
        "changedFields": list(draft.get("changedFields") or []),
        "stale": bool(current_updated_at and base_updated_at != current_updated_at),
    }


def _public_revision(revision: dict[str, Any]) -> dict[str, Any]:
    runtime_binding = revision.get("runtimeBinding") if isinstance(revision.get("runtimeBinding"), dict) else {}
    return {
        "revisionId": str(revision.get("revisionId") or "").strip(),
        "revisionNumber": int(revision.get("revisionNumber") or 0),
        "publishedAt": str(revision.get("publishedAt") or "").strip(),
        "source": str(revision.get("source") or "").strip(),
        "sourceDraftId": str(revision.get("sourceDraftId") or "").strip(),
        "changedFields": list(revision.get("changedFields") or []),
        "runtimeBinding": {
            "directSessionId": str(runtime_binding.get("directSessionId") or "").strip(),
        },
    }


def _record_change_event(event_code: str, payload: dict[str, Any], *, outcome: str) -> None:
    try:
        runtime_binding = payload.get("runtimeBinding") if isinstance(payload.get("runtimeBinding"), dict) else {}
        agent_directory_service.record_runtime_scene_event(
            "agent_directory",
            "config_change",
            event_code,
            message=event_code,
            level="info",
            outcome=outcome,
            fields={
                "agentId": str(payload.get("agentId") or "").strip(),
                "draftId": str(payload.get("draftId") or payload.get("sourceDraftId") or "").strip(),
                "revisionId": str(payload.get("revisionId") or "").strip(),
                "changedFieldCount": len(list(payload.get("changedFields") or [])),
                "directSessionId": str(runtime_binding.get("directSessionId") or "").strip(),
            },
            lifecycle=True,
        )
    except Exception:
        return
