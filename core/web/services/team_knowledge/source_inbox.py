"""Team knowledge owner inbox and central source promotion.

Claim scope: owner source governance, collect/list/review inbox, central
promotion/dedupe, central list, and direct-ingest after accept.
Late-binds ``team_knowledge_service`` for store, permissions, and remaining facade APIs.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from core.chat.chat_task_types import trim_lines


def _service():
    from core.web.services import team_knowledge_service

    return team_knowledge_service


def update_owner_source_governance(
    owner_type: str,
    owner_id: str,
    *,
    local_steward_agent_ids: list[str] | None = None,
    actor_agent_id: str = "",
) -> dict[str, Any]:
    """Configure owner-local source stewards for the owner inbox."""

    s = _service()
    owner = s._require_owner_context(owner_type, owner_id)
    actor_id = str(actor_agent_id or "").strip()
    if not s._can_configure_owner_source_governance(owner, actor_id):
        raise s.TeamKnowledgePermissionError("Agent is not allowed to configure this source governance scope.")
    now = s.utc_now_iso()
    payload = {
        "schemaVersion": s.SCHEMA_VERSION,
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "localStewardAgentIds": s._unique_strings(local_steward_agent_ids or []),
        "updatedByAgentId": actor_id,
        "updatedAt": now,
    }
    with s._LOCK:
        s._write_json(s._owner_source_governance_path(owner), payload)
        s._append_audit(owner, "knowledge.source_governance.updated", payload, actor_agent_id=actor_id)
    s._record_event(
        "knowledge.source_governance.updated",
        owner,
        "",
        actor_agent_id=actor_id,
        fields={"localStewardCount": len(payload["localStewardAgentIds"])},
    )
    return payload


def ensure_owner_source_review_grant(owner_type: str, owner_id: str, agent_id: str) -> dict[str, Any]:
    """Idempotently grant one agent owner-source review permission for an owner.

    Server-authoritative ensure used by the trusted knowledge-ingestion gate
    (source collection writeback auto-ingestion): it deliberately skips the
    ``_can_configure_owner_source_governance`` check, mirroring
    ``ensure_knowledge_base_review_grant`` on the knowledge-base side. This only
    adds the named agent to this owner's ``localStewardAgentIds`` (preserving
    existing entries, deduplicated); it never widens REVIEW_ROLES or any other
    owner's governance scope.
    """
    s = _service()
    owner = s._require_owner_context(owner_type, owner_id)
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise s.TeamKnowledgePermissionError("Agent identity is required to grant owner source review.")
    existing = s._source_governance_for_owner(owner)
    steward_ids = list(existing.get("localStewardAgentIds") or [])
    if normalized_agent_id in steward_ids:
        return {
            "schemaVersion": existing.get("schemaVersion") or s.SCHEMA_VERSION,
            "ownerType": owner["ownerType"],
            "ownerId": owner["ownerId"],
            "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
            "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
            "localStewardAgentIds": steward_ids,
            "updatedByAgentId": "",
            "updatedAt": str(existing.get("updatedAt") or ""),
        }
    steward_ids.append(normalized_agent_id)
    now = s.utc_now_iso()
    payload = {
        "schemaVersion": s.SCHEMA_VERSION,
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "localStewardAgentIds": s._unique_strings(steward_ids),
        "updatedByAgentId": normalized_agent_id,
        "updatedAt": now,
    }
    with s._LOCK:
        s._write_json(s._owner_source_governance_path(owner), payload)
        s._append_audit(owner, "knowledge.source_governance.updated", payload, actor_agent_id=normalized_agent_id)
    s._record_event(
        "knowledge.source_governance.updated",
        owner,
        "",
        actor_agent_id=normalized_agent_id,
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
    local_file_paths: list[Any] | None = None,
) -> dict[str, Any]:
    """Stage raw source material inside the owning Team/Agent workspace."""

    s = _service()
    owner = s._require_owner_context(owner_type, owner_id)
    actor_id = str(actor_agent_id or captured_by or "").strip()
    if not s._can_collect_owner_source(owner, actor_id):
        raise s.TeamKnowledgePermissionError("Agent is not allowed to collect sources for this owner.")
    normalized_type = str(source_type or "").strip()
    if normalized_type not in s.SOURCE_TYPES:
        raise s.TeamKnowledgeError(f"Unsupported source type: {source_type}")
    normalized_ref = s._bounded_dict(source_ref if isinstance(source_ref, dict) else {})
    if normalized_type == "team_chat_refinement":
        if str(owner.get("ownerType") or "") != "team":
            raise s.TeamKnowledgeError("team_chat_refinement sources require a Team owner.")
        s._validate_team_chat_source(owner["team"], normalized_ref)
    now = s.utc_now_iso()
    inbox_source_id = s._new_event_id("inboxsrc")
    safe_title = trim_lines(title or normalized_type, max_lines=1).strip()
    safe_summary = trim_lines(summary or "", max_lines=16).strip()
    safe_content = str(original_content or "")
    original_path = s._write_owner_inbox_source_file(
        owner,
        inbox_source_id,
        original_filename=original_filename,
        original_content=safe_content,
        source_ref=normalized_ref,
        title=safe_title,
        summary=safe_summary,
    )
    local_copies = s._stage_local_source_copies(
        owner,
        inbox_source_id,
        local_file_paths or [],
    )
    if local_copies:
        normalized_ref["localCopies"] = local_copies
    normalized_hash = trim_lines(
        source_hash or s._source_hash_with_content(normalized_ref, safe_title, safe_summary, safe_content),
        max_lines=1,
    ).strip()
    source = {
        "schemaVersion": s.SCHEMA_VERSION,
        "inboxSourceId": inbox_source_id,
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "sourceType": normalized_type,
        "sourceRef": normalized_ref,
        "sourceCreatedAt": trim_lines(source_created_at or "", max_lines=1).strip(),
        "capturedBy": trim_lines(captured_by or actor_id or "user", max_lines=1).strip(),
        "capturedAt": now,
        "sourceHash": normalized_hash,
        "evidenceRange": s._bounded_dict(evidence_range if isinstance(evidence_range, dict) else {}),
        "title": safe_title,
        "summary": safe_summary,
        "originalFilename": s._safe_source_filename(original_filename, default=f"{normalized_type}.txt"),
        "originalPath": s._project_relative_path(original_path),
        "localCopies": local_copies,
        "status": "pending",
        "curationStatus": "owner_inbox",
        "centralSourceId": "",
        "dedupeStatus": "",
        "reviewedAt": "",
        "reviewedByAgentId": "",
        "resolutionNote": "",
        "updatedAt": now,
    }
    with s._LOCK:
        sources = s._read_jsonl(s._owner_source_index_path(owner))
        sources.append(source)
        s._write_jsonl(s._owner_source_index_path(owner), sources)
        s._rewrite_owner_source_review_queue_locked(owner, sources)
        s._append_audit(owner, "knowledge.source_inbox.collected", source, actor_agent_id=actor_id)
    s._record_event(
        "knowledge.source_inbox.collected",
        owner,
        "",
        actor_agent_id=actor_id,
        fields={
            "inboxSourceId": inbox_source_id,
            "sourceType": normalized_type,
            "localCopyCount": len(local_copies),
        },
    )
    return source


def list_owner_source_inbox(
    owner_type: str,
    owner_id: str,
    *,
    agent_id: str = "",
    status: str = "",
) -> dict[str, Any]:
    s = _service()
    owner = s._require_owner_context(owner_type, owner_id)
    actor_id = str(agent_id or "").strip()
    if not s._can_read_owner_source_inbox(owner, actor_id):
        raise s.TeamKnowledgePermissionError("Agent is not allowed to read this owner source inbox.")
    normalized_status = str(status or "").strip().lower()
    if normalized_status and normalized_status not in s.SOURCE_INBOX_STATUSES:
        raise s.TeamKnowledgeError(f"Unsupported source inbox status: {status}")
    sources = s._read_jsonl(s._owner_source_index_path(owner))
    if normalized_status:
        sources = [item for item in sources if str(item.get("status") or "") == normalized_status]
    sources.sort(key=lambda item: str(item.get("updatedAt") or item.get("capturedAt") or ""), reverse=True)
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "actorAgentId": actor_id,
        "summary": s._source_inbox_summary(sources),
        "sources": sources,
        "updatedAt": s.utc_now_iso(),
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

    s = _service()
    owner = s._require_owner_context(owner_type, owner_id)
    reviewer_id = str(reviewed_by_agent_id or "").strip()
    if not s._can_review_owner_source(owner, reviewer_id):
        raise s.TeamKnowledgePermissionError("Agent is not allowed to review this owner source inbox.")
    normalized_decision = s._normalize_source_review_decision(decision)
    wants_direct_ingest = bool(
        ingest_on_accept
        or str(knowledge_base_id or "").strip()
        or str(knowledge_content or "").strip()
        or str(knowledge_title or "").strip()
    )
    if wants_direct_ingest and normalized_decision != "accepted":
        raise s.TeamKnowledgeError("Direct ingestion is only supported for accepted source reviews.")
    now = s.utc_now_iso()
    direct_ingestion: dict[str, Any] | None = None
    with s._LOCK:
        sources = s._read_jsonl(s._owner_source_index_path(owner))
        source = s._find_by_id(sources, "inboxSourceId", inbox_source_id)
        if not source:
            raise s.TeamKnowledgeNotFoundError("Inbox source not found.")
        current_status = str(source.get("status") or "")
        if current_status not in {"pending", "needs_more_context"}:
            raise s.TeamKnowledgeError("Only pending or needs_more_context inbox sources can be reviewed.")
        central_source: dict[str, Any] | None = None
        promotion: dict[str, Any] | None = None
        if normalized_decision == "accepted":
            central_source, promotion = s._promote_owner_source_to_central_locked(
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
                direct_ingestion = s._direct_ingest_accepted_source_locked(
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
            central_source = s._resolve_duplicate_central_source_locked(source, duplicate_of=duplicate_of)
            promotion = s._append_owner_ref_for_central_source_locked(
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
            s._append_jsonl(s._owner_source_rejected_path(owner), {**source, "reviewedAt": now, "reviewedByAgentId": reviewer_id})
        else:
            source["status"] = "needs_more_context"
            source["curationStatus"] = "owner_inbox"
            source["dedupeStatus"] = ""
        source["reviewedAt"] = now
        source["reviewedByAgentId"] = reviewer_id
        source["resolutionNote"] = trim_lines(resolution_note or "", max_lines=6).strip()
        source["updatedAt"] = now
        s._write_jsonl(s._owner_source_index_path(owner), sources)
        s._rewrite_owner_source_review_queue_locked(owner, sources)
        s._append_audit(owner, "knowledge.source_inbox.reviewed", source, actor_agent_id=reviewer_id)
    s._record_event(
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
        "schemaVersion": s.SCHEMA_VERSION,
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "source": source,
        "centralSource": central_source,
        "promotion": promotion,
        "directIngestion": direct_ingestion,
        "updatedAt": s.utc_now_iso(),
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
    s = _service()
    owner, base = s._require_base_with_owner(knowledge_base_id)
    s._require_permission(owner, base, actor_agent_id, "propose")
    central_source, owner_ref = s._require_central_source_for_owner(owner, central_source_id, actor_agent_id=actor_agent_id)
    source_ref = s._bounded_dict(central_source.get("sourceRef") if isinstance(central_source.get("sourceRef"), dict) else {})
    source_ref.update({
        "centralSourceId": central_source["centralSourceId"],
        "centralPath": central_source.get("centralPath") or "",
        "sourceHash": central_source.get("sourceHash") or "",
        "originalOwnerType": owner_ref.get("ownerType") or central_source.get("originOwnerType") or "",
        "originalOwnerId": owner_ref.get("ownerId") or central_source.get("originOwnerId") or "",
        "originalPath": owner_ref.get("originalPath") or central_source.get("originOriginalPath") or "",
    })
    local_copies = [
        item
        for item in list(central_source.get("localCopies") or source_ref.get("localCopies") or [])
        if isinstance(item, dict)
    ][: s.MAX_LOCAL_SOURCE_COPIES]
    if local_copies:
        source_ref["localCopies"] = local_copies
    return s.create_source_artifact(
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

    s = _service()
    normalized_actor = str(agent_id or "").strip()
    normalized_owner_type = s._normalize_owner_type(owner_type)
    normalized_owner_id = str(owner_id or "").strip()
    registry = s._read_jsonl(s._central_source_registry_path())
    owner_refs = s._read_jsonl(s._central_owner_refs_path())
    visible_owner_refs = [
        ref
        for ref in owner_refs
        if s._central_owner_ref_visible(ref, normalized_actor, internal=internal)
        and (not normalized_owner_type or str(ref.get("ownerType") or "") == normalized_owner_type)
        and (not normalized_owner_id or str(ref.get("ownerId") or "") == normalized_owner_id)
    ]
    visible_source_ids = {str(ref.get("centralSourceId") or "") for ref in visible_owner_refs if str(ref.get("centralSourceId") or "").strip()}
    if internal or s._is_global_knowledge_steward(normalized_actor):
        visible_source_ids.update(str(source.get("centralSourceId") or "") for source in registry if str(source.get("centralSourceId") or ""))
    sources = [source for source in registry if str(source.get("centralSourceId") or "") in visible_source_ids]
    sources.sort(key=lambda item: str(item.get("updatedAt") or item.get("acceptedAt") or ""), reverse=True)
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "agentId": normalized_actor,
        "ownerType": normalized_owner_type,
        "ownerId": normalized_owner_id,
        "summary": {"centralSourceCount": len(sources), "ownerRefCount": len(visible_owner_refs)},
        "centralSources": sources,
        "ownerRefs": visible_owner_refs,
        "updatedAt": s.utc_now_iso(),
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
    s = _service()
    owner = s._coerce_owner_context(owner_value)
    target_owner, base = s._require_base_with_owner(knowledge_base_id)
    target_owner = s._coerce_owner_context(target_owner)
    if target_owner["ownerType"] != owner["ownerType"] or target_owner["ownerId"] != owner["ownerId"]:
        raise s.TeamKnowledgePermissionError("Direct ingestion target knowledge base must belong to the reviewed owner.")
    if not s._can_review_owner_source(owner, reviewer_id):
        raise s.TeamKnowledgePermissionError("Agent is not allowed to direct-ingest this owner source.")
    normalized_title = trim_lines(knowledge_title or source.get("title") or central_source.get("title") or "", max_lines=1).strip()
    normalized_summary = trim_lines(
        knowledge_summary or source.get("summary") or central_source.get("summary") or "",
        max_lines=6,
    ).strip()
    normalized_content = trim_lines(knowledge_content or "", max_lines=120).strip()
    if not normalized_title:
        raise s.TeamKnowledgeError("Direct ingestion requires knowledgeTitle or source title.")
    if not normalized_content:
        raise s.TeamKnowledgeError("Direct ingestion requires knowledgeContent.")

    scoped_base_id = s._owner_scoped_knowledge_base_id(owner, base["knowledgeBaseId"])
    source_artifact = s.create_source_artifact_from_central_source(
        scoped_base_id,
        str(central_source.get("centralSourceId") or ""),
        actor_agent_id=reviewer_id,
        title=normalized_title,
        summary=normalized_summary,
    )
    batch = {
        "batchId": s._new_event_id("kbatch"),
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
        "knowledgeItemId": s._new_event_id("kitem"),
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
        "tags": s._unique_strings(tags or [])[:24],
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
    s._append_jsonl(s._batches_path_for_owner(owner), batch)
    s._append_jsonl(s._items_path_for_owner(owner), item)
    s._append_audit(owner, "knowledge.item.direct_ingested", item, actor_agent_id=reviewer_id)
    s._record_event(
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
        "schemaVersion": s.SCHEMA_VERSION,
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


def _normalize_source_review_decision(decision: str) -> str:
    s = _service()
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
    if normalized not in s.SOURCE_REVIEW_DECISIONS:
        raise s.TeamKnowledgeError("Source review decision must be accepted, rejected, duplicate, or needs_more_context.")
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
    s = _service()
    owner = s._coerce_owner_context(owner_value)
    default_filename = "source.txt" if str(original_content or "") else "source.json"
    filename = s._safe_source_filename(original_filename, default=default_filename)
    source_dir = s._owner_inbox_source_dir(owner, inbox_source_id)
    path = source_dir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    write_path = s._extended_fs_path(path)
    if str(original_content or ""):
        write_path.write_text(str(original_content), encoding="utf-8")
    else:
        write_path.write_text(
            json.dumps(
                {
                    "schemaVersion": s.SCHEMA_VERSION,
                    "sourceRef": s._bounded_dict(source_ref),
                    "title": title,
                    "summary": summary,
                    "capturedAt": s.utc_now_iso(),
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
    s = _service()
    owner = s._coerce_owner_context(owner_value)
    source_hash = str(source.get("sourceHash") or "").strip()
    if not source_hash:
        raise s.TeamKnowledgeError("Inbox source requires sourceHash before central promotion.")
    s._assert_central_source_write_allowed()
    existing = s._find_central_source_by_hash_locked(source_hash)
    dedupe_status = "reused" if existing else "created"
    if existing:
        central_source = existing
    else:
        now = s.utc_now_iso()
        central_source_id = s._new_event_id("csrc")
        central_path = s._copy_or_write_central_source_file(owner, source, central_source_id)
        source_dir = central_path.parent
        local_copies = s._relocate_local_copies_to_central(
            list(source.get("localCopies") or []),
            source_dir,
        )
        source_ref = s._bounded_dict(source.get("sourceRef") if isinstance(source.get("sourceRef"), dict) else {})
        if local_copies:
            source_ref["localCopies"] = local_copies
        central_source = {
            "schemaVersion": s.SCHEMA_VERSION,
            "centralSourceId": central_source_id,
            "status": "active",
            "sourceHash": source_hash,
            "sourceType": str(source.get("sourceType") or ""),
            "sourceRef": source_ref,
            "sourceCreatedAt": str(source.get("sourceCreatedAt") or ""),
            "title": trim_lines(str(source.get("title") or ""), max_lines=1).strip(),
            "summary": trim_lines(str(source.get("summary") or ""), max_lines=16).strip(),
            "centralPath": s._project_relative_path(central_path),
            "localCopies": local_copies,
            "originOwnerType": owner["ownerType"],
            "originOwnerId": owner["ownerId"],
            "originInboxSourceId": str(source.get("inboxSourceId") or ""),
            "originOriginalPath": str(source.get("originalPath") or ""),
            "acceptedByAgentId": reviewer_id,
            "acceptedAt": now,
            "updatedAt": now,
        }
        registry = s._read_jsonl(s._central_source_registry_path())
        registry.append(central_source)
        s._write_jsonl(s._central_source_registry_path(), registry)
    promotion = s._append_owner_ref_for_central_source_locked(
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
    s = _service()
    normalized_duplicate_of = str(duplicate_of or "").strip()
    central_source = s._find_central_source_by_id_locked(normalized_duplicate_of) if normalized_duplicate_of else {}
    if not central_source:
        central_source = s._find_central_source_by_hash_locked(str(source.get("sourceHash") or "").strip())
    if not central_source:
        raise s.TeamKnowledgeError("Duplicate source review requires duplicateOf or an existing central source with the same sourceHash.")
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
    s = _service()
    s._assert_central_source_write_allowed()
    owner = s._coerce_owner_context(owner_value)
    central_source_id = str(central_source.get("centralSourceId") or "").strip()
    inbox_source_id = str(source.get("inboxSourceId") or "").strip()
    now = s.utc_now_iso()
    refs = s._read_jsonl(s._central_owner_refs_path())
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
    owner_ref_id = s._new_event_id("srcown")
    promotion_id = s._new_event_id("srcprom")
    ref = {
        "schemaVersion": s.SCHEMA_VERSION,
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
    s._write_jsonl(s._central_owner_refs_path(), refs)
    promotion = {
        "schemaVersion": s.SCHEMA_VERSION,
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
    s._append_jsonl(s._central_promotion_log_path(), promotion)
    return promotion


def _copy_or_write_central_source_file(owner_value: Any, source: dict[str, Any], central_source_id: str) -> Path:
    s = _service()
    s._assert_central_source_write_allowed()
    owner = s._coerce_owner_context(owner_value)
    accepted_at = str(source.get("reviewedAt") or source.get("capturedAt") or s.utc_now_iso())
    year = s._safe_token(accepted_at[:4], default="undated", max_length=16)
    source_dir = s._central_source_accepted_dir() / year / s._safe_token(central_source_id, default="source", max_length=128)
    source_dir.mkdir(parents=True, exist_ok=True)
    original_path = s._project_path_from_relative(str(source.get("originalPath") or ""))
    filename = s._safe_source_filename(str(source.get("originalFilename") or ""), default="source.txt")
    target_path = source_dir / filename
    copied_original = False
    if original_path and original_path.exists() and original_path.is_file():
        shutil.copy2(s._extended_fs_path(original_path), s._extended_fs_path(target_path))
        copied_original = True
        attachments_src = original_path.parent / "attachments"
        if attachments_src.is_dir():
            shutil.copytree(
                s._extended_fs_path(attachments_src),
                s._extended_fs_path(source_dir / "attachments"),
                dirs_exist_ok=True,
            )
    if not copied_original:
        target_path.write_text(
            json.dumps(
                {
                    "schemaVersion": s.SCHEMA_VERSION,
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
    s = _service()
    owner = s._coerce_owner_context(owner_value)
    central_source = s._find_central_source_by_id_locked(central_source_id)
    if not central_source:
        raise s.TeamKnowledgeNotFoundError("Central source not found.")
    if str(central_source.get("status") or "active") not in s.CENTRAL_SOURCE_STATUSES:
        raise s.TeamKnowledgeError("Central source status is invalid.")
    if str(central_source.get("status") or "active") != "active":
        raise s.TeamKnowledgePermissionError("Central source is not active.")
    refs = [
        ref
        for ref in s._read_jsonl(s._central_owner_refs_path())
        if str(ref.get("centralSourceId") or "") == str(central_source.get("centralSourceId") or "")
        and str(ref.get("ownerType") or "") == owner["ownerType"]
        and str(ref.get("ownerId") or "") == owner["ownerId"]
    ]
    if refs:
        return central_source, refs[0]
    if s._is_global_knowledge_steward(str(actor_agent_id or "").strip()):
        return central_source, {}
    raise s.TeamKnowledgePermissionError("Central source is not linked to this owner.")


def _central_owner_ref_visible(ref: dict[str, Any], agent_id: str, *, internal: bool = False) -> bool:
    s = _service()
    if internal:
        return True
    normalized_agent_id = str(agent_id or "").strip()
    if s._is_global_knowledge_steward(normalized_agent_id):
        return True
    owner = s._owner_context(str(ref.get("ownerType") or ""), str(ref.get("ownerId") or ""))
    return s._can_read_owner_source_inbox(owner, normalized_agent_id)


def _stage_local_source_copies(
    owner_value: Any,
    inbox_source_id: str,
    local_file_paths: list[Any],
) -> list[dict[str, Any]]:
    """Copy obtainable local files into the inbox source attachments directory."""

    s = _service()
    copies: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    attachments_dir = s._owner_inbox_source_dir(owner_value, inbox_source_id) / "attachments"
    for raw_item in list(local_file_paths or [])[: s.MAX_LOCAL_SOURCE_COPIES]:
        spec = raw_item if isinstance(raw_item, dict) else {"path": raw_item}
        resolved = s._resolve_copyable_local_file(spec.get("path") or spec.get("sourcePath") or spec.get("filePath"))
        if resolved is None:
            continue
        digest = s._sha256_local_file(resolved)
        if not digest or digest in seen_hashes:
            continue
        candidate_id = s._safe_token(spec.get("candidateId") or spec.get("sourceId") or "", default="", max_length=96)
        filename = s._safe_source_filename(resolved.name, default="source.bin")
        dest_name = f"{candidate_id}-{filename}" if candidate_id else filename
        dest_path = attachments_dir / dest_name
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s._extended_fs_path(resolved), s._extended_fs_path(dest_path))
        seen_hashes.add(digest)
        copies.append(
            {
                "candidateId": candidate_id,
                "title": trim_lines(str(spec.get("title") or resolved.name), max_lines=1).strip(),
                "filename": dest_name,
                "originalPath": s._project_relative_path(resolved),
                "inboxPath": s._project_relative_path(dest_path),
                "sha256": digest,
                "byteSize": int(resolved.stat().st_size),
                "kind": "local_file",
            }
        )
        if len(copies) >= s.MAX_LOCAL_SOURCE_COPIES:
            break
    return copies


def _relocate_local_copies_to_central(
    copies: list[Any],
    source_dir: Path,
) -> list[dict[str, Any]]:
    s = _service()
    relocated: list[dict[str, Any]] = []
    for item in list(copies or [])[: s.MAX_LOCAL_SOURCE_COPIES]:
        if not isinstance(item, dict):
            continue
        payload = dict(item)
        filename = str(item.get("filename") or "").strip()
        dest = source_dir / "attachments" / filename if filename else Path()
        if dest.exists() and dest.is_file():
            payload["centralPath"] = s._project_relative_path(dest)
        relocated.append(payload)
    return relocated


def _is_copyable_local_path_text(value: Any) -> bool:
    """Reject URLs and UNC/network paths before any filesystem probe."""

    text = str(value or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if lowered.startswith(("http://", "https://", "ftp://", "file://")):
        return False
    if text.startswith(("\\\\", "//")):
        return False
    return True


def _resolve_copyable_local_file(value: Any) -> Path | None:
    s = _service()
    text = str(value or "").strip()
    if not _is_copyable_local_path_text(text):
        return None
    candidate = Path(text)
    if not candidate.is_absolute():
        mapped = s._project_path_from_relative(text)
        candidate = mapped if mapped and str(mapped) else s._project_root() / text
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError):
        return None
    if not resolved.is_file():
        return None
    try:
        size = resolved.stat().st_size
    except OSError:
        return None
    if size <= 0 or size > s.MAX_LOCAL_SOURCE_COPY_BYTES:
        return None
    return resolved


def _sha256_local_file(path: Path) -> str:
    s = _service()
    digest = hashlib.sha256()
    try:
        with s._extended_fs_path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()
