"""Source-collection stage session: advance gates, seed context, start task.

Clarity B6: split from stages.py. Late-bound facade keeps route imports and
monkeypatches on ``team_workflow_orchestration_service`` stable.
"""

from __future__ import annotations

from typing import Any

from .stage_session_replay import (
    mark_source_collection_stage_task_session_missing,
    prepare_source_collection_stage_task_replay,
)

_AUTO_FORMAL_RETRY_STATUSES = {
    "error",
    "failed",
    "incomplete",
    "timed_out",
    "timeout",
    # Product bar: blocked/no-product stage tasks are failures and must re-open as formal retry.
    "blocked",
}

# Ingestion must not open when the candidate graph is clearly not ready.
_INGESTION_GRAPH_MISSING_LINK_HARD_LIMIT = 5


def assert_source_collection_stage_advance_ready(
    *,
    stage_id: str,
    record_count: int,
    approved_or_source_candidate_count: int,
    graph_node_count: int,
    graph_edge_count: int,
    graph_missing_link_count: int,
) -> None:
    """
    Hard product gate for stage advance. Fail loudly before opening Agent chat.
    Mirrors web stageAdvancePreflight so UI and API agree.
    """
    s = _service()
    normalized_stage = s._normalize_source_collection_stage_id(stage_id, default="")
    records = max(0, int(record_count or 0))
    candidates = max(0, int(approved_or_source_candidate_count or 0))
    nodes = max(0, int(graph_node_count or 0))
    edges = max(0, int(graph_edge_count or 0))
    missing = max(0, int(graph_missing_link_count or 0))

    if normalized_stage == "extraction" and records <= 0:
        raise s.TeamWorkflowOrchestrationError(
            "推进失败（不合格）：还没有原始资料，无法提炼。请先完成找资料。"
        )
    if normalized_stage == "relations" and candidates <= 0:
        raise s.TeamWorkflowOrchestrationError(
            "推进失败（不合格）：没有可整理的候选资料。请先完成提炼/审查。"
        )
    if normalized_stage != "ingestion":
        return
    if candidates <= 0:
        raise s.TeamWorkflowOrchestrationError(
            "推进失败（不合格）：没有可入库的候选资料。请先完成提炼。"
        )
    if nodes > 0 and edges <= 0:
        raise s.TeamWorkflowOrchestrationError(
            f"推进失败（不合格）：关系图有 {nodes} 个节点但 0 条边，入库会被系统拦截。请先完成整理关系。"
        )
    if missing > _INGESTION_GRAPH_MISSING_LINK_HARD_LIMIT:
        raise s.TeamWorkflowOrchestrationError(
            f"推进失败（不合格）：关系缺口 {missing}，入库不能当作成功。请先修整理关系。"
        )

def _source_collection_run_graph_metrics(
    team_id: str,
    run_id: str,
    source_candidates: list[dict[str, Any]],
) -> dict[str, int]:
    s = _service()
    source_candidate_ids = {
        s._trim_text(item.get("candidateId"), max_length=160)
        for item in source_candidates
        if isinstance(item, dict) and s._trim_text(item.get("candidateId"), max_length=160)
    }
    with s._WORKFLOW_LOCK:
        candidate_store = s._load_candidate_store(team_id)
        stored_candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
    graph_candidates = [
        item
        for item in stored_candidates
        if str(item.get("candidateType") or "") == "candidate_graph"
        and not s._candidate_is_archived(item)
        and s._source_collection_candidate_graph_matches_run(item, source_candidate_ids)
    ]
    latest_graph = s._latest_candidate_record(graph_candidates) or {}
    metadata = latest_graph.get("metadata") if isinstance(latest_graph.get("metadata"), dict) else {}
    graph_payload = metadata.get("graph") if isinstance(metadata.get("graph"), dict) else {}
    if not graph_payload and isinstance(latest_graph.get("graph"), dict):
        graph_payload = latest_graph.get("graph") or {}
    if not graph_payload and isinstance(latest_graph.get("payload"), dict):
        graph_payload = latest_graph.get("payload") or {}
    summary = graph_payload.get("summary") if isinstance(graph_payload.get("summary"), dict) else {}
    nodes = list(graph_payload.get("nodes") or []) if isinstance(graph_payload.get("nodes"), list) else []
    edges = list(graph_payload.get("edges") or []) if isinstance(graph_payload.get("edges"), list) else []
    missing_links = list(graph_payload.get("missingLinks") or []) if isinstance(graph_payload.get("missingLinks"), list) else []
    return {
        "nodeCount": int(summary.get("nodeCount") or len(nodes) or 0),
        "edgeCount": int(summary.get("edgeCount") or len(edges) or 0),
        "missingLinkCount": int(summary.get("missingLinkCount") or len(missing_links) or 0),
    }

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
    formal_retry_requested = bool(request_payload.get("formalRetry"))
    evidence_remediation_contract = (
        s._normalize_metadata(request_payload.get("evidenceRemediationContract"))
        if isinstance(request_payload.get("evidenceRemediationContract"), dict)
        else {}
    )
    if evidence_remediation_contract and stage_id != "extraction":
        raise s.TeamWorkflowOrchestrationError(
            "Evidence remediation contract is only valid for extraction tasks."
        )
    if stage_id not in s.SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES:
        raise s.TeamWorkflowOrchestrationError(f"Unsupported source collection stage: {stage_id}")
    if not agent_id:
        default_agent = s._source_collection_default_stage_agent(stage_id, agent_role=agent_role)
        if default_agent:
            agent_id = s._trim_text(default_agent.get("agentId"), max_length=160)
    if not agent_id:
        raise s.TeamWorkflowOrchestrationError("Agent id is required for source collection stage session task.")

    run_bundle = s._source_collection_run_context_bundle(normalized_team_id, normalized_run_id)
    run = run_bundle["run"]
    assignments = run_bundle["assignments"]
    records = run_bundle["records"]
    source_candidates = run_bundle["sourceCandidates"]
    run_status = run_bundle["runStatus"]
    active_work_run = run_bundle["activeWorkRun"]
    # Product bar: refuse stage open when upstream is not ready (same contract as UI preflight).
    graph_metrics = _source_collection_run_graph_metrics(
        normalized_team_id,
        normalized_run_id,
        source_candidates if isinstance(source_candidates, list) else [],
    )
    approved_or_source_count = 0
    for item in source_candidates if isinstance(source_candidates, list) else []:
        if not isinstance(item, dict):
            continue
        quality = str(item.get("qualityStatus") or item.get("currentState") or "").lower()
        if "approv" in quality or "screened" in quality or "ready" in quality or "synced" in quality:
            approved_or_source_count += 1
        elif s._trim_text(item.get("candidateId"), max_length=160) and str(
            item.get("candidateType") or ""
        ) in {"source_manifest", "paper_note", "algorithm_hypothesis"}:
            # Count concrete source/manifest candidates even before quality label is perfect.
            approved_or_source_count += 1
    assert_source_collection_stage_advance_ready(
        stage_id=stage_id,
        record_count=len(records) if isinstance(records, list) else 0,
        approved_or_source_candidate_count=max(approved_or_source_count, len(source_candidates) if isinstance(source_candidates, list) else 0),
        graph_node_count=graph_metrics["nodeCount"],
        graph_edge_count=graph_metrics["edgeCount"],
        graph_missing_link_count=graph_metrics["missingLinkCount"],
    )
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
    replay_task: dict[str, Any] | None = None
    missing_session_recovery = False
    if idempotency_key:
        existing_task = s._find_source_collection_stage_session_task(
            normalized_team_id,
            normalized_run_id,
            idempotency_key=task_idempotency_key,
        )
        if existing_task is not None:
            replay = prepare_source_collection_stage_task_replay(
                normalized_team_id,
                normalized_run_id,
                existing_task,
            )
            replay_action = str(replay.get("action") or "")
            replay_task = (
                replay.get("task") if isinstance(replay.get("task"), dict) else existing_task
            )
            if replay_action == "resume_same_task":
                replay_action = "reuse"
            if replay_action != "reuse":
                task_id = s._trim_text(replay_task.get("taskId"), max_length=160)
                missing_session_recovery = replay_action == "formal_retry_same_task"
            else:
                existing_task = replay_task
        if existing_task is not None and replay_task is not None and replay_action == "reuse":
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

    # The canonical stage task/session/turn is the idempotency authority for a
    # replay.  Only a genuinely new task needs a fresh Agent-directory lookup;
    # otherwise a transient directory refresh can turn a healthy running turn
    # into a false terminal "Agent not found" failure.
    agent = s.agent_directory_service.get_agent(agent_id)
    if not isinstance(agent, dict):
        raise s.TeamWorkflowOrchestrationError(f"Agent not found: {agent_id}")

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
    if (
        isinstance(previous_stage_task, dict)
        and s._trim_text(previous_stage_task.get("status"), max_length=80).lower()
        in {"queued", "running"}
    ):
        previous_stage_task = s._reconcile_source_collection_stage_session_task(
            normalized_team_id,
            normalized_run_id,
            previous_stage_task,
        )
    previous_stage_task_status = s._trim_text(
        previous_stage_task.get("status") if isinstance(previous_stage_task, dict) else "",
        max_length=80,
    ).lower()
    auto_formal_retry = (
        not formal_retry_requested
        and previous_stage_task_status in _AUTO_FORMAL_RETRY_STATUSES
    )
    formal_retry = formal_retry_requested or auto_formal_retry
    formal_retry_reason = (
        "missing_canonical_session"
        if missing_session_recovery
        else
        "requested"
        if formal_retry_requested
        else "previous_stage_task_failed"
        if auto_formal_retry
        else ""
    )
    if auto_formal_retry:
        s._record_workflow_event(
            "source_collection.stage_session_task_auto_formal_retry",
            normalized_team_id,
            fields={
                "runId": normalized_run_id,
                "stageId": stage_id,
                "agentId": agent_id,
                "agentRole": agent_role,
                "previousTaskId": s._trim_text(
                    previous_stage_task.get("taskId"),
                    max_length=160,
                ),
                "previousTaskStatus": previous_stage_task_status,
                "reason": formal_retry_reason,
            },
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
            recover_missing_session=True,
        )
    except s.ResearchProjectAgentSessionError as exc:
        raise s.TeamWorkflowOrchestrationError(str(exc)) from exc
    session_id = experiment_session["sessionId"]
    if experiment_session.get("recoveryReason") == "missing_canonical_session":
        formal_retry = True
        formal_retry_reason = "missing_canonical_session"
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
    task_checklist = s._source_collection_stage_task_checklist(
        stage_id,
        agent_role,
        evidence_remediation_contract=evidence_remediation_contract,
    )
    writeback_contract["taskToolRequired"] = False
    writeback_contract["taskChecklist"] = task_checklist
    if evidence_remediation_contract:
        writeback_contract["evidenceRemediationContract"] = evidence_remediation_contract
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
        "formalRetryRequested": formal_retry_requested,
        "formalRetryReason": formal_retry_reason,
        "evidenceRemediationContract": evidence_remediation_contract,
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
        "createdAt": (
            s._trim_text(replay_task.get("createdAt"), max_length=120)
            if isinstance(replay_task, dict)
            else now
        ) or now,
        "updatedAt": now,
    }
    s._upsert_source_collection_stage_session_task(normalized_team_id, normalized_run_id, task_record)
    try:
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
    except s.session_service.SessionNotFoundError as exc:
        mark_source_collection_stage_task_session_missing(
            normalized_team_id,
            normalized_run_id,
            task_record,
        )
        raise s.TeamWorkflowOrchestrationError(
            "The canonical Agent session disappeared before the stage task could start. "
            "Replay the same command to create a lineage-preserving formal retry."
        ) from exc
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
