# -*- coding: utf-8 -*-
"""Agent-facing tools for team-scoped knowledge bases."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from core.chat.chat_task_types import trim_lines


UNIFIED_MEMORY_SEARCH_TOOL_NAME = "unified_memory_search_tool"
AGENT_PRIVATE_MEMORY_SEARCH_TOOL_NAME = "search_agent_private_memory_tool"
SESSION_ATTACHMENT_STAGE_TOOL_NAME = "knowledge_stage_session_attachment_tool"
KNOWLEDGE_PROPOSAL_TOOL_NAME = "knowledge_proposal_tool"
KNOWLEDGE_PROPOSAL_REVIEW_TOOL_NAME = "knowledge_proposal_review_tool"
KNOWLEDGE_INGESTION_TOOL_NAME = "knowledge_ingestion_tool"
KNOWLEDGE_GOVERNANCE_TASKS_TOOL_NAME = "knowledge_governance_tasks_tool"
KNOWLEDGE_OPERATIONS_HEALTH_TOOL_NAME = "knowledge_operations_health_tool"
KNOWLEDGE_GOVERNANCE_PLAN_TOOL_NAME = "knowledge_governance_plan_tool"
KNOWLEDGE_STEWARD_RECOMMENDATIONS_TOOL_NAME = "knowledge_steward_recommendations_tool"
KNOWLEDGE_STEWARD_WORKBENCH_TOOL_NAME = "knowledge_steward_workbench_tool"
KNOWLEDGE_RATING_SUGGESTION_TOOL_NAME = "knowledge_rating_suggestion_tool"


def unified_memory_search_tool(
    query: str = "",
    query_mode: str = "auto",
    knowledge_base_id: str = "",
    owner_type: str = "",
    owner_id: str = "",
    research_project_id: str = "",
    question_id: str = "",
    source_collection_run_id: str = "",
    tags: str = "",
    limit: int = 8,
    max_context_chars: int = 1200,
    include_user_content: bool = False,
    user_content_space_ids: str = "",
) -> str:
    """
    Search governed Agent/Team memory and formal knowledge through one read-only Agent-facing tool.

    The Agent chooses query_mode and query text; supported query_mode values
    include auto, exact, semantic, hybrid, bm25, metadata, regex/rg/grep, and
    rag. The platform routes the search to the current local knowledge,
    metadata, regex, BM25, or RAG backend and returns a stable result schema
    with citations/source ids.
    """

    runtime = _current_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()
    requested_base_id = str(knowledge_base_id or "").strip()
    memory_policy = runtime.get("memoryPolicy") if isinstance(runtime.get("memoryPolicy"), dict) else {}
    allowed_base_ids = _policy_ids(memory_policy, "readKnowledgeBaseIds")
    requested_user_content_space_ids = _split_tags(user_content_space_ids)
    allowed_user_content_space_ids = _policy_ids(memory_policy, "readUserContentSpaceIds")
    if requested_base_id and not _policy_allows_knowledge_base(requested_base_id, allowed_base_ids):
        return _json_result(_blocked_result(agent_id, "knowledge_base_not_in_memory_policy"))
    if requested_user_content_space_ids and allowed_user_content_space_ids:
        denied = [space_id for space_id in requested_user_content_space_ids if space_id not in allowed_user_content_space_ids]
        if denied:
            return _json_result(_blocked_result(agent_id, "user_content_space_not_in_memory_policy"))

    try:
        from core.web.services import unified_knowledge_search_service

        payload = unified_knowledge_search_service.search_unified_memory(
            agent_id=agent_id,
            query=trim_lines(str(query or ""), max_lines=4).strip(),
            query_mode=query_mode,
            owner_type=str(owner_type or "").strip(),
            owner_id=str(owner_id or "").strip(),
            research_project_id=str(research_project_id or "").strip(),
            question_id=str(question_id or "").strip(),
            source_collection_run_id=str(source_collection_run_id or "").strip(),
            knowledge_base_id=requested_base_id,
            tags=_split_tags(tags),
            allowed_knowledge_base_ids=allowed_base_ids,
            include_user_content=bool(include_user_content),
            allowed_user_content_space_ids=requested_user_content_space_ids or allowed_user_content_space_ids,
            limit=limit,
            max_context_chars=max_context_chars,
        )
        _record_event(
            "memory.tool.unified_search.succeeded",
            runtime=runtime,
            outcome="succeeded",
            fields={
                "knowledgeBaseId": requested_base_id,
                "queryLength": int((payload.get("request") or {}).get("queryLength") or 0),
                "queryMode": str((payload.get("request") or {}).get("effectiveQueryMode") or query_mode),
                "backend": str((payload.get("request") or {}).get("backend") or ""),
                "resultCount": int((payload.get("summary") or {}).get("resultCount") or 0),
                "userContentResultCount": int((payload.get("summary") or {}).get("userContentResultCount") or 0),
            },
        )
        return _json_result({"ok": True, "status": "succeeded", **payload})
    except Exception as exc:
        _record_event(
            "memory.tool.unified_search.failed",
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


def search_agent_private_memory_tool(
    query: str = "",
    query_mode: str = "auto",
    limit: int = 8,
    max_context_chars: int = 1200,
) -> str:
    """Search reviewed formal knowledge in the current Agent's own private KBs only."""

    runtime = _current_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()
    if not agent_id:
        return _json_result(_blocked_result("", "agent_identity_required"))
    memory_policy = runtime.get("memoryPolicy") if isinstance(runtime.get("memoryPolicy"), dict) else {}
    if memory_policy.get("enabled") is False:
        return _json_result(_blocked_result(agent_id, "personal_memory_disabled"))

    try:
        from core.web.services import team_knowledge_service, unified_knowledge_search_service

        private_bases = team_knowledge_service.list_agent_knowledge_bases(
            agent_id,
            actor_agent_id=agent_id,
        )
        private_base_ids = [
            str(base.get("scopedKnowledgeBaseId") or "").strip()
            for base in list(private_bases.get("knowledgeBases") or [])
            if isinstance(base, dict)
            and str(base.get("ownerType") or "").strip() == "agent"
            and str(base.get("ownerId") or "").strip() == agent_id
            and str(base.get("status") or "active").strip() == "active"
            and bool((base.get("permissions") or {}).get("canRead"))
            and str(base.get("scopedKnowledgeBaseId") or "").strip()
        ]
        if not private_base_ids:
            payload = {
                "ok": True,
                "status": "empty",
                "agentId": agent_id,
                "message": "当前 Agent 没有可检索的私有正式知识库。",
                "summary": {"resultCount": 0, "citationCount": 0, "userContentResultCount": 0},
                "results": [],
                "citations": [],
            }
            _record_event(
                "memory.tool.private_search.empty",
                runtime=runtime,
                outcome="succeeded",
                fields={"knowledgeBaseCount": 0, "queryLength": len(trim_lines(str(query or ""), max_lines=4).strip())},
            )
            return _json_result(payload)

        payload = unified_knowledge_search_service.search_unified_memory(
            agent_id=agent_id,
            query=trim_lines(str(query or ""), max_lines=4).strip(),
            query_mode=query_mode,
            owner_type="agent",
            owner_id=agent_id,
            allowed_knowledge_base_ids=private_base_ids,
            include_user_content=False,
            allowed_user_content_space_ids=[],
            limit=limit,
            max_context_chars=max_context_chars,
        )
        _record_event(
            "memory.tool.private_search.succeeded",
            runtime=runtime,
            outcome="succeeded",
            fields={
                "knowledgeBaseCount": len(private_base_ids),
                "queryLength": int((payload.get("request") or {}).get("queryLength") or 0),
                "queryMode": str((payload.get("request") or {}).get("effectiveQueryMode") or query_mode),
                "resultCount": int((payload.get("summary") or {}).get("resultCount") or 0),
            },
        )
        return _json_result({"ok": True, "status": "succeeded", **payload})
    except Exception as exc:
        _record_event(
            "memory.tool.private_search.failed",
            runtime=runtime,
            level="error",
            outcome="failed",
            fields={"errorType": type(exc).__name__},
        )
        return _json_result(
            {
                "ok": False,
                "status": "failed",
                "error": "private_memory_search_failed",
                "message": "私有知识检索失败，请稍后重试或检查知识库状态。",
                "agentId": agent_id,
            }
        )


def knowledge_stage_session_attachment_tool(
    attachment_id: str,
    team_id: str = "",
    title: str = "",
    summary: str = "",
) -> str:
    """Stage a ready attachment from the current Agent's session into its own or an authorized Team inbox."""

    runtime = _current_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()
    session_id = str(runtime.get("sessionId") or "").strip()
    if not agent_id or not session_id:
        return _json_result(
            {
                "ok": False,
                "status": "blocked",
                "error": "agent_session_identity_required",
                "message": "必须从绑定当前 Agent 的活动会话中暂存附件。",
                "agentId": agent_id,
            }
        )

    normalized_team_id = str(team_id or "").strip()
    owner_type = "team" if normalized_team_id else "agent"
    owner_id = normalized_team_id or agent_id
    memory_policy = runtime.get("memoryPolicy") if isinstance(runtime.get("memoryPolicy"), dict) else {}
    if owner_type == "agent" and memory_policy.get("enabled") is False:
        return _json_result(_blocked_result(agent_id, "personal_memory_disabled"))
    normalized_attachment_id = str(attachment_id or "").strip()
    stage_identity = json.dumps(
        [
            "session-attachment-stage-v1",
            agent_id,
            session_id,
            owner_type,
            owner_id,
            normalized_attachment_id,
            str(title or ""),
            str(summary or ""),
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    idempotency_key = "agent-stage-" + hashlib.sha256(stage_identity.encode("utf-8")).hexdigest()
    try:
        from core.web.services import team_knowledge_service

        source = team_knowledge_service.collect_session_attachment_to_inbox(
            owner_type,
            owner_id,
            session_id=session_id,
            attachment_id=normalized_attachment_id,
            actor_agent_id=agent_id,
            title=title,
            summary=summary,
            idempotency_key=idempotency_key,
        )
        _record_event(
            "knowledge.tool.session_attachment.staged",
            runtime=runtime,
            outcome="succeeded",
            fields={
                "ownerType": owner_type,
                "inboxSourceId": str(source.get("inboxSourceId") or ""),
                "sourceType": str(source.get("sourceType") or ""),
            },
            include_session_id=False,
        )
        return _json_result(
            {
                "ok": True,
                "status": "staged",
                "agentId": agent_id,
                "ownerType": owner_type,
                "ownerId": owner_id,
                "inboxSourceId": str(source.get("inboxSourceId") or ""),
                "sourceType": str(source.get("sourceType") or ""),
                "reviewStatus": str(source.get("status") or "pending"),
            }
        )
    except Exception as exc:
        _record_event(
            "knowledge.tool.session_attachment.stage_failed",
            runtime=runtime,
            level="error",
            outcome="failed",
            fields={"ownerType": owner_type, "errorType": type(exc).__name__},
            include_session_id=False,
        )
        return _json_result(
            {
                "ok": False,
                "status": "failed",
                "error": type(exc).__name__,
                "message": "附件暂存失败；请检查会话、附件状态和知识库权限。",
                "agentId": agent_id,
                "ownerType": owner_type,
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


def knowledge_proposal_review_tool(
    knowledge_base_id: str,
    proposal_id: str,
    decision: str,
    resolution_note: str = "",
) -> str:
    """Apply or reject a pending proposal as the current authorized reviewer."""

    runtime = _current_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()
    base_id = str(knowledge_base_id or "").strip()
    normalized_decision = str(decision or "").strip().lower()
    if not agent_id:
        return _json_result(_blocked_result("", "agent_identity_required"))
    if normalized_decision not in {"applied", "rejected"}:
        return _json_result(_invalid_json_result(agent_id, "decision must be applied or rejected"))
    memory_policy = runtime.get("memoryPolicy") if isinstance(runtime.get("memoryPolicy"), dict) else {}
    allowed_base_ids = _policy_ids(memory_policy, "reviewKnowledgeBaseIds")
    if base_id and not _policy_allows_knowledge_base(base_id, allowed_base_ids):
        return _json_result(_blocked_result(agent_id, "knowledge_base_not_in_memory_policy"))

    try:
        from core.web.services import team_knowledge_service

        result = team_knowledge_service.review_refinement_proposal(
            base_id,
            str(proposal_id or "").strip(),
            status=normalized_decision,
            reviewed_by_agent_id=agent_id,
            resolution_note=resolution_note,
        )
        proposal = result.get("proposal") if isinstance(result.get("proposal"), dict) else {}
        item = result.get("item") if isinstance(result.get("item"), dict) else {}
        _record_event(
            "knowledge.tool.proposal.reviewed",
            runtime=runtime,
            outcome="succeeded",
            fields={
                "knowledgeBaseId": base_id,
                "proposalId": str(proposal.get("proposalId") or ""),
                "decision": normalized_decision,
                "knowledgeItemId": str(item.get("knowledgeItemId") or ""),
            },
        )
        return _json_result(
            {
                "ok": True,
                "status": str(proposal.get("status") or normalized_decision),
                "knowledgeBaseId": base_id,
                "proposalId": str(proposal.get("proposalId") or ""),
                "knowledgeItemId": str(item.get("knowledgeItemId") or ""),
            }
        )
    except Exception as exc:
        _record_event(
            "knowledge.tool.proposal.review_failed",
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
                "knowledgeBaseId": base_id,
                "proposalId": str(proposal_id or "").strip(),
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
    inbox_source_id: str = "",
    owner_type: str = "",
    owner_id: str = "",
    review_decision: str = "accepted",
    resolution_note: str = "",
) -> str:
    """
    Submit a knowledge ingestion package, or direct-ingest a screened inbox source.

    When inbox_source_id + owner_type + owner_id are provided, the tool reviews
    that owner inbox source and direct-ingests accepted content as a formal
    KnowledgeItem. Without inbox_source_id, it keeps the older central-source
    package behavior and creates SourceArtifact + pending RefinementProposal.
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

        normalized_inbox_source_id = str(inbox_source_id or "").strip()
        if normalized_inbox_source_id:
            review = team_knowledge_service.review_owner_inbox_source(
                owner_type,
                owner_id,
                normalized_inbox_source_id,
                decision=review_decision or "accepted",
                reviewed_by_agent_id=agent_id,
                resolution_note=resolution_note,
                ingest_on_accept=True,
                knowledge_base_id=base_id,
                knowledge_title=proposal_title or source_title,
                knowledge_summary=proposal_summary or source_summary,
                knowledge_content=proposal_content or excerpt,
                tags=_split_tags(tags),
            )
            direct_ingestion = review.get("directIngestion") if isinstance(review.get("directIngestion"), dict) else {}
            workflow_reconciliation = {
                "status": "not_applicable",
                "updated": False,
                "reason": "source_is_not_an_experiment_result_pack",
            }
            reviewed_source = review.get("source") if isinstance(review.get("source"), dict) else {}
            reviewed_source_ref = (
                reviewed_source.get("sourceRef")
                if isinstance(reviewed_source.get("sourceRef"), dict)
                else {}
            )
            if (
                str(owner_type or "").strip().lower() == "team"
                and reviewed_source_ref.get("planId")
                and reviewed_source_ref.get("experimentResultPackId")
            ):
                try:
                    from core.web.services import team_workflow_orchestration_service

                    workflow_reconciliation = (
                        team_workflow_orchestration_service.reconcile_experiment_knowledge_ingestion(
                            owner_id,
                            inbox_source_id=normalized_inbox_source_id,
                            source_ref=reviewed_source_ref,
                            direct_ingestion=direct_ingestion,
                            reconciled_by_agent_id=agent_id,
                        )
                    )
                except Exception as exc:
                    workflow_reconciliation = {
                        "status": "failed",
                        "updated": False,
                        "reason": "experiment_workflow_reconciliation_failed",
                        "errorType": type(exc).__name__,
                    }
                    _record_event(
                        "knowledge.tool.ingestion.workflow_reconciliation_failed",
                        runtime=runtime,
                        level="error",
                        outcome="failed",
                        fields={
                            "knowledgeBaseId": base_id,
                            "ownerType": owner_type,
                            "ownerId": owner_id,
                            "inboxSourceId": normalized_inbox_source_id,
                            "knowledgeItemId": (
                                (direct_ingestion.get("item") or {})
                                if isinstance(direct_ingestion.get("item"), dict)
                                else {}
                            ).get("knowledgeItemId", ""),
                            "errorType": type(exc).__name__,
                        },
                    )
            _record_event(
                "knowledge.tool.ingestion.direct_ingested",
                runtime=runtime,
                outcome="succeeded",
                fields={
                    "knowledgeBaseId": base_id,
                    "ownerType": owner_type,
                    "ownerId": owner_id,
                    "inboxSourceId": normalized_inbox_source_id,
                    "knowledgeItemId": ((direct_ingestion.get("item") or {}) if isinstance(direct_ingestion.get("item"), dict) else {}).get("knowledgeItemId", ""),
                    "workflowReconciliationStatus": str(workflow_reconciliation.get("status") or ""),
                    "workflowReconciliationUpdated": bool(workflow_reconciliation.get("updated")),
                },
            )
            return _json_result(
                {
                    "ok": True,
                    "status": str(direct_ingestion.get("status") or "ingested"),
                    "agentId": agent_id,
                    "review": review,
                    "directIngestion": direct_ingestion,
                    "workflowReconciliation": workflow_reconciliation,
                }
            )

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
    """Read the current Agent's knowledge base admin governance recommendations."""

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
    """Read the current Agent's consolidated knowledge base admin workbench."""

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
    include_session_id: bool = True,
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
                **({"sessionId": str(runtime.get("sessionId") or "").strip()} if include_session_id else {}),
                **dict(fields or {}),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _json_result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
