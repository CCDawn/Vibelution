"""Governed RAG retrieval helpers for Team Knowledge."""

from __future__ import annotations

import hashlib
from typing import Any

from core.chat.chat_task_types import trim_lines
from core.chatroom.store import utc_now_iso

from . import rag_vector_index_service, team_knowledge_service


SCHEMA_VERSION = 1
SUPPORTED_PROVIDERS = {"local"}
SUPPORTED_RETRIEVAL_MODES = {"exact", "semantic", "hybrid"}
DEFAULT_TOP_K = 5
MAX_TOP_K = 20
DEFAULT_CONTEXT_CHARS = 1200
MAX_CONTEXT_CHARS = 4000


class RagRetrievalError(ValueError):
    """Raised when a RAG retrieval request is invalid."""


def get_rag_retrieval_health(*, agent_id: str = "", internal: bool = False) -> dict[str, Any]:
    """Return read-only RAG provider readiness for the memory platform."""

    normalized_agent_id = str(agent_id or "").strip()
    vector_health = rag_vector_index_service.get_vector_index_health(agent_id=normalized_agent_id, internal=internal)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": normalized_agent_id,
        "provider": "local",
        "status": "ready",
        "providers": [
            {
                "provider": "local",
                "status": "ready",
                "vectorEnabled": False,
                "indexedItemCount": 0,
                "staleItemCount": 0,
            },
            {
                "provider": "vector",
                "status": str(vector_health.get("status") or "unavailable"),
                "vectorEnabled": bool(vector_health.get("vectorEnabled")),
                "indexedItemCount": int(vector_health.get("indexedItemCount") or 0),
                "staleItemCount": int(vector_health.get("staleItemCount") or 0),
                "missingItemCount": int(vector_health.get("missingItemCount") or 0),
                "failedItemCount": int(vector_health.get("failedItemCount") or 0),
                "indexableItemCount": int(vector_health.get("indexableItemCount") or 0),
                "embeddingProvider": str(vector_health.get("embeddingProvider") or ""),
                "embeddingModel": str(vector_health.get("embeddingModel") or ""),
                "lastIndexedAt": str(vector_health.get("lastIndexedAt") or ""),
            },
        ],
        "retrievalPolicy": _retrieval_policy("local"),
        "updatedAt": utc_now_iso(),
    }


def retrieve_rag_contexts(
    *,
    agent_id: str = "",
    query: str = "",
    team_id: str = "",
    owner_type: str = "",
    owner_id: str = "",
    knowledge_base_id: str = "",
    tags: list[str] | None = None,
    retrieval_mode: str = "hybrid",
    provider: str = "local",
    top_k: int = DEFAULT_TOP_K,
    max_context_chars: int = DEFAULT_CONTEXT_CHARS,
) -> dict[str, Any]:
    """Return compact, cited context blocks from reviewed Team Knowledge.

    This service is a retrieval boundary only. It delegates access control and
    item filtering to Team Knowledge search and does not mutate formal
    knowledge or inject anything into Agent prompts.
    """

    normalized_provider = str(provider or "local").strip().lower()
    if normalized_provider not in SUPPORTED_PROVIDERS:
        raise RagRetrievalError(f"Unsupported RAG retrieval provider: {provider}")
    normalized_mode = str(retrieval_mode or "hybrid").strip().lower()
    if normalized_mode not in SUPPORTED_RETRIEVAL_MODES:
        raise RagRetrievalError(f"Unsupported RAG retrieval mode: {retrieval_mode}")
    normalized_top_k = _clamp_int(top_k, default=DEFAULT_TOP_K, minimum=1, maximum=MAX_TOP_K)
    normalized_max_chars = _clamp_int(
        max_context_chars,
        default=DEFAULT_CONTEXT_CHARS,
        minimum=40,
        maximum=MAX_CONTEXT_CHARS,
    )
    normalized_query = trim_lines(str(query or ""), max_lines=4).strip()

    search_payload = team_knowledge_service.search_knowledge_items(
        agent_id=str(agent_id or "").strip(),
        query=normalized_query,
        team_id=str(team_id or "").strip(),
        owner_type=str(owner_type or "").strip(),
        owner_id=str(owner_id or "").strip(),
        knowledge_base_id=str(knowledge_base_id or "").strip(),
        tags=tags or [],
        search_mode=normalized_mode,
        limit=normalized_top_k,
    )
    contexts = [
        _context_from_search_result(
            result,
            rank=index + 1,
            retrieval_mode=normalized_mode,
            provider=normalized_provider,
            max_context_chars=normalized_max_chars,
        )
        for index, result in enumerate(list(search_payload.get("results") or [])[:normalized_top_k])
    ]
    citations = [_citation_from_context(context) for context in contexts]

    return {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": str(agent_id or "").strip(),
        "request": {
            "queryLength": len(normalized_query),
            "teamId": str(team_id or "").strip(),
            "ownerType": str(owner_type or "").strip(),
            "ownerId": str(owner_id or "").strip(),
            "knowledgeBaseId": str(knowledge_base_id or "").strip(),
            "tags": sorted({str(tag or "").strip().lower() for tag in (tags or []) if str(tag or "").strip()}),
            "retrievalMode": normalized_mode,
            "provider": normalized_provider,
            "topK": normalized_top_k,
            "maxContextChars": normalized_max_chars,
        },
        "summary": {
            "candidateCount": int((search_payload.get("summary") or {}).get("resultCount") or 0),
            "contextCount": len(contexts),
            "citationCount": len(citations),
            "scannedKnowledgeBaseCount": int((search_payload.get("summary") or {}).get("scannedKnowledgeBaseCount") or 0),
        },
        "contexts": contexts,
        "citations": citations,
        "retrievalPolicy": {
            **_retrieval_policy(normalized_provider),
        },
        "updatedAt": utc_now_iso(),
    }


def _context_from_search_result(
    result: dict[str, Any],
    *,
    rank: int,
    retrieval_mode: str,
    provider: str,
    max_context_chars: int,
) -> dict[str, Any]:
    source_artifact_ids = [str(item or "").strip() for item in list(result.get("sourceArtifactIds") or []) if str(item or "").strip()]
    central_source_ids = [str(item or "").strip() for item in list(result.get("centralSourceIds") or []) if str(item or "").strip()]
    context_source = {
        "ownerType": str(result.get("ownerType") or "team").strip(),
        "ownerId": str(result.get("ownerId") or result.get("teamId") or result.get("agentId") or "").strip(),
        "teamId": str(result.get("teamId") or "").strip(),
        "teamName": str(result.get("teamName") or "").strip(),
        "agentId": str(result.get("agentId") or "").strip(),
        "agentName": str(result.get("agentName") or "").strip(),
        "knowledgeBaseId": str(result.get("knowledgeBaseId") or "").strip(),
        "knowledgeBaseName": str(result.get("knowledgeBaseName") or "").strip(),
        "knowledgeItemId": str(result.get("knowledgeItemId") or "").strip(),
        "sourceArtifactIds": source_artifact_ids,
        "centralSourceIds": central_source_ids,
    }
    context_id = _context_id(context_source["knowledgeItemId"], rank)
    return {
        "contextId": context_id,
        "text": _trim_context_text(_context_text(result), max_context_chars),
        "title": str(result.get("title") or "").strip(),
        "score": float(result.get("semanticScore") or 0.0),
        "rank": rank,
        "retrievalMode": retrieval_mode,
        "provider": provider,
        "matchReason": str(result.get("matchReason") or "").strip(),
        "source": context_source,
        "metadata": {
            "tags": [str(tag or "").strip() for tag in list(result.get("tags") or []) if str(tag or "").strip()],
            "importanceLevel": str(result.get("importanceLevel") or "").strip(),
            "confidence": result.get("confidence"),
            "stability": str(result.get("stability") or "").strip(),
        },
    }


def _citation_from_context(context: dict[str, Any]) -> dict[str, Any]:
    source = context.get("source") if isinstance(context.get("source"), dict) else {}
    return {
        "contextId": str(context.get("contextId") or "").strip(),
        "rank": int(context.get("rank") or 0),
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


def _context_text(result: dict[str, Any]) -> str:
    parts = [
        trim_lines(str(result.get("title") or ""), max_lines=1).strip(),
        trim_lines(str(result.get("summary") or ""), max_lines=3).strip(),
        trim_lines(str(result.get("content") or ""), max_lines=12).strip(),
    ]
    return "\n".join(part for part in parts if part)


def _trim_context_text(text: str, max_chars: int) -> str:
    normalized = str(text or "").strip()
    if len(normalized) <= max_chars:
        return normalized
    if max_chars <= 3:
        return "." * max_chars
    return normalized[: max_chars - 3].rstrip() + "..."


def _context_id(knowledge_item_id: str, rank: int) -> str:
    digest = hashlib.sha1(f"{knowledge_item_id}:{rank}".encode("utf-8")).hexdigest()[:12]
    return f"ctx-{digest}"


def _retrieval_policy(provider: str) -> dict[str, Any]:
    return {
        "provider": str(provider or "local").strip().lower() or "local",
        "honorsKnowledgeAcl": True,
        "honorsMemoryPolicy": True,
        "mutatesFormalKnowledge": False,
        "injectsPromptByDefault": False,
    }


def _clamp_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))
