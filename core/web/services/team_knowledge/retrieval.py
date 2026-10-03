"""Canonical ACL/lifecycle filtering shared by formal knowledge reads and retrieval."""
from __future__ import annotations
from typing import Any
from . import lifecycle

def _service():
    from core.web.services import team_knowledge_service
    return team_knowledge_service


def _require_owner_read_permission(owner: dict, base: dict, agent_id: str) -> None:
    s = _service()
    s._require_permission(owner, base, agent_id, "read")
    if owner["ownerType"] == "agent" and owner["ownerId"] != str(agent_id or "").strip():
        raise s.TeamKnowledgePermissionError("Agent private knowledge is only readable by its owner.")


def list_knowledge_items(knowledge_base_id: str, *, agent_id: str = "") -> dict[str, Any]:
    s = _service()
    owner, base = s._require_base_with_owner(knowledge_base_id)
    _require_owner_read_permission(owner, base, agent_id)
    items = [
        item
        for item in s._read_jsonl(s._items_path_for_owner(owner))
        if str(item.get("knowledgeBaseId") or "") == base["knowledgeBaseId"]
    ]
    items.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    artifacts = {row["sourceArtifactId"]: row for row in s._source_artifacts_for_base(owner, base["knowledgeBaseId"])}
    states = lifecycle.lifecycle_states_for_base(owner, base, items, artifacts)
    if str(base.get("status") or "active") != "active":
        states = {row["knowledgeItemId"]: "archived" for row in items}
    items = [{**row, "knowledgeState": states[row["knowledgeItemId"]],
              "content": (row.get("content") or "") if states[row["knowledgeItemId"]] == "active" else "",
              "contentLength": len(str(row.get("content") or "")),
              "revision": int(row.get("revision") or 1), "contentSha256": lifecycle.content_sha256(row),
              "rootKnowledgeItemId": row.get("rootKnowledgeItemId") or row["knowledgeItemId"]} for row in items]
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "knowledgeBase": s._knowledge_base_to_api(base, owner),
        "items": items,
        "summary": {"itemCount": len(items)},
        "updatedAt": s.utc_now_iso(),
    }



def get_readable_knowledge_item(
    knowledge_base_id: str,
    knowledge_item_id: str,
    *,
    agent_id: str,
) -> dict[str, Any]:
    """Read one formal item under the same ACL and eligibility as retrieval."""

    s = _service()
    owner, base = s._require_base_with_owner(knowledge_base_id)
    _require_owner_read_permission(owner, base, agent_id)
    if str(base.get("status") or "active") != "active":
        raise s.TeamKnowledgeNotFoundError("Knowledge item not found.")
    stored_items = s._read_jsonl(s._items_path_for_owner(owner))
    item = s._find_by_id(stored_items, "knowledgeItemId", str(knowledge_item_id or "").strip())
    if not item or str(item.get("knowledgeBaseId") or "") != base["knowledgeBaseId"]:
        raise s.TeamKnowledgeNotFoundError("Knowledge item not found.")
    artifacts_by_id = {
        str(source.get("sourceArtifactId") or ""): source
        for source in s._source_artifacts_for_base(owner, base["knowledgeBaseId"])
    }
    eligible = s._tk_financial.eligible_financial_items(owner, base, stored_items, artifacts_by_id)
    if lifecycle.lifecycle_states_for_base(owner, base, stored_items, artifacts_by_id).get(item["knowledgeItemId"]) != "active":
        raise s.TeamKnowledgeNotFoundError("Knowledge item is no longer active.")
    if eligible is not None:
        if item["knowledgeItemId"] not in eligible:
            raise s.TeamKnowledgeNotFoundError("Knowledge item not found.")
        item = s._tk_financial.financial_item_projection(item, eligible[item["knowledgeItemId"]])
    return {**item, "ownerType": owner["ownerType"], "ownerId": owner["ownerId"],
            "contentSha256": lifecycle.content_sha256(item), "revision": int(item.get("revision") or 1),
            "rootKnowledgeItemId": item.get("rootKnowledgeItemId") or item["knowledgeItemId"]}



def search_knowledge_items(
    *,
    agent_id: str = "",
    query: str = "",
    team_id: str = "",
    owner_type: str = "",
    owner_id: str = "",
    knowledge_base_id: str = "",
    research_project_id: str = "",
    question_id: str = "",
    source_collection_run_id: str = "",
    tags: list[str] | None = None,
    source_type: str = "",
    importance_level: str = "",
    confidence_min: float | None = None,
    stability: str = "",
    created_from: str = "",
    created_to: str = "",
    search_mode: str = "exact",
    limit: int = 25,
    private_memory_enabled: bool = True,
) -> dict[str, Any]:
    s = _service()
    s._sync_roots()
    normalized_query = s.trim_lines(query or "", max_lines=4).strip().lower()
    normalized_team_id = str(team_id or "").strip()
    normalized_owner_type = s._normalize_owner_type(owner_type)
    normalized_owner_id = str(owner_id or "").strip()
    scoped_owner_type, scoped_owner_id, normalized_base_id = s._parse_owner_scoped_knowledge_base_id(knowledge_base_id)
    normalized_owner_type = normalized_owner_type or scoped_owner_type
    normalized_owner_id = normalized_owner_id or scoped_owner_id
    normalized_tags = {item.lower() for item in s._unique_strings(tags or [])}
    normalized_research_project_id = str(research_project_id or "").strip()
    normalized_question_id = str(question_id or "").strip()
    normalized_source_collection_run_id = str(source_collection_run_id or "").strip()
    normalized_source_type = str(source_type or "").strip()
    if normalized_source_type and normalized_source_type not in s.SOURCE_TYPES:
        raise s.TeamKnowledgeError(f"Unsupported source type: {source_type}")
    normalized_importance = s._enum_value(importance_level, s.IMPORTANCE_LEVELS, "importance level") if importance_level else ""
    normalized_stability = s._enum_value(stability, s.STABILITY_VALUES, "stability") if stability else ""
    normalized_search_mode = str(search_mode or "exact").strip().lower()
    if normalized_search_mode not in s.KNOWLEDGE_SEARCH_MODES:
        raise s.TeamKnowledgeError(f"Unsupported knowledge search mode: {search_mode}")
    bounded_limit = max(1, min(100, int(limit or 25)))
    score_after_scan = normalized_search_mode in {"bm25", "semantic", "hybrid"}
    semantic_info = None
    results: list[dict[str, Any]] = []
    scanned_bases = 0
    owner_candidates = s._iter_knowledge_owners(agent_id=agent_id, include_archived=True)
    if normalized_owner_type and normalized_owner_id and not any(
        str(owner.get("ownerType") or "") == normalized_owner_type and str(owner.get("ownerId") or "") == normalized_owner_id
        for owner in owner_candidates
    ):
        owner_candidates.append(s._owner_context(normalized_owner_type, normalized_owner_id))
    if normalized_base_id and not (normalized_owner_type and normalized_owner_id):
        visible_matches = [
            owner
            for owner in owner_candidates
            for base in s._knowledge_bases_for_owner(owner)
            if str(base.get("knowledgeBaseId") or "") == normalized_base_id
            and s._can_access(owner, base, agent_id, "read")
        ]
        unique_owner_keys = {
            (str(owner.get("ownerType") or ""), str(owner.get("ownerId") or ""))
            for owner in visible_matches
        }
        if len(unique_owner_keys) > 1:
            raise s.TeamKnowledgeAmbiguousKnowledgeBaseError(
                "Knowledge base id is ambiguous across owners; use scopedKnowledgeBaseId."
            )
    for owner in owner_candidates:
        current_owner_type = str(owner.get("ownerType") or "").strip()
        current_owner_id = str(owner.get("ownerId") or "").strip()
        if not private_memory_enabled and current_owner_type == "agent":
            continue
        if normalized_owner_type and current_owner_type != normalized_owner_type:
            continue
        if normalized_owner_id and current_owner_id != normalized_owner_id:
            continue
        if normalized_team_id and not (current_owner_type == "team" and current_owner_id == normalized_team_id):
            continue
        readable_bases = [
            base
            for base in s._knowledge_bases_for_owner(owner)
            if (not normalized_base_id or str(base.get("knowledgeBaseId") or "") == normalized_base_id)
            and str(base.get("status") or "active") == "active"
            and s._can_access(owner, base, agent_id, "read")
        ]
        if not readable_bases:
            continue
        owner_artifacts = s._read_jsonl(s._source_artifacts_path_for_owner(owner))
        stored_items = s._read_jsonl(s._items_path_for_owner(owner))
        for base in readable_bases:
            base_id = str(base.get("knowledgeBaseId") or "")
            scanned_bases += 1
            artifacts_by_id = {
                str(artifact.get("sourceArtifactId") or ""): s._public_source_artifact(artifact)
                for artifact in owner_artifacts
                if str(artifact.get("knowledgeBaseId") or "") == base_id
                and str(artifact.get("sourceArtifactId") or "")
            }
            financial_items = s._tk_financial.eligible_financial_items(owner, base, stored_items, artifacts_by_id)
            states = lifecycle.lifecycle_states_for_base(owner, base, stored_items, artifacts_by_id)
            for item in stored_items:
                if states.get(str(item.get("knowledgeItemId") or "")) != "active":
                    continue
                if financial_items is not None and item.get("knowledgeItemId") not in financial_items:
                    continue
                if financial_items is not None:
                    item = s._tk_financial.financial_item_projection(item, financial_items[item["knowledgeItemId"]])
                if str(item.get("knowledgeBaseId") or "") != base_id:
                    continue
                linked_artifacts = {
                    source_id: artifacts_by_id[source_id]
                    for source_id in [str(value or "") for value in list(item.get("sourceArtifactIds") or [])]
                    if source_id in artifacts_by_id
                }
                search_document = s._knowledge_item_search_document(item, linked_artifacts)
                if not s._item_matches_filters(
                    item,
                    query="" if score_after_scan else normalized_query,
                    tags=normalized_tags,
                    source_type=normalized_source_type,
                    importance_level=normalized_importance,
                    confidence_min=confidence_min,
                    stability=normalized_stability,
                    created_from=created_from,
                    created_to=created_to,
                    artifacts_by_id=linked_artifacts,
                    search_mode=normalized_search_mode,
                    research_project_id=normalized_research_project_id,
                    question_id=normalized_question_id,
                    source_collection_run_id=normalized_source_collection_run_id,
                    search_document=search_document,
                ):
                    continue
                view = s._search_item_view(
                    item,
                    base,
                    owner,
                    linked_artifacts,
                    query=normalized_query,
                    search_document=search_document,
                )
                view["_searchDocument"] = search_document
                from core.web.services.rag_vector_index_service import _content_hash
                view["_indexContentHash"] = _content_hash(item)
                view["revision"] = int(item.get("revision") or 1)
                view["rootKnowledgeItemId"] = item.get("rootKnowledgeItemId") or item["knowledgeItemId"]
                view["contentSha256"] = lifecycle.content_sha256(item)
                if financial_items is not None:
                    view["financialEvidence"] = financial_items[item["knowledgeItemId"]]
                if score_after_scan:
                    view["semanticScore"] = 1.0 if not normalized_query else 0.0
                    view["searchMode"] = normalized_search_mode
                    view["matchReason"] = "no_query" if not normalized_query else "metadata_filter"
                else:
                    score = s._semantic_match_score(search_document, normalized_query) if normalized_query else 1.0
                    if normalized_query and normalized_search_mode == "semantic" and score <= 0:
                        continue
                    view["semanticScore"] = score
                    view["searchMode"] = normalized_search_mode
                    view["matchReason"] = s._search_match_reason(search_document, normalized_query, score)
                results.append(view)
    if normalized_search_mode in {"semantic", "hybrid"} and normalized_query:
        from .semantic import rank_candidates
        results, semantic_info = rank_candidates(results, normalized_query, mode=normalized_search_mode)
        results = results[:bounded_limit]
    elif score_after_scan:
        results = s._rank_bm25_search_results(results, normalized_query)
        if normalized_query:
            results = [item for item in results if float(item.get("semanticScore") or 0.0) > 0]
        results = results[:bounded_limit]
    else:
        results.sort(key=lambda item: (float(item.get("semanticScore") or 0.0), str(item.get("updatedAt") or item.get("createdAt") or "")), reverse=True)
        results = results[:bounded_limit]
    for result in results:
        result.pop("_searchDocument", None)
        result.pop("_indexContentHash", None)
    s._record_event(
        "knowledge.search.executed",
        normalized_team_id,
        normalized_base_id,
        actor_agent_id=agent_id,
        fields={"queryLength": len(normalized_query), "resultCount": len(results), "scannedKnowledgeBaseCount": scanned_bases},
    )
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "agentId": str(agent_id or "").strip(),
        **({"semanticRetrieval": semantic_info} if semantic_info is not None else {}),
        "filters": {
            "query": normalized_query,
            "teamId": normalized_team_id,
            "ownerType": normalized_owner_type,
            "ownerId": normalized_owner_id,
            "knowledgeBaseId": normalized_base_id,
            "researchProjectId": normalized_research_project_id,
            "questionId": normalized_question_id,
            "sourceCollectionRunId": normalized_source_collection_run_id,
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
        "updatedAt": s.utc_now_iso(),
    }
