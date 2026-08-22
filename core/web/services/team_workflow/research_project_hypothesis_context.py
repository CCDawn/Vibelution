"""Build the bounded evidence context for formal hypothesis-design tasks."""

from __future__ import annotations

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
    if package is None:
        return {
            "status": "blocked",
            "code": "knowledge_package_not_materialized",
            "workflowRunId": workflow_run_id,
            "sourceCollectionRunId": source_run_id,
            "allowedEvidenceRefs": [],
        }

    item_ids = {
        _text(item.get("knowledgeItemId"))
        for item in list(package.get("knowledgeItems") or [])
        if isinstance(item, dict) and _text(item.get("knowledgeItemId"))
    }
    reviewer_id = _text((package.get("approval") or {}).get("reviewedByAgentId"))
    knowledge_base_id = _text(package.get("knowledgeBaseId"))
    items: list[dict[str, Any]] = []
    if knowledge_base_id and reviewer_id and item_ids:
        try:
            response = team_knowledge_service.list_knowledge_items(
                knowledge_base_id,
                agent_id=reviewer_id,
            )
        except team_knowledge_service.TeamKnowledgeError:
            response = {"items": []}
        for item in list(response.get("items") or []):
            if not isinstance(item, dict):
                continue
            item_id = _text(item.get("knowledgeItemId"))
            if item_id not in item_ids:
                continue
            items.append(
                {
                    "knowledgeItemId": item_id,
                    "title": _text(item.get("title"), limit=240),
                    "summary": _text(item.get("summary"), limit=800),
                }
            )

    candidate_id = _text(package.get("candidateId"))
    candidate_response = list_candidate_store(team_id, limit=500)
    accepted_candidate = next(
        (
            candidate
            for candidate in list(candidate_response.get("candidates") or [])
            if isinstance(candidate, dict)
            and _text(candidate.get("candidateId")) == candidate_id
        ),
        None,
    )
    evidence_claims: list[dict[str, str]] = []
    if accepted_candidate is not None:
        metadata = (
            accepted_candidate.get("metadata")
            if isinstance(accepted_candidate.get("metadata"), dict)
            else {}
        )
        output = (
            metadata.get("output")
            if isinstance(metadata.get("output"), dict)
            else {}
        )
        for claim in list(output.get("claims") or [])[:24]:
            if not isinstance(claim, dict):
                continue
            source_ref = _text(claim.get("sourceRef"), limit=200)
            statement = _text(claim.get("claim"), limit=1200)
            if source_ref and statement:
                evidence_claims.append(
                    {"claim": statement, "sourceRef": source_ref}
                )

    allowed_refs = sorted(
        {
            *(
                _text(value, limit=200)
                for value in list(package.get("sourceArtifactIds") or [])
            ),
            *(item["sourceRef"] for item in evidence_claims),
        }
        - {""}
    )
    ready = bool(evidence_claims and allowed_refs)
    candidate_id = _text(task.get("candidateId"))
    candidate_context = (
        dict(task.get("candidateContext") or {})
        if isinstance(task.get("candidateContext"), dict)
        else {}
    )
    writeback_contract = {
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
                    "predictions",
                    "falsificationCriteria",
                    "evidenceRefs",
                    "counterEvidenceRefs",
                    "scores",
                ],
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
    return {
        "status": "ready" if ready else "blocked",
        "code": "ready" if ready else "knowledge_package_has_no_evidence_claims",
        "workflowRunId": workflow_run_id,
        "sourceCollectionRunId": source_run_id,
        "knowledgePackage": {
            "candidateId": candidate_id,
            "knowledgeBaseId": knowledge_base_id,
            "knowledgeItems": items,
            "sourceArtifactIds": list(package.get("sourceArtifactIds") or []),
            "approval": dict(package.get("approval") or {}),
        },
        "evidenceClaims": evidence_claims[:24],
        "allowedEvidenceRefs": allowed_refs[:64],
        "candidateContext": candidate_context,
        "writebackContract": writeback_contract,
    }
