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
KNOWLEDGE_RATING_SUGGESTION_TOOL_NAME = "knowledge_rating_suggestion_tool"


def knowledge_query_tool(query: str = "", knowledge_base_id: str = "", limit: int = 8) -> str:
    """
    Read formal team knowledge items the current Agent is allowed to access.

    The tool is read-only. It returns reviewed knowledge items only; source
    artifacts and pending refinement proposals stay behind the review workflow.
    """

    runtime = _current_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()
    blocked = _tool_policy_blocked(runtime, KNOWLEDGE_QUERY_TOOL_NAME)
    if blocked:
        return _json_result(blocked)
    normalized_limit = _clamp_limit(limit)
    normalized_query = trim_lines(str(query or ""), max_lines=4).strip().lower()
    requested_base_id = str(knowledge_base_id or "").strip()
    memory_policy = runtime.get("memoryPolicy") if isinstance(runtime.get("memoryPolicy"), dict) else {}
    allowed_base_ids = _policy_ids(memory_policy, "readKnowledgeBaseIds")
    if requested_base_id and allowed_base_ids and requested_base_id not in allowed_base_ids:
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


def knowledge_proposal_tool(
    knowledge_base_id: str,
    source_type: str,
    source_ref_json: str,
    proposal_title: str,
    proposal_content: str,
    source_title: str = "",
    source_summary: str = "",
    proposal_summary: str = "",
    tags: str = "",
    evidence_range_json: str = "{}",
    source_created_at: str = "",
    captured_by: str = "",
) -> str:
    """
    Register one source artifact and submit one refinement proposal.

    This tool cannot create formal knowledge directly. Reviewers must apply the
    proposal through the team knowledge review flow before it becomes an item.
    """

    runtime = _current_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()
    blocked = _tool_policy_blocked(runtime, KNOWLEDGE_PROPOSAL_TOOL_NAME)
    if blocked:
        return _json_result(blocked)
    base_id = str(knowledge_base_id or "").strip()
    memory_policy = runtime.get("memoryPolicy") if isinstance(runtime.get("memoryPolicy"), dict) else {}
    allowed_base_ids = _policy_ids(memory_policy, "proposeKnowledgeBaseIds")
    if base_id and allowed_base_ids and base_id not in allowed_base_ids:
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
    source_title: str = "",
    source_summary: str = "",
    proposal_summary: str = "",
    tags: str = "",
    evidence_range_json: str = "{}",
    source_created_at: str = "",
) -> str:
    """
    Submit a standard semi-automatic ingestion package.

    The tool only creates SourceArtifact + pending RefinementProposal. It does
    not parse files, search the web, or create formal KnowledgeItems.
    """

    runtime = _current_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()
    blocked = _tool_policy_blocked(runtime, KNOWLEDGE_INGESTION_TOOL_NAME)
    if blocked:
        return _json_result(blocked)
    base_id = str(knowledge_base_id or "").strip()
    memory_policy = runtime.get("memoryPolicy") if isinstance(runtime.get("memoryPolicy"), dict) else {}
    allowed_base_ids = _policy_ids(memory_policy, "proposeKnowledgeBaseIds")
    if base_id and allowed_base_ids and base_id not in allowed_base_ids:
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
    blocked = _tool_policy_blocked(runtime, KNOWLEDGE_GOVERNANCE_TASKS_TOOL_NAME)
    if blocked:
        return _json_result(blocked)
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
    blocked = _tool_policy_blocked(runtime, KNOWLEDGE_RATING_SUGGESTION_TOOL_NAME)
    if blocked:
        return _json_result(blocked)
    base_id = str(knowledge_base_id or "").strip()
    memory_policy = runtime.get("memoryPolicy") if isinstance(runtime.get("memoryPolicy"), dict) else {}
    allowed_base_ids = _policy_ids(memory_policy, "rateKnowledgeBaseIds") or _policy_ids(memory_policy, "reviewKnowledgeBaseIds")
    if base_id and allowed_base_ids and base_id not in allowed_base_ids:
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


def _tool_policy_blocked(runtime: dict[str, Any], tool_name: str) -> dict[str, Any] | None:
    policy = runtime.get("toolPolicy") if isinstance(runtime.get("toolPolicy"), dict) else {}
    allowed = {str(item or "").strip() for item in policy.get("allowedTools") or [] if str(item or "").strip()}
    blocked = {str(item or "").strip() for item in policy.get("blockedTools") or [] if str(item or "").strip()}
    if tool_name not in allowed or tool_name in blocked:
        return _blocked_result(str(runtime.get("agentId") or "").strip(), "tool_not_explicitly_allowed")
    return None


def _blocked_result(agent_id: str, reason: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "blocked",
        "error": reason,
        "message": "Team knowledge tools require explicit ToolPolicy and MemoryPolicy/team access.",
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
