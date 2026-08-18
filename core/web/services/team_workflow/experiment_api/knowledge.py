"""Experiment result knowledge ingestion operations (Clarity B6 split from experiment.py).

Late-bound facade keeps route imports and monkeypatches on
``team_workflow_orchestration_service`` stable during mechanical splits.
"""

from __future__ import annotations

from typing import Any


def _service():
    from core.web.services import team_workflow_orchestration_service

    return team_workflow_orchestration_service


def request_experiment_result_knowledge_ingestion(team_id: str, plan_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_plan_id = s._normalize_required_id(plan_id, "Experiment plan id is required.")
    team = s.team_service.get_team(normalized_team_id)
    request_payload = payload if isinstance(payload, dict) else {}
    requested_by_agent = s._trim_text(request_payload.get("requestedByAgent"), max_length=160) or s.DEFAULT_OWNER_AGENT_ID
    steward_agent_id = s._trim_text(request_payload.get("stewardAgentId"), max_length=160) or s.agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    knowledge_base_id = s._trim_text(request_payload.get("knowledgeBaseId"), max_length=160) or f"{normalized_team_id}-challenge-cup-experiments"
    target_domain = s._trim_text(request_payload.get("targetDomain"), max_length=240) or "挑战杯实验结果"
    wake_steward_agent = bool(request_payload.get("wakeStewardAgent", True))
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        stage_store = s._load_stage_round_store(normalized_team_id)
        rounds = s._stage_rounds(stage_store)
        candidate_store = s._load_candidate_store(normalized_team_id)
        plan_store = s._load_experiment_plan_store(normalized_team_id)
        plan = s._find_experiment_plan(plan_store, normalized_plan_id)
        if plan is None:
            raise s.TeamWorkflowOrchestrationError("Experiment plan not found.")
        experiment_result_pack = s._experiment_result_ingestion_pack_record(
            plan,
            request_payload,
            knowledge_base_id=knowledge_base_id,
            target_domain=target_domain,
            requested_by_agent=requested_by_agent,
        )
        activation = s._notify_knowledge_steward_for_experiment_result(
            normalized_team_id,
            steward_agent_id=steward_agent_id,
            requester_agent_id=requested_by_agent,
            experiment_result_pack=experiment_result_pack,
            knowledge_base_id=knowledge_base_id,
            target_domain=target_domain,
            wake_target=wake_steward_agent,
        )
        activation_status = str(activation.get("status") or "")
        if activation_status in {"message_written", "agent_wake_started"}:
            plan_status = "knowledge_steward_notified"
        elif activation_status.startswith("agent_wake_"):
            plan_status = "knowledge_steward_wake_pending"
        else:
            plan_status = "knowledge_steward_notification_failed"
        plan["knowledgeIngestion"] = {
            "status": plan_status,
            "experimentResultPack": experiment_result_pack,
            "knowledgeStewardActivation": activation,
            "knowledgeBaseId": knowledge_base_id,
            "targetDomain": target_domain,
            "updatedAt": experiment_result_pack["createdAt"],
            "officialBoundary": experiment_result_pack["officialBoundary"],
        }
        plan["status"] = plan_status
        plan["updatedAt"] = experiment_result_pack["createdAt"]
        s._refresh_experiment_plan_readiness(plan)
        plan_store["activePlanId"] = plan["planId"]
        plan_store["updatedAt"] = experiment_result_pack["createdAt"]
        s._write_json(s._experiment_plan_store_path(normalized_team_id), plan_store)
        stage_round = s._find_stage_round(rounds, str(plan.get("stageRoundId") or ""))
        if stage_round is not None:
            stage_round["experimentPlanRef"] = {
                "planId": plan["planId"],
                "status": plan["status"],
                "storagePath": s._relative_path(s._experiment_plan_store_path(normalized_team_id)),
                "experimentResultPackRef": {
                    "packId": experiment_result_pack["packId"],
                    "fullRunResultId": experiment_result_pack["fullRunResultId"],
                    "knowledgeBaseId": knowledge_base_id,
                    "messageId": str(activation.get("messageId") or ""),
                },
                "updatedAt": experiment_result_pack["createdAt"],
            }
            active_full_run = plan.get("activeFullRunResult") if isinstance(plan.get("activeFullRunResult"), dict) else None
            if active_full_run:
                stage_round["experimentPlanRef"]["fullRunResultRef"] = {
                    "fullRunResultId": active_full_run.get("fullRunResultId", ""),
                    "status": active_full_run.get("status", ""),
                    "resultPath": active_full_run.get("resultPath", ""),
                    "logRef": active_full_run.get("logRef", ""),
                }
            planning_contract = stage_round.get("planningContract") if isinstance(stage_round.get("planningContract"), dict) else {}
            planning_contract["currentPlanId"] = plan["planId"]
            planning_contract["experimentResultPackId"] = experiment_result_pack["packId"]
            planning_contract["knowledgeStewardInboxMessageId"] = str(activation.get("messageId") or "")
            planning_contract["readyForKnowledgeIngestion"] = bool((plan.get("readiness") or {}).get("readyForKnowledgeIngestion"))
            planning_contract["autoExecution"] = False
            planning_contract["requiresUserDecision"] = True
            stage_round["planningContract"] = planning_contract
            stage_round["status"] = "planning"
            stage_round["updatedAt"] = experiment_result_pack["createdAt"]
            stage_store["rounds"] = rounds
            stage_store["updatedAt"] = experiment_result_pack["createdAt"]
            s._write_json(s._stage_round_store_path(normalized_team_id), stage_store)
        workflow["updatedAt"] = experiment_result_pack["createdAt"]
        workflow["activeWorkflowItems"] = s._upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=str(plan.get("stageRoundId") or plan["planId"]),
            current_node=s.RESEARCH_STAGE_DEFAULTS["experiment"]["currentNode"],
            status=plan_status,
            transfer_id="",
        )
        s._write_json(s._workflow_path(normalized_team_id), workflow)
        status_payload = s._experiment_planning_status(normalized_team_id, rounds, candidate_store, plan_store)
        stage_round_status = s.get_research_stage_round_status(normalized_team_id)
    s._record_workflow_event(
        "experiment_plan.knowledge_ingestion_requested",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "stageRoundId": str(plan.get("stageRoundId") or ""),
            "planId": plan["planId"],
            "experimentResultPackId": experiment_result_pack["packId"],
            "fullRunResultId": experiment_result_pack["fullRunResultId"],
            "knowledgeBaseId": knowledge_base_id,
            "knowledgeStewardActivationStatus": activation_status,
            "knowledgeStewardInboxMessageId": str(activation.get("messageId") or ""),
            "requestedByAgent": requested_by_agent,
        },
    )
    notification_failed = activation_status not in {"message_written", "agent_wake_started"} and not activation_status.startswith("agent_wake_")
    s._record_workflow_event(
        "experiment_plan.steward_notification_failed" if notification_failed else "experiment_plan.steward_notification_completed",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "stageRoundId": str(plan.get("stageRoundId") or ""),
            "planId": plan["planId"],
            "experimentResultPackId": experiment_result_pack["packId"],
            "fullRunResultId": experiment_result_pack["fullRunResultId"],
            "knowledgeBaseId": knowledge_base_id,
            "targetAgentId": str(activation.get("targetAgentId") or ""),
            "status": activation_status,
            "messageId": str(activation.get("messageId") or ""),
            "threadId": str(activation.get("threadId") or ""),
            "wakeStatus": str(activation.get("wakeStatus") or ""),
            "requestedByAgent": requested_by_agent,
            "errorType": type(activation.get("error")).__name__ if activation.get("error") and not isinstance(activation.get("error"), str) else "",
        },
        level="warning" if notification_failed else "info",
        outcome="failed" if notification_failed else "completed",
        child_log_path=f"artifacts/experiment-result-{s._safe_token(experiment_result_pack['packId'], default='pack', max_length=96)}-steward-notification.jsonl",
        child_log_payload=s._experiment_result_steward_notification_child_log_payload(
            team_id=normalized_team_id,
            experiment_result_pack=experiment_result_pack,
            activation=activation,
            knowledge_base_id=knowledge_base_id,
            target_domain=target_domain,
            requested_by_agent=requested_by_agent,
        ),
        lifecycle=notification_failed,
    )
    return {
        "experimentResultPack": experiment_result_pack,
        "knowledgeStewardActivation": activation,
        "plan": plan,
        "status": status_payload,
        "stageRoundStatus": stage_round_status,
        "workflow": s._workflow_to_api(normalized_team_id, workflow, candidate_store),
        "team": {"teamId": team.get("teamId", normalized_team_id), "name": team.get("name", "")},
        "boundaries": s._experiment_planning_boundaries(),
    }

def reconcile_experiment_knowledge_ingestion(
    team_id: str,
    *,
    inbox_source_id: str,
    source_ref: dict[str, Any] | None,
    direct_ingestion: dict[str, Any] | None,
    reconciled_by_agent_id: str = "",
) -> dict[str, Any]:
    """Idempotently project a completed direct ingestion into its experiment ledger."""

    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_inbox_source_id = s._normalize_required_id(inbox_source_id, "Inbox source id is required.")
    normalized_source_ref = source_ref if isinstance(source_ref, dict) else {}
    normalized_direct_ingestion = direct_ingestion if isinstance(direct_ingestion, dict) else {}
    plan_id = s._trim_text(normalized_source_ref.get("planId"), max_length=160)
    pack_id = s._trim_text(normalized_source_ref.get("experimentResultPackId"), max_length=160)
    item = normalized_direct_ingestion.get("item") if isinstance(normalized_direct_ingestion.get("item"), dict) else {}
    batch = normalized_direct_ingestion.get("batch") if isinstance(normalized_direct_ingestion.get("batch"), dict) else {}
    source_artifact = (
        normalized_direct_ingestion.get("sourceArtifact")
        if isinstance(normalized_direct_ingestion.get("sourceArtifact"), dict)
        else {}
    )
    knowledge_item_id = s._trim_text(item.get("knowledgeItemId"), max_length=160)
    batch_id = s._trim_text(batch.get("batchId"), max_length=160)
    source_artifact_id = s._trim_text(source_artifact.get("sourceArtifactId"), max_length=160)
    if not source_artifact_id:
        source_artifact_ids = item.get("sourceArtifactIds") if isinstance(item.get("sourceArtifactIds"), list) else []
        source_artifact_id = s._trim_text(source_artifact_ids[0] if source_artifact_ids else "", max_length=160)
    central_source_id = s._trim_text(source_artifact.get("centralSourceId"), max_length=160)
    if not central_source_id:
        central_source_ids = item.get("centralSourceIds") if isinstance(item.get("centralSourceIds"), list) else []
        central_source_id = s._trim_text(central_source_ids[0] if central_source_ids else "", max_length=160)
    direct_status = s._trim_text(normalized_direct_ingestion.get("status"), max_length=80).lower()
    required_evidence = {
        "planId": plan_id,
        "experimentResultPackId": pack_id,
        "knowledgeItemId": knowledge_item_id,
        "centralSourceId": central_source_id,
        "sourceArtifactId": source_artifact_id,
        "batchId": batch_id,
    }
    if direct_status != "ingested" or any(not value for value in required_evidence.values()):
        return {
            "schemaVersion": s.SCHEMA_VERSION,
            "status": "ignored",
            "updated": False,
            "reason": "incomplete_direct_ingestion_evidence",
            "teamId": normalized_team_id,
            "inboxSourceId": normalized_inbox_source_id,
        }
    direct_owner_type = s._trim_text(normalized_direct_ingestion.get("ownerType"), max_length=40).lower()
    direct_owner_id = s._trim_text(normalized_direct_ingestion.get("ownerId"), max_length=160)
    if (direct_owner_type and direct_owner_type != "team") or (
        direct_owner_id and direct_owner_id != normalized_team_id
    ):
        return {
            "schemaVersion": s.SCHEMA_VERSION,
            "status": "ignored",
            "updated": False,
            "reason": "direct_ingestion_owner_mismatch",
            "teamId": normalized_team_id,
            "inboxSourceId": normalized_inbox_source_id,
        }

    updated = False
    reason = "reconciled"
    now = (
        s._trim_text(normalized_direct_ingestion.get("updatedAt"), max_length=80)
        or s._trim_text(batch.get("appliedAt"), max_length=80)
        or s._trim_text(item.get("appliedAt"), max_length=80)
        or s.utc_now_iso()
    )
    result_evidence = {
        "status": "ingested",
        "inboxSourceId": normalized_inbox_source_id,
        "experimentResultPackId": pack_id,
        "planId": plan_id,
        "knowledgeItemId": knowledge_item_id,
        "centralSourceId": central_source_id,
        "sourceArtifactId": source_artifact_id,
        "batchId": batch_id,
        "knowledgeBaseId": s._trim_text(
            normalized_direct_ingestion.get("scopedKnowledgeBaseId")
            or normalized_direct_ingestion.get("knowledgeBaseId"),
            max_length=200,
        ),
        "reconciledByAgentId": s._trim_text(reconciled_by_agent_id, max_length=160),
        "ingestedAt": now,
    }
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        stage_store = s._load_stage_round_store(normalized_team_id)
        rounds = s._stage_rounds(stage_store)
        candidate_store = s._load_candidate_store(normalized_team_id)
        plan_store = s._load_experiment_plan_store(normalized_team_id)
        plan = s._find_experiment_plan(plan_store, plan_id)
        if plan is None:
            return {
                "schemaVersion": s.SCHEMA_VERSION,
                "status": "ignored",
                "updated": False,
                "reason": "experiment_plan_not_found",
                "teamId": normalized_team_id,
                "inboxSourceId": normalized_inbox_source_id,
                "planId": plan_id,
            }
        knowledge_ingestion = plan.get("knowledgeIngestion") if isinstance(plan.get("knowledgeIngestion"), dict) else {}
        stored_pack = (
            knowledge_ingestion.get("experimentResultPack")
            if isinstance(knowledge_ingestion.get("experimentResultPack"), dict)
            else {}
        )
        stored_activation = (
            knowledge_ingestion.get("knowledgeStewardActivation")
            if isinstance(knowledge_ingestion.get("knowledgeStewardActivation"), dict)
            else {}
        )
        if (
            s._trim_text(stored_pack.get("packId"), max_length=160) != pack_id
            or s._trim_text(stored_activation.get("inboxSourceId"), max_length=160) != normalized_inbox_source_id
        ):
            return {
                "schemaVersion": s.SCHEMA_VERSION,
                "status": "ignored",
                "updated": False,
                "reason": "experiment_ingestion_reference_mismatch",
                "teamId": normalized_team_id,
                "inboxSourceId": normalized_inbox_source_id,
                "planId": plan_id,
            }
        existing_result = knowledge_ingestion.get("result") if isinstance(knowledge_ingestion.get("result"), dict) else {}
        if s._trim_text(knowledge_ingestion.get("status"), max_length=80).lower() == "ingested":
            stable_keys = (
                "inboxSourceId",
                "experimentResultPackId",
                "planId",
                "knowledgeItemId",
                "centralSourceId",
                "sourceArtifactId",
                "batchId",
            )
            if all(str(existing_result.get(key) or "") == str(result_evidence.get(key) or "") for key in stable_keys):
                reason = "already_reconciled"
            else:
                return {
                    "schemaVersion": s.SCHEMA_VERSION,
                    "status": "ignored",
                    "updated": False,
                    "reason": "conflicting_ingestion_evidence",
                    "teamId": normalized_team_id,
                    "inboxSourceId": normalized_inbox_source_id,
                    "planId": plan_id,
                }
        else:
            allowed_statuses = {
                "knowledge_steward_notified",
                "knowledge_steward_wake_pending",
            }
            if s._trim_text(knowledge_ingestion.get("status"), max_length=80).lower() not in allowed_statuses:
                return {
                    "schemaVersion": s.SCHEMA_VERSION,
                    "status": "ignored",
                    "updated": False,
                    "reason": "experiment_ingestion_not_awaiting_steward",
                    "teamId": normalized_team_id,
                    "inboxSourceId": normalized_inbox_source_id,
                    "planId": plan_id,
                }
            knowledge_ingestion["status"] = "ingested"
            knowledge_ingestion["result"] = result_evidence
            knowledge_ingestion["updatedAt"] = now
            plan["knowledgeIngestion"] = knowledge_ingestion
            plan["status"] = "ingested"
            plan["updatedAt"] = now
            s._refresh_hypothesis_progress(plan)
            plan_store["activePlanId"] = plan["planId"]
            plan_store["updatedAt"] = now
            s._write_json(s._experiment_plan_store_path(normalized_team_id), plan_store)

            stage_round = s._find_stage_round(rounds, str(plan.get("stageRoundId") or ""))
            if stage_round is not None:
                experiment_plan_ref = (
                    stage_round.get("experimentPlanRef")
                    if isinstance(stage_round.get("experimentPlanRef"), dict)
                    else {}
                )
                experiment_plan_ref["planId"] = plan["planId"]
                experiment_plan_ref["status"] = "ingested"
                experiment_plan_ref["knowledgeIngestionResultRef"] = result_evidence
                experiment_plan_ref["updatedAt"] = now
                stage_round["experimentPlanRef"] = experiment_plan_ref
                planning_contract = (
                    stage_round.get("planningContract")
                    if isinstance(stage_round.get("planningContract"), dict)
                    else {}
                )
                planning_contract["currentPlanId"] = plan["planId"]
                planning_contract["knowledgeIngestionStatus"] = "ingested"
                planning_contract["knowledgeItemId"] = knowledge_item_id
                planning_contract["requiresUserDecision"] = False
                stage_round["planningContract"] = planning_contract
                stage_round["updatedAt"] = now
                stage_store["rounds"] = rounds
                stage_store["updatedAt"] = now
                s._write_json(s._stage_round_store_path(normalized_team_id), stage_store)
            workflow["updatedAt"] = now
            workflow["activeWorkflowItems"] = s._upsert_active_item(
                workflow.get("activeWorkflowItems"),
                candidate_id=str(plan.get("stageRoundId") or plan["planId"]),
                current_node=s.RESEARCH_STAGE_DEFAULTS["experiment"]["currentNode"],
                status="ingested",
                transfer_id="",
            )
            s._write_json(s._workflow_path(normalized_team_id), workflow)
            updated = True
        status_payload = s._experiment_planning_status(normalized_team_id, rounds, candidate_store, plan_store)

    if updated:
        s._record_workflow_event(
            "experiment_plan.knowledge_ingestion_reconciled",
            normalized_team_id,
            fields={
                "workflowId": workflow["workflowId"],
                "stageRoundId": str(plan.get("stageRoundId") or ""),
                **result_evidence,
            },
            outcome="completed",
        )
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "status": "ingested",
        "updated": updated,
        "reason": reason,
        "teamId": normalized_team_id,
        "planId": plan_id,
        "inboxSourceId": normalized_inbox_source_id,
        "result": result_evidence,
        "projectionStatus": status_payload["status"],
    }
