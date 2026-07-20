"""Source-collection candidates register/import/extract/list/validate entrypoints.

Late-bound facade helpers keep route imports and monkeypatches on
``team_workflow_orchestration_service`` stable during P0 mechanical splits.
"""

from __future__ import annotations

from typing import Any


def _service():
    from core.web.services import team_workflow_orchestration_service

    return team_workflow_orchestration_service


def register_candidate_source(team_id: str, payload: dict[str, Any], *, strict: bool = False) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.get_team(normalized_team_id)
    candidate_type = s._normalize_candidate_type(payload.get("candidateType") or "source_manifest")
    title = s._trim_text(payload.get("title"), max_length=240)
    source_url = s._trim_text(payload.get("sourceUrl"), max_length=2000)
    source_path = s._trim_text(payload.get("sourcePath"), max_length=2000)
    if not title and not source_url and not source_path:
        raise s.TeamWorkflowOrchestrationError("Candidate title or sourceUrl is required.")
    now = s.utc_now_iso()
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        candidate_store = s._load_candidate_store(normalized_team_id)
        source_kind = s._trim_text(payload.get("sourceKind"), max_length=80) or "unknown"
        metadata = s._normalize_metadata(payload.get("metadata"))
        candidate = {
            "schemaVersion": s.SCHEMA_VERSION,
            "candidateId": s._new_record_id("candidate"),
            "candidateType": candidate_type,
            "teamId": normalized_team_id,
            "workflowId": workflow["workflowId"],
            "title": title or source_url or source_path,
            "sourceUrl": source_url,
            "sourcePath": source_path,
            "sourceKind": source_kind,
            "sha256": s._trim_text(payload.get("sha256"), max_length=128),
            "allowedForAnalysis": s._normalize_optional_bool(payload.get("allowedForAnalysis")),
            "pageScope": s._trim_text(payload.get("pageScope"), max_length=160),
            "summary": s._trim_text(payload.get("summary"), max_length=4000),
            "tags": s._normalize_text_list(payload.get("tags"), max_items=24, max_length=80),
            "evidenceRefs": s._normalize_ref_list(payload.get("evidenceRefs"), max_items=24),
            "metadata": metadata,
            "createdByAgent": s._trim_text(payload.get("createdByAgent"), max_length=160),
            "currentWorkflowNode": "knowledge_collection",
            "currentState": "source_registered",
            "qualityStatus": "pending_screening",
            "createdAt": now,
            "updatedAt": now,
        }
        validation = s.validate_candidate_record(candidate)
        candidate["validation"] = validation
        # 统一写入口校验：registry 提供 envelope 级守卫（candidateId/teamId/类型等恒在，零回归），
        # 逐类型深校验仍由 s.validate_candidate_record 承担。strict=True 时硬拦截（供科研生成链调用方选用）。
        envelope_validation = s.candidate_schema_registry.validate_envelope(candidate)
        candidate["envelopeValidation"] = envelope_validation
        candidate_valid = bool(validation.get("valid")) and bool(envelope_validation.get("valid"))
        if strict and not candidate_valid:
            raise s.TeamWorkflowOrchestrationError(
                f"Candidate failed schema validation: {validation.get('issues', [])} {envelope_validation.get('issues', [])}"
            )
        if not candidate_valid:
            candidate["currentState"] = "source_needs_confirmation"
            candidate["qualityStatus"] = "source_manifest_invalid"
        candidate_store.setdefault("candidates", []).append(candidate)
        candidate_store["updatedAt"] = now
        s._write_json(s._candidate_store_path(normalized_team_id), candidate_store)
        workflow["updatedAt"] = now
        workflow["activeWorkflowItems"] = s._upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=candidate["candidateId"],
            current_node=candidate["currentWorkflowNode"],
            status=candidate["currentState"],
            transfer_id="",
        )
        s._write_json(s._workflow_path(normalized_team_id), workflow)
    s._record_workflow_event(
        "candidate.registered",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "candidateId": candidate["candidateId"],
            "candidateType": candidate["candidateType"],
            "sourceKind": candidate["sourceKind"],
        },
    )
    return {
        "candidate": candidate,
        "validation": validation,
        "workflow": s._workflow_to_api(normalized_team_id, workflow, candidate_store),
    }

def import_data_record_as_source_candidate(team_id: str, run_id: str, record_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_run_id = s._trim_text(run_id, max_length=128)
    normalized_record_id = s._trim_text(record_id, max_length=128)
    if not normalized_run_id or not normalized_record_id:
        raise s.TeamWorkflowOrchestrationError("Data processing runId and recordId are required.")
    s.team_service.get_team(normalized_team_id)
    import_payload = payload if isinstance(payload, dict) else {}
    run, record = s._load_data_processing_record(normalized_run_id, normalized_record_id)
    source_identity_key = s._source_collection_record_identity_key(record)
    excluded_entry = s._source_collection_record_is_excluded(normalized_team_id, run, record)
    if excluded_entry:
        s._record_workflow_event(
            "candidate.import_excluded_source_blocked",
            normalized_team_id,
            fields={
                "runId": normalized_run_id,
                "recordId": normalized_record_id,
                "sourceIdentityKey": source_identity_key,
                "exclusionId": s._trim_text(excluded_entry.get("exclusionId"), max_length=160),
                "reason": s._trim_text(excluded_entry.get("reason"), max_length=120),
            },
            level="warning",
            outcome="blocked",
        )
        raise s.TeamWorkflowOrchestrationError("Data processing record is excluded from this source collection topic.")
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        candidate_store = s._load_candidate_store(normalized_team_id)
        existing = s._find_candidate_imported_from_data_record(candidate_store, normalized_run_id, normalized_record_id)
        if existing is not None:
            s._record_workflow_event(
                "candidate.import_duplicate_skipped",
                normalized_team_id,
                fields={
                    "workflowId": workflow["workflowId"],
                    "runId": normalized_run_id,
                    "recordId": normalized_record_id,
                    "duplicateReason": "imported_from_data_record",
                    "duplicateOfCandidateId": str(existing.get("candidateId") or ""),
                    "sourceIdentityKey": source_identity_key,
                },
            )
            return {
                "created": False,
                "duplicate": True,
                "duplicateReason": "imported_from_data_record",
                "duplicateOfCandidateId": str(existing.get("candidateId") or ""),
                "candidate": existing,
                "dataRecordRef": s._data_record_ref(run, record),
                "validation": existing.get("validation") if isinstance(existing.get("validation"), dict) else s.validate_candidate_record(existing),
                "workflow": s._workflow_to_api(normalized_team_id, workflow, candidate_store),
            }
        existing_by_identity = s._find_source_candidate_by_identity_key(candidate_store, source_identity_key)
        if existing_by_identity is not None:
            s._record_workflow_event(
                "candidate.import_duplicate_skipped",
                normalized_team_id,
                fields={
                    "workflowId": workflow["workflowId"],
                    "runId": normalized_run_id,
                    "recordId": normalized_record_id,
                    "duplicateReason": "source_identity_key",
                    "duplicateOfCandidateId": str(existing_by_identity.get("candidateId") or ""),
                    "sourceIdentityKey": source_identity_key,
                },
            )
            return {
                "created": False,
                "duplicate": True,
                "duplicateReason": "source_identity_key",
                "duplicateOfCandidateId": str(existing_by_identity.get("candidateId") or ""),
                "candidate": existing_by_identity,
                "dataRecordRef": s._data_record_ref(run, record),
                "validation": existing_by_identity.get("validation") if isinstance(existing_by_identity.get("validation"), dict) else s.validate_candidate_record(existing_by_identity),
                "workflow": s._workflow_to_api(normalized_team_id, workflow, candidate_store),
            }
    candidate_payload = s._source_candidate_payload_from_data_record(run, record, import_payload)
    response = register_candidate_source(normalized_team_id, candidate_payload)
    candidate = response["candidate"]
    s._record_workflow_event(
        "candidate.imported_from_data_record",
        normalized_team_id,
        fields={
            "workflowId": candidate.get("workflowId", ""),
            "candidateId": candidate.get("candidateId", ""),
            "runId": normalized_run_id,
            "recordId": normalized_record_id,
            "sourceKind": candidate.get("sourceKind", ""),
        },
    )
    return {
        "created": True,
        "candidate": candidate,
        "dataRecordRef": s._data_record_ref(run, record),
        "validation": response["validation"],
        "workflow": response["workflow"],
    }

def extract_source_collection_candidates(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.get_team(normalized_team_id)
    request_payload = payload if isinstance(payload, dict) else {}
    normalized_run_id = s._normalize_required_id(request_payload.get("runId"), "Data processing run id is required.")
    extraction_agent_id = (
        s._trim_text(request_payload.get("extractionAgentId"), max_length=160)
        or s._trim_text(request_payload.get("createdByAgent"), max_length=160)
        or "资料提炼 Agent"
    )
    max_records = s._normalize_int(request_payload.get("maxRecords"), default=100, minimum=1, maximum=500)
    force = bool(request_payload.get("force"))
    notes = s._trim_text(request_payload.get("notes"), max_length=4000)
    try:
        run = s.data_processing_service.get_processing_run(normalized_run_id)
        records_payload = s.data_processing_service.list_records(normalized_run_id)
        assignments_payload = s.data_processing_service.list_collection_assignments(normalized_run_id)
    except s.data_processing_service.DataProcessingError as exc:
        raise s.TeamWorkflowOrchestrationError(str(exc)) from exc
    run_scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    run_team_id = s._trim_text(run_scope.get("teamId"), max_length=128)
    if run_team_id and run_team_id != normalized_team_id:
        raise s.TeamWorkflowOrchestrationError("Data processing run does not belong to this team.")

    records = [item for item in list(records_payload.get("records") or []) if isinstance(item, dict)]
    assignments = [item for item in list(assignments_payload.get("assignments") or []) if isinstance(item, dict)]
    storage_artifacts = s._source_collection_storage_artifacts(normalized_team_id, normalized_run_id)
    with s._WORKFLOW_LOCK:
        candidate_store = s._load_candidate_store(normalized_team_id)
    existing_by_record_id: dict[str, dict[str, Any]] = {}
    for candidate in list(candidate_store.get("candidates") or []):
        if not isinstance(candidate, dict) or candidate.get("candidateType") != "source_manifest":
            continue
        imported_from = (candidate.get("metadata") or {}).get("importedFromDataRecord") if isinstance(candidate.get("metadata"), dict) else {}
        if not isinstance(imported_from, dict):
            continue
        if s._trim_text(imported_from.get("runId"), max_length=128) != normalized_run_id:
            continue
        imported_record_id = s._trim_text(imported_from.get("recordId"), max_length=128)
        if imported_record_id:
            existing_by_record_id[imported_record_id] = candidate

    pending_records = [
        record for record in records
        if s._trim_text(record.get("recordId"), max_length=128) not in existing_by_record_id
    ]
    target_records = (records if force else pending_records)[:max_records]
    imported: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    record_outcomes: list[dict[str, Any]] = []
    execution_events: list[dict[str, Any]] = []
    extraction_assignment = next(
        (
            item for item in assignments
            if s._normalize_source_collection_agent_role(item.get("agentRole")) == "source_extractor"
        ),
        {"assignmentId": "", "agentRole": "source_extractor", "agentId": extraction_agent_id},
    )
    for record in target_records:
        record_id = s._trim_text(record.get("recordId"), max_length=128)
        if not record_id:
            continue
        try:
            import_response = import_data_record_as_source_candidate(
                normalized_team_id,
                normalized_run_id,
                record_id,
                {
                    "createdByAgent": extraction_agent_id,
                    "tags": ["source_collection", "source_extractor"],
                    "metadata": {
                        "sourceCollectionExtraction": True,
                        "extractionAgentId": extraction_agent_id,
                        "extractionNotes": notes,
                    },
                },
            )
        except s.TeamWorkflowOrchestrationError as exc:
            failed.append({"recordId": record_id, "error": str(exc)})
            record_outcomes.append(
                {
                    "recordId": record_id,
                    "status": "failed",
                    "reason": "source_manifest_import_failed",
                    "errorType": type(exc).__name__,
                }
            )
            execution_events.append(
                s._source_collection_execution_event(
                    "storage.source_manifest_import_failed",
                    assignment=extraction_assignment,
                    status="blocked",
                    title=f"资料提炼失败：{record.get('title') or record_id}",
                    summary=s._trim_text(exc, max_length=600),
                    refs=[record_id],
                    storage_refs=[storage_artifacts["dataProcessingRecordsPath"], storage_artifacts["candidateStorePath"]],
                )
            )
            continue
        event_status = "completed" if import_response.get("created") else "skipped"
        if import_response.get("created"):
            imported.append(import_response)
            record_outcomes.append(
                {
                    "recordId": record_id,
                    "status": "imported",
                    "candidateId": import_response.get("candidate", {}).get("candidateId", ""),
                }
            )
        else:
            duplicate_reason = s._trim_text(import_response.get("duplicateReason"), max_length=120) or "already_imported"
            skipped.append(
                {
                    "recordId": record_id,
                    "candidateId": import_response.get("candidate", {}).get("candidateId", ""),
                    "reason": duplicate_reason,
                }
            )
            record_outcomes.append(
                {
                    "recordId": record_id,
                    "status": "skipped",
                    "candidateId": import_response.get("candidate", {}).get("candidateId", ""),
                    "reason": duplicate_reason,
                }
            )
        execution_events.append(
            s._source_collection_execution_event(
                "storage.source_manifest_imported",
                assignment=extraction_assignment,
                query=s._source_collection_record_search_trace(record),
                status=event_status,
                title=f"资料提炼：{import_response['candidate'].get('title')}",
                summary="资料提炼 Agent 将 DataRecord 转为可追溯 source_manifest 候选；不写正式知识库、RAG 或官方图谱。",
                refs=[import_response["candidate"].get("candidateId", ""), record_id],
                raw_location=s._trim_text(record.get("rawLocation") or record.get("sourceRef"), max_length=1000),
                storage_refs=[storage_artifacts["candidatesPath"], storage_artifacts["candidateStorePath"]],
            )
        )

    completed_extraction_assignments = 0
    remaining_pending_after_batch = max(0, len(pending_records) - len(target_records)) if not force else 0
    if records:
        open_extraction_assignments = [
            item for item in assignments
            if s._normalize_source_collection_agent_role(item.get("agentRole")) == "source_extractor"
            and str(item.get("status") or "").strip().lower() in {"open", "in_progress", "returned"}
        ]
        assignment_output_status = "completed" if not failed and remaining_pending_after_batch == 0 else "returned"
        for assignment in open_extraction_assignments:
            assignment_id = s._trim_text(assignment.get("assignmentId"), max_length=128)
            if not assignment_id:
                continue
            try:
                s.data_processing_service.record_collection_output(
                    normalized_run_id,
                    assignment_id,
                    {
                        "status": assignment_output_status,
                        "records": [],
                        "notes": (
                            f"{extraction_agent_id} synchronized DataRecord records into source_manifest candidates. "
                            f"Imported {len(imported)}, skipped {len(skipped)}, failed {len(failed)}."
                        ),
                        "qualitySignals": {
                            "sourceCollectionExtraction": True,
                            "recordCount": len(records),
                            "importedCount": len(imported),
                            "skippedCount": len(skipped),
                            "failedCount": len(failed),
                        },
                        "blockingIssues": ["source_manifest_import_failed"] if failed else [],
                    },
                )
            except s.data_processing_service.DataProcessingError as exc:
                failed.append({"assignmentId": assignment_id, "error": str(exc)})
                continue
            completed_extraction_assignments += 1

    s._append_source_collection_execution_artifacts(
        normalized_team_id,
        normalized_run_id,
        execution_events=execution_events,
        created_records=[],
        imported=imported,
    )
    final_run = s.data_processing_service.get_processing_run(normalized_run_id)
    final_records_payload = s.data_processing_service.list_records(normalized_run_id)
    final_assignments = s.data_processing_service.list_collection_assignments(normalized_run_id)["assignments"]
    final_status = s.data_processing_service.get_processing_status(normalized_run_id)
    source_collection_summary = s._source_collection_assignment_stage_summary(
        [item for item in list(final_assignments or []) if isinstance(item, dict)]
    )
    final_status_summary = final_status.get("summary") if isinstance(final_status.get("summary"), dict) else {}
    final_status_summary.update(source_collection_summary)
    final_status["summary"] = final_status_summary
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        final_candidate_store = s._load_candidate_store(normalized_team_id)
        workflow_api = s._workflow_to_api(normalized_team_id, workflow, final_candidate_store)
    final_records = [item for item in list(final_records_payload.get("records") or []) if isinstance(item, dict)]
    final_source_candidates = [
        item for item in list(final_candidate_store.get("candidates") or [])
        if isinstance(item, dict)
        and item.get("candidateType") == "source_manifest"
        and isinstance(item.get("metadata"), dict)
        and isinstance(item["metadata"].get("importedFromDataRecord"), dict)
        and s._trim_text(item["metadata"]["importedFromDataRecord"].get("runId"), max_length=128) == normalized_run_id
    ]
    final_candidate_record_ids = {
        s._trim_text(item["metadata"]["importedFromDataRecord"].get("recordId"), max_length=128)
        for item in final_source_candidates
    }
    pending_record_count = len(
        [
            record for record in final_records
            if s._trim_text(record.get("recordId"), max_length=128) not in final_candidate_record_ids
        ]
    )
    status_label = "blocked" if not final_records else ("partial" if failed or pending_record_count else "completed")
    s._record_workflow_event(
        "source_collection.candidates_extracted",
        normalized_team_id,
        fields={
            "runId": normalized_run_id,
            "status": status_label,
            "recordCount": len(final_records),
            "candidateCount": len(final_source_candidates),
            "importedCount": len(imported),
            "skippedCount": len(skipped),
            "failedCount": len(failed),
            "pendingRecordCount": pending_record_count,
            "completedExtractionAssignmentCount": completed_extraction_assignments,
        },
        child_log_path=f"artifacts/source-collection-{s._safe_token(normalized_run_id, default='run', max_length=96)}-candidate-extraction.jsonl",
        child_log_payload={
            "kind": "source_collection_candidate_extraction",
            "teamId": normalized_team_id,
            "runId": normalized_run_id,
            "status": status_label,
            "recordCount": len(final_records),
            "candidateCount": len(final_source_candidates),
            "importedCount": len(imported),
            "skippedCount": len(skipped),
            "failedCount": len(failed),
            "pendingRecordCount": pending_record_count,
            "completedExtractionAssignmentCount": completed_extraction_assignments,
            "recordOutcomes": record_outcomes[:80],
            "truncatedRecordOutcomeCount": max(0, len(record_outcomes) - 80),
        },
    )
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "runId": normalized_run_id,
        "status": status_label,
        "run": final_run,
        "runStatus": final_status,
        "sourceCollectionSummary": source_collection_summary,
        "storageArtifacts": storage_artifacts,
        "assignments": final_assignments,
        "recordCount": len(final_records),
        "candidateCount": len(final_source_candidates),
        "pendingRecordCount": pending_record_count,
        "importedCount": len(imported),
        "skippedCount": len(skipped),
        "failedCount": len(failed),
        "completedExtractionAssignmentCount": completed_extraction_assignments,
        "imported": imported,
        "skipped": skipped,
        "failed": failed,
        "executionEvents": execution_events,
        "workflow": workflow_api,
        "boundaries": {
            "externalSearchTriggered": False,
            "metadataOnlyDownload": True,
            "writesFormalKnowledge": False,
            "writesRag": False,
            "writesOfficialGraph": False,
        },
        "nextActions": [
            "Run source quality assessment on extracted source_manifest candidates.",
            "Keep formal Team Knowledge/RAG/official graph writes behind the later governance gate.",
        ],
    }

def list_candidate_store(
    team_id: str,
    *,
    candidate_type: str = "",
    current_state: str = "",
    quality_status: str = "",
    limit: int = 100,
    include_validation: bool = False,
    include_store: bool = False,
) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.assert_team_exists(normalized_team_id)
    normalized_candidate_type = s._trim_text(candidate_type, max_length=80)
    if normalized_candidate_type:
        normalized_candidate_type = s._normalize_candidate_type(normalized_candidate_type)
    normalized_state = s._trim_text(current_state, max_length=120)
    normalized_quality = s._trim_text(quality_status, max_length=120)
    normalized_limit = max(1, min(int(limit or 100), 500))
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        candidate_store = s._load_candidate_store(normalized_team_id)
        candidates = s._filtered_candidates(
            candidate_store,
            candidate_type=normalized_candidate_type,
            current_state=normalized_state,
            quality_status=normalized_quality,
        )[:normalized_limit]
        all_candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
    if include_validation:
        validation_summary = validate_candidate_store(normalized_team_id)["summary"]
    else:
        validation_summary = {
            "candidateCount": len(all_candidates),
            "validCandidateCount": 0,
            "invalidCandidateCount": 0,
            "errorCount": 0,
            "warningCount": 0,
            "skipped": True,
            "reason": "not_requested",
        }
    response = {
        "teamId": normalized_team_id,
        "workflowId": workflow["workflowId"],
        "filters": {
            "candidateType": normalized_candidate_type,
            "currentState": normalized_state,
            "qualityStatus": normalized_quality,
            "limit": normalized_limit,
        },
        "candidates": candidates,
        "candidateCount": len(candidates),
        "validationSummary": validation_summary,
    }
    if include_store:
        response["store"] = s._workflow_to_api(normalized_team_id, workflow, candidate_store)["candidateStore"]
    return response

def validate_candidate_store(team_id: str) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.assert_team_exists(normalized_team_id)
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        candidate_store = s._load_candidate_store(normalized_team_id)
        candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
        candidate_reports = [
            {
                "candidateId": str(candidate.get("candidateId") or ""),
                "candidateType": str(candidate.get("candidateType") or ""),
                "currentState": str(candidate.get("currentState") or ""),
                "qualityStatus": str(candidate.get("qualityStatus") or ""),
                "validation": s.validate_candidate_record(candidate),
            }
            for candidate in candidates
        ]
    error_count = sum(1 for item in candidate_reports for issue in item["validation"]["issues"] if issue["severity"] == "error")
    warning_count = sum(1 for item in candidate_reports for issue in item["validation"]["issues"] if issue["severity"] == "warning")
    invalid_count = sum(1 for item in candidate_reports if not item["validation"]["valid"])
    invalid_reports = [item for item in candidate_reports if not item["validation"]["valid"]]
    summary = {
        "candidateCount": len(candidate_reports),
        "validCandidateCount": len(candidate_reports) - invalid_count,
        "invalidCandidateCount": invalid_count,
        "errorCount": error_count,
        "warningCount": warning_count,
    }
    s._record_workflow_event(
        "candidate_store.validated",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            **summary,
            "invalidCandidateIds": s._workflow_log_sample_values(invalid_reports, "candidateId"),
        },
    )
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "workflowId": workflow["workflowId"],
        "summary": summary,
        "candidates": candidate_reports,
        "storagePath": s._relative_path(s._candidate_store_path(normalized_team_id)),
    }
