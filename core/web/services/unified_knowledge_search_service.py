"""Unified read-only search boundary for governed memory and formal knowledge."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from core.chat.chat_task_types import trim_lines
from core.chatroom.store import utc_now_iso

from . import rag_retrieval_service, team_knowledge_service, user_content_markdown_service


SCHEMA_VERSION = 1
SUPPORTED_QUERY_MODES = {"auto", "literal", "exact", "semantic", "hybrid", "bm25", "metadata", "regex", "rg", "grep", "rag"}
MAX_LIMIT = 25
REGEX_SCAN_LIMIT = 100


class UnifiedMemorySearchError(ValueError):
    """Raised when a unified search request is invalid."""


def search_unified_memory(
    *,
    agent_id: str = "",
    query: str = "",
    query_mode: str = "auto",
    owner_type: str = "",
    owner_id: str = "",
    knowledge_base_id: str = "",
    tags: list[str] | None = None,
    allowed_knowledge_base_ids: list[str] | set[str] | tuple[str, ...] | None = None,
    include_user_content: bool = False,
    allowed_user_content_space_ids: list[str] | set[str] | tuple[str, ...] | None = None,
    user_id: str = "default",
    limit: int = 8,
    max_context_chars: int = 1200,
) -> dict[str, Any]:
    """Search formal Agent/Team memory through one stable Agent-facing result contract."""

    normalized_agent_id = str(agent_id or "").strip()
    normalized_query = trim_lines(str(query or ""), max_lines=4).strip()
    requested_mode = str(query_mode or "auto").strip().lower() or "auto"
    if requested_mode not in SUPPORTED_QUERY_MODES:
        raise UnifiedMemorySearchError(f"Unsupported unified memory query mode: {query_mode}")
    effective_mode = _effective_query_mode(requested_mode, normalized_query)
    bounded_limit = _clamp_limit(limit)
    normalized_tags = [str(tag or "").strip() for tag in list(tags or []) if str(tag or "").strip()]
    normalized_allowed_base_ids = _unique_strings(allowed_knowledge_base_ids or [])
    normalized_user_content_space_ids = _unique_strings(allowed_user_content_space_ids or [])
    normalized_base_id = str(knowledge_base_id or "").strip()
    normalized_user_id = str(user_id or "default").strip() or "default"
    if normalized_base_id and normalized_allowed_base_ids and not _policy_allows_knowledge_base(normalized_base_id, normalized_allowed_base_ids):
        raise UnifiedMemorySearchError("Knowledge base is not allowed by the active memory policy.")

    if effective_mode == "rag":
        return _rag_search(
            agent_id=normalized_agent_id,
            query=normalized_query,
            requested_mode=requested_mode,
            effective_mode=effective_mode,
            owner_type=owner_type,
            owner_id=owner_id,
            knowledge_base_id=normalized_base_id,
            tags=normalized_tags,
            allowed_knowledge_base_ids=normalized_allowed_base_ids,
            include_user_content=bool(include_user_content),
            allowed_user_content_space_ids=normalized_user_content_space_ids,
            user_id=normalized_user_id,
            limit=bounded_limit,
            max_context_chars=max_context_chars,
        )

    if effective_mode in {"regex", "rg", "grep"}:
        return _regex_search(
            agent_id=normalized_agent_id,
            query=normalized_query,
            requested_mode=requested_mode,
            effective_mode=effective_mode,
            owner_type=owner_type,
            owner_id=owner_id,
            knowledge_base_id=normalized_base_id,
            tags=normalized_tags,
            allowed_knowledge_base_ids=normalized_allowed_base_ids,
            include_user_content=bool(include_user_content),
            allowed_user_content_space_ids=normalized_user_content_space_ids,
            user_id=normalized_user_id,
            limit=bounded_limit,
        )

    search_mode = {
        "literal": "exact",
        "exact": "exact",
        "semantic": "semantic",
        "hybrid": "hybrid",
        "bm25": "bm25",
        "metadata": "exact",
    }[effective_mode]
    search_query = "" if effective_mode == "metadata" else normalized_query
    payloads = _knowledge_search_payloads(
        agent_id=normalized_agent_id,
        query=search_query,
        owner_type=owner_type,
        owner_id=owner_id,
        knowledge_base_id=normalized_base_id,
        tags=normalized_tags,
        search_mode=search_mode,
        limit=bounded_limit,
        allowed_knowledge_base_ids=normalized_allowed_base_ids,
    )
    matched_items = [
        item
        for payload in payloads
        for item in list(payload.get("results") or [])
    ]
    matched_items.sort(
        key=lambda item: (float(item.get("semanticScore") or 0.0), str(item.get("updatedAt") or item.get("createdAt") or "")),
        reverse=True,
    )
    formal_results = [
        _result_from_knowledge_item(item, rank=index + 1, backend=_backend_for_mode(effective_mode))
        for index, item in enumerate(matched_items[:bounded_limit])
    ]
    user_results = _user_content_results(
        include_user_content=bool(include_user_content),
        user_id=normalized_user_id,
        query=normalized_query,
        limit=bounded_limit,
        max_excerpt_chars=max_context_chars,
        allowed_space_ids=normalized_user_content_space_ids,
    )
    results = _merge_ranked_results(formal_results, user_results, limit=bounded_limit)
    return _payload(
        agent_id=normalized_agent_id,
        query=normalized_query,
        requested_mode=requested_mode,
        effective_mode=effective_mode,
        backend=_backend_for_mode(effective_mode),
        owner_type=owner_type,
        owner_id=owner_id,
        knowledge_base_id=normalized_base_id,
        tags=normalized_tags,
        limit=bounded_limit,
        results=results,
        summary=_summary_with_user_content(
            base_summary={
                "candidateCount": sum(int((payload.get("summary") or {}).get("resultCount") or 0) for payload in payloads),
                "scannedKnowledgeBaseCount": sum(int((payload.get("summary") or {}).get("scannedKnowledgeBaseCount") or 0) for payload in payloads),
            },
            results=results,
        ),
        citations=_citations_for_results(results),
    )


def _rag_search(
    *,
    agent_id: str,
    query: str,
    requested_mode: str,
    effective_mode: str,
    owner_type: str,
    owner_id: str,
    knowledge_base_id: str,
    tags: list[str],
    allowed_knowledge_base_ids: list[str],
    include_user_content: bool,
    allowed_user_content_space_ids: list[str],
    user_id: str,
    limit: int,
    max_context_chars: int,
) -> dict[str, Any]:
    payloads = _rag_payloads(
        agent_id=agent_id,
        query=query,
        owner_type=owner_type,
        owner_id=owner_id,
        knowledge_base_id=knowledge_base_id,
        tags=tags,
        limit=limit,
        max_context_chars=max_context_chars,
        allowed_knowledge_base_ids=allowed_knowledge_base_ids,
    )
    contexts = [
        context
        for payload in payloads
        for context in list(payload.get("contexts") or [])
    ]
    contexts.sort(key=lambda context: float(context.get("score") or 0.0), reverse=True)
    selected_contexts = contexts[:limit]
    formal_results = [
        _result_from_rag_context(context, rank=index + 1)
        for index, context in enumerate(selected_contexts)
    ]
    user_results = _user_content_results(
        include_user_content=include_user_content,
        user_id=user_id,
        query=query,
        limit=limit,
        max_excerpt_chars=max_context_chars,
        allowed_space_ids=allowed_user_content_space_ids,
    )
    results = _merge_ranked_results(formal_results, user_results, limit=limit)
    return _payload(
        agent_id=agent_id,
        query=query,
        requested_mode=requested_mode,
        effective_mode=effective_mode,
        backend="local_rag",
        owner_type=owner_type,
        owner_id=owner_id,
        knowledge_base_id=knowledge_base_id,
        tags=tags,
        limit=limit,
        results=results,
        summary=_summary_with_user_content(
            base_summary={
                "candidateCount": sum(int((payload.get("summary") or {}).get("candidateCount") or 0) for payload in payloads),
                "contextCount": len(selected_contexts),
                "citationCount": len(_citations_for_results(results)),
                "scannedKnowledgeBaseCount": sum(int((payload.get("summary") or {}).get("scannedKnowledgeBaseCount") or 0) for payload in payloads),
            },
            results=results,
        ),
        citations=_citations_for_results(results),
        retrieval_policy=_read_only_policy("local_rag"),
    )


def _regex_search(
    *,
    agent_id: str,
    query: str,
    requested_mode: str,
    effective_mode: str,
    owner_type: str,
    owner_id: str,
    knowledge_base_id: str,
    tags: list[str],
    allowed_knowledge_base_ids: list[str],
    include_user_content: bool,
    allowed_user_content_space_ids: list[str],
    user_id: str,
    limit: int,
) -> dict[str, Any]:
    if not query:
        raise UnifiedMemorySearchError("Regex unified memory search requires query.")
    try:
        pattern = re.compile(query, re.IGNORECASE)
    except re.error as exc:
        raise UnifiedMemorySearchError(f"Invalid regex query: {exc}") from exc
    payloads = _knowledge_search_payloads(
        agent_id=agent_id,
        query="",
        owner_type=owner_type,
        owner_id=owner_id,
        knowledge_base_id=knowledge_base_id,
        tags=tags,
        search_mode="exact",
        limit=REGEX_SCAN_LIMIT,
        allowed_knowledge_base_ids=allowed_knowledge_base_ids,
    )
    matched = []
    for payload in payloads:
        for item in list(payload.get("results") or []):
            if pattern.search(_knowledge_text(item)):
                next_item = dict(item)
                next_item["semanticScore"] = 1.0
                next_item["matchReason"] = "regex_match"
                matched.append(next_item)
            if len(matched) >= limit:
                break
        if len(matched) >= limit:
            break
    formal_results = [
        _result_from_knowledge_item(item, rank=index + 1, backend="local_regex")
        for index, item in enumerate(matched)
    ]
    user_results = _user_content_results(
        include_user_content=include_user_content,
        user_id=user_id,
        query=query,
        limit=limit,
        max_excerpt_chars=900,
        allowed_space_ids=allowed_user_content_space_ids,
    )
    results = _merge_ranked_results(formal_results, user_results, limit=limit)
    return _payload(
        agent_id=agent_id,
        query=query,
        requested_mode=requested_mode,
        effective_mode=effective_mode,
        backend="local_regex",
        owner_type=owner_type,
        owner_id=owner_id,
        knowledge_base_id=knowledge_base_id,
        tags=tags,
        limit=limit,
        results=results,
        summary=_summary_with_user_content(
            base_summary={
                "candidateCount": sum(int((payload.get("summary") or {}).get("resultCount") or 0) for payload in payloads),
                "scannedKnowledgeBaseCount": sum(int((payload.get("summary") or {}).get("scannedKnowledgeBaseCount") or 0) for payload in payloads),
            },
            results=results,
        ),
        citations=_citations_for_results(results),
    )


def _payload(
    *,
    agent_id: str,
    query: str,
    requested_mode: str,
    effective_mode: str,
    backend: str,
    owner_type: str,
    owner_id: str,
    knowledge_base_id: str,
    tags: list[str],
    limit: int,
    results: list[dict[str, Any]],
    summary: dict[str, Any],
    citations: list[dict[str, Any]] | None = None,
    retrieval_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": agent_id,
        "request": {
            "query": query,
            "queryLength": len(query),
            "queryMode": requested_mode,
            "effectiveQueryMode": effective_mode,
            "backend": backend,
            "ownerType": str(owner_type or "").strip(),
            "ownerId": str(owner_id or "").strip(),
            "knowledgeBaseId": str(knowledge_base_id or "").strip(),
            "tags": sorted({str(tag or "").strip().lower() for tag in tags if str(tag or "").strip()}),
            "limit": limit,
        },
        "summary": summary,
        "results": results,
        "citations": citations or [],
        "retrievalPolicy": retrieval_policy or _read_only_policy(backend),
        "updatedAt": utc_now_iso(),
    }


def _result_from_knowledge_item(item: dict[str, Any], *, rank: int, backend: str) -> dict[str, Any]:
    knowledge_item_id = str(item.get("knowledgeItemId") or "").strip()
    excerpt = _excerpt(_knowledge_text(item), max_chars=900)
    return {
        "resultId": _result_id("knowledge_item", knowledge_item_id, rank),
        "resultType": "knowledge_item",
        "title": str(item.get("title") or "").strip(),
        "excerpt": excerpt,
        "score": float(item.get("semanticScore") or 0.0),
        "rank": rank,
        "ownerType": str(item.get("ownerType") or "team").strip(),
        "ownerId": str(item.get("ownerId") or item.get("teamId") or item.get("agentId") or "").strip(),
        "teamId": str(item.get("teamId") or "").strip(),
        "teamName": str(item.get("teamName") or "").strip(),
        "agentId": str(item.get("agentId") or "").strip(),
        "agentName": str(item.get("agentName") or "").strip(),
        "knowledgeBaseId": str(item.get("knowledgeBaseId") or "").strip(),
        "knowledgeBaseName": str(item.get("knowledgeBaseName") or "").strip(),
        "knowledgeItemId": knowledge_item_id,
        "sourceArtifactIds": [str(value or "").strip() for value in list(item.get("sourceArtifactIds") or []) if str(value or "").strip()],
        "centralSourceIds": [str(value or "").strip() for value in list(item.get("centralSourceIds") or []) if str(value or "").strip()],
        "searchBackend": backend,
        "matchReason": str(item.get("matchReason") or "").strip(),
        "metadata": {
            "tags": [str(tag or "").strip() for tag in list(item.get("tags") or []) if str(tag or "").strip()],
            "importanceLevel": str(item.get("importanceLevel") or "").strip(),
            "confidence": item.get("confidence"),
            "stability": str(item.get("stability") or "").strip(),
            "updatedAt": str(item.get("updatedAt") or item.get("createdAt") or "").strip(),
        },
    }


def _result_from_rag_context(context: dict[str, Any], *, rank: int) -> dict[str, Any]:
    source = context.get("source") if isinstance(context.get("source"), dict) else {}
    metadata = context.get("metadata") if isinstance(context.get("metadata"), dict) else {}
    knowledge_item_id = str(source.get("knowledgeItemId") or "").strip()
    return {
        "resultId": str(context.get("contextId") or _result_id("rag_context", knowledge_item_id, rank)).strip(),
        "resultType": "rag_context",
        "title": str(context.get("title") or "").strip(),
        "excerpt": _excerpt(str(context.get("text") or ""), max_chars=1200),
        "score": float(context.get("score") or 0.0),
        "rank": rank,
        "ownerType": str(source.get("ownerType") or "team").strip(),
        "ownerId": str(source.get("ownerId") or source.get("teamId") or source.get("agentId") or "").strip(),
        "teamId": str(source.get("teamId") or "").strip(),
        "teamName": str(source.get("teamName") or "").strip(),
        "agentId": str(source.get("agentId") or "").strip(),
        "agentName": str(source.get("agentName") or "").strip(),
        "knowledgeBaseId": str(source.get("knowledgeBaseId") or "").strip(),
        "knowledgeBaseName": str(source.get("knowledgeBaseName") or "").strip(),
        "knowledgeItemId": knowledge_item_id,
        "sourceArtifactIds": [str(value or "").strip() for value in list(source.get("sourceArtifactIds") or []) if str(value or "").strip()],
        "centralSourceIds": [str(value or "").strip() for value in list(source.get("centralSourceIds") or []) if str(value or "").strip()],
        "searchBackend": "local_rag",
        "matchReason": str(context.get("matchReason") or "").strip(),
        "metadata": {
            **metadata,
            "provider": str(context.get("provider") or "").strip(),
            "retrievalMode": str(context.get("retrievalMode") or "").strip(),
        },
    }


def _user_content_results(
    *,
    include_user_content: bool,
    user_id: str,
    query: str,
    limit: int,
    max_excerpt_chars: int,
    allowed_space_ids: list[str],
) -> list[dict[str, Any]]:
    if not include_user_content:
        return []
    payloads = []
    for current_space_id in allowed_space_ids or [""]:
        payloads.append(
            user_content_markdown_service.search_user_markdown_spaces(
                user_id=user_id,
                query=query,
                space_id=current_space_id,
                limit=limit,
                max_excerpt_chars=max_excerpt_chars,
            )
        )
    merged = [
        dict(item)
        for payload in payloads
        for item in list(payload.get("results") or [])
    ]
    merged.sort(key=lambda item: (_result_score(item), _result_updated_at(item), str(item.get("title") or "")), reverse=True)
    return [
        {**item, "rank": index + 1}
        for index, item in enumerate(merged[:limit])
    ]


def _merge_ranked_results(formal_results: list[dict[str, Any]], user_results: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    merged = [dict(item) for item in list(formal_results or [])] + [dict(item) for item in list(user_results or [])]
    merged.sort(key=lambda item: (_result_score(item), _result_updated_at(item), str(item.get("title") or "")), reverse=True)
    ranked = []
    for index, item in enumerate(merged[:limit], start=1):
        next_item = _rerank_result(item, rank=index)
        ranked.append(next_item)
    return ranked


def _rerank_result(item: dict[str, Any], *, rank: int) -> dict[str, Any]:
    next_item = dict(item)
    next_item["rank"] = rank
    if str(next_item.get("resultType") or "") == "knowledge_item":
        next_item["resultId"] = _result_id("knowledge_item", str(next_item.get("knowledgeItemId") or "").strip(), rank)
    return next_item


def _summary_with_user_content(*, base_summary: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    summary = dict(base_summary)
    summary["formalResultCount"] = sum(1 for item in results if str(item.get("resultType") or "") != "user_markdown_page")
    summary["userContentResultCount"] = sum(1 for item in results if str(item.get("resultType") or "") == "user_markdown_page")
    summary["resultCount"] = len(results)
    return summary


def _citations_for_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    citations = []
    for result in results:
        rank = int(result.get("rank") or 0)
        result_type = str(result.get("resultType") or "")
        if result_type == "rag_context":
            citations.append(
                _citation_from_rag_result(result, rank=rank)
            )
            continue
        citation = result.get("citation") if isinstance(result.get("citation"), dict) else {}
        if citation:
            citations.append({**citation, "rank": rank, "title": str(result.get("title") or "").strip()})
    return citations


def _citation_from_rag_result(result: dict[str, Any], *, rank: int) -> dict[str, Any]:
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    return {
        "contextId": str(result.get("resultId") or "").strip(),
        "rank": rank,
        "title": str(result.get("title") or "").strip(),
        "ownerType": str(result.get("ownerType") or "team").strip(),
        "ownerId": str(result.get("ownerId") or "").strip(),
        "teamId": str(result.get("teamId") or "").strip(),
        "teamName": str(result.get("teamName") or "").strip(),
        "agentId": str(result.get("agentId") or "").strip(),
        "agentName": str(result.get("agentName") or "").strip(),
        "knowledgeBaseId": str(result.get("knowledgeBaseId") or "").strip(),
        "knowledgeBaseName": str(result.get("knowledgeBaseName") or "").strip(),
        "knowledgeItemId": str(result.get("knowledgeItemId") or "").strip(),
        "sourceArtifactIds": list(result.get("sourceArtifactIds") or []),
        "centralSourceIds": list(result.get("centralSourceIds") or []),
        "provider": str(metadata.get("provider") or "").strip(),
        "retrievalMode": str(metadata.get("retrievalMode") or "").strip(),
    }


def _result_score(item: dict[str, Any]) -> float:
    return float(item.get("score") or item.get("semanticScore") or 0.0)


def _result_updated_at(item: dict[str, Any]) -> str:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return str(
        item.get("updatedAt")
        or item.get("createdAt")
        or metadata.get("updatedAt")
        or ""
    )


def _citation_from_rag_context(context: dict[str, Any], *, rank: int) -> dict[str, Any]:
    source = context.get("source") if isinstance(context.get("source"), dict) else {}
    return {
        "contextId": str(context.get("contextId") or "").strip(),
        "rank": rank,
        "title": str(context.get("title") or "").strip(),
        "ownerType": str(source.get("ownerType") or "team").strip(),
        "ownerId": str(source.get("ownerId") or source.get("teamId") or source.get("agentId") or "").strip(),
        "teamId": str(source.get("teamId") or "").strip(),
        "teamName": str(source.get("teamName") or "").strip(),
        "agentId": str(source.get("agentId") or "").strip(),
        "agentName": str(source.get("agentName") or "").strip(),
        "knowledgeBaseId": str(source.get("knowledgeBaseId") or "").strip(),
        "knowledgeBaseName": str(source.get("knowledgeBaseName") or "").strip(),
        "knowledgeItemId": str(source.get("knowledgeItemId") or "").strip(),
        "sourceArtifactIds": list(source.get("sourceArtifactIds") or []),
        "centralSourceIds": list(source.get("centralSourceIds") or []),
        "provider": str(context.get("provider") or "").strip(),
        "retrievalMode": str(context.get("retrievalMode") or "").strip(),
    }


def _knowledge_search_payloads(
    *,
    agent_id: str,
    query: str,
    owner_type: str,
    owner_id: str,
    knowledge_base_id: str,
    tags: list[str],
    search_mode: str,
    limit: int,
    allowed_knowledge_base_ids: list[str],
) -> list[dict[str, Any]]:
    payloads = []
    for base_id in _effective_knowledge_base_ids(knowledge_base_id, allowed_knowledge_base_ids):
        payloads.append(
            team_knowledge_service.search_knowledge_items(
                agent_id=agent_id,
                query=query,
                owner_type=str(owner_type or "").strip(),
                owner_id=str(owner_id or "").strip(),
                knowledge_base_id=base_id,
                tags=tags,
                search_mode=search_mode,
                limit=limit,
            )
        )
    return payloads


def _rag_payloads(
    *,
    agent_id: str,
    query: str,
    owner_type: str,
    owner_id: str,
    knowledge_base_id: str,
    tags: list[str],
    limit: int,
    max_context_chars: int,
    allowed_knowledge_base_ids: list[str],
) -> list[dict[str, Any]]:
    payloads = []
    for base_id in _effective_knowledge_base_ids(knowledge_base_id, allowed_knowledge_base_ids):
        payloads.append(
            rag_retrieval_service.retrieve_rag_contexts(
                agent_id=agent_id,
                query=query,
                owner_type=str(owner_type or "").strip(),
                owner_id=str(owner_id or "").strip(),
                knowledge_base_id=base_id,
                tags=tags,
                retrieval_mode="hybrid",
                provider="local",
                top_k=limit,
                max_context_chars=max_context_chars,
            )
        )
    return payloads


def _effective_knowledge_base_ids(knowledge_base_id: str, allowed_knowledge_base_ids: list[str]) -> list[str]:
    normalized_base_id = str(knowledge_base_id or "").strip()
    if normalized_base_id:
        return [normalized_base_id]
    if allowed_knowledge_base_ids:
        return _unique_strings(allowed_knowledge_base_ids)
    return [""]


def _policy_allows_knowledge_base(knowledge_base_id: str, allowed_knowledge_base_ids: list[str]) -> bool:
    if not allowed_knowledge_base_ids:
        return True
    return team_knowledge_service.knowledge_base_policy_allows(knowledge_base_id, allowed_knowledge_base_ids)


def _unique_strings(values: list[str] | set[str] | tuple[str, ...]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        result.append(item)
        seen.add(item)
    return result


def _effective_query_mode(requested_mode: str, query: str) -> str:
    if requested_mode == "auto":
        return "hybrid" if query else "metadata"
    return requested_mode


def _backend_for_mode(mode: str) -> str:
    return {
        "literal": "local_exact",
        "exact": "local_exact",
        "semantic": "local_token_overlap",
        "hybrid": "local_hybrid",
        "bm25": "local_bm25",
        "metadata": "local_metadata",
    }.get(mode, "local_hybrid")


def _knowledge_text(item: dict[str, Any]) -> str:
    return "\n".join(
        part
        for part in [
            trim_lines(str(item.get("title") or ""), max_lines=1).strip(),
            trim_lines(str(item.get("summary") or ""), max_lines=4).strip(),
            trim_lines(str(item.get("content") or ""), max_lines=18).strip(),
            " ".join(str(tag or "").strip() for tag in list(item.get("tags") or []) if str(tag or "").strip()),
        ]
        if part
    )


def _excerpt(text: str, *, max_chars: int) -> str:
    normalized = trim_lines(str(text or ""), max_lines=18).strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3].rstrip() + "..."


def _result_id(result_type: str, knowledge_item_id: str, rank: int) -> str:
    digest = hashlib.sha1(f"{result_type}:{knowledge_item_id}:{rank}".encode("utf-8")).hexdigest()[:12]
    return f"usr-{digest}"


def _read_only_policy(backend: str) -> dict[str, Any]:
    return {
        "backend": backend,
        "honorsKnowledgeAcl": True,
        "honorsMemoryPolicy": True,
        "honorsUserContentPolicy": True,
        "mutatesFormalKnowledge": False,
        "mutatesUserContent": False,
        "injectsPromptByDefault": False,
    }


def _clamp_limit(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 8
    return max(1, min(MAX_LIMIT, parsed))
