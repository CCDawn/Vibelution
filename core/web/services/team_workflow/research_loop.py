"""Research stage round status/start and coordination/memory retries.

Late-bound facade keeps route imports and monkeypatches on
``team_workflow_orchestration_service`` stable during P0 mechanical splits.
"""

from __future__ import annotations

from typing import Any


def _service():
    from core.web.services import team_workflow_orchestration_service

    return team_workflow_orchestration_service


def get_research_stage_round_status(team_id: str) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    team = s._source_collection_team_identity_snapshot(normalized_team_id)
    s._reconcile_source_collection_stage_session_tasks(normalized_team_id)
    s._reconcile_superseded_research_stage_rounds(normalized_team_id)
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        store = s._load_stage_round_store(normalized_team_id)
    rounds = s._stage_rounds(store)
    synced_from_work_run = False
    for stage_round in rounds:
        if str(stage_round.get("stageType") or "") != "knowledge_collection":
            continue
        if str(stage_round.get("status") or "") not in s.RESEARCH_STAGE_ACTIVE_STATUSES:
            continue
        for source_run_id in [str(item) for item in list(stage_round.get("sourceRunIds") or []) if str(item or "").strip()]:
            synced_from_work_run = s._sync_source_collection_stage_round_from_latest_work_run(normalized_team_id, source_run_id) is not None or synced_from_work_run
    if synced_from_work_run:
        with s._WORKFLOW_LOCK:
            workflow = s._load_or_create_workflow(normalized_team_id)
            store = s._load_stage_round_store(normalized_team_id)
        rounds = s._stage_rounds(store)
    s._attach_source_collection_stage_card_projections(normalized_team_id, rounds)
    phases = [
        s._stage_phase_status(
            normalized_team_id,
            stage_type,
            rounds,
            workflow=workflow,
            team=team,
        )
        for stage_type in s.RESEARCH_STAGE_TYPES
    ]
    active_rounds = [item for item in rounds if str(item.get("status") or "") in s.RESEARCH_STAGE_ACTIVE_STATUSES]
    latest_round = s._latest_stage_round(rounds)
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "active" if active_rounds else "idle",
        "currentStage": s._current_research_stage(phases, workflow),
        "phases": phases,
        "activeRounds": active_rounds,
        "latestRound": latest_round,
        "roundCount": len(rounds),
        "storagePath": s._relative_path(s._stage_round_store_path(normalized_team_id)),
        "boundaries": s._research_stage_boundaries(),
        "updatedAt": str(store.get("updatedAt") or ""),
    }

def start_research_stage_round(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    team = s.team_service.get_team(normalized_team_id)
    request_payload = dict(payload) if isinstance(payload, dict) else {}
    stage_type = s._normalize_stage_type(request_payload.get("stageType"))
    start_mode = s._normalize_stage_start_mode(request_payload.get("mode") or request_payload.get("startMode"))
    requested_by_agent = s._trim_text(request_payload.get("requestedByAgent"), max_length=160) or s._source_collection_owner_agent_id(team, request_payload)
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        store = s._load_stage_round_store(normalized_team_id)
        rounds = s._stage_rounds(store)
        active_round = s._active_stage_round(rounds, stage_type)
        if active_round and start_mode != "new_round":
            if stage_type != "knowledge_collection":
                memory_context = s._research_stage_memory_context(
                    normalized_team_id,
                    stage_type=stage_type,
                    research_question=s._first_non_empty_text(
                        active_round.get("goal"),
                        active_round.get("topic"),
                    ),
                    actor_agent_id=requested_by_agent,
                )
                active_round["memoryContext"] = memory_context
                planning_contract = (
                    active_round.get("planningContract")
                    if isinstance(active_round.get("planningContract"), dict)
                    else s._stage_planning_contract(stage_type, active_round)
                )
                planning_contract["memoryContextId"] = memory_context["contextId"]
                active_round["planningContract"] = planning_contract
                active_round["coordinationContract"] = s._stage_coordination_contract(
                    team,
                    active_round,
                    trigger="manual",
                )
                active_round["coordinationContract"]["startResult"] = s._stage_coordination_manual_pending_result(
                    active_round["coordinationContract"]
                )
                active_round["updatedAt"] = s.utc_now_iso()
                store["rounds"] = rounds
                store["updatedAt"] = active_round["updatedAt"]
                s._write_json(s._stage_round_store_path(normalized_team_id), store)
            continued_payload = s._continued_stage_round_payload(active_round, stage_type)
            continued_ref = continued_payload.get("continuedSourceRunRef") if isinstance(continued_payload.get("continuedSourceRunRef"), dict) else {}
            s._record_workflow_event(
                "research_stage_round.continued",
                normalized_team_id,
                fields={
                    "workflowId": workflow["workflowId"],
                    "stageRoundId": active_round.get("stageRoundId", ""),
                    "stageType": stage_type,
                    "status": active_round.get("status", ""),
                    "sourceRunCount": len(list(active_round.get("sourceRunIds") or [])),
                    "continuedSourceRunId": continued_ref.get("runId", ""),
                    "continuedRecordCount": continued_ref.get("recordCount", 0),
                    "continuedOpenAssignmentCount": continued_ref.get("openAssignmentCount", 0),
                },
            )
            status_payload = s._stage_phase_status(normalized_team_id, stage_type, rounds, workflow=workflow, team=team)
            return {
                "created": False,
                "continued": True,
                "stageRound": active_round,
                "phase": status_payload,
                "workflow": s._workflow_to_api(normalized_team_id, workflow, s._load_candidate_store(normalized_team_id)),
                "status": get_research_stage_round_status(normalized_team_id),
                "nextActions": s._stage_next_actions(stage_type, reused=True),
                "boundaries": s._research_stage_boundaries(),
                **continued_payload,
            }
        previous_round = s._latest_stage_round([item for item in rounds if str(item.get("stageType") or "") == stage_type])
        round_payload = s._build_stage_round(
            normalized_team_id,
            stage_type,
            request_payload,
            rounds,
            previous_round=previous_round,
            requested_by_agent=requested_by_agent,
            team=team,
        )
        result_payload: dict[str, Any] = {}
        status = "running"
        warnings: list[dict[str, str]] = []
        if stage_type == "knowledge_collection":
            source_payload = s._stage_source_collection_payload(round_payload, request_payload, team)
            source_result = s.start_source_collection_run(normalized_team_id, source_payload)
            search_execution = s.start_source_collection_search_background(
                normalized_team_id,
                source_result["run"]["runId"],
                {
                    "backgroundExecution": True,
                    "provider": s.SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF,
                    "maxQueries": s._normalize_int(
                        request_payload.get("maxQueries"),
                        default=s.SOURCE_COLLECTION_SEARCH_EXECUTION_DEFAULT_MAX_QUERIES,
                        minimum=1,
                        maximum=s.SOURCE_COLLECTION_SEARCH_EXECUTION_MAX_QUERIES,
                    ),
                    "maxResultsPerQuery": s._normalize_int(
                        request_payload.get("maxResultsPerQuery"),
                        default=s.SOURCE_COLLECTION_SEARCH_EXECUTION_DEFAULT_RESULTS_PER_QUERY,
                        minimum=1,
                        maximum=s.SOURCE_COLLECTION_SEARCH_EXECUTION_MAX_RESULTS_PER_QUERY,
                    ),
                },
            )
            result_payload["sourceCollectionRun"] = source_result
            result_payload["sourceCollectionSearchExecution"] = search_execution
            result_payload["run"] = source_result["run"]
            result_payload["searchPlan"] = source_result["searchPlan"]
            result_payload["promptCachePolicy"] = source_result.get("promptCachePolicy", {})
            result_payload["assignments"] = source_result["assignments"]
            round_payload["sourceRunIds"] = [source_result["run"]["runId"]]
            round_payload["dataSearchPlanRef"] = s._source_collection_search_plan_ref(source_result["searchPlan"])
            round_payload["promptCachePolicy"] = source_result.get("promptCachePolicy", {})
            round_payload["sourceCollectionSearchExecution"] = {
                "runId": search_execution["runId"],
                "status": search_execution["status"],
                "executionMode": search_execution["executionMode"],
                "accepted": bool(search_execution.get("accepted")),
                "provider": search_execution["provider"],
                "activeWorkRunId": str((search_execution.get("activeWorkRun") or {}).get("runId") or ""),
            }
            round_payload["assignmentIds"] = [str(item.get("assignmentId") or "") for item in source_result["assignments"] if item.get("assignmentId")]
            round_payload["agentRoleAssignments"] = [
                {
                    "agentRole": str(item.get("agentRole") or ""),
                    "agentId": str(item.get("agentId") or ""),
                    "assignmentId": str(item.get("assignmentId") or ""),
                }
                for item in source_result["assignments"]
            ]
            warnings.extend(s._stage_agent_binding_warnings(source_result["assignments"]))
            round_payload["workflowItemRef"] = {"candidateId": source_result["run"]["runId"], "currentNode": "knowledge_collection"}
            workflow = s._load_or_create_workflow(normalized_team_id)
        else:
            status = "planning"
            memory_context = s._research_stage_memory_context(
                normalized_team_id,
                stage_type=stage_type,
                research_question=s._first_non_empty_text(
                    round_payload.get("goal"),
                    round_payload.get("topic"),
                ),
                actor_agent_id=requested_by_agent,
            )
            round_payload["memoryContext"] = memory_context
            round_payload["planningContract"] = s._stage_planning_contract(stage_type, round_payload)
            round_payload["planningContract"]["memoryContextId"] = memory_context["contextId"]
            workflow["activeWorkflowItems"] = s._upsert_active_item(
                workflow.get("activeWorkflowItems"),
                candidate_id=round_payload["stageRoundId"],
                current_node=s.RESEARCH_STAGE_DEFAULTS[stage_type]["currentNode"],
                status=f"{stage_type}_planning_started",
                transfer_id="",
            )
            workflow["updatedAt"] = s.utc_now_iso()
            s._write_json(s._workflow_path(normalized_team_id), workflow)
        round_payload["warnings"] = warnings
        round_payload["teamMemoryRecord"] = s._stage_memory_record(round_payload, workflow)
        round_payload["teamMemoryRecordId"] = round_payload["teamMemoryRecord"]["recordId"]
        coordination_contract = s._stage_coordination_contract(team, round_payload, trigger="manual")
        coordination_result = s._stage_coordination_manual_pending_result(coordination_contract)
        coordination_contract["startResult"] = coordination_result
        round_payload["coordinationContract"] = coordination_contract
        round_payload["status"] = status
        now = s.utc_now_iso()
        round_payload["updatedAt"] = now
        store["rounds"] = rounds + [round_payload]
        store["updatedAt"] = now
        s._write_json(s._stage_round_store_path(normalized_team_id), store)
        candidate_store = s._load_candidate_store(normalized_team_id)
    s._record_workflow_event(
        "research_stage_round.started",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "stageRoundId": round_payload["stageRoundId"],
            "stageType": stage_type,
            "status": round_payload["status"],
            "sourceRunCount": len(list(round_payload.get("sourceRunIds") or [])),
            "querySeedCount": len(list(round_payload.get("querySeeds") or [])),
            "warningCount": len(warnings),
            "coordinationStarted": bool(coordination_result.get("started")),
            "coordinationRoomId": str(coordination_result.get("roomId") or ""),
            "coordinationRoundId": str(coordination_result.get("roundId") or ""),
            "coordinationErrorType": str(coordination_result.get("errorType") or ""),
            "sourceSearchAccepted": bool((result_payload.get("sourceCollectionSearchExecution") or {}).get("accepted")),
            "requestedByAgent": requested_by_agent,
            "memoryContextId": str((round_payload.get("memoryContext") or {}).get("contextId") or ""),
            "memoryKnowledgeItemCount": int(((round_payload.get("memoryContext") or {}).get("retrieval") or {}).get("knowledgeItemCount") or 0),
            "memoryNegativeExperimentCount": int(((round_payload.get("memoryContext") or {}).get("retrieval") or {}).get("negativeExperimentCount") or 0),
        },
    )
    if stage_type == "knowledge_collection":
        source_run = result_payload.get("run") if isinstance(result_payload.get("run"), dict) else {}
        synced_round = s._sync_source_collection_stage_round_from_latest_work_run(normalized_team_id, str(source_run.get("runId") or ""))
        if synced_round is not None:
            round_payload = synced_round
    stage_status_payload = get_research_stage_round_status(normalized_team_id)
    phase_payload = next(
        (item for item in list(stage_status_payload.get("phases") or []) if isinstance(item, dict) and item.get("stageType") == stage_type),
        s._stage_phase_status(normalized_team_id, stage_type, [round_payload], workflow=workflow, team=team),
    )
    return {
        "created": True,
        "stageRound": round_payload,
        "phase": phase_payload,
        "workflow": s._workflow_to_api(normalized_team_id, workflow, candidate_store),
        "status": stage_status_payload,
        "nextActions": s._stage_next_actions(stage_type, reused=False),
        "boundaries": s._research_stage_boundaries(),
        **result_payload,
    }

def retry_research_stage_round_coordination(team_id: str, stage_round_id: str) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_round_id = s._normalize_required_id(stage_round_id, "Stage round id is required.")
    team = s.team_service.get_team(normalized_team_id)
    with s._WORKFLOW_LOCK:
        store = s._load_stage_round_store(normalized_team_id)
        rounds = s._stage_rounds(store)
        stage_round = s._find_stage_round(rounds, normalized_round_id)
        if stage_round is None:
            raise s.TeamWorkflowOrchestrationError("Stage round not found.")
        coordination_contract = s._stage_coordination_contract(team, stage_round, trigger="explicit_retry")
        coordination_result = s._try_start_stage_coordination_round(team, coordination_contract)
        coordination_contract["startResult"] = coordination_result
        stage_round["coordinationContract"] = coordination_contract
        if coordination_result.get("started"):
            stage_round["coordinationRoundId"] = str(coordination_result.get("roundId") or "")
            stage_round["coordinationRoomId"] = str(coordination_result.get("roomId") or "")
            stage_round["status"] = "running" if str(stage_round.get("stageType") or "") == "knowledge_collection" else "planning"
            stage_round["warnings"] = [
                item
                for item in list(stage_round.get("warnings") or [])
                if isinstance(item, dict) and str(item.get("code") or "") != "coordination_round_not_started"
            ]
        else:
            stage_round["status"] = "needs_attention"
            warnings = [
                item
                for item in list(stage_round.get("warnings") or [])
                if isinstance(item, dict) and str(item.get("code") or "") != "coordination_round_not_started"
            ]
            warnings.append(
                {
                    "code": "coordination_round_not_started",
                    "severity": "warning",
                    "message": s._trim_text(coordination_result.get("reason"), max_length=240) or "Coordination round was not started.",
                }
            )
            stage_round["warnings"] = warnings
        stage_round["updatedAt"] = s.utc_now_iso()
        store["rounds"] = rounds
        store["updatedAt"] = stage_round["updatedAt"]
        s._write_json(s._stage_round_store_path(normalized_team_id), store)
    s._record_workflow_event(
        "research_stage_round.coordination_retry_recorded",
        normalized_team_id,
        fields={
            "stageRoundId": normalized_round_id,
            "stageType": stage_round.get("stageType", ""),
            "status": stage_round.get("status", ""),
            "coordinationStarted": bool(coordination_result.get("started")),
            "coordinationRoomId": str(coordination_result.get("roomId") or ""),
            "coordinationRoundId": str(coordination_result.get("roundId") or ""),
            "coordinationErrorType": str(coordination_result.get("errorType") or ""),
        },
    )
    return {
        "stageRound": stage_round,
        "coordinationContract": stage_round["coordinationContract"],
        "status": get_research_stage_round_status(normalized_team_id),
    }

def retry_research_stage_round_memory_record(team_id: str, stage_round_id: str) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_round_id = s._normalize_required_id(stage_round_id, "Stage round id is required.")
    s.team_service.get_team(normalized_team_id)
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        store = s._load_stage_round_store(normalized_team_id)
        rounds = s._stage_rounds(store)
        stage_round = s._find_stage_round(rounds, normalized_round_id)
        if stage_round is None:
            raise s.TeamWorkflowOrchestrationError("Stage round not found.")
        stage_round["teamMemoryRecord"] = s._stage_memory_record(stage_round, workflow)
        stage_round["teamMemoryRecordId"] = stage_round["teamMemoryRecord"]["recordId"]
        stage_round["updatedAt"] = s.utc_now_iso()
        store["rounds"] = rounds
        store["updatedAt"] = stage_round["updatedAt"]
        s._write_json(s._stage_round_store_path(normalized_team_id), store)
    s._record_workflow_event(
        "research_stage_round.memory_retry_recorded",
        normalized_team_id,
        fields={"stageRoundId": normalized_round_id, "stageType": stage_round.get("stageType", "")},
    )
    return {
        "stageRound": stage_round,
        "teamMemoryRecord": stage_round["teamMemoryRecord"],
        "status": get_research_stage_round_status(normalized_team_id),
    }
