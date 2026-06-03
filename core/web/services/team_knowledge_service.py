"""Team-scoped knowledge base storage and governance service."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from datetime import UTC, datetime
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
REVIEW_ROLES = {"owner", "lead", "steward", "coordinator"}
IMPORTANCE_LEVELS = {"low", "medium", "high", "critical"}
STABILITY_VALUES = {"temporary", "evolving", "stable", "deprecated"}
SCOPES = {"agent", "team", "project", "global"}
REVIEW_PRIORITIES = {"normal", "elevated", "urgent"}
SUGGESTION_STATUSES = {"pending", "applied", "rejected"}
_SAFE_ID_FRAGMENT = re.compile(r"[^A-Za-z0-9_.-]+")
_SEARCH_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_.-]+|[\u4e00-\u9fff]")
_LOCK = threading.RLock()


class TeamKnowledgeError(ValueError):
    """Raised when a team knowledge request is invalid."""


class TeamKnowledgeNotFoundError(TeamKnowledgeError):
    """Raised when a knowledge resource does not exist."""


class TeamKnowledgePermissionError(TeamKnowledgeError):
    """Raised when an actor cannot perform the requested knowledge action."""


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def list_knowledge_overview(*, agent_id: str = "") -> dict[str, Any]:
    """Return all knowledge bases visible to an optional Agent."""

    _sync_roots()
    teams = team_service.list_teams_compact().get("teams") or []
    visible_bases: list[dict[str, Any]] = []
    pending_proposals = 0
    item_count = 0
    source_count = 0
    for team in teams:
        team_id = str(team.get("teamId") or "").strip()
        if not team_id:
            continue
        for base in _knowledge_bases_for_team(team_id):
            if not _can_access(team, base, agent_id, "read"):
                continue
            stats = _knowledge_base_stats(team_id, str(base.get("knowledgeBaseId") or ""))
            pending_proposals += stats["pendingProposalCount"]
            item_count += stats["itemCount"]
            source_count += stats["sourceArtifactCount"]
            visible_bases.append(
                {
                    **_knowledge_base_to_api(base, team),
                    "stats": stats,
                    "pendingProposals": _pending_proposals_for_base(team_id, str(base.get("knowledgeBaseId") or "")),
                    "permissions": _permissions_for_actor(team, base, agent_id),
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


def get_knowledge_steward_overview() -> dict[str, Any]:
    """Return the default knowledge steward Agent and its read-only governance posture."""

    _sync_roots()
    steward = agent_directory_service.get_agent(agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID)
    steward_id = str((steward or {}).get("agentId") or agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID).strip()
    governance_tasks = list_knowledge_governance_tasks(agent_id="", status="all")
    task_summary = dict(governance_tasks.get("summary") or {})
    open_tasks = [task for task in list(governance_tasks.get("tasks") or []) if str(task.get("status") or "") == "open"]
    open_tasks.sort(
        key=lambda item: (
            _priority_rank(str(item.get("priority") or "")),
            str(item.get("updatedAt") or item.get("createdAt") or ""),
        ),
        reverse=True,
    )
    permission_boundary = "proposal_and_rating_suggestion_only"
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
            "displayName": str((steward or {}).get("displayName") or "").strip() or "Knowledge Steward",
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
            "canDirectlyApplyKnowledge": False,
            "canDeleteKnowledge": False,
            "canChangeAcl": False,
            "canBypassReviewer": False,
            "formalKnowledgeRequiresReviewer": True,
            "knowledgeBodiesInPrompt": False,
        },
        "updatedAt": utc_now_iso(),
    }
    _record_event(
        "knowledge.steward.overview.viewed",
        "",
        "",
        actor_agent_id=steward_id,
        fields={
            "stewardAgentId": steward_id,
            "openTaskCount": int((payload["governance"]["summary"] or {}).get("openTaskCount") or 0),
            "permissionBoundary": permission_boundary,
        },
    )
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
        }
        for source_type in sorted(INGESTION_ADAPTERS)
    ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "adapters": adapters,
        "summary": {"adapterCount": len(adapters)},
        "updatedAt": utc_now_iso(),
    }


def list_team_knowledge_bases(team_id: str, *, agent_id: str = "") -> dict[str, Any]:
    team = _require_team(team_id)
    bases = []
    for base in _knowledge_bases_for_team(team["teamId"]):
        if _can_access(team, base, agent_id, "read"):
            bases.append(
                {
                    **_knowledge_base_to_api(base, team),
                    "stats": _knowledge_base_stats(team["teamId"], str(base.get("knowledgeBaseId") or "")),
                    "pendingProposals": _pending_proposals_for_base(team["teamId"], str(base.get("knowledgeBaseId") or "")),
                    "permissions": _permissions_for_actor(team, base, agent_id),
                }
            )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": team["teamId"],
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
    if actor_agent_id and not _member_role(team, actor_agent_id):
        raise TeamKnowledgePermissionError("Only Team members can create a team knowledge base.")
    normalized_name = trim_lines(name or "", max_lines=1).strip()
    if not normalized_name:
        raise TeamKnowledgeError("Knowledge base name is required.")
    now = utc_now_iso()
    with _LOCK:
        state = _load_bases_state(team["teamId"])
        existing_ids = {str(item.get("knowledgeBaseId") or "") for item in state.get("knowledgeBases") or []}
        knowledge_base_id = _new_id("kb", existing_ids, normalized_name)
        base = {
            "knowledgeBaseId": knowledge_base_id,
            "teamId": team["teamId"],
            "name": normalized_name,
            "description": trim_lines(description or "", max_lines=6).strip(),
            "status": "active",
            "acl": _normalize_acl(acl),
            "createdAt": now,
            "updatedAt": now,
        }
        state.setdefault("knowledgeBases", []).append(base)
        state["updatedAt"] = now
        _save_bases_state(team["teamId"], state)
        _append_audit(team["teamId"], "knowledge_base.created", base, actor_agent_id=actor_agent_id)
    _record_event("knowledge.knowledge_base.created", team["teamId"], knowledge_base_id, actor_agent_id=actor_agent_id)
    return {
        **_knowledge_base_to_api(base, team),
        "stats": _knowledge_base_stats(team["teamId"], knowledge_base_id),
        "permissions": _permissions_for_actor(team, base, actor_agent_id),
    }


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
) -> dict[str, Any]:
    team, base = _require_base_with_team(knowledge_base_id)
    _require_permission(team, base, actor_agent_id, "propose")
    normalized_type = str(source_type or "").strip()
    if normalized_type not in SOURCE_TYPES:
        raise TeamKnowledgeError(f"Unsupported source type: {source_type}")
    normalized_ref = source_ref if isinstance(source_ref, dict) else {}
    if normalized_type == "team_chat_refinement":
        _validate_team_chat_source(team, normalized_ref)
    now = utc_now_iso()
    artifact = {
        "sourceArtifactId": _new_event_id("src"),
        "teamId": team["teamId"],
        "knowledgeBaseId": base["knowledgeBaseId"],
        "sourceType": normalized_type,
        "sourceRef": _bounded_dict(normalized_ref),
        "capturedAt": now,
        "sourceCreatedAt": trim_lines(source_created_at or "", max_lines=1).strip(),
        "capturedBy": trim_lines(captured_by or actor_agent_id or "user", max_lines=1).strip(),
        "sourceHash": trim_lines(source_hash or _source_hash(normalized_ref, title, summary), max_lines=1).strip(),
        "evidenceRange": _bounded_dict(evidence_range if isinstance(evidence_range, dict) else {}),
        "title": trim_lines(title or normalized_type, max_lines=1).strip(),
        "summary": trim_lines(summary or "", max_lines=8).strip(),
    }
    with _LOCK:
        _append_jsonl(_source_artifacts_path(team["teamId"]), artifact)
        _append_audit(team["teamId"], "knowledge.source.registered", artifact, actor_agent_id=actor_agent_id)
    _record_event(
        "knowledge.source.registered",
        team["teamId"],
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
    team, base = _require_base_with_team(knowledge_base_id)
    actor_agent_id = str(proposed_by_agent_id or "").strip()
    _require_permission(team, base, actor_agent_id, "propose")
    normalized_title = trim_lines(title or "", max_lines=1).strip()
    normalized_content = trim_lines(content or "", max_lines=80).strip()
    if not normalized_title:
        raise TeamKnowledgeError("Proposal title is required.")
    if not normalized_content:
        raise TeamKnowledgeError("Proposal content is required.")
    artifact_ids = _unique_strings(source_artifact_ids or [])
    if artifact_ids:
        known_artifacts = {item["sourceArtifactId"] for item in _source_artifacts_for_base(team["teamId"], base["knowledgeBaseId"])}
        missing = [item for item in artifact_ids if item not in known_artifacts]
        if missing:
            raise TeamKnowledgeError(f"Unknown source artifact ids: {', '.join(missing[:3])}")
    now = utc_now_iso()
    proposal = {
        "proposalId": _new_event_id("kprop"),
        "teamId": team["teamId"],
        "targetKnowledgeBaseId": base["knowledgeBaseId"],
        "sourceArtifactIds": artifact_ids,
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
        _append_jsonl(_proposals_path(team["teamId"]), proposal)
        _append_audit(team["teamId"], "knowledge.proposal.created", proposal, actor_agent_id=actor_agent_id)
    _record_event(
        "knowledge.proposal.created",
        team["teamId"],
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
    proposal_title: str = "",
    proposal_summary: str = "",
    proposal_content: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Create one source artifact and one pending proposal from a semi-automatic adapter."""

    team, base = _require_base_with_team(knowledge_base_id)
    actor_agent_id = str(proposed_by_agent_id or captured_by or "").strip()
    _require_permission(team, base, actor_agent_id, "propose")
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
        "teamId": team["teamId"],
        "knowledgeBaseId": base["knowledgeBaseId"],
        "status": "submitted",
        "sourceArtifact": source,
        "proposal": proposal,
        "updatedAt": utc_now_iso(),
    }
    _append_audit(team["teamId"], "knowledge.ingestion.adapter.created", proposal, actor_agent_id=actor_agent_id)
    _record_event(
        "knowledge.ingestion.adapter.created",
        team["teamId"],
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
    team, base = _require_base_with_team(knowledge_base_id)
    reviewer_id = str(reviewed_by_agent_id or "").strip()
    _require_permission(team, base, reviewer_id, "review")
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in {"approved", "applied", "rejected"}:
        raise TeamKnowledgeError("Review status must be approved, applied, or rejected.")
    with _LOCK:
        proposals = _read_jsonl(_proposals_path(team["teamId"]))
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
            batch = _batch_from_proposal(team, base, proposal, reviewer_id, now)
            item = _item_from_proposal(team, base, proposal, batch, reviewer_id, now)
            proposal["batchId"] = batch["batchId"]
            proposal["knowledgeItemIds"] = [item["knowledgeItemId"]]
            _append_jsonl(_batches_path(team["teamId"]), batch)
            _append_jsonl(_items_path(team["teamId"]), item)
            _append_audit(team["teamId"], "knowledge.batch.applied", batch, actor_agent_id=reviewer_id)
        _write_jsonl(_proposals_path(team["teamId"]), proposals)
        _append_audit(team["teamId"], "knowledge.proposal.reviewed", proposal, actor_agent_id=reviewer_id)
    _record_event(
        "knowledge.proposal.reviewed",
        team["teamId"],
        base["knowledgeBaseId"],
        actor_agent_id=reviewer_id,
        fields={"proposalId": proposal["proposalId"], "status": proposal["status"], "batchId": proposal.get("batchId") or ""},
    )
    if batch:
        _record_event(
            "knowledge.batch.applied",
            team["teamId"],
            base["knowledgeBaseId"],
            actor_agent_id=reviewer_id,
            fields={"batchId": batch["batchId"], "knowledgeItemCount": 1},
        )
    return {"proposal": proposal, "batch": batch, "item": item}


def list_knowledge_items(knowledge_base_id: str, *, agent_id: str = "") -> dict[str, Any]:
    team, base = _require_base_with_team(knowledge_base_id)
    _require_permission(team, base, agent_id, "read")
    items = [
        item
        for item in _read_jsonl(_items_path(team["teamId"]))
        if str(item.get("knowledgeBaseId") or "") == base["knowledgeBaseId"]
    ]
    items.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": team["teamId"],
        "knowledgeBase": _knowledge_base_to_api(base, team),
        "items": items,
        "summary": {"itemCount": len(items)},
        "updatedAt": utc_now_iso(),
    }


def list_knowledge_governance_tasks(*, agent_id: str = "", status: str = "open") -> dict[str, Any]:
    """Return a reviewer-facing queue derived from proposals, rating suggestions, and source-only evidence."""

    _sync_roots()
    normalized_status = str(status or "open").strip().lower()
    if normalized_status not in {"open", "closed", "all"}:
        raise TeamKnowledgeError(f"Unsupported governance task status: {status}")
    tasks: list[dict[str, Any]] = []
    for team in team_service.list_teams_compact(include_archived=True).get("teams") or []:
        team_id = str(team.get("teamId") or "").strip()
        if not team_id:
            continue
        for base in _knowledge_bases_for_team(team_id):
            base_id = str(base.get("knowledgeBaseId") or "")
            permissions = _permissions_for_actor(team, base, agent_id)
            if not permissions["canRead"]:
                continue
            proposals = [
                proposal
                for proposal in _read_jsonl(_proposals_path(team_id))
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
                        team,
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
            for suggestion in _read_jsonl(_rating_suggestions_path(team_id)):
                if str(suggestion.get("knowledgeBaseId") or "") != base_id:
                    continue
                suggestion_status = str(suggestion.get("status") or "")
                task_closed = suggestion_status != "pending"
                if not _task_status_matches(task_closed, normalized_status):
                    continue
                tasks.append(
                    _governance_task(
                        team,
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
                for artifact in _source_artifacts_for_base(team_id, base_id):
                    source_id = str(artifact.get("sourceArtifactId") or "")
                    if source_id in proposal_source_ids:
                        continue
                    tasks.append(
                        _governance_task(
                            team,
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
        "agentId": str(agent_id or "").strip(),
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


def list_knowledge_steward_recommendations(*, agent_id: str = "", limit: int = 12) -> dict[str, Any]:
    """Return read-only steward recommendations derived from open governance tasks."""

    _sync_roots()
    steward = agent_directory_service.get_agent(agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID)
    steward_id = str((steward or {}).get("agentId") or agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID).strip()
    normalized_agent_id = str(agent_id or "").strip()
    bounded_limit = max(1, min(50, int(limit or 12)))
    tasks_payload = list_knowledge_governance_tasks(agent_id=normalized_agent_id, status="open")
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
    _record_event(
        "knowledge.steward.recommendations.viewed",
        "",
        "",
        actor_agent_id=steward_id,
        fields={
            "agentId": normalized_agent_id,
            "recommendationCount": payload["summary"]["recommendationCount"],
            "visibleRecommendationCount": payload["summary"]["visibleRecommendationCount"],
        },
    )
    return payload


def get_knowledge_steward_workbench(*, agent_id: str = "", limit: int = 12) -> dict[str, Any]:
    """Return the Knowledge Steward's consolidated read-only workbench."""

    _sync_roots()
    normalized_agent_id = str(agent_id or "").strip()
    bounded_limit = max(1, min(50, int(limit or 12)))
    overview = get_knowledge_steward_overview()
    tasks_payload = list_knowledge_governance_tasks(agent_id=normalized_agent_id, status="open")
    recommendations_payload = list_knowledge_steward_recommendations(agent_id=normalized_agent_id, limit=bounded_limit)
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
    _record_event(
        "knowledge.steward.workbench.viewed",
        "",
        "",
        actor_agent_id=str((payload.get("steward") or {}).get("agentId") or agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID),
        fields={
            "agentId": normalized_agent_id,
            "openTaskCount": int(payload["summary"].get("openTaskCount") or 0),
            "recommendationCount": int(payload["summary"].get("recommendationCount") or 0),
            "stageCount": len(stages),
        },
    )
    return payload


def get_knowledge_trace(knowledge_base_id: str, target_id: str, *, agent_id: str = "") -> dict[str, Any]:
    """Return the source -> proposal -> batch -> item -> rating trail for one knowledge object."""

    team, base = _require_base_with_team(knowledge_base_id)
    _require_permission(team, base, agent_id, "read")
    normalized_target_id = str(target_id or "").strip()
    if not normalized_target_id:
        raise TeamKnowledgeError("Knowledge trace target id is required.")
    artifacts = _source_artifacts_for_base(team["teamId"], base["knowledgeBaseId"])
    proposals = [
        proposal
        for proposal in _read_jsonl(_proposals_path(team["teamId"]))
        if str(proposal.get("targetKnowledgeBaseId") or "") == base["knowledgeBaseId"]
    ]
    batches = [
        batch
        for batch in _read_jsonl(_batches_path(team["teamId"]))
        if str(batch.get("knowledgeBaseId") or "") == base["knowledgeBaseId"]
    ]
    items = [
        item
        for item in _read_jsonl(_items_path(team["teamId"]))
        if str(item.get("knowledgeBaseId") or "") == base["knowledgeBaseId"]
    ]
    suggestions = [
        suggestion
        for suggestion in _read_jsonl(_rating_suggestions_path(team["teamId"]))
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
        "teamId": team["teamId"],
        "knowledgeBase": _knowledge_base_to_api(base, team),
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
    team, base = _require_base_with_team(knowledge_base_id)
    _require_permission(team, base, actor_agent_id, "review")
    with _LOCK:
        items = _read_jsonl(_items_path(team["teamId"]))
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
        _write_jsonl(_items_path(team["teamId"]), items)
        _append_audit(team["teamId"], "knowledge.item.rating.updated", item, actor_agent_id=actor_agent_id)
    _record_event(
        "knowledge.item.rating.updated",
        team["teamId"],
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
    team, base = _require_base_with_team(knowledge_base_id)
    suggester_id = str(suggested_by_agent_id or "").strip()
    _require_permission(team, base, suggester_id, "rate")
    normalized_target_type = str(target_type or "").strip().lower()
    if normalized_target_type not in {"proposal", "knowledge_item"}:
        raise TeamKnowledgeError("Rating suggestion targetType must be proposal or knowledge_item.")
    normalized_item_id = str(knowledge_item_id or "").strip()
    normalized_proposal_id = str(proposal_id or "").strip()
    if normalized_target_type == "knowledge_item":
        if not normalized_item_id:
            raise TeamKnowledgeError("knowledge_item rating suggestions require knowledgeItemId.")
        _require_item(team["teamId"], base["knowledgeBaseId"], normalized_item_id)
    if normalized_target_type == "proposal":
        if not normalized_proposal_id:
            raise TeamKnowledgeError("proposal rating suggestions require proposalId.")
        _require_proposal(team["teamId"], base["knowledgeBaseId"], normalized_proposal_id)
    now = utc_now_iso()
    suggestion = {
        "suggestionId": _new_event_id("krate"),
        "teamId": team["teamId"],
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
        _append_jsonl(_rating_suggestions_path(team["teamId"]), suggestion)
        _append_audit(team["teamId"], "knowledge.rating.suggested", suggestion, actor_agent_id=suggester_id)
    _record_event(
        "knowledge.rating.suggested",
        team["teamId"],
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
    team, base = _require_base_with_team(knowledge_base_id)
    _require_permission(team, base, agent_id, "read")
    normalized_status = str(status or "").strip().lower()
    if normalized_status and normalized_status not in SUGGESTION_STATUSES:
        raise TeamKnowledgeError(f"Unsupported rating suggestion status: {status}")
    suggestions = [
        item
        for item in _read_jsonl(_rating_suggestions_path(team["teamId"]))
        if str(item.get("knowledgeBaseId") or "") == base["knowledgeBaseId"]
        and (not normalized_status or str(item.get("status") or "") == normalized_status)
    ]
    suggestions.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": team["teamId"],
        "knowledgeBase": _knowledge_base_to_api(base, team),
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
    team, base = _require_base_with_team(knowledge_base_id)
    reviewer_id = str(reviewed_by_agent_id or "").strip()
    _require_permission(team, base, reviewer_id, "rate")
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
        suggestions = _read_jsonl(_rating_suggestions_path(team["teamId"]))
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
                    items = _read_jsonl(_items_path(team["teamId"]))
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
                _append_audit(team["teamId"], "knowledge.item.rating.updated", item, actor_agent_id=reviewer_id)
            suggestion["status"] = normalized_status
            suggestion["updatedAt"] = now
            suggestion["reviewedAt"] = now
            suggestion["reviewedByAgentId"] = reviewer_id
            suggestion["resolutionNote"] = trim_lines(resolution_note or "", max_lines=4).strip()
            reviewed.append({"suggestion": suggestion, "item": applied_item})
            _append_audit(team["teamId"], "knowledge.rating_suggestion.reviewed", suggestion, actor_agent_id=reviewer_id)
        if items is not None and items_changed:
            _write_jsonl(_items_path(team["teamId"]), items)
        _write_jsonl(_rating_suggestions_path(team["teamId"]), suggestions)
        _append_audit(
            team["teamId"],
            "knowledge.rating_suggestion.bulk_reviewed",
            {
                "teamId": team["teamId"],
                "knowledgeBaseId": base["knowledgeBaseId"],
                "status": normalized_status,
                "reviewedCount": len(reviewed),
                "skippedCount": len(skipped),
            },
            actor_agent_id=reviewer_id,
        )
    _record_event(
        "knowledge.rating_suggestion.bulk_reviewed",
        team["teamId"],
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
            team["teamId"],
            base["knowledgeBaseId"],
            actor_agent_id=reviewer_id,
            fields={"knowledgeItemId": applied_item["knowledgeItemId"], "importanceLevel": applied_item.get("importanceLevel")},
        )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": team["teamId"],
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
    team, base = _require_base_with_team(knowledge_base_id)
    reviewer_id = str(reviewed_by_agent_id or "").strip()
    _require_permission(team, base, reviewer_id, "rate")
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in {"applied", "rejected"}:
        raise TeamKnowledgeError("Rating suggestion review status must be applied or rejected.")
    with _LOCK:
        suggestions = _read_jsonl(_rating_suggestions_path(team["teamId"]))
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
            items = _read_jsonl(_items_path(team["teamId"]))
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
            _write_jsonl(_items_path(team["teamId"]), items)
            _append_audit(team["teamId"], "knowledge.item.rating.updated", item, actor_agent_id=reviewer_id)
        _write_jsonl(_rating_suggestions_path(team["teamId"]), suggestions)
        _append_audit(team["teamId"], "knowledge.rating_suggestion.reviewed", suggestion, actor_agent_id=reviewer_id)
    _record_event(
        "knowledge.rating_suggestion.reviewed",
        team["teamId"],
        base["knowledgeBaseId"],
        actor_agent_id=reviewer_id,
        fields={"suggestionId": suggestion["suggestionId"], "status": suggestion["status"]},
    )
    if applied_item:
        _record_event(
            "knowledge.item.rating.updated",
            team["teamId"],
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
    normalized_base_id = str(knowledge_base_id or "").strip()
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
    for team in team_service.list_teams_compact(include_archived=True).get("teams") or []:
        current_team_id = str(team.get("teamId") or "").strip()
        if normalized_team_id and current_team_id != normalized_team_id:
            continue
        for base in _knowledge_bases_for_team(current_team_id):
            base_id = str(base.get("knowledgeBaseId") or "")
            if normalized_base_id and base_id != normalized_base_id:
                continue
            if not _can_access(team, base, agent_id, "read"):
                continue
            scanned_bases += 1
            artifacts_by_id = {
                str(item.get("sourceArtifactId") or ""): item
                for item in _source_artifacts_for_base(current_team_id, base_id)
            }
            for item in _read_jsonl(_items_path(current_team_id)):
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
                view = _search_item_view(item, base, team, artifacts_by_id)
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


def get_knowledge_operations_health(*, agent_id: str = "") -> dict[str, Any]:
    """Return operational health for accessible team knowledge bases."""

    _sync_roots()
    normalized_agent_id = str(agent_id or "").strip()
    rows: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for team in team_service.list_teams_compact(include_archived=True).get("teams") or []:
        team_id = str(team.get("teamId") or "").strip()
        if not team_id:
            continue
        for base in _knowledge_bases_for_team(team_id):
            if not _can_access(team, base, normalized_agent_id, "read"):
                continue
            base_id = str(base.get("knowledgeBaseId") or "")
            artifacts = _source_artifacts_for_base(team_id, base_id)
            proposals = [
                proposal
                for proposal in _read_jsonl(_proposals_path(team_id))
                if str(proposal.get("targetKnowledgeBaseId") or "") == base_id
            ]
            items = [
                item
                for item in _read_jsonl(_items_path(team_id))
                if str(item.get("knowledgeBaseId") or "") == base_id
            ]
            suggestions = [
                suggestion
                for suggestion in _read_jsonl(_rating_suggestions_path(team_id))
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
                "teamId": team_id,
                "teamName": str(team.get("name") or ""),
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
    _record_event(
        "knowledge.operations.health.viewed",
        "",
        "",
        actor_agent_id=normalized_agent_id,
        fields={"knowledgeBaseCount": summary["knowledgeBaseCount"], "findingCount": summary["findingCount"]},
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": normalized_agent_id,
        "knowledgeBases": rows,
        "findings": findings,
        "summary": summary,
        "updatedAt": utc_now_iso(),
    }


def get_knowledge_governance_plan(*, agent_id: str = "", limit: int = 12) -> dict[str, Any]:
    """Return a read-only governance plan derived from health and steward workbench state."""

    normalized_agent_id = str(agent_id or "").strip()
    bounded_limit = max(1, min(50, int(limit or 12)))
    workbench = get_knowledge_steward_workbench(agent_id=normalized_agent_id, limit=bounded_limit)
    health = get_knowledge_operations_health(agent_id=normalized_agent_id)
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
    _record_event(
        "knowledge.governance.plan.viewed",
        "",
        "",
        actor_agent_id=normalized_agent_id,
        fields={"actionCount": len(actions), "healthFindingCount": payload["summary"]["healthFindingCount"]},
    )
    return payload


def knowledge_permission_audit(*, agent_id: str = "") -> dict[str, Any]:
    _sync_roots()
    normalized_agent_id = str(agent_id or "").strip()
    try:
        from core.web.services import agent_directory_service

        memory_policy = agent_directory_service.resolve_memory_policy_for_agent(normalized_agent_id) if normalized_agent_id else {}
        tool_policy = agent_directory_service.resolve_tool_policy_for_agent(normalized_agent_id) if normalized_agent_id else {}
    except Exception:
        memory_policy = {}
        tool_policy = {}
    tool_allowed = {str(item or "").strip() for item in tool_policy.get("allowedTools") or [] if str(item or "").strip()}
    tool_blocked = {str(item or "").strip() for item in tool_policy.get("blockedTools") or [] if str(item or "").strip()}
    read_policy = set(_unique_strings(memory_policy.get("readKnowledgeBaseIds") or []))
    propose_policy = set(_unique_strings(memory_policy.get("proposeKnowledgeBaseIds") or []))
    review_policy = set(_unique_strings(memory_policy.get("reviewKnowledgeBaseIds") or []))
    rate_policy = set(_unique_strings(memory_policy.get("rateKnowledgeBaseIds") or []))
    rows: list[dict[str, Any]] = []
    for team in team_service.list_teams_compact(include_archived=True).get("teams") or []:
        team_id = str(team.get("teamId") or "").strip()
        role = _member_role(team, normalized_agent_id) if normalized_agent_id else ""
        for base in _knowledge_bases_for_team(team_id):
            base_id = str(base.get("knowledgeBaseId") or "")
            rows.append(
                {
                    "teamId": team_id,
                    "teamName": str(team.get("name") or ""),
                    "knowledgeBaseId": base_id,
                    "knowledgeBaseName": str(base.get("name") or ""),
                    "teamRole": role,
                    "permissions": {
                        "read": _permission_explain(team, base, normalized_agent_id, "read", read_policy),
                        "propose": _permission_explain(team, base, normalized_agent_id, "propose", propose_policy),
                        "review": _permission_explain(team, base, normalized_agent_id, "review", review_policy),
                        "rate": _permission_explain(team, base, normalized_agent_id, "rate", rate_policy),
                    },
                }
            )
    tools = {
        name: {
            "toolName": name,
            "visible": name in tool_allowed and name not in tool_blocked,
            "allowedByToolPolicy": name in tool_allowed,
            "blockedByToolPolicy": name in tool_blocked,
            "reason": "visible" if name in tool_allowed and name not in tool_blocked else "tool_policy_blocked",
        }
        for name in ("knowledge_query_tool", "knowledge_proposal_tool", "knowledge_rating_suggestion_tool")
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

    overview = list_knowledge_overview()
    return {
        "knowledgeBaseCount": int((overview.get("summary") or {}).get("knowledgeBaseCount") or 0),
        "pendingProposalCount": int((overview.get("summary") or {}).get("pendingProposalCount") or 0),
        "itemCount": int((overview.get("summary") or {}).get("itemCount") or 0),
        "sourceArtifactCount": int((overview.get("summary") or {}).get("sourceArtifactCount") or 0),
        "updatedAt": str(overview.get("updatedAt") or ""),
    }


def _require_base_with_team(knowledge_base_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized_id = _safe_token(knowledge_base_id, default="", max_length=128)
    if not normalized_id:
        raise TeamKnowledgeError("Knowledge base id is required.")
    _sync_roots()
    for team in team_service.list_teams_compact(include_archived=True).get("teams") or []:
        team_id = str(team.get("teamId") or "").strip()
        if not team_id:
            continue
        base = _find_knowledge_base(team_id, normalized_id)
        if base:
            return team_service.get_team(team_id), base
    raise TeamKnowledgeNotFoundError("Knowledge base not found.")


def _require_team(team_id: str) -> dict[str, Any]:
    _sync_roots()
    try:
        return team_service.get_team(team_id)
    except team_service.TeamNotFoundError as exc:
        raise TeamKnowledgeNotFoundError("Team not found.") from exc
    except team_service.TeamServiceError as exc:
        raise TeamKnowledgeError(str(exc)) from exc


def _knowledge_base_to_api(base: dict[str, Any], team: dict[str, Any]) -> dict[str, Any]:
    return {
        "knowledgeBaseId": str(base.get("knowledgeBaseId") or "").strip(),
        "teamId": str(base.get("teamId") or team.get("teamId") or "").strip(),
        "teamName": str(team.get("name") or "").strip(),
        "name": str(base.get("name") or "").strip(),
        "description": str(base.get("description") or "").strip(),
        "status": str(base.get("status") or "active").strip(),
        "acl": _normalize_acl(base.get("acl") if isinstance(base.get("acl"), dict) else {}),
        "createdAt": str(base.get("createdAt") or "").strip(),
        "updatedAt": str(base.get("updatedAt") or "").strip(),
    }


def _knowledge_base_stats(team_id: str, knowledge_base_id: str) -> dict[str, int]:
    proposals = [
        item
        for item in _read_jsonl(_proposals_path(team_id))
        if str(item.get("targetKnowledgeBaseId") or "") == knowledge_base_id
    ]
    return {
        "sourceArtifactCount": len(_source_artifacts_for_base(team_id, knowledge_base_id)),
        "pendingProposalCount": sum(1 for item in proposals if str(item.get("status") or "") == "pending"),
        "proposalCount": len(proposals),
        "itemCount": sum(
            1
            for item in _read_jsonl(_items_path(team_id))
            if str(item.get("knowledgeBaseId") or "") == knowledge_base_id
        ),
        "batchCount": sum(
            1
            for item in _read_jsonl(_batches_path(team_id))
            if str(item.get("knowledgeBaseId") or "") == knowledge_base_id
        ),
    }


def _pending_proposals_for_base(team_id: str, knowledge_base_id: str) -> list[dict[str, Any]]:
    proposals = [
        item
        for item in _read_jsonl(_proposals_path(team_id))
        if str(item.get("targetKnowledgeBaseId") or "") == knowledge_base_id and str(item.get("status") or "") == "pending"
    ]
    proposals.sort(key=lambda item: str(item.get("createdAt") or ""), reverse=True)
    return proposals[:12]


def _permissions_for_actor(team: dict[str, Any], base: dict[str, Any], agent_id: str) -> dict[str, bool]:
    return {
        "canRead": _can_access(team, base, agent_id, "read"),
        "canPropose": _can_access(team, base, agent_id, "propose"),
        "canReview": _can_access(team, base, agent_id, "review"),
        "canRate": _can_access(team, base, agent_id, "rate"),
    }


def _require_permission(team: dict[str, Any], base: dict[str, Any], agent_id: str, action: str) -> None:
    if not _can_access(team, base, agent_id, action):
        raise TeamKnowledgePermissionError(f"Agent is not allowed to {action} this knowledge base.")


def _can_access(team: dict[str, Any], base: dict[str, Any], agent_id: str, action: str) -> bool:
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        return True
    role = _member_role(team, normalized_agent_id)
    acl = _normalize_acl(base.get("acl") if isinstance(base.get("acl"), dict) else {})
    grants = acl.get("grants") if isinstance(acl.get("grants"), dict) else {}
    agent_grants = _unique_strings((grants.get(action) or []) + (grants.get("*") or [])) if isinstance(grants, dict) else []
    if normalized_agent_id in agent_grants:
        return True
    if action == "read":
        return bool(role)
    if action == "propose":
        return bool(role)
    if action == "review":
        return role in REVIEW_ROLES
    if action == "rate":
        return role in REVIEW_ROLES
    return False


def _permission_explain(
    team: dict[str, Any],
    base: dict[str, Any],
    agent_id: str,
    action: str,
    policy_ids: set[str],
) -> dict[str, Any]:
    base_id = str(base.get("knowledgeBaseId") or "")
    team_allowed = _can_access(team, base, agent_id, action)
    policy_allowed = not policy_ids or base_id in policy_ids
    allowed = team_allowed and policy_allowed
    reason = "allowed"
    if not team_allowed:
        reason = "team_acl_blocked"
    elif not policy_allowed:
        reason = "memory_policy_blocked"
    return {
        "allowed": allowed,
        "reason": reason,
        "teamAclAllowed": team_allowed,
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


def _knowledge_bases_for_team(team_id: str) -> list[dict[str, Any]]:
    state = _load_bases_state(team_id)
    bases = [item for item in state.get("knowledgeBases") or [] if isinstance(item, dict)]
    return [_repair_base(team_id, item) for item in bases]


def _find_knowledge_base(team_id: str, knowledge_base_id: str) -> dict[str, Any] | None:
    for base in _knowledge_bases_for_team(team_id):
        if str(base.get("knowledgeBaseId") or "").strip() == knowledge_base_id:
            return base
    return None


def _source_artifacts_for_base(team_id: str, knowledge_base_id: str) -> list[dict[str, Any]]:
    return [
        item
        for item in _read_jsonl(_source_artifacts_path(team_id))
        if str(item.get("knowledgeBaseId") or "") == knowledge_base_id
    ]


def _require_item(team_id: str, knowledge_base_id: str, knowledge_item_id: str) -> dict[str, Any]:
    item = _find_by_id(_read_jsonl(_items_path(team_id)), "knowledgeItemId", knowledge_item_id)
    if not item or str(item.get("knowledgeBaseId") or "") != knowledge_base_id:
        raise TeamKnowledgeNotFoundError("Knowledge item not found.")
    return item


def _require_proposal(team_id: str, knowledge_base_id: str, proposal_id: str) -> dict[str, Any]:
    proposal = _find_by_id(_read_jsonl(_proposals_path(team_id)), "proposalId", proposal_id)
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
    team: dict[str, Any],
    artifacts_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    source_artifacts = [
        artifacts_by_id[source_id]
        for source_id in [str(value or "") for value in list(item.get("sourceArtifactIds") or [])]
        if source_id in artifacts_by_id
    ]
    return {
        "knowledgeItemId": str(item.get("knowledgeItemId") or ""),
        "knowledgeBaseId": str(base.get("knowledgeBaseId") or ""),
        "knowledgeBaseName": str(base.get("name") or ""),
        "teamId": str(team.get("teamId") or ""),
        "teamName": str(team.get("name") or ""),
        "batchId": str(item.get("batchId") or ""),
        "sourceArtifactIds": [str(value) for value in list(item.get("sourceArtifactIds") or [])[:12] if str(value or "").strip()],
        "sourceTypes": sorted({str(source.get("sourceType") or "") for source in source_artifacts if str(source.get("sourceType") or "")}),
        "sourceSummaries": [
            {
                "sourceArtifactId": str(source.get("sourceArtifactId") or ""),
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
    team: dict[str, Any],
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
    return {
        "taskId": f"ktask:{base.get('knowledgeBaseId')}:{task_type}:{target_id}",
        "taskType": task_type,
        "status": status,
        "priority": priority if priority in REVIEW_PRIORITIES else "normal",
        "teamId": str(team.get("teamId") or ""),
        "teamName": str(team.get("name") or ""),
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
    }.get(str(action or "").strip(), "knowledge_query_tool")


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
    team: dict[str, Any],
    base: dict[str, Any],
    proposal: dict[str, Any],
    reviewer_id: str,
    now: str,
) -> dict[str, Any]:
    return {
        "batchId": _new_event_id("kbatch"),
        "teamId": team["teamId"],
        "knowledgeBaseId": base["knowledgeBaseId"],
        "proposalIds": [proposal["proposalId"]],
        "sourceArtifactIds": list(proposal.get("sourceArtifactIds") or []),
        "reviewedByAgentId": reviewer_id,
        "appliedAt": now,
        "status": "applied",
    }


def _item_from_proposal(
    team: dict[str, Any],
    base: dict[str, Any],
    proposal: dict[str, Any],
    batch: dict[str, Any],
    reviewer_id: str,
    now: str,
) -> dict[str, Any]:
    return {
        "knowledgeItemId": _new_event_id("kitem"),
        "teamId": team["teamId"],
        "knowledgeBaseId": base["knowledgeBaseId"],
        "batchId": batch["batchId"],
        "sourceArtifactIds": list(proposal.get("sourceArtifactIds") or []),
        "title": proposal.get("title") or "",
        "summary": proposal.get("summary") or "",
        "content": proposal.get("content") or "",
        "tags": list(proposal.get("tags") or []),
        "importanceLevel": "medium",
        "confidence": 0.7,
        "stability": "evolving",
        "scope": "team",
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


def _repair_base(team_id: str, base: dict[str, Any]) -> dict[str, Any]:
    now = utc_now_iso()
    return {
        "knowledgeBaseId": _safe_token(base.get("knowledgeBaseId"), default=_new_event_id("kb"), max_length=128),
        "teamId": _safe_token(base.get("teamId"), default=team_id, max_length=96),
        "name": trim_lines(str(base.get("name") or "Team Knowledge"), max_lines=1).strip(),
        "description": trim_lines(str(base.get("description") or ""), max_lines=6).strip(),
        "status": str(base.get("status") or "active").strip() or "active",
        "acl": _normalize_acl(base.get("acl")),
        "createdAt": str(base.get("createdAt") or now),
        "updatedAt": str(base.get("updatedAt") or base.get("createdAt") or now),
    }


def _load_bases_state(team_id: str) -> dict[str, Any]:
    path = _knowledge_bases_path(team_id)
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


def _save_bases_state(team_id: str, state: dict[str, Any]) -> None:
    _write_json(_knowledge_bases_path(team_id), state)


def _append_audit(team_id: str, action: str, payload: dict[str, Any], *, actor_agent_id: str = "") -> None:
    _append_jsonl(
        _audit_path(team_id),
        {
            "auditId": _new_event_id("kaudit"),
            "action": action,
            "actorAgentId": str(actor_agent_id or "").strip(),
            "createdAt": utc_now_iso(),
            "payload": {
                "teamId": payload.get("teamId"),
                "knowledgeBaseId": payload.get("knowledgeBaseId") or payload.get("targetKnowledgeBaseId"),
                "sourceArtifactId": payload.get("sourceArtifactId"),
                "proposalId": payload.get("proposalId"),
                "batchId": payload.get("batchId"),
                "knowledgeItemId": payload.get("knowledgeItemId"),
                "status": payload.get("status"),
            },
        },
    )


def _record_event(
    event_code: str,
    team_id: str,
    knowledge_base_id: str,
    *,
    actor_agent_id: str = "",
    fields: dict[str, Any] | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "team_knowledge_service",
            "knowledge",
            event_code,
            message=event_code,
            outcome="observed",
            fields={
                "teamId": team_id,
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


def _knowledge_root(team_id: str) -> Path:
    return _project_root() / "workspace" / "teams" / _safe_token(team_id, default="team", max_length=96) / "knowledge"


def _knowledge_bases_path(team_id: str) -> Path:
    return _knowledge_root(team_id) / "knowledge_bases.json"


def _source_artifacts_path(team_id: str) -> Path:
    return _knowledge_root(team_id) / "source_artifacts.jsonl"


def _proposals_path(team_id: str) -> Path:
    return _knowledge_root(team_id) / "refinement_proposals.jsonl"


def _batches_path(team_id: str) -> Path:
    return _knowledge_root(team_id) / "batches.jsonl"


def _items_path(team_id: str) -> Path:
    return _knowledge_root(team_id) / "items.jsonl"


def _audit_path(team_id: str) -> Path:
    return _knowledge_root(team_id) / "audit.jsonl"


def _rating_suggestions_path(team_id: str) -> Path:
    return _knowledge_root(team_id) / "rating_suggestions.jsonl"


def _project_root() -> Path:
    root = Path(PROJECT_ROOT).resolve()
    return root.parent if root.name.lower() == "workspace" else root


def _sync_roots() -> None:
    if team_service.PROJECT_ROOT != PROJECT_ROOT:
        team_service.PROJECT_ROOT = PROJECT_ROOT
    if chat_room_service.PROJECT_ROOT != PROJECT_ROOT:
        chat_room_service.PROJECT_ROOT = PROJECT_ROOT


def _safe_token(value: Any, *, default: str, max_length: int) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    text = _SAFE_ID_FRAGMENT.sub("-", text).strip(".-_")
    return (text or default)[:max_length]


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
