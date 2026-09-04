"""Source-collection runs and search public entrypoints.

Claim scope: start SC run, execute/background search, work-run summary, SC summary.
Do not put stage writeback, candidates register, or experiment packs here.

Late-bound facade keeps route imports and monkeypatches on
``team_workflow_orchestration_service`` stable.
"""

from __future__ import annotations

import shutil
from typing import Any


def _service():
    from core.web.services import team_workflow_orchestration_service

    return team_workflow_orchestration_service


def _search_circuit():
    from core.web.services.team_workflow.source_collection import search_circuit

    return search_circuit


def start_source_collection_run(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    team = s.team_service.get_team(normalized_team_id)
    request_payload = dict(payload) if isinstance(payload, dict) else {}
    active_project = s.get_active_research_project(normalized_team_id)
    scope = s._normalize_metadata(request_payload.get("scope"))
    requested_project_id = s._trim_text(request_payload.get("researchProjectId"), max_length=160)
    research_project = active_project
    if requested_project_id and requested_project_id != active_project["projectId"]:
        # Workflow-run-scoped payloads (hypothesis-first chain) pin the
        # question's canonical research project, resolved from the question
        # binding instead of the operator's active-project pointer.  Every
        # other caller keeps the strict active-project rule unchanged.
        if not s._trim_text(scope.get("workflowRunId"), max_length=160):
            raise s.TeamWorkflowOrchestrationError(
                "Source collection run researchProjectId must match the active research project."
            )
        try:
            research_project = s.get_research_project(normalized_team_id, requested_project_id)
        except s.ResearchProjectNotFoundError as exc:
            raise s.TeamWorkflowOrchestrationError(str(exc)) from exc
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
    # Optional ensure-idempotency fingerprint set by the knowledge-collection
    # facade (see facade.search_envelope_fingerprint).  Only the explicit
    # metadata key is propagated; arbitrary caller metadata is never merged.
    search_envelope_fingerprint = s._trim_text(
        request_payload.get("searchEnvelopeFingerprint"), max_length=128
    )
    # Evidence-request circuit metadata (rewrite runs only; see
    # source_collection.search_circuit).  Absent on every other caller, so
    # the default run-creation path is unchanged.
    search_circuit_metadata = (
        request_payload.get("searchCircuit")
        if isinstance(request_payload.get("searchCircuit"), dict)
        else {}
    )
    question_id = request_payload.get("questionId") or scope.get("questionId")
    required_model_policy = (
        request_payload.get("requiredModelPolicy")
        if isinstance(request_payload.get("requiredModelPolicy"), dict)
        else scope.get("requiredModelPolicy")
        if isinstance(scope.get("requiredModelPolicy"), dict)
        else {}
    )
    if question_id and not required_model_policy:
        required_model_policy = s.derive_challenge_required_model_policy(prompt_cache_policy.get("modelId"))
    try:
        challenge_task_contract = s.normalize_challenge_research_task_policy(
            question_id,
            required_model_policy,
        )
    except ValueError as exc:
        raise s.TeamWorkflowOrchestrationError(str(exc)) from exc
    if goal:
        scope["goal"] = goal
    if topic:
        scope["topic"] = topic
    scope["teamId"] = normalized_team_id
    scope["workflowKind"] = workflow_kind
    scope["workflowPurpose"] = workflow_kind
    scope["collectionMode"] = collection_mode
    scope["researchProjectId"] = research_project["projectId"]
    scope["experimentName"] = research_project["name"]
    scope["promptCachePolicyRef"] = s._source_collection_prompt_cache_policy_ref(prompt_cache_policy)
    if challenge_task_contract:
        scope.update(challenge_task_contract)
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
    run_metadata = {
        "startedFrom": "team_workflow_source_collection",
        "teamId": normalized_team_id,
        "workflowKind": workflow_kind,
        "workflowPurpose": workflow_kind,
        "collectionMode": collection_mode,
        "researchProjectId": research_project["projectId"],
        "experimentName": research_project["name"],
        **challenge_task_contract,
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
    }
    if search_envelope_fingerprint:
        run_metadata["searchEnvelopeFingerprint"] = search_envelope_fingerprint
    if search_circuit_metadata:
        run_metadata["searchCircuit"] = search_circuit_metadata
    run = s.data_processing_service.create_processing_run(
        s.data_processing_service.DEFAULT_PROFILE_ID,
        title=title,
        scope=scope,
        metadata=run_metadata,
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
    research_project = s.lock_research_project_name(
        normalized_team_id,
        research_project["projectId"],
        reason="first_experiment_task",
    )
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
            "researchProjectId": research_project["projectId"],
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
        "researchProjectId": research_project["projectId"],
        "experimentName": research_project["name"],
        **challenge_task_contract,
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


def _stage_round_source_run_ids(item: dict[str, Any]) -> set[str]:
    s = _service()
    return {
        s._trim_text(source_run_id, max_length=160)
        for source_run_id in list(item.get("sourceRunIds") or [])
        if s._trim_text(source_run_id, max_length=160)
    }


def _stage_round_belongs_to_research_project(
    item: dict[str, Any],
    research_project_id: str,
    project_run_ids: set[str],
) -> bool:
    """Scope stage rounds to one research project when resetting Stage-1 sources."""

    s = _service()
    if not isinstance(item, dict):
        return False
    round_project_id = s._trim_text(item.get("researchProjectId"), max_length=160)
    if round_project_id:
        return round_project_id == research_project_id
    source_run_ids = _stage_round_source_run_ids(item)
    if source_run_ids:
        return bool(source_run_ids & project_run_ids)
    # Unscoped legacy rounds only attach to the legacy project boundary.
    return research_project_id == s.LEGACY_PROJECT_ID


def _candidate_belongs_to_research_project(
    candidate: dict[str, Any],
    research_project_id: str,
    project_run_ids: set[str],
) -> bool:
    """Decide whether a candidate is owned by the project being reset."""

    s = _service()
    if not isinstance(candidate, dict):
        return False
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    candidate_project_id = s._trim_text(
        candidate.get("researchProjectId") or metadata.get("researchProjectId"),
        max_length=160,
    )
    if candidate_project_id:
        return candidate_project_id == research_project_id
    imported = metadata.get("importedFromDataRecord") if isinstance(metadata.get("importedFromDataRecord"), dict) else {}
    imported_run_id = s._trim_text(imported.get("runId"), max_length=160)
    if imported_run_id:
        return imported_run_id in project_run_ids
    # Unscoped candidates without provenance stay on the legacy project only.
    return research_project_id == s.LEGACY_PROJECT_ID


def _project_source_collection_run_ids(team_id: str, research_project_id: str) -> set[str]:
    s = _service()
    runs_payload = s.data_processing_service.list_processing_runs(
        limit=200,
        metadata_filters={"startedFrom": "team_workflow_source_collection", "teamId": team_id},
    )
    return {
        s._trim_text(item.get("runId"), max_length=160)
        for item in list(runs_payload.get("runs") or [])
        if isinstance(item, dict)
        and s._source_collection_run_belongs_to_team(item, team_id)
        and s._source_collection_run_belongs_to_research_project(item, research_project_id)
        and s._trim_text(item.get("runId"), max_length=160)
    }


def _assert_project_agent_tasks_not_active(team_id: str, project_id: str) -> None:
    """Resetting mid-task deletes the plan the task is writing back to."""
    s = _service()
    try:
        from core.web.services.team_workflow import (
            research_project_agent_tasks as task_service,
        )

        status = task_service.get_research_project_agent_task_status(team_id, project_id)
    except Exception:  # noqa: BLE001 - guard must fail open on status errors
        return
    active = list((status or {}).get("activeTasks") or [])
    if active:
        raise s.TeamWorkflowOrchestrationError(
            "该项目仍有进行中的 Agent 任务（"
            + ", ".join(str(item.get("taskKind") or item.get("taskId") or "") for item in active[:5])
            + "）。请等待任务结束或先停止任务，再清空项目进度。"
        )


def _assert_project_source_search_not_active(team_id: str, run_ids: set[str]) -> None:
    s = _service()
    active_snapshot = s._source_collection_work_run_store().load_active_snapshot(s.SOURCE_COLLECTION_WORK_RUN_KIND)
    active_snapshot = s._decorate_source_collection_work_run_snapshot(active_snapshot)
    active_run_id = s._trim_text(active_snapshot.get("runId"), max_length=160) if isinstance(active_snapshot, dict) else ""
    if active_run_id in run_ids and s._source_collection_background_snapshot_is_active(
        active_snapshot,
        team_id,
        active_run_id,
    ):
        raise s.TeamWorkflowOrchestrationError(
            "当前项目的资料搜索仍在进行。请等待结束后再清空本项目资料。"
            " The current project's source search is still running. Wait for it to finish before clearing this project."
        )


def _delete_project_source_collection_runs(team_id: str, run_ids: set[str]) -> list[str]:
    s = _service()
    removed_run_ids: list[str] = []
    for run_id in sorted(run_ids):
        s._source_collection_work_run_store().delete_snapshot(s.SOURCE_COLLECTION_WORK_RUN_KIND, run_id)
        artifacts = s._source_collection_storage_artifact_paths(team_id, run_id)
        run_directory = artifacts["runDirectory"]
        if run_directory.exists():
            shutil.rmtree(run_directory)
        s.data_processing_service.delete_processing_run(run_id)
        removed_run_ids.append(run_id)
    return removed_run_ids


def _source_collection_reset_context(team_id: str, run_ids: set[str]) -> dict[str, Any]:
    """Validate exact source runs before a narrower domain owner removes them."""
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_run_ids = {
        s._trim_text(run_id, max_length=160)
        for run_id in run_ids
        if s._trim_text(run_id, max_length=160)
    }
    loaded_runs: list[dict[str, Any]] = []
    missing_run_ids: list[str] = []
    for run_id in sorted(normalized_run_ids):
        try:
            run = s.data_processing_service.get_processing_run(run_id)
        except s.data_processing_service.DataProcessingNotFoundError:
            # A prior partial reset may already have removed the physical run.
            # It is safe to clear the stale chain reference on a retry.
            missing_run_ids.append(run_id)
            continue
        if not s._source_collection_run_belongs_to_team(run, normalized_team_id):
            raise s.TeamWorkflowOrchestrationError(
                "资料搜集运行不属于当前团队，不能随本题重置。"
            )
        run_status = s._trim_text(run.get("status"), max_length=80).lower()
        if run_status in {"collecting", "processing"}:
            raise s.TeamWorkflowOrchestrationError(
                "本题的资料搜集仍在进行，请等待结束或先停止任务。"
            )
        loaded_runs.append(run)

    _assert_project_source_search_not_active(normalized_team_id, normalized_run_ids)
    return {
        "teamId": normalized_team_id,
        "runIds": normalized_run_ids,
        "runs": loaded_runs,
        "missingRunIds": missing_run_ids,
    }


def preview_source_collection_runs_reset(team_id: str, run_ids: set[str]) -> dict[str, Any]:
    """Return the safe-to-delete status for exact source-collection runs.

    The caller has already derived the ids from an owning question's chain
    records.  This module verifies that those ids are still source-collection
    runs of the same team; it never broadens the operation to a project.
    """
    try:
        context = _source_collection_reset_context(team_id, run_ids)
    except ValueError as exc:  # The UI needs a blocker, not a failed preview.
        return {
            "canReset": False,
            "blockingReason": str(exc),
            "runCount": 0,
            "missingRunIds": [],
        }
    return {
        "canReset": True,
        "blockingReason": "",
        "runCount": len(context["runs"]),
        "missingRunIds": list(context["missingRunIds"]),
    }


def stop_source_collection_search(
    team_id: str,
    run_id: str,
    *,
    reason: str = "operator stopped stuck collection",
) -> dict[str, Any]:
    """Stop one team-owned collection run and clear its active work marker."""

    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_run_id = s._normalize_required_id(run_id, "Data processing run id is required.")
    team = s.team_service.get_team(normalized_team_id)
    try:
        run = s.data_processing_service.get_processing_run(normalized_run_id)
    except s.data_processing_service.DataProcessingError as exc:
        raise s.TeamWorkflowOrchestrationError(str(exc)) from exc
    if not s._source_collection_run_belongs_to_team(run, normalized_team_id):
        raise s.TeamWorkflowOrchestrationError(
            "Data processing run does not belong to this team."
        )
    cancelled_run = s.data_processing_service.cancel_processing_run(
        normalized_run_id,
        reason=reason,
    )
    assignments = s.data_processing_service.list_collection_assignments(
        normalized_run_id
    ).get("assignments", [])
    records = s.data_processing_service.list_records(normalized_run_id).get("records", [])
    snapshot = s._persist_source_collection_work_run(
        normalized_team_id,
        normalized_run_id,
        status="cancelled",
        current_phase="cancelled",
        run=cancelled_run,
        team=team,
        assignments=[item for item in list(assignments or []) if isinstance(item, dict)],
        records=[item for item in list(records or []) if isinstance(item, dict)],
        summary="资料搜索已由操作员停止。",
        active=False,
        extra={"stopReason": s._trim_text(reason, max_length=300)},
    )
    result = {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "runId": normalized_run_id,
        "status": "cancelled",
        "run": cancelled_run,
        "activeWorkRun": snapshot,
        "sourceCollectionSummary": s._source_collection_assignment_stage_summary(
            [item for item in list(assignments or []) if isinstance(item, dict)]
        ),
    }
    s._sync_source_collection_stage_round_after_search(
        normalized_team_id,
        normalized_run_id,
        result,
        terminal_status="cancelled",
        terminal_summary="资料搜索已由操作员停止。",
    )
    return result


def reset_source_collection_runs_for_question(
    team_id: str,
    run_ids: set[str],
) -> dict[str, Any]:
    """Remove only the completed source batches directly linked to one question.

    This is deliberately narrower than a research-project reset.  Mixed or
    downstream artifacts are rejected rather than guessed away, so a question
    reset cannot delete a sibling question's source records.
    """
    context = _source_collection_reset_context(team_id, run_ids)
    s = _service()
    normalized_team_id = context["teamId"]
    target_run_ids = set(context["runIds"])
    if not target_run_ids:
        return {
            "removedRunIds": [],
            "removedSourceCandidateCount": 0,
            "removedStageRoundCount": 0,
            "missingRunIds": [],
        }

    removed_candidate_ids: set[str] = set()
    removed_round_ids: set[str] = set()
    with s._WORKFLOW_LOCK:
        candidate_store = s._load_candidate_store(normalized_team_id)
        candidates = [
            item
            for item in list(candidate_store.get("candidates") or [])
            if isinstance(item, dict)
        ]
        kept_candidates: list[dict[str, Any]] = []
        downstream_candidate_ids: list[str] = []
        for candidate in candidates:
            metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
            imported = (
                metadata.get("importedFromDataRecord")
                if isinstance(metadata.get("importedFromDataRecord"), dict)
                else {}
            )
            source_run_id = s._trim_text(
                imported.get("runId") or metadata.get("sourceCollectionRunId"),
                max_length=160,
            )
            if source_run_id not in target_run_ids:
                kept_candidates.append(candidate)
                continue
            if str(candidate.get("candidateType") or "") != "source_manifest":
                downstream_candidate_ids.append(
                    s._trim_text(candidate.get("candidateId"), max_length=160)
                )
                kept_candidates.append(candidate)
                continue
            candidate_id = s._trim_text(candidate.get("candidateId"), max_length=160)
            if candidate_id:
                removed_candidate_ids.add(candidate_id)

        if downstream_candidate_ids:
            raise s.TeamWorkflowOrchestrationError(
                "本题资料已生成下游科研候选，不能在保留下游产物的情况下重置资料运行。"
            )

        stage_store = s._load_stage_round_store(normalized_team_id)
        remaining_rounds: list[dict[str, Any]] = []
        mixed_or_downstream_round_ids: list[str] = []
        for item in list(stage_store.get("rounds") or []):
            if not isinstance(item, dict):
                continue
            source_run_ids = _stage_round_source_run_ids(item)
            if not (source_run_ids & target_run_ids):
                remaining_rounds.append(item)
                continue
            stage_round_id = s._trim_text(item.get("stageRoundId"), max_length=160)
            if (
                not source_run_ids.issubset(target_run_ids)
                or str(item.get("stageType") or "") != "knowledge_collection"
            ):
                mixed_or_downstream_round_ids.append(stage_round_id)
                remaining_rounds.append(item)
                continue
            if stage_round_id:
                removed_round_ids.add(stage_round_id)

        if mixed_or_downstream_round_ids:
            raise s.TeamWorkflowOrchestrationError(
                "本题资料已进入混合或下游阶段，不能只删除其中一个资料运行。"
            )

        workflow = s._load_or_create_workflow(normalized_team_id)
        workflow["activeWorkflowItems"] = [
            item
            for item in list(workflow.get("activeWorkflowItems") or [])
            if isinstance(item, dict)
            and s._trim_text(item.get("candidateId"), max_length=160)
            not in (target_run_ids | removed_candidate_ids)
        ]
        candidate_store["candidates"] = kept_candidates
        candidate_store["updatedAt"] = s.utc_now_iso()
        stage_store["rounds"] = remaining_rounds
        stage_store["updatedAt"] = s.utc_now_iso()
        workflow["updatedAt"] = s.utc_now_iso()
        s._write_json(s._candidate_store_path(normalized_team_id), candidate_store)
        s._write_json(s._stage_round_store_path(normalized_team_id), stage_store)
        s._write_json(s._workflow_path(normalized_team_id), workflow)

    removed_run_ids = _delete_project_source_collection_runs(
        normalized_team_id,
        {s._trim_text(run.get("runId"), max_length=160) for run in context["runs"]},
    )
    s._record_workflow_event(
        "source_collection.question_run_reset",
        normalized_team_id,
        fields={
            "runIds": removed_run_ids,
            "missingRunIds": context["missingRunIds"],
            "removedSourceCandidateCount": len(removed_candidate_ids),
            "removedStageRoundCount": len(removed_round_ids),
        },
    )
    return {
        "removedRunIds": removed_run_ids,
        "removedSourceCandidateCount": len(removed_candidate_ids),
        "removedStageRoundCount": len(removed_round_ids),
        "missingRunIds": list(context["missingRunIds"]),
    }


def _require_active_research_project(team_id: str, project_id: str) -> tuple[Any, str, str, dict[str, Any]]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_project_id = s._normalize_required_id(project_id, "Research project id is required.")
    s.team_service.get_team(normalized_team_id)
    active_project = s.get_active_research_project(normalized_team_id)
    if active_project["projectId"] != normalized_project_id:
        raise s.TeamWorkflowOrchestrationError(
            "Source collection can only be reset for the active research project."
        )
    return s, normalized_team_id, normalized_project_id, active_project


def reset_research_project_source_collection(team_id: str, project_id: str) -> dict[str, Any]:
    """Clear only a project's still-recoverable Stage-1 source collection.

    This is intentionally narrower than a project reset: it preserves Agent
    conversations, formal knowledge, question ledgers, and every downstream
    experiment.  A reset is rejected once **this** project's source candidates
    have been used to create any non-source research artifact. Downstream
    artifacts belonging to other research projects on the same team must not
    block Stage-1 recovery for the active project.

    When Stage-1 is blocked, call ``reset_research_project_progress`` for an
    explicit cascade that also clears this project's experiment/iteration.
    """

    s, normalized_team_id, normalized_project_id, active_project = _require_active_research_project(
        team_id, project_id
    )
    run_ids = _project_source_collection_run_ids(normalized_team_id, normalized_project_id)
    _assert_project_source_search_not_active(normalized_team_id, run_ids)
    _assert_project_agent_tasks_not_active(normalized_team_id, normalized_project_id)

    removed_candidate_ids: set[str] = set()
    removed_round_ids: set[str] = set()
    with s._WORKFLOW_LOCK:
        stage_store = s._load_stage_round_store(normalized_team_id)
        stage_rounds = s._stage_rounds(stage_store)
        # Only this project's experiment/iteration rounds block Stage-1 reset.
        # Other projects on the same team keep their own audit trail independently.
        downstream_rounds = [
            item
            for item in stage_rounds
            if str(item.get("stageType") or "") in {"experiment", "iteration"}
            and _stage_round_belongs_to_research_project(item, normalized_project_id, run_ids)
        ]
        if downstream_rounds:
            raise s.TeamWorkflowOrchestrationError(
                "本项目已有实验设计或迭代产物，资料批次保留供审计，无法仅清空资料后重开。"
                "请使用「连同实验与迭代一起清空」。 "
                "This project already has downstream experiment or iteration artifacts; source collection is preserved for audit. "
                "Use the include-downstream project reset."
            )

        candidate_store = s._load_candidate_store(normalized_team_id)
        candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
        removable_candidates: list[dict[str, Any]] = []
        kept_candidates: list[dict[str, Any]] = []
        project_non_source_candidates: list[dict[str, Any]] = []
        project_protected_source_candidates: list[dict[str, Any]] = []
        for candidate in candidates:
            metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
            imported = metadata.get("importedFromDataRecord") if isinstance(metadata.get("importedFromDataRecord"), dict) else {}
            imported_run_id = s._trim_text(imported.get("runId"), max_length=160)
            if candidate.get("candidateType") == "source_manifest" and imported_run_id in run_ids:
                removable_candidates.append(candidate)
                continue
            if not _candidate_belongs_to_research_project(candidate, normalized_project_id, run_ids):
                # Other research projects' candidates stay untouched.
                kept_candidates.append(candidate)
                continue
            kept_candidates.append(candidate)
            if str(candidate.get("candidateType") or "") != "source_manifest":
                project_non_source_candidates.append(candidate)
            else:
                project_protected_source_candidates.append(candidate)
        if project_non_source_candidates:
            raise s.TeamWorkflowOrchestrationError(
                "本项目已有下游科研候选（非资料清单），资料批次保留供审计，无法仅清空资料后重开。"
                "请使用「连同实验与迭代一起清空」。 "
                "This project already contains downstream research candidates; source collection is preserved for audit. "
                "Use the include-downstream project reset."
            )
        if project_protected_source_candidates:
            raise s.TeamWorkflowOrchestrationError(
                "本项目存在不可重置的资料记录（不在当前可清空批次内），资料保留供审计。"
                " This project contains source records outside its resettable batches; source collection is preserved for audit."
            )

        removed_candidate_ids = {
            s._trim_text(item.get("candidateId"), max_length=160)
            for item in removable_candidates
            if s._trim_text(item.get("candidateId"), max_length=160)
        }
        remaining_rounds: list[dict[str, Any]] = []
        for item in stage_rounds:
            source_run_ids = _stage_round_source_run_ids(item)
            belongs = _stage_round_belongs_to_research_project(item, normalized_project_id, run_ids)
            is_resettable_round = (
                belongs
                and str(item.get("stageType") or "") == "knowledge_collection"
                and (not source_run_ids or source_run_ids.issubset(run_ids))
            )
            if is_resettable_round:
                stage_round_id = s._trim_text(item.get("stageRoundId"), max_length=160)
                if stage_round_id:
                    removed_round_ids.add(stage_round_id)
                continue
            remaining_rounds.append(item)

        candidate_store["candidates"] = kept_candidates
        candidate_store["updatedAt"] = s.utc_now_iso()
        stage_store["rounds"] = remaining_rounds
        stage_store["updatedAt"] = s.utc_now_iso()
        workflow = s._load_or_create_workflow(normalized_team_id)
        workflow["activeWorkflowItems"] = [
            item
            for item in list(workflow.get("activeWorkflowItems") or [])
            if isinstance(item, dict)
            and s._trim_text(item.get("candidateId"), max_length=160) not in (run_ids | removed_candidate_ids)
        ]
        workflow["updatedAt"] = s.utc_now_iso()
        s._write_json(s._candidate_store_path(normalized_team_id), candidate_store)
        s._write_json(s._stage_round_store_path(normalized_team_id), stage_store)
        s._write_json(s._workflow_path(normalized_team_id), workflow)

    removed_run_ids = _delete_project_source_collection_runs(normalized_team_id, run_ids)

    s._record_workflow_event(
        "source_collection.research_project_reset",
        normalized_team_id,
        fields={
            "researchProjectId": normalized_project_id,
            "includeDownstream": False,
            "removedRunCount": len(removed_run_ids),
            "removedSourceCandidateCount": len(removed_candidate_ids),
            "removedStageRoundCount": len(removed_round_ids),
        },
        outcome="completed",
    )
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "researchProjectId": normalized_project_id,
        "experimentName": active_project["name"],
        "includeDownstream": False,
        "removedRunIds": removed_run_ids,
        "removedRunCount": len(removed_run_ids),
        "removedSourceCandidateCount": len(removed_candidate_ids),
        "removedStageRoundCount": len(removed_round_ids),
        "removedExperimentPlanCount": 0,
        "nextAction": "Create a fresh source-collection batch for this research project.",
    }


def reset_research_project_progress(team_id: str, project_id: str) -> dict[str, Any]:
    """Explicitly clear this project's Stage-1 sources plus experiment/iteration.

    Scope (active research project only):
    - source-collection runs and storage artifacts
    - knowledge_collection / experiment / iteration stage rounds
    - candidates owned by the project (source manifests and downstream)
    - experiment plans owned by the project

    Preserved: other projects, Agent conversations, formal knowledge ledgers,
    challenge question ledgers, and team-wide configuration.
    """

    s, normalized_team_id, normalized_project_id, active_project = _require_active_research_project(
        team_id, project_id
    )
    run_ids = _project_source_collection_run_ids(normalized_team_id, normalized_project_id)
    _assert_project_source_search_not_active(normalized_team_id, run_ids)
    _assert_project_agent_tasks_not_active(normalized_team_id, normalized_project_id)

    removed_candidate_ids: set[str] = set()
    removed_round_ids: set[str] = set()
    removed_plan_ids: set[str] = set()
    with s._WORKFLOW_LOCK:
        stage_store = s._load_stage_round_store(normalized_team_id)
        stage_rounds = s._stage_rounds(stage_store)
        remaining_rounds: list[dict[str, Any]] = []
        for item in stage_rounds:
            belongs = _stage_round_belongs_to_research_project(item, normalized_project_id, run_ids)
            if belongs:
                stage_round_id = s._trim_text(item.get("stageRoundId"), max_length=160)
                if stage_round_id:
                    removed_round_ids.add(stage_round_id)
                continue
            remaining_rounds.append(item)

        candidate_store = s._load_candidate_store(normalized_team_id)
        candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
        kept_candidates: list[dict[str, Any]] = []
        for candidate in candidates:
            metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
            imported = metadata.get("importedFromDataRecord") if isinstance(metadata.get("importedFromDataRecord"), dict) else {}
            imported_run_id = s._trim_text(imported.get("runId"), max_length=160)
            remove = (
                (candidate.get("candidateType") == "source_manifest" and imported_run_id in run_ids)
                or _candidate_belongs_to_research_project(candidate, normalized_project_id, run_ids)
            )
            if remove:
                candidate_id = s._trim_text(candidate.get("candidateId"), max_length=160)
                if candidate_id:
                    removed_candidate_ids.add(candidate_id)
                continue
            kept_candidates.append(candidate)

        plan_store = s._load_experiment_plan_store(normalized_team_id)
        plans = [item for item in list(plan_store.get("plans") or []) if isinstance(item, dict)]
        kept_plans: list[dict[str, Any]] = []
        for plan in plans:
            plan_project_id = s._trim_text(plan.get("researchProjectId"), max_length=160)
            plan_id = s._trim_text(plan.get("planId"), max_length=160)
            if plan_project_id and plan_project_id == normalized_project_id:
                if plan_id:
                    removed_plan_ids.add(plan_id)
                continue
            # Plans without project id stay unless they only reference removed candidates.
            if not plan_project_id and plan_id:
                linked_candidate_ids = {
                    s._trim_text(value, max_length=160)
                    for value in [
                        plan.get("candidateId"),
                        plan.get("hypothesisCandidateId"),
                        *((plan.get("hypothesisCandidateIds") or []) if isinstance(plan.get("hypothesisCandidateIds"), list) else []),
                    ]
                    if s._trim_text(value, max_length=160)
                }
                if linked_candidate_ids and linked_candidate_ids.issubset(removed_candidate_ids):
                    removed_plan_ids.add(plan_id)
                    continue
            kept_plans.append(plan)
        active_plan_id = s._trim_text(plan_store.get("activePlanId"), max_length=160)
        if active_plan_id in removed_plan_ids:
            plan_store["activePlanId"] = ""
        plan_store["plans"] = kept_plans
        plan_store["updatedAt"] = s.utc_now_iso()

        candidate_store["candidates"] = kept_candidates
        candidate_store["updatedAt"] = s.utc_now_iso()
        stage_store["rounds"] = remaining_rounds
        stage_store["updatedAt"] = s.utc_now_iso()
        workflow = s._load_or_create_workflow(normalized_team_id)
        workflow["activeWorkflowItems"] = [
            item
            for item in list(workflow.get("activeWorkflowItems") or [])
            if isinstance(item, dict)
            and s._trim_text(item.get("candidateId"), max_length=160) not in (run_ids | removed_candidate_ids)
        ]
        workflow["updatedAt"] = s.utc_now_iso()
        s._write_json(s._candidate_store_path(normalized_team_id), candidate_store)
        s._write_json(s._stage_round_store_path(normalized_team_id), stage_store)
        s._write_json(s._experiment_plan_store_path(normalized_team_id), plan_store)
        s._write_json(s._workflow_path(normalized_team_id), workflow)

    removed_run_ids = _delete_project_source_collection_runs(normalized_team_id, run_ids)
    s._record_workflow_event(
        "research_project.progress_reset",
        normalized_team_id,
        fields={
            "researchProjectId": normalized_project_id,
            "includeDownstream": True,
            "removedRunCount": len(removed_run_ids),
            "removedSourceCandidateCount": len(removed_candidate_ids),
            "removedStageRoundCount": len(removed_round_ids),
            "removedExperimentPlanCount": len(removed_plan_ids),
        },
        outcome="completed",
    )
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "researchProjectId": normalized_project_id,
        "experimentName": active_project["name"],
        "includeDownstream": True,
        "removedRunIds": removed_run_ids,
        "removedRunCount": len(removed_run_ids),
        "removedSourceCandidateCount": len(removed_candidate_ids),
        "removedStageRoundCount": len(removed_round_ids),
        "removedExperimentPlanCount": len(removed_plan_ids),
        "nextAction": "Create a fresh source-collection batch for this research project.",
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
        circuit = _search_circuit()
        exhausted_duplicate_marker = circuit.exhausted_duplicate_marker_for_run(
            normalized_team_id,
            normalized_run_id,
        )
    except Exception:  # noqa: BLE001 - circuit must fail open to the legacy path
        exhausted_duplicate_marker = {}
    if exhausted_duplicate_marker:
        # Evidence-request circuit: this run's goal already exhausted its
        # rewrite budget and a duplicate request was routed back here.  Do
        # not repeat any provider search; return the structured gap marker
        # as a terminal, zero-query execution result (terminal status maps
        # to "completed" so the chain bridge still handoffs).
        result = _search_circuit().build_exhausted_duplicate_result(
            exhausted_duplicate_marker,
            run=run,
            run_status=None,
            assignments=assignments,
        )
    else:
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
            # The data-processing run itself must become terminal too: the
            # circuit's liveness gate reads this status, and a run left in
            # "collecting" would keep every later ensure for the same goal
            # pinned to reuse_in_flight forever.  Both writes are best-effort;
            # the original search error stays the raised error.
            try:
                s.data_processing_service.fail_processing_run(
                    normalized_run_id,
                    reason=f"source_collection_search_failed: {type(exc).__name__}",
                )
            except Exception:  # noqa: BLE001 - liveness marking must not mask the failure
                pass
            # Close the ledger attempt (idempotent; only touches non-executed
            # entries) so decide_circuit_action stops treating it as in flight.
            try:
                _search_circuit().record_attempt_outcome(
                    normalized_team_id,
                    normalized_run_id,
                    failure_result,
                )
            except Exception:  # noqa: BLE001 - ledger must never mask the failure
                pass
            s._sync_source_collection_stage_round_after_search(
                normalized_team_id,
                normalized_run_id,
                failure_result,
                terminal_status="failed",
                terminal_summary="资料搜索执行失败，等待检查搜索错误。",
            )
            raise
        try:
            _search_circuit().record_attempt_outcome(normalized_team_id, normalized_run_id, result)
        except Exception:  # noqa: BLE001 - ledger must never fail the search
            pass

    final_run = result.get("run") if isinstance(result.get("run"), dict) else run
    final_assignments = [item for item in list(result.get("assignments") or []) if isinstance(item, dict)]
    try:
        final_records = s.data_processing_service.list_records(normalized_run_id).get("records") if normalized_run_id else []
    except s.data_processing_service.DataProcessingError:
        final_records = []
    terminal_status = s._source_collection_work_run_terminal_status(result)
    terminal_phase = s._source_collection_work_run_terminal_phase(result)
    terminal_summary = s._source_collection_work_run_terminal_summary(result)
    terminal_extra: dict[str, Any] = {
        "attemptedQueryCount": s._source_collection_count(result.get("attemptedQueryCount")),
        "executedQueryCount": s._source_collection_count(result.get("executedQueryCount")),
        "failedQueryCount": s._source_collection_count(result.get("failedQueryCount")),
        "recordCount": s._source_collection_count(result.get("recordCount")),
        "importedCount": s._source_collection_count(result.get("importedCount")),
        "resultCount": s._source_collection_count(result.get("resultCount")),
    }
    evidence_gap = result.get("evidenceGap") if isinstance(result.get("evidenceGap"), dict) else {}
    if str(result.get("status") or "") == "evidence_gap_unavailable":
        # Surface the circuit verdict on the collection run status snapshot.
        terminal_extra["evidenceGapUnavailable"] = True
        terminal_extra["evidenceGapMarkerId"] = str(evidence_gap.get("markerId") or "")[:64]
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
        extra=terminal_extra,
    )
    s._sync_source_collection_stage_round_after_search(
        normalized_team_id,
        normalized_run_id,
        result,
        terminal_status=terminal_status,
        terminal_summary=terminal_summary,
    )
    # Write the batch outcome back onto the data-processing run itself: the
    # work-run snapshot above is worker bookkeeping only, and without this
    # writeback run.json stays "collecting" forever even after the last batch
    # finishes.  Best-effort — the search result is already durable, so a
    # failed status writeback must not fail the batch.
    try:
        if terminal_status == "failed":
            s.data_processing_service.fail_processing_run(
                normalized_run_id,
                reason="source_collection_batch_failed: every query failed",
            )
        elif terminal_status != "cancelled":
            # Cancelled runs were already driven terminal by
            # cancel_processing_run inside stop_source_collection_search.
            s.data_processing_service.complete_collection_batch(
                normalized_run_id,
                terminal_status=terminal_status,
            )
    except Exception:  # noqa: BLE001, S110 - run.json writeback must not fail the batch
        pass
    return result

def start_source_collection_search_background(team_id: str, run_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_run_id = s._normalize_required_id(run_id, "Data processing run id is required.")
    team = s.team_service.get_team(normalized_team_id)
    request_payload = dict(payload) if isinstance(payload, dict) else {}
    provider = s._trim_text(request_payload.get("provider"), max_length=80)
    if provider and provider not in s.SOURCE_COLLECTION_SEARCH_PROVIDERS:
        raise s.TeamWorkflowOrchestrationError(f"Unsupported source collection search provider: {provider}")
    provider = provider or s.SOURCE_COLLECTION_SEARCH_PROVIDERS[0]
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
        stale_snapshot_reclaimed = (
            isinstance(existing_active_snapshot, dict)
            and s._trim_text(existing_active_snapshot.get("runId"), max_length=160) == normalized_run_id
            and s._trim_text(existing_active_snapshot.get("teamId"), max_length=160) == normalized_team_id
            and s._source_collection_snapshot_is_age_stale(existing_active_snapshot)
        )
        if stale_snapshot_reclaimed:
            # The previous worker is gone (its active snapshot outlived the
            # stale-age window without progress).  Persisting the new queued
            # snapshot below replaces the dead active marker, and the worker
            # starts for real instead of short-circuiting forever.
            s._record_workflow_event(
                "source_collection.search_background_stale_snapshot_reclaimed",
                normalized_team_id,
                level="warning",
                outcome="degraded",
                fields={
                    "runId": normalized_run_id,
                    "provider": provider,
                    "activeStatus": str(existing_active_snapshot.get("status") or ""),
                    "activePhase": str(existing_active_snapshot.get("currentPhase") or ""),
                    "activeUpdatedAt": str(existing_active_snapshot.get("updatedAt") or ""),
                    "staleSnapshotMs": s._source_collection_snapshot_stale_ms(),
                },
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


def _source_collection_summary_search_plan(team_id: str, run_id: str) -> dict[str, Any]:
    """Project the bounded search-plan identity needed to resume a selected run."""

    s = _service()
    if not run_id:
        return {}
    path = s._source_collection_storage_artifact_paths(team_id, run_id)["searchPlanPath"]
    if not path.is_file():
        return {}
    try:
        payload = s.json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    query_seeds = s._normalize_text_list(
        payload.get("querySeeds"),
        max_items=s.SOURCE_COLLECTION_MAX_QUERIES,
        max_length=220,
    )
    queries = [item for item in list(payload.get("queries") or []) if isinstance(item, dict)]
    return {
        "planId": s._trim_text(payload.get("planId"), max_length=128),
        "querySeeds": query_seeds,
        "queryCount": s._normalize_int(
            payload.get("queryCount"),
            default=len(queries),
            minimum=0,
            maximum=s.SOURCE_COLLECTION_MAX_QUERIES,
        ),
    }


def get_source_collection_summary(team_id: str, *, run_id: str = "") -> dict[str, Any]:
    """Return the fast first-paint source collection state without heavy repair reads."""

    s = _service()
    started_at = s.time.perf_counter()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.assert_team_exists(normalized_team_id)
    active_project = s.get_active_research_project(normalized_team_id)
    active_project_id = active_project["projectId"]
    normalized_run_id = s._trim_text(run_id, max_length=160)
    selected_run: dict[str, Any] | None = None
    if normalized_run_id:
        try:
            selected_run = s.data_processing_service.get_processing_run(normalized_run_id)
        except s.data_processing_service.DataProcessingError as exc:
            raise s.TeamWorkflowOrchestrationError(str(exc)) from exc
        if not s._source_collection_run_belongs_to_team(selected_run, normalized_team_id):
            raise s.TeamWorkflowOrchestrationError("Data processing run does not belong to this team.")
        if not s._source_collection_run_belongs_to_research_project(selected_run, active_project_id):
            raise s.TeamWorkflowOrchestrationError("Data processing run does not belong to the active research project.")
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
            if (
                isinstance(item, dict)
                and s._source_collection_run_belongs_to_team(item, normalized_team_id)
                and s._source_collection_run_belongs_to_research_project(item, active_project_id)
            )
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
            data_run_exists=selected_run is not None,
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
        "searchPlan": _source_collection_summary_search_plan(normalized_team_id, normalized_run_id),
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
