# -*- coding: utf-8 -*-
"""Agent-facing read-only tools for the research knowledge base."""

from __future__ import annotations

import json
from typing import Any

from core.chat.chat_task_types import trim_lines


RESEARCH_KNOWLEDGE_QUERY_TOOL_NAME = "research_knowledge_query_tool"
_ALLOWED_COLLECTIONS = {"all", "entries", "claims", "evidence", "gaps"}
_ALLOWED_KINDS = {"", "paper", "github", "dataset", "web"}


def research_knowledge_query_tool(
    query: str = "",
    collection: str = "all",
    kind: str = "",
    category: str = "",
    limit: int = 8,
) -> str:
    """
    Query the persistent research knowledge base for sources, claims, evidence, and gaps.

    Args:
        query: Keyword or phrase to search in titles, summaries, tags, claims, evidence, and gaps.
        collection: Which collection to return: all, entries, claims, evidence, or gaps.
        kind: Optional source kind filter for entries: paper, github, dataset, or web.
        category: Optional category filter for entries, such as literature, dataset, open_source, or web_background.
        limit: Maximum items per collection, clamped to 1-25.

    Returns:
        JSON result with matching research knowledge records. The tool is read-only.
    """

    runtime = _current_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()

    normalized_collection = str(collection or "all").strip().lower() or "all"
    if normalized_collection not in _ALLOWED_COLLECTIONS:
        normalized_collection = "all"
    normalized_kind = str(kind or "").strip().lower()
    if normalized_kind not in _ALLOWED_KINDS:
        normalized_kind = ""
    normalized_category = str(category or "").strip().lower()
    normalized_query = trim_lines(str(query or ""), max_lines=4).strip()
    normalized_limit = _clamp_limit(limit)

    try:
        from core.research.knowledge_base import ResearchKnowledgeBase

        payload = ResearchKnowledgeBase().payload(
            query=normalized_query,
            kind=normalized_kind,
            category=normalized_category,
            limit=normalized_limit,
        )
        result = {
            "ok": True,
            "status": "succeeded",
            "agentId": agent_id,
            "path": payload.get("path") or "",
            "query": normalized_query,
            "collection": normalized_collection,
            "kind": normalized_kind,
            "category": normalized_category,
            "limit": normalized_limit,
            "summary": payload.get("summary") if isinstance(payload.get("summary"), dict) else {},
            "results": _select_results(payload, collection=normalized_collection, limit=normalized_limit),
        }
        _record_query_event(
            "research_knowledge.query.succeeded",
            runtime=runtime,
            outcome="succeeded",
            fields={
                "collection": normalized_collection,
                "kind": normalized_kind,
                "category": normalized_category,
                "limit": normalized_limit,
                "queryLength": len(normalized_query),
                "resultCounts": _result_counts(result["results"]),
            },
        )
        return _json_result(result)
    except Exception as exc:
        _record_query_event(
            "research_knowledge.query.failed",
            runtime=runtime,
            level="error",
            outcome="failed",
            fields={"errorType": type(exc).__name__},
        )
        return _json_result(
            {
                "ok": False,
                "status": "failed",
                "error": type(exc).__name__,
                "message": trim_lines(str(exc), max_lines=2),
                "agentId": agent_id,
            }
        )


def _select_results(payload: dict[str, Any], *, collection: str, limit: int) -> dict[str, list[dict[str, Any]]]:
    if collection == "entries":
        return {"entries": [_entry_view(item) for item in list(payload.get("entries") or [])[:limit] if isinstance(item, dict)]}
    if collection == "claims":
        return {"claims": [_record_view(item) for item in list(payload.get("claims") or [])[:limit] if isinstance(item, dict)]}
    if collection == "evidence":
        return {"evidence": [_record_view(item) for item in list(payload.get("evidence") or [])[:limit] if isinstance(item, dict)]}
    if collection == "gaps":
        return {"gaps": [_record_view(item) for item in list(payload.get("gaps") or [])[:limit] if isinstance(item, dict)]}
    return {
        "entries": [_entry_view(item) for item in list(payload.get("entries") or [])[:limit] if isinstance(item, dict)],
        "claims": [_record_view(item) for item in list(payload.get("claims") or [])[:limit] if isinstance(item, dict)],
        "evidence": [_record_view(item) for item in list(payload.get("evidence") or [])[:limit] if isinstance(item, dict)],
        "gaps": [_record_view(item) for item in list(payload.get("gaps") or [])[:limit] if isinstance(item, dict)],
    }


def _entry_view(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "entryId": str(item.get("entryId") or item.get("id") or item.get("key") or item.get("dedupeKey") or "").strip(),
        "kind": str(item.get("kind") or "").strip(),
        "title": trim_lines(str(item.get("title") or ""), max_lines=2),
        "url": str(item.get("url") or "").strip(),
        "summary": trim_lines(str(item.get("summary") or item.get("snippet") or ""), max_lines=4),
        "tags": [str(value) for value in list(item.get("tags") or [])[:8] if str(value or "").strip()],
        "categories": [str(value) for value in list(item.get("categories") or [])[:6] if str(value or "").strip()],
        "sourceIds": [str(value) for value in list(item.get("sourceIds") or [])[:8] if str(value or "").strip()],
        "lastSeenAt": str(item.get("lastSeenAt") or "").strip(),
    }


def _record_view(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "recordId": str(item.get("recordId") or item.get("id") or item.get("key") or item.get("dedupeKey") or "").strip(),
        "type": str(item.get("type") or item.get("recordType") or "").strip(),
        "content": trim_lines(str(item.get("content") or item.get("summary") or ""), max_lines=4),
        "status": str(item.get("status") or "").strip(),
        "tags": [str(value) for value in list(item.get("tags") or [])[:8] if str(value or "").strip()],
        "sourceIds": [str(value) for value in list(item.get("sourceIds") or [])[:8] if str(value or "").strip()],
        "createdAt": str(item.get("createdAt") or "").strip(),
    }


def _result_counts(results: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    return {key: len(value) for key, value in results.items()}


def _clamp_limit(value: Any) -> int:
    try:
        limit = int(value or 8)
    except (TypeError, ValueError):
        limit = 8
    return max(1, min(25, limit))


def _current_runtime() -> dict[str, Any]:
    try:
        from core.web.services.agent_directory_service import current_agent_runtime

        runtime = current_agent_runtime()
        return runtime if isinstance(runtime, dict) else {}
    except Exception:
        return {}


def _record_query_event(
    event_code: str,
    *,
    runtime: dict[str, Any],
    level: str = "info",
    outcome: str = "observed",
    fields: dict[str, Any] | None = None,
) -> None:
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        record_runtime_scene_event(
            "research_knowledge",
            "tool",
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields={
                "agentId": str(runtime.get("agentId") or "").strip(),
                "sessionId": str(runtime.get("sessionId") or "").strip(),
                **dict(fields or {}),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _json_result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
