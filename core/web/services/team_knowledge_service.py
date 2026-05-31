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

from . import chat_room_service, team_service
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
REVIEW_ROLES = {"owner", "lead", "steward", "coordinator"}
IMPORTANCE_LEVELS = {"low", "medium", "high", "critical"}
STABILITY_VALUES = {"temporary", "evolving", "stable", "deprecated"}
SCOPES = {"agent", "team", "project", "global"}
REVIEW_PRIORITIES = {"normal", "elevated", "urgent"}
_SAFE_ID_FRAGMENT = re.compile(r"[^A-Za-z0-9_.-]+")
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
            return team, base
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
        "canRate": _can_access(team, base, agent_id, "review"),
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
    return False


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
