"""Source-collection runs and search public entrypoints.

Claim scope: start SC run, execute/background search, work-run summary, SC summary.
Do not put stage writeback, candidates register, or experiment packs here.

Late-bound facade keeps route imports and monkeypatches on
``team_workflow_orchestration_service`` stable.
"""

from __future__ import annotations

from typing import Any


def _service():
    from core.web.services import team_workflow_orchestration_service

    return team_workflow_orchestration_service


def start_source_collection_run(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    team = s.team_service.get_team(normalized_team_id)
    request_payload = dict(payload) if isinstance(payload, dict) else {}
    workflow_kind = s._source_collection_workflow_kind(request_payload, team)
    collection_mode = s._source_collection_collection_mode(request_payload.get("collectionMode"))
    title = s._trim_text(request_payload.get("title"), max_length=180) or (
        "Knowledge expansion source collection"
        if workflow_kind == s.WORKFLOW_KIND_KNOWLEDGE_EXPANSION
        else "Challenge Cup source collection"
    )
    goal = s._trim_text(request_payload.get("goal"), max_length=1000)
    topic = s._trim_text(request_payload.get("topic"), max_length=500)
    input_refs = s._normalize_text_list(request_payload.get("inputRefs"), max_items=120, max_length=240)
    roles = s._normalize_source_collection_roles(request_payload.get("agentRoles"))
    request_payload["agentIds"] = s._source_collection_team_agent_ids(team, roles, request_payload)
    default_owner_agent_id = s._source_collection_owner_agent_id(team, request_payload)
    owner_agent_id = s._trim_text(request_payload.get("ownerAgentId"), max_length=160) or default_owner_agent_id
    requested_by_agent = s._trim_text(request_payload.get("requestedByAgent"), max_length=160) or owner_agent_id
    prompt_cache_policy = s._source_collection_prompt_cache_policy(normalized_team_id, request_payload, roles)
    scope = s._normalize_metadata(request_payload.get("scope"))
    if goal:
        scope["goal"] = goal
    if topic:
        scope["topic"] = topic
    scope["teamId"] = normalized_team_id
    scope["workflowKind"] = workflow_kind
    scope["workflowPurpose"] = workflow_kind
    scope["collectionMode"] = collection_mode
    scope["promptCachePolicyRef"] = s._source_collection_prompt_cache_policy_ref(prompt_cache_policy)
    preliminary_search_plan = s._build_source_collection_search_plan(
        team_id=normalized_team_id,
        run_id="",
        payload=request_payload,
        scope=scope,
        input_refs=input_refs,
        roles=roles,
        prompt_cache_policy=prompt_cache_policy,
    )
    scope["dataSearchPlanRef"] = s._source_collection_search_plan_ref(preliminary_search_plan)
    session_cleanup = s._clean_source_collection_stage_agent_sessions_for_new_round(
        normalized_team_id,
        roles,
        request_payload,
    )
    run = s.data_processing_service.create_processing_run(
        s.data_processing_service.DEFAULT_PROFILE_ID,
        title=title,
        scope=scope,
        metadata={
            "startedFrom": "team_workflow_source_collection",
            "teamId": normalized_team_id,
            "workflowKind": workflow_kind,
            "workflowPurpose": workflow_kind,
            "collectionMode": collection_mode,
            "requestedByAgent": requested_by_agent,
            "ownerAgentId": owner_agent_id,
            "searchPlanId": preliminary_search_plan["planId"],
            "queryCount": preliminary_search_plan["queryCount"],
            "querySeedCount": len(preliminary_search_plan["querySeeds"]),
            "promptCachePolicyId": prompt_cache_policy["policyId"],
            "promptCacheRequirement": prompt_cache_policy["requirement"],
            "promptCacheModelId": prompt_cache_policy["modelId"],
            "promptCacheMode": prompt_cache_policy["promptCacheMode"],
            "promptCacheGateStatus": prompt_cache_policy["gate"]["status"],
            "sessionCleanupStatus": session_cleanup["status"],
            "sessionCleanupCleanedCount": session_cleanup["cleanedCount"],
        },
    )
    search_plan = s._build_source_collection_search_plan(
        team_id=normalized_team_id,
        run_id=run["runId"],
        payload=request_payload,
        scope=scope,
        input_refs=input_refs,
        roles=roles,
        plan_id=preliminary_search_plan["planId"],
        prompt_cache_policy=prompt_cache_policy,
    )
    search_plan["workflowKind"] = workflow_kind
    search_plan["collectionMode"] = collection_mode
    storage_artifacts = s._source_collection_storage_artifacts(normalized_team_id, run["runId"])
    search_plan["storageArtifacts"] = storage_artifacts
    search_plan["resultWritebackContract"]["evidenceStorage"] = storage_artifacts
    s._write_source_collection_search_plan(normalized_team_id, run["runId"], search_plan)
    assignments = [
        s.data_processing_service.create_collection_assignment(
            run["runId"],
            {
                "agentRole": role,
                "agentId": s._source_collection_agent_id(role, request_payload),
                "scope": s._source_collection_assignment_scope(role, scope, search_plan=search_plan),
                "inputRefs": input_refs,
                "expectedRecordTypes": ["source_manifest", "paper", "dataset", "url", "file"],
                "acceptance": {
                    "output": "CollectionOutput.records",
                    "handoff": "Import accepted DataRecord through Team workflow source-candidate bridge.",
                    "resultWritebackContract": search_plan["resultWritebackContract"],
                    "noFormalKnowledgeWrite": True,
                },
            },
        )
        for role in roles
    ]
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        workflow["ownerAgentId"] = owner_agent_id
        workflow["routingPolicy"] = s._sync_owner_policy(workflow.get("routingPolicy"), owner_agent_id)
        workflow["transferPolicy"] = s._sync_transfer_policy(workflow.get("transferPolicy"), owner_agent_id)
        workflow["updatedAt"] = s.utc_now_iso()
        workflow["activeWorkflowItems"] = s._upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=run["runId"],
            current_node="knowledge_collection",
            status="source_collection_started",
            transfer_id="",
        )
        s._write_json(s._workflow_path(normalized_team_id), workflow)
        candidate_store = s._load_candidate_store(normalized_team_id)
    s._record_workflow_event(
        "source_collection.run_started",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "runId": run["runId"],
            "assignmentCount": len(assignments),
            "requestedByAgent": requested_by_agent,
            "ownerAgentId": owner_agent_id,
            "searchPlanId": search_plan["planId"],
            "queryCount": search_plan["queryCount"],
            "querySeedCount": len(search_plan["querySeeds"]),
            "promptCacheRequirement": prompt_cache_policy["requirement"],
            "promptCacheMode": prompt_cache_policy["promptCacheMode"],
            "promptCacheGateStatus": prompt_cache_policy["gate"]["status"],
            "teamAgentBindingCount": sum(1 for item in assignments if str(item.get("agentId") or "") != str(item.get("agentRole") or "")),
            "sourceCollectionRunDirectory": storage_artifacts["runDirectory"],
            "sessionCleanupCleanedCount": session_cleanup["cleanedCount"],
        },
    )
    local_workspace_scan = s._import_source_collection_local_workspace_sources(
        normalized_team_id,
        run["runId"],
        request_payload,
        assignments=assignments,
    ) if collection_mode in {"local_workspace", "mixed"} else s._source_collection_local_scan_summary(status="skipped_mode")
    return {
        "run": s.data_processing_service.get_processing_run(run["runId"]),
        "searchPlan": search_plan,
        "storageArtifacts": storage_artifacts,
        "promptCachePolicy": prompt_cache_policy,
        "sessionCleanup": session_cleanup,
        "localWorkspaceScan": local_workspace_scan,
        "assignments": assignments,
        "assignmentCount": len(assignments),
        "workflow": s._workflow_to_api(normalized_team_id, workflow, candidate_store),
        "nextActions": [
            "Functional data collection agents submit CollectionOutput records.",
            "Accepted DataRecords are imported through source-candidate bridge.",
            "Imported source_manifest candidates continue through source extraction and screening.",
        ],
        "boundaries": {
            "writesFormalKnowledge": False,
            "writesRag": False,
            "writesKnowledgeGraph": False,
        },
    }

def execute_source_collection_search(team_id: str, run_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_run_id = s._normalize_required_id(run_id, "Data processing run id is required.")
    team = s.team_service.get_team(normalized_team_id)
    try:
        run = s.data_processing_service.get_processing_run(normalized_run_id)
    except s.data_processing_service.DataProcessingError as exc:
        raise s.TeamWorkflowOrchestrationError(str(exc)) from exc
    run_scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    run_team_id = s._trim_text(run_scope.get("teamId"), max_length=128)
    if run_team_id and run_team_id != normalized_team_id:
        raise s.TeamWorkflowOrchestrationError("Data processing run does not belong to this team.")

    try:
        assignments_payload = s.data_processing_service.list_collection_assignments(normalized_run_id)
        records_payload = s.data_processing_service.list_records(normalized_run_id)
    except s.data_processing_service.DataProcessingError as exc:
        raise s.TeamWorkflowOrchestrationError(str(exc)) from exc
    assignments = [item for item in list(assignments_payload.get("assignments") or []) if isinstance(item, dict)]
    records = [item for item in list(records_payload.get("records") or []) if isinstance(item, dict)]
    s._persist_source_collection_work_run(
        normalized_team_id,
        normalized_run_id,
        status="running",
        current_phase="searching",
        run=run,
        team=team,
        assignments=assignments,
        records=records,
        summary="正在执行资料搜索，搜索来源元数据并写入候选资料库。",
        active=True,
    )
    try:
        result = s._execute_source_collection_search_impl(normalized_team_id, normalized_run_id, payload)
    except Exception as exc:
        failure_result = {
            "status": "failed",
            "failedQueryCount": 1,
            "executedQueryCount": 0,
            "recordCount": len(records),
            "importedCount": 0,
            "sourceCollectionSummary": s._source_collection_assignment_stage_summary(assignments),
        }
        s._persist_source_collection_work_run(
            normalized_team_id,
            normalized_run_id,
            status="failed",
            current_phase="failed",
            run=run,
            team=team,
            assignments=assignments,
            records=records,
            summary="资料搜索执行失败。",
            active=False,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        s._sync_source_collection_stage_round_after_search(
            normalized_team_id,
            normalized_run_id,
            failure_result,
            terminal_status="failed",
            terminal_summary="资料搜索执行失败，等待检查搜索错误。",
        )
        raise

    final_run = result.get("run") if isinstance(result.get("run"), dict) else run
    final_assignments = [item for item in list(result.get("assignments") or []) if isinstance(item, dict)]
    try:
        final_records = s.data_processing_service.list_records(normalized_run_id).get("records") if normalized_run_id else []
    except s.data_processing_service.DataProcessingError:
        final_records = []
    terminal_status = s._source_collection_work_run_terminal_status(result)
    terminal_phase = s._source_collection_work_run_terminal_phase(result)
    terminal_summary = s._source_collection_work_run_terminal_summary(result)
    s._persist_source_collection_work_run(
        normalized_team_id,
        normalized_run_id,
        status=terminal_status,
        current_phase=terminal_phase,
        run=final_run,
        team=team,
        assignments=final_assignments,
        records=[item for item in list(final_records or []) if isinstance(item, dict)],
        summary=terminal_summary,
        active=False,
        extra={
            "attemptedQueryCount": s._source_collection_count(result.get("attemptedQueryCount")),
            "executedQueryCount": s._source_collection_count(result.get("executedQueryCount")),
            "failedQueryCount": s._source_collection_count(result.get("failedQueryCount")),
            "recordCount": s._source_collection_count(result.get("recordCount")),
            "importedCount": s._source_collection_count(result.get("importedCount")),
            "resultCount": s._source_collection_count(result.get("resultCount")),
        },
    )
    s._sync_source_collection_stage_round_after_search(
        normalized_team_id,
        normalized_run_id,
        result,
        terminal_status=terminal_status,
        terminal_summary=terminal_summary,
    )
    return result

def start_source_collection_search_background(team_id: str, run_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_run_id = s._normalize_required_id(run_id, "Data processing run id is required.")
    team = s.team_service.get_team(normalized_team_id)
    request_payload = dict(payload) if isinstance(payload, dict) else {}
    provider = s._trim_text(request_payload.get("provider"), max_length=80) or s.SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF
    if provider != s.SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF:
        raise s.TeamWorkflowOrchestrationError(f"Unsupported source collection search provider: {provider}")
    try:
        run = s.data_processing_service.get_processing_run(normalized_run_id)
        assignments_payload = s.data_processing_service.list_collection_assignments(normalized_run_id)
        records_payload = s.data_processing_service.list_records(normalized_run_id)
        run_status = s.data_processing_service.get_processing_status(normalized_run_id)
    except s.data_processing_service.DataProcessingError as exc:
        raise s.TeamWorkflowOrchestrationError(str(exc)) from exc
    run_scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    run_team_id = s._trim_text(run_scope.get("teamId"), max_length=128)
    if run_team_id and run_team_id != normalized_team_id:
        raise s.TeamWorkflowOrchestrationError("Data processing run does not belong to this team.")
    assignments = [item for item in list(assignments_payload.get("assignments") or []) if isinstance(item, dict)]
    records = [item for item in list(records_payload.get("records") or []) if isinstance(item, dict)]
    storage_artifacts = s._source_collection_storage_artifacts(normalized_team_id, normalized_run_id)
    with s._WORKFLOW_LOCK:
        existing_active_snapshot = s._source_collection_work_run_store().load_active_snapshot(s.SOURCE_COLLECTION_WORK_RUN_KIND)
        existing_active_snapshot = s._decorate_source_collection_work_run_snapshot(
            existing_active_snapshot,
            team_id=normalized_team_id,
            run_id=normalized_run_id,
        )
        if s._source_collection_background_snapshot_is_active(existing_active_snapshot, normalized_team_id, normalized_run_id):
            s._record_workflow_event(
                "source_collection.search_background_already_running",
                normalized_team_id,
                fields={
                    "runId": normalized_run_id,
                    "provider": provider,
                    "assignmentCount": len(assignments),
                    "recordCount": len(records),
                    "activeStatus": str(existing_active_snapshot.get("status") or ""),
                    "activePhase": str(existing_active_snapshot.get("currentPhase") or ""),
                },
            )
            return s._source_collection_search_background_response(
                team_id=normalized_team_id,
                run_id=normalized_run_id,
                provider=provider,
                run=run,
                run_status=run_status,
                storage_artifacts=storage_artifacts,
                assignments=assignments,
                records=records,
                active_snapshot=existing_active_snapshot,
                already_running=True,
            )
        active_snapshot = s._persist_source_collection_work_run(
            normalized_team_id,
            normalized_run_id,
            status="running",
            current_phase="queued",
            run=run,
            team=team,
            assignments=assignments,
            records=records,
            summary="资料搜索已进入后台执行，页面可继续操作。",
            active=True,
            extra={
                "executionMode": "background",
                "provider": provider,
                "queuedSearchExecution": True,
            },
        )
    active_snapshot = s._decorate_source_collection_work_run_snapshot(
        active_snapshot,
        team_id=normalized_team_id,
        run_id=normalized_run_id,
    )
    worker = s.threading.Thread(
        target=s._run_source_collection_search_background,
        args=(normalized_team_id, normalized_run_id, request_payload),
        name=f"source-collection-search-{normalized_run_id[:24]}",
        daemon=True,
    )
    worker.start()
    s._record_workflow_event(
        "source_collection.search_background_accepted",
        normalized_team_id,
        fields={
            "runId": normalized_run_id,
            "provider": provider,
            "assignmentCount": len(assignments),
            "recordCount": len(records),
            "threadName": worker.name,
        },
    )
    return s._source_collection_search_background_response(
        team_id=normalized_team_id,
        run_id=normalized_run_id,
        provider=provider,
        run=run,
        run_status=run_status,
        storage_artifacts=storage_artifacts,
        assignments=assignments,
        records=records,
        active_snapshot=active_snapshot,
        already_running=False,
    )

def load_source_collection_work_run_summary() -> dict[str, Any]:
    s = _service()
    store = s._source_collection_work_run_store()
    active = store.load_active_snapshot(s.SOURCE_COLLECTION_WORK_RUN_KIND)
    latest = store.load_latest_snapshot(s.SOURCE_COLLECTION_WORK_RUN_KIND)
    active_team_id = s._trim_text(active.get("teamId"), max_length=96) if isinstance(active, dict) else ""
    active_run_id = s._trim_text(active.get("runId"), max_length=96) if isinstance(active, dict) else ""
    latest_team_id = s._trim_text(latest.get("teamId"), max_length=96) if isinstance(latest, dict) else ""
    latest_run_id = s._trim_text(latest.get("runId"), max_length=96) if isinstance(latest, dict) else ""
    active = s._decorate_source_collection_work_run_snapshot(
        active,
        team_id=active_team_id,
        run_id=active_run_id,
    )
    latest = s._decorate_source_collection_work_run_snapshot(
        latest,
        team_id=latest_team_id,
        run_id=latest_run_id,
    )
    active_for_lifecycle = None if s._source_collection_work_run_snapshot_is_stale(active) else active
    return {
        "active": active_for_lifecycle,
        "latest": latest,
        "activeItems": [active_for_lifecycle] if isinstance(active_for_lifecycle, dict) else [],
    }

def get_source_collection_summary(team_id: str, *, run_id: str = "") -> dict[str, Any]:
    """Return the fast first-paint source collection state without heavy repair reads."""

    s = _service()
    started_at = s.time.perf_counter()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.assert_team_exists(normalized_team_id)
    normalized_run_id = s._trim_text(run_id, max_length=160)
    selected_run: dict[str, Any] | None = None
    if normalized_run_id:
        try:
            selected_run = s.data_processing_service.get_processing_run(normalized_run_id)
        except s.data_processing_service.DataProcessingError as exc:
            raise s.TeamWorkflowOrchestrationError(str(exc)) from exc
        if not s._source_collection_run_belongs_to_team(selected_run, normalized_team_id):
            raise s.TeamWorkflowOrchestrationError("Data processing run does not belong to this team.")
    else:
        try:
            runs_payload = s.data_processing_service.list_processing_runs(
                limit=s.SOURCE_COLLECTION_SUMMARY_DEFAULT_RUN_LOOKUP_LIMIT,
                metadata_filters={"startedFrom": "team_workflow_source_collection", "teamId": normalized_team_id},
            )
        except s.data_processing_service.DataProcessingError as exc:
            raise s.TeamWorkflowOrchestrationError(str(exc)) from exc
        team_runs = [
            item for item in list(runs_payload.get("runs") or [])
            if isinstance(item, dict) and s._source_collection_run_belongs_to_team(item, normalized_team_id)
        ]
        selected_run = next(
            (item for item in team_runs if s._source_collection_run_has_usable_outputs(item)),
            team_runs[0] if team_runs else None,
        )
        normalized_run_id = s._trim_text((selected_run or {}).get("runId"), max_length=160)
    run_status: dict[str, Any] = {}
    run_summary: dict[str, Any] = {}
    if normalized_run_id:
        selected_run_status = selected_run.get("processingStatus") if isinstance(selected_run, dict) else None
        if (
            isinstance(selected_run_status, dict)
            and s._trim_text(selected_run_status.get("runId"), max_length=160) == normalized_run_id
        ):
            run_status = selected_run_status
        else:
            try:
                run_status = s.data_processing_service.get_processing_status(normalized_run_id)
            except s.data_processing_service.DataProcessingError as exc:
                raise s.TeamWorkflowOrchestrationError(str(exc)) from exc
        run_summary = run_status.get("summary") if isinstance(run_status.get("summary"), dict) else {}
        s._reconcile_source_collection_stage_session_tasks_for_run(normalized_team_id, normalized_run_id)
    if normalized_run_id:
        projection = s._source_collection_stage_cards_projection(
            normalized_team_id,
            normalized_run_id,
            run_status=run_status,
            run=selected_run,
        )
    else:
        projection = {
            "runId": "",
            "cards": [],
            "latestTasks": {},
            "summary": {"closedLoopCount": 0, "stageCount": 0},
        }
    projection_summary = projection.get("summary") if isinstance(projection.get("summary"), dict) else {}
    stage_round_ref = s._source_collection_stage_round_ref_for_run(normalized_team_id, normalized_run_id) if normalized_run_id else {}
    phase_close_gate = s._source_collection_phase_close_gate(
        normalized_run_id,
        projection=projection,
        stage_round_ref=stage_round_ref,
    )
    active_snapshot = s._source_collection_work_run_store().load_active_snapshot(s.SOURCE_COLLECTION_WORK_RUN_KIND) if normalized_run_id else {}
    active_snapshot = (
        s._decorate_source_collection_work_run_snapshot(
            active_snapshot,
            team_id=normalized_team_id,
            run_id=normalized_run_id,
        )
        if isinstance(active_snapshot, dict)
        else {}
    )
    active_work_run = (
        active_snapshot
        if s._source_collection_background_snapshot_is_active(active_snapshot, normalized_team_id, normalized_run_id)
        else {}
    )
    payload = {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "runId": normalized_run_id,
        "status": s._source_collection_summary_payload_status(
            normalized_run_id,
            run_status=run_status,
            active_work_run=active_work_run,
            stage_round_ref=stage_round_ref,
            projection=projection,
        ),
        "run": selected_run or {},
        "runStatus": run_status,
        "scope": {
            "kind": "source_run",
            "runId": normalized_run_id,
            "stageRoundId": s._trim_text(stage_round_ref.get("stageRoundId"), max_length=160),
            "includesHistorical": False,
            "eligibleForPhaseCloseGate": bool(normalized_run_id),
        },
        "summary": {
            "recordCount": s._source_collection_count(run_summary.get("recordCount")),
            "assignmentCount": s._source_collection_count(run_summary.get("assignmentCount")),
            "openAssignmentCount": s._source_collection_count(run_summary.get("openAssignmentCount")),
            "outputCount": s._source_collection_count(run_summary.get("outputCount")),
            "sourceCandidateCount": s._source_collection_count(projection_summary.get("sourceCandidateCount")),
            "assessedSourceCandidateCount": s._source_collection_count(projection_summary.get("assessedSourceCandidateCount")),
            "approvedSourceCandidateCount": s._source_collection_count(projection_summary.get("approvedSourceCandidateCount")),
            "graphNodeCount": s._source_collection_count(projection_summary.get("graphNodeCount")),
            "stewardPackCount": s._source_collection_count(projection_summary.get("stewardPackCount")),
            "formalKnowledgeSyncCount": s._source_collection_count(projection_summary.get("formalKnowledgeSyncCount")),
        },
        "stageCards": projection.get("cards", []),
        "stageCardSummary": projection_summary,
        "phaseCloseGate": phase_close_gate,
        "latestTasks": projection.get("latestTasks", {}),
        "stageRound": stage_round_ref,
        "activeWorkRun": active_work_run,
        "storageArtifacts": s._source_collection_storage_artifacts(normalized_team_id, normalized_run_id) if normalized_run_id else {},
        "boundaries": s._research_stage_boundaries(),
        "updatedAt": s.utc_now_iso(),
    }
    s._record_source_collection_summary_timing(normalized_team_id, normalized_run_id, payload, started_at)
    return payload
