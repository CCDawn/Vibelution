"""Source-collection stage session tasks: seed context, start, writeback, get context, post-turn reconcile.

Late-bound facade keeps route imports and monkeypatches on
``team_workflow_orchestration_service`` stable during P0 mechanical splits.
"""

from __future__ import annotations

from typing import Any


def _service():
    from core.web.services import team_workflow_orchestration_service

    return team_workflow_orchestration_service


def _source_collection_task_experiment_session_fields(
    task: dict[str, Any],
    *,
    research_project: dict[str, Any],
    return_to: str = "",
    return_label: str = "",
) -> dict[str, Any]:
    s = _service()
    session_id = s._trim_text(task.get("sessionId"), max_length=160)
    detail = s.session_service.get_session_detail(session_id) if session_id else None
    session_title = (
        s._trim_text(task.get("sessionTitle"), max_length=120)
        or s._trim_text((detail or {}).get("title"), max_length=120)
    )
    return {
        "researchProjectId": s._trim_text(
            task.get("researchProjectId") or research_project.get("projectId"),
            max_length=160,
        ),
        "experimentName": s._trim_text(
            task.get("experimentName") or research_project.get("name"),
            max_length=160,
        ),
        "sessionId": session_id,
        "sessionTitle": session_title,
        "sessionAttempt": s._normalize_int(
            task.get("sessionAttempt"),
            default=1,
            minimum=1,
            maximum=10000,
        ),
        "sessionCreated": False,
        "retryOfSessionId": s._trim_text(task.get("retryOfSessionId"), max_length=160),
        "chatRoute": s._source_collection_stage_task_chat_route(
            session_id,
            return_to=return_to,
            return_label=return_label,
        ),
    }


def seed_source_collection_agent_session_context(
    team_id: str,
    run_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_run_id = s._normalize_required_id(run_id, "Data processing run id is required.")
    team = s.team_service.get_team(normalized_team_id)
    request_payload = dict(payload) if isinstance(payload, dict) else {}
    stage_id = s._normalize_source_collection_stage_id(request_payload.get("stageId"), default="finding")
    agent_id = s._trim_text(request_payload.get("agentId"), max_length=160)
    agent_role = s._normalize_source_collection_agent_role(request_payload.get("agentRole"))
    if stage_id not in s.SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES:
        raise s.TeamWorkflowOrchestrationError(f"Unsupported source collection stage: {stage_id}")
    if not agent_id:
        raise s.TeamWorkflowOrchestrationError("Agent id is required for source collection session context.")

    agent = s.agent_directory_service.get_agent(agent_id)
    if not isinstance(agent, dict):
        raise s.TeamWorkflowOrchestrationError(f"Agent not found: {agent_id}")

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
    if not agent_role:
        agent_role = s._source_collection_agent_role_for_id(assignments, agent_id, stage_id)
    allowed_roles = s.SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES[stage_id]
    if agent_role and agent_role not in allowed_roles:
        raise s.TeamWorkflowOrchestrationError(f"Agent role {agent_role} is not assigned to source collection stage {stage_id}.")
    research_project = s.resolve_research_project_identity_from_record(normalized_team_id, run)
    resolved_role_key = agent_role or s._trim_text(agent.get("roleKey"), max_length=80)
    try:
        experiment_session = s.resolve_research_project_agent_session(
            normalized_team_id,
            research_project_id=research_project["projectId"],
            agent_id=agent_id,
            role_key=resolved_role_key,
            role_label=s.research_project_agent_role_label(resolved_role_key, agent),
        )
    except s.ResearchProjectAgentSessionError as exc:
        raise s.TeamWorkflowOrchestrationError(str(exc)) from exc
    session_id = experiment_session["sessionId"]

    matching_assignments = [
        item for item in assignments
        if (
            (agent_role and s._trim_text(item.get("agentRole"), max_length=80) == agent_role)
            or s._trim_text(item.get("agentId"), max_length=160) == agent_id
        )
    ]
    storage_artifacts = s._source_collection_storage_artifacts(normalized_team_id, normalized_run_id)
    source_candidates = s._source_collection_candidates_for_run(normalized_team_id, normalized_run_id)
    active_snapshot = s._source_collection_work_run_store().load_active_snapshot(s.SOURCE_COLLECTION_WORK_RUN_KIND)
    active_snapshot = s._decorate_source_collection_work_run_snapshot(
        active_snapshot,
        team_id=normalized_team_id,
        run_id=normalized_run_id,
    )
    active_work_run = (
        active_snapshot
        if s._source_collection_background_snapshot_is_active(active_snapshot, normalized_team_id, normalized_run_id)
        else {}
    )
    context_key = f"source_collection_context:{normalized_team_id}:{normalized_run_id}:{stage_id}:{agent_id}:{agent_role or 'agent'}"
    existing_message = s._find_source_collection_context_message(session_id, context_key)
    if existing_message is not None:
        return {
            "schemaVersion": s.SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "runId": normalized_run_id,
            "stageId": stage_id,
            "agentId": agent_id,
            "agentRole": agent_role,
            "sessionId": session_id,
            **experiment_session,
            "contextKey": context_key,
            "created": False,
            "alreadyPresent": True,
            "message": existing_message,
        }

    message_content = s._source_collection_agent_context_message(
        team=team,
        agent=agent,
        stage_id=stage_id,
        agent_role=agent_role,
        run=run,
        run_status=run_status,
        active_work_run=active_work_run,
        assignments=assignments,
        matching_assignments=matching_assignments,
        records=records,
        source_candidates=source_candidates,
        storage_artifacts=storage_artifacts,
    )
    message = s.session_service.append_session_assistant_artifact_message(
        session_id,
        message_content,
        metadata={
            "kind": "source_collection_agent_context",
            "status": "observed",
            "teamId": normalized_team_id,
            "runId": normalized_run_id,
            "stageId": stage_id,
            "agentId": agent_id,
            "agentRole": agent_role,
            "sourceCollectionContextKey": context_key,
            "researchProjectId": research_project["projectId"],
            "experimentName": research_project["name"],
            "sessionAttempt": experiment_session["sessionAttempt"],
            "recordCount": len(records),
            "candidateCount": len(source_candidates),
            "assignmentCount": len(assignments),
            "matchingAssignmentCount": len(matching_assignments),
            "activeWorkRunId": s._trim_text(active_work_run.get("runId"), max_length=160) if active_work_run else "",
            "storageArtifacts": storage_artifacts,
            "turnId": context_key,
        },
    )
    s._record_workflow_event(
        "source_collection.agent_session_context_seeded",
        normalized_team_id,
        fields={
            "runId": normalized_run_id,
            "stageId": stage_id,
            "agentId": agent_id,
            "agentRole": agent_role,
            "sessionId": session_id,
            "recordCount": len(records),
            "candidateCount": len(source_candidates),
            "assignmentCount": len(assignments),
        },
    )
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "runId": normalized_run_id,
        "stageId": stage_id,
        "agentId": agent_id,
        "agentRole": agent_role,
        "sessionId": session_id,
        **experiment_session,
        "contextKey": context_key,
        "created": True,
        "alreadyPresent": False,
        "message": message,
    }

def start_source_collection_stage_session_task(
    team_id: str,
    run_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_run_id = s._normalize_required_id(run_id, "Data processing run id is required.")
    team = s.team_service.get_team(normalized_team_id)
    request_payload = dict(payload) if isinstance(payload, dict) else {}
    stage_id = s._normalize_source_collection_stage_id(request_payload.get("stageId"), default="finding")
    agent_id = s._trim_text(request_payload.get("agentId"), max_length=160)
    agent_role = s._normalize_source_collection_agent_role(request_payload.get("agentRole"))
    return_to = s._trim_text(request_payload.get("returnTo"), max_length=1000)
    return_label = s._trim_text(request_payload.get("returnLabel"), max_length=240)
    requested_by = s._trim_text(request_payload.get("requestedByAgent"), max_length=160)
    idempotency_key = s._trim_text(request_payload.get("idempotencyKey"), max_length=240)
    formal_retry = bool(request_payload.get("formalRetry"))
    if stage_id not in s.SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES:
        raise s.TeamWorkflowOrchestrationError(f"Unsupported source collection stage: {stage_id}")
    if not agent_id:
        default_agent = s._source_collection_default_stage_agent(stage_id, agent_role=agent_role)
        if default_agent:
            agent_id = s._trim_text(default_agent.get("agentId"), max_length=160)
    if not agent_id:
        raise s.TeamWorkflowOrchestrationError("Agent id is required for source collection stage session task.")

    agent = s.agent_directory_service.get_agent(agent_id)
    if not isinstance(agent, dict):
        raise s.TeamWorkflowOrchestrationError(f"Agent not found: {agent_id}")

    run_bundle = s._source_collection_run_context_bundle(normalized_team_id, normalized_run_id)
    run = run_bundle["run"]
    assignments = run_bundle["assignments"]
    records = run_bundle["records"]
    source_candidates = run_bundle["sourceCandidates"]
    run_status = run_bundle["runStatus"]
    active_work_run = run_bundle["activeWorkRun"]
    if not agent_role:
        agent_role = s._normalize_source_collection_agent_role(s._source_collection_agent_role_for_id(assignments, agent_id, stage_id))
    allowed_roles = s.SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES[stage_id]
    if agent_role and agent_role not in allowed_roles:
        raise s.TeamWorkflowOrchestrationError(f"Agent role {agent_role} is not assigned to source collection stage {stage_id}.")
    research_project = s.resolve_research_project_identity_from_record(normalized_team_id, run)
    run_scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    run_metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    question_id = s._trim_text(
        request_payload.get("questionId")
        or run_scope.get("questionId")
        or run_metadata.get("questionId"),
        max_length=32,
    )
    required_model_policy = (
        request_payload.get("requiredModelPolicy")
        if isinstance(request_payload.get("requiredModelPolicy"), dict)
        else run_scope.get("requiredModelPolicy")
        if isinstance(run_scope.get("requiredModelPolicy"), dict)
        else run_metadata.get("requiredModelPolicy")
        if isinstance(run_metadata.get("requiredModelPolicy"), dict)
        else {}
    )
    if question_id and not required_model_policy:
        prompt_cache_policy_ref = (
            run_scope.get("promptCachePolicyRef")
            if isinstance(run_scope.get("promptCachePolicyRef"), dict)
            else {}
        )
        required_model_policy = s.derive_challenge_required_model_policy(
            prompt_cache_policy_ref.get("modelId")
            or run_metadata.get("promptCacheModelId")
        )

    matching_assignments = s._source_collection_matching_assignments(assignments, agent_id=agent_id, agent_role=agent_role)
    if not requested_by:
        requested_by = s._source_collection_owner_agent_id(team, {})
    storage_artifacts = s._source_collection_storage_artifacts(normalized_team_id, normalized_run_id)
    task_id = s._new_record_id("stagetask")
    task_idempotency_key = s._source_collection_stage_task_idempotency_key(
        team_id=normalized_team_id,
        run_id=normalized_run_id,
        stage_id=stage_id,
        agent_id=agent_id,
        agent_role=agent_role,
        task_id=task_id,
        requested_key=idempotency_key,
    )
    if idempotency_key:
        existing_task = s._find_source_collection_stage_session_task(
            normalized_team_id,
            normalized_run_id,
            idempotency_key=task_idempotency_key,
        )
        if existing_task is not None:
            existing_session = _source_collection_task_experiment_session_fields(
                existing_task,
                research_project=research_project,
                return_to=return_to or s._trim_text(existing_task.get("returnTo"), max_length=1000),
                return_label=return_label or s._trim_text(existing_task.get("returnLabel"), max_length=240),
            )
            s._record_workflow_event(
                "source_collection.stage_session_task_reused",
                normalized_team_id,
                fields={
                    "runId": normalized_run_id,
                    "stageId": stage_id,
                    "agentId": agent_id,
                    "agentRole": agent_role,
                    "sessionId": existing_session["sessionId"],
                    "taskId": s._trim_text(existing_task.get("taskId"), max_length=160),
                    "idempotencyKey": task_idempotency_key,
                    "status": s._trim_text(existing_task.get("status"), max_length=80),
                },
            )
            return {
                "schemaVersion": s.SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "runId": normalized_run_id,
                "stageId": stage_id,
                "agentId": agent_id,
                "agentRole": agent_role,
                **existing_session,
                "taskId": s._trim_text(existing_task.get("taskId"), max_length=160),
                "idempotencyKey": task_idempotency_key,
                "created": False,
                "alreadyPresent": True,
                "task": existing_task,
                "turn": existing_task.get("turn") if isinstance(existing_task.get("turn"), dict) else {},
                "writebackContract": existing_task.get("writebackContract") if isinstance(existing_task.get("writebackContract"), dict) else {},
                "challengeTaskContract": (
                    existing_task.get("challengeTaskContract")
                    if isinstance(existing_task.get("challengeTaskContract"), dict)
                    else {}
                ),
                "boundaries": s._source_collection_stage_session_task_boundaries(
                    stage_id=stage_id,
                    agent_role=agent_role,
                ),
            }

    dialogue_model_id = s.agent_directory_service.agent_dialogue_model_id(agent)
    try:
        challenge_task_contract = s.bind_challenge_research_task_model(
            team_id=normalized_team_id,
            research_project_id=research_project["projectId"],
            question_id=question_id,
            required_model_policy=required_model_policy,
            dialogue_model_id=dialogue_model_id,
            model_library=s._source_collection_model_library(),
        )
    except ValueError as exc:
        raise s.TeamWorkflowOrchestrationError(str(exc)) from exc
    if challenge_task_contract:
        challenge_task_contract = {
            **challenge_task_contract,
            "taskId": task_id,
            "turnId": "",
        }

    previous_stage_task = s._latest_source_collection_stage_task(
        [
            item
            for item in s._source_collection_stage_session_tasks(normalized_team_id, normalized_run_id)
            if s._trim_text(item.get("stageId"), max_length=80) == stage_id
            and s._trim_text(item.get("agentId"), max_length=160) == agent_id
        ]
    )
    source_context_mode = s._source_collection_stage_task_context_mode(
        stage_id=stage_id,
        agent_role=agent_role,
        previous_task=previous_stage_task,
        source_candidates=source_candidates,
    )
    try:
        experiment_session = s.resolve_research_project_agent_session(
            normalized_team_id,
            research_project_id=research_project["projectId"],
            agent_id=agent_id,
            role_key=agent_role or s._trim_text(agent.get("roleKey"), max_length=80),
            role_label=s.research_project_agent_role_label(
                agent_role or s._trim_text(agent.get("roleKey"), max_length=80),
                agent,
            ),
            created_from_task_id=task_id,
            formal_retry=formal_retry,
            previous_task=previous_stage_task,
        )
    except s.ResearchProjectAgentSessionError as exc:
        raise s.TeamWorkflowOrchestrationError(str(exc)) from exc
    session_id = experiment_session["sessionId"]
    session_isolation = {
        "status": "not_required",
        "reason": "research_project_agent_session_registry",
    }
    s._record_source_collection_stage_task_tool_policy_event(
        normalized_team_id,
        normalized_run_id,
        stage_id=stage_id,
        agent_id=agent_id,
        agent_role=agent_role,
        session_id=session_id,
        task_id=task_id,
    )
    writeback_contract = s._source_collection_stage_task_writeback_contract(
        normalized_team_id,
        normalized_run_id,
        task_id,
        stage_id=stage_id,
        agent_id=agent_id,
        agent_role=agent_role,
    )
    task_checklist = s._source_collection_stage_task_checklist(stage_id, agent_role)
    writeback_contract["taskToolRequired"] = False
    writeback_contract["taskChecklist"] = task_checklist
    task_message = s._source_collection_stage_session_task_message(
        team=team,
        agent=agent,
        stage_id=stage_id,
        agent_role=agent_role,
        run=run,
        run_status=run_status,
        active_work_run=active_work_run,
        assignments=assignments,
        matching_assignments=matching_assignments,
        records=records,
        source_candidates=source_candidates,
        storage_artifacts=storage_artifacts,
        writeback_contract=writeback_contract,
        task_checklist=task_checklist,
        previous_task=previous_stage_task,
        context_mode=source_context_mode,
    )
    now = s.utc_now_iso()
    task_record = {
        "schemaVersion": s.SCHEMA_VERSION,
        "taskKind": s.SOURCE_COLLECTION_STAGE_SESSION_TASK_KIND,
        "taskId": task_id,
        "idempotencyKey": task_idempotency_key,
        "teamId": normalized_team_id,
        "runId": normalized_run_id,
        "stageId": stage_id,
        "agentId": agent_id,
        "agentRole": agent_role,
        "sessionId": session_id,
        "researchProjectId": experiment_session["researchProjectId"],
        "experimentName": experiment_session["experimentName"],
        "sessionTitle": experiment_session["sessionTitle"],
        "sessionAttempt": experiment_session["sessionAttempt"],
        "sessionCreated": experiment_session["sessionCreated"],
        "retryOfSessionId": experiment_session["retryOfSessionId"],
        "challengeTaskContract": challenge_task_contract,
        "formalRetry": formal_retry,
        "status": "queued",
        "title": s._source_collection_stage_task_title(stage_id),
        "summary": "",
        "returnTo": return_to,
        "returnLabel": return_label,
        "requestedByAgent": requested_by,
        "recordCount": len(records),
        "candidateCount": len(source_candidates),
        "assignmentCount": len(assignments),
        "matchingAssignmentCount": len(matching_assignments),
        "storageArtifacts": storage_artifacts,
        "writebackContract": writeback_contract,
        "taskToolRequired": False,
        "taskChecklist": task_checklist,
        "checklistBinding": {
            "mode": "stage_task",
            "bound": True,
            "boundAt": now,
            "source": "backend",
        },
        "taskToolProgress": s._source_collection_stage_task_tool_progress(task_checklist),
        "completionGate": s._source_collection_stage_completion_gate(
            task_checklist=task_checklist,
            artifact_complete=False,
            task_checklist_complete=False,
        ),
        "writesFormalKnowledge": bool(writeback_contract.get("writesFormalKnowledge")),
        "writesRag": False,
        "writesOfficialGraph": bool(writeback_contract.get("writesOfficialGraph")),
        "turn": {},
        "result": {},
        "writeback": {},
        "sourceContextMode": source_context_mode,
        "retrySourceTaskId": (
            s._trim_text(previous_stage_task.get("taskId"), max_length=160)
            if (
                source_context_mode in {"retry_missing", "retry_evidence"}
                or s._source_collection_stage_task_needs_writeback_resume(previous_stage_task)
                or stage_id == "extraction"
                or formal_retry
            )
            and isinstance(previous_stage_task, dict)
            else ""
        ),
        "sessionIsolation": session_isolation,
        "createdAt": now,
        "updatedAt": now,
    }
    s._upsert_source_collection_stage_session_task(normalized_team_id, normalized_run_id, task_record)
    turn = s.session_service.submit_session_message(
        session_id,
        task_message,
        mental_model_enabled=False,
        turn_mode="task",
        write_intent=False,
        message_source="agent_inbox",
        message_metadata={
            "kind": s.SOURCE_COLLECTION_STAGE_SESSION_TASK_KIND,
            "sourceSurface": "team_workflow_stage_task",
            "teamId": normalized_team_id,
            "runId": normalized_run_id,
            "stageId": stage_id,
            "agentId": agent_id,
            "agentRole": agent_role,
            "researchProjectId": experiment_session["researchProjectId"],
            "experimentName": experiment_session["experimentName"],
            "sessionAttempt": experiment_session["sessionAttempt"],
            "retryOfSessionId": experiment_session["retryOfSessionId"],
            "questionId": str(challenge_task_contract.get("questionId") or ""),
            "requiredModelPolicy": (
                challenge_task_contract.get("requiredModelPolicy")
                if isinstance(challenge_task_contract.get("requiredModelPolicy"), dict)
                else {}
            ),
            "challengeTaskContract": challenge_task_contract,
            "sourceCollectionStageTaskId": task_id,
            "sourceCollectionStageTaskKey": task_idempotency_key,
            "sourceContextMode": source_context_mode,
            "writebackContract": writeback_contract,
            "taskToolRequired": False,
            "taskChecklist": task_checklist,
            "checklistBinding": task_record["checklistBinding"],
        },
        include_started_turn_id=True,
        lightweight_response=True,
    )
    turn_payload = turn if isinstance(turn, dict) else {}
    task_record["status"] = "running" if turn_payload.get("accepted") else "queued"
    task_record["turn"] = {
        "accepted": bool(turn_payload.get("accepted")),
        "turnId": s._trim_text(turn_payload.get("turnId") or turn_payload.get("startedTurnId"), max_length=160),
        "status": s._trim_text(turn_payload.get("status"), max_length=80),
        "acceptedAt": s._trim_text(turn_payload.get("acceptedAt"), max_length=120),
    }
    if challenge_task_contract:
        challenge_task_contract = {
            **challenge_task_contract,
            "turnId": task_record["turn"]["turnId"],
        }
        task_record["challengeTaskContract"] = challenge_task_contract
    if not task_record["turn"]["accepted"]:
        s._record_workflow_event(
            "source_collection.stage_session_task_submit_not_accepted",
            normalized_team_id,
            fields={
                "runId": normalized_run_id,
                "stageId": stage_id,
                "agentId": agent_id,
                "agentRole": agent_role,
                "sessionId": session_id,
                "taskId": task_id,
                "turnStatus": task_record["turn"].get("status", ""),
            },
        )
    task_record["updatedAt"] = s.utc_now_iso()
    s._upsert_source_collection_stage_session_task(normalized_team_id, normalized_run_id, task_record)
    s._sync_stage_round_with_source_collection_stage_task(normalized_team_id, normalized_run_id, task_record)
    s._record_workflow_event(
        "source_collection.stage_session_task_started",
        normalized_team_id,
        fields={
            "runId": normalized_run_id,
            "stageId": stage_id,
            "agentId": agent_id,
            "agentRole": agent_role,
            "sessionId": session_id,
            "taskId": task_id,
            "turnId": task_record["turn"].get("turnId", ""),
        },
    )
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "runId": normalized_run_id,
        "stageId": stage_id,
        "agentId": agent_id,
        "agentRole": agent_role,
        **experiment_session,
        "taskId": task_id,
        "idempotencyKey": task_idempotency_key,
        "created": True,
        "alreadyPresent": False,
        "task": task_record,
        "turn": task_record["turn"],
        "chatRoute": s._source_collection_stage_task_chat_route(session_id, return_to=return_to, return_label=return_label),
        "writebackContract": writeback_contract,
        "taskChecklist": task_checklist,
        "completionGate": task_record["completionGate"],
        "sessionIsolation": session_isolation,
        "boundaries": s._source_collection_stage_session_task_boundaries(stage_id=stage_id, agent_role=agent_role),
    }

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
    source_candidates = s._rank_source_collection_context_candidates(
        run_bundle["sourceCandidates"],
        stage_id=normalized_stage_id,
    ) if include_candidates else []
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
    if retry_source_task_id:
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
            "returnedCandidateCount": len(selected_candidates),
            "assignmentCount": len(run_bundle["assignments"]),
            "matchingAssignmentCount": len(matching_assignments),
        },
        "run": s._source_collection_context_run_summary(run_bundle["run"], run_bundle["runStatus"], run_bundle["activeWorkRun"]),
        "task": s._source_collection_context_task_summary(task),
        "assignments": [s._source_collection_context_assignment_summary(item) for item in matching_assignments[:12]],
        "records": [s._source_collection_context_record_summary(item) for item in selected_records],
        "candidates": [s._source_collection_context_candidate_summary(item) for item in selected_candidates],
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
        "allUnassessedCandidateCount": sum(1 for item in source_candidates if s._source_quality_bucket(item) == "pending"),
        "storageArtifacts": storage_artifacts,
        "writebackContract": task.get("writebackContract") if isinstance(task.get("writebackContract"), dict) else {},
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
            source_candidates,
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
