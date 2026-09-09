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
    if not workflow_run_id:
        return {
            "status": "blocked",
            "code": "missing_workflow_scope",
            "workflowRunId": workflow_run_id,
            "sourceCollectionRunId": source_run_id,
            "allowedEvidenceRefs": [],
        }

    from core.web.services import team_knowledge_service
    from core.web.services.team_workflow.source_collection.candidates import (
        list_candidate_store_authority_records,
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
        package_candidate_ids = [
            _text(value, limit=200)
            for value in list(current.get("candidateIds") or [])
            if _text(value, limit=200)
        ]
        source_candidate_id = _text(current.get("candidateId"))
        if source_candidate_id and source_candidate_id not in package_candidate_ids:
            package_candidate_ids.append(source_candidate_id)
        for package_candidate_id in package_candidate_ids:
            if package_candidate_id not in source_candidate_ids:
                source_candidate_ids.append(package_candidate_id)
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
        package_approvals = current.get("approvals")
        if isinstance(package_approvals, list):
            for package_approval in package_approvals:
                if isinstance(package_approval, Mapping):
                    approvals.append(dict(package_approval))
        elif approval:
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
        candidates = list_candidate_store_authority_records(
            team_id,
            run_id=_text(current.get("sourceCollectionRunId"), limit=200),
            metadata_task_type="steward_pack_draft",
        )
        candidates_by_id = {
            _text(candidate.get("candidateId"), limit=200): candidate
            for candidate in candidates
            if isinstance(candidate, Mapping)
            and _text(candidate.get("candidateId"), limit=200)
        }
        for package_candidate_id in package_candidate_ids:
            accepted_candidate = candidates_by_id.get(package_candidate_id)
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


def _grounded_problem_context(
    team_id: str, workflow_run_id: str, *, store: Any,
) -> dict[str, Any] | None:
    """Read the current problem attempt, never an older successful scope."""
    attempts = store.read(lambda repo: repo.list_attempts(workflow_run_id))
    problem_attempts = [item for item in attempts if item.node_id == "problem_understanding"]
    if not problem_attempts:
        return None
    current = max(problem_attempts, key=lambda item: item.attempt)
    if current.status != "succeeded":
        return None
    from .research_runtime.agent_task_artifact_builder import load_canonical_problem_understanding_payload
    from .research_runtime.human_gate_artifacts import canonical_sha256
    from .research_runtime.problem_understanding_artifact_writer import validate_problem_understanding

    payload = validate_problem_understanding(load_canonical_problem_understanding_payload(
        record={"teamId": team_id, "runId": workflow_run_id},
        node_run={"nodeRunId": current.node_run_id},
    ))
    if payload["human_gate"]["decision"] in {"rejected", "revision_requested"}:
        return None
    return {
        "workflowRunId": workflow_run_id,
        "nodeRunId": current.node_run_id,
        "contentHash": canonical_sha256(payload),
        "payload": payload,
    }


def build_stage_one_grounded_generation_context(
    team_id: str,
    workflow_run_id: str,
    *,
    question_id: str,
    store: Any | None = None,
) -> dict[str, Any] | None:
    """Build grounded R1 input for a canonical Challenge Cup workflow run."""
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
    try:
        from core.research.workflow.definition import (
            CHALLENGE_CUP_WORKFLOW_ID,
            SCHEMA_VERSION,
        )
        from core.research.workflow.definition_registry import resolve_definition_by_version_id
        from core.research.workflow.stage_one_definition import STAGE_ONE_SCHEMA_VERSION

        pinned = resolve_definition_by_version_id(
            _text(getattr(run, "workflow_version_id", ""))
        )
    except Exception:
        return {
            "status": "blocked",
            "code": "workflow_definition_unavailable",
            "allowedEvidenceRefs": [],
        }
    if (
        pinned.workflowId != CHALLENGE_CUP_WORKFLOW_ID
        # Stage-one runs pin the trimmed 3.1 main flow; both sanctioned
        # schema versions carry the nodes this context binds against.
        or pinned.schemaVersion not in (SCHEMA_VERSION, STAGE_ONE_SCHEMA_VERSION)
    ):
        return {
            "status": "blocked",
            "code": "workflow_definition_unavailable",
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
    context = build_hypothesis_input_context(
        normalized_team_id,
        {
            "workflowRunId": _text(workflow_run_id),
            "sourceCollectionRunId": _text(snapshot.get("sourceCollectionRunId")),
        },
        store=resolved,
    )
    if context.get("status") != "ready":
        return context
    try:
        problem = _grounded_problem_context(
            normalized_team_id, _text(workflow_run_id), store=resolved,
        )
    except (TypeError, ValueError):
        problem = None
    if problem is None:
        return {
            "status": "blocked",
            "code": "problem_understanding_not_ready",
            "workflowRunId": _text(workflow_run_id),
            "allowedEvidenceRefs": [],
        }
    return {**context, "problemUnderstandingContext": problem}
