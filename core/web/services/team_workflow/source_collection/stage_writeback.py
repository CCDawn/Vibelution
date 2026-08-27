"""Source-collection stage writeback / task context / post-turn reconcile.

Clarity B6: split from stages.py. Shared gates/helpers import from stage_session.
"""

from __future__ import annotations

from typing import Any

from ..source_collection_common import project_source_version_families

from .stage_session import (
    _AUTO_FORMAL_RETRY_STATUSES,
    _service,
    _source_collection_run_graph_metrics,
    _source_collection_task_experiment_session_fields,
    assert_source_collection_stage_advance_ready,
)

def writeback_source_collection_stage_session_task(
    team_id: str,
    task_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_task_id = s._normalize_required_id(task_id, "Stage session task id is required.")
    s.team_service.get_team(normalized_team_id)
    request_payload = dict(payload) if isinstance(payload, dict) else {}
    task, run_id = s._find_source_collection_stage_session_task_by_id(normalized_team_id, normalized_task_id)
    if task is None or not run_id:
        raise s.TeamWorkflowOrchestrationError(f"Stage session task not found: {normalized_task_id}")
    status = s._normalize_source_collection_stage_session_task_status(request_payload.get("status") or request_payload.get("resultStatus"))
    result_payload = s._normalize_source_collection_stage_writeback_result_payload(request_payload.get("result"))
    result_payload = s._merge_source_collection_stage_writeback_evidence_fetch_attempts(
        result_payload,
        request_payload.get("evidenceRefs"),
    )
    result_payload = s._merge_source_collection_stage_writeback_result_payload(normalized_team_id, run_id, task, result_payload)
    writeback = {
        "status": status,
        "agentRequestedStatus": status,
        "summary": s._trim_text(request_payload.get("summary"), max_length=4000),
        "result": s._normalize_source_collection_stage_writeback_result_metadata(result_payload),
        "evidenceRefs": s._normalize_ref_list(request_payload.get("evidenceRefs"), max_items=24),
        "nextActions": s._normalize_text_list(request_payload.get("nextActions"), max_items=12, max_length=500),
        "recordedByAgent": s._trim_text(request_payload.get("recordedByAgent"), max_length=160),
        "metadata": s._normalize_metadata(request_payload.get("metadata")),
        "recordedAt": s.utc_now_iso(),
    }
    coverage_summary = s._source_collection_stage_writeback_candidate_coverage(
        normalized_team_id,
        run_id,
        task,
        writeback,
    )
    if coverage_summary.get("applicable"):
        if status == "completed" and not bool(coverage_summary.get("complete")):
            status = "needs_review"
            writeback["status"] = status
        writeback["coverageSummary"] = coverage_summary
        writeback["invalidCandidateIds"] = list(coverage_summary.get("invalidCandidateIds") or [])
        writeback["invalidRecordIds"] = list(coverage_summary.get("invalidRecordIds") or [])
    materialized_sources = s._materialize_source_collection_stage_writeback_sources(
        normalized_team_id,
        run_id,
        task,
        writeback,
    )
    materialized_content_extraction = s._materialize_source_collection_stage_writeback_content_extraction(
        normalized_team_id,
        run_id,
        task,
        writeback,
    )
    materialized_source_quality = s._materialize_source_collection_stage_writeback_quality(
        normalized_team_id,
        run_id,
        task,
        writeback,
    )
    materialized_candidate_graph = s._materialize_source_collection_stage_writeback_candidate_graph(
        normalized_team_id,
        run_id,
        task,
        writeback,
    )
    materialized_knowledge_ingestion = s._materialize_source_collection_stage_writeback_knowledge_ingestion(
        normalized_team_id,
        run_id,
        task,
        writeback,
    )
    if status == "completed" and s._source_collection_count(materialized_content_extraction.get("missingEvidenceAnchorCount")):
        status = "needs_review"
        writeback["status"] = status
        writeback["evidenceReviewRequiredReason"] = "missing_evidence_anchor"
    closure_summary = s._source_collection_stage_writeback_closure_summary(
        task,
        writeback,
        coverage_summary=coverage_summary,
        materialized_sources=materialized_sources,
        materialized_content_extraction=materialized_content_extraction,
        materialized_source_quality=materialized_source_quality,
        materialized_candidate_graph=materialized_candidate_graph,
        materialized_knowledge_ingestion=materialized_knowledge_ingestion,
    )
    if status == "completed" and not bool(closure_summary.get("artifactComplete")):
        status = "needs_review"
        writeback["status"] = status
        closure_summary = s._source_collection_stage_writeback_closure_summary(
            task,
            writeback,
            coverage_summary=coverage_summary,
            materialized_sources=materialized_sources,
            materialized_content_extraction=materialized_content_extraction,
            materialized_source_quality=materialized_source_quality,
            materialized_candidate_graph=materialized_candidate_graph,
            materialized_knowledge_ingestion=materialized_knowledge_ingestion,
        )
    task_checklist = [
        item for item in list(task.get("taskChecklist") or [])
        if isinstance(item, dict)
    ]
    task_tool_progress = closure_summary.get("taskToolProgress") if isinstance(closure_summary.get("taskToolProgress"), dict) else {}
    completion_gate = s._source_collection_stage_completion_gate(
        task_checklist=task_checklist,
        artifact_complete=bool(closure_summary.get("artifactComplete")),
        task_checklist_complete=bool(closure_summary.get("taskChecklistComplete")),
    )
    closure_summary["completionGate"] = completion_gate
    closure_summary["completionGatePassed"] = bool(completion_gate.get("passed"))
    if status == "completed" and not bool(closure_summary.get("completionGatePassed")):
        status = "needs_review"
        writeback["status"] = status
        closure_summary = s._source_collection_stage_writeback_closure_summary(
            task,
            writeback,
            coverage_summary=coverage_summary,
            materialized_sources=materialized_sources,
            materialized_content_extraction=materialized_content_extraction,
            materialized_source_quality=materialized_source_quality,
            materialized_candidate_graph=materialized_candidate_graph,
            materialized_knowledge_ingestion=materialized_knowledge_ingestion,
        )
        task_tool_progress = closure_summary.get("taskToolProgress") if isinstance(closure_summary.get("taskToolProgress"), dict) else {}
        completion_gate = s._source_collection_stage_completion_gate(
            task_checklist=task_checklist,
            artifact_complete=bool(closure_summary.get("artifactComplete")),
            task_checklist_complete=bool(closure_summary.get("taskChecklistComplete")),
        )
        closure_summary["completionGate"] = completion_gate
        closure_summary["completionGatePassed"] = bool(completion_gate.get("passed"))
    writeback["materializedSources"] = materialized_sources
    writeback["materializedContentExtraction"] = materialized_content_extraction
    writeback["materializedSourceQuality"] = materialized_source_quality
    writeback["materializedCandidateGraph"] = materialized_candidate_graph
    writeback["materializedKnowledgeIngestion"] = materialized_knowledge_ingestion
    writeback["closureSummary"] = closure_summary
    task["status"] = status
    task["summary"] = writeback["summary"] or s._trim_text(task.get("summary"), max_length=4000)
    task["result"] = writeback["result"]
    if coverage_summary.get("applicable"):
        task["result"]["coverageSummary"] = coverage_summary
        task["result"]["invalidCandidateIds"] = list(coverage_summary.get("invalidCandidateIds") or [])
        task["result"]["invalidRecordIds"] = list(coverage_summary.get("invalidRecordIds") or [])
    if (
        materialized_sources.get("createdRecordCount")
        or materialized_sources.get("importedCandidateCount")
        or materialized_sources.get("excludedSourceCount")
    ):
        task["result"]["materializedSources"] = materialized_sources
    if materialized_content_extraction.get("extractedCandidateCount"):
        task["result"]["materializedContentExtraction"] = materialized_content_extraction
    if materialized_source_quality.get("assessedCandidateCount"):
        task["result"]["materializedSourceQuality"] = materialized_source_quality
    if materialized_candidate_graph.get("candidateGraphId"):
        task["result"]["materializedCandidateGraph"] = materialized_candidate_graph
    if materialized_knowledge_ingestion.get("stewardPackCandidateId") or materialized_knowledge_ingestion.get("formalKnowledgeItemCount"):
        task["result"]["materializedKnowledgeIngestion"] = materialized_knowledge_ingestion
    task["result"]["closureSummary"] = closure_summary
    task["evidenceRefs"] = writeback["evidenceRefs"]
    task["nextActions"] = writeback["nextActions"]
    task["writeback"] = writeback
    task["taskToolRequired"] = bool(task.get("taskToolRequired", True))
    if task_checklist:
        task["taskChecklist"] = task_checklist
    task["taskToolProgress"] = task_tool_progress or s._source_collection_stage_task_tool_progress(task_checklist)
    task["completionGate"] = completion_gate
    task["writesFormalKnowledge"] = bool(materialized_knowledge_ingestion.get("writesFormalKnowledge"))
    task["writesRag"] = False
    task["writesOfficialGraph"] = bool(materialized_knowledge_ingestion.get("writesOfficialGraph"))
    turn = task.get("turn") if isinstance(task.get("turn"), dict) else {}
    if turn:
        next_turn = dict(turn)
        next_turn["status"] = status
        task["turn"] = next_turn
    task["updatedAt"] = writeback["recordedAt"]
    s._upsert_source_collection_stage_session_task(normalized_team_id, run_id, task)
    s._sync_stage_round_with_source_collection_stage_task(normalized_team_id, run_id, task)
    s._record_workflow_event(
        "source_collection.stage_session_task_writeback",
        normalized_team_id,
        fields={
            "runId": run_id,
            "taskId": normalized_task_id,
            "stageId": task.get("stageId", ""),
            "agentId": task.get("agentId", ""),
            "status": status,
            "sourceLeadCount": materialized_sources.get("sourceLeadCount", 0),
            "createdRecordCount": materialized_sources.get("createdRecordCount", 0),
            "importedCandidateCount": materialized_sources.get("importedCandidateCount", 0),
            "excludedSourceCount": materialized_sources.get("excludedSourceCount", 0),
            "skippedDuplicateCount": materialized_sources.get("skippedDuplicateCount", 0),
            "contentExtractionCandidateCount": materialized_content_extraction.get("extractedCandidateCount", 0),
            "sourceQualityAssessedCandidateCount": materialized_source_quality.get("assessedCandidateCount", 0),
            "coverageProcessedCount": coverage_summary.get("processed", 0) if coverage_summary.get("applicable") else 0,
            "coverageMissingCount": coverage_summary.get("missing", 0) if coverage_summary.get("applicable") else 0,
            "coverageInvalidCount": coverage_summary.get("invalid", 0) if coverage_summary.get("applicable") else 0,
            "sourceQualitySkippedCandidateCount": materialized_source_quality.get("skippedCandidateCount", 0),
            "candidateGraphId": materialized_candidate_graph.get("candidateGraphId", ""),
            "candidateGraphCreatedCount": materialized_candidate_graph.get("createdCandidateGraphCount", 0),
            "candidateGraphReused": bool(materialized_candidate_graph.get("reusedCandidateGraph")),
            "knowledgeIngestionStatus": materialized_knowledge_ingestion.get("status", ""),
            "formalKnowledgeItemCount": materialized_knowledge_ingestion.get("formalKnowledgeItemCount", 0),
            "stewardPackCandidateId": materialized_knowledge_ingestion.get("stewardPackCandidateId", ""),
            "closureUserStatus": closure_summary.get("userStatus", ""),
            "closureArtifactStatus": closure_summary.get("artifactStatus", ""),
            "closureSuccessCount": closure_summary.get("successCount", 0),
        },
        child_log_path=f"artifacts/source-collection-{s._safe_token(run_id, default='run', max_length=96)}-stage-writeback.jsonl",
        child_log_payload=s._source_collection_stage_writeback_child_log_payload(
            team_id=normalized_team_id,
            run_id=run_id,
            task=task,
            materialized_sources=materialized_sources,
            materialized_source_quality=materialized_source_quality,
            materialized_candidate_graph=materialized_candidate_graph,
            materialized_knowledge_ingestion=materialized_knowledge_ingestion,
        ),
    )
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "runId": run_id,
        "taskId": normalized_task_id,
        "stageId": task.get("stageId", ""),
        "agentId": task.get("agentId", ""),
        "agentRole": task.get("agentRole", ""),
        "task": task,
        "writeback": writeback,
        "boundaries": s._source_collection_stage_session_task_boundaries(
            stage_id=s._trim_text(task.get("stageId"), max_length=80),
            agent_role=s._trim_text(task.get("agentRole"), max_length=80),
        ),
    }

def get_source_collection_stage_task_context(
    team_id: str,
    *,
    run_id: str = "",
    stage_id: str = "",
    task_id: str = "",
    max_records: int = 24,
    include_candidates: bool = True,
    record_offset: int = 0,
    record_limit: int | None = None,
    candidate_offset: int = 0,
    candidate_limit: int | None = None,
    context_mode: str = "compact",
) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.assert_team_exists(normalized_team_id)
    normalized_task_id = s._trim_text(task_id, max_length=160)
    task: dict[str, Any] = {}
    task_run_id = ""
    if normalized_task_id:
        found_task, found_run_id = s._find_source_collection_stage_session_task_by_id(normalized_team_id, normalized_task_id)
        if found_task is None or not found_run_id:
            raise s.TeamWorkflowOrchestrationError(f"Stage session task not found: {normalized_task_id}")
        task = s._reconcile_source_collection_stage_session_task(normalized_team_id, found_run_id, dict(found_task))
        task_run_id = found_run_id
    normalized_run_id = (
        s._trim_text(run_id, max_length=128)
        or task_run_id
        or s._trim_text(task.get("runId"), max_length=128)
    )
    normalized_run_id = s._normalize_required_id(normalized_run_id, "Data processing run id is required.")
    normalized_stage_id = s._normalize_source_collection_stage_id(
        s._trim_text(stage_id, max_length=80)
        or s._trim_text(task.get("stageId"), max_length=80),
        default="finding",
    )
    if normalized_stage_id not in s.SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES:
        raise s.TeamWorkflowOrchestrationError(f"Unsupported source collection stage: {normalized_stage_id}")
    normalized_context_mode = s._normalize_source_collection_context_mode(context_mode)
    task_context_mode_raw = s._trim_text(task.get("sourceContextMode"), max_length=40)
    if task_context_mode_raw:
        task_context_mode = s._normalize_source_collection_context_mode(task_context_mode_raw)
        if task_context_mode in {"retry_missing", "retry_evidence"} or (
            normalized_stage_id == "relations" and task_context_mode == "evidence"
        ):
            normalized_context_mode = task_context_mode
    run_bundle = s._source_collection_run_context_bundle(normalized_team_id, normalized_run_id)
    task_agent_id = s._trim_text(task.get("agentId"), max_length=160)
    task_agent_role = s._normalize_source_collection_agent_role(task.get("agentRole"))
    matching_assignments = s._source_collection_matching_assignments(
        run_bundle["assignments"],
        agent_id=task_agent_id,
        agent_role=task_agent_role,
    )
    limit = s._normalize_int(max_records, default=24, minimum=1, maximum=80)
    records = s._rank_source_collection_context_records(
        run_bundle["records"],
        stage_id=normalized_stage_id,
        source_candidates=run_bundle["sourceCandidates"],
    )
    record_page_offset = s._normalize_int(record_offset, default=0, minimum=0, maximum=10000)
    record_page_limit = s._normalize_int(
        record_limit if record_limit is not None else limit,
        default=limit,
        minimum=1,
        maximum=80,
    )
    selected_records = records[record_page_offset:record_page_offset + record_page_limit]
    next_record_offset = record_page_offset + len(selected_records)
    record_has_more = next_record_offset < len(records)
    projected_source_candidates, source_family_summary = project_source_version_families(
        run_bundle["sourceCandidates"],
    )
    inventory_candidates = s._rank_source_collection_context_candidates(
        projected_source_candidates,
        stage_id=normalized_stage_id,
    )
    source_candidates = inventory_candidates if include_candidates else []
    memory_steward_mode = s._source_collection_stage_can_materialize_formal_knowledge(
        normalized_stage_id,
        task_agent_role,
    )
    pageable_candidates = [
        item for item in source_candidates if s._source_quality_bucket(item) == "approved"
    ] if memory_steward_mode else source_candidates
    retry_focus = {}
    retry_source_task = task
    retry_source_task_id = s._trim_text(task.get("retrySourceTaskId"), max_length=160)
    completed_remediation_writeback = bool(
        isinstance(task.get("evidenceRemediationContract"), dict)
        and task.get("evidenceRemediationContract")
        and isinstance(task.get("writeback"), dict)
        and task.get("writeback")
    )
    if retry_source_task_id and not completed_remediation_writeback:
        found_retry_task, found_retry_run_id = s._find_source_collection_stage_session_task_by_id(
            normalized_team_id,
            retry_source_task_id,
        )
        if found_retry_task is not None and found_retry_run_id == normalized_run_id:
            retry_source_task = found_retry_task
    if normalized_context_mode == "retry_missing":
        retry_focus = s._source_collection_stage_retry_focus(retry_source_task, pageable_candidates, records)
        missing_candidate_ids = set(s._normalize_text_list(retry_focus.get("missingCandidateIds"), max_items=500, max_length=160))
        if missing_candidate_ids:
            pageable_candidates = [
                item
                for item in pageable_candidates
                if s._trim_text(item.get("candidateId"), max_length=160) in missing_candidate_ids
            ]
        missing_record_ids = set(s._normalize_text_list(retry_focus.get("missingRecordIds"), max_items=500, max_length=160))
        if missing_record_ids:
            records = [
                item
                for item in records
                if s._trim_text(item.get("recordId"), max_length=160) in missing_record_ids
            ]
            selected_records = records[record_page_offset:record_page_offset + record_page_limit]
            next_record_offset = record_page_offset + len(selected_records)
            record_has_more = next_record_offset < len(records)
    elif normalized_context_mode == "retry_evidence":
        retry_focus = s._source_collection_stage_evidence_retry_focus(retry_source_task, pageable_candidates)
        evidence_gap_ids = set(
            s._normalize_text_list(retry_focus.get("evidenceGapCandidateIds"), max_items=500, max_length=160)
        )
        remediation_contract = (
            task.get("evidenceRemediationContract")
            if isinstance(task.get("evidenceRemediationContract"), dict)
            else {}
        )
        remediation_scope_ids = set(
            s._normalize_text_list(
                remediation_contract.get("scopeCandidateIds"),
                max_items=500,
                max_length=160,
            )
        )
        if remediation_scope_ids:
            evidence_gap_ids &= remediation_scope_ids
            if evidence_gap_ids:
                retry_focus["evidenceGapCandidateIds"] = sorted(evidence_gap_ids)
                retry_focus["missingEvidenceAnchorCount"] = len(evidence_gap_ids)
            else:
                retry_focus = {}
        pageable_candidates = [
            item
            for item in pageable_candidates
            if s._trim_text(item.get("candidateId"), max_length=160) in evidence_gap_ids
        ]
    candidate_page_offset = s._normalize_int(candidate_offset, default=0, minimum=0, maximum=10000)
    candidate_page_limit = s._normalize_int(
        candidate_limit if candidate_limit is not None else limit,
        default=limit,
        minimum=1,
        maximum=80,
    )
    selected_candidates = pageable_candidates[candidate_page_offset:candidate_page_offset + candidate_page_limit]
    next_candidate_offset = candidate_page_offset + len(selected_candidates)
    candidate_has_more = next_candidate_offset < len(pageable_candidates)
    storage_artifacts = s._source_collection_storage_artifacts(normalized_team_id, normalized_run_id)
    selected_unassessed_candidate_ids = [
        s._trim_text(item.get("candidateId"), max_length=128)
        for item in selected_candidates
        if s._trim_text(item.get("candidateId"), max_length=128) and s._source_quality_bucket(item) == "pending"
    ]
    context = {
        "schemaVersion": s.SCHEMA_VERSION,
        "status": "ok",
        "contextKind": "source_collection_stage_task_context",
        "contextMode": normalized_context_mode,
        "teamId": normalized_team_id,
        "runId": normalized_run_id,
        "stageId": normalized_stage_id,
        "taskId": normalized_task_id,
        "agentId": task_agent_id,
        "agentRole": task_agent_role,
        "counts": {
            "recordCount": len(run_bundle["records"]),
            "rawRecordCount": len(run_bundle.get("allRecords") or []),
            "excludedSourceCount": s._source_collection_count((run_bundle.get("excludedSourceSummary") or {}).get("excludedCount")),
            "returnedRecordCount": len(selected_records),
            "candidateCount": len(run_bundle["sourceCandidates"]),
            "independentSourceCount": source_family_summary["independentSourceCount"],
            "versionFamilyCount": source_family_summary["versionFamilyCount"],
            "supersededSourceRecordCount": source_family_summary["supersededRecordCount"],
            "returnedCandidateCount": len(selected_candidates),
            "assignmentCount": len(run_bundle["assignments"]),
            "matchingAssignmentCount": len(matching_assignments),
        },
        "run": s._source_collection_context_run_summary(run_bundle["run"], run_bundle["runStatus"], run_bundle["activeWorkRun"]),
        "task": s._source_collection_context_task_summary(task),
        "assignments": [s._source_collection_context_assignment_summary(item) for item in matching_assignments[:12]],
        "records": [s._source_collection_context_record_summary(item) for item in selected_records],
        "candidates": [
            {
                **s._source_collection_context_candidate_summary(item),
                "sourceVersionFamily": s._normalize_metadata(item.get("sourceVersionFamily")),
            }
            for item in selected_candidates
        ],
        "excludedSourceSummary": s._normalize_metadata(run_bundle.get("excludedSourceSummary")),
        "recordPage": {
            "offset": record_page_offset,
            "limit": record_page_limit,
            "returned": len(selected_records),
            "total": len(records),
            "hasMore": record_has_more,
            "nextOffset": next_record_offset if record_has_more else None,
        },
        "candidatePage": {
            "offset": candidate_page_offset,
            "limit": candidate_page_limit,
            "returned": len(selected_candidates),
            "total": len(pageable_candidates),
            "hasMore": candidate_has_more,
            "nextOffset": next_candidate_offset if candidate_has_more else None,
        },
        "unassessedCandidateIds": selected_unassessed_candidate_ids,
        "allUnassessedCandidateCount": sum(
            1
            for item in inventory_candidates
            if s._source_quality_bucket(item) == "pending"
        ),
        "storageArtifacts": storage_artifacts,
        "writebackContract": task.get("writebackContract") if isinstance(task.get("writebackContract"), dict) else {},
        "evidenceRemediationContract": (
            task.get("evidenceRemediationContract")
            if isinstance(task.get("evidenceRemediationContract"), dict)
            else {}
        ),
        "boundaries": s._source_collection_stage_session_task_boundaries(
            stage_id=normalized_stage_id,
            agent_role=task_agent_role,
        ),
        "usage": {
            "readTool": "source_collection_context_tool",
            "writebackTool": "source_collection_stage_writeback_tool",
            "doNotUse": ["file://", "localhost fetch", "web_fetch_tool for local paths"],
            "fallback": "If required context is missing, write back status=blocked with a short reason.",
        },
    }
    if retry_focus:
        context["retryFocus"] = retry_focus
        context["usage"]["retryInstruction"] = s._trim_text(retry_focus.get("retryInstruction"), max_length=1000)
    if normalized_context_mode in {"evidence", "retry_missing", "retry_evidence"}:
        context["usage"]["evidenceInstruction"] = (
            "candidates[].summary 是搜集阶段保存的摘要或元数据，不等于全文；"
            "只可对该摘要支持的判断使用 candidates[].evidenceRefs，不能虚构页码、原文引语或全文结论。"
        )
    context["usage"]["continuationHint"] = s._source_collection_context_continuation_hint(
        context["candidatePage"],
        context_mode=context["contextMode"],
    )
    context["usage"]["recordContinuationHint"] = s._source_collection_context_record_continuation_hint(
        context["recordPage"],
        context_mode=context["contextMode"],
    )
    if memory_steward_mode:
        context["stewardActionPacket"] = s._source_collection_memory_steward_action_packet(
            inventory_candidates,
            writeback_contract=context["writebackContract"],
        )
        context["usage"]["fallback"] = (
            "Use stewardActionPacket. Do not infer hidden or truncated candidates; "
            "if no approvedCandidateIds are present, write back status=blocked with a short reason."
        )
        context["usage"]["continuationHint"] = s._source_collection_context_continuation_hint(
            context["candidatePage"],
            context_mode=context["contextMode"],
        )
    if context["contextMode"] == "full":
        return context
    return s._compact_source_collection_stage_task_context(context)

def reconcile_source_collection_stage_session_task_after_turn(
    team_id: str,
    task_id: str,
    *,
    run_id: str = "",
    session_id: str = "",
    turn_id: str = "",
    final_status: str = "",
    llm_usage: dict[str, Any] | None = None,
    model_invocation_receipt: Any = None,
    stage_id: str | None = None,
    model_policy_sha256: str | None = None,
    reason: str = "session_turn_completed",
) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_task_id = s._trim_text(task_id, max_length=160)
    if not normalized_task_id:
        return {"schemaVersion": s.SCHEMA_VERSION, "status": "skipped", "reason": "missing_task_id", "changed": False}
    found_task, found_run_id = s._find_source_collection_stage_session_task_by_id(normalized_team_id, normalized_task_id)
    if found_task is None or not found_run_id:
        return {
            "schemaVersion": s.SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "taskId": normalized_task_id,
            "status": "not_found",
            "reason": "stage_session_task_not_found",
            "changed": False,
        }
    normalized_run_id = s._trim_text(run_id, max_length=128)
    if normalized_run_id and normalized_run_id != found_run_id:
        return {
            "schemaVersion": s.SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "runId": found_run_id,
            "requestedRunId": normalized_run_id,
            "taskId": normalized_task_id,
            "status": "skipped",
            "reason": "run_id_mismatch",
            "changed": False,
        }
    normalized_session_id = s._trim_text(session_id, max_length=160)
    task_turn = found_task.get("turn") if isinstance(found_task.get("turn"), dict) else {}
    task_session_id = s._trim_text(found_task.get("sessionId") or task_turn.get("sessionId"), max_length=160)
    if normalized_session_id and task_session_id and normalized_session_id != task_session_id:
        return {
            "schemaVersion": s.SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "runId": found_run_id,
            "taskId": normalized_task_id,
            "status": "skipped",
            "reason": "session_id_mismatch",
            "changed": False,
        }
    normalized_turn_id = s._trim_text(turn_id, max_length=200)
    task_turn_id = s._trim_text(task_turn.get("turnId"), max_length=200)
    original_found_task = dict(found_task)
    if normalized_turn_id and task_turn_id and normalized_turn_id != task_turn_id:
        continuation_task = s._source_collection_stage_session_task_with_continuation_turn(
            found_task,
            session_id=normalized_session_id or task_session_id,
            turn_id=normalized_turn_id,
        )
        if continuation_task is None:
            return {
                "schemaVersion": s.SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "runId": found_run_id,
                "taskId": normalized_task_id,
                "status": "skipped",
                "reason": "turn_id_mismatch",
                "changed": False,
            }
        found_task = continuation_task
        task_turn = found_task.get("turn") if isinstance(found_task.get("turn"), dict) else {}
        task_turn_id = s._trim_text(task_turn.get("turnId"), max_length=200)
        s._upsert_source_collection_stage_session_task(normalized_team_id, found_run_id, found_task)
        s._record_workflow_event(
            "source_collection.stage_session_task_continuation_turn_adopted",
            normalized_team_id,
            fields={
                "runId": found_run_id,
                "taskId": normalized_task_id,
                "sessionId": task_session_id,
                "previousTurnId": s._trim_text(task_turn.get("previousTurnId"), max_length=200),
                "turnId": task_turn_id,
            },
            level="info",
            outcome="reconciled",
            lifecycle=True,
        )
    before_task = dict(found_task)
    before_status = s._trim_text(before_task.get("status"), max_length=80)
    before_gate = before_task.get("completionGate") if isinstance(before_task.get("completionGate"), dict) else {}
    reconciled = s._reconcile_source_collection_stage_session_task(normalized_team_id, found_run_id, dict(found_task))
    official_model_evidence = s.register_challenge_task_model_evidence(
        normalized_team_id,
        reconciled,
        final_status=final_status,
        llm_usage=llm_usage,
        model_invocation_receipt=model_invocation_receipt,
        stage_id=stage_id,
        model_policy_sha256=model_policy_sha256,
    )
    after_gate = reconciled.get("completionGate") if isinstance(reconciled.get("completionGate"), dict) else {}
    task_tool_progress = reconciled.get("taskToolProgress") if isinstance(reconciled.get("taskToolProgress"), dict) else {}
    reconciled_turn = reconciled.get("turn") if isinstance(reconciled.get("turn"), dict) else {}
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "runId": found_run_id,
        "taskId": normalized_task_id,
        "sessionId": task_session_id,
        "turnId": s._trim_text(reconciled_turn.get("turnId"), max_length=200) or task_turn_id,
        "status": "reconciled",
        "reason": s._trim_text(reason, max_length=120) or "session_turn_completed",
        "changed": reconciled != original_found_task,
        "previousTaskStatus": before_status,
        "taskStatus": s._trim_text(reconciled.get("status"), max_length=80),
        "previousCompletionGatePassed": bool(before_gate.get("passed")),
        "completionGatePassed": bool(after_gate.get("passed")),
        "taskChecklistComplete": bool(after_gate.get("taskChecklistComplete")),
        "artifactComplete": bool(after_gate.get("artifactComplete")),
        "taskToolProgress": task_tool_progress,
        "officialModelEvidence": official_model_evidence or {},
    }
