"""Workflow ops: iteration proposal, deliverables export, inbox, stage-round glue.

Claim scope: propose_iteration, export_deliverables, candidate validation,
team-workflow inbox bridge, research memory summary helpers, and residual
stage-round helpers still on the facade.

Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


def _service():
    from core.web.services import team_workflow_orchestration_service

    return team_workflow_orchestration_service


def _active_stage_round(rounds: list[dict[str, Any]], stage_type: str) -> dict[str, Any] | None:
    s = _service()
    candidates = [
        item
        for item in rounds
        if str(item.get("stageType") or "") == stage_type and str(item.get("status") or "") in s.RESEARCH_STAGE_ACTIVE_STATUSES
    ]
    return s._latest_stage_round(candidates)


def _build_stage_round(
    team_id: str,
    stage_type: str,
    payload: dict[str, Any],
    rounds: list[dict[str, Any]],
    *,
    previous_round: dict[str, Any] | None,
    requested_by_agent: str,
    team: dict[str, Any],
) -> dict[str, Any]:
    s = _service()
    now = s.utc_now_iso()
    round_number = s._stage_round_number(rounds, stage_type)
    topic = s._trim_text(payload.get("topic"), max_length=500) or s._trim_text(previous_round.get("topic") if previous_round else "", max_length=500)
    goal = s._trim_text(payload.get("goal"), max_length=1000) or s._trim_text(previous_round.get("goal") if previous_round else "", max_length=1000)
    if stage_type == "knowledge_collection" and not topic:
        raise s.TeamWorkflowOrchestrationError("Research topic is required to start knowledge collection.")
    if not topic:
        topic = s._stage_default_topic(stage_type, previous_round)
    if not goal:
        goal = s._stage_default_goal(stage_type, previous_round)
    query_seeds = s._stage_query_seeds(payload, previous_round, topic=topic, goal=goal)
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "stageRoundId": s._new_record_id("stage"),
        "teamId": team_id,
        "stageType": stage_type,
        "roundNumber": round_number,
        "status": "initializing",
        "title": s._trim_text(payload.get("title"), max_length=180) or f"{s.RESEARCH_STAGE_DEFAULTS[stage_type]['title']} {round_number}",
        "topic": topic,
        "goal": goal,
        "requestedByAgent": requested_by_agent,
        "ownerAgentId": s._source_collection_owner_agent_id(team, payload),
        "upstreamRoundIds": s._stage_upstream_round_ids(payload, rounds, stage_type, previous_round),
        "sourceRunIds": [],
        "assignmentIds": [],
        "agentRoleAssignments": [],
        "querySeeds": query_seeds,
        "suggestedQuerySeeds": s._suggest_stage_query_seeds(previous_round, topic=topic, goal=goal),
        "inputRefs": s._normalize_text_list(payload.get("inputRefs"), max_items=120, max_length=240),
        "searchLanguages": s._source_collection_search_languages(payload.get("searchLanguages")),
        "sourceTypes": s._source_collection_source_types(payload.get("sourceTypes")),
        "maxResultsPerQuery": s._normalize_int(
            payload.get("maxResultsPerQuery"),
            default=s.SOURCE_COLLECTION_DEFAULT_MAX_RESULTS_PER_QUERY,
            minimum=1,
            maximum=100,
        ),
        "workflowItemRef": {},
        "dataSearchPlanRef": {},
        "teamMemoryRecordId": "",
        "teamMemoryRecord": {},
        "coordinationContract": {},
        "planningContract": {},
        "warnings": [],
        "boundaries": s._research_stage_boundaries(),
        "createdAt": now,
        "updatedAt": now,
    }


def _continued_stage_round_payload(stage_round: dict[str, Any], stage_type: str) -> dict[str, Any]:
    """Return enough context for the UI to show that an active stage was reused."""
    s = _service()

    if stage_type != "knowledge_collection":
        return {}
    source_run_ids = [str(item) for item in list(stage_round.get("sourceRunIds") or []) if str(item or "").strip()]
    source_run_id = source_run_ids[0] if source_run_ids else ""
    if not source_run_id:
        return {
            "continuedSourceRunRef": {
                "runId": "",
                "status": "missing",
                "recordCount": 0,
                "assignmentCount": 0,
                "openAssignmentCount": 0,
                "message": "Active knowledge-collection round has no source run id.",
            }
        }
    try:
        run = s.data_processing_service.get_processing_run(source_run_id)
        assignment_payload = s.data_processing_service.list_collection_assignments(source_run_id)
    except s.data_processing_service.DataProcessingNotFoundError:
        return {
            "continuedSourceRunRef": {
                "runId": source_run_id,
                "status": "missing",
                "recordCount": 0,
                "assignmentCount": 0,
                "openAssignmentCount": 0,
                "message": "Active knowledge-collection round points to a missing source run.",
            }
        }
    assignments = [item for item in list(assignment_payload.get("assignments") or []) if isinstance(item, dict)]
    assignment_summary = s._source_collection_assignment_stage_summary(assignments)
    summary = run.get("summary") if isinstance(run.get("summary"), dict) else {}
    scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    data_search_plan_ref = scope.get("dataSearchPlanRef") if isinstance(scope.get("dataSearchPlanRef"), dict) else {}
    return {
        "run": run,
        "assignments": assignments,
        "assignmentCount": len(assignments),
        "continuedSourceRunRef": {
            "runId": source_run_id,
            "status": str(run.get("status") or ""),
            "recordCount": s._normalize_int(summary.get("recordCount"), default=0, minimum=0, maximum=100000),
            "assignmentCount": s._normalize_int(summary.get("assignmentCount"), default=len(assignments), minimum=0, maximum=100000),
            "openAssignmentCount": s._normalize_int(summary.get("openAssignmentCount"), default=0, minimum=0, maximum=100000),
            "searchOpenAssignmentCount": assignment_summary["searchOpenAssignmentCount"],
            "collectionOpenAssignmentCount": assignment_summary["collectionOpenAssignmentCount"],
            "downstreamOpenAssignmentCount": assignment_summary["downstreamOpenAssignmentCount"],
            "queryCount": s._normalize_int(data_search_plan_ref.get("queryCount"), default=0, minimum=0, maximum=s.SOURCE_COLLECTION_MAX_QUERIES),
            "planId": s._trim_text(data_search_plan_ref.get("planId"), max_length=160),
            "externalSearchTriggered": bool(data_search_plan_ref.get("externalSearchTriggered")),
            "message": "Reused the active source-collection run instead of creating a new one.",
        },
    }


def _default_workflow(team_id: str, *, workflow_kind: str, owner_agent_id: str) -> dict[str, Any]:
    s = _service()
    now = s.utc_now_iso()
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "workflowId": s.DEFAULT_WORKFLOW_ID,
        "teamId": team_id,
        "workflowKind": workflow_kind,
        "status": "active",
        "ownerAgentId": owner_agent_id,
        "stateMachine": {
            "currentStage": "knowledge_collection",
            "nodes": [
                {"nodeId": "knowledge_collection", "label": "知识搜集"},
            {"nodeId": "source_screening", "label": "资料审查"},
            {"nodeId": "candidate_ingestion", "label": "资料入库"},
            {"nodeId": "team_memory_ready", "label": "团队知识库已接入"},
            ],
            "transitions": [
                {"from": "knowledge_collection", "to": "source_screening"},
                {"from": "source_screening", "to": "candidate_ingestion"},
                {"from": "candidate_ingestion", "to": "team_memory_ready"},
                {"from": "source_screening", "to": "knowledge_collection", "type": "rework"},
                {"from": "candidate_ingestion", "to": "source_screening", "type": "rework"},
            ],
        },
        "routingPolicy": {
            "coordinationAgentId": owner_agent_id,
            "functionalAgentsMayRequestTransfer": True,
            "finalStateWriter": owner_agent_id,
        },
        "transferPolicy": {
            "requiresUserConfirmation": False,
            "requestedBy": "functional_agent",
            "decidedBy": owner_agent_id,
            "recordDecidedByAgent": True,
        },
        "activeWorkflowItems": [],
        "createdAt": now,
        "updatedAt": now,
    }


def _find_stage_round(rounds: list[dict[str, Any]], stage_round_id: str) -> dict[str, Any] | None:
    s = _service()
    for item in rounds:
        if str(item.get("stageRoundId") or "") == stage_round_id:
            return item
    return None


def _legacy_research_lifecycle_memory_contexts(
    *,
    team_id: str,
    candidate_store: dict[str, Any],
    plans: list[dict[str, Any]],
    design_plan: dict[str, Any] | None,
    best_plan: dict[str, Any] | None,
    latest_experiment: dict[str, Any] | None,
    latest_iteration: dict[str, Any] | None,
    active_loop: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    s = _service()
    design_contract = (
        design_plan.get("experimentContract")
        if isinstance((design_plan or {}).get("experimentContract"), dict)
        else {}
    )
    best_contract = (
        best_plan.get("experimentContract")
        if isinstance((best_plan or {}).get("experimentContract"), dict)
        else {}
    )
    research_question = s._trim_text(
        design_contract.get("researchQuestion")
        or best_contract.get("researchQuestion")
        or (latest_experiment or {}).get("topic")
        or (latest_experiment or {}).get("goal")
        or (latest_iteration or {}).get("topic")
        or (latest_iteration or {}).get("goal")
        or (active_loop or {}).get("title")
        or "research lifecycle memory projection",
        max_length=1200,
    )
    actor_agent_id = s._trim_text(
        (latest_experiment or {}).get("requestedByAgent")
        or (latest_experiment or {}).get("ownerAgentId")
        or (latest_iteration or {}).get("requestedByAgent")
        or (latest_iteration or {}).get("ownerAgentId"),
        max_length=160,
    )
    knowledge_results, retrieval_status = s._research_memory_knowledge_results(
        team_id,
        research_question=research_question,
        actor_agent_id=actor_agent_id,
    )
    loop_store = s._read_json(s._team_workflow_root(team_id) / "research_loops" / "index.json")
    common = {
        "research_question": research_question,
        "candidates": [
            item
            for item in list(candidate_store.get("candidates") or [])
            if isinstance(item, dict)
        ],
        "plans": plans,
        "loops": [
            item
            for item in list(loop_store.get("loops") or [])
            if isinstance(item, dict)
        ],
        "knowledge_results": knowledge_results,
        "retrieval_status": retrieval_status,
    }
    return {
        "stage2": s._build_research_memory_context(
            stage_type="experiment_design",
            control_plan=design_plan,
            **common,
        ),
        "stage3": s._build_research_memory_context(
            stage_type="experiment_execution_iteration",
            control_plan=design_plan,
            **common,
        ),
    }


def _load_or_create_workflow(team_id: str, *, persist_repair: bool = True) -> dict[str, Any]:
    s = _service()
    path = s._workflow_path(team_id)
    if path.exists():
        raw_workflow = s._read_json(path)
        workflow = s._repair_workflow(raw_workflow, team_id)
        if persist_repair and workflow != raw_workflow:
            s._write_json(path, workflow)
        return workflow
    workflow = s._default_workflow(
        team_id,
        workflow_kind=s.WORKFLOW_KIND_CHALLENGE_CUP_RESEARCH,
        owner_agent_id=s.DEFAULT_OWNER_AGENT_ID,
    )
    s._write_json(path, workflow)
    s._record_workflow_event(
        "workflow.created",
        team_id,
        fields={"workflowId": workflow["workflowId"], "workflowKind": workflow["workflowKind"]},
    )
    return workflow


def _reconcile_superseded_research_stage_rounds(team_id: str) -> bool:
    s = _service()
    now = s.utc_now_iso()
    superseded_pairs: list[tuple[str, str]] = []
    with s._WORKFLOW_LOCK:
        store = s._load_stage_round_store(team_id)
        rounds = s._stage_rounds(store)
        for stage_type in s.RESEARCH_STAGE_TYPES:
            stage_rounds = [
                item
                for item in rounds
                if s._trim_text(item.get("stageType"), max_length=80) == stage_type
            ]
            if len(stage_rounds) < 2:
                continue
            latest_round = max(
                stage_rounds,
                key=lambda item: (
                    s._source_collection_count(item.get("roundNumber")),
                    s._trim_text(item.get("createdAt"), max_length=120),
                    s._trim_text(item.get("updatedAt"), max_length=120),
                ),
            )
            latest_round_id = s._trim_text(latest_round.get("stageRoundId"), max_length=160)
            for stage_round in stage_rounds:
                stage_round_id = s._trim_text(stage_round.get("stageRoundId"), max_length=160)
                if stage_round is latest_round or not stage_round_id:
                    continue
                if s._trim_text(stage_round.get("status"), max_length=80) not in s.RESEARCH_STAGE_ACTIVE_STATUSES:
                    continue
                stage_round["status"] = "superseded"
                stage_round["supersededByStageRoundId"] = latest_round_id
                stage_round["supersededAt"] = now
                stage_round["updatedAt"] = now
                warnings = [item for item in list(stage_round.get("warnings") or []) if isinstance(item, dict)]
                if not any(s._trim_text(item.get("code"), max_length=120) == "stage_round_superseded" for item in warnings):
                    warnings.append(
                        {
                            "code": "stage_round_superseded",
                            "severity": "info",
                            "message": "A newer round of the same research stage superseded this active round.",
                        }
                    )
                stage_round["warnings"] = warnings
                superseded_pairs.append((stage_round_id, latest_round_id))
        if superseded_pairs:
            store["updatedAt"] = now
            s._write_json(s._stage_round_store_path(team_id), store)
    for stage_round_id, latest_round_id in superseded_pairs:
        s._record_workflow_event(
            "research_stage_round.superseded_by_newer_round",
            team_id,
            fields={
                "stageRoundId": stage_round_id,
                "supersededByStageRoundId": latest_round_id,
            },
            outcome="reconciled",
            lifecycle=True,
        )
    return bool(superseded_pairs)


def _research_memory_context_summary(value: Any) -> dict[str, Any]:
    s = _service()
    context = value if isinstance(value, dict) else {}
    retrieval = context.get("retrieval") if isinstance(context.get("retrieval"), dict) else {}
    claim_map = [
        item
        for item in list(context.get("claimMap") or [])
        if isinstance(item, dict)
    ]
    claim_status_counts = {
        status: sum(
            1
            for item in claim_map
            if str(item.get("status") or "") == status
        )
        for status in ("qualified", "unsupported", "rejected", "not_established")
    }
    allowed_variable_contract = (
        context.get("allowedVariableContract")
        if isinstance(context.get("allowedVariableContract"), dict)
        else {}
    )
    allowed_variables = [
        str(item.get("path") or "")
        for item in list(allowed_variable_contract.get("variables") or [])
        if isinstance(item, dict) and str(item.get("path") or "").strip()
    ][:16]
    allowed_variable_details = [
        {
            "path": str(item.get("path") or "")[:240],
            "source": str(item.get("source") or "")[:80],
            "evidenceRef": str(item.get("evidenceRef") or "")[:240],
        }
        for item in list(allowed_variable_contract.get("variables") or [])
        if isinstance(item, dict) and str(item.get("path") or "").strip()
    ][:16]
    claim_details = [
        {
            "claimId": str(item.get("claimId") or "")[:160],
            "claim": str(item.get("claim") or "")[:800],
            "status": str(item.get("status") or "")[:64],
            "supportEvidenceRefs": [
                {
                    "type": str(ref.get("type") or "")[:80],
                    "id": str(ref.get("id") or "")[:500],
                }
                for ref in list(item.get("supportEvidenceRefs") or [])
                if isinstance(ref, dict) and str(ref.get("id") or "").strip()
            ][:8],
            "counterEvidenceRefs": [
                {
                    "type": str(ref.get("type") or "")[:80],
                    "id": str(ref.get("id") or "")[:500],
                }
                for ref in list(item.get("counterEvidenceRefs") or [])
                if isinstance(ref, dict) and str(ref.get("id") or "").strip()
            ][:8],
            "applicableBoundaries": [
                str(boundary)[:360]
                for boundary in list(item.get("applicableBoundaries") or [])
                if str(boundary).strip()
            ][:12],
            "sourcePlanIds": [
                str(plan_id)[:160]
                for plan_id in list(item.get("sourcePlanIds") or [])
                if str(plan_id).strip()
            ][:12],
        }
        for item in claim_map[:12]
    ]
    forbidden = [
        item
        for item in list(context.get("forbiddenDuplicateExperiments") or [])
        if isinstance(item, dict)
    ]
    return {
        "contextId": str(context.get("contextId") or ""),
        "knowledgeItemCount": int(retrieval.get("knowledgeItemCount") or 0),
        "reviewedSourceCount": int(retrieval.get("reviewedSourceCount") or 0),
        "negativeExperimentCount": int(retrieval.get("negativeExperimentCount") or 0),
        "successfulRunCount": int(retrieval.get("successfulRunCount") or 0),
        "forbiddenDuplicateExperimentCount": len(forbidden),
        "claimCount": len(claim_map),
        "claimStatusCounts": claim_status_counts,
        "allowedVariableCount": len(allowed_variables),
        "allowedVariables": allowed_variables,
        "allowedVariableContract": {
            "status": str(allowed_variable_contract.get("status") or "missing"),
            "variables": allowed_variable_details,
            "frozenControls": [
                str(item)[:360]
                for item in list(allowed_variable_contract.get("frozenControls") or [])
                if str(item).strip()
            ][:12],
        },
        "claimMap": claim_details,
        "claimMapPreview": [
            {
                "claimId": str(item.get("claimId") or ""),
                "claim": str(item.get("claim") or ""),
                "status": str(item.get("status") or ""),
            }
            for item in claim_map[:6]
        ],
        "missingEvidence": [
            str(item)
            for item in list(context.get("missingEvidence") or [])
            if str(item).strip()
        ][:12],
    }


def _stage_phase_status(
    team_id: str,
    stage_type: str,
    rounds: list[dict[str, Any]],
    *,
    workflow: dict[str, Any],
    team: dict[str, Any],
) -> dict[str, Any]:
    s = _service()
    stage_rounds = [item for item in rounds if str(item.get("stageType") or "") == stage_type]
    active_round = s._active_stage_round(rounds, stage_type)
    latest_round = active_round or s._latest_stage_round(stage_rounds)
    defaults = s.RESEARCH_STAGE_DEFAULTS[stage_type]
    return {
        "stageType": stage_type,
        "label": s._stage_label(stage_type),
        "status": str(latest_round.get("status") if latest_round else "not_started"),
        "roundCount": len(stage_rounds),
        "activeRoundId": str(active_round.get("stageRoundId") if active_round else ""),
        "latestRound": latest_round,
        "primaryAction": defaults["continueActionZh"] if active_round else defaults["primaryActionZh"],
        "secondaryAction": defaults["newRoundActionZh"],
        "canStart": True,
        "canContinue": bool(active_round),
        "canNewRound": bool(stage_rounds),
        "requiresUserDecision": stage_type in {"experiment", "iteration"},
        "readiness": s._stage_readiness(stage_type, rounds),
        "coordinationRoomId": str(team.get("linkedChatRoomId") or ""),
        "storagePath": s._relative_path(s._stage_round_store_path(team_id)),
    }


def _stage_round_store_path(team_id: str) -> Path:
    s = _service()
    return s._team_workflow_root(team_id) / "research_stage_rounds" / "index.json"


def _submit_team_workflow_inbox_via_kernel(
    *,
    target_agent_id: str,
    content: str,
    source_agent_id: str,
    thread_id: str,
    kind: str,
    summary: str,
    created_by: str,
    metadata: dict[str, Any],
    wake_target: bool,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    s = _service()
    from core.agent_kernel.adapters import submit_agent_message_event

    normalized_metadata = dict(metadata or {})
    source_id = str(thread_id or normalized_metadata.get("sourceMessageId") or "").strip()
    created_by_value = str(created_by or source_agent_id or "team_workflow").strip()
    kernel_metadata = {
        **normalized_metadata,
        "source": "team_workflow_orchestration",
        "sourceSurface": "team_workflow",
        "sourceMessageId": source_id,
        "projectionRef": {"kind": kind, "id": source_id},
        "senderAgentId": source_agent_id,
        "sourceAgentId": source_agent_id,
        "inboxKind": kind,
        "messageSummary": summary,
        "inboxCreatedBy": created_by_value,
    }
    if normalized_metadata:
        kernel_metadata["agentToolMetadataJson"] = json.dumps(normalized_metadata, ensure_ascii=False, sort_keys=True)
    sender = (
        {"type": "agent", "id": source_agent_id, "agentId": source_agent_id}
        if source_agent_id
        else {"type": "system", "id": created_by_value}
    )
    kernel_result = submit_agent_message_event(
        source="team_workflow",
        sender=sender,
        recipient_agent_ids=[target_agent_id],
        content=content,
        correlation_id=thread_id,
        wake_target=wake_target,
        metadata=kernel_metadata,
        source_id=source_id,
    )
    kernel_delivery = s._team_workflow_kernel_delivery(kernel_result, target_agent_id)
    if str(kernel_delivery.get("status") or "").strip() != "delivered":
        raise s.agent_directory_service.AgentDirectoryError(str(kernel_delivery.get("reason") or "Kernel delivery failed."))
    message = s._team_workflow_inbox_message_from_kernel_delivery(
        target_agent_id,
        kernel_delivery,
        fallback={
            "sourceAgentId": source_agent_id,
            "targetAgentId": target_agent_id,
            "threadId": thread_id,
            "kind": kind,
            "summary": summary,
            "metadata": kernel_metadata,
        },
    )
    delivery = (
        kernel_delivery.get("wake")
        if isinstance(kernel_delivery.get("wake"), dict)
        else {
            "wakeRequested": bool(wake_target),
            "wakeStatus": "not_requested" if not wake_target else "skipped",
            "messageId": str(message.get("messageId") or message.get("eventId") or "").strip(),
            "targetAgentId": target_agent_id,
            "targetSessionId": str(message.get("targetSessionId") or "").strip(),
            "turnId": "",
            "reason": "",
        }
    )
    return message, delivery, kernel_result


def _team_workflow_inbox_message_from_kernel_delivery(
    target_agent_id: str,
    delivery: dict[str, Any],
    *,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    s = _service()
    message_id = str(
        delivery.get("inboxMessageId")
        or (delivery.get("wake", {}) if isinstance(delivery.get("wake"), dict) else {}).get("messageId")
        or ""
    ).strip()
    if message_id:
        for message in s.agent_directory_service.list_agent_inbox_messages_for_agent(
            target_agent_id,
            limit=100,
            status="",
        ):
            if str(message.get("messageId") or message.get("eventId") or "").strip() == message_id:
                return message
    message = dict(fallback)
    if message_id:
        message["messageId"] = message_id
        message.setdefault("eventId", message_id)
    message["targetAgentId"] = str(target_agent_id or "").strip()
    message["targetSessionId"] = str(
        delivery.get("targetSessionId")
        or (delivery.get("wake", {}) if isinstance(delivery.get("wake"), dict) else {}).get("targetSessionId")
        or ""
    ).strip()
    return message


def _team_workflow_kernel_delivery(kernel_result: dict[str, Any], target_agent_id: str) -> dict[str, Any]:
    s = _service()
    outcome = kernel_result.get("outcome") if isinstance(kernel_result.get("outcome"), dict) else {}
    deliveries = outcome.get("deliveries") if isinstance(outcome.get("deliveries"), list) else []
    normalized_target_agent_id = str(target_agent_id or "").strip()
    for delivery in deliveries:
        if not isinstance(delivery, dict):
            continue
        if str(delivery.get("targetAgentId") or "").strip() == normalized_target_agent_id:
            return dict(delivery)
    return dict(deliveries[0]) if deliveries and isinstance(deliveries[0], dict) else {}


def _team_workflow_root(team_id: str) -> Path:
    from core.web.services.team_workflow.research_projects import resolve_team_workflow_root

    return resolve_team_workflow_root(team_id)


def _validate_algorithm_hypothesis_candidate(candidate: dict[str, Any]) -> list[dict[str, str]]:
    s = _service()
    issues: list[dict[str, str]] = []
    if not s._normalize_ref_list(candidate.get("sourceRefs"), max_items=32):
        issues.append({"severity": "error", "code": "missing_source_refs", "message": "algorithm_hypothesis must keep sourceRefs."})
    if not s._normalize_ref_list(candidate.get("evidenceRefs"), max_items=32):
        issues.append({"severity": "error", "code": "missing_evidence_refs", "message": "algorithm_hypothesis requires evidenceRefs before review."})
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    if output:
        issues.extend(s._validate_algorithm_hypothesis_output(output))
    return issues


def _validate_mechanism_mapping_candidate(candidate: dict[str, Any]) -> list[dict[str, str]]:
    s = _service()
    issues: list[dict[str, str]] = []
    if not s._normalize_ref_list(candidate.get("sourceRefs"), max_items=32):
        issues.append({"severity": "error", "code": "missing_source_refs", "message": "mechanism_mapping must keep sourceRefs."})
    if not s._normalize_ref_list(candidate.get("evidenceRefs"), max_items=32):
        issues.append({"severity": "error", "code": "missing_evidence_refs", "message": "mechanism_mapping requires evidenceRefs before hypothesis generation."})
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    if output:
        issues.extend(s._validate_mechanism_mapping_output(output))
    return issues


def _validate_neuro_mechanism_candidate(candidate: dict[str, Any]) -> list[dict[str, str]]:
    s = _service()
    issues: list[dict[str, str]] = []
    if not s._normalize_ref_list(candidate.get("sourceRefs"), max_items=32):
        issues.append({"severity": "error", "code": "missing_source_refs", "message": "neuro_mechanism must keep sourceRefs."})
    if not s._normalize_ref_list(candidate.get("evidenceRefs"), max_items=32):
        issues.append({"severity": "error", "code": "missing_evidence_refs", "message": "neuro_mechanism requires evidenceRefs before mapping."})
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    if output:
        issues.extend(s._validate_neuro_mechanism_output(output))
    return issues


def export_deliverables(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """N-13：交付材料导出（节点 12）。只读 official/approved/明确标注的证据，生成
    deliverable_manifest + blockers；不反写知识库。证据不足时输出 blocker 清单而非伪造完整材料。
    """
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    requested_by = s._trim_text(payload.get("requestedByAgent"), max_length=160) or "Challenge Cup Delivery Agent"
    now = s.utc_now_iso()

    candidate_store = s._load_candidate_store(normalized_team_id)
    candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
    candidate_breakdown: dict[str, int] = {}
    for candidate in candidates:
        candidate_type = str(candidate.get("candidateType") or "")
        candidate_breakdown[candidate_type] = candidate_breakdown.get(candidate_type, 0) + 1

    reviewed_hypotheses = [
        candidate
        for candidate in candidates
        if candidate.get("candidateType") == "algorithm_hypothesis"
        and isinstance(candidate.get("metadata"), dict)
        and any(
            str(record.get("decision")) == "approve"
            for record in (candidate["metadata"].get("reviewRecords") or [])
            if isinstance(record, dict)
        )
    ]

    plan_store = s._load_experiment_plan_store(normalized_team_id)
    artifact_refs: list[dict[str, Any]] = []
    for plan in list(plan_store.get("plans") or []):
        if not isinstance(plan, dict):
            continue
        for run in plan.get("smokeRunResults") or []:
            if isinstance(run, dict) and run.get("artifactHash"):
                artifact_refs.append(
                    {
                        "planId": plan.get("planId"),
                        "smokeRunId": run.get("smokeRunId"),
                        "artifactHash": run.get("artifactHash"),
                        "status": run.get("status"),
                    }
                )

    ingestion_status = s.get_knowledge_ingestion_status(normalized_team_id)
    formal_item_count = int((ingestion_status.get("summary") or {}).get("formalKnowledgeItemCount") or 0)

    evidence_refs: list[dict[str, str]] = []
    for candidate in reviewed_hypotheses:
        evidence_refs.extend(s._normalize_ref_list(candidate.get("evidenceRefs"), max_items=24))

    blockers: list[dict[str, str]] = []
    if not reviewed_hypotheses:
        blockers.append({"code": "no_reviewed_hypothesis", "message": "至少需要 1 个已审稿通过的 algorithm_hypothesis。"})
    if not artifact_refs:
        blockers.append({"code": "experiment_loop_incomplete", "message": "缺 runner_result/artifactHash；实验闭环未完成。"})
    if formal_item_count <= 0:
        blockers.append({"code": "no_official_knowledge", "message": "尚无正式 KnowledgeItem（official_synced）。"})

    sections = [
        {"key": "problem", "label": "问题定义", "ready": bool(reviewed_hypotheses)},
        {"key": "architecture", "label": "方法/架构", "ready": bool(reviewed_hypotheses)},
        {"key": "experiment", "label": "实验与证据", "ready": bool(artifact_refs)},
        {"key": "reproducibility", "label": "复现包", "ready": bool(artifact_refs)},
        {"key": "official_knowledge", "label": "正式知识", "ready": formal_item_count > 0},
    ]
    manifest = {
        "deliverableId": s._new_record_id("deliverable"),
        "teamId": normalized_team_id,
        "generatedAt": now,
        "requestedByAgent": requested_by,
        "sections": sections,
        "evidenceRefs": evidence_refs[:48],
        "artifactRefs": artifact_refs[:48],
        "officialBoundary": {
            "formalKnowledgeItemCount": formal_item_count,
            "reusesOfficialOnly": True,
            "writesBackToKnowledge": False,
        },
        "candidateBreakdown": candidate_breakdown,
        "blockers": blockers,
        "status": "ready" if not blockers else "blocked",
    }
    s._record_workflow_event(
        "deliverables.exported",
        normalized_team_id,
        fields={"deliverableId": manifest["deliverableId"], "status": manifest["status"], "blockerCount": len(blockers)},
    )
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "deliverableManifest": manifest,
        "status": manifest["status"],
        "blockers": blockers,
    }


def propose_iteration(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """N-12：持续迭代与版本化（节点 11）。根据 RunnerResult/审稿/steward 决策提出迭代提案。

    硬约束：不覆盖原候选，只新建版本/归档；无 changeReason 的状态变化拒绝写入；检测并拒绝
    circular supersedes。版本链边记录在父候选 metadata.versionEdges（supersedes / rejected_because /
    merged_with），提案记录在 metadata.iterationProposals。
    """
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    parent_id = s._normalize_required_id(payload.get("parentCandidateId") or payload.get("candidateId"), "parentCandidateId is required.")
    action = s._trim_text(payload.get("action"), max_length=40).strip().lower()
    if action not in s.ITERATION_ACTIONS:
        raise s.TeamWorkflowOrchestrationError("action must be iterate/reject/merge/hold.")
    change_reason = s._trim_text(payload.get("changeReason"), max_length=2000)
    if action != "hold" and not change_reason:
        raise s.TeamWorkflowOrchestrationError(f"{action} iteration requires a changeReason.")
    proposed_by = s._trim_text(payload.get("proposedByAgent"), max_length=160) or "Iteration Versioning Agent"
    merge_with = s._trim_text(payload.get("mergeWithCandidateId"), max_length=128)
    now = s.utc_now_iso()
    with s._WORKFLOW_LOCK:
        candidate_store = s._load_candidate_store(normalized_team_id)
        parent = s._find_candidate(candidate_store, parent_id)
        if parent is None:
            raise s.TeamWorkflowOrchestrationError("Candidate not found.")
        metadata = parent.get("metadata") if isinstance(parent.get("metadata"), dict) else {}
        version_edges = metadata.get("versionEdges") if isinstance(metadata.get("versionEdges"), list) else []
        proposal_id = s._new_record_id("iteration")
        new_edges: list[dict[str, Any]] = []
        new_draft: dict[str, Any] | None = None
        rejection_archive: dict[str, Any] | None = None
        if action == "iterate":
            draft_id = s._new_record_id("candidate")
            new_draft = {
                "candidateId": draft_id,
                "parentCandidateId": parent_id,
                "candidateType": str(parent.get("candidateType") or ""),
                "status": "iteration_draft",
                "changeReason": change_reason,
            }
            new_edges.append({"edgeType": "supersedes", "from": draft_id, "to": parent_id})
        elif action == "reject":
            rejection_archive = {
                "parentCandidateId": parent_id,
                "reason": change_reason,
                "evidenceRefs": s._normalize_ref_list(payload.get("evidenceRefs"), max_items=24),
                "archivedAt": now,
            }
            new_edges.append({"edgeType": "rejected_because", "from": parent_id, "to": proposal_id})
        elif action == "merge":
            if not merge_with:
                raise s.TeamWorkflowOrchestrationError("merge iteration requires mergeWithCandidateId.")
            new_edges.append({"edgeType": "merged_with", "from": parent_id, "to": merge_with})
        for edge in new_edges:
            if edge["edgeType"] != "supersedes":
                continue
            for existing in version_edges:
                if (
                    existing.get("edgeType") == "supersedes"
                    and existing.get("from") == edge["to"]
                    and existing.get("to") == edge["from"]
                ):
                    raise s.TeamWorkflowOrchestrationError("Circular supersedes detected; cannot create version cycle.")
        proposal = {
            "proposalId": proposal_id,
            "parentCandidateId": parent_id,
            "action": action,
            "changeReason": change_reason,
            "versionEdges": new_edges,
            "newCandidateDraft": new_draft,
            "rejectionArchive": rejection_archive,
            "mergeWithCandidateId": merge_with,
            "proposedByAgent": proposed_by,
            "createdAt": now,
        }
        proposals = metadata.get("iterationProposals") if isinstance(metadata.get("iterationProposals"), list) else []
        metadata["iterationProposals"] = [*proposals[-23:], proposal]
        metadata["versionEdges"] = [*version_edges, *new_edges]
        parent["metadata"] = metadata
        parent["updatedAt"] = now
        candidate_store["updatedAt"] = now
        s._write_json(s._candidate_store_path(normalized_team_id), candidate_store)
        workflow = s._load_or_create_workflow(normalized_team_id)
        version_edges_after = list(metadata["versionEdges"])
    s._record_workflow_event(
        "candidate.iteration_proposed",
        normalized_team_id,
        fields={"parentCandidateId": parent_id, "proposalId": proposal_id, "action": action},
    )
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "parentCandidateId": parent_id,
        "action": action,
        "proposal": proposal,
        "versionEdges": version_edges_after,
        "workflowId": workflow["workflowId"],
    }


def validate_candidate_record(candidate: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    candidate_type = s._trim_text(candidate.get("candidateType"), max_length=80)
    issues: list[dict[str, str]] = []
    if not candidate_type:
        issues.append({"severity": "error", "code": "missing_candidate_type", "message": "candidateType is required."})
    elif candidate_type not in s.CANDIDATE_TYPES:
        issues.append({"severity": "error", "code": "invalid_candidate_type", "message": "candidateType is not supported."})
    if not s._has_value(candidate.get("candidateId")):
        issues.append({"severity": "error", "code": "missing_candidate_id", "message": "candidateId is required."})
    if not s._has_value(candidate.get("teamId")):
        issues.append({"severity": "error", "code": "missing_team_id", "message": "teamId is required."})
    if candidate_type == "source_manifest":
        issues.extend(s._validate_source_manifest(candidate))
    elif candidate_type == "paper_note":
        issues.extend(s._validate_paper_note_candidate(candidate))
    elif candidate_type == "neuro_mechanism":
        issues.extend(s._validate_neuro_mechanism_candidate(candidate))
    elif candidate_type == "mechanism_mapping":
        issues.extend(s._validate_mechanism_mapping_candidate(candidate))
    elif candidate_type == "algorithm_hypothesis":
        issues.extend(s._validate_algorithm_hypothesis_candidate(candidate))
    elif candidate_type == "review_record":
        issues.extend(s._validate_review_record_candidate(candidate))
    elif candidate_type == "candidate_graph":
        issues.extend(s._validate_candidate_graph_candidate(candidate))
    elif candidate_type in {"paper_note", "neuro_mechanism", "mechanism_mapping", "algorithm_hypothesis", "review_record"}:
        if not s._normalize_ref_list(candidate.get("sourceRefs"), max_items=32):
            issues.append({"severity": "error", "code": "missing_source_refs", "message": f"{candidate_type} must keep sourceRefs."})
        if not s._normalize_ref_list(candidate.get("evidenceRefs"), max_items=32):
            issues.append({"severity": "warning", "code": "missing_evidence_refs", "message": f"{candidate_type} should include evidenceRefs before review."})
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "candidateType": candidate_type,
        "valid": not any(item["severity"] == "error" for item in issues),
        "issues": issues,
    }
