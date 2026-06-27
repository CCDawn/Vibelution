"""Team-scoped knowledge base storage and governance service."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.chat.chat_task_types import trim_lines

from . import agent_directory_service, chat_room_service, team_service
from .runtime_scene_service import record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = 1
SOURCE_TYPES = {
    "team_chat_refinement",
    "external_search_refinement",
    "pdf_refinement",
    "agent_authored",
    "runtime_evidence_refinement",
    "manual_user_entry",
}
INGESTION_ADAPTERS = {
    "team_chat_refinement": {
        "label": "Team chat refinement",
        "requiredSourceRef": ["roomId", "messageRange|roundId"],
        "optionalSourceRef": ["teamId", "threadId"],
        "evidenceKinds": ["message_range", "round"],
    },
    "external_search_refinement": {
        "label": "External search refinement",
        "requiredSourceRef": ["url|query"],
        "optionalSourceRef": ["retrievedAt", "searchEngine", "rank"],
        "evidenceKinds": ["url", "query", "excerpt"],
    },
    "pdf_refinement": {
        "label": "PDF refinement",
        "requiredSourceRef": ["filePath|url"],
        "optionalSourceRef": ["pageRange", "documentHash"],
        "evidenceKinds": ["file", "page_range", "excerpt"],
    },
    "agent_authored": {
        "label": "Agent authored",
        "requiredSourceRef": ["agentId"],
        "optionalSourceRef": ["sessionId", "turnId"],
        "evidenceKinds": ["agent_note"],
    },
    "runtime_evidence_refinement": {
        "label": "Runtime evidence refinement",
        "requiredSourceRef": ["runtimeSceneId|runId"],
        "optionalSourceRef": ["logPath", "eventCode", "artifactPath"],
        "evidenceKinds": ["runtime_scene", "log_ref", "artifact"],
    },
    "manual_user_entry": {
        "label": "Manual user entry",
        "requiredSourceRef": ["note|title"],
        "optionalSourceRef": ["author", "context"],
        "evidenceKinds": ["manual_note"],
    },
}
REVIEW_ROLES = {"owner", "lead", "steward", "knowledge_steward", "coordinator"}
IMPORTANCE_LEVELS = {"low", "medium", "high", "critical"}
STABILITY_VALUES = {"temporary", "evolving", "stable", "deprecated"}
SCOPES = {"agent", "team", "project", "global"}
REVIEW_PRIORITIES = {"normal", "elevated", "urgent"}
SUGGESTION_STATUSES = {"pending", "applied", "rejected"}
KNOWLEDGE_OWNER_TYPES = {"team", "agent"}
SOURCE_INBOX_STATUSES = {"pending", "accepted", "rejected", "duplicate", "needs_more_context"}
SOURCE_REVIEW_DECISIONS = {"accepted", "rejected", "duplicate", "needs_more_context"}
CENTRAL_SOURCE_STATUSES = {"active", "archived", "superseded"}
_SAFE_ID_FRAGMENT = re.compile(r"[^A-Za-z0-9_.-]+")
_SEARCH_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_.-]+|[\u4e00-\u9fff]")
_LOCK = threading.RLock()


class TeamKnowledgeError(ValueError):
    """Raised when a team knowledge request is invalid."""


class TeamKnowledgeNotFoundError(TeamKnowledgeError):
    """Raised when a knowledge resource does not exist."""


class TeamKnowledgePermissionError(TeamKnowledgeError):
    """Raised when an actor cannot perform the requested knowledge action."""


class TeamKnowledgeAmbiguousKnowledgeBaseError(TeamKnowledgeError):
    """Raised when an unscoped knowledge base id matches multiple owners."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_knowledge_overview(*, agent_id: str = "", internal: bool = False) -> dict[str, Any]:
    """Return formal knowledge bases visible to an optional Agent."""

    _sync_roots()
    visible_bases: list[dict[str, Any]] = []
    pending_proposals = 0
    item_count = 0
    source_count = 0
    for owner in _iter_knowledge_owners(agent_id=agent_id, include_archived=False, include_all_agents=internal):
        for base in _knowledge_bases_for_owner(owner):
            if not _can_access(owner, base, agent_id, "read", internal=internal):
                continue
            stats = _knowledge_base_stats_for_owner(owner, str(base.get("knowledgeBaseId") or ""))
            pending_proposals += stats["pendingProposalCount"]
            item_count += stats["itemCount"]
            source_count += stats["sourceArtifactCount"]
            visible_bases.append(
                {
                    **_knowledge_base_to_api(base, owner),
                    "stats": stats,
                    "pendingProposals": _pending_proposals_for_base(owner, str(base.get("knowledgeBaseId") or "")),
                    "permissions": _permissions_for_actor(owner, base, agent_id, internal=internal),
                }
            )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": str(agent_id or "").strip(),
        "summary": {
            "knowledgeBaseCount": len(visible_bases),
            "pendingProposalCount": pending_proposals,
            "itemCount": item_count,
            "sourceArtifactCount": source_count,
        },
        "knowledgeBases": visible_bases,
        "updatedAt": utc_now_iso(),
    }


def get_knowledge_steward_overview(*, agent_id: str = "", internal: bool = False) -> dict[str, Any]:
    """Return the default knowledge steward Agent and its read-only governance posture."""

    payload = _build_knowledge_steward_overview(agent_id=agent_id, internal=internal)
    _record_event(
        "knowledge.steward.overview.viewed",
        "",
        "",
        actor_agent_id=str((payload.get("steward") or {}).get("agentId") or agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID),
        fields={
            "stewardAgentId": str((payload.get("steward") or {}).get("agentId") or ""),
            "openTaskCount": int((payload["governance"]["summary"] or {}).get("openTaskCount") or 0),
            "permissionBoundary": str((payload.get("steward") or {}).get("permissionBoundary") or ""),
        },
    )
    return payload


def _build_knowledge_steward_overview(
    *,
    agent_id: str = "",
    governance_tasks: dict[str, Any] | None = None,
    internal: bool = False,
) -> dict[str, Any]:
    _sync_roots()
    steward = agent_directory_service.get_agent(agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID)
    steward_id = str((steward or {}).get("agentId") or agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID).strip()
    normalized_agent_id = str(agent_id or "").strip()
    governance_tasks = governance_tasks or list_knowledge_governance_tasks(
        agent_id=normalized_agent_id,
        status="all",
        internal=internal,
    )
    task_summary = dict(governance_tasks.get("summary") or {})
    open_tasks = [task for task in list(governance_tasks.get("tasks") or []) if str(task.get("status") or "") == "open"]
    open_tasks.sort(
        key=lambda item: (
            _priority_rank(str(item.get("priority") or "")),
            str(item.get("updatedAt") or item.get("createdAt") or ""),
        ),
        reverse=True,
    )
    permission_boundary = "governed_stage_writeback_ingestion"
    metadata = dict((steward or {}).get("metadata") or {}) if isinstance((steward or {}).get("metadata"), dict) else {}
    if metadata.get("permissionBoundary"):
        permission_boundary = str(metadata.get("permissionBoundary") or permission_boundary).strip() or permission_boundary
    tool_policy = dict((steward or {}).get("toolPolicy") or {}) if isinstance((steward or {}).get("toolPolicy"), dict) else {}
    memory_policy = dict((steward or {}).get("memoryPolicy") or {}) if isinstance((steward or {}).get("memoryPolicy"), dict) else {}
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "steward": {
            "agentId": steward_id,
            "agentCode": str((steward or {}).get("agentCode") or "").strip(),
            "displayName": str((steward or {}).get("displayName") or "").strip() or "知识库管理员",
            "functionalDisplayName": str(metadata.get("functionalDisplayName") or "知识库管理员").strip(),
            "status": str((steward or {}).get("status") or "missing").strip(),
            "directSessionId": str((steward or {}).get("directSessionId") or "").strip(),
            "directChatPath": f"/chat?session={str((steward or {}).get('directSessionId') or '').strip()}" if str((steward or {}).get("directSessionId") or "").strip() else "/chat",
            "managedDomain": str(metadata.get("managedDomain") or "team_knowledge").strip(),
            "permissionBoundary": permission_boundary,
            "protected": bool(metadata.get("protected")),
            "taskProfile": (steward or {}).get("taskProfile") if isinstance((steward or {}).get("taskProfile"), dict) else {},
            "toolPolicy": {
                "policyId": str(tool_policy.get("policyId") or (steward or {}).get("toolPolicyId") or "").strip(),
                "allowedTools": list(tool_policy.get("allowedTools") or []),
                "preferredTools": list(tool_policy.get("preferredTools") or []),
                "networkAccess": str(tool_policy.get("networkAccess") or "none").strip(),
                "mutationAccess": str(tool_policy.get("mutationAccess") or "restricted").strip(),
                "maxCallsPerTurn": int(tool_policy.get("maxCallsPerTurn") or 0),
            },
            "memoryPolicy": {
                "policyId": str(memory_policy.get("policyId") or (steward or {}).get("memoryPolicyId") or "").strip(),
                "readSharedGroups": list(memory_policy.get("readSharedGroups") or []),
                "writeSharedGroups": list(memory_policy.get("writeSharedGroups") or []),
                "readKnowledgeBaseIds": list(memory_policy.get("readKnowledgeBaseIds") or []),
                "proposeKnowledgeBaseIds": list(memory_policy.get("proposeKnowledgeBaseIds") or []),
                "reviewKnowledgeBaseIds": list(memory_policy.get("reviewKnowledgeBaseIds") or []),
                "rateKnowledgeBaseIds": list(memory_policy.get("rateKnowledgeBaseIds") or []),
            },
        },
        "governance": {
            "summary": {
                **task_summary,
                "openTaskCount": sum(1 for task in list(governance_tasks.get("tasks") or []) if str(task.get("status") or "") == "open"),
            },
            "openTasks": open_tasks[:8],
        },
        "operatingBoundary": {
            "canDirectlyApplyKnowledge": True,
            "canDirectlyIngestScreenedSources": True,
            "canDeleteKnowledge": False,
            "canChangeAcl": False,
            "canBypassReviewer": False,
            "formalKnowledgeRequiresReviewer": False,
            "screeningAgentIsReviewer": True,
            "knowledgeBodiesInPrompt": False,
        },
        "updatedAt": utc_now_iso(),
    }
    return payload


def list_ingestion_adapters() -> dict[str, Any]:
    """Return the standard adapter contract for semi-automatic knowledge ingestion."""

    adapters = [
        {
            "sourceType": source_type,
            **dict(INGESTION_ADAPTERS[source_type]),
            "outputContract": {
                "creates": ["SourceArtifact", "RefinementProposal"],
                "proposalStatus": "pending",
                "createsKnowledgeItem": False,
                "requiresReview": True,
            },
            "directReviewContract": {
                "entrypoint": "owner_source_inbox_review",
                "creates": ["CentralSource", "SourceArtifact", "KnowledgeItem"],
                "createsKnowledgeItem": True,
                "requiresScreening": True,
                "proposalStatus": "not_required",
            },
        }
        for source_type in sorted(INGESTION_ADAPTERS)
    ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "adapters": adapters,
        "summary": {"adapterCount": len(adapters)},
        "updatedAt": utc_now_iso(),
    }


def list_team_knowledge_bases(team_id: str, *, agent_id: str = "", internal: bool = False) -> dict[str, Any]:
    team = _require_team_identity(team_id) if internal else _require_team(team_id)
    owner = _owner_context("team", team["teamId"], team=team)
    bases = []
    for base in _knowledge_bases_for_owner(owner):
        if _can_access(owner, base, agent_id, "read", internal=internal):
            bases.append(
                {
                    **_knowledge_base_to_api(base, owner),
                    "stats": _knowledge_base_stats_for_owner(owner, str(base.get("knowledgeBaseId") or "")),
                    "pendingProposals": _pending_proposals_for_base(owner, str(base.get("knowledgeBaseId") or "")),
                    "permissions": _permissions_for_actor(owner, base, agent_id, internal=internal),
                }
            )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": team["teamId"],
        "knowledgeBases": bases,
        "summary": {"knowledgeBaseCount": len(bases)},
        "updatedAt": utc_now_iso(),
    }


def list_agent_knowledge_bases(agent_id: str, *, actor_agent_id: str = "", internal: bool = False) -> dict[str, Any]:
    agent = _require_agent(agent_id)
    owner = _owner_context("agent", agent["agentId"], agent=agent)
    bases = []
    for base in _knowledge_bases_for_owner(owner):
        if _can_access(owner, base, actor_agent_id, "read", internal=internal):
            bases.append(
                {
                    **_knowledge_base_to_api(base, owner),
                    "stats": _knowledge_base_stats_for_owner(owner, str(base.get("knowledgeBaseId") or "")),
                    "pendingProposals": _pending_proposals_for_base(owner, str(base.get("knowledgeBaseId") or "")),
                    "permissions": _permissions_for_actor(owner, base, actor_agent_id, internal=internal),
                }
            )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": agent["agentId"],
        "knowledgeBases": bases,
        "summary": {"knowledgeBaseCount": len(bases)},
        "updatedAt": utc_now_iso(),
    }


def create_knowledge_base(
    team_id: str,
    *,
    name: str,
    description: str = "",
    actor_agent_id: str = "",
    acl: dict[str, Any] | None = None,
) -> dict[str, Any]:
    team = _require_team(team_id)
    owner = _owner_context("team", team["teamId"], team=team)
    normalized_actor = str(actor_agent_id or "").strip()
    if not normalized_actor:
        raise TeamKnowledgePermissionError("Agent identity is required to create a team knowledge base.")
    if not _member_role(team, normalized_actor):
        raise TeamKnowledgePermissionError("Only Team members can create a team knowledge base.")
    return _create_knowledge_base_for_owner(owner, name=name, description=description, actor_agent_id=normalized_actor, acl=acl)


def ensure_knowledge_base_review_grant(knowledge_base_id: str, agent_id: str) -> dict[str, Any]:
    """Idempotently grant one agent review permission on a knowledge base.

    Used by the trusted team knowledge-ingestion gate to honor separation of
    duties: the steward proposes, a distinct coordinator/lead reviews. This only
    extends the per-base ACL review grant for the named agent; it never widens
    the shared REVIEW_ROLES set or any other knowledge base.
    """
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise TeamKnowledgePermissionError("Agent identity is required to grant knowledge base review.")
    owner, base = _require_base_with_owner(knowledge_base_id)
    with _LOCK:
        state = _load_bases_state_for_owner(owner)
        bases = state.get("knowledgeBases") if isinstance(state.get("knowledgeBases"), list) else []
        target = _find_by_id(bases, "knowledgeBaseId", base["knowledgeBaseId"])
        if not target:
            raise TeamKnowledgeNotFoundError("Knowledge base not found.")
        acl = _normalize_acl(target.get("acl"))
        review_grants = list(acl["grants"].get("review") or [])
        if normalized_agent_id not in review_grants:
            review_grants.append(normalized_agent_id)
            acl["grants"]["review"] = _unique_strings(review_grants)
            target["acl"] = acl
            target["updatedAt"] = utc_now_iso()
            _save_bases_state_for_owner(owner, state)
        return dict(target)


def create_agent_knowledge_base(
    agent_id: str,
    *,
    name: str,
    description: str = "",
    actor_agent_id: str = "",
    acl: dict[str, Any] | None = None,
) -> dict[str, Any]:
    agent = _require_agent(agent_id)
    owner = _owner_context("agent", agent["agentId"], agent=agent)
    normalized_actor = str(actor_agent_id or "").strip()
    if not normalized_actor:
        raise TeamKnowledgePermissionError("Agent identity is required to create a private formal knowledge base.")
    if normalized_actor != agent["agentId"]:
        raise TeamKnowledgePermissionError("Only the owning Agent can create its private formal knowledge base.")
    return _create_knowledge_base_for_owner(owner, name=name, description=description, actor_agent_id=normalized_actor, acl=acl)


def _create_knowledge_base_for_owner(
    owner: dict[str, Any],
    *,
    name: str,
    description: str = "",
    actor_agent_id: str = "",
    acl: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_name = trim_lines(name or "", max_lines=1).strip()
    if not normalized_name:
        raise TeamKnowledgeError("Knowledge base name is required.")
    now = utc_now_iso()
    owner_type = str(owner.get("ownerType") or "team")
    owner_id = str(owner.get("ownerId") or "").strip()
    with _LOCK:
        state = _load_bases_state_for_owner(owner)
        existing_ids = {str(item.get("knowledgeBaseId") or "") for item in state.get("knowledgeBases") or []}
        knowledge_base_id = _new_id("kb", existing_ids, normalized_name)
        base = {
            "knowledgeBaseId": knowledge_base_id,
            "ownerType": owner_type,
            "ownerId": owner_id,
            "teamId": owner_id if owner_type == "team" else "",
            "agentId": owner_id if owner_type == "agent" else "",
            "name": normalized_name,
            "description": trim_lines(description or "", max_lines=6).strip(),
            "status": "active",
            "acl": _normalize_acl(acl),
            "createdAt": now,
            "updatedAt": now,
        }
        state.setdefault("knowledgeBases", []).append(base)
        state["updatedAt"] = now
        _save_bases_state_for_owner(owner, state)
        _append_audit(owner, "knowledge_base.created", base, actor_agent_id=actor_agent_id)
    _record_event("knowledge.knowledge_base.created", owner, knowledge_base_id, actor_agent_id=actor_agent_id)
    return {
        **_knowledge_base_to_api(base, owner),
        "stats": _knowledge_base_stats_for_owner(owner, knowledge_base_id),
        "permissions": _permissions_for_actor(owner, base, actor_agent_id),
    }


def update_owner_source_governance(
    owner_type: str,
    owner_id: str,
    *,
    local_steward_agent_ids: list[str] | None = None,
    actor_agent_id: str = "",
) -> dict[str, Any]:
    """Configure owner-local source stewards for the owner inbox."""

    owner = _require_owner_context(owner_type, owner_id)
    actor_id = str(actor_agent_id or "").strip()
    if not _can_configure_owner_source_governance(owner, actor_id):
        raise TeamKnowledgePermissionError("Agent is not allowed to configure this source governance scope.")
    now = utc_now_iso()
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "localStewardAgentIds": _unique_strings(local_steward_agent_ids or []),
        "updatedByAgentId": actor_id,
        "updatedAt": now,
    }
    with _LOCK:
        _write_json(_owner_source_governance_path(owner), payload)
        _append_audit(owner, "knowledge.source_governance.updated", payload, actor_agent_id=actor_id)
    _record_event(
        "knowledge.source_governance.updated",
        owner,
        "",
        actor_agent_id=actor_id,
        fields={"localStewardCount": len(payload["localStewardAgentIds"])},
    )
    return payload


def collect_source_to_inbox(
    owner_type: str,
    owner_id: str,
    *,
    source_type: str,
    source_ref: dict[str, Any] | None = None,
    original_content: str = "",
    original_filename: str = "",
    source_created_at: str = "",
    captured_by: str = "",
    source_hash: str = "",
    evidence_range: dict[str, Any] | None = None,
    title: str = "",
    summary: str = "",
    actor_agent_id: str = "",
) -> dict[str, Any]:
    """Stage raw source material inside the owning Team/Agent workspace."""

    owner = _require_owner_context(owner_type, owner_id)
    actor_id = str(actor_agent_id or captured_by or "").strip()
    if not _can_collect_owner_source(owner, actor_id):
        raise TeamKnowledgePermissionError("Agent is not allowed to collect sources for this owner.")
    normalized_type = str(source_type or "").strip()
    if normalized_type not in SOURCE_TYPES:
        raise TeamKnowledgeError(f"Unsupported source type: {source_type}")
    normalized_ref = source_ref if isinstance(source_ref, dict) else {}
    if normalized_type == "team_chat_refinement":
        if str(owner.get("ownerType") or "") != "team":
            raise TeamKnowledgeError("team_chat_refinement sources require a Team owner.")
        _validate_team_chat_source(owner["team"], normalized_ref)
    now = utc_now_iso()
    inbox_source_id = _new_event_id("inboxsrc")
    safe_title = trim_lines(title or normalized_type, max_lines=1).strip()
    safe_summary = trim_lines(summary or "", max_lines=16).strip()
    safe_content = str(original_content or "")
    normalized_hash = trim_lines(
        source_hash or _source_hash_with_content(normalized_ref, safe_title, safe_summary, safe_content),
        max_lines=1,
    ).strip()
    original_path = _write_owner_inbox_source_file(
        owner,
        inbox_source_id,
        original_filename=original_filename,
        original_content=safe_content,
        source_ref=normalized_ref,
        title=safe_title,
        summary=safe_summary,
    )
    source = {
        "schemaVersion": SCHEMA_VERSION,
        "inboxSourceId": inbox_source_id,
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "sourceType": normalized_type,
        "sourceRef": _bounded_dict(normalized_ref),
        "sourceCreatedAt": trim_lines(source_created_at or "", max_lines=1).strip(),
        "capturedBy": trim_lines(captured_by or actor_id or "user", max_lines=1).strip(),
        "capturedAt": now,
        "sourceHash": normalized_hash,
        "evidenceRange": _bounded_dict(evidence_range if isinstance(evidence_range, dict) else {}),
        "title": safe_title,
        "summary": safe_summary,
        "originalFilename": _safe_source_filename(original_filename, default=f"{normalized_type}.txt"),
        "originalPath": _project_relative_path(original_path),
        "status": "pending",
        "curationStatus": "owner_inbox",
        "centralSourceId": "",
        "dedupeStatus": "",
        "reviewedAt": "",
        "reviewedByAgentId": "",
        "resolutionNote": "",
        "updatedAt": now,
    }
    with _LOCK:
        sources = _read_jsonl(_owner_source_index_path(owner))
        sources.append(source)
        _write_jsonl(_owner_source_index_path(owner), sources)
        _rewrite_owner_source_review_queue_locked(owner, sources)
        _append_audit(owner, "knowledge.source_inbox.collected", source, actor_agent_id=actor_id)
    _record_event(
        "knowledge.source_inbox.collected",
        owner,
        "",
        actor_agent_id=actor_id,
        fields={"inboxSourceId": inbox_source_id, "sourceType": normalized_type},
    )
    return source


def list_owner_source_inbox(
    owner_type: str,
    owner_id: str,
    *,
    agent_id: str = "",
    status: str = "",
) -> dict[str, Any]:
    owner = _require_owner_context(owner_type, owner_id)
    actor_id = str(agent_id or "").strip()
    if not _can_read_owner_source_inbox(owner, actor_id):
        raise TeamKnowledgePermissionError("Agent is not allowed to read this owner source inbox.")
    normalized_status = str(status or "").strip().lower()
    if normalized_status and normalized_status not in SOURCE_INBOX_STATUSES:
        raise TeamKnowledgeError(f"Unsupported source inbox status: {status}")
    sources = _read_jsonl(_owner_source_index_path(owner))
    if normalized_status:
        sources = [item for item in sources if str(item.get("status") or "") == normalized_status]
    sources.sort(key=lambda item: str(item.get("updatedAt") or item.get("capturedAt") or ""), reverse=True)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "actorAgentId": actor_id,
        "summary": _source_inbox_summary(sources),
        "sources": sources,
        "updatedAt": utc_now_iso(),
    }


def review_owner_inbox_source(
    owner_type: str,
    owner_id: str,
    inbox_source_id: str,
    *,
    decision: str,
    reviewed_by_agent_id: str = "",
    resolution_note: str = "",
    duplicate_of: str = "",
    ingest_on_accept: bool = False,
    knowledge_base_id: str = "",
    knowledge_title: str = "",
    knowledge_summary: str = "",
    knowledge_content: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Resolve one owner inbox source and optionally direct-ingest it as formal knowledge."""

    owner = _require_owner_context(owner_type, owner_id)
    reviewer_id = str(reviewed_by_agent_id or "").strip()
    if not _can_review_owner_source(owner, reviewer_id):
        raise TeamKnowledgePermissionError("Agent is not allowed to review this owner source inbox.")
    normalized_decision = _normalize_source_review_decision(decision)
    wants_direct_ingest = bool(
        ingest_on_accept
        or str(knowledge_base_id or "").strip()
        or str(knowledge_content or "").strip()
        or str(knowledge_title or "").strip()
    )
    if wants_direct_ingest and normalized_decision != "accepted":
        raise TeamKnowledgeError("Direct ingestion is only supported for accepted source reviews.")
    now = utc_now_iso()
    direct_ingestion: dict[str, Any] | None = None
    with _LOCK:
        sources = _read_jsonl(_owner_source_index_path(owner))
        source = _find_by_id(sources, "inboxSourceId", inbox_source_id)
        if not source:
            raise TeamKnowledgeNotFoundError("Inbox source not found.")
        current_status = str(source.get("status") or "")
        if current_status not in {"pending", "needs_more_context"}:
            raise TeamKnowledgeError("Only pending or needs_more_context inbox sources can be reviewed.")
        central_source: dict[str, Any] | None = None
        promotion: dict[str, Any] | None = None
        if normalized_decision == "accepted":
            central_source, promotion = _promote_owner_source_to_central_locked(
                owner,
                source,
                reviewer_id=reviewer_id,
                resolution_note=resolution_note,
            )
            source["status"] = "accepted"
            source["curationStatus"] = "central_curated"
            source["centralSourceId"] = central_source["centralSourceId"]
            source["dedupeStatus"] = str(promotion.get("dedupeStatus") or "")
            if wants_direct_ingest:
                direct_ingestion = _direct_ingest_accepted_source_locked(
                    owner,
                    source,
                    central_source,
                    reviewer_id=reviewer_id,
                    knowledge_base_id=knowledge_base_id,
                    knowledge_title=knowledge_title,
                    knowledge_summary=knowledge_summary,
                    knowledge_content=knowledge_content,
                    tags=tags,
                    now=now,
                )
                source["curationStatus"] = "formal_knowledge"
                source["knowledgeBaseId"] = direct_ingestion["knowledgeBaseId"]
                source["knowledgeItemId"] = direct_ingestion["item"]["knowledgeItemId"]
        elif normalized_decision == "duplicate":
            central_source = _resolve_duplicate_central_source_locked(source, duplicate_of=duplicate_of)
            promotion = _append_owner_ref_for_central_source_locked(
                owner,
                source,
                central_source,
                reviewer_id=reviewer_id,
                decision="duplicate",
                resolution_note=resolution_note,
                dedupe_status="explicit_duplicate",
            )
            source["status"] = "duplicate"
            source["curationStatus"] = "central_curated"
            source["centralSourceId"] = central_source["centralSourceId"]
            source["dedupeStatus"] = "explicit_duplicate"
        elif normalized_decision == "rejected":
            source["status"] = "rejected"
            source["curationStatus"] = "owner_rejected"
            source["dedupeStatus"] = ""
            _append_jsonl(_owner_source_rejected_path(owner), {**source, "reviewedAt": now, "reviewedByAgentId": reviewer_id})
        else:
            source["status"] = "needs_more_context"
            source["curationStatus"] = "owner_inbox"
            source["dedupeStatus"] = ""
        source["reviewedAt"] = now
        source["reviewedByAgentId"] = reviewer_id
        source["resolutionNote"] = trim_lines(resolution_note or "", max_lines=6).strip()
        source["updatedAt"] = now
        _write_jsonl(_owner_source_index_path(owner), sources)
        _rewrite_owner_source_review_queue_locked(owner, sources)
        _append_audit(owner, "knowledge.source_inbox.reviewed", source, actor_agent_id=reviewer_id)
    _record_event(
        "knowledge.source_inbox.reviewed",
        owner,
        "",
        actor_agent_id=reviewer_id,
        fields={
            "inboxSourceId": str(inbox_source_id or "").strip(),
            "decision": normalized_decision,
            "centralSourceId": str((central_source or {}).get("centralSourceId") or ""),
            "directIngestionStatus": str((direct_ingestion or {}).get("status") or ""),
            "knowledgeItemId": str(((direct_ingestion or {}).get("item") or {}).get("knowledgeItemId") or ""),
        },
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "source": source,
        "centralSource": central_source,
        "promotion": promotion,
        "directIngestion": direct_ingestion,
        "updatedAt": utc_now_iso(),
    }


def create_source_artifact_from_central_source(
    knowledge_base_id: str,
    central_source_id: str,
    *,
    actor_agent_id: str = "",
    evidence_range: dict[str, Any] | None = None,
    title: str = "",
    summary: str = "",
) -> dict[str, Any]:
    owner, base = _require_base_with_owner(knowledge_base_id)
    _require_permission(owner, base, actor_agent_id, "propose")
    central_source, owner_ref = _require_central_source_for_owner(owner, central_source_id, actor_agent_id=actor_agent_id)
    source_ref = _bounded_dict(central_source.get("sourceRef") if isinstance(central_source.get("sourceRef"), dict) else {})
    source_ref.update({
        "centralSourceId": central_source["centralSourceId"],
        "centralPath": central_source.get("centralPath") or "",
        "sourceHash": central_source.get("sourceHash") or "",
        "originalOwnerType": owner_ref.get("ownerType") or central_source.get("originOwnerType") or "",
        "originalOwnerId": owner_ref.get("ownerId") or central_source.get("originOwnerId") or "",
        "originalPath": owner_ref.get("originalPath") or central_source.get("originOriginalPath") or "",
    })
    return create_source_artifact(
        knowledge_base_id,
        source_type=str(central_source.get("sourceType") or "manual_user_entry"),
        source_ref=source_ref,
        source_created_at=str(central_source.get("sourceCreatedAt") or ""),
        captured_by=actor_agent_id,
        source_hash=str(central_source.get("sourceHash") or ""),
        evidence_range=evidence_range,
        title=title or str(central_source.get("title") or ""),
        summary=summary or str(central_source.get("summary") or ""),
        actor_agent_id=actor_agent_id,
        central_source_id=central_source["centralSourceId"],
        inbox_source_id=str(owner_ref.get("inboxSourceId") or ""),
    )


def list_central_sources(
    *,
    agent_id: str = "",
    owner_type: str = "",
    owner_id: str = "",
    internal: bool = False,
) -> dict[str, Any]:
    """List accepted central source records visible to the actor."""

    normalized_actor = str(agent_id or "").strip()
    normalized_owner_type = _normalize_owner_type(owner_type)
    normalized_owner_id = str(owner_id or "").strip()
    registry = _read_jsonl(_central_source_registry_path())
    owner_refs = _read_jsonl(_central_owner_refs_path())
    visible_owner_refs = [
        ref
        for ref in owner_refs
        if _central_owner_ref_visible(ref, normalized_actor, internal=internal)
        and (not normalized_owner_type or str(ref.get("ownerType") or "") == normalized_owner_type)
        and (not normalized_owner_id or str(ref.get("ownerId") or "") == normalized_owner_id)
    ]
    visible_source_ids = {str(ref.get("centralSourceId") or "") for ref in visible_owner_refs if str(ref.get("centralSourceId") or "").strip()}
    if internal or _is_global_knowledge_steward(normalized_actor):
        visible_source_ids.update(str(source.get("centralSourceId") or "") for source in registry if str(source.get("centralSourceId") or ""))
    sources = [source for source in registry if str(source.get("centralSourceId") or "") in visible_source_ids]
    sources.sort(key=lambda item: str(item.get("updatedAt") or item.get("acceptedAt") or ""), reverse=True)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": normalized_actor,
        "ownerType": normalized_owner_type,
        "ownerId": normalized_owner_id,
        "summary": {"centralSourceCount": len(sources), "ownerRefCount": len(visible_owner_refs)},
        "centralSources": sources,
        "ownerRefs": visible_owner_refs,
        "updatedAt": utc_now_iso(),
    }


def knowledge_base_policy_allows(knowledge_base_id: str, policy_ids: set[str] | list[str] | tuple[str, ...]) -> bool:
    """Return whether a tool memoryPolicy allows a raw or owner-scoped knowledge base id."""

    normalized_policy_ids = {str(item or "").strip() for item in list(policy_ids or []) if str(item or "").strip()}
    if not normalized_policy_ids:
        return True
    requested = str(knowledge_base_id or "").strip()
    if not requested:
        return False
    if requested in normalized_policy_ids:
        return True
    owner_type, owner_id, base_id = _parse_owner_scoped_knowledge_base_id(requested)
    has_scoped_policy = any(_parse_owner_scoped_knowledge_base_id(item)[0] for item in normalized_policy_ids)
    if owner_type and owner_id and base_id and base_id in normalized_policy_ids and not has_scoped_policy:
        return True
    return False


def create_source_artifact(
    knowledge_base_id: str,
    *,
    source_type: str,
    source_ref: dict[str, Any] | None = None,
    source_created_at: str = "",
    captured_by: str = "",
    source_hash: str = "",
    evidence_range: dict[str, Any] | None = None,
    title: str = "",
    summary: str = "",
    actor_agent_id: str = "",
    central_source_id: str = "",
    inbox_source_id: str = "",
) -> dict[str, Any]:
    owner, base = _require_base_with_owner(knowledge_base_id)
    _require_permission(owner, base, actor_agent_id, "propose")
    central_source: dict[str, Any] | None = None
    owner_ref: dict[str, Any] = {}
    normalized_central_source_id = str(central_source_id or "").strip()
    if not normalized_central_source_id:
        raise TeamKnowledgeError("SourceArtifact requires centralSourceId; collect the source to the owner inbox and promote it first.")
    if normalized_central_source_id:
        central_source, owner_ref = _require_central_source_for_owner(
            owner,
            normalized_central_source_id,
            actor_agent_id=actor_agent_id,
        )
    normalized_type = str(source_type or "").strip()
    if not normalized_type and central_source:
        normalized_type = str(central_source.get("sourceType") or "").strip()
    normalized_ref = source_ref if isinstance(source_ref, dict) else {}
    if normalized_type == "team_chat_refinement":
        if str(owner.get("ownerType") or "") != "team":
            raise TeamKnowledgeError("team_chat_refinement sources require a Team knowledge base.")
        _validate_team_chat_source(owner["team"], normalized_ref)
    if central_source:
        central_source_type = str(central_source.get("sourceType") or "").strip()
        if normalized_type != central_source_type:
            raise TeamKnowledgeError("SourceArtifact sourceType must match the central source.")
        central_ref = _bounded_dict(central_source.get("sourceRef") if isinstance(central_source.get("sourceRef"), dict) else {})
        central_ref.update({
            "centralSourceId": central_source["centralSourceId"],
            "centralPath": central_source.get("centralPath") or "",
            "sourceHash": central_source.get("sourceHash") or "",
            "originalOwnerType": owner_ref.get("ownerType") or central_source.get("originOwnerType") or "",
            "originalOwnerId": owner_ref.get("ownerId") or central_source.get("originOwnerId") or "",
            "originalPath": owner_ref.get("originalPath") or central_source.get("originOriginalPath") or "",
        })
        source_ref = central_ref
        source_created_at = str(central_source.get("sourceCreatedAt") or source_created_at or "")
        source_hash = str(central_source.get("sourceHash") or source_hash or "")
    if normalized_type not in SOURCE_TYPES:
        raise TeamKnowledgeError(f"Unsupported source type: {source_type}")
    now = utc_now_iso()
    artifact = {
        "sourceArtifactId": _new_event_id("src"),
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "knowledgeBaseId": base["knowledgeBaseId"],
        "sourceType": normalized_type,
        "sourceRef": _bounded_dict(normalized_ref),
        "capturedAt": now,
        "sourceCreatedAt": trim_lines(source_created_at or "", max_lines=1).strip(),
        "capturedBy": trim_lines(captured_by or actor_agent_id or "user", max_lines=1).strip(),
        "sourceHash": trim_lines(source_hash or str((central_source or {}).get("sourceHash") or "") or _source_hash(normalized_ref, title, summary), max_lines=1).strip(),
        "evidenceRange": _bounded_dict(evidence_range if isinstance(evidence_range, dict) else {}),
        "title": trim_lines(title or normalized_type, max_lines=1).strip(),
        "summary": trim_lines(summary or "", max_lines=8).strip(),
        "centralSourceId": normalized_central_source_id,
        "inboxSourceId": trim_lines(inbox_source_id or str(owner_ref.get("inboxSourceId") or ""), max_lines=1).strip(),
        "curationStatus": "central_curated" if normalized_central_source_id else "source_artifact",
    }
    with _LOCK:
        _append_jsonl(_source_artifacts_path_for_owner(owner), artifact)
        _append_audit(owner, "knowledge.source.registered", artifact, actor_agent_id=actor_agent_id)
    _record_event(
        "knowledge.source.registered",
        owner,
        base["knowledgeBaseId"],
        actor_agent_id=actor_agent_id,
        fields={"sourceArtifactId": artifact["sourceArtifactId"], "sourceType": artifact["sourceType"]},
    )
    return artifact


def create_refinement_proposal(
    knowledge_base_id: str,
    *,
    source_artifact_ids: list[str] | None,
    proposed_by_agent_id: str = "",
    title: str,
    summary: str = "",
    content: str,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    owner, base = _require_base_with_owner(knowledge_base_id)
    actor_agent_id = str(proposed_by_agent_id or "").strip()
    _require_permission(owner, base, actor_agent_id, "propose")
    normalized_title = trim_lines(title or "", max_lines=1).strip()
    normalized_content = trim_lines(content or "", max_lines=80).strip()
    if not normalized_title:
        raise TeamKnowledgeError("Proposal title is required.")
    if not normalized_content:
        raise TeamKnowledgeError("Proposal content is required.")
    artifact_ids = _unique_strings(source_artifact_ids or [])
    if not artifact_ids:
        raise TeamKnowledgeError("Formal knowledge proposals require at least one central source artifact.")
    central_source_ids: list[str] = []
    artifacts_by_id = {
        str(item.get("sourceArtifactId") or ""): item
        for item in _source_artifacts_for_base(owner, base["knowledgeBaseId"])
    }
    known_artifacts = set(artifacts_by_id)
    missing = [item for item in artifact_ids if item not in known_artifacts]
    if missing:
        raise TeamKnowledgeError(f"Unknown source artifact ids: {', '.join(missing[:3])}")
    ungoverned = [
        item_id
        for item_id in artifact_ids
        if not str((artifacts_by_id.get(item_id) or {}).get("centralSourceId") or "").strip()
    ]
    if ungoverned:
        raise TeamKnowledgeError("Formal knowledge proposals require central-curated source artifacts.")
    central_source_ids = _unique_strings(
        str((artifacts_by_id.get(item_id) or {}).get("centralSourceId") or "")
        for item_id in artifact_ids
    )
    now = utc_now_iso()
    proposal = {
        "proposalId": _new_event_id("kprop"),
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "targetKnowledgeBaseId": base["knowledgeBaseId"],
        "sourceArtifactIds": artifact_ids,
        "centralSourceIds": central_source_ids,
        "proposedByAgentId": actor_agent_id,
        "status": "pending",
        "title": normalized_title,
        "summary": trim_lines(summary or "", max_lines=6).strip(),
        "content": normalized_content,
        "tags": _unique_strings(tags or [])[:24],
        "createdAt": now,
        "updatedAt": now,
        "reviewedAt": "",
        "reviewedByAgentId": "",
        "resolutionNote": "",
        "batchId": "",
        "knowledgeItemIds": [],
    }
    with _LOCK:
        _append_jsonl(_proposals_path_for_owner(owner), proposal)
        _append_audit(owner, "knowledge.proposal.created", proposal, actor_agent_id=actor_agent_id)
    _record_event(
        "knowledge.proposal.created",
        owner,
        base["knowledgeBaseId"],
        actor_agent_id=actor_agent_id,
        fields={"proposalId": proposal["proposalId"], "sourceArtifactCount": len(artifact_ids)},
    )
    return proposal


def create_ingestion_package(
    knowledge_base_id: str,
    *,
    source_type: str,
    source_ref: dict[str, Any] | None = None,
    source_created_at: str = "",
    captured_by: str = "",
    evidence_range: dict[str, Any] | None = None,
    source_title: str = "",
    source_summary: str = "",
    excerpt: str = "",
    proposed_by_agent_id: str = "",
    central_source_id: str = "",
    proposal_title: str = "",
    proposal_summary: str = "",
    proposal_content: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Create one source artifact and one pending proposal from a semi-automatic adapter."""

    owner, base = _require_base_with_owner(knowledge_base_id)
    actor_agent_id = str(proposed_by_agent_id or captured_by or "").strip()
    _require_permission(owner, base, actor_agent_id, "propose")
    normalized_type = str(source_type or "").strip()
    if normalized_type not in SOURCE_TYPES:
        raise TeamKnowledgeError(f"Unsupported source type: {source_type}")
    normalized_excerpt = trim_lines(excerpt or "", max_lines=24).strip()
    normalized_source_summary = trim_lines(source_summary or normalized_excerpt, max_lines=8).strip()
    normalized_proposal_title = trim_lines(proposal_title or source_title or normalized_type, max_lines=1).strip()
    normalized_proposal_summary = trim_lines(proposal_summary or normalized_source_summary, max_lines=6).strip()
    normalized_content = trim_lines(proposal_content or normalized_excerpt or normalized_source_summary, max_lines=80).strip()
    if not normalized_content:
        raise TeamKnowledgeError("Ingestion requires proposalContent, excerpt, or sourceSummary.")
    source = create_source_artifact(
        knowledge_base_id,
        source_type=normalized_type,
        source_ref=source_ref,
        source_created_at=source_created_at,
        captured_by=captured_by or actor_agent_id,
        evidence_range=evidence_range,
        title=source_title or normalized_proposal_title,
        summary=normalized_source_summary,
        actor_agent_id=actor_agent_id,
        central_source_id=central_source_id,
    )
    proposal = create_refinement_proposal(
        knowledge_base_id,
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=actor_agent_id,
        title=normalized_proposal_title,
        summary=normalized_proposal_summary,
        content=normalized_content,
        tags=tags,
    )
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "knowledgeBaseId": base["knowledgeBaseId"],
        "status": "submitted",
        "sourceArtifact": source,
        "proposal": proposal,
        "updatedAt": utc_now_iso(),
    }
    _append_audit(owner, "knowledge.ingestion.adapter.created", proposal, actor_agent_id=actor_agent_id)
    _record_event(
        "knowledge.ingestion.adapter.created",
        owner,
        base["knowledgeBaseId"],
        actor_agent_id=actor_agent_id,
        fields={
            "sourceArtifactId": source["sourceArtifactId"],
            "proposalId": proposal["proposalId"],
            "sourceType": normalized_type,
        },
    )
    return payload


def review_refinement_proposal(
    knowledge_base_id: str,
    proposal_id: str,
    *,
    status: str,
    reviewed_by_agent_id: str = "",
    resolution_note: str = "",
) -> dict[str, Any]:
    owner, base = _require_base_with_owner(knowledge_base_id)
    reviewer_id = str(reviewed_by_agent_id or "").strip()
    _require_permission(owner, base, reviewer_id, "review")
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in {"approved", "applied", "rejected"}:
        raise TeamKnowledgeError("Review status must be approved, applied, or rejected.")
    with _LOCK:
        proposals = _read_jsonl(_proposals_path_for_owner(owner))
        proposal = _find_by_id(proposals, "proposalId", proposal_id)
        if not proposal or str(proposal.get("targetKnowledgeBaseId") or "") != base["knowledgeBaseId"]:
            raise TeamKnowledgeNotFoundError("Knowledge proposal not found.")
        if str(proposal.get("status") or "") != "pending":
            raise TeamKnowledgeError("Only pending proposals can be reviewed.")
        now = utc_now_iso()
        proposal["status"] = "rejected" if normalized_status == "rejected" else "applied"
        proposal["updatedAt"] = now
        proposal["reviewedAt"] = now
        proposal["reviewedByAgentId"] = reviewer_id
        proposal["resolutionNote"] = trim_lines(resolution_note or "", max_lines=4).strip()
        batch: dict[str, Any] | None = None
        item: dict[str, Any] | None = None
        if proposal["status"] == "applied":
            batch = _batch_from_proposal(owner, base, proposal, reviewer_id, now)
            item = _item_from_proposal(owner, base, proposal, batch, reviewer_id, now)
            proposal["batchId"] = batch["batchId"]
            proposal["knowledgeItemIds"] = [item["knowledgeItemId"]]
            _append_jsonl(_batches_path_for_owner(owner), batch)
            _append_jsonl(_items_path_for_owner(owner), item)
            _append_audit(owner, "knowledge.batch.applied", batch, actor_agent_id=reviewer_id)
        _write_jsonl(_proposals_path_for_owner(owner), proposals)
        _append_audit(owner, "knowledge.proposal.reviewed", proposal, actor_agent_id=reviewer_id)
    _record_event(
        "knowledge.proposal.reviewed",
        owner,
        base["knowledgeBaseId"],
        actor_agent_id=reviewer_id,
        fields={"proposalId": proposal["proposalId"], "status": proposal["status"], "batchId": proposal.get("batchId") or ""},
    )
    if batch:
        _record_event(
            "knowledge.batch.applied",
            owner,
            base["knowledgeBaseId"],
            actor_agent_id=reviewer_id,
            fields={"batchId": batch["batchId"], "knowledgeItemCount": 1},
        )
    return {"proposal": proposal, "batch": batch, "item": item}


def list_knowledge_items(knowledge_base_id: str, *, agent_id: str = "") -> dict[str, Any]:
    owner, base = _require_base_with_owner(knowledge_base_id)
    _require_permission(owner, base, agent_id, "read")
    items = [
        item
        for item in _read_jsonl(_items_path_for_owner(owner))
        if str(item.get("knowledgeBaseId") or "") == base["knowledgeBaseId"]
    ]
    items.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "knowledgeBase": _knowledge_base_to_api(base, owner),
        "items": items,
        "summary": {"itemCount": len(items)},
        "updatedAt": utc_now_iso(),
    }


def update_knowledge_item_metadata(
    knowledge_base_id: str,
    knowledge_item_id: str,
    *,
    metadata_patch: dict[str, Any],
    actor_agent_id: str = "",
) -> dict[str, Any]:
    owner, base = _require_base_with_owner(knowledge_base_id)
    actor_id = str(actor_agent_id or "").strip()
    _require_permission(owner, base, actor_id, "review")
    normalized_item_id = str(knowledge_item_id or "").strip()
    if not normalized_item_id:
        raise TeamKnowledgeError("Knowledge item id is required.")
    if not isinstance(metadata_patch, dict) or not metadata_patch:
        raise TeamKnowledgeError("Knowledge item metadata patch is required.")
    now = utc_now_iso()
    with _LOCK:
        items = _read_jsonl(_items_path_for_owner(owner))
        item = _find_by_id(items, "knowledgeItemId", normalized_item_id)
        if not item or str(item.get("knowledgeBaseId") or "") != base["knowledgeBaseId"]:
            raise TeamKnowledgeNotFoundError("Knowledge item not found.")
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        metadata.update(_bounded_dict(metadata_patch))
        item["metadata"] = metadata
        item["updatedAt"] = now
        _write_jsonl(_items_path_for_owner(owner), items)
        _append_audit(owner, "knowledge.item.metadata.updated", item, actor_agent_id=actor_id)
    _record_event(
        "knowledge.item.metadata.updated",
        owner,
        base["knowledgeBaseId"],
        actor_agent_id=actor_id,
        fields={"knowledgeItemId": item["knowledgeItemId"], "metadataKeys": sorted(_bounded_dict(metadata_patch).keys())},
    )
    return item


def list_knowledge_governance_tasks(*, agent_id: str = "", status: str = "open", internal: bool = False) -> dict[str, Any]:
    """Return a reviewer-facing queue derived from proposals, rating suggestions, and source-only evidence."""

    _sync_roots()
    normalized_status = str(status or "open").strip().lower()
    if normalized_status not in {"open", "closed", "all"}:
        raise TeamKnowledgeError(f"Unsupported governance task status: {status}")
    tasks: list[dict[str, Any]] = []
    actor_id = str(agent_id or "").strip()
    for owner in _iter_knowledge_owners(agent_id=actor_id, include_archived=True, include_all_agents=internal):
        for base in _knowledge_bases_for_owner(owner):
            base_id = str(base.get("knowledgeBaseId") or "")
            permissions = _permissions_for_actor(owner, base, actor_id, internal=internal)
            if not permissions["canRead"]:
                continue
            proposals = [
                proposal
                for proposal in _read_jsonl(_proposals_path_for_owner(owner))
                if str(proposal.get("targetKnowledgeBaseId") or "") == base_id
            ]
            proposal_source_ids = {
                source_id
                for proposal in proposals
                for source_id in [str(value or "") for value in list(proposal.get("sourceArtifactIds") or [])]
                if source_id
            }
            for proposal in proposals:
                proposal_status = str(proposal.get("status") or "")
                task_closed = proposal_status != "pending"
                if not _task_status_matches(task_closed, normalized_status):
                    continue
                tasks.append(
                    _governance_task(
                        owner,
                        base,
                        task_type="proposal_review",
                        status="closed" if task_closed else "open",
                        priority="elevated" if not task_closed else "normal",
                        title=str(proposal.get("title") or "Review proposal"),
                        summary=str(proposal.get("summary") or proposal.get("content") or ""),
                        target_id=str(proposal.get("proposalId") or ""),
                        target_status=proposal_status,
                        created_at=str(proposal.get("createdAt") or ""),
                        updated_at=str(proposal.get("updatedAt") or ""),
                        permissions=permissions,
                        source_artifact_ids=[str(value) for value in list(proposal.get("sourceArtifactIds") or []) if str(value or "").strip()],
                    )
                )
            for suggestion in _read_jsonl(_rating_suggestions_path_for_owner(owner)):
                if str(suggestion.get("knowledgeBaseId") or "") != base_id:
                    continue
                suggestion_status = str(suggestion.get("status") or "")
                task_closed = suggestion_status != "pending"
                if not _task_status_matches(task_closed, normalized_status):
                    continue
                tasks.append(
                    _governance_task(
                        owner,
                        base,
                        task_type="rating_review",
                        status="closed" if task_closed else "open",
                        priority=str(suggestion.get("reviewPriority") or "normal"),
                        title=f"{suggestion.get('importanceLevel') or 'medium'} rating suggestion",
                        summary=str(suggestion.get("markingReason") or ""),
                        target_id=str(suggestion.get("suggestionId") or ""),
                        target_status=suggestion_status,
                        created_at=str(suggestion.get("createdAt") or ""),
                        updated_at=str(suggestion.get("updatedAt") or ""),
                        permissions=permissions,
                        source_artifact_ids=[],
                    )
                )
            if normalized_status in {"open", "all"}:
                for artifact in _source_artifacts_for_base(owner, base_id):
                    source_id = str(artifact.get("sourceArtifactId") or "")
                    if source_id in proposal_source_ids:
                        continue
                    tasks.append(
                        _governance_task(
                            owner,
                            base,
                            task_type="source_needs_proposal",
                            status="open",
                            priority="normal",
                            title=str(artifact.get("title") or "Source needs proposal"),
                            summary=str(artifact.get("summary") or ""),
                            target_id=source_id,
                            target_status="source_only",
                            created_at=str(artifact.get("capturedAt") or ""),
                            updated_at=str(artifact.get("capturedAt") or ""),
                            permissions=permissions,
                            source_artifact_ids=[source_id],
                        )
                    )
    tasks.sort(key=lambda item: (_priority_rank(str(item.get("priority") or "")), str(item.get("updatedAt") or item.get("createdAt") or "")), reverse=True)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": actor_id,
        "tasks": tasks,
        "summary": {
            "taskCount": len(tasks),
            "openTaskCount": sum(1 for task in tasks if task.get("status") == "open"),
            "proposalReviewCount": sum(1 for task in tasks if task.get("taskType") == "proposal_review"),
            "ratingReviewCount": sum(1 for task in tasks if task.get("taskType") == "rating_review"),
            "sourceNeedsProposalCount": sum(1 for task in tasks if task.get("taskType") == "source_needs_proposal"),
        },
        "updatedAt": utc_now_iso(),
    }


def list_knowledge_steward_recommendations(*, agent_id: str = "", limit: int = 12, internal: bool = False) -> dict[str, Any]:
    """Return read-only steward recommendations derived from open governance tasks."""

    payload = _build_knowledge_steward_recommendations(agent_id=agent_id, limit=limit, internal=internal)
    _record_event(
        "knowledge.steward.recommendations.viewed",
        "",
        "",
        actor_agent_id=str(payload.get("stewardAgentId") or agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID),
        fields={
            "agentId": str(payload.get("agentId") or ""),
            "recommendationCount": payload["summary"]["recommendationCount"],
            "visibleRecommendationCount": payload["summary"]["visibleRecommendationCount"],
        },
    )
    return payload


def _build_knowledge_steward_recommendations(
    *,
    agent_id: str = "",
    limit: int = 12,
    tasks_payload: dict[str, Any] | None = None,
    internal: bool = False,
) -> dict[str, Any]:
    _sync_roots()
    steward = agent_directory_service.get_agent(agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID)
    steward_id = str((steward or {}).get("agentId") or agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID).strip()
    normalized_agent_id = str(agent_id or "").strip()
    bounded_limit = max(1, min(50, int(limit or 12)))
    tasks_payload = tasks_payload or list_knowledge_governance_tasks(agent_id=normalized_agent_id, status="open", internal=internal)
    recommendations = [_steward_recommendation_from_task(task) for task in list(tasks_payload.get("tasks") or [])]
    recommendations.sort(
        key=lambda item: (
            _priority_rank(str(item.get("priority") or "")),
            str(item.get("updatedAt") or item.get("createdAt") or ""),
        ),
        reverse=True,
    )
    visible_recommendations = recommendations[:bounded_limit]
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": normalized_agent_id,
        "stewardAgentId": steward_id,
        "recommendations": visible_recommendations,
        "summary": {
            "recommendationCount": len(recommendations),
            "visibleRecommendationCount": len(visible_recommendations),
            "proposalReviewCount": sum(1 for item in recommendations if item.get("recommendedAction") == "review_proposal"),
            "ratingReviewCount": sum(1 for item in recommendations if item.get("recommendedAction") == "review_rating_suggestion"),
            "proposalDraftCount": sum(1 for item in recommendations if item.get("recommendedAction") == "draft_refinement_proposal"),
        },
        "operatingBoundary": {
            "canDirectlyApplyKnowledge": False,
            "canDeleteKnowledge": False,
            "canChangeAcl": False,
            "canBypassReviewer": False,
            "recommendationsOnly": True,
            "formalKnowledgeRequiresReviewer": True,
        },
        "updatedAt": utc_now_iso(),
    }
    return payload


def get_knowledge_steward_workbench(*, agent_id: str = "", limit: int = 12, internal: bool = False) -> dict[str, Any]:
    """Return the knowledge base admin's consolidated read-only workbench."""

    payload = _build_knowledge_steward_workbench(agent_id=agent_id, limit=limit, internal=internal)
    _record_event(
        "knowledge.steward.workbench.viewed",
        "",
        "",
        actor_agent_id=str((payload.get("steward") or {}).get("agentId") or agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID),
        fields={
            "agentId": str(payload.get("agentId") or ""),
            "openTaskCount": int(payload["summary"].get("openTaskCount") or 0),
            "recommendationCount": int(payload["summary"].get("recommendationCount") or 0),
            "stageCount": len(payload.get("stages") or []),
        },
    )
    return payload


def _build_knowledge_steward_workbench(
    *,
    agent_id: str = "",
    limit: int = 12,
    overview: dict[str, Any] | None = None,
    tasks_payload: dict[str, Any] | None = None,
    recommendations_payload: dict[str, Any] | None = None,
    internal: bool = False,
) -> dict[str, Any]:
    _sync_roots()
    normalized_agent_id = str(agent_id or "").strip()
    bounded_limit = max(1, min(50, int(limit or 12)))
    overview = overview or _build_knowledge_steward_overview(agent_id=normalized_agent_id, internal=internal)
    tasks_payload = tasks_payload or list_knowledge_governance_tasks(agent_id=normalized_agent_id, status="open", internal=internal)
    recommendations_payload = recommendations_payload or _build_knowledge_steward_recommendations(
        agent_id=normalized_agent_id,
        limit=bounded_limit,
        tasks_payload=tasks_payload,
        internal=internal,
    )
    recommendations = list(recommendations_payload.get("recommendations") or [])
    tasks = list(tasks_payload.get("tasks") or [])
    stages = [
        _steward_workbench_stage(
            "source_to_proposal",
            "Source evidence to proposal",
            "Turn registered evidence into pending refinement proposals without creating formal knowledge.",
            "draft_refinement_proposal",
            recommendations,
            tasks,
            expected_task_type="source_needs_proposal",
            next_tool="knowledge_ingestion_tool or knowledge_proposal_tool",
        ),
        _steward_workbench_stage(
            "proposal_review",
            "Proposal review",
            "Inspect source evidence and wait for a reviewer-capable Agent to approve or reject proposals.",
            "review_proposal",
            recommendations,
            tasks,
            expected_task_type="proposal_review",
            next_tool="review_refinement_proposal API / UI reviewer action",
        ),
        _steward_workbench_stage(
            "rating_review",
            "Rating review",
            "Confirm or reject importance, confidence, stability, and priority suggestions.",
            "review_rating_suggestion",
            recommendations,
            tasks,
            expected_task_type="rating_review",
            next_tool="rating suggestion review API / UI reviewer action",
        ),
    ]
    next_actions = [
        {
            "actionId": f"next:{item.get('recommendationId') or index}",
            "recommendedAction": str(item.get("recommendedAction") or ""),
            "priority": str(item.get("priority") or "normal"),
            "title": str(item.get("title") or ""),
            "knowledgeBaseId": str(item.get("knowledgeBaseId") or ""),
            "knowledgeBaseName": str(item.get("knowledgeBaseName") or ""),
            "targetId": str(item.get("targetId") or ""),
            "requiresReviewer": bool(item.get("requiresReviewer")),
            "canExecuteWithCurrentActor": bool(item.get("canExecuteWithCurrentActor")),
            "nextStep": str(item.get("nextStep") or ""),
        }
        for index, item in enumerate(recommendations[: min(6, bounded_limit)])
    ]
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": normalized_agent_id,
        "steward": overview.get("steward") or {},
        "summary": {
            **dict(tasks_payload.get("summary") or {}),
            **{
                "recommendationCount": int((recommendations_payload.get("summary") or {}).get("recommendationCount") or 0),
                "visibleRecommendationCount": int((recommendations_payload.get("summary") or {}).get("visibleRecommendationCount") or 0),
                "stageCount": len(stages),
                "blockedStageCount": sum(1 for stage in stages if int(stage.get("openCount") or 0) and not int(stage.get("executableCount") or 0)),
            },
        },
        "stages": stages,
        "nextActions": next_actions,
        "acceptanceChecklist": [
            {"id": "source_registered", "label": "Every candidate keeps SourceArtifact ids and timestamps.", "required": True},
            {"id": "proposal_reviewed", "label": "Formal knowledge is created only after reviewer approval.", "required": True},
            {"id": "rating_reviewed", "label": "Importance and stability marks stay pending until reviewed.", "required": True},
            {"id": "trace_available", "label": "Trace view can reconstruct source -> proposal -> batch/item -> rating.", "required": True},
        ],
        "operatingBoundary": {
            **dict(overview.get("operatingBoundary") or {}),
            "recommendationsOnly": True,
            "canDirectlyApplyKnowledge": False,
            "canDeleteKnowledge": False,
            "canChangeAcl": False,
            "canBypassReviewer": False,
            "formalKnowledgeRequiresReviewer": True,
        },
        "updatedAt": utc_now_iso(),
    }
    return payload


def get_knowledge_trace(knowledge_base_id: str, target_id: str, *, agent_id: str = "") -> dict[str, Any]:
    """Return the source -> proposal -> batch -> item -> rating trail for one knowledge object."""

    owner, base = _require_base_with_owner(knowledge_base_id)
    _require_permission(owner, base, agent_id, "read")
    normalized_target_id = str(target_id or "").strip()
    if not normalized_target_id:
        raise TeamKnowledgeError("Knowledge trace target id is required.")
    artifacts = _source_artifacts_for_base(owner, base["knowledgeBaseId"])
    proposals = [
        proposal
        for proposal in _read_jsonl(_proposals_path_for_owner(owner))
        if str(proposal.get("targetKnowledgeBaseId") or "") == base["knowledgeBaseId"]
    ]
    batches = [
        batch
        for batch in _read_jsonl(_batches_path_for_owner(owner))
        if str(batch.get("knowledgeBaseId") or "") == base["knowledgeBaseId"]
    ]
    items = [
        item
        for item in _read_jsonl(_items_path_for_owner(owner))
        if str(item.get("knowledgeBaseId") or "") == base["knowledgeBaseId"]
    ]
    suggestions = [
        suggestion
        for suggestion in _read_jsonl(_rating_suggestions_path_for_owner(owner))
        if str(suggestion.get("knowledgeBaseId") or "") == base["knowledgeBaseId"]
    ]
    target_type = "unknown"
    source_ids: set[str] = set()
    proposal_ids: set[str] = set()
    batch_ids: set[str] = set()
    item_ids: set[str] = set()
    suggestion_ids: set[str] = set()
    if _find_by_id(items, "knowledgeItemId", normalized_target_id):
        target_type = "knowledge_item"
        item_ids.add(normalized_target_id)
    elif _find_by_id(proposals, "proposalId", normalized_target_id):
        target_type = "proposal"
        proposal_ids.add(normalized_target_id)
    elif _find_by_id(artifacts, "sourceArtifactId", normalized_target_id):
        target_type = "source_artifact"
        source_ids.add(normalized_target_id)
    elif _find_by_id(suggestions, "suggestionId", normalized_target_id):
        target_type = "rating_suggestion"
        suggestion_ids.add(normalized_target_id)
    else:
        raise TeamKnowledgeNotFoundError("Knowledge trace target not found.")

    changed = True
    while changed:
        changed = False
        for item in items:
            item_id = str(item.get("knowledgeItemId") or "")
            if item_id in item_ids:
                if _add_all(source_ids, [str(value or "") for value in list(item.get("sourceArtifactIds") or [])]):
                    changed = True
                if _add_all(batch_ids, [str(item.get("batchId") or "")]):
                    changed = True
            if str(item.get("batchId") or "") in batch_ids and item_id:
                if _add_all(item_ids, [item_id]):
                    changed = True
        for batch in batches:
            batch_id = str(batch.get("batchId") or "")
            if batch_id in batch_ids:
                if _add_all(proposal_ids, [str(value or "") for value in list(batch.get("proposalIds") or [])]):
                    changed = True
                if _add_all(source_ids, [str(value or "") for value in list(batch.get("sourceArtifactIds") or [])]):
                    changed = True
        for proposal in proposals:
            proposal_id = str(proposal.get("proposalId") or "")
            if proposal_id in proposal_ids or any(str(value or "") in source_ids for value in list(proposal.get("sourceArtifactIds") or [])):
                if proposal_id and _add_all(proposal_ids, [proposal_id]):
                    changed = True
                if _add_all(source_ids, [str(value or "") for value in list(proposal.get("sourceArtifactIds") or [])]):
                    changed = True
                if _add_all(batch_ids, [str(proposal.get("batchId") or "")]):
                    changed = True
                if _add_all(item_ids, [str(value or "") for value in list(proposal.get("knowledgeItemIds") or [])]):
                    changed = True
        for suggestion in suggestions:
            suggestion_id = str(suggestion.get("suggestionId") or "")
            if str(suggestion.get("knowledgeItemId") or "") in item_ids or str(suggestion.get("proposalId") or "") in proposal_ids:
                if suggestion_id and _add_all(suggestion_ids, [suggestion_id]):
                    changed = True
                if _add_all(item_ids, [str(suggestion.get("knowledgeItemId") or "")]):
                    changed = True
                if _add_all(proposal_ids, [str(suggestion.get("proposalId") or "")]):
                    changed = True
    nodes = {
        "sourceArtifacts": [item for item in artifacts if str(item.get("sourceArtifactId") or "") in source_ids],
        "proposals": [item for item in proposals if str(item.get("proposalId") or "") in proposal_ids],
        "batches": [item for item in batches if str(item.get("batchId") or "") in batch_ids],
        "items": [item for item in items if str(item.get("knowledgeItemId") or "") in item_ids],
        "ratingSuggestions": [item for item in suggestions if str(item.get("suggestionId") or "") in suggestion_ids],
    }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "knowledgeBase": _knowledge_base_to_api(base, owner),
        "targetId": normalized_target_id,
        "targetType": target_type,
        "nodes": nodes,
        "summary": {key: len(value) for key, value in nodes.items()},
        "updatedAt": utc_now_iso(),
    }


def update_knowledge_item_rating(
    knowledge_base_id: str,
    knowledge_item_id: str,
    *,
    actor_agent_id: str = "",
    importance_level: str = "",
    confidence: float | None = None,
    stability: str = "",
    scope: str = "",
    review_priority: str = "",
    marking_reason: str = "",
) -> dict[str, Any]:
    owner, base = _require_base_with_owner(knowledge_base_id)
    _require_permission(owner, base, actor_agent_id, "review")
    with _LOCK:
        items = _read_jsonl(_items_path_for_owner(owner))
        item = _find_by_id(items, "knowledgeItemId", knowledge_item_id)
        if not item or str(item.get("knowledgeBaseId") or "") != base["knowledgeBaseId"]:
            raise TeamKnowledgeNotFoundError("Knowledge item not found.")
        if importance_level:
            item["importanceLevel"] = _enum_value(importance_level, IMPORTANCE_LEVELS, "importance level")
        if confidence is not None:
            item["confidence"] = max(0.0, min(1.0, float(confidence)))
        if stability:
            item["stability"] = _enum_value(stability, STABILITY_VALUES, "stability")
        if scope:
            item["scope"] = _enum_value(scope, SCOPES, "scope")
        if review_priority:
            item["reviewPriority"] = _enum_value(review_priority, REVIEW_PRIORITIES, "review priority")
        now = utc_now_iso()
        item["markedBy"] = trim_lines(actor_agent_id or "user", max_lines=1).strip()
        item["markedAt"] = now
        item["markingReason"] = trim_lines(marking_reason or "", max_lines=4).strip()
        item["updatedAt"] = now
        _write_jsonl(_items_path_for_owner(owner), items)
        _append_audit(owner, "knowledge.item.rating.updated", item, actor_agent_id=actor_agent_id)
    _record_event(
        "knowledge.item.rating.updated",
        owner,
        base["knowledgeBaseId"],
        actor_agent_id=actor_agent_id,
        fields={"knowledgeItemId": item["knowledgeItemId"], "importanceLevel": item.get("importanceLevel")},
    )
    return item


def create_rating_suggestion(
    knowledge_base_id: str,
    *,
    suggested_by_agent_id: str = "",
    target_type: str = "",
    knowledge_item_id: str = "",
    proposal_id: str = "",
    importance_level: str,
    confidence: float | None = None,
    stability: str,
    review_priority: str,
    marking_reason: str = "",
) -> dict[str, Any]:
    owner, base = _require_base_with_owner(knowledge_base_id)
    suggester_id = str(suggested_by_agent_id or "").strip()
    _require_rating_suggestion_permission(owner, base, suggester_id)
    normalized_target_type = str(target_type or "").strip().lower()
    if normalized_target_type not in {"proposal", "knowledge_item"}:
        raise TeamKnowledgeError("Rating suggestion targetType must be proposal or knowledge_item.")
    normalized_item_id = str(knowledge_item_id or "").strip()
    normalized_proposal_id = str(proposal_id or "").strip()
    if normalized_target_type == "knowledge_item":
        if not normalized_item_id:
            raise TeamKnowledgeError("knowledge_item rating suggestions require knowledgeItemId.")
        _require_item(owner, base["knowledgeBaseId"], normalized_item_id)
    if normalized_target_type == "proposal":
        if not normalized_proposal_id:
            raise TeamKnowledgeError("proposal rating suggestions require proposalId.")
        _require_proposal(owner, base["knowledgeBaseId"], normalized_proposal_id)
    now = utc_now_iso()
    suggestion = {
        "suggestionId": _new_event_id("krate"),
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "knowledgeBaseId": base["knowledgeBaseId"],
        "targetType": normalized_target_type,
        "knowledgeItemId": normalized_item_id,
        "proposalId": normalized_proposal_id,
        "suggestedByAgentId": suggester_id,
        "importanceLevel": _enum_value(importance_level, IMPORTANCE_LEVELS, "importance level"),
        "confidence": max(0.0, min(1.0, float(confidence if confidence is not None else 0.7))),
        "stability": _enum_value(stability, STABILITY_VALUES, "stability"),
        "reviewPriority": _enum_value(review_priority, REVIEW_PRIORITIES, "review priority"),
        "markingReason": trim_lines(marking_reason or "", max_lines=4).strip(),
        "status": "pending",
        "createdAt": now,
        "updatedAt": now,
        "reviewedByAgentId": "",
        "reviewedAt": "",
        "resolutionNote": "",
    }
    with _LOCK:
        _append_jsonl(_rating_suggestions_path_for_owner(owner), suggestion)
        _append_audit(owner, "knowledge.rating.suggested", suggestion, actor_agent_id=suggester_id)
    _record_event(
        "knowledge.rating.suggested",
        owner,
        base["knowledgeBaseId"],
        actor_agent_id=suggester_id,
        fields={
            "suggestionId": suggestion["suggestionId"],
            "targetType": suggestion["targetType"],
            "knowledgeItemId": suggestion["knowledgeItemId"],
            "proposalId": suggestion["proposalId"],
        },
    )
    return suggestion


def list_rating_suggestions(knowledge_base_id: str, *, agent_id: str = "", status: str = "") -> dict[str, Any]:
    owner, base = _require_base_with_owner(knowledge_base_id)
    _require_permission(owner, base, agent_id, "read")
    normalized_status = str(status or "").strip().lower()
    if normalized_status and normalized_status not in SUGGESTION_STATUSES:
        raise TeamKnowledgeError(f"Unsupported rating suggestion status: {status}")
    suggestions = [
        item
        for item in _read_jsonl(_rating_suggestions_path_for_owner(owner))
        if str(item.get("knowledgeBaseId") or "") == base["knowledgeBaseId"]
        and (not normalized_status or str(item.get("status") or "") == normalized_status)
    ]
    suggestions.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "knowledgeBase": _knowledge_base_to_api(base, owner),
        "suggestions": suggestions,
        "summary": {
            "suggestionCount": len(suggestions),
            "pendingSuggestionCount": sum(1 for item in suggestions if str(item.get("status") or "") == "pending"),
        },
        "updatedAt": utc_now_iso(),
    }


def review_rating_suggestions_bulk(
    knowledge_base_id: str,
    *,
    suggestion_ids: list[str] | None,
    status: str,
    reviewed_by_agent_id: str = "",
    resolution_note: str = "",
) -> dict[str, Any]:
    owner, base = _require_base_with_owner(knowledge_base_id)
    reviewer_id = str(reviewed_by_agent_id or "").strip()
    _require_permission(owner, base, reviewer_id, "rate")
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in {"applied", "rejected"}:
        raise TeamKnowledgeError("Rating suggestion review status must be applied or rejected.")
    normalized_ids = _unique_strings(suggestion_ids or [])
    if not normalized_ids:
        raise TeamKnowledgeError("At least one rating suggestion id is required.")

    reviewed: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    applied_items: list[dict[str, Any]] = []
    now = utc_now_iso()
    with _LOCK:
        suggestions = _read_jsonl(_rating_suggestions_path_for_owner(owner))
        items: list[dict[str, Any]] | None = None
        items_changed = False
        for suggestion_id in normalized_ids:
            suggestion = _find_by_id(suggestions, "suggestionId", suggestion_id)
            if not suggestion or str(suggestion.get("knowledgeBaseId") or "") != base["knowledgeBaseId"]:
                skipped.append({"suggestionId": suggestion_id, "reason": "not_found"})
                continue
            if str(suggestion.get("status") or "") != "pending":
                skipped.append({"suggestionId": suggestion_id, "reason": "not_pending"})
                continue
            applied_item: dict[str, Any] | None = None
            if normalized_status == "applied" and str(suggestion.get("targetType") or "") == "knowledge_item":
                if items is None:
                    items = _read_jsonl(_items_path_for_owner(owner))
                item = _find_by_id(items, "knowledgeItemId", str(suggestion.get("knowledgeItemId") or ""))
                if not item or str(item.get("knowledgeBaseId") or "") != base["knowledgeBaseId"]:
                    skipped.append({"suggestionId": suggestion_id, "reason": "target_not_found"})
                    continue
                item["importanceLevel"] = suggestion["importanceLevel"]
                item["confidence"] = suggestion["confidence"]
                item["stability"] = suggestion["stability"]
                item["reviewPriority"] = suggestion["reviewPriority"]
                item["markedBy"] = reviewer_id
                item["markedAt"] = now
                item["markingReason"] = str(suggestion.get("markingReason") or "")
                item["updatedAt"] = now
                applied_item = item
                applied_items.append(item)
                items_changed = True
                _append_audit(owner, "knowledge.item.rating.updated", item, actor_agent_id=reviewer_id)
            suggestion["status"] = normalized_status
            suggestion["updatedAt"] = now
            suggestion["reviewedAt"] = now
            suggestion["reviewedByAgentId"] = reviewer_id
            suggestion["resolutionNote"] = trim_lines(resolution_note or "", max_lines=4).strip()
            reviewed.append({"suggestion": suggestion, "item": applied_item})
            _append_audit(owner, "knowledge.rating_suggestion.reviewed", suggestion, actor_agent_id=reviewer_id)
        if items is not None and items_changed:
            _write_jsonl(_items_path_for_owner(owner), items)
        _write_jsonl(_rating_suggestions_path_for_owner(owner), suggestions)
        _append_audit(
            owner,
            "knowledge.rating_suggestion.bulk_reviewed",
            {
                "ownerType": owner["ownerType"],
                "ownerId": owner["ownerId"],
                "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
                "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
                "knowledgeBaseId": base["knowledgeBaseId"],
                "status": normalized_status,
                "reviewedCount": len(reviewed),
                "skippedCount": len(skipped),
            },
            actor_agent_id=reviewer_id,
        )
    _record_event(
        "knowledge.rating_suggestion.bulk_reviewed",
        owner,
        base["knowledgeBaseId"],
        actor_agent_id=reviewer_id,
        fields={
            "status": normalized_status,
            "reviewedCount": len(reviewed),
            "skippedCount": len(skipped),
        },
    )
    for applied_item in applied_items:
        _record_event(
            "knowledge.item.rating.updated",
            owner,
            base["knowledgeBaseId"],
            actor_agent_id=reviewer_id,
            fields={"knowledgeItemId": applied_item["knowledgeItemId"], "importanceLevel": applied_item.get("importanceLevel")},
        )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "knowledgeBaseId": base["knowledgeBaseId"],
        "status": normalized_status,
        "reviewed": reviewed,
        "skipped": skipped,
        "summary": {
            "requestedCount": len(normalized_ids),
            "reviewedCount": len(reviewed),
            "skippedCount": len(skipped),
            "appliedItemCount": len(applied_items),
        },
        "updatedAt": utc_now_iso(),
    }


def review_rating_suggestion(
    knowledge_base_id: str,
    suggestion_id: str,
    *,
    status: str,
    reviewed_by_agent_id: str = "",
    resolution_note: str = "",
) -> dict[str, Any]:
    owner, base = _require_base_with_owner(knowledge_base_id)
    reviewer_id = str(reviewed_by_agent_id or "").strip()
    _require_permission(owner, base, reviewer_id, "rate")
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in {"applied", "rejected"}:
        raise TeamKnowledgeError("Rating suggestion review status must be applied or rejected.")
    with _LOCK:
        suggestions = _read_jsonl(_rating_suggestions_path_for_owner(owner))
        suggestion = _find_by_id(suggestions, "suggestionId", suggestion_id)
        if not suggestion or str(suggestion.get("knowledgeBaseId") or "") != base["knowledgeBaseId"]:
            raise TeamKnowledgeNotFoundError("Rating suggestion not found.")
        if str(suggestion.get("status") or "") != "pending":
            raise TeamKnowledgeError("Only pending rating suggestions can be reviewed.")
        now = utc_now_iso()
        suggestion["status"] = normalized_status
        suggestion["updatedAt"] = now
        suggestion["reviewedAt"] = now
        suggestion["reviewedByAgentId"] = reviewer_id
        suggestion["resolutionNote"] = trim_lines(resolution_note or "", max_lines=4).strip()
        applied_item: dict[str, Any] | None = None
        if normalized_status == "applied" and str(suggestion.get("targetType") or "") == "knowledge_item":
            items = _read_jsonl(_items_path_for_owner(owner))
            item = _find_by_id(items, "knowledgeItemId", str(suggestion.get("knowledgeItemId") or ""))
            if not item or str(item.get("knowledgeBaseId") or "") != base["knowledgeBaseId"]:
                raise TeamKnowledgeNotFoundError("Knowledge item not found.")
            item["importanceLevel"] = suggestion["importanceLevel"]
            item["confidence"] = suggestion["confidence"]
            item["stability"] = suggestion["stability"]
            item["reviewPriority"] = suggestion["reviewPriority"]
            item["markedBy"] = reviewer_id
            item["markedAt"] = now
            item["markingReason"] = str(suggestion.get("markingReason") or "")
            item["updatedAt"] = now
            applied_item = item
            _write_jsonl(_items_path_for_owner(owner), items)
            _append_audit(owner, "knowledge.item.rating.updated", item, actor_agent_id=reviewer_id)
        _write_jsonl(_rating_suggestions_path_for_owner(owner), suggestions)
        _append_audit(owner, "knowledge.rating_suggestion.reviewed", suggestion, actor_agent_id=reviewer_id)
    _record_event(
        "knowledge.rating_suggestion.reviewed",
        owner,
        base["knowledgeBaseId"],
        actor_agent_id=reviewer_id,
        fields={"suggestionId": suggestion["suggestionId"], "status": suggestion["status"]},
    )
    if applied_item:
        _record_event(
            "knowledge.item.rating.updated",
            owner,
            base["knowledgeBaseId"],
            actor_agent_id=reviewer_id,
            fields={"knowledgeItemId": applied_item["knowledgeItemId"], "importanceLevel": applied_item.get("importanceLevel")},
        )
    return {"suggestion": suggestion, "item": applied_item}


def search_knowledge_items(
    *,
    agent_id: str = "",
    query: str = "",
    team_id: str = "",
    owner_type: str = "",
    owner_id: str = "",
    knowledge_base_id: str = "",
    tags: list[str] | None = None,
    source_type: str = "",
    importance_level: str = "",
    confidence_min: float | None = None,
    stability: str = "",
    created_from: str = "",
    created_to: str = "",
    search_mode: str = "exact",
    limit: int = 25,
) -> dict[str, Any]:
    _sync_roots()
    normalized_query = trim_lines(query or "", max_lines=4).strip().lower()
    normalized_team_id = str(team_id or "").strip()
    normalized_owner_type = _normalize_owner_type(owner_type)
    normalized_owner_id = str(owner_id or "").strip()
    scoped_owner_type, scoped_owner_id, normalized_base_id = _parse_owner_scoped_knowledge_base_id(knowledge_base_id)
    normalized_owner_type = normalized_owner_type or scoped_owner_type
    normalized_owner_id = normalized_owner_id or scoped_owner_id
    normalized_tags = {item.lower() for item in _unique_strings(tags or [])}
    normalized_source_type = str(source_type or "").strip()
    if normalized_source_type and normalized_source_type not in SOURCE_TYPES:
        raise TeamKnowledgeError(f"Unsupported source type: {source_type}")
    normalized_importance = _enum_value(importance_level, IMPORTANCE_LEVELS, "importance level") if importance_level else ""
    normalized_stability = _enum_value(stability, STABILITY_VALUES, "stability") if stability else ""
    normalized_search_mode = str(search_mode or "exact").strip().lower()
    if normalized_search_mode not in {"exact", "semantic", "hybrid"}:
        raise TeamKnowledgeError(f"Unsupported knowledge search mode: {search_mode}")
    bounded_limit = max(1, min(100, int(limit or 25)))
    results: list[dict[str, Any]] = []
    scanned_bases = 0
    owner_candidates = _iter_knowledge_owners(agent_id=agent_id, include_archived=True)
    if normalized_owner_type and normalized_owner_id and not any(
        str(owner.get("ownerType") or "") == normalized_owner_type and str(owner.get("ownerId") or "") == normalized_owner_id
        for owner in owner_candidates
    ):
        owner_candidates.append(_owner_context(normalized_owner_type, normalized_owner_id))
    if normalized_base_id and not (normalized_owner_type and normalized_owner_id):
        visible_matches = [
            owner
            for owner in owner_candidates
            for base in _knowledge_bases_for_owner(owner)
            if str(base.get("knowledgeBaseId") or "") == normalized_base_id
            and _can_access(owner, base, agent_id, "read")
        ]
        unique_owner_keys = {
            (str(owner.get("ownerType") or ""), str(owner.get("ownerId") or ""))
            for owner in visible_matches
        }
        if len(unique_owner_keys) > 1:
            raise TeamKnowledgeAmbiguousKnowledgeBaseError(
                "Knowledge base id is ambiguous across owners; use scopedKnowledgeBaseId."
            )
    for owner in owner_candidates:
        current_owner_type = str(owner.get("ownerType") or "").strip()
        current_owner_id = str(owner.get("ownerId") or "").strip()
        if normalized_owner_type and current_owner_type != normalized_owner_type:
            continue
        if normalized_owner_id and current_owner_id != normalized_owner_id:
            continue
        if normalized_team_id and not (current_owner_type == "team" and current_owner_id == normalized_team_id):
            continue
        for base in _knowledge_bases_for_owner(owner):
            base_id = str(base.get("knowledgeBaseId") or "")
            if normalized_base_id and base_id != normalized_base_id:
                continue
            if not _can_access(owner, base, agent_id, "read"):
                continue
            scanned_bases += 1
            artifacts_by_id = {
                str(item.get("sourceArtifactId") or ""): item
                for item in _source_artifacts_for_base(owner, base_id)
            }
            for item in _read_jsonl(_items_path_for_owner(owner)):
                if str(item.get("knowledgeBaseId") or "") != base_id:
                    continue
                if not _item_matches_filters(
                    item,
                    query=normalized_query,
                    tags=normalized_tags,
                    source_type=normalized_source_type,
                    importance_level=normalized_importance,
                    confidence_min=confidence_min,
                    stability=normalized_stability,
                    created_from=created_from,
                    created_to=created_to,
                    artifacts_by_id=artifacts_by_id,
                    search_mode=normalized_search_mode,
                ):
                    continue
                view = _search_item_view(item, base, owner, artifacts_by_id)
                score = _semantic_match_score(view, normalized_query) if normalized_query else 1.0
                if normalized_query and normalized_search_mode == "semantic" and score <= 0:
                    continue
                if normalized_query and normalized_search_mode == "hybrid" and score <= 0:
                    haystack = " ".join(
                        [
                            str(view.get("title") or ""),
                            str(view.get("summary") or ""),
                            str(view.get("content") or ""),
                        ]
                    ).lower()
                    if normalized_query not in haystack:
                        continue
                view["semanticScore"] = score
                view["searchMode"] = normalized_search_mode
                view["matchReason"] = _search_match_reason(view, normalized_query, score)
                results.append(view)
                if len(results) >= bounded_limit:
                    break
            if len(results) >= bounded_limit:
                break
        if len(results) >= bounded_limit:
            break
    results.sort(key=lambda item: (float(item.get("semanticScore") or 0.0), str(item.get("updatedAt") or item.get("createdAt") or "")), reverse=True)
    _record_event(
        "knowledge.search.executed",
        normalized_team_id,
        normalized_base_id,
        actor_agent_id=agent_id,
        fields={"queryLength": len(normalized_query), "resultCount": len(results), "scannedKnowledgeBaseCount": scanned_bases},
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": str(agent_id or "").strip(),
        "filters": {
            "query": normalized_query,
            "teamId": normalized_team_id,
            "ownerType": normalized_owner_type,
            "ownerId": normalized_owner_id,
            "knowledgeBaseId": normalized_base_id,
            "tags": sorted(normalized_tags),
            "sourceType": normalized_source_type,
            "importanceLevel": normalized_importance,
            "confidenceMin": confidence_min,
            "stability": normalized_stability,
            "createdFrom": str(created_from or "").strip(),
            "createdTo": str(created_to or "").strip(),
            "searchMode": normalized_search_mode,
            "limit": bounded_limit,
        },
        "summary": {"resultCount": len(results), "scannedKnowledgeBaseCount": scanned_bases},
        "results": results,
        "updatedAt": utc_now_iso(),
    }


def get_knowledge_operations_health(*, agent_id: str = "", internal: bool = False) -> dict[str, Any]:
    """Return operational health for accessible team knowledge bases."""

    payload = _build_knowledge_operations_health(agent_id=agent_id, internal=internal)
    _record_event(
        "knowledge.operations.health.viewed",
        "",
        "",
        actor_agent_id=str(payload.get("agentId") or ""),
        fields={"knowledgeBaseCount": payload["summary"]["knowledgeBaseCount"], "findingCount": payload["summary"]["findingCount"]},
    )
    return payload


def _build_knowledge_operations_health(*, agent_id: str = "", internal: bool = False) -> dict[str, Any]:
    _sync_roots()
    normalized_agent_id = str(agent_id or "").strip()
    rows: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for owner in _iter_knowledge_owners(agent_id=normalized_agent_id, include_archived=True, include_all_agents=internal):
        for base in _knowledge_bases_for_owner(owner):
            if not _can_access(owner, base, normalized_agent_id, "read", internal=internal):
                continue
            base_id = str(base.get("knowledgeBaseId") or "")
            artifacts = _source_artifacts_for_base(owner, base_id)
            proposals = [
                proposal
                for proposal in _read_jsonl(_proposals_path_for_owner(owner))
                if str(proposal.get("targetKnowledgeBaseId") or "") == base_id
            ]
            items = [
                item
                for item in _read_jsonl(_items_path_for_owner(owner))
                if str(item.get("knowledgeBaseId") or "") == base_id
            ]
            suggestions = [
                suggestion
                for suggestion in _read_jsonl(_rating_suggestions_path_for_owner(owner))
                if str(suggestion.get("knowledgeBaseId") or "") == base_id
            ]
            proposal_source_ids = {
                str(source_id or "")
                for proposal in proposals
                for source_id in list(proposal.get("sourceArtifactIds") or [])
                if str(source_id or "").strip()
            }
            orphan_sources = [item for item in artifacts if str(item.get("sourceArtifactId") or "") not in proposal_source_ids]
            pending_proposals = [item for item in proposals if str(item.get("status") or "") == "pending"]
            pending_suggestions = [item for item in suggestions if str(item.get("status") or "") == "pending"]
            unrated_items = [
                item
                for item in items
                if not str(item.get("markedAt") or "").strip()
                and str(item.get("importanceLevel") or "medium") == "medium"
                and str(item.get("reviewPriority") or "normal") == "normal"
            ]
            health = "ok"
            if pending_proposals or pending_suggestions:
                health = "warning"
            if orphan_sources and not proposals:
                health = "attention"
            row = {
                "ownerType": owner["ownerType"],
                "ownerId": owner["ownerId"],
                "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
                "teamName": str((owner.get("team") or {}).get("name") or ""),
                "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
                "agentName": str((owner.get("agent") or {}).get("displayName") or ""),
                "knowledgeBaseId": base_id,
                "knowledgeBaseName": str(base.get("name") or ""),
                "health": health,
                "counts": {
                    "sourceArtifactCount": len(artifacts),
                    "orphanSourceCount": len(orphan_sources),
                    "proposalCount": len(proposals),
                    "pendingProposalCount": len(pending_proposals),
                    "formalItemCount": len(items),
                    "unratedItemCount": len(unrated_items),
                    "pendingRatingSuggestionCount": len(pending_suggestions),
                },
                "nextReviewTargetIds": [
                    *[str(item.get("proposalId") or "") for item in pending_proposals[:3]],
                    *[str(item.get("suggestionId") or "") for item in pending_suggestions[:3]],
                    *[str(item.get("sourceArtifactId") or "") for item in orphan_sources[:3]],
                ],
            }
            rows.append(row)
            if orphan_sources:
                findings.append(_knowledge_health_finding("orphan_sources", "warning", row, len(orphan_sources), "Registered sources still need refinement proposals."))
            if pending_proposals:
                findings.append(_knowledge_health_finding("pending_proposals", "warning", row, len(pending_proposals), "Pending proposals need reviewer decisions."))
            if pending_suggestions:
                findings.append(_knowledge_health_finding("pending_rating_suggestions", "info", row, len(pending_suggestions), "Rating suggestions are waiting for reviewer confirmation."))
            if unrated_items:
                findings.append(_knowledge_health_finding("unrated_items", "info", row, len(unrated_items), "Formal knowledge items still use default importance metadata."))
    summary = {
        "knowledgeBaseCount": len(rows),
        "attentionCount": sum(1 for row in rows if row["health"] == "attention"),
        "warningCount": sum(1 for row in rows if row["health"] == "warning"),
        "okCount": sum(1 for row in rows if row["health"] == "ok"),
        "findingCount": len(findings),
        "orphanSourceCount": sum(int(row["counts"]["orphanSourceCount"]) for row in rows),
        "pendingProposalCount": sum(int(row["counts"]["pendingProposalCount"]) for row in rows),
        "pendingRatingSuggestionCount": sum(int(row["counts"]["pendingRatingSuggestionCount"]) for row in rows),
        "unratedItemCount": sum(int(row["counts"]["unratedItemCount"]) for row in rows),
    }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": normalized_agent_id,
        "knowledgeBases": rows,
        "findings": findings,
        "summary": summary,
        "updatedAt": utc_now_iso(),
    }


def get_knowledge_governance_plan(*, agent_id: str = "", limit: int = 12, internal: bool = False) -> dict[str, Any]:
    """Return a read-only governance plan derived from health and steward workbench state."""

    payload = _build_knowledge_governance_plan(agent_id=agent_id, limit=limit, internal=internal)
    _record_event(
        "knowledge.governance.plan.viewed",
        "",
        "",
        actor_agent_id=str(payload.get("agentId") or ""),
        fields={"actionCount": len(payload.get("actions") or []), "healthFindingCount": payload["summary"]["healthFindingCount"]},
    )
    return payload


def _build_knowledge_governance_plan(
    *,
    agent_id: str = "",
    limit: int = 12,
    workbench: dict[str, Any] | None = None,
    health: dict[str, Any] | None = None,
    internal: bool = False,
) -> dict[str, Any]:
    """Build a read-only governance plan, optionally reusing already computed dashboard state."""

    normalized_agent_id = str(agent_id or "").strip()
    bounded_limit = max(1, min(50, int(limit or 12)))
    workbench = workbench or _build_knowledge_steward_workbench(agent_id=normalized_agent_id, limit=bounded_limit, internal=internal)
    health = health or _build_knowledge_operations_health(agent_id=normalized_agent_id, internal=internal)
    actions: list[dict[str, Any]] = []
    for item in list(workbench.get("nextActions") or []):
        actions.append(
            {
                "planActionId": f"plan:{item.get('actionId')}",
                "kind": str(item.get("recommendedAction") or ""),
                "priority": str(item.get("priority") or "normal"),
                "knowledgeBaseId": str(item.get("knowledgeBaseId") or ""),
                "knowledgeBaseName": str(item.get("knowledgeBaseName") or ""),
                "targetId": str(item.get("targetId") or ""),
                "title": str(item.get("title") or ""),
                "recommendedTool": _recommended_tool_for_action(str(item.get("recommendedAction") or "")),
                "nextStep": str(item.get("nextStep") or ""),
                "requiresReviewer": bool(item.get("requiresReviewer")),
                "mutatesFormalKnowledge": False,
            }
        )
    for finding in list(health.get("findings") or []):
        if str(finding.get("findingType") or "") == "unrated_items":
            actions.append(
                {
                    "planActionId": f"plan:{finding.get('findingId')}",
                    "kind": "suggest_rating_metadata",
                    "priority": "normal",
                    "knowledgeBaseId": str(finding.get("knowledgeBaseId") or ""),
                    "knowledgeBaseName": str(finding.get("knowledgeBaseName") or ""),
                    "targetId": "",
                    "title": "Suggest rating metadata for default-marked formal knowledge.",
                    "recommendedTool": "knowledge_rating_suggestion_tool",
                    "nextStep": "Inspect formal items and submit pending rating suggestions for reviewer confirmation.",
                    "requiresReviewer": True,
                    "mutatesFormalKnowledge": False,
                }
            )
    actions = actions[:bounded_limit]
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": normalized_agent_id,
        "mode": "recommendations_only",
        "actions": actions,
        "summary": {
            "actionCount": len(actions),
            "healthFindingCount": int((health.get("summary") or {}).get("findingCount") or 0),
            "workbenchRecommendationCount": int((workbench.get("summary") or {}).get("recommendationCount") or 0),
        },
        "operatingBoundary": {
            "canDirectlyApplyKnowledge": False,
            "canDeleteKnowledge": False,
            "canChangeAcl": False,
            "canBypassReviewer": False,
            "formalKnowledgeRequiresReviewer": True,
            "planOnly": True,
        },
        "updatedAt": utc_now_iso(),
    }
    return payload


def get_knowledge_dashboard_snapshot(
    *,
    agent_id: str = "",
    recommendation_limit: int = 6,
    workbench_limit: int = 8,
    plan_limit: int = 8,
    internal: bool = False,
) -> dict[str, Any]:
    """Return the Memory route's knowledge dashboard state with shared intermediate scans."""

    _sync_roots()
    normalized_agent_id = str(agent_id or "").strip()
    bounded_recommendation_limit = max(1, min(50, int(recommendation_limit or 6)))
    bounded_workbench_limit = max(1, min(50, int(workbench_limit or 8)))
    bounded_plan_limit = max(1, min(50, int(plan_limit or 8)))
    internal_access = bool(internal)
    overview = list_knowledge_overview(agent_id=normalized_agent_id, internal=internal_access)
    governance_tasks_all = list_knowledge_governance_tasks(agent_id=normalized_agent_id, status="all", internal=internal_access)
    governance_tasks_open = list_knowledge_governance_tasks(agent_id=normalized_agent_id, status="open", internal=internal_access)
    steward = _build_knowledge_steward_overview(
        agent_id=normalized_agent_id,
        governance_tasks=governance_tasks_all,
        internal=internal_access,
    )
    recommendations = _build_knowledge_steward_recommendations(
        agent_id=normalized_agent_id,
        limit=bounded_recommendation_limit,
        tasks_payload=governance_tasks_open,
        internal=internal_access,
    )
    workbench_recommendations = (
        recommendations
        if bounded_workbench_limit == bounded_recommendation_limit
        else _build_knowledge_steward_recommendations(
            agent_id=normalized_agent_id,
            limit=bounded_workbench_limit,
            tasks_payload=governance_tasks_open,
            internal=internal_access,
        )
    )
    workbench = _build_knowledge_steward_workbench(
        agent_id=normalized_agent_id,
        limit=bounded_workbench_limit,
        overview=steward,
        tasks_payload=governance_tasks_open,
        recommendations_payload=workbench_recommendations,
        internal=internal_access,
    )
    health = _build_knowledge_operations_health(agent_id=normalized_agent_id, internal=internal_access)
    governance_plan = _build_knowledge_governance_plan(
        agent_id=normalized_agent_id,
        limit=bounded_plan_limit,
        workbench=workbench,
        health=health,
        internal=internal_access,
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": normalized_agent_id,
        "overview": overview,
        "steward": steward,
        "recommendations": recommendations,
        "workbench": workbench,
        "operationsHealth": health,
        "governancePlan": governance_plan,
        "updatedAt": utc_now_iso(),
    }


def knowledge_permission_audit(*, agent_id: str = "") -> dict[str, Any]:
    _sync_roots()
    normalized_agent_id = str(agent_id or "").strip()
    try:
        from core.web.services import agent_directory_service

        memory_policy = agent_directory_service.resolve_memory_policy_for_agent(normalized_agent_id) if normalized_agent_id else {}
    except Exception:
        memory_policy = {}
    read_policy = set(_unique_strings(memory_policy.get("readKnowledgeBaseIds") or []))
    propose_policy = set(_unique_strings(memory_policy.get("proposeKnowledgeBaseIds") or []))
    review_policy = set(_unique_strings(memory_policy.get("reviewKnowledgeBaseIds") or []))
    rate_policy = set(_unique_strings(memory_policy.get("rateKnowledgeBaseIds") or []))
    rows: list[dict[str, Any]] = []
    for owner in _iter_knowledge_owners(agent_id=normalized_agent_id, include_archived=True):
        team = owner.get("team") if isinstance(owner.get("team"), dict) else {}
        agent = owner.get("agent") if isinstance(owner.get("agent"), dict) else {}
        role = _member_role(team, normalized_agent_id) if normalized_agent_id and owner["ownerType"] == "team" else ""
        for base in _knowledge_bases_for_owner(owner):
            base_id = str(base.get("knowledgeBaseId") or "")
            rows.append(
                {
                    "ownerType": owner["ownerType"],
                    "ownerId": owner["ownerId"],
                    "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
                    "teamName": str(team.get("name") or ""),
                    "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
                    "agentName": str(agent.get("displayName") or agent.get("agentCode") or ""),
                    "knowledgeBaseId": base_id,
                    "knowledgeBaseName": str(base.get("name") or ""),
                    "teamRole": role,
                    "permissions": {
                        "read": _permission_explain(owner, base, normalized_agent_id, "read", read_policy),
                        "propose": _permission_explain(owner, base, normalized_agent_id, "propose", propose_policy),
                        "review": _permission_explain(owner, base, normalized_agent_id, "review", review_policy),
                        "rate": _permission_explain(owner, base, normalized_agent_id, "rate", rate_policy),
                    },
                }
            )
    tools = {
        name: {
            "toolName": name,
            "visible": True,
            "allowedByToolPolicy": True,
            "blockedByToolPolicy": False,
            "reason": "available",
        }
        for name in ("unified_memory_search_tool", "knowledge_proposal_tool", "knowledge_rating_suggestion_tool")
    }
    _record_event(
        "knowledge.permission.audit.viewed",
        "",
        "",
        actor_agent_id=normalized_agent_id,
        fields={"knowledgeBaseCount": len(rows), "visibleToolCount": sum(1 for item in tools.values() if item["visible"])},
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": normalized_agent_id,
        "tools": tools,
        "knowledgeBases": rows,
        "summary": {
            "knowledgeBaseCount": len(rows),
            "readableCount": sum(1 for row in rows if row["permissions"]["read"]["allowed"]),
            "proposableCount": sum(1 for row in rows if row["permissions"]["propose"]["allowed"]),
            "reviewableCount": sum(1 for row in rows if row["permissions"]["review"]["allowed"]),
            "rateableCount": sum(1 for row in rows if row["permissions"]["rate"]["allowed"]),
        },
        "updatedAt": utc_now_iso(),
    }


def team_knowledge_memory_section_summary() -> dict[str, Any]:
    """Return a lightweight summary for /api/memory/overview."""

    overview = _lightweight_knowledge_memory_summary()
    return {
        "knowledgeBaseCount": int((overview.get("summary") or {}).get("knowledgeBaseCount") or 0),
        "pendingProposalCount": int((overview.get("summary") or {}).get("pendingProposalCount") or 0),
        "itemCount": int((overview.get("summary") or {}).get("itemCount") or 0),
        "sourceArtifactCount": int((overview.get("summary") or {}).get("sourceArtifactCount") or 0),
        "updatedAt": str(overview.get("updatedAt") or ""),
    }


def _lightweight_knowledge_memory_summary() -> dict[str, Any]:
    """Count knowledge artifacts without expanding owners, permissions, or proposal payloads."""

    knowledge_base_count = 0
    pending_proposal_count = 0
    item_count = 0
    source_artifact_count = 0
    updated_at = ""
    for root in _iter_existing_knowledge_roots():
        bases_state = _load_knowledge_bases_state_from_path(root / "knowledge_bases.json")
        base_ids = {
            str(item.get("knowledgeBaseId") or "").strip()
            for item in list(bases_state.get("knowledgeBases") or [])
            if isinstance(item, dict) and str(item.get("knowledgeBaseId") or "").strip()
        }
        knowledge_base_count += len(base_ids)
        updated_at = max(updated_at, str(bases_state.get("updatedAt") or ""))
        if not base_ids:
            continue
        for item in _read_jsonl(root / "items.jsonl"):
            if str(item.get("knowledgeBaseId") or "") in base_ids:
                item_count += 1
                updated_at = max(updated_at, str(item.get("updatedAt") or item.get("createdAt") or ""))
        for item in _read_jsonl(root / "source_artifacts.jsonl"):
            if str(item.get("knowledgeBaseId") or "") in base_ids:
                source_artifact_count += 1
                updated_at = max(updated_at, str(item.get("updatedAt") or item.get("createdAt") or ""))
        for item in _read_jsonl(root / "refinement_proposals.jsonl"):
            if str(item.get("targetKnowledgeBaseId") or "") not in base_ids:
                continue
            updated_at = max(updated_at, str(item.get("updatedAt") or item.get("createdAt") or ""))
            if str(item.get("status") or "") == "pending":
                pending_proposal_count += 1

    return {
        "schemaVersion": SCHEMA_VERSION,
        "summary": {
            "knowledgeBaseCount": knowledge_base_count,
            "pendingProposalCount": pending_proposal_count,
            "itemCount": item_count,
            "sourceArtifactCount": source_artifact_count,
        },
        "updatedAt": updated_at or utc_now_iso(),
    }


def _iter_existing_knowledge_roots() -> list[Path]:
    workspace_root = _route_team_knowledge_workspace_path(seed=True)
    roots: list[Path] = []
    for parent in (workspace_root / "teams", workspace_root / "agents"):
        if not parent.exists():
            continue
        for path in sorted(parent.glob("*/knowledge/knowledge_bases.json")):
            roots.append(path.parent)
    return roots


def _load_knowledge_bases_state_from_path(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schemaVersion": SCHEMA_VERSION, "updatedAt": "", "knowledgeBases": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schemaVersion": SCHEMA_VERSION, "updatedAt": "", "knowledgeBases": []}
    if not isinstance(payload, dict):
        return {"schemaVersion": SCHEMA_VERSION, "updatedAt": "", "knowledgeBases": []}
    knowledge_bases = [item for item in list(payload.get("knowledgeBases") or []) if isinstance(item, dict)]
    return {
        "schemaVersion": int(payload.get("schemaVersion") or SCHEMA_VERSION),
        "updatedAt": str(payload.get("updatedAt") or ""),
        "knowledgeBases": knowledge_bases,
    }


def _require_base_with_owner(knowledge_base_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    owner_type, owner_id, normalized_id = _parse_owner_scoped_knowledge_base_id(knowledge_base_id)
    if not normalized_id:
        raise TeamKnowledgeError("Knowledge base id is required.")
    _sync_roots()
    if owner_type and owner_id:
        owner = _owner_context(owner_type, owner_id)
        base = _find_knowledge_base_for_owner(owner, normalized_id)
        if base:
            return owner, base
        raise TeamKnowledgeNotFoundError("Knowledge base not found.")
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for owner in _iter_knowledge_owners(agent_id="", include_archived=True, include_all_agents=True):
        base = _find_knowledge_base_for_owner(owner, normalized_id)
        if base:
            matches.append((owner, base))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise TeamKnowledgeAmbiguousKnowledgeBaseError(
            "Knowledge base id is ambiguous across owners; use scopedKnowledgeBaseId."
        )
    raise TeamKnowledgeNotFoundError("Knowledge base not found.")


def _require_base_with_team(knowledge_base_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    owner, base = _require_base_with_owner(knowledge_base_id)
    if str(owner.get("ownerType") or "") != "team":
        raise TeamKnowledgeNotFoundError("Team knowledge base not found.")
    return dict(owner.get("team") or {}), base


def _require_team(team_id: str) -> dict[str, Any]:
    _sync_roots()
    try:
        return team_service.get_team(team_id)
    except team_service.TeamNotFoundError as exc:
        raise TeamKnowledgeNotFoundError("Team not found.") from exc
    except team_service.TeamServiceError as exc:
        raise TeamKnowledgeError(str(exc)) from exc


def _require_team_identity(team_id: str) -> dict[str, Any]:
    _sync_roots()
    try:
        normalized_team_id = team_service.assert_team_exists(team_id)
    except team_service.TeamNotFoundError as exc:
        raise TeamKnowledgeNotFoundError("Team not found.") from exc
    except team_service.TeamServiceError as exc:
        raise TeamKnowledgeError(str(exc)) from exc
    return {"teamId": normalized_team_id, "name": ""}


def _require_agent(agent_id: str) -> dict[str, Any]:
    _sync_roots()
    normalized_id = str(agent_id or "").strip()
    if not normalized_id:
        raise TeamKnowledgeError("Agent id is required.")
    agent = agent_directory_service.get_agent(normalized_id)
    if not agent:
        raise TeamKnowledgeNotFoundError("Agent not found.")
    return agent


def _require_owner_context(owner_type: str, owner_id: str) -> dict[str, Any]:
    normalized_type = _normalize_owner_type(owner_type)
    normalized_id = str(owner_id or "").strip()
    if not normalized_id:
        raise TeamKnowledgeError("Owner id is required.")
    if normalized_type == "team":
        return _owner_context("team", normalized_id, team=_require_team(normalized_id))
    if normalized_type == "agent":
        return _owner_context("agent", normalized_id, agent=_require_agent(normalized_id))
    raise TeamKnowledgeError("Owner type is required.")


def _knowledge_base_to_api(base: dict[str, Any], owner_value: dict[str, Any]) -> dict[str, Any]:
    owner = _coerce_owner_context(owner_value)
    owner_type = str(base.get("ownerType") or owner.get("ownerType") or "team").strip() or "team"
    owner_id = str(base.get("ownerId") or owner.get("ownerId") or base.get("teamId") or "").strip()
    team = owner.get("team") if isinstance(owner.get("team"), dict) else {}
    agent = owner.get("agent") if isinstance(owner.get("agent"), dict) else {}
    scoped_id = _owner_scoped_knowledge_base_id(owner, str(base.get("knowledgeBaseId") or ""))
    return {
        "knowledgeBaseId": str(base.get("knowledgeBaseId") or "").strip(),
        "scopedKnowledgeBaseId": scoped_id,
        "ownerType": owner_type,
        "ownerId": owner_id,
        "teamId": str(base.get("teamId") or (owner_id if owner_type == "team" else "")).strip(),
        "teamName": str(team.get("name") or "").strip(),
        "agentId": str(base.get("agentId") or (owner_id if owner_type == "agent" else "")).strip(),
        "agentName": str(agent.get("displayName") or agent.get("agentCode") or "").strip(),
        "name": str(base.get("name") or "").strip(),
        "description": str(base.get("description") or "").strip(),
        "status": str(base.get("status") or "active").strip(),
        "acl": _normalize_acl(base.get("acl") if isinstance(base.get("acl"), dict) else {}),
        "createdAt": str(base.get("createdAt") or "").strip(),
        "updatedAt": str(base.get("updatedAt") or "").strip(),
    }


def _knowledge_base_stats_for_owner(owner_value: Any, knowledge_base_id: str) -> dict[str, int]:
    owner = _coerce_owner_context(owner_value)
    proposals = [
        item
        for item in _read_jsonl(_proposals_path_for_owner(owner))
        if str(item.get("targetKnowledgeBaseId") or "") == knowledge_base_id
    ]
    return {
        "sourceArtifactCount": len(_source_artifacts_for_base(owner, knowledge_base_id)),
        "pendingProposalCount": sum(1 for item in proposals if str(item.get("status") or "") == "pending"),
        "proposalCount": len(proposals),
        "itemCount": sum(
            1
            for item in _read_jsonl(_items_path_for_owner(owner))
            if str(item.get("knowledgeBaseId") or "") == knowledge_base_id
        ),
        "batchCount": sum(
            1
            for item in _read_jsonl(_batches_path_for_owner(owner))
            if str(item.get("knowledgeBaseId") or "") == knowledge_base_id
        ),
    }


def _knowledge_base_stats(team_id: str, knowledge_base_id: str) -> dict[str, int]:
    return _knowledge_base_stats_for_owner(_owner_context("team", team_id), knowledge_base_id)


def _pending_proposals_for_base(owner_value: Any, knowledge_base_id: str) -> list[dict[str, Any]]:
    owner = _coerce_owner_context(owner_value)
    proposals = [
        item
        for item in _read_jsonl(_proposals_path_for_owner(owner))
        if str(item.get("targetKnowledgeBaseId") or "") == knowledge_base_id and str(item.get("status") or "") == "pending"
    ]
    proposals.sort(key=lambda item: str(item.get("createdAt") or ""), reverse=True)
    return proposals[:12]


def _permissions_for_actor(owner_value: Any, base: dict[str, Any], agent_id: str, *, internal: bool = False) -> dict[str, bool]:
    return {
        "canRead": _can_access(owner_value, base, agent_id, "read", internal=internal),
        "canPropose": _can_access(owner_value, base, agent_id, "propose", internal=internal),
        "canReview": _can_access(owner_value, base, agent_id, "review", internal=internal),
        "canRate": _can_access(owner_value, base, agent_id, "rate", internal=internal),
    }


def _require_permission(owner_value: Any, base: dict[str, Any], agent_id: str, action: str) -> None:
    if not _can_access(owner_value, base, agent_id, action):
        raise TeamKnowledgePermissionError(f"Agent is not allowed to {action} this knowledge base.")


def _require_rating_suggestion_permission(owner_value: Any, base: dict[str, Any], agent_id: str) -> None:
    if _can_access(owner_value, base, agent_id, "rate") or _is_global_knowledge_steward(agent_id):
        return
    raise TeamKnowledgePermissionError("Agent is not allowed to suggest ratings for this knowledge base.")


def _can_access(owner_value: Any, base: dict[str, Any], agent_id: str, action: str, *, internal: bool = False) -> bool:
    owner = _coerce_owner_context(owner_value)
    normalized_agent_id = str(agent_id or "").strip()
    if internal:
        return True
    if not normalized_agent_id:
        return False
    if _is_global_knowledge_steward(normalized_agent_id) and action in {"read", "propose"}:
        return True
    acl = _normalize_acl(base.get("acl") if isinstance(base.get("acl"), dict) else {})
    grants = acl.get("grants") if isinstance(acl.get("grants"), dict) else {}
    agent_grants = _unique_strings((grants.get(action) or []) + (grants.get("*") or [])) if isinstance(grants, dict) else []
    if normalized_agent_id in agent_grants:
        return True
    owner_type = str(owner.get("ownerType") or "team").strip()
    owner_id = str(owner.get("ownerId") or "").strip()
    if owner_type == "agent":
        return normalized_agent_id == owner_id
    team = owner.get("team") if isinstance(owner.get("team"), dict) else owner
    role = _member_role(team, normalized_agent_id)
    if action == "read":
        return bool(role)
    if action == "propose":
        return bool(role)
    if action == "review":
        return role in REVIEW_ROLES
    if action == "rate":
        return role in REVIEW_ROLES
    return False


def _can_collect_owner_source(owner_value: Any, agent_id: str) -> bool:
    owner = _coerce_owner_context(owner_value)
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        return False
    if _is_global_knowledge_steward(normalized_agent_id):
        return True
    if str(owner.get("ownerType") or "") == "agent":
        return str(owner.get("ownerId") or "") == normalized_agent_id
    return bool(_member_role(owner.get("team") if isinstance(owner.get("team"), dict) else {}, normalized_agent_id))


def _can_read_owner_source_inbox(owner_value: Any, agent_id: str) -> bool:
    return _can_collect_owner_source(owner_value, agent_id) or _can_review_owner_source(owner_value, agent_id)


def _can_review_owner_source(owner_value: Any, agent_id: str) -> bool:
    owner = _coerce_owner_context(owner_value)
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        return False
    if _is_global_knowledge_steward(normalized_agent_id):
        return True
    if normalized_agent_id in _source_governance_for_owner(owner).get("localStewardAgentIds", []):
        return True
    if str(owner.get("ownerType") or "") == "agent":
        return str(owner.get("ownerId") or "") == normalized_agent_id
    role = _member_role(owner.get("team") if isinstance(owner.get("team"), dict) else {}, normalized_agent_id)
    return role in REVIEW_ROLES


def _can_configure_owner_source_governance(owner_value: Any, agent_id: str) -> bool:
    owner = _coerce_owner_context(owner_value)
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        return False
    if _is_global_knowledge_steward(normalized_agent_id):
        return True
    if str(owner.get("ownerType") or "") == "agent":
        return str(owner.get("ownerId") or "") == normalized_agent_id
    role = _member_role(owner.get("team") if isinstance(owner.get("team"), dict) else {}, normalized_agent_id)
    return role in REVIEW_ROLES


def _is_global_knowledge_steward(agent_id: str) -> bool:
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        return False
    if normalized_agent_id == getattr(agent_directory_service, "KNOWLEDGE_STEWARD_AGENT_ID", ""):
        return True
    try:
        agent = agent_directory_service.get_agent(normalized_agent_id, include_archived=True)
    except Exception:
        agent = {}
    metadata = agent.get("metadata") if isinstance(agent, dict) and isinstance(agent.get("metadata"), dict) else {}
    return str(metadata.get("governanceRole") or metadata.get("systemRole") or "").strip() == "knowledge_steward"


def _permission_explain(
    team: dict[str, Any],
    base: dict[str, Any],
    agent_id: str,
    action: str,
    policy_ids: set[str],
    internal: bool = False,
) -> dict[str, Any]:
    owner = _coerce_owner_context(team)
    base_id = str(base.get("knowledgeBaseId") or "")
    team_allowed = _can_access(owner, base, agent_id, action, internal=internal)
    policy_allowed = knowledge_base_policy_allows(_owner_scoped_knowledge_base_id(owner, base_id), policy_ids)
    allowed = team_allowed and policy_allowed
    reason = "allowed"
    if not team_allowed:
        reason = "agent_owner_blocked" if str(owner.get("ownerType") or "") == "agent" else "team_acl_blocked"
    elif not policy_allowed:
        reason = "memory_policy_blocked"
    return {
        "allowed": allowed,
        "reason": reason,
        "teamAclAllowed": team_allowed if str(owner.get("ownerType") or "") == "team" else False,
        "agentOwnerAllowed": team_allowed if str(owner.get("ownerType") or "") == "agent" else False,
        "memoryPolicyAllowed": policy_allowed,
        "memoryPolicyExplicit": bool(policy_ids),
    }


def _member_role(team: dict[str, Any], agent_id: str) -> str:
    normalized_agent_id = str(agent_id or "").strip()
    for member in list(team.get("members") or []):
        if isinstance(member, dict) and str(member.get("agentId") or "").strip() == normalized_agent_id:
            return str(member.get("role") or "member").strip().lower() or "member"
    return ""


def _validate_team_chat_source(team: dict[str, Any], source_ref: dict[str, Any]) -> None:
    room_id = str(source_ref.get("roomId") or "").strip()
    if not room_id:
        raise TeamKnowledgeError("team_chat_refinement requires sourceRef.roomId.")
    if not (source_ref.get("messageRange") or source_ref.get("roundId")):
        raise TeamKnowledgeError("team_chat_refinement requires sourceRef.messageRange or sourceRef.roundId.")
    linked_room_id = str(team.get("linkedChatRoomId") or "").strip()
    if room_id == linked_room_id:
        return
    room = chat_room_service.get_chat_room_detail(room_id)
    config = room.get("config") if isinstance(room, dict) and isinstance(room.get("config"), dict) else {}
    if str(config.get("source") or "").strip() == "team" and str(config.get("teamId") or "").strip() == team["teamId"]:
        return
    raise TeamKnowledgeError("team_chat_refinement roomId must belong to the Team linked chat room.")


def _knowledge_bases_for_owner(owner_value: Any) -> list[dict[str, Any]]:
    owner = _coerce_owner_context(owner_value)
    state = _load_bases_state_for_owner(owner)
    bases = [item for item in state.get("knowledgeBases") or [] if isinstance(item, dict)]
    return [_repair_base_for_owner(owner, item) for item in bases]


def _knowledge_bases_for_team(team_id: str) -> list[dict[str, Any]]:
    return _knowledge_bases_for_owner(_owner_context("team", team_id))


def _find_knowledge_base_for_owner(owner_value: Any, knowledge_base_id: str) -> dict[str, Any] | None:
    _, _, normalized_id = _parse_owner_scoped_knowledge_base_id(knowledge_base_id)
    for base in _knowledge_bases_for_owner(owner_value):
        if str(base.get("knowledgeBaseId") or "").strip() == normalized_id:
            return base
    return None


def _find_knowledge_base(team_id: str, knowledge_base_id: str) -> dict[str, Any] | None:
    return _find_knowledge_base_for_owner(_owner_context("team", team_id), knowledge_base_id)


def _source_artifacts_for_base(owner_value: Any, knowledge_base_id: str) -> list[dict[str, Any]]:
    owner = _coerce_owner_context(owner_value)
    return [
        item
        for item in _read_jsonl(_source_artifacts_path_for_owner(owner))
        if str(item.get("knowledgeBaseId") or "") == knowledge_base_id
    ]


def _require_item(owner_value: Any, knowledge_base_id: str, knowledge_item_id: str) -> dict[str, Any]:
    owner = _coerce_owner_context(owner_value)
    item = _find_by_id(_read_jsonl(_items_path_for_owner(owner)), "knowledgeItemId", knowledge_item_id)
    if not item or str(item.get("knowledgeBaseId") or "") != knowledge_base_id:
        raise TeamKnowledgeNotFoundError("Knowledge item not found.")
    return item


def _require_proposal(owner_value: Any, knowledge_base_id: str, proposal_id: str) -> dict[str, Any]:
    owner = _coerce_owner_context(owner_value)
    proposal = _find_by_id(_read_jsonl(_proposals_path_for_owner(owner)), "proposalId", proposal_id)
    if not proposal or str(proposal.get("targetKnowledgeBaseId") or "") != knowledge_base_id:
        raise TeamKnowledgeNotFoundError("Knowledge proposal not found.")
    return proposal


def _search_text_for_payload(payload: Any) -> str:
    values: list[str] = []

    def collect(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str):
            text = value.strip()
            if text:
                values.append(text)
            return
        if isinstance(value, (int, float)):
            values.append(str(value))
            return
        if isinstance(value, dict):
            for nested in value.values():
                collect(nested)
            return
        if isinstance(value, (list, tuple, set)):
            for nested in value:
                collect(nested)

    collect(payload)
    return " ".join(values).lower()


def _tokenize_search_text(text: str) -> set[str]:
    return {
        match.group(0).lower()
        for match in _SEARCH_TOKEN_PATTERN.finditer(str(text or "").lower())
        if match.group(0).strip()
    }


def _semantic_match_score(payload: Any, query: str) -> float:
    normalized_query = str(query or "").strip().lower()
    if not normalized_query:
        return 1.0
    haystack = payload if isinstance(payload, str) else _search_text_for_payload(payload)
    if normalized_query in haystack:
        return 1.0
    query_tokens = _tokenize_search_text(normalized_query)
    if not query_tokens:
        return 0.0
    haystack_tokens = _tokenize_search_text(haystack)
    if not haystack_tokens:
        return 0.0
    return round(len(query_tokens.intersection(haystack_tokens)) / len(query_tokens), 4)


def _search_match_reason(view: dict[str, Any], query: str, score: float) -> str:
    if not str(query or "").strip():
        return "no_query"
    if str(query or "").strip().lower() in _search_text_for_payload(view):
        return "exact_phrase"
    if score > 0:
        return "token_overlap"
    return "metadata_filter"


def _item_matches_filters(
    item: dict[str, Any],
    *,
    query: str,
    tags: set[str],
    source_type: str,
    importance_level: str,
    confidence_min: float | None,
    stability: str,
    created_from: str,
    created_to: str,
    artifacts_by_id: dict[str, dict[str, Any]],
    search_mode: str = "exact",
) -> bool:
    if query:
        normalized_search_mode = str(search_mode or "exact").strip().lower()
        haystack = _search_text_for_payload([item, list(artifacts_by_id.values())])
        exact_match = query in haystack
        semantic_score = _semantic_match_score(haystack, query)
        if normalized_search_mode == "exact" and not exact_match:
            return False
        if normalized_search_mode == "semantic" and semantic_score <= 0:
            return False
        if normalized_search_mode == "hybrid" and not exact_match and semantic_score <= 0:
            return False
    if tags and not tags.issubset({str(tag or "").strip().lower() for tag in list(item.get("tags") or [])}):
        return False
    if source_type:
        source_ids = [str(value or "") for value in list(item.get("sourceArtifactIds") or [])]
        if not any(str((artifacts_by_id.get(source_id) or {}).get("sourceType") or "") == source_type for source_id in source_ids):
            return False
    if importance_level and str(item.get("importanceLevel") or "") != importance_level:
        return False
    if confidence_min is not None:
        try:
            if float(item.get("confidence") or 0.0) < float(confidence_min):
                return False
        except (TypeError, ValueError):
            return False
    if stability and str(item.get("stability") or "") != stability:
        return False
    created_at = str(item.get("createdAt") or item.get("appliedAt") or "")
    if created_from and created_at < str(created_from):
        return False
    if created_to and created_at > str(created_to):
        return False
    return True


def _search_item_view(
    item: dict[str, Any],
    base: dict[str, Any],
    owner_value: dict[str, Any],
    artifacts_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    owner = _coerce_owner_context(owner_value)
    team = owner.get("team") if isinstance(owner.get("team"), dict) else {}
    agent = owner.get("agent") if isinstance(owner.get("agent"), dict) else {}
    source_artifacts = [
        artifacts_by_id[source_id]
        for source_id in [str(value or "") for value in list(item.get("sourceArtifactIds") or [])]
        if source_id in artifacts_by_id
    ]
    return {
        "knowledgeItemId": str(item.get("knowledgeItemId") or ""),
        "knowledgeBaseId": str(base.get("knowledgeBaseId") or ""),
        "knowledgeBaseName": str(base.get("name") or ""),
        "ownerType": str(item.get("ownerType") or base.get("ownerType") or owner.get("ownerType") or "team"),
        "ownerId": str(item.get("ownerId") or base.get("ownerId") or owner.get("ownerId") or ""),
        "teamId": str(item.get("teamId") or (owner.get("ownerId") if owner.get("ownerType") == "team" else "")),
        "teamName": str(team.get("name") or ""),
        "agentId": str(item.get("agentId") or (owner.get("ownerId") if owner.get("ownerType") == "agent" else "")),
        "agentName": str(agent.get("displayName") or agent.get("agentCode") or ""),
        "batchId": str(item.get("batchId") or ""),
        "sourceArtifactIds": [str(value) for value in list(item.get("sourceArtifactIds") or [])[:12] if str(value or "").strip()],
        "centralSourceIds": [str(value) for value in list(item.get("centralSourceIds") or [])[:12] if str(value or "").strip()],
        "sourceTypes": sorted({str(source.get("sourceType") or "") for source in source_artifacts if str(source.get("sourceType") or "")}),
        "sourceSummaries": [
            {
                "sourceArtifactId": str(source.get("sourceArtifactId") or ""),
                "centralSourceId": str(source.get("centralSourceId") or ""),
                "sourceType": str(source.get("sourceType") or ""),
                "capturedAt": str(source.get("capturedAt") or ""),
                "title": trim_lines(str(source.get("title") or ""), max_lines=1),
                "summary": trim_lines(str(source.get("summary") or ""), max_lines=2),
            }
            for source in source_artifacts[:6]
        ],
        "title": trim_lines(str(item.get("title") or ""), max_lines=2),
        "summary": trim_lines(str(item.get("summary") or ""), max_lines=4),
        "content": trim_lines(str(item.get("content") or ""), max_lines=12),
        "tags": [str(value) for value in list(item.get("tags") or [])[:12] if str(value or "").strip()],
        "importanceLevel": str(item.get("importanceLevel") or ""),
        "confidence": item.get("confidence"),
        "stability": str(item.get("stability") or ""),
        "scope": str(item.get("scope") or ""),
        "reviewPriority": str(item.get("reviewPriority") or ""),
        "createdAt": str(item.get("createdAt") or ""),
        "appliedAt": str(item.get("appliedAt") or ""),
        "updatedAt": str(item.get("updatedAt") or ""),
    }


def _task_status_matches(closed: bool, normalized_status: str) -> bool:
    if normalized_status == "all":
        return True
    if normalized_status == "closed":
        return closed
    return not closed


def _governance_task(
    owner_value: dict[str, Any],
    base: dict[str, Any],
    *,
    task_type: str,
    status: str,
    priority: str,
    title: str,
    summary: str,
    target_id: str,
    target_status: str,
    created_at: str,
    updated_at: str,
    permissions: dict[str, bool],
    source_artifact_ids: list[str],
) -> dict[str, Any]:
    owner = _coerce_owner_context(owner_value)
    team = owner.get("team") if isinstance(owner.get("team"), dict) else {}
    agent = owner.get("agent") if isinstance(owner.get("agent"), dict) else {}
    return {
        "taskId": f"ktask:{base.get('knowledgeBaseId')}:{task_type}:{target_id}",
        "taskType": task_type,
        "status": status,
        "priority": priority if priority in REVIEW_PRIORITIES else "normal",
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": str(team.get("teamId") or ""),
        "teamName": str(team.get("name") or ""),
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "agentName": str(agent.get("displayName") or agent.get("agentCode") or ""),
        "knowledgeBaseId": str(base.get("knowledgeBaseId") or ""),
        "knowledgeBaseName": str(base.get("name") or ""),
        "targetId": target_id,
        "targetStatus": target_status,
        "title": trim_lines(title or task_type, max_lines=1),
        "summary": trim_lines(summary or "", max_lines=3),
        "sourceArtifactIds": source_artifact_ids[:12],
        "createdAt": created_at,
        "updatedAt": updated_at or created_at,
        "permissions": {
            "canReview": bool(permissions.get("canReview")),
            "canRate": bool(permissions.get("canRate")),
            "canPropose": bool(permissions.get("canPropose")),
        },
    }


def _steward_recommendation_from_task(task: dict[str, Any]) -> dict[str, Any]:
    task_type = str(task.get("taskType") or "").strip()
    priority = str(task.get("priority") or "normal").strip()
    permissions = task.get("permissions") if isinstance(task.get("permissions"), dict) else {}
    if task_type == "proposal_review":
        recommended_action = "review_proposal"
        reason = "Pending refinement proposal needs a reviewer before it can become formal knowledge."
        next_step = "Open the trace, inspect source evidence, then approve or reject as a review-capable Agent."
        requires_reviewer = True
        can_execute = bool(permissions.get("canReview"))
    elif task_type == "rating_review":
        recommended_action = "review_rating_suggestion"
        reason = "Pending importance or stability suggestion needs reviewer confirmation before item metadata changes."
        next_step = "Compare the suggestion with the target evidence, then apply or reject the rating suggestion."
        requires_reviewer = True
        can_execute = bool(permissions.get("canRate"))
    elif task_type == "source_needs_proposal":
        recommended_action = "draft_refinement_proposal"
        reason = "Registered source evidence has not yet been refined into a proposal."
        next_step = "Draft a refinement proposal that summarizes the source without creating formal knowledge directly."
        requires_reviewer = False
        can_execute = bool(permissions.get("canPropose"))
    else:
        recommended_action = "inspect_task"
        reason = "Governance task needs manual inspection."
        next_step = "Inspect the task and choose the smallest review-safe action."
        requires_reviewer = True
        can_execute = False
    return {
        "recommendationId": f"krec:{task.get('taskId')}",
        "taskId": str(task.get("taskId") or ""),
        "taskType": task_type,
        "recommendedAction": recommended_action,
        "priority": priority if priority in REVIEW_PRIORITIES else "normal",
        "teamId": str(task.get("teamId") or ""),
        "teamName": str(task.get("teamName") or ""),
        "knowledgeBaseId": str(task.get("knowledgeBaseId") or ""),
        "knowledgeBaseName": str(task.get("knowledgeBaseName") or ""),
        "targetId": str(task.get("targetId") or ""),
        "targetStatus": str(task.get("targetStatus") or ""),
        "title": trim_lines(str(task.get("title") or recommended_action), max_lines=1),
        "summary": trim_lines(str(task.get("summary") or ""), max_lines=3),
        "reason": reason,
        "nextStep": next_step,
        "requiresReviewer": requires_reviewer,
        "canExecuteWithCurrentActor": can_execute,
        "sourceArtifactIds": [str(value) for value in list(task.get("sourceArtifactIds") or [])[:12] if str(value or "").strip()],
        "createdAt": str(task.get("createdAt") or ""),
        "updatedAt": str(task.get("updatedAt") or task.get("createdAt") or ""),
    }


def _steward_workbench_stage(
    stage_id: str,
    title: str,
    description: str,
    recommended_action: str,
    recommendations: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    *,
    expected_task_type: str,
    next_tool: str,
) -> dict[str, Any]:
    stage_recommendations = [
        item
        for item in recommendations
        if str(item.get("recommendedAction") or "") == recommended_action
    ]
    stage_tasks = [
        item
        for item in tasks
        if str(item.get("taskType") or "") == expected_task_type
    ]
    open_count = len(stage_tasks)
    executable_count = sum(1 for item in stage_recommendations if bool(item.get("canExecuteWithCurrentActor")))
    return {
        "stageId": stage_id,
        "title": title,
        "description": description,
        "recommendedAction": recommended_action,
        "nextTool": next_tool,
        "openCount": open_count,
        "executableCount": executable_count,
        "blockedCount": max(0, open_count - executable_count),
        "items": stage_recommendations[:6],
        "status": "clear" if open_count == 0 else ("actionable" if executable_count else "needs_permission_or_reviewer"),
    }


def _knowledge_health_finding(
    finding_type: str,
    severity: str,
    row: dict[str, Any],
    count: int,
    message: str,
) -> dict[str, Any]:
    return {
        "findingId": f"khealth:{row.get('knowledgeBaseId')}:{finding_type}",
        "findingType": finding_type,
        "severity": severity,
        "teamId": str(row.get("teamId") or ""),
        "teamName": str(row.get("teamName") or ""),
        "knowledgeBaseId": str(row.get("knowledgeBaseId") or ""),
        "knowledgeBaseName": str(row.get("knowledgeBaseName") or ""),
        "count": int(count),
        "message": message,
        "nextReviewTargetIds": [str(value) for value in list(row.get("nextReviewTargetIds") or []) if str(value or "").strip()],
    }


def _recommended_tool_for_action(action: str) -> str:
    return {
        "review_proposal": "knowledge_governance_tasks_tool",
        "review_rating_suggestion": "knowledge_governance_tasks_tool",
        "draft_refinement_proposal": "knowledge_proposal_tool",
        "suggest_rating_metadata": "knowledge_rating_suggestion_tool",
    }.get(str(action or "").strip(), "unified_memory_search_tool")


def _priority_rank(priority: str) -> int:
    return {"normal": 1, "elevated": 2, "urgent": 3}.get(str(priority or ""), 0)


def _add_all(target: set[str], values: list[str]) -> bool:
    changed = False
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in target:
            target.add(normalized)
            changed = True
    return changed


def _batch_from_proposal(
    owner_value: dict[str, Any],
    base: dict[str, Any],
    proposal: dict[str, Any],
    reviewer_id: str,
    now: str,
) -> dict[str, Any]:
    owner = _coerce_owner_context(owner_value)
    return {
        "batchId": _new_event_id("kbatch"),
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "knowledgeBaseId": base["knowledgeBaseId"],
        "proposalIds": [proposal["proposalId"]],
        "sourceArtifactIds": list(proposal.get("sourceArtifactIds") or []),
        "centralSourceIds": list(proposal.get("centralSourceIds") or []),
        "reviewedByAgentId": reviewer_id,
        "appliedAt": now,
        "status": "applied",
    }


def _item_from_proposal(
    owner_value: dict[str, Any],
    base: dict[str, Any],
    proposal: dict[str, Any],
    batch: dict[str, Any],
    reviewer_id: str,
    now: str,
) -> dict[str, Any]:
    owner = _coerce_owner_context(owner_value)
    return {
        "knowledgeItemId": _new_event_id("kitem"),
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "knowledgeBaseId": base["knowledgeBaseId"],
        "batchId": batch["batchId"],
        "sourceArtifactIds": list(proposal.get("sourceArtifactIds") or []),
        "centralSourceIds": list(proposal.get("centralSourceIds") or []),
        "title": proposal.get("title") or "",
        "summary": proposal.get("summary") or "",
        "content": proposal.get("content") or "",
        "tags": list(proposal.get("tags") or []),
        "importanceLevel": "medium",
        "confidence": 0.7,
        "stability": "evolving",
        "scope": "team" if owner["ownerType"] == "team" else "agent",
        "reviewPriority": "normal",
        "createdAt": now,
        "updatedAt": now,
        "reviewedAt": now,
        "appliedAt": now,
        "reviewedByAgentId": reviewer_id,
        "markedBy": "",
        "markedAt": "",
        "markingReason": "",
    }


def _direct_ingest_accepted_source_locked(
    owner_value: dict[str, Any],
    source: dict[str, Any],
    central_source: dict[str, Any],
    *,
    reviewer_id: str,
    knowledge_base_id: str,
    knowledge_title: str,
    knowledge_summary: str,
    knowledge_content: str,
    tags: list[str] | None,
    now: str,
) -> dict[str, Any]:
    owner = _coerce_owner_context(owner_value)
    target_owner, base = _require_base_with_owner(knowledge_base_id)
    target_owner = _coerce_owner_context(target_owner)
    if target_owner["ownerType"] != owner["ownerType"] or target_owner["ownerId"] != owner["ownerId"]:
        raise TeamKnowledgePermissionError("Direct ingestion target knowledge base must belong to the reviewed owner.")
    if not _can_review_owner_source(owner, reviewer_id):
        raise TeamKnowledgePermissionError("Agent is not allowed to direct-ingest this owner source.")
    normalized_title = trim_lines(knowledge_title or source.get("title") or central_source.get("title") or "", max_lines=1).strip()
    normalized_summary = trim_lines(
        knowledge_summary or source.get("summary") or central_source.get("summary") or "",
        max_lines=6,
    ).strip()
    normalized_content = trim_lines(knowledge_content or "", max_lines=120).strip()
    if not normalized_title:
        raise TeamKnowledgeError("Direct ingestion requires knowledgeTitle or source title.")
    if not normalized_content:
        raise TeamKnowledgeError("Direct ingestion requires knowledgeContent.")

    scoped_base_id = _owner_scoped_knowledge_base_id(owner, base["knowledgeBaseId"])
    source_artifact = create_source_artifact_from_central_source(
        scoped_base_id,
        str(central_source.get("centralSourceId") or ""),
        actor_agent_id=reviewer_id,
        title=normalized_title,
        summary=normalized_summary,
    )
    batch = {
        "batchId": _new_event_id("kbatch"),
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "knowledgeBaseId": base["knowledgeBaseId"],
        "proposalIds": [],
        "sourceArtifactIds": [source_artifact["sourceArtifactId"]],
        "centralSourceIds": [str(central_source.get("centralSourceId") or "")],
        "reviewedByAgentId": reviewer_id,
        "appliedAt": now,
        "status": "applied",
        "ingestionMode": "source_review_direct",
    }
    item = {
        "knowledgeItemId": _new_event_id("kitem"),
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "knowledgeBaseId": base["knowledgeBaseId"],
        "batchId": batch["batchId"],
        "sourceArtifactIds": [source_artifact["sourceArtifactId"]],
        "centralSourceIds": [str(central_source.get("centralSourceId") or "")],
        "title": normalized_title,
        "summary": normalized_summary,
        "content": normalized_content,
        "tags": _unique_strings(tags or [])[:24],
        "importanceLevel": "medium",
        "confidence": 0.75,
        "stability": "evolving",
        "scope": "team" if owner["ownerType"] == "team" else "agent",
        "reviewPriority": "normal",
        "createdAt": now,
        "updatedAt": now,
        "reviewedAt": now,
        "appliedAt": now,
        "reviewedByAgentId": reviewer_id,
        "markedBy": "",
        "markedAt": "",
        "markingReason": "",
        "ingestionMode": "source_review_direct",
    }
    _append_jsonl(_batches_path_for_owner(owner), batch)
    _append_jsonl(_items_path_for_owner(owner), item)
    _append_audit(owner, "knowledge.item.direct_ingested", item, actor_agent_id=reviewer_id)
    _record_event(
        "knowledge.item.direct_ingested",
        owner,
        base["knowledgeBaseId"],
        actor_agent_id=reviewer_id,
        fields={
            "sourceArtifactId": source_artifact["sourceArtifactId"],
            "centralSourceId": str(central_source.get("centralSourceId") or ""),
            "knowledgeItemId": item["knowledgeItemId"],
            "ingestionMode": "source_review_direct",
        },
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "ingested",
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "knowledgeBaseId": base["knowledgeBaseId"],
        "scopedKnowledgeBaseId": scoped_base_id,
        "sourceArtifact": source_artifact,
        "batch": batch,
        "item": item,
        "updatedAt": now,
    }


def _normalize_acl(raw: Any) -> dict[str, Any]:
    payload = raw if isinstance(raw, dict) else {}
    return {
        "read": str(payload.get("read") or "team").strip() or "team",
        "propose": str(payload.get("propose") or "team").strip() or "team",
        "review": str(payload.get("review") or "review_roles").strip() or "review_roles",
        "grants": {
            "read": _unique_strings((payload.get("grants") or {}).get("read") if isinstance(payload.get("grants"), dict) else []),
            "propose": _unique_strings((payload.get("grants") or {}).get("propose") if isinstance(payload.get("grants"), dict) else []),
            "review": _unique_strings((payload.get("grants") or {}).get("review") if isinstance(payload.get("grants"), dict) else []),
            "*": _unique_strings((payload.get("grants") or {}).get("*") if isinstance(payload.get("grants"), dict) else []),
        },
    }


def _repair_base_for_owner(owner_value: Any, base: dict[str, Any]) -> dict[str, Any]:
    owner = _coerce_owner_context(owner_value)
    now = utc_now_iso()
    owner_type = str(base.get("ownerType") or owner.get("ownerType") or "team").strip()
    owner_id = _safe_token(base.get("ownerId"), default=str(owner.get("ownerId") or ""), max_length=128)
    return {
        "knowledgeBaseId": _safe_token(base.get("knowledgeBaseId"), default=_new_event_id("kb"), max_length=128),
        "ownerType": owner_type,
        "ownerId": owner_id,
        "teamId": _safe_token(base.get("teamId"), default=owner_id if owner_type == "team" else "", max_length=96),
        "agentId": _safe_token(base.get("agentId"), default=owner_id if owner_type == "agent" else "", max_length=128),
        "name": trim_lines(str(base.get("name") or ("Agent Knowledge" if owner_type == "agent" else "Team Knowledge")), max_lines=1).strip(),
        "description": trim_lines(str(base.get("description") or ""), max_lines=6).strip(),
        "status": str(base.get("status") or "active").strip() or "active",
        "acl": _normalize_acl(base.get("acl")),
        "createdAt": str(base.get("createdAt") or now),
        "updatedAt": str(base.get("updatedAt") or base.get("createdAt") or now),
    }


def _repair_base(team_id: str, base: dict[str, Any]) -> dict[str, Any]:
    return _repair_base_for_owner(_owner_context("team", team_id), base)


def _load_bases_state_for_owner(owner_value: Any) -> dict[str, Any]:
    path = _knowledge_bases_path_for_owner(_coerce_owner_context(owner_value))
    if not path.exists():
        return {"schemaVersion": SCHEMA_VERSION, "updatedAt": utc_now_iso(), "knowledgeBases": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schemaVersion": SCHEMA_VERSION, "updatedAt": utc_now_iso(), "knowledgeBases": []}
    if not isinstance(payload, dict):
        return {"schemaVersion": SCHEMA_VERSION, "updatedAt": utc_now_iso(), "knowledgeBases": []}
    payload.setdefault("schemaVersion", SCHEMA_VERSION)
    payload.setdefault("updatedAt", "")
    payload.setdefault("knowledgeBases", [])
    return payload


def _load_bases_state(team_id: str) -> dict[str, Any]:
    return _load_bases_state_for_owner(_owner_context("team", team_id))


def _source_governance_for_owner(owner_value: Any) -> dict[str, Any]:
    owner = _coerce_owner_context(owner_value)
    path = _owner_source_governance_path(owner)
    if not path.exists():
        return {
            "schemaVersion": SCHEMA_VERSION,
            "ownerType": owner["ownerType"],
            "ownerId": owner["ownerId"],
            "localStewardAgentIds": [],
            "updatedAt": "",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return {
        "schemaVersion": int(payload.get("schemaVersion") or SCHEMA_VERSION),
        "ownerType": str(payload.get("ownerType") or owner["ownerType"]),
        "ownerId": str(payload.get("ownerId") or owner["ownerId"]),
        "localStewardAgentIds": _unique_strings(payload.get("localStewardAgentIds") or []),
        "updatedAt": str(payload.get("updatedAt") or ""),
    }


def _save_bases_state_for_owner(owner_value: Any, state: dict[str, Any]) -> None:
    _write_json(_knowledge_bases_path_for_owner(_coerce_owner_context(owner_value)), state)


def _save_bases_state(team_id: str, state: dict[str, Any]) -> None:
    _save_bases_state_for_owner(_owner_context("team", team_id), state)


def _append_audit(owner_value: Any, action: str, payload: dict[str, Any], *, actor_agent_id: str = "") -> None:
    owner = _coerce_owner_context(owner_value)
    _append_jsonl(
        _audit_path_for_owner(owner),
        {
            "auditId": _new_event_id("kaudit"),
            "action": action,
            "actorAgentId": str(actor_agent_id or "").strip(),
            "createdAt": utc_now_iso(),
            "payload": {
                "ownerType": payload.get("ownerType") or owner.get("ownerType"),
                "ownerId": payload.get("ownerId") or owner.get("ownerId"),
                "teamId": payload.get("teamId"),
                "agentId": payload.get("agentId"),
                "knowledgeBaseId": payload.get("knowledgeBaseId") or payload.get("targetKnowledgeBaseId"),
                "sourceArtifactId": payload.get("sourceArtifactId"),
                "inboxSourceId": payload.get("inboxSourceId"),
                "centralSourceId": payload.get("centralSourceId"),
                "proposalId": payload.get("proposalId"),
                "batchId": payload.get("batchId"),
                "knowledgeItemId": payload.get("knowledgeItemId"),
                "status": payload.get("status"),
            },
        },
    )


def _record_event(
    event_code: str,
    owner_value: Any,
    knowledge_base_id: str,
    *,
    actor_agent_id: str = "",
    fields: dict[str, Any] | None = None,
) -> None:
    owner = _coerce_owner_context(owner_value)
    try:
        record_runtime_scene_event(
            "team_knowledge_service",
            "knowledge",
            event_code,
            message=event_code,
            outcome="observed",
            fields={
                "ownerType": owner.get("ownerType"),
                "ownerId": owner.get("ownerId"),
                "teamId": owner.get("ownerId") if owner.get("ownerType") == "team" else "",
                "agentId": owner.get("ownerId") if owner.get("ownerType") == "agent" else "",
                "knowledgeBaseId": knowledge_base_id,
                "actorAgentId": str(actor_agent_id or "").strip(),
                **(fields or {}),
            },
            lifecycle=True,
        )
    except Exception:
        pass


def _enum_value(value: str, allowed: set[str], label: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in allowed:
        raise TeamKnowledgeError(f"Unsupported {label}: {value}")
    return normalized


def _find_by_id(items: list[dict[str, Any]], key: str, value: str) -> dict[str, Any] | None:
    normalized = str(value or "").strip()
    for item in items:
        if isinstance(item, dict) and str(item.get(key) or "").strip() == normalized:
            return item
    return None


def _bounded_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {str(key)[:80]: value for key, value in list(payload.items())[:40]}


def _source_hash(source_ref: dict[str, Any], title: str, summary: str) -> str:
    text = json.dumps({"sourceRef": source_ref, "title": title, "summary": summary}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _source_hash_with_content(source_ref: dict[str, Any], title: str, summary: str, original_content: str) -> str:
    payload = {
        "sourceRef": source_ref,
        "title": title,
        "summary": summary,
        "originalContent": original_content,
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_source_review_decision(decision: str) -> str:
    normalized = str(decision or "").strip().lower().replace("-", "_")
    aliases = {
        "accept": "accepted",
        "approve": "accepted",
        "approved": "accepted",
        "reject": "rejected",
        "more_context": "needs_more_context",
        "need_more_context": "needs_more_context",
        "needs_more": "needs_more_context",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in SOURCE_REVIEW_DECISIONS:
        raise TeamKnowledgeError("Source review decision must be accepted, rejected, duplicate, or needs_more_context.")
    return normalized


def _write_owner_inbox_source_file(
    owner_value: Any,
    inbox_source_id: str,
    *,
    original_filename: str,
    original_content: str,
    source_ref: dict[str, Any],
    title: str,
    summary: str,
) -> Path:
    owner = _coerce_owner_context(owner_value)
    default_filename = "source.txt" if str(original_content or "") else "source.json"
    filename = _safe_source_filename(original_filename, default=default_filename)
    source_dir = _owner_inbox_source_dir(owner, inbox_source_id)
    path = source_dir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    if str(original_content or ""):
        path.write_text(str(original_content), encoding="utf-8")
    else:
        path.write_text(
            json.dumps(
                {
                    "schemaVersion": SCHEMA_VERSION,
                    "sourceRef": _bounded_dict(source_ref),
                    "title": title,
                    "summary": summary,
                    "capturedAt": utc_now_iso(),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return path


def _promote_owner_source_to_central_locked(
    owner_value: Any,
    source: dict[str, Any],
    *,
    reviewer_id: str,
    resolution_note: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    owner = _coerce_owner_context(owner_value)
    source_hash = str(source.get("sourceHash") or "").strip()
    if not source_hash:
        raise TeamKnowledgeError("Inbox source requires sourceHash before central promotion.")
    _assert_central_source_write_allowed()
    existing = _find_central_source_by_hash_locked(source_hash)
    dedupe_status = "reused" if existing else "created"
    if existing:
        central_source = existing
    else:
        now = utc_now_iso()
        central_source_id = _new_event_id("csrc")
        central_path = _copy_or_write_central_source_file(owner, source, central_source_id)
        central_source = {
            "schemaVersion": SCHEMA_VERSION,
            "centralSourceId": central_source_id,
            "status": "active",
            "sourceHash": source_hash,
            "sourceType": str(source.get("sourceType") or ""),
            "sourceRef": _bounded_dict(source.get("sourceRef") if isinstance(source.get("sourceRef"), dict) else {}),
            "sourceCreatedAt": str(source.get("sourceCreatedAt") or ""),
            "title": trim_lines(str(source.get("title") or ""), max_lines=1).strip(),
            "summary": trim_lines(str(source.get("summary") or ""), max_lines=16).strip(),
            "centralPath": _project_relative_path(central_path),
            "originOwnerType": owner["ownerType"],
            "originOwnerId": owner["ownerId"],
            "originInboxSourceId": str(source.get("inboxSourceId") or ""),
            "originOriginalPath": str(source.get("originalPath") or ""),
            "acceptedByAgentId": reviewer_id,
            "acceptedAt": now,
            "updatedAt": now,
        }
        registry = _read_jsonl(_central_source_registry_path())
        registry.append(central_source)
        _write_jsonl(_central_source_registry_path(), registry)
    promotion = _append_owner_ref_for_central_source_locked(
        owner,
        source,
        central_source,
        reviewer_id=reviewer_id,
        decision="accepted",
        resolution_note=resolution_note,
        dedupe_status=dedupe_status,
    )
    return central_source, promotion


def _resolve_duplicate_central_source_locked(source: dict[str, Any], *, duplicate_of: str) -> dict[str, Any]:
    normalized_duplicate_of = str(duplicate_of or "").strip()
    central_source = _find_central_source_by_id_locked(normalized_duplicate_of) if normalized_duplicate_of else {}
    if not central_source:
        central_source = _find_central_source_by_hash_locked(str(source.get("sourceHash") or "").strip())
    if not central_source:
        raise TeamKnowledgeError("Duplicate source review requires duplicateOf or an existing central source with the same sourceHash.")
    return central_source


def _append_owner_ref_for_central_source_locked(
    owner_value: Any,
    source: dict[str, Any],
    central_source: dict[str, Any],
    *,
    reviewer_id: str,
    decision: str,
    resolution_note: str,
    dedupe_status: str,
) -> dict[str, Any]:
    _assert_central_source_write_allowed()
    owner = _coerce_owner_context(owner_value)
    central_source_id = str(central_source.get("centralSourceId") or "").strip()
    inbox_source_id = str(source.get("inboxSourceId") or "").strip()
    now = utc_now_iso()
    refs = _read_jsonl(_central_owner_refs_path())
    for ref in refs:
        if (
            str(ref.get("centralSourceId") or "") == central_source_id
            and str(ref.get("ownerType") or "") == owner["ownerType"]
            and str(ref.get("ownerId") or "") == owner["ownerId"]
            and str(ref.get("inboxSourceId") or "") == inbox_source_id
        ):
            return {
                "promotionId": str(ref.get("promotionId") or ""),
                "ownerRefId": str(ref.get("ownerRefId") or ""),
                "centralSourceId": central_source_id,
                "dedupeStatus": "existing_owner_ref",
                "decision": str(ref.get("decision") or decision),
            }
    owner_ref_id = _new_event_id("srcown")
    promotion_id = _new_event_id("srcprom")
    ref = {
        "schemaVersion": SCHEMA_VERSION,
        "ownerRefId": owner_ref_id,
        "promotionId": promotion_id,
        "centralSourceId": central_source_id,
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "inboxSourceId": inbox_source_id,
        "originalPath": str(source.get("originalPath") or ""),
        "sourceHash": str(source.get("sourceHash") or ""),
        "decision": decision,
        "dedupeStatus": dedupe_status,
        "reviewedByAgentId": reviewer_id,
        "resolutionNote": trim_lines(resolution_note or "", max_lines=6).strip(),
        "createdAt": now,
        "updatedAt": now,
    }
    refs.append(ref)
    _write_jsonl(_central_owner_refs_path(), refs)
    promotion = {
        "schemaVersion": SCHEMA_VERSION,
        "promotionId": promotion_id,
        "ownerRefId": owner_ref_id,
        "centralSourceId": central_source_id,
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "inboxSourceId": inbox_source_id,
        "decision": decision,
        "dedupeStatus": dedupe_status,
        "reviewedByAgentId": reviewer_id,
        "createdAt": now,
    }
    _append_jsonl(_central_promotion_log_path(), promotion)
    return promotion


def _copy_or_write_central_source_file(owner_value: Any, source: dict[str, Any], central_source_id: str) -> Path:
    _assert_central_source_write_allowed()
    owner = _coerce_owner_context(owner_value)
    accepted_at = str(source.get("reviewedAt") or source.get("capturedAt") or utc_now_iso())
    year = _safe_token(accepted_at[:4], default="undated", max_length=16)
    source_dir = _central_source_accepted_dir() / year / _safe_token(central_source_id, default="source", max_length=128)
    source_dir.mkdir(parents=True, exist_ok=True)
    original_path = _project_path_from_relative(str(source.get("originalPath") or ""))
    filename = _safe_source_filename(str(source.get("originalFilename") or ""), default="source.txt")
    target_path = source_dir / filename
    if original_path and original_path.exists() and original_path.is_file():
        shutil.copy2(original_path, target_path)
    else:
        target_path.write_text(
            json.dumps(
                {
                    "schemaVersion": SCHEMA_VERSION,
                    "ownerType": owner["ownerType"],
                    "ownerId": owner["ownerId"],
                    "inboxSourceId": source.get("inboxSourceId") or "",
                    "sourceType": source.get("sourceType") or "",
                    "sourceRef": source.get("sourceRef") or {},
                    "title": source.get("title") or "",
                    "summary": source.get("summary") or "",
                    "sourceHash": source.get("sourceHash") or "",
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return target_path


def _require_central_source_for_owner(
    owner_value: Any,
    central_source_id: str,
    *,
    actor_agent_id: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    owner = _coerce_owner_context(owner_value)
    central_source = _find_central_source_by_id_locked(central_source_id)
    if not central_source:
        raise TeamKnowledgeNotFoundError("Central source not found.")
    if str(central_source.get("status") or "active") not in CENTRAL_SOURCE_STATUSES:
        raise TeamKnowledgeError("Central source status is invalid.")
    if str(central_source.get("status") or "active") != "active":
        raise TeamKnowledgePermissionError("Central source is not active.")
    refs = [
        ref
        for ref in _read_jsonl(_central_owner_refs_path())
        if str(ref.get("centralSourceId") or "") == str(central_source.get("centralSourceId") or "")
        and str(ref.get("ownerType") or "") == owner["ownerType"]
        and str(ref.get("ownerId") or "") == owner["ownerId"]
    ]
    if refs:
        return central_source, refs[0]
    if _is_global_knowledge_steward(str(actor_agent_id or "").strip()):
        return central_source, {}
    raise TeamKnowledgePermissionError("Central source is not linked to this owner.")


def _find_central_source_by_hash_locked(source_hash: str) -> dict[str, Any]:
    normalized_hash = str(source_hash or "").strip()
    if not normalized_hash:
        return {}
    for source in _read_jsonl(_central_source_registry_path()):
        if str(source.get("sourceHash") or "").strip() == normalized_hash:
            return source
    return {}


def _find_central_source_by_id_locked(central_source_id: str) -> dict[str, Any]:
    normalized_id = str(central_source_id or "").strip()
    if not normalized_id:
        return {}
    for source in _read_jsonl(_central_source_registry_path()):
        if str(source.get("centralSourceId") or "").strip() == normalized_id:
            return source
    return {}


def _central_owner_ref_visible(ref: dict[str, Any], agent_id: str, *, internal: bool = False) -> bool:
    if internal:
        return True
    normalized_agent_id = str(agent_id or "").strip()
    if _is_global_knowledge_steward(normalized_agent_id):
        return True
    owner = _owner_context(str(ref.get("ownerType") or ""), str(ref.get("ownerId") or ""))
    return _can_read_owner_source_inbox(owner, normalized_agent_id)


def _rewrite_owner_source_review_queue_locked(owner_value: Any, sources: list[dict[str, Any]]) -> None:
    pending_sources = [
        source
        for source in sources
        if str(source.get("status") or "") in {"pending", "needs_more_context"}
    ]
    _write_jsonl(_owner_source_review_queue_path(owner_value), pending_sources)


def _source_inbox_summary(sources: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = {status: 0 for status in sorted(SOURCE_INBOX_STATUSES)}
    for source in sources:
        status = str(source.get("status") or "")
        if status in status_counts:
            status_counts[status] += 1
    return {
        "sourceCount": len(sources),
        "pendingSourceCount": status_counts.get("pending", 0),
        "acceptedSourceCount": status_counts.get("accepted", 0),
        "rejectedSourceCount": status_counts.get("rejected", 0),
        "duplicateSourceCount": status_counts.get("duplicate", 0),
        "needsMoreContextSourceCount": status_counts.get("needs_more_context", 0),
        "statusCounts": status_counts,
    }


def _safe_source_filename(value: Any, *, default: str) -> str:
    raw = Path(str(value or "")).name.strip()
    if not raw:
        raw = default
    safe = _SAFE_ID_FRAGMENT.sub("-", raw).strip(".-_")
    if not safe:
        safe = default
    if "." not in safe and "." in default:
        safe = f"{safe}{Path(default).suffix}"
    return safe[:180]


def _project_relative_path(path: Path) -> str:
    resolved = path.resolve()
    workspace_root = _route_team_knowledge_workspace_path(seed=True).resolve()
    try:
        return f"workspace/{resolved.relative_to(workspace_root).as_posix()}"
    except (OSError, ValueError):
        pass
    try:
        return resolved.relative_to(_project_root().resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)


def _project_path_from_relative(value: str) -> Path:
    text = str(value or "").strip()
    if not text:
        return Path()
    candidate = Path(text)
    if candidate.parts and candidate.parts[0].lower() == "workspace":
        return _route_team_knowledge_workspace_path(*candidate.parts[1:], seed=True)
    if not candidate.is_absolute():
        candidate = _project_root() / candidate
    workspace_root = _route_team_knowledge_workspace_path(seed=True).resolve()
    try:
        candidate.resolve().relative_to(workspace_root)
        return candidate
    except (OSError, ValueError):
        pass
    try:
        candidate.resolve().relative_to(_project_root().resolve())
    except (OSError, ValueError):
        return Path()
    return candidate


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                items.append(payload)
    except (OSError, json.JSONDecodeError):
        return []
    return items


def _write_jsonl(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in items if isinstance(item, dict))
    path.write_text(text, encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _owner_context(
    owner_type: str,
    owner_id: str,
    *,
    team: dict[str, Any] | None = None,
    agent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_type = _normalize_owner_type(owner_type) or "team"
    normalized_id = str(owner_id or "").strip()
    payload: dict[str, Any] = {
        "ownerType": normalized_type,
        "ownerId": normalized_id,
        "team": team if isinstance(team, dict) else {},
        "agent": agent if isinstance(agent, dict) else {},
    }
    if normalized_type == "team" and not payload["team"] and normalized_id:
        try:
            payload["team"] = team_service.get_team(normalized_id)
        except Exception:
            payload["team"] = {"teamId": normalized_id, "name": ""}
    if normalized_type == "agent" and not payload["agent"] and normalized_id:
        try:
            payload["agent"] = agent_directory_service.get_agent(normalized_id) or {"agentId": normalized_id}
        except Exception:
            payload["agent"] = {"agentId": normalized_id}
    return payload


def _coerce_owner_context(value: Any) -> dict[str, Any]:
    if isinstance(value, dict) and str(value.get("ownerType") or "").strip() in KNOWLEDGE_OWNER_TYPES:
        raw_type = str(value.get("ownerType") or "")
        return _owner_context(
            raw_type,
            str(value.get("ownerId") or value.get("teamId") or value.get("agentId") or ""),
            team=value.get("team") if isinstance(value.get("team"), dict) else (value if raw_type == "team" else None),
            agent=value.get("agent") if isinstance(value.get("agent"), dict) else (value if raw_type == "agent" else None),
        )
    if isinstance(value, dict) and str(value.get("teamId") or "").strip():
        return _owner_context("team", str(value.get("teamId") or ""), team=value)
    if isinstance(value, dict) and str(value.get("agentId") or "").strip():
        return _owner_context("agent", str(value.get("agentId") or ""), agent=value)
    return _owner_context("team", str(value or ""))


def _normalize_owner_type(owner_type: Any) -> str:
    normalized = str(owner_type or "").strip().lower()
    if not normalized:
        return ""
    if normalized not in KNOWLEDGE_OWNER_TYPES:
        raise TeamKnowledgeError(f"Unsupported knowledge owner type: {owner_type}")
    return normalized


def _iter_knowledge_owners(
    *,
    agent_id: str = "",
    include_archived: bool = True,
    include_all_agents: bool = False,
) -> list[dict[str, Any]]:
    owners: list[dict[str, Any]] = []
    normalized_agent_id = str(agent_id or "").strip()
    if normalized_agent_id:
        agent = agent_directory_service.get_agent(normalized_agent_id, include_archived=include_archived)
        if agent:
            owners.append(_owner_context("agent", normalized_agent_id, agent=agent))
    elif include_all_agents:
        for agent in agent_directory_service.list_agents(include_archived=include_archived):
            agent_id_value = str(agent.get("agentId") or "").strip()
            if agent_id_value:
                owners.append(_owner_context("agent", agent_id_value, agent=agent))
    for team in team_service.list_teams_compact(include_archived=include_archived).get("teams") or []:
        team_id = str(team.get("teamId") or "").strip()
        if team_id:
            owners.append(_owner_context("team", team_id, team=team))
    return owners


def _knowledge_root(team_id: str) -> Path:
    return _route_team_knowledge_workspace_path(
        "teams",
        _safe_token(team_id, default="team", max_length=96),
        "knowledge",
    )


def _knowledge_root_for_owner(owner_value: Any) -> Path:
    owner = _coerce_owner_context(owner_value)
    owner_type = str(owner.get("ownerType") or "team")
    owner_id = str(owner.get("ownerId") or "").strip()
    if owner_type == "agent":
        return _route_team_knowledge_workspace_path(
            "agents",
            _safe_token(owner_id, default="agent", max_length=128),
            "knowledge",
        )
    return _knowledge_root(owner_id)


def _knowledge_bases_path_for_owner(owner_value: Any) -> Path:
    return _knowledge_root_for_owner(owner_value) / "knowledge_bases.json"


def _knowledge_bases_path(team_id: str) -> Path:
    return _knowledge_root(team_id) / "knowledge_bases.json"


def _source_artifacts_path_for_owner(owner_value: Any) -> Path:
    return _knowledge_root_for_owner(owner_value) / "source_artifacts.jsonl"


def _source_artifacts_path(team_id: str) -> Path:
    return _knowledge_root(team_id) / "source_artifacts.jsonl"


def _owner_source_governance_path(owner_value: Any) -> Path:
    return _knowledge_root_for_owner(owner_value) / "source_governance.json"


def _owner_inbox_root_for_owner(owner_value: Any) -> Path:
    return _knowledge_root_for_owner(owner_value) / "inbox"


def _owner_inbox_source_dir(owner_value: Any, inbox_source_id: str) -> Path:
    safe_id = _safe_token(inbox_source_id, default="source", max_length=128)
    return _owner_inbox_root_for_owner(owner_value) / "sources" / safe_id


def _owner_source_index_path(owner_value: Any) -> Path:
    return _owner_inbox_root_for_owner(owner_value) / "source_index.jsonl"


def _owner_source_review_queue_path(owner_value: Any) -> Path:
    return _owner_inbox_root_for_owner(owner_value) / "review_queue.jsonl"


def _owner_source_rejected_path(owner_value: Any) -> Path:
    return _owner_inbox_root_for_owner(owner_value) / "rejected.jsonl"


def _proposals_path_for_owner(owner_value: Any) -> Path:
    return _knowledge_root_for_owner(owner_value) / "refinement_proposals.jsonl"


def _proposals_path(team_id: str) -> Path:
    return _knowledge_root(team_id) / "refinement_proposals.jsonl"


def _batches_path_for_owner(owner_value: Any) -> Path:
    return _knowledge_root_for_owner(owner_value) / "batches.jsonl"


def _batches_path(team_id: str) -> Path:
    return _knowledge_root(team_id) / "batches.jsonl"


def _items_path_for_owner(owner_value: Any) -> Path:
    return _knowledge_root_for_owner(owner_value) / "items.jsonl"


def _items_path(team_id: str) -> Path:
    return _knowledge_root(team_id) / "items.jsonl"


def _audit_path_for_owner(owner_value: Any) -> Path:
    return _knowledge_root_for_owner(owner_value) / "audit.jsonl"


def _audit_path(team_id: str) -> Path:
    return _knowledge_root(team_id) / "audit.jsonl"


def _rating_suggestions_path_for_owner(owner_value: Any) -> Path:
    return _knowledge_root_for_owner(owner_value) / "rating_suggestions.jsonl"


def _rating_suggestions_path(team_id: str) -> Path:
    return _knowledge_root(team_id) / "rating_suggestions.jsonl"


def _developer_sandbox_module():
    from core.infrastructure import developer_sandbox

    return developer_sandbox


def _route_team_knowledge_workspace_path(*parts: str, intent: str = "state", seed: bool = True) -> Path:
    return _developer_sandbox_module().route_workspace_path(
        _project_root(),
        "team_knowledge",
        *parts,
        intent=intent,
        seed=seed,
    )


def _assert_central_source_write_allowed() -> None:
    _route_team_knowledge_workspace_path("knowledge", "sources", intent="central_promotion", seed=False)


def _central_knowledge_root() -> Path:
    return _route_team_knowledge_workspace_path("knowledge", intent="state", seed=True)


def _central_sources_root() -> Path:
    return _central_knowledge_root() / "sources"


def _central_source_accepted_dir() -> Path:
    return _central_sources_root() / "accepted"


def _central_source_registry_root() -> Path:
    return _central_sources_root() / "registry"


def _central_source_registry_path() -> Path:
    return _central_source_registry_root() / "source_registry.jsonl"


def _central_owner_refs_path() -> Path:
    return _central_source_registry_root() / "owner_refs.jsonl"


def _central_promotion_log_path() -> Path:
    return _central_source_registry_root() / "promotion_log.jsonl"


def _project_root() -> Path:
    root = Path(PROJECT_ROOT).resolve()
    return root.parent if root.name.lower() == "workspace" else root


def _sync_roots() -> None:
    if team_service.PROJECT_ROOT != PROJECT_ROOT:
        team_service.PROJECT_ROOT = PROJECT_ROOT
    if chat_room_service.PROJECT_ROOT != PROJECT_ROOT:
        chat_room_service.PROJECT_ROOT = PROJECT_ROOT
    if agent_directory_service.PROJECT_ROOT != PROJECT_ROOT:
        agent_directory_service.PROJECT_ROOT = PROJECT_ROOT


def _safe_token(value: Any, *, default: str, max_length: int) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    text = _SAFE_ID_FRAGMENT.sub("-", text).strip(".-_")
    return (text or default)[:max_length]


def _owner_scoped_knowledge_base_id(owner_value: Any, knowledge_base_id: str) -> str:
    owner = _coerce_owner_context(owner_value)
    owner_type = _safe_token(owner.get("ownerType"), default="", max_length=32)
    owner_id = _safe_token(owner.get("ownerId"), default="", max_length=128)
    base_id = _safe_token(knowledge_base_id, default="", max_length=128)
    if owner_type and owner_id and base_id:
        return f"{owner_type}:{owner_id}:{base_id}"
    return base_id


def _parse_owner_scoped_knowledge_base_id(value: Any) -> tuple[str, str, str]:
    normalized = str(value or "").strip()
    parts = normalized.split(":", 2)
    if len(parts) == 3 and parts[0].strip() in KNOWLEDGE_OWNER_TYPES and parts[1].strip() and parts[2].strip():
        owner_type = _safe_token(parts[0], default="", max_length=32)
        owner_id = _safe_token(parts[1], default="", max_length=128)
        base_id = _safe_token(parts[2], default="", max_length=128)
        return owner_type, owner_id, base_id
    return "", "", _safe_token(normalized, default="", max_length=128)


def _new_id(prefix: str, existing_ids: set[str], name: str) -> str:
    base = f"{prefix}-{_safe_token(name, default=prefix, max_length=42).lower()}"
    candidate = base
    index = 2
    while candidate in existing_ids:
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def _new_event_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _unique_strings(values: Any) -> list[str]:
    raw = [values] if isinstance(values, str) else list(values or [])
    result: list[str] = []
    for item in raw:
        text = trim_lines(str(item or ""), max_lines=1).strip()
        if text and text not in result:
            result.append(text)
    return result
