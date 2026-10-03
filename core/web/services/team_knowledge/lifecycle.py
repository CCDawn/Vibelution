"""Governed revision lineage and source validity over the canonical owner store.

Content remains in items.jsonl; history is its immutable revision lineage.
Source withdrawal is owner-local and never rewrites a shared central snapshot.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _service():
    from core.web.services import team_knowledge_service

    return team_knowledge_service


def content_sha256(item: dict[str, Any]) -> str:
    return hashlib.sha256(str(item.get("content") or "").encode("utf-8")).hexdigest()


def _date(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError("timezone required")
        return result.astimezone(timezone.utc)
    except (TypeError, ValueError) as exc:
        raise _service().TeamKnowledgeError("Lifecycle timestamps must be ISO-8601 with a timezone.") from exc


def source_lifecycle_state(source: dict[str, Any], *, now: str) -> str:
    state = str(source.get("status") or "active")
    if state in {"withdrawn", "expired", "archived", "superseded"}:
        return state
    if state != "active":
        return "unavailable"
    expires = str(source.get("expiresAt") or "")
    if expires:
        try:
            if _date(expires) <= _date(now):
                return "expired"
        except _service().TeamKnowledgeError:
            return "unavailable"
    return "active"


def item_lifecycle_states(
    items: list[dict[str, Any]], artifacts: dict[str, dict[str, Any]], *, now: str,
    central_sources: dict[str, dict[str, Any]] | None = None,
) -> dict[str, str]:
    """Supersession remains true even if the newer version later loses validity."""
    superseded = {
        str(row.get("supersedesKnowledgeItemId") or "")
        for row in items if row.get("supersedesKnowledgeItemId")
    }
    result: dict[str, str] = {}
    for item in items:
        item_id = str(item.get("knowledgeItemId") or "")
        if item_id in superseded:
            result[item_id] = "superseded"
            continue
        state = str(item.get("status") or "active")
        if state != "active":
            result[item_id] = state
            continue
        for source_id in item.get("sourceArtifactIds") or []:
            source = artifacts.get(str(source_id))
            if source is None:
                state = "source_unavailable"
                break
            source_state = source_lifecycle_state(source, now=now)
            captured = (item.get("sourceLifecycleRevisions") or {}).get(str(source_id), 0)
            if source_state == "active" and int(captured) != int(source.get("lifecycleRevision") or 0):
                source_state = "revalidation_required"
            if source_state == "active" and central_sources is not None:
                central = central_sources.get(str(source.get("centralSourceId") or ""))
                source_state = source_lifecycle_state(central, now=now) if central else "unavailable"
            if source_state != "active":
                state = f"source_{source_state}"
                break
        result[item_id] = state
    return result


def lifecycle_states_for_base(owner: dict, base: dict, items: list[dict], artifacts: dict) -> dict[str, str]:
    s = _service()
    central = {str(row.get("centralSourceId") or ""): row for row in s._read_jsonl(s._central_source_registry_path())}
    base_items = [row for row in items if row.get("knowledgeBaseId") == base["knowledgeBaseId"]]
    return item_lifecycle_states(base_items, artifacts, central_sources=central, now=s.utc_now_iso())


def require_active_sources(owner: dict, base: dict, source_ids: list[str]) -> dict[str, int]:
    s = _service()
    artifacts = {row["sourceArtifactId"]: row for row in s._source_artifacts_for_base(owner, base["knowledgeBaseId"])}
    revisions = {source_id: int((artifacts.get(source_id) or {}).get("lifecycleRevision") or 0) for source_id in source_ids}
    state = lifecycle_states_for_base(owner, base, [{"knowledgeItemId": "candidate", "knowledgeBaseId": base["knowledgeBaseId"],
                                                   "sourceArtifactIds": source_ids, "sourceLifecycleRevisions": revisions}], artifacts)["candidate"]
    if state != "active":
        raise s.TeamKnowledgeError("Knowledge proposals require active governed sources.")
    return revisions


def prepare_revision_fields(
    owner: dict, base: dict, target_item_id: str, *, expected_content_sha256: str, reason: str,
) -> dict[str, Any]:
    s = _service()
    expected = str(expected_content_sha256 or "").lower().removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise s.TeamKnowledgeError("An expectedContentSha256 is required for a knowledge revision.")
    note = str(reason or "").strip()
    if not note or len(note) > 1000:
        raise s.TeamKnowledgeError("A revision reason of at most 1000 characters is required.")
    items = s._read_jsonl(s._items_path_for_owner(owner))
    target = s._find_by_id(items, "knowledgeItemId", str(target_item_id))
    if not target or target.get("knowledgeBaseId") != base["knowledgeBaseId"]:
        raise s.TeamKnowledgeNotFoundError("Knowledge item not found.")
    if any(row.get("supersedesKnowledgeItemId") == target_item_id for row in items):
        raise s.TeamKnowledgeIdempotencyConflictError("Knowledge revision target has changed; read the latest version.")
    if content_sha256(target) != expected:
        raise s.TeamKnowledgeIdempotencyConflictError("Knowledge content has changed; read it again before revising.")
    return {
        "supersedesKnowledgeItemId": target_item_id,
        "rootKnowledgeItemId": str(target.get("rootKnowledgeItemId") or target_item_id),
        "revision": int(target.get("revision") or 1) + 1,
        "expectedContentSha256": expected,
        "revisionReason": note,
    }


def validate_revision_review(owner: dict, base: dict, proposal: dict) -> None:
    parent = str(proposal.get("supersedesKnowledgeItemId") or "")
    if parent:
        current = prepare_revision_fields(
            owner, base, parent, expected_content_sha256=str(proposal.get("expectedContentSha256") or ""),
            reason=str(proposal.get("revisionReason") or ""),
        )
        if any(proposal.get(key) != value for key, value in current.items()):
            raise _service().TeamKnowledgeIdempotencyConflictError("Knowledge revision lineage has changed.")


def decorate_revision_item(item: dict, proposal: dict) -> dict:
    return {
        **item,
        "revision": int(proposal.get("revision") or 1),
        "rootKnowledgeItemId": str(proposal.get("rootKnowledgeItemId") or item["knowledgeItemId"]),
        "contentSha256": content_sha256(item),
        "sourceLifecycleRevisions": dict(proposal.get("sourceLifecycleRevisions") or {}),
        **({
            "supersedesKnowledgeItemId": proposal["supersedesKnowledgeItemId"],
            "revisionReason": proposal.get("revisionReason") or "",
        } if proposal.get("supersedesKnowledgeItemId") else {}),
    }


def set_knowledge_source_lifecycle(
    knowledge_base_id: str, source_artifact_id: str, *, status: str, reason: str,
    actor_agent_id: str, expires_at: str = "",
) -> dict[str, Any]:
    s = _service()
    owner, base = s._require_base_with_owner(knowledge_base_id)
    s._require_permission(owner, base, actor_agent_id, "review")
    state = str(status or "").strip()
    note = str(reason or "").strip()
    if state not in {"active", "withdrawn", "expired"}:
        raise s.TeamKnowledgeError("Source lifecycle status must be active, withdrawn, or expired.")
    if not note or len(note) > 1000:
        raise s.TeamKnowledgeError("A source lifecycle reason of at most 1000 characters is required.")
    expiry = _date(expires_at).isoformat().replace("+00:00", "Z") if expires_at else ""
    with s._LOCK:
        rows = s._read_jsonl(s._source_artifacts_path_for_owner(owner))
        source = s._find_by_id(rows, "sourceArtifactId", source_artifact_id)
        if not source or source.get("knowledgeBaseId") != base["knowledgeBaseId"]:
            raise s.TeamKnowledgeNotFoundError("Source artifact not found.")
        previous_state = source_lifecycle_state(source, now=s.utc_now_iso())
        if previous_state != "active" or state != "active":
            source["lifecycleRevision"] = int(source.get("lifecycleRevision") or 0) + 1
        source.update({
            "status": state, "expiresAt": expiry, "lifecycleReason": note,
            "lifecycleUpdatedAt": s.utc_now_iso(), "lifecycleUpdatedByAgentId": actor_agent_id,
        })
        s._write_jsonl(s._source_artifacts_path_for_owner(owner), rows)
        s._append_audit(owner, "knowledge.source.lifecycle.updated", source, actor_agent_id=actor_agent_id)
    s._record_event(
        "knowledge.source.lifecycle.updated", owner, base["knowledgeBaseId"], actor_agent_id=actor_agent_id,
        fields={"sourceArtifactId": source_artifact_id, "status": state, "hasExpiry": bool(expiry)},
    )
    return {"sourceArtifact": s._public_source_artifact(source)}


def list_knowledge_item_versions(
    knowledge_base_id: str, knowledge_item_id: str, *, agent_id: str, offset: int = 0, limit: int = 25,
) -> dict:
    s = _service()
    owner, base = s._require_base_with_owner(knowledge_base_id)
    s._require_permission(owner, base, agent_id, "read")
    if owner["ownerType"] == "agent" and owner["ownerId"] != agent_id:
        raise s.TeamKnowledgePermissionError("Private knowledge history is only readable by its owner.")
    target = s._require_item(owner, base["knowledgeBaseId"], knowledge_item_id)
    root = str(target.get("rootKnowledgeItemId") or target["knowledgeItemId"])
    items = s._read_jsonl(s._items_path_for_owner(owner))
    artifacts = {row["sourceArtifactId"]: row for row in s._source_artifacts_for_base(owner, base["knowledgeBaseId"])}
    states = lifecycle_states_for_base(owner, base, items, artifacts)
    versions = [row for row in items if row.get("knowledgeBaseId") == base["knowledgeBaseId"]
                and str(row.get("rootKnowledgeItemId") or row.get("knowledgeItemId")) == root]
    versions.sort(key=lambda row: int(row.get("revision") or 1), reverse=True)
    start = min(max(0, int(offset)), len(versions))
    end = min(len(versions), start + max(1, min(100, int(limit))))
    return {
        "knowledgeBaseId": base["knowledgeBaseId"], "ownerType": owner["ownerType"], "ownerId": owner["ownerId"],
        "rootKnowledgeItemId": root, "versionCount": len(versions),
        "versions": [{
            "knowledgeItemId": row["knowledgeItemId"], "revision": int(row.get("revision") or 1),
            "contentSha256": content_sha256(row), "contentLength": len(str(row.get("content") or "")),
            "state": states.get(row["knowledgeItemId"], "unavailable"),
            "title": str(row.get("title") or "")[:240], "reviewedAt": row.get("reviewedAt") or "",
            "reviewedByAgentId": row.get("reviewedByAgentId") or "",
            "supersedesKnowledgeItemId": row.get("supersedesKnowledgeItemId") or "",
            "revisionReason": row.get("revisionReason") or "",
        } for row in versions[start:end]],
        "offset": start, "hasMore": end < len(versions), "nextOffset": end if end < len(versions) else None,
    }


def read_knowledge_source_snapshot(
    knowledge_base_id: str, knowledge_item_id: str, source_artifact_id: str, *, agent_id: str,
) -> dict[str, Any]:
    """Read only a linked, owner-authorized, checksummed central text snapshot."""
    s = _service()
    owner, base = s._require_base_with_owner(knowledge_base_id)
    item = s.get_readable_knowledge_item(knowledge_base_id, knowledge_item_id, agent_id=agent_id)
    if source_artifact_id not in (item.get("sourceArtifactIds") or []):
        raise s.TeamKnowledgeError("Source artifact is not linked to this knowledge item.")
    source = s._find_by_id(s._source_artifacts_for_base(owner, base["knowledgeBaseId"]), "sourceArtifactId", source_artifact_id)
    central, _ = s._require_central_source_for_owner(owner, str(source.get("centralSourceId") or ""), actor_agent_id=agent_id)
    if source_lifecycle_state(source, now=s.utc_now_iso()) != "active":
        raise s.TeamKnowledgeNotFoundError("Source is no longer active.")
    if source.get("sourceHash") != central.get("sourceHash"):
        raise s.TeamKnowledgeError("Source snapshot relation does not match its central source.")
    year = str(central.get("snapshotYear") or "")
    filename = str(central.get("snapshotFilename") or "")
    expected_hash = str(central.get("snapshotSha256") or "")
    if not re.fullmatch(r"[0-9]{4}", year) or not filename or Path(filename).name != filename:
        raise s.TeamKnowledgeError("Original source body is unavailable; restage the source with integrity metadata.")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise s.TeamKnowledgeError("Original source integrity metadata is unavailable.")
    # Keep the lexical trusted parent so an ancestor symlink cannot redefine it.
    expected_path = s._central_source_accepted_dir().absolute() / year / central["centralSourceId"] / filename
    actual_path = s._project_path_from_relative(str(central.get("centralPath") or ""))
    if actual_path.absolute() != expected_path or actual_path.resolve() != expected_path:
        raise s.TeamKnowledgeError("Source snapshot path is outside its governed source directory.")
    try:
        if actual_path.stat().st_size > 1_000_000:
            raise s.TeamKnowledgeError("Original source body exceeds the bounded text reader limit.")
        body = actual_path.read_bytes()
    except OSError as exc:
        raise s.TeamKnowledgeNotFoundError("Original source snapshot is unavailable.") from exc
    if hashlib.sha256(body).hexdigest() != expected_hash:
        raise s.TeamKnowledgeError("Original source snapshot integrity check failed.")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise s.TeamKnowledgeError("Original source snapshot is not a supported UTF-8 text document.") from exc
    return {"content": text, "contentSha256": expected_hash, "centralSourceId": central["centralSourceId"]}
