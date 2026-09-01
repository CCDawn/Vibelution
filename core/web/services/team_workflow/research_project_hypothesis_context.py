"""Build the bounded evidence context for formal hypothesis-design tasks."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any


def _text(value: Any, *, limit: int = 160) -> str:
    return str(value or "").strip()[:limit]


def _load_receipt_bound_knowledge_package(
    *,
    team_id: str,
    workflow_run_id: str,
    store: Any | None,
) -> dict[str, Any] | None:
    """Read the accepted package from the bound receipt only.

    Inventory without a receipt must not unlock hypothesis input. A later
    inventory item also must not replace the receipt-pinned content hash.
    """
    resolved = store
    if resolved is None:
        try:
            from core.web.services.team_workflow.research_runtime.formal_write_runtime import (
                FormalWriteRuntimeUnavailable,
                WorkflowMigrationRequired,
                get_write_store,
            )

            resolved = get_write_store()
        except (FormalWriteRuntimeUnavailable, WorkflowMigrationRequired):
            return None
    from core.web.services.team_workflow.research_runtime.human_acceptance_artifact import (
        load_accepted_knowledge_package_from_receipt,
    )

    return load_accepted_knowledge_package_from_receipt(
        resolved,
        team_id=team_id,
        run_id=workflow_run_id,
    )


def _load_sideflow_bound_knowledge_packages(
    *,
    team_id: str,
    workflow_run_id: str,
    store: Any | None,
) -> list[dict[str, Any]]:
    resolved = store
    if resolved is None:
        try:
            from core.web.services.team_workflow.research_runtime.formal_write_runtime import (
                FormalWriteRuntimeUnavailable,
                WorkflowMigrationRequired,
                get_write_store,
            )

            resolved = get_write_store()
        except (FormalWriteRuntimeUnavailable, WorkflowMigrationRequired):
            return []
    from core.web.services.team_workflow.research_runtime.human_acceptance_artifact import (
        load_accepted_knowledge_packages_from_invocations,
    )

    return load_accepted_knowledge_packages_from_invocations(
        resolved,
        team_id=team_id,
        parent_run_id=workflow_run_id,
    )


def bind_hypothesis_input_to_task(
    hypothesis_input: Mapping[str, Any],
    task: Mapping[str, Any],
) -> dict[str, Any]:
    """Project one immutable evidence binding into one candidate task scope."""

    result = deepcopy(dict(hypothesis_input))
    workflow_run_id = _text(result.get("workflowRunId"))
    candidate_id = _text(task.get("candidateId"))
    candidate_context = (
        dict(task.get("candidateContext") or {})
        if isinstance(task.get("candidateContext"), Mapping)
        else {}
    )
    writeback_contract: dict[str, Any] = {
        "tool": "challenge_cup_experiment_writeback_tool",
        "operation": "record_hypothesis_fragment"
        if candidate_id
        else "record_hypothesis_set",
        "artifactKind": "hypothesis_fragment"
        if candidate_id
        else "hypothesis_set",
        "runId": workflow_run_id,
    }
    if candidate_id:
        writeback_contract.update(
            {
                "selectionId": _text(task.get("selectionId")),
                "candidateId": candidate_id,
                "requiredFields": [
                    "statement",
                    "mechanism",
                    "novelty_basis",
                    "predictions",
                    "falsificationCriteria",
                    "evidenceRefs",
                    "counterEvidenceRefs",
                    "boundary_conditions",
                    "scores",
                ],
            }
        )
        result.update(
            {
                "selectionId": _text(task.get("selectionId")),
                "candidateId": candidate_id,
                "writebackOperation": "record_hypothesis_fragment",
            }
        )
    else:
        writeback_contract["requiredCandidateFields"] = [
            "candidateId",
            "claim",
            "scores",
            "counterEvidenceRefs",
            "derivedFromCandidateIds",
            "status",
            "reviewRef",
        ]
    result["candidateContext"] = candidate_context
    result["writebackContract"] = writeback_contract
    return result


def build_hypothesis_input_context(
    team_id: str,
    task: dict[str, Any],
    store: Any | None = None,
) -> dict[str, Any]:
    """Resolve one accepted package into evidence claims and writeback limits."""
    workflow_run_id = _text(task.get("workflowRunId"))
    source_run_id = _text(task.get("sourceCollectionRunId"))
    if not workflow_run_id or not source_run_id:
        return {
            "status": "blocked",
            "code": "missing_workflow_scope",
            "workflowRunId": workflow_run_id,
            "sourceCollectionRunId": source_run_id,
            "allowedEvidenceRefs": [],
        }

    from core.web.services import team_knowledge_service
    from core.web.services.team_workflow.source_collection.candidates import (
        list_candidate_store,
    )

    package = _load_receipt_bound_knowledge_package(
        team_id=team_id,
        workflow_run_id=workflow_run_id,
        store=store,
    )
    if package is not None:
        from core.web.services.team_workflow.research_runtime.human_gate_artifacts import (
            canonical_sha256,
        )

        package_records = [
            {
                "invocationId": "",
                "producerRunId": workflow_run_id,
                "knowledgePackageRef": "",
                "packageContentHash": canonical_sha256(package),
                "package": package,
                "authority": "parent_handoff_receipt",
            }
        ]
    else:
        package_records = _load_sideflow_bound_knowledge_packages(
            team_id=team_id,
            workflow_run_id=workflow_run_id,
            store=store,
        )
    if not package_records:
        return {
            "status": "blocked",
            "code": "knowledge_package_not_materialized",
            "workflowRunId": workflow_run_id,
            "sourceCollectionRunId": source_run_id,
            "allowedEvidenceRefs": [],
        }

    knowledge_items: dict[str, dict[str, Any]] = {}
    source_candidate_ids: list[str] = []
    source_artifact_ids: set[str] = set()
    approvals: list[dict[str, Any]] = []
    knowledge_base_ids: list[str] = []
    snapshot_packages: list[dict[str, str]] = []
    evidence_claims: list[dict[str, str]] = []
    seen_claims: set[tuple[str, str]] = set()
    for record in package_records:
        current = (
            dict(record.get("package") or {})
            if isinstance(record.get("package"), Mapping)
            else {}
        )
        if not current:
            continue
        invocation_id = _text(record.get("invocationId"), limit=200)
        producer_run_id = _text(record.get("producerRunId"), limit=200)
        package_hash = _text(record.get("packageContentHash"), limit=80).lower()
        package_ref = _text(record.get("knowledgePackageRef"), limit=400)
        snapshot_packages.append(
            {
                "invocationId": invocation_id,
                "producerRunId": producer_run_id,
                "knowledgePackageRef": package_ref,
                "packageContentHash": package_hash,
            }
        )
        source_candidate_id = _text(current.get("candidateId"))
        if source_candidate_id and source_candidate_id not in source_candidate_ids:
            source_candidate_ids.append(source_candidate_id)
        source_artifact_ids.update(
            _text(value, limit=200)
            for value in list(current.get("sourceArtifactIds") or [])
            if _text(value, limit=200)
        )
        approval = (
            dict(current.get("approval") or {})
            if isinstance(current.get("approval"), Mapping)
            else {}
        )
        if approval:
            approvals.append(approval)
        item_ids = {
            _text(item.get("knowledgeItemId"))
            for item in list(current.get("knowledgeItems") or [])
            if isinstance(item, Mapping) and _text(item.get("knowledgeItemId"))
        }
        reviewer_id = _text(approval.get("reviewedByAgentId"))
        knowledge_base_id = _text(current.get("knowledgeBaseId"))
        if knowledge_base_id and knowledge_base_id not in knowledge_base_ids:
            knowledge_base_ids.append(knowledge_base_id)
        if knowledge_base_id and reviewer_id and item_ids:
            try:
                response = team_knowledge_service.list_knowledge_items(
                    knowledge_base_id,
                    agent_id=reviewer_id,
                )
            except team_knowledge_service.TeamKnowledgeError:
                response = {"items": []}
            for item in list(response.get("items") or []):
                if not isinstance(item, Mapping):
                    continue
                item_id = _text(item.get("knowledgeItemId"))
                if item_id not in item_ids:
                    continue
                knowledge_items[item_id] = {
                    "knowledgeItemId": item_id,
                    "title": _text(item.get("title"), limit=240),
                    "summary": _text(item.get("summary"), limit=800),
                }
        candidate_response = list_candidate_store(
            team_id,
            limit=500,
            **(
                {"run_id": _text(current.get("sourceCollectionRunId"), limit=200)}
                if _text(current.get("sourceCollectionRunId"), limit=200)
                else {}
            ),
        )
        accepted_candidate = next(
            (
                candidate
                for candidate in list(candidate_response.get("candidates") or [])
                if isinstance(candidate, Mapping)
                and _text(candidate.get("candidateId")) == source_candidate_id
            ),
            None,
        )
        metadata = (
            accepted_candidate.get("metadata")
            if isinstance(accepted_candidate, Mapping)
            and isinstance(accepted_candidate.get("metadata"), Mapping)
            else {}
        )
        output = (
            metadata.get("output")
            if isinstance(metadata.get("output"), Mapping)
            else {}
        )
        for claim in list(output.get("claims") or []):
            if not isinstance(claim, Mapping):
                continue
            source_ref = _text(claim.get("sourceRef"), limit=200)
            statement = _text(claim.get("claim"), limit=1200)
            key = (statement, source_ref)
            if source_ref and statement and key not in seen_claims:
                seen_claims.add(key)
                evidence_claims.append(
                    {"claim": statement, "sourceRef": source_ref}
                )

    allowed_refs = sorted(
        {
            *source_artifact_ids,
            *(item["sourceRef"] for item in evidence_claims),
        }
        - {""}
    )
    snapshot_packages = sorted(
        snapshot_packages,
        key=lambda item: (
            item["packageContentHash"],
            item["invocationId"],
            item["producerRunId"],
        ),
    )
    from core.web.services.team_workflow.research_runtime.human_gate_artifacts import (
        canonical_sha256,
    )

    knowledge_snapshot = {
        "packageCount": len(snapshot_packages),
        "packages": snapshot_packages,
        "knowledgeItemIds": sorted(knowledge_items),
    }
    knowledge_snapshot["snapshotHash"] = canonical_sha256(knowledge_snapshot)
    ready = bool(evidence_claims and allowed_refs)
    result = {
        "status": "ready" if ready else "blocked",
        "code": "ready" if ready else "knowledge_package_has_no_evidence_claims",
        "workflowRunId": workflow_run_id,
        "sourceCollectionRunId": source_run_id,
        "knowledgePackage": {
            "knowledgeBaseId": sorted(knowledge_base_ids)[0]
            if knowledge_base_ids
            else "",
            "knowledgeBaseIds": sorted(knowledge_base_ids),
            "candidateId": source_candidate_ids[0] if source_candidate_ids else "",
            "candidateIds": source_candidate_ids,
            "knowledgeItems": [
                knowledge_items[item_id] for item_id in sorted(knowledge_items)
            ],
            "sourceArtifactIds": sorted(source_artifact_ids),
            "approval": approvals[0] if approvals else {},
            "approvals": approvals,
        },
        "evidenceClaims": evidence_claims[:24],
        "allowedEvidenceRefs": allowed_refs[:64],
        "knowledgeSnapshot": knowledge_snapshot,
        "consumedKnowledgeSnapshotHash": knowledge_snapshot["snapshotHash"],
    }
    return bind_hypothesis_input_to_task(result, task)


def build_stage_one_grounded_generation_context(
    team_id: str,
    workflow_run_id: str,
    *,
    question_id: str,
    store: Any | None = None,
) -> dict[str, Any] | None:
    """Build R1 input only for a run pinned to the current stage-one policy."""
    resolved = store
    if resolved is None:
        from core.web.services.team_workflow.research_runtime.formal_write_runtime import (
            get_write_store,
        )

        resolved = get_write_store()
    run = resolved.get_run(_text(workflow_run_id))
    if run is None:
        return {
            "status": "blocked",
            "code": "workflow_run_not_found",
            "allowedEvidenceRefs": [],
        }
    try:
        snapshot = json.loads(str(run.input_snapshot_json or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {
            "status": "blocked",
            "code": "workflow_snapshot_invalid",
            "allowedEvidenceRefs": [],
        }
    raw_policy = snapshot.get("stageOneCompletionPolicy")
    if raw_policy is None:
        return None
    if not isinstance(raw_policy, Mapping):
        return {
            "status": "blocked",
            "code": "stage_one_policy_invalid",
            "allowedEvidenceRefs": [],
        }
    from core.research.competition.stage_one_completion_policy import (
        StageOneCompletionPolicyError,
        require_current_stage_one_policy_snapshot,
    )

    try:
        require_current_stage_one_policy_snapshot(raw_policy)
    except StageOneCompletionPolicyError:
        return {
            "status": "blocked",
            "code": "stage_one_policy_invalid",
            "allowedEvidenceRefs": [],
        }
    normalized_team_id = _text(team_id)
    normalized_question_id = _text(question_id).upper()
    if (
        _text(run.team_id) != normalized_team_id
        or _text(run.question_id).upper() != normalized_question_id
    ):
        return {
            "status": "blocked",
            "code": "workflow_scope_mismatch",
            "allowedEvidenceRefs": [],
        }
    return build_hypothesis_input_context(
        normalized_team_id,
        {
            "workflowRunId": _text(workflow_run_id),
            "sourceCollectionRunId": _text(snapshot.get("sourceCollectionRunId")),
        },
        store=resolved,
    )
