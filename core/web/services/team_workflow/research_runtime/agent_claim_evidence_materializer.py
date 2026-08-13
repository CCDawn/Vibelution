"""Materialize verified Agent extraction output into canonical ClaimEvidence.

Source Collection remains the authority for candidate extraction writeback.  A
formal workflow may acknowledge an ``evidence_card_batch`` only after the
anchored claims have been copied into the canonical Evidence Store and can be
read back there.  This module is that explicit boundary; it deliberately skips
summaries that do not contain a verbatim, bounded source quote.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any


class EvidenceMaterializationError(RuntimeError):
    """Raised when a formal task cannot be materialized within its frozen scope."""


def _text(value: object) -> str:
    return str(value or "").strip()


def _sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _claim_locator(claim: dict[str, Any]) -> dict[str, Any] | None:
    explicit = claim.get("citationLocator")
    if isinstance(explicit, dict) and _text(explicit.get("kind")):
        locator = dict(explicit)
        if any(locator.get(key) not in (None, "") for key in ("page", "section", "anchor", "url")):
            return locator

    source_ref = _text(claim.get("sourceRef"))
    page = claim.get("page")
    if isinstance(page, int) and not isinstance(page, bool) and page > 0:
        return {"kind": "pdf_page", "page": page, **({"url": source_ref} if source_ref else {})}
    page_range = _text(claim.get("pageRange"))
    if page_range:
        return {"kind": "page_range", "anchor": page_range, **({"url": source_ref} if source_ref else {})}
    citation = _text(claim.get("citation"))
    if citation:
        return {"kind": "citation", "anchor": citation, **({"url": source_ref} if source_ref else {})}
    evidence_ref = _text(claim.get("evidenceRef"))
    if evidence_ref:
        return {"kind": "evidence_ref", "anchor": evidence_ref, **({"url": source_ref} if source_ref else {})}
    return None


def _materializable_claims(task: dict[str, Any]) -> Iterable[tuple[dict[str, Any], dict[str, Any]]]:
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    for collection in ("candidateExtractions", "recordExtractions"):
        for raw_extraction in result.get(collection) or []:
            if not isinstance(raw_extraction, dict):
                continue
            extraction = dict(raw_extraction)
            if _text(extraction.get("decision")).lower() == "exclude":
                continue
            evidence_status = _text(extraction.get("evidenceStatus")).lower()
            if evidence_status in {"missing_evidence_anchor", "missing", "unverified"}:
                continue
            # Source Collection's canonical extraction contract names verified
            # per-source findings ``keyFindings``.  Older formal tasks may use
            # ``claims``.  Both collections carry the same bounded
            # finding/quote/source/locator evidence shape; accepting either at
            # this boundary avoids requiring a parallel write solely for the
            # formal workflow while preserving the exact anchor checks below.
            for raw_claim in (
                list(extraction.get("claims") or [])
                + list(extraction.get("keyFindings") or [])
            ):
                if isinstance(raw_claim, dict):
                    yield extraction, dict(raw_claim)


def materialize_claim_evidence_from_task(
    *,
    project_root: str | Path,
    team_id: str,
    workflow_run_id: str,
    source_collection_run_id: str,
    task: dict[str, Any],
    model_ref: str,
) -> list[dict[str, Any]]:
    """Register only fully anchored claims; repeated calls remain idempotent."""
    from core.research.evidence import ClaimEvidenceStore

    normalized_team = _text(team_id)
    normalized_workflow_run = _text(workflow_run_id)
    normalized_source_run = _text(source_collection_run_id)
    if _text(task.get("teamId")) != normalized_team:
        raise EvidenceMaterializationError("stage task team does not match the formal workflow")
    if _text(task.get("runId")) != normalized_source_run:
        raise EvidenceMaterializationError("stage task source collection run does not match the formal workflow")
    if _text(task.get("stageId")).lower() != "extraction":
        raise EvidenceMaterializationError("only extraction stage tasks may materialize ClaimEvidence")

    extractor_agent_id = _text(task.get("agentId"))
    normalized_model_ref = _text(model_ref)
    store = ClaimEvidenceStore(project_root)
    materialized: list[dict[str, Any]] = []
    for extraction, claim in _materializable_claims(task):
        candidate_id = _text(extraction.get("candidateId") or extraction.get("recordId"))
        claim_text = _text(claim.get("claim") or claim.get("finding"))
        quote = _text(claim.get("quote"))
        source_ref = _text(claim.get("sourceRef"))
        locator = _claim_locator(claim)
        if not all((candidate_id, claim_text, quote, source_ref, locator)):
            continue
        if not extractor_agent_id or not normalized_model_ref:
            raise EvidenceMaterializationError(
                "anchored model evidence requires extractorAgentId and modelRef"
            )
        source_revision = "sha256:" + _sha256(
            {"sourceRef": source_ref, "locator": locator, "quote": quote}
        )
        claim_id = "workflow-claim-" + _sha256(
            {
                "workflowRunId": normalized_workflow_run,
                "candidateId": candidate_id,
                "claim": claim_text,
            }
        )[:24]
        materialized.append(
            store.register(
                normalized_team,
                {
                    "claimId": claim_id,
                    "candidateId": candidate_id,
                    "sourceId": source_ref,
                    "sourceRevision": source_revision,
                    "locator": locator,
                    "quote": quote,
                    "evidenceKind": "primary_result",
                    "reasoningRole": "fact",
                    "supportLevel": "unverified",
                    "extractionMethod": "model",
                    "extractorAgentId": extractor_agent_id,
                    "modelRef": normalized_model_ref,
                    "sourceCollectionRunId": normalized_source_run,
                    "workflowRunId": normalized_workflow_run,
                },
            )
        )
    return materialized


def _candidate_source_run_id(candidate: dict[str, Any]) -> str:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    for key in ("importedFromDataRecord", "sourceCollectionTrace", "dataProcessingCollectionTrace"):
        value = metadata.get(key) if isinstance(metadata.get(key), dict) else {}
        run_id = _text(value.get("runId"))
        if run_id:
            return run_id
    return _text(metadata.get("sourceRunId"))


def build_formal_evidence_retry_contract(
    *,
    workflow_run_id: str,
    source_collection_run_id: str,
    candidates: list[dict[str, Any]] | None = None,
    evidence_records: list[dict[str, Any]] | None = None,
    team_id: str = "",
) -> dict[str, Any]:
    """Return a retry scope containing every candidate without canonical evidence."""
    normalized_workflow_run = _text(workflow_run_id)
    normalized_source_run = _text(source_collection_run_id)
    if candidates is None or evidence_records is None:
        if not _text(team_id):
            raise EvidenceMaterializationError("teamId is required to build evidence retry scope")
        from core.research.evidence import ClaimEvidenceStore
        from core.web.services import team_service
        from core.web.services.team_workflow.source_collection.candidates import (
            list_candidate_store,
        )

        if candidates is None:
            response = list_candidate_store(_text(team_id), limit=500)
            candidates = [
                dict(item)
                for item in response.get("candidates") or []
                if isinstance(item, dict)
            ]
        if evidence_records is None:
            evidence_records = ClaimEvidenceStore(Path(team_service.PROJECT_ROOT)).list(
                _text(team_id)
            )

    scoped_candidate_ids = sorted(
        {
            _text(item.get("candidateId"))
            for item in candidates
            if isinstance(item, dict)
            and _candidate_source_run_id(item) == normalized_source_run
            and _text(item.get("candidateId"))
        }
    )
    covered_candidate_ids = {
        _text(item.get("candidateId"))
        for item in evidence_records
        if isinstance(item, dict)
        and _text(item.get("sourceCollectionRunId")) == normalized_source_run
        and _text(item.get("workflowRunId")) == normalized_workflow_run
        and _text(item.get("candidateId"))
    }
    gaps = [item for item in scoped_candidate_ids if item not in covered_candidate_ids]
    if not gaps:
        return {}
    return {
        "schemaVersion": 1,
        "parentRunId": normalized_workflow_run,
        "sourceNodeId": "source_extraction",
        "resolutionKind": "add_budget",
        "evidenceGapCandidateIds": gaps,
        "scopeCandidateIds": gaps,
        "requiredExistingLocatorFetch": True,
        "additionalBudget": {},
        "operatorReason": "canonical evidence_card_batch is incomplete",
    }


def materialize_completed_extraction_task(
    *,
    team_id: str,
    workflow_run_id: str,
    source_collection_run_id: str,
    task_id: str,
) -> list[dict[str, Any]]:
    """Load the exact canonical stage task and cross the Evidence Store boundary."""
    from core.web.services import agent_directory_service, team_service
    from core.web.services.team_workflow.source_collection.stage_task_query import (
        get_source_collection_stage_session_task,
    )

    response = get_source_collection_stage_session_task(
        team_id,
        task_id,
    )
    task = response.get("task") if isinstance(response, dict) else None
    resolved_run_id = response.get("runId") if isinstance(response, dict) else ""
    if not isinstance(task, dict):
        raise EvidenceMaterializationError("canonical extraction stage task is missing")
    if _text(resolved_run_id) != _text(source_collection_run_id):
        raise EvidenceMaterializationError("canonical stage task resolved to a different source collection run")
    agent_id = _text(task.get("agentId"))
    agent = agent_directory_service.get_agent(agent_id) if agent_id else None
    bindings = agent.get("llmBindings") if isinstance(agent, dict) else {}
    dialogue = bindings.get("dialogue") if isinstance(bindings, dict) else {}
    model_ref = _text(dialogue.get("modelId")) if isinstance(dialogue, dict) else ""
    return materialize_claim_evidence_from_task(
        project_root=Path(team_service.PROJECT_ROOT),
        team_id=team_id,
        workflow_run_id=workflow_run_id,
        source_collection_run_id=source_collection_run_id,
        task=task,
        model_ref=model_ref,
    )
