# -*- coding: utf-8 -*-
"""Agent-facing tools for team-scoped knowledge bases."""

from __future__ import annotations

import json
from typing import Any

from core.chat.chat_task_types import trim_lines


KNOWLEDGE_QUERY_TOOL_NAME = "knowledge_query_tool"
KNOWLEDGE_PROPOSAL_TOOL_NAME = "knowledge_proposal_tool"
KNOWLEDGE_INGESTION_TOOL_NAME = "knowledge_ingestion_tool"
KNOWLEDGE_GOVERNANCE_TASKS_TOOL_NAME = "knowledge_governance_tasks_tool"
KNOWLEDGE_OPERATIONS_HEALTH_TOOL_NAME = "knowledge_operations_health_tool"
KNOWLEDGE_GOVERNANCE_PLAN_TOOL_NAME = "knowledge_governance_plan_tool"
KNOWLEDGE_STEWARD_RECOMMENDATIONS_TOOL_NAME = "knowledge_steward_recommendations_tool"
KNOWLEDGE_STEWARD_WORKBENCH_TOOL_NAME = "knowledge_steward_workbench_tool"
KNOWLEDGE_RATING_SUGGESTION_TOOL_NAME = "knowledge_rating_suggestion_tool"
KNOWLEDGE_RAG_RETRIEVE_TOOL_NAME = "knowledge_rag_retrieve_tool"
UNIFIED_KNOWLEDGE_SEARCH_TOOL_NAME = "unified_knowledge_search_tool"


def unified_knowledge_search_tool(
    query: str = "",
    query_mode: str = "auto",
    knowledge_base_id: str = "",
    owner_type: str = "",
    owner_id: str = "",
    tags: str = "",
    limit: int = 8,
    max_context_chars: int = 1200,
) -> str:
    """
    Search governed formal knowledge through one read-only Agent-facing tool.

    The Agent chooses query_mode and query text; the platform routes the search
    to the current local knowledge, metadata, regex, or RAG backend and returns
    a stable result schema with citations/source ids.
    """

    runtime = _current_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()
    requested_base_id = str(knowledge_base_id or "").strip()
    memory_policy = runtime.get("memoryPolicy") if isinstance(runtime.get("memoryPolicy"), dict) else {}
    allowed_base_ids = _policy_ids(memory_policy, "readKnowledgeBaseIds")
    if requested_base_id and not _policy_allows_knowledge_base(requested_base_id, allowed_base_ids):
        return _json_result(_blocked_result(agent_id, "knowledge_base_not_in_memory_policy"))

    try:
        from core.web.services import unified_knowledge_search_service

        payload = unified_knowledge_search_service.search_unified_knowledge(
            agent_id=agent_id,
            query=trim_lines(str(query or ""), max_lines=4).strip(),
            query_mode=query_mode,
            owner_type=str(owner_type or "").strip(),
            owner_id=str(owner_id or "").strip(),
            knowledge_base_id=requested_base_id,
            tags=_split_tags(tags),
            allowed_knowledge_base_ids=allowed_base_ids,
            limit=limit,
            max_context_chars=max_context_chars,
        )
        _record_event(
            "knowledge.tool.unified_search.succeeded",
            runtime=runtime,
            outcome="succeeded",
            fields={
                "knowledgeBaseId": requested_base_id,
                "queryLength": int((payload.get("request") or {}).get("queryLength") or 0),
                "queryMode": str((payload.get("request") or {}).get("effectiveQueryMode") or query_mode),
                "backend": str((payload.get("request") or {}).get("backend") or ""),
                "resultCount": int((payload.get("summary") or {}).get("resultCount") or 0),
            },
        )
        return _json_result({"ok": True, "status": "succeeded", **payload})
    except Exception as exc:
        _record_event(
            "knowledge.tool.unified_search.failed",
            runtime=runtime,
            level="error",
            outcome="failed",
            fields={"knowledgeBaseId": requested_base_id, "errorType": type(exc).__name__},
        )
        return _json_result(
            {
                "ok": False,
                "status": "failed",
                "error": type(exc).__name__,
                "message": trim_lines(str(exc), max_lines=2),
                "agentId": agent_id,
                "knowledgeBaseId": requested_base_id,
            }
        )


def knowledge_query_tool(query: str = "", knowledge_base_id: str = "", limit: int = 8) -> str:
    """
    Read formal team knowledge items the current Agent is allowed to access.

    The tool is read-only. It returns reviewed knowledge items only; source
    artifacts and pending refinement proposals stay behind the review workflow.
    """

    runtime = _current_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()
    normalized_limit = _clamp_limit(limit)
    normalized_query = trim_lines(str(query or ""), max_lines=4).strip().lower()
    requested_base_id = str(knowledge_base_id or "").strip()
    memory_policy = runtime.get("memoryPolicy") if isinstance(runtime.get("memoryPolicy"), dict) else {}
    allowed_base_ids = _policy_ids(memory_policy, "readKnowledgeBaseIds")
    if requested_base_id and not _policy_allows_knowledge_base(requested_base_id, allowed_base_ids):
        return _json_result(_blocked_result(agent_id, "knowledge_base_not_in_memory_policy"))

    try:
        from core.web.services import team_knowledge_service

        payload = team_knowledge_service.search_knowledge_items(
            agent_id=agent_id,
            query=normalized_query,
            knowledge_base_id=requested_base_id,
            limit=normalized_limit,
        )
        results = list(payload.get("results") or [])
        _record_event(
            "knowledge.tool.query.succeeded",
            runtime=runtime,
            outcome="succeeded",
            fields={
                "knowledgeBaseId": requested_base_id,
                "queryLength": len(normalized_query),
                "resultCount": len(results),
                "limit": normalized_limit,
            },
        )
        return _json_result(
            {
                "ok": True,
                "status": "succeeded",
                "agentId": agent_id,
                "knowledgeBaseId": requested_base_id,
                "query": normalized_query,
                "limit": normalized_limit,
                "summary": payload.get("summary") or {"resultCount": len(results)},
                "results": results,
            }
        )
    except Exception as exc:
        _record_event(
            "knowledge.tool.query.failed",
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


def knowledge_rag_retrieve_tool(
    query: str = "",
    knowledge_base_id: str = "",
    owner_type: str = "",
    owner_id: str = "",
    retrieval_mode: str = "hybrid",
    provider: str = "local",
    top_k: int = 5,
    max_context_chars: int = 1200,
) -> str:
    """
    Retrieve compact, cited RAG context candidates from formal Team Knowledge.

    The tool is read-only. It does not mutate formal knowledge and does not
    inject retrieved content into prompts by default.
    """

    runtime = _current_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()
    requested_base_id = str(knowledge_base_id or "").strip()
    memory_policy = runtime.get("memoryPolicy") if isinstance(runtime.get("memoryPolicy"), dict) else {}
    allowed_base_ids = _policy_ids(memory_policy, "readKnowledgeBaseIds")
    if requested_base_id and not _policy_allows_knowledge_base(requested_base_id, allowed_base_ids):
        return _json_result(_blocked_result(agent_id, "knowledge_base_not_in_memory_policy"))

    try:
        from core.web.services import rag_retrieval_service

        payload = rag_retrieval_service.retrieve_rag_contexts(
            agent_id=agent_id,
            query=trim_lines(str(query or ""), max_lines=4).strip(),
            owner_type=str(owner_type or "").strip(),
            owner_id=str(owner_id or "").strip(),
            knowledge_base_id=requested_base_id,
            retrieval_mode=retrieval_mode,
            provider=provider,
            top_k=top_k,
            max_context_chars=max_context_chars,
        )
        contexts = list(payload.get("contexts") or [])
        citations = list(payload.get("citations") or [])
        _record_event(
            "knowledge.tool.rag_retrieve.succeeded",
            runtime=runtime,
            outcome="succeeded",
            fields={
                "knowledgeBaseId": requested_base_id,
                "queryLength": len(trim_lines(str(query or ""), max_lines=4).strip()),
                "contextCount": len(contexts),
                "citationCount": len(citations),
                "retrievalMode": str((payload.get("request") or {}).get("retrievalMode") or retrieval_mode),
                "provider": str((payload.get("request") or {}).get("provider") or provider),
            },
        )
        return _json_result(
            {
                "ok": True,
                "status": "succeeded",
                "agentId": agent_id,
                "knowledgeBaseId": requested_base_id,
                "summary": payload.get("summary") or {"contextCount": len(contexts), "citationCount": len(citations)},
                "contexts": contexts,
                "citations": citations,
                "retrievalPolicy": payload.get("retrievalPolicy") or {},
                "request": payload.get("request") or {},
            }
        )
    except Exception as exc:
        _record_event(
            "knowledge.tool.rag_retrieve.failed",
            runtime=runtime,
            level="error",
            outcome="failed",
            fields={"knowledgeBaseId": requested_base_id, "errorType": type(exc).__name__},
        )
        return _json_result(
            {
                "ok": False,
                "status": "failed",
                "error": type(exc).__name__,
                "message": trim_lines(str(exc), max_lines=2),
                "agentId": agent_id,
                "knowledgeBaseId": requested_base_id,
            }
        )


def knowledge_proposal_tool(
    knowledge_base_id: str,
    source_type: str,
    source_ref_json: str,
    proposal_title: str,
    proposal_content: str,
    central_source_id: str = "",
    source_title: str = "",
    source_summary: str = "",
    proposal_summary: str = "",
    tags: str = "",
    evidence_range_json: str = "{}",
    source_created_at: str = "",
    captured_by: str = "",
) -> str:
    """
    Attach one central-curated source artifact and submit one refinement proposal.

    This tool cannot create formal knowledge directly. Reviewers must apply the
    proposal through the team knowledge review flow before it becomes an item.
    Raw sources must be collected through the owner source inbox first. The
    central source is the source of truth for SourceArtifact provenance; caller
    source_type must match that source, and caller source_ref does not become
    formal provenance.
    """

    runtime = _current_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()
    base_id = str(knowledge_base_id or "").strip()
    memory_policy = runtime.get("memoryPolicy") if isinstance(runtime.get("memoryPolicy"), dict) else {}
    allowed_base_ids = _policy_ids(memory_policy, "proposeKnowledgeBaseIds")
    if base_id and not _policy_allows_knowledge_base(base_id, allowed_base_ids):
        return _json_result(_blocked_result(agent_id, "knowledge_base_not_in_memory_policy"))
    source_ref = _parse_json_object(source_ref_json, "source_ref_json")
    if isinstance(source_ref, str):
        return _json_result(_invalid_json_result(agent_id, source_ref))
    evidence_range = _parse_json_object(evidence_range_json, "evidence_range_json")
    if isinstance(evidence_range, str):
        return _json_result(_invalid_json_result(agent_id, evidence_range))

    try:
        from core.web.services import team_knowledge_service

        source = team_knowledge_service.create_source_artifact(
            base_id,
            source_type=source_type,
            source_ref=source_ref,
            source_created_at=source_created_at,
            captured_by=captured_by or agent_id,
            evidence_range=evidence_range,
            title=source_title,
            summary=source_summary,
            actor_agent_id=agent_id,
            central_source_id=central_source_id,
        )
        proposal = team_knowledge_service.create_refinement_proposal(
            base_id,
            source_artifact_ids=[str(source.get("sourceArtifactId") or "")],
            proposed_by_agent_id=agent_id,
            title=proposal_title,
            summary=proposal_summary,
            content=proposal_content,
            tags=_split_tags(tags),
        )
        _record_event(
            "knowledge.tool.proposal.submitted",
            runtime=runtime,
            outcome="succeeded",
            fields={
                "knowledgeBaseId": base_id,
                "sourceArtifactId": source.get("sourceArtifactId") or "",
                "centralSourceId": source.get("centralSourceId") or "",
                "proposalId": proposal.get("proposalId") or "",
                "sourceType": source.get("sourceType") or "",
            },
        )
        return _json_result(
            {
                "ok": True,
                "status": "submitted",
                "agentId": agent_id,
                "knowledgeBaseId": base_id,
                "sourceArtifact": source,
                "proposal": proposal,
            }
        )
    except Exception as exc:
        _record_event(
            "knowledge.tool.proposal.failed",
            runtime=runtime,
            level="error",
            outcome="failed",
            fields={"knowledgeBaseId": base_id, "errorType": type(exc).__name__},
        )
        return _json_result(
            {
                "ok": False,
                "status": "failed",
                "error": type(exc).__name__,
                "message": trim_lines(str(exc), max_lines=2),
                "agentId": agent_id,
                "knowledgeBaseId": base_id,
            }
        )


def knowledge_ingestion_tool(
    knowledge_base_id: str,
    source_type: str,
    source_ref_json: str,
    proposal_title: str,
    excerpt: str = "",
    proposal_content: str = "",
    central_source_id: str = "",
    source_title: str = "",
    source_summary: str = "",
    proposal_summary: str = "",
    tags: str = "",
    evidence_range_json: str = "{}",
    source_created_at: str = "",
) -> str:
    """
    Submit a standard semi-automatic ingestion package from a central source.

    The tool only creates a central-curated SourceArtifact + pending
    RefinementProposal. It does not parse files, search the web, collect raw
    sources, or create formal KnowledgeItems. The central source is the source
    of truth for SourceArtifact provenance.
    """

    runtime = _current_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()
    base_id = str(knowledge_base_id or "").strip()
    memory_policy = runtime.get("memoryPolicy") if isinstance(runtime.get("memoryPolicy"), dict) else {}
    allowed_base_ids = _policy_ids(memory_policy, "proposeKnowledgeBaseIds")
    if base_id and not _policy_allows_knowledge_base(base_id, allowed_base_ids):
        return _json_result(_blocked_result(agent_id, "knowledge_base_not_in_memory_policy"))
    source_ref = _parse_json_object(source_ref_json, "source_ref_json")
    if isinstance(source_ref, str):
        return _json_result(_invalid_json_result(agent_id, source_ref))
    evidence_range = _parse_json_object(evidence_range_json, "evidence_range_json")
    if isinstance(evidence_range, str):
        return _json_result(_invalid_json_result(agent_id, evidence_range))
    try:
        from core.web.services import team_knowledge_service

        package = team_knowledge_service.create_ingestion_package(
            base_id,
            source_type=source_type,
            source_ref=source_ref,
            source_created_at=source_created_at,
            captured_by=agent_id,
            evidence_range=evidence_range,
            source_title=source_title,
            source_summary=source_summary,
            excerpt=excerpt,
            proposed_by_agent_id=agent_id,
            central_source_id=central_source_id,
            proposal_title=proposal_title,
            proposal_summary=proposal_summary,
            proposal_content=proposal_content,
            tags=_split_tags(tags),
        )
        _record_event(
            "knowledge.tool.ingestion.submitted",
            runtime=runtime,
            outcome="succeeded",
            fields={
                "knowledgeBaseId": base_id,
                "sourceType": source_type,
                "sourceArtifactId": (package.get("sourceArtifact") or {}).get("sourceArtifactId") or "",
                "centralSourceId": (package.get("sourceArtifact") or {}).get("centralSourceId") or "",
                "proposalId": (package.get("proposal") or {}).get("proposalId") or "",
            },
        )
        return _json_result({"ok": True, "status": "submitted", "agentId": agent_id, "package": package})
    except Exception as exc:
        _record_event(
            "knowledge.tool.ingestion.failed",
            runtime=runtime,
            level="error",
            outcome="failed",
            fields={"knowledgeBaseId": base_id, "errorType": type(exc).__name__},
        )
        return _json_result(
            {
                "ok": False,
                "status": "failed",
                "error": type(exc).__name__,
                "message": trim_lines(str(exc), max_lines=2),
                "agentId": agent_id,
                "knowledgeBaseId": base_id,
            }
        )


def knowledge_governance_tasks_tool(status: str = "open") -> str:
    """Read the current Agent's team knowledge governance task queue."""

    runtime = _current_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()
    try:
        from core.web.services import team_knowledge_service

        payload = team_knowledge_service.list_knowledge_governance_tasks(agent_id=agent_id, status=status)
        _record_event(
            "knowledge.tool.governance_tasks.queried",
            runtime=runtime,
            outcome="succeeded",
            fields={"status": status, "taskCount": (payload.get("summary") or {}).get("taskCount", 0)},
        )
        return _json_result({"ok": True, "status": "succeeded", "agentId": agent_id, **payload})
    except Exception as exc:
        _record_event(
            "knowledge.tool.governance_tasks.failed",
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


def knowledge_operations_health_tool() -> str:
    """Read operational health for accessible team knowledge bases."""

    runtime = _current_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()
    try:
        from core.web.services import team_knowledge_service

        payload = team_knowledge_service.get_knowledge_operations_health(agent_id=agent_id)
        _record_event(
            "knowledge.tool.operations_health.queried",
            runtime=runtime,
            outcome="succeeded",
            fields={
                "knowledgeBaseCount": (payload.get("summary") or {}).get("knowledgeBaseCount", 0),
                "findingCount": (payload.get("summary") or {}).get("findingCount", 0),
            },
        )
        return _json_result({"ok": True, "status": "succeeded", "agentId": agent_id, **payload})
    except Exception as exc:
        _record_event(
            "knowledge.tool.operations_health.failed",
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


def knowledge_governance_plan_tool(limit: int = 8) -> str:
    """Read a read-only governance plan for accessible team knowledge bases."""

    runtime = _current_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()
    try:
        from core.web.services import team_knowledge_service

        payload = team_knowledge_service.get_knowledge_governance_plan(agent_id=agent_id, limit=limit)
        _record_event(
            "knowledge.tool.governance_plan.queried",
            runtime=runtime,
            outcome="succeeded",
            fields={
                "actionCount": (payload.get("summary") or {}).get("actionCount", 0),
                "healthFindingCount": (payload.get("summary") or {}).get("healthFindingCount", 0),
            },
        )
        return _json_result({"ok": True, "status": "succeeded", "agentId": agent_id, **payload})
    except Exception as exc:
        _record_event(
            "knowledge.tool.governance_plan.failed",
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


def knowledge_steward_recommendations_tool(limit: int = 8) -> str:
    """Read the current Agent's Knowledge Steward governance recommendations."""

    runtime = _current_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()
    try:
        from core.web.services import team_knowledge_service

        payload = team_knowledge_service.list_knowledge_steward_recommendations(agent_id=agent_id, limit=limit)
        _record_event(
            "knowledge.tool.steward_recommendations.queried",
            runtime=runtime,
            outcome="succeeded",
            fields={
                "recommendationCount": (payload.get("summary") or {}).get("recommendationCount", 0),
                "visibleRecommendationCount": (payload.get("summary") or {}).get("visibleRecommendationCount", 0),
            },
        )
        return _json_result({"ok": True, "status": "succeeded", "agentId": agent_id, **payload})
    except Exception as exc:
        _record_event(
            "knowledge.tool.steward_recommendations.failed",
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


def knowledge_steward_workbench_tool(limit: int = 8) -> str:
    """Read the current Agent's consolidated Knowledge Steward workbench."""

    runtime = _current_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()
    try:
        from core.web.services import team_knowledge_service

        payload = team_knowledge_service.get_knowledge_steward_workbench(agent_id=agent_id, limit=limit)
        _record_event(
            "knowledge.tool.steward_workbench.queried",
            runtime=runtime,
            outcome="succeeded",
            fields={
                "openTaskCount": (payload.get("summary") or {}).get("openTaskCount", 0),
                "recommendationCount": (payload.get("summary") or {}).get("recommendationCount", 0),
                "stageCount": (payload.get("summary") or {}).get("stageCount", 0),
            },
        )
        return _json_result({"ok": True, "status": "succeeded", "agentId": agent_id, **payload})
    except Exception as exc:
        _record_event(
            "knowledge.tool.steward_workbench.failed",
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


def knowledge_rating_suggestion_tool(
    knowledge_base_id: str,
    target_type: str,
    importance_level: str,
    stability: str,
    review_priority: str,
    marking_reason: str,
    knowledge_item_id: str = "",
    proposal_id: str = "",
    confidence: float = 0.7,
) -> str:
    """
    Submit a reviewable rating suggestion for a proposal or formal item.

    The tool never applies a rating directly. A reviewer must review/apply the
    suggestion before a KnowledgeItem is updated.
    """

    runtime = _current_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()
    base_id = str(knowledge_base_id or "").strip()
    memory_policy = runtime.get("memoryPolicy") if isinstance(runtime.get("memoryPolicy"), dict) else {}
    allowed_base_ids = _policy_ids(memory_policy, "rateKnowledgeBaseIds") or _policy_ids(memory_policy, "reviewKnowledgeBaseIds")
    if base_id and not _policy_allows_knowledge_base(base_id, allowed_base_ids):
        return _json_result(_blocked_result(agent_id, "knowledge_base_not_in_memory_policy"))
    try:
        from core.web.services import team_knowledge_service

        suggestion = team_knowledge_service.create_rating_suggestion(
            base_id,
            suggested_by_agent_id=agent_id,
            target_type=target_type,
            knowledge_item_id=knowledge_item_id,
            proposal_id=proposal_id,
            importance_level=importance_level,
            confidence=confidence,
            stability=stability,
            review_priority=review_priority,
            marking_reason=marking_reason,
        )
        _record_event(
            "knowledge.tool.rating_suggestion.submitted",
            runtime=runtime,
            outcome="succeeded",
            fields={
                "knowledgeBaseId": base_id,
                "suggestionId": suggestion.get("suggestionId") or "",
                "targetType": suggestion.get("targetType") or "",
            },
        )
        return _json_result(
            {
                "ok": True,
                "status": "submitted",
                "agentId": agent_id,
                "knowledgeBaseId": base_id,
                "suggestion": suggestion,
            }
        )
    except Exception as exc:
        _record_event(
            "knowledge.tool.rating_suggestion.failed",
            runtime=runtime,
            level="error",
            outcome="failed",
            fields={"knowledgeBaseId": base_id, "errorType": type(exc).__name__},
        )
        return _json_result(
            {
                "ok": False,
                "status": "failed",
                "error": type(exc).__name__,
                "message": trim_lines(str(exc), max_lines=2),
                "agentId": agent_id,
                "knowledgeBaseId": base_id,
            }
        )


def _blocked_result(agent_id: str, reason: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "blocked",
        "error": reason,
        "message": "Team knowledge access is limited by MemoryPolicy and team access.",
        "agentId": agent_id,
    }


def _invalid_json_result(agent_id: str, field: str) -> dict[str, Any]:
    return {"ok": False, "status": "failed", "error": "invalid_json", "field": field, "agentId": agent_id}


def _parse_json_object(value: str, field: str) -> dict[str, Any] | str:
    text = str(value or "").strip() or "{}"
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return field
    return payload if isinstance(payload, dict) else field


def _policy_ids(policy: dict[str, Any], field: str) -> set[str]:
    return {str(item or "").strip() for item in policy.get(field) or [] if str(item or "").strip()}


def _policy_allows_knowledge_base(knowledge_base_id: str, allowed_base_ids: set[str]) -> bool:
    if not allowed_base_ids:
        return True
    try:
        from core.web.services import team_knowledge_service

        return team_knowledge_service.knowledge_base_policy_allows(knowledge_base_id, allowed_base_ids)
    except Exception:
        return str(knowledge_base_id or "").strip() in allowed_base_ids


def _split_tags(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").replace("，", ",").split(",") if item.strip()][:24]


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


def _record_event(
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
            "team_knowledge",
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
