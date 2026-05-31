# -*- coding: utf-8 -*-
"""Agent-facing tools for team-scoped knowledge bases."""

from __future__ import annotations

import json
from typing import Any

from core.chat.chat_task_types import trim_lines


KNOWLEDGE_QUERY_TOOL_NAME = "knowledge_query_tool"
KNOWLEDGE_PROPOSAL_TOOL_NAME = "knowledge_proposal_tool"


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

        overview = team_knowledge_service.list_knowledge_overview(agent_id=agent_id)
        bases = [
            base
            for base in list(overview.get("knowledgeBases") or [])
            if isinstance(base, dict)
            and (not requested_base_id or str(base.get("knowledgeBaseId") or "") == requested_base_id)
            and (not allowed_base_ids or str(base.get("knowledgeBaseId") or "") in allowed_base_ids)
        ]
        results: list[dict[str, Any]] = []
        for base in bases:
            base_id = str(base.get("knowledgeBaseId") or "").strip()
            if not base_id:
                continue
            payload = team_knowledge_service.list_knowledge_items(base_id, agent_id=agent_id)
            for item in list(payload.get("items") or []):
                if not isinstance(item, dict) or not _matches_query(item, normalized_query):
                    continue
                results.append(_item_view(item, base))
                if len(results) >= normalized_limit:
                    break
            if len(results) >= normalized_limit:
                break
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
                "summary": {"knowledgeBaseCount": len(bases), "resultCount": len(results)},
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


def _matches_query(item: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    haystack = " ".join(
        [
            str(item.get("title") or ""),
            str(item.get("summary") or ""),
            str(item.get("content") or ""),
            " ".join(str(tag) for tag in list(item.get("tags") or [])),
        ]
    ).lower()
    return query in haystack


def _item_view(item: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    return {
        "knowledgeItemId": str(item.get("knowledgeItemId") or "").strip(),
        "knowledgeBaseId": str(item.get("knowledgeBaseId") or base.get("knowledgeBaseId") or "").strip(),
        "knowledgeBaseName": str(base.get("name") or "").strip(),
        "teamId": str(base.get("teamId") or "").strip(),
        "teamName": str(base.get("teamName") or "").strip(),
        "batchId": str(item.get("batchId") or "").strip(),
        "sourceArtifactIds": [str(value) for value in list(item.get("sourceArtifactIds") or [])[:12] if str(value or "").strip()],
        "title": trim_lines(str(item.get("title") or ""), max_lines=2),
        "summary": trim_lines(str(item.get("summary") or ""), max_lines=4),
        "content": trim_lines(str(item.get("content") or ""), max_lines=12),
        "tags": [str(value) for value in list(item.get("tags") or [])[:12] if str(value or "").strip()],
        "importanceLevel": str(item.get("importanceLevel") or "").strip(),
        "confidence": item.get("confidence"),
        "stability": str(item.get("stability") or "").strip(),
        "scope": str(item.get("scope") or "").strip(),
        "reviewPriority": str(item.get("reviewPriority") or "").strip(),
        "appliedAt": str(item.get("appliedAt") or "").strip(),
        "updatedAt": str(item.get("updatedAt") or "").strip(),
    }


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
