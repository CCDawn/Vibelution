"""Team workflow knowledge / graph / steward / coordination public APIs.

Claim scope: candidate paper-note pipeline, source quality, candidate graph,
knowledge ingestion/completion, steward packs, local research model helpers,
official graph/evidence, coordination status, and transfer requests.

Private helpers remain on ``team_workflow_orchestration_service`` and are
reached via late-bound ``_service()`` until a later pure-helper extraction.

Facade re-exports keep route imports and monkeypatches stable.
"""

from __future__ import annotations

import json
import re
import threading
from copy import deepcopy
from typing import Any

from .source_collection_common import project_source_version_families

# Dedup memory for the high-frequency status_viewed workflow event (the UI
# polls the status endpoint every ~2s; only status changes should be logged).
_WORKFLOW_EVENT_STATUS_VIEW_MEMORY: dict[str, str] = {}


def _service():
    from core.web.services import team_workflow_orchestration_service

    return team_workflow_orchestration_service


def extract_candidate_source_pages(team_id: str, candidate_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_candidate_id = s._normalize_required_id(candidate_id, "Candidate id is required.")
    s.team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    created_by_agent = s._trim_text(payload.get("createdByAgent"), max_length=160) or "Source Extraction Agent"
    max_pages = s._normalize_int(payload.get("maxPages"), default=s.SOURCE_EXTRACTION_DEFAULT_MAX_PAGES, minimum=1, maximum=s.SOURCE_EXTRACTION_HARD_MAX_PAGES)
    max_chars_per_page = s._normalize_int(
        payload.get("maxCharsPerPage"),
        default=s.SOURCE_EXTRACTION_DEFAULT_MAX_CHARS_PER_PAGE,
        minimum=200,
        maximum=s.SOURCE_EXTRACTION_HARD_MAX_CHARS_PER_PAGE,
    )
    page_scope_override = s._trim_text(payload.get("pageScope"), max_length=160)
    allowed_override = s._normalize_optional_bool(payload.get("allowedForAnalysis")) if "allowedForAnalysis" in payload else None
    now = s.utc_now_iso()
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        candidate_store = s._load_candidate_store(normalized_team_id)
        candidate = s._find_candidate(candidate_store, normalized_candidate_id)
        if candidate is None:
            raise s.TeamWorkflowOrchestrationError("Candidate not found.")
        if str(candidate.get("candidateType") or "") != "source_manifest":
            raise s.TeamWorkflowOrchestrationError("Source extraction only supports source_manifest candidates.")
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        source_path = s._source_manifest_path(candidate)
        if not source_path:
            raise s.TeamWorkflowOrchestrationError("Source manifest does not include a local sourcePath.")
        if page_scope_override:
            candidate["pageScope"] = page_scope_override
            metadata["pageScope"] = page_scope_override
        if allowed_override is not None:
            candidate["allowedForAnalysis"] = allowed_override
            metadata["allowedForAnalysis"] = allowed_override
        try:
            resolved_source_path = s._resolve_source_path(source_path)
            sha256 = s._sha256_file(resolved_source_path)
            page_anchors = s._extract_pdf_page_anchors(
                resolved_source_path,
                page_scope=page_scope_override or s._trim_text(candidate.get("pageScope") or metadata.get("pageScope"), max_length=160),
                max_pages=max_pages,
                max_chars_per_page=max_chars_per_page,
            )
            if not page_anchors:
                raise s.SourceExtractionError("empty_extraction", "PDF extraction produced no page text.")
            page_scope = s._page_scope_from_anchors(page_anchors)
            extraction = {
                "status": "extracted",
                "sourceKind": "pdf",
                "sourcePath": str(resolved_source_path),
                "sha256": sha256,
                "pageScope": page_scope,
                "pageAnchors": page_anchors,
                "excerpt": s._excerpt_from_page_anchors(page_anchors, max_chars=s.SOURCE_EXTRACTION_EXCERPT_MAX_CHARS),
                "extractor": "pypdf",
                "extractedByAgent": created_by_agent,
                "extractedAt": now,
                "limits": {
                    "maxPages": max_pages,
                    "maxCharsPerPage": max_chars_per_page,
                },
            }
            candidate["sha256"] = sha256
            candidate["pageScope"] = page_scope
            candidate["sourceKind"] = s._trim_text(candidate.get("sourceKind"), max_length=80) or "pdf"
            metadata["sha256"] = sha256
            metadata["pageScope"] = page_scope
            metadata["sourceExtraction"] = extraction
        except s.SourceExtractionError as exc:
            extraction = {
                "status": "failed",
                "sourcePath": source_path,
                "errorCode": exc.code,
                "message": exc.message,
                "extractedByAgent": created_by_agent,
                "extractedAt": now,
                "limits": {
                    "maxPages": max_pages,
                    "maxCharsPerPage": max_chars_per_page,
                },
            }
            metadata["sourceExtraction"] = extraction
        candidate["metadata"] = metadata
        validation = s.validate_candidate_record(candidate)
        candidate["validation"] = validation
        if validation["valid"]:
            candidate["currentState"] = "source_registered"
            candidate["qualityStatus"] = "source_manifest_ready"
        else:
            candidate["currentState"] = "source_needs_confirmation"
            candidate["qualityStatus"] = "source_manifest_invalid"
        candidate["updatedAt"] = now
        candidate_store["updatedAt"] = now
        s._write_json(s._candidate_store_path(normalized_team_id), candidate_store)
        workflow["updatedAt"] = now
        workflow["activeWorkflowItems"] = s._upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=normalized_candidate_id,
            current_node=str(candidate.get("currentWorkflowNode") or "knowledge_collection"),
            status=str(candidate.get("currentState") or ""),
            transfer_id=str(candidate.get("pendingTransferId") or ""),
        )
        s._write_json(s._workflow_path(normalized_team_id), workflow)
    s._record_workflow_event(
        "candidate.source_extracted",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "candidateId": normalized_candidate_id,
            "status": str(extraction.get("status") or ""),
            "pageAnchorCount": len(extraction.get("pageAnchors") or []) if isinstance(extraction.get("pageAnchors"), list) else 0,
            "errorCode": str(extraction.get("errorCode") or ""),
        },
    )
    return {
        "candidate": candidate,
        "sourceExtraction": extraction,
        "validation": validation,
        "workflow": s._workflow_to_api(normalized_team_id, workflow, candidate_store),
    }


def draft_paper_note_from_source_candidate(
    team_id: str,
    candidate_id: str,
    payload: dict[str, Any] | None = None,
    *,
    llm_client_factory: Any = None,
) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_candidate_id = s._normalize_required_id(candidate_id, "Candidate id is required.")
    s.team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    created_by_agent = s._trim_text(payload.get("createdByAgent"), max_length=160) or "Paper Note Extraction Agent"
    model_id = s._trim_text(payload.get("modelId"), max_length=160)
    title_override = s._trim_text(payload.get("title"), max_length=240)
    summary_override = s._trim_text(payload.get("summary"), max_length=4000)
    excerpt_override = s._trim_text(payload.get("excerpt"), max_length=24_000)
    chunk_id = s._trim_text(payload.get("chunkId"), max_length=128)
    with s._WORKFLOW_LOCK:
        candidate_store = s._load_candidate_store(normalized_team_id)
        source_candidate = s._find_candidate(candidate_store, normalized_candidate_id)
        if source_candidate is None:
            raise s.TeamWorkflowOrchestrationError("Candidate not found.")
        if str(source_candidate.get("candidateType") or "") != "source_manifest":
            raise s.TeamWorkflowOrchestrationError("Paper note autodraft requires a source_manifest candidate.")
        extraction = s._ready_source_extraction(source_candidate)
        chunk = s._paper_note_chunk_by_id(source_candidate, chunk_id) if chunk_id else None
        if chunk_id and chunk is None:
            raise s.TeamWorkflowOrchestrationError("Paper note chunkId was not found on this source candidate.")
        chunk_anchors = s._page_anchors_for_paper_note_chunk(source_candidate, extraction, chunk) if chunk else []
        excerpt = excerpt_override or (
            s._excerpt_from_page_anchors(chunk_anchors, max_chars=24_000)
            if chunk_anchors
            else s._trim_text(extraction.get("excerpt"), max_length=24_000)
        )
        if not excerpt:
            raise s.TeamWorkflowOrchestrationError("Source extraction does not include excerpt text for paper_note drafting.")
        source_refs = [s._source_manifest_source_ref(source_candidate)]
        evidence_refs = s._source_extraction_evidence_refs(
            source_candidate,
            extraction,
            anchor_ids=set(s._normalize_id_values(chunk.get("anchorIds"))) if chunk else None,
        )
        if not evidence_refs:
            raise s.TeamWorkflowOrchestrationError("Source extraction does not include page anchors for paper_note drafting.")
        evidence_ledger = s._ready_content_extraction_evidence_ledger(source_candidate)
        if evidence_ledger:
            source_refs = s._merge_local_research_refs(
                source_refs,
                s._normalize_ref_list(evidence_ledger.get("sourceRefs"), max_items=24),
                max_items=32,
            )
            evidence_refs = s._merge_local_research_refs(
                evidence_refs,
                s._normalize_ref_list(evidence_ledger.get("evidenceRefs"), max_items=24),
                max_items=32,
            )
        candidate_refs = [
            {
                "type": "source_manifest",
                "id": normalized_candidate_id,
                "label": s._source_manifest_label(source_candidate),
            }
        ]
        if chunk:
            candidate_refs.append(
                {
                    "type": "paper_note_chunk",
                    "id": chunk_id,
                    "label": str(chunk.get("pageScope") or chunk_id),
                }
            )
        page_scope = str((chunk or {}).get("pageScope") or extraction.get("pageScope") or source_candidate.get("pageScope") or "")
        paper_note_title = title_override or f"paper_note draft - {s._source_manifest_label(source_candidate)}{f' - {page_scope}' if page_scope else ''}"
        paper_note_summary = summary_override or f"Autodrafted from sourceExtraction pageScope {page_scope}".strip()

    invoke_response = s.invoke_local_research_model(
        normalized_team_id,
        {
            "taskType": "paper_note_draft",
            "modelId": model_id,
            "sourceRefs": source_refs,
            "evidenceRefs": evidence_refs,
            "candidateRefs": candidate_refs,
            "excerpt": excerpt,
            "evidenceLedger": evidence_ledger,
            "title": paper_note_title,
            "summary": paper_note_summary,
            "createdByAgent": created_by_agent,
        },
        llm_client_factory=llm_client_factory,
    )
    paper_note_candidate = invoke_response.get("candidate") if isinstance(invoke_response.get("candidate"), dict) else {}
    validation = invoke_response.get("validation") if isinstance(invoke_response.get("validation"), dict) else {"valid": False, "issues": []}
    task = invoke_response.get("task") if isinstance(invoke_response.get("task"), dict) else {}
    now = s.utc_now_iso()
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        candidate_store = s._load_candidate_store(normalized_team_id)
        source_candidate = s._find_candidate(candidate_store, normalized_candidate_id)
        if source_candidate is not None:
            metadata = source_candidate.get("metadata") if isinstance(source_candidate.get("metadata"), dict) else {}
            drafts = metadata.get("paperNoteDrafts") if isinstance(metadata.get("paperNoteDrafts"), list) else []
            draft_record = {
                "candidateId": str(paper_note_candidate.get("candidateId") or ""),
                "taskId": str(task.get("taskId") or ""),
                "status": "drafted" if validation.get("valid") is True else "needs_revision",
                "createdByAgent": created_by_agent,
                "createdAt": now,
                "sourceExtractionSha256": str(extraction.get("sha256") or source_candidate.get("sha256") or ""),
                "pageScope": page_scope,
                "chunkId": chunk_id,
            }
            metadata["paperNoteDrafts"] = [*drafts[-23:], draft_record]
            if chunk_id:
                metadata["paperNoteChunkPlan"] = s._update_paper_note_chunk_plan_progress(
                    metadata.get("paperNoteChunkPlan"),
                    chunk_id=chunk_id,
                    paper_note_candidate_id=str(paper_note_candidate.get("candidateId") or ""),
                    task_id=str(task.get("taskId") or ""),
                    valid=validation.get("valid") is True,
                    updated_at=now,
                )
            source_candidate["metadata"] = metadata
            source_candidate["updatedAt"] = now
            candidate_store["updatedAt"] = now
            s._write_json(s._candidate_store_path(normalized_team_id), candidate_store)
        else:
            source_candidate = {}
    s._record_workflow_event(
        "candidate.paper_note_autodrafted",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "sourceCandidateId": normalized_candidate_id,
            "paperNoteCandidateId": str(paper_note_candidate.get("candidateId") or ""),
            "valid": validation.get("valid") is True,
            "issueCount": len(validation.get("issues") or []) if isinstance(validation.get("issues"), list) else 0,
        },
    )
    invoke_response["sourceCandidate"] = source_candidate
    invoke_response["workflow"] = s._workflow_to_api(normalized_team_id, workflow, candidate_store)
    return invoke_response


def extract_neuro_mechanism_from_paper_note(
    team_id: str,
    payload: dict[str, Any] | None = None,
    *,
    llm_client_factory: Any = None,
) -> dict[str, Any]:
    """N-02：从 paper_note 候选抽取 neuro_mechanism 候选（节点 03 专用编排）。

    复用 s.invoke_local_research_model 的 neuro_mechanism_extract 任务（含 schema 校验）；
    在 paper_note 上以 metadata.mechanismDrafts 记录 supports 边/谱系；并施加置信度门禁：
    confidence < 0.45 → review_needs_human，不自动进入节点 04。
    """
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    paper_note_id = s._normalize_required_id(payload.get("paperNoteId") or payload.get("candidateId"), "paperNoteId is required.")
    created_by_agent = s._trim_text(payload.get("createdByAgent"), max_length=160) or "NeuroMechanism Extraction Agent"
    model_id = s._trim_text(payload.get("modelId"), max_length=160)
    with s._WORKFLOW_LOCK:
        candidate_store = s._load_candidate_store(normalized_team_id)
        paper_note = s._find_candidate(candidate_store, paper_note_id)
        if paper_note is None:
            raise s.TeamWorkflowOrchestrationError("Candidate not found.")
        if str(paper_note.get("candidateType") or "") != "paper_note":
            raise s.TeamWorkflowOrchestrationError("Neuro mechanism extraction requires a paper_note candidate.")
        note_payload = paper_note.get("payload") if isinstance(paper_note.get("payload"), dict) else {}
        source_refs = s._normalize_ref_list(paper_note.get("sourceRefs") or note_payload.get("sourceRefs"), max_items=24)
        evidence_refs = s._normalize_ref_list(paper_note.get("evidenceRefs") or note_payload.get("evidenceRefs"), max_items=24)
        if not evidence_refs:
            raise s.TeamWorkflowOrchestrationError("paper_note candidate has no evidenceRefs for mechanism extraction.")
        candidate_refs = [{"type": "paper_note", "id": paper_note_id, "label": str(paper_note.get("title") or paper_note_id)}]
        excerpt = s._trim_text(payload.get("excerpt"), max_length=24_000) or s._trim_text(paper_note.get("summary"), max_length=24_000)

    invoke_response = s.invoke_local_research_model(
        normalized_team_id,
        {
            "taskType": "neuro_mechanism_extract",
            "modelId": model_id,
            "sourceRefs": source_refs,
            "evidenceRefs": evidence_refs,
            "candidateRefs": candidate_refs,
            "paperNoteIds": [paper_note_id],
            "excerpt": excerpt,
            "createdByAgent": created_by_agent,
        },
        llm_client_factory=llm_client_factory,
    )
    mechanism_candidate = invoke_response.get("candidate") if isinstance(invoke_response.get("candidate"), dict) else {}
    validation = invoke_response.get("validation") if isinstance(invoke_response.get("validation"), dict) else {"valid": False, "issues": []}
    task = invoke_response.get("task") if isinstance(invoke_response.get("task"), dict) else {}
    raw_confidence = mechanism_candidate.get("confidence")
    try:
        confidence = float(raw_confidence) if raw_confidence is not None and str(raw_confidence) != "" else None
    except (TypeError, ValueError):
        confidence = None
    gate = "ready" if (validation.get("valid") is True and (confidence is None or confidence >= 0.45)) else "review_needs_human"
    now = s.utc_now_iso()
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        candidate_store = s._load_candidate_store(normalized_team_id)
        paper_note = s._find_candidate(candidate_store, paper_note_id)
        if paper_note is not None:
            metadata = paper_note.get("metadata") if isinstance(paper_note.get("metadata"), dict) else {}
            drafts = metadata.get("mechanismDrafts") if isinstance(metadata.get("mechanismDrafts"), list) else []
            metadata["mechanismDrafts"] = [
                *drafts[-23:],
                {
                    "candidateId": str(mechanism_candidate.get("candidateId") or ""),
                    "taskId": str(task.get("taskId") or ""),
                    "edgeType": "supports",
                    "gate": gate,
                    "confidence": confidence,
                    "valid": validation.get("valid") is True,
                    "createdByAgent": created_by_agent,
                    "createdAt": now,
                },
            ]
            paper_note["metadata"] = metadata
            paper_note["updatedAt"] = now
            candidate_store["updatedAt"] = now
            s._write_json(s._candidate_store_path(normalized_team_id), candidate_store)
        else:
            paper_note = {}
    s._record_workflow_event(
        "candidate.neuro_mechanism_extracted",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "paperNoteCandidateId": paper_note_id,
            "mechanismCandidateId": str(mechanism_candidate.get("candidateId") or ""),
            "gate": gate,
            "valid": validation.get("valid") is True,
        },
    )
    invoke_response["paperNoteCandidate"] = paper_note
    invoke_response["mechanismGate"] = gate
    invoke_response["workflow"] = s._workflow_to_api(normalized_team_id, workflow, candidate_store)
    return invoke_response


def map_mechanism_to_abstraction(
    team_id: str,
    payload: dict[str, Any] | None = None,
    *,
    llm_client_factory: Any = None,
) -> dict[str, Any]:
    """N-03：把 neuro_mechanism 候选映射为 mechanism_mapping 候选（节点 04 专用编排）。

    门禁：overAnalogyRisk=high → review_needs_human，不自动进入节点 05；在 neuro_mechanism 上
    以 metadata.mappingDrafts 记录 maps_to 谱系。
    """
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    mechanism_id = s._normalize_required_id(payload.get("mechanismId") or payload.get("candidateId"), "mechanismId is required.")
    created_by_agent = s._trim_text(payload.get("createdByAgent"), max_length=160) or "Mechanism Mapping Agent"
    model_id = s._trim_text(payload.get("modelId"), max_length=160)
    with s._WORKFLOW_LOCK:
        candidate_store = s._load_candidate_store(normalized_team_id)
        mechanism = s._find_candidate(candidate_store, mechanism_id)
        if mechanism is None:
            raise s.TeamWorkflowOrchestrationError("Candidate not found.")
        if str(mechanism.get("candidateType") or "") != "neuro_mechanism":
            raise s.TeamWorkflowOrchestrationError("Mechanism mapping requires a neuro_mechanism candidate.")
        mech_payload = mechanism.get("payload") if isinstance(mechanism.get("payload"), dict) else {}
        source_refs = s._normalize_ref_list(mechanism.get("sourceRefs") or mech_payload.get("sourceRefs"), max_items=24)
        evidence_refs = s._normalize_ref_list(mechanism.get("evidenceRefs") or mech_payload.get("evidenceRefs"), max_items=24)
        if not evidence_refs:
            raise s.TeamWorkflowOrchestrationError("neuro_mechanism candidate has no evidenceRefs for mapping.")
        candidate_refs = [{"type": "neuro_mechanism", "id": mechanism_id, "label": str(mechanism.get("title") or mechanism_id)}]
        excerpt = s._trim_text(payload.get("excerpt"), max_length=24_000) or s._trim_text(mechanism.get("summary"), max_length=24_000)

    invoke_response = s.invoke_local_research_model(
        normalized_team_id,
        {
            "taskType": "mechanism_mapping",
            "modelId": model_id,
            "sourceRefs": source_refs,
            "evidenceRefs": evidence_refs,
            "candidateRefs": candidate_refs,
            "neuroMechanismIds": [mechanism_id],
            "excerpt": excerpt,
            "createdByAgent": created_by_agent,
        },
        llm_client_factory=llm_client_factory,
    )
    mapping_candidate = invoke_response.get("candidate") if isinstance(invoke_response.get("candidate"), dict) else {}
    validation = invoke_response.get("validation") if isinstance(invoke_response.get("validation"), dict) else {"valid": False, "issues": []}
    task = invoke_response.get("task") if isinstance(invoke_response.get("task"), dict) else {}
    over_analogy = str(mapping_candidate.get("overAnalogyRisk") or "").strip().lower()
    gate = "ready" if (validation.get("valid") is True and over_analogy != "high") else "review_needs_human"
    now = s.utc_now_iso()
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        candidate_store = s._load_candidate_store(normalized_team_id)
        mechanism = s._find_candidate(candidate_store, mechanism_id)
        if mechanism is not None:
            metadata = mechanism.get("metadata") if isinstance(mechanism.get("metadata"), dict) else {}
            drafts = metadata.get("mappingDrafts") if isinstance(metadata.get("mappingDrafts"), list) else []
            metadata["mappingDrafts"] = [
                *drafts[-23:],
                {
                    "candidateId": str(mapping_candidate.get("candidateId") or ""),
                    "taskId": str(task.get("taskId") or ""),
                    "edgeType": "maps_to",
                    "gate": gate,
                    "overAnalogyRisk": over_analogy,
                    "valid": validation.get("valid") is True,
                    "createdByAgent": created_by_agent,
                    "createdAt": now,
                },
            ]
            mechanism["metadata"] = metadata
            mechanism["updatedAt"] = now
            candidate_store["updatedAt"] = now
            s._write_json(s._candidate_store_path(normalized_team_id), candidate_store)
        else:
            mechanism = {}
    s._record_workflow_event(
        "candidate.mechanism_mapping_created",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "neuroMechanismCandidateId": mechanism_id,
            "mappingCandidateId": str(mapping_candidate.get("candidateId") or ""),
            "gate": gate,
            "overAnalogyRisk": over_analogy,
            "valid": validation.get("valid") is True,
        },
    )
    invoke_response["mechanismCandidate"] = mechanism
    invoke_response["mappingGate"] = gate
    invoke_response["workflow"] = s._workflow_to_api(normalized_team_id, workflow, candidate_store)
    return invoke_response


def generate_algorithm_hypothesis_from_mechanism_mapping(
    team_id: str,
    payload: dict[str, Any] | None = None,
    *,
    llm_client_factory: Any = None,
) -> dict[str, Any]:
    """N-04：从 mechanism_mapping 生成 algorithm_hypothesis 候选（节点 05 专用编排）。

    门禁：上游 overAnalogyRisk=high 不得生成（须先过 Review Gate）；输出须含 experimentPlan/baseline
    （由 schema 校验保证），否则 revise_required；在 mechanism_mapping 上以 metadata.hypothesisDrafts
    记录 inspires 谱系。
    """
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    mapping_id = s._normalize_required_id(payload.get("mappingId") or payload.get("candidateId"), "mappingId is required.")
    created_by_agent = s._trim_text(payload.get("createdByAgent"), max_length=160) or "Algorithm Hypothesis Agent"
    model_id = s._trim_text(payload.get("modelId"), max_length=160)
    with s._WORKFLOW_LOCK:
        candidate_store = s._load_candidate_store(normalized_team_id)
        mapping = s._find_candidate(candidate_store, mapping_id)
        if mapping is None:
            raise s.TeamWorkflowOrchestrationError("Candidate not found.")
        if str(mapping.get("candidateType") or "") != "mechanism_mapping":
            raise s.TeamWorkflowOrchestrationError("Hypothesis generation requires a mechanism_mapping candidate.")
        map_payload = mapping.get("payload") if isinstance(mapping.get("payload"), dict) else {}
        map_metadata = mapping.get("metadata") if isinstance(mapping.get("metadata"), dict) else {}
        over_analogy = str(
            mapping.get("overAnalogyRisk") or map_payload.get("overAnalogyRisk") or map_metadata.get("overAnalogyRisk") or ""
        ).strip().lower()
        if over_analogy == "high":
            raise s.TeamWorkflowOrchestrationError("high overAnalogyRisk mapping must pass Review Gate before hypothesis generation.")
        source_refs = s._normalize_ref_list(mapping.get("sourceRefs") or map_payload.get("sourceRefs"), max_items=24)
        evidence_refs = s._normalize_ref_list(mapping.get("evidenceRefs") or map_payload.get("evidenceRefs"), max_items=24)
        if not evidence_refs:
            raise s.TeamWorkflowOrchestrationError("mechanism_mapping candidate has no evidenceRefs for hypothesis generation.")
        candidate_refs = [{"type": "mechanism_mapping", "id": mapping_id, "label": str(mapping.get("title") or mapping_id)}]
        excerpt = s._trim_text(payload.get("excerpt"), max_length=24_000) or s._trim_text(mapping.get("summary"), max_length=24_000)

    invoke_response = s.invoke_local_research_model(
        normalized_team_id,
        {
            "taskType": "algorithm_hypothesis_draft",
            "modelId": model_id,
            "sourceRefs": source_refs,
            "evidenceRefs": evidence_refs,
            "candidateRefs": candidate_refs,
            "mechanismMappingIds": [mapping_id],
            "excerpt": excerpt,
            "createdByAgent": created_by_agent,
        },
        llm_client_factory=llm_client_factory,
    )
    hypothesis_candidate = invoke_response.get("candidate") if isinstance(invoke_response.get("candidate"), dict) else {}
    validation = invoke_response.get("validation") if isinstance(invoke_response.get("validation"), dict) else {"valid": False, "issues": []}
    task = invoke_response.get("task") if isinstance(invoke_response.get("task"), dict) else {}
    gate = "review_ready" if validation.get("valid") is True else "revise_required"
    now = s.utc_now_iso()
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        candidate_store = s._load_candidate_store(normalized_team_id)
        mapping = s._find_candidate(candidate_store, mapping_id)
        if mapping is not None:
            metadata = mapping.get("metadata") if isinstance(mapping.get("metadata"), dict) else {}
            drafts = metadata.get("hypothesisDrafts") if isinstance(metadata.get("hypothesisDrafts"), list) else []
            metadata["hypothesisDrafts"] = [
                *drafts[-23:],
                {
                    "candidateId": str(hypothesis_candidate.get("candidateId") or ""),
                    "taskId": str(task.get("taskId") or ""),
                    "edgeType": "inspires",
                    "gate": gate,
                    "valid": validation.get("valid") is True,
                    "createdByAgent": created_by_agent,
                    "createdAt": now,
                },
            ]
            mapping["metadata"] = metadata
            mapping["updatedAt"] = now
            candidate_store["updatedAt"] = now
            s._write_json(s._candidate_store_path(normalized_team_id), candidate_store)
        else:
            mapping = {}
    s._record_workflow_event(
        "candidate.algorithm_hypothesis_generated",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "mechanismMappingCandidateId": mapping_id,
            "hypothesisCandidateId": str(hypothesis_candidate.get("candidateId") or ""),
            "gate": gate,
            "valid": validation.get("valid") is True,
        },
    )
    invoke_response["mappingCandidate"] = mapping
    invoke_response["hypothesisGate"] = gate
    invoke_response["workflow"] = s._workflow_to_api(normalized_team_id, workflow, candidate_store)
    return invoke_response


def decide_research_review(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """N-05：科研审稿决策门禁（节点 06）。对候选链路做 checklist，输出 review_record 决策。

    硬门禁：missing_evidence / high_over_analogy / no_metric 任一为真 → 不得 approve；
    reject 必须带 rejectionReason（requiredChanges 或 comments）。在被审候选上以
    metadata.reviewRecords 记录 reviewed_by 谱系。
    """
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    candidate_ids = s._normalize_text_list(payload.get("candidateIds"), max_items=24, max_length=128)
    if not candidate_ids:
        raise s.TeamWorkflowOrchestrationError("candidateIds is required for research review.")
    reviewed_by = s._trim_text(payload.get("reviewedByAgent"), max_length=160) or "Evidence Review Agent"
    requested_decision = s._trim_text(payload.get("decision"), max_length=40).strip().lower()
    if requested_decision and requested_decision not in s.RESEARCH_REVIEW_DECISIONS:
        raise s.TeamWorkflowOrchestrationError("decision must be approve/revise/reject/needs_human.")
    comments = s._trim_text(payload.get("comments"), max_length=4000)
    required_changes = s._normalize_text_list(payload.get("requiredChanges"), max_items=24, max_length=400)
    now = s.utc_now_iso()
    with s._WORKFLOW_LOCK:
        candidate_store = s._load_candidate_store(normalized_team_id)
        reviewed: list[dict[str, Any]] = []
        checklist_all: dict[str, dict[str, bool]] = {}
        risk_flags: set[str] = set()
        for candidate_id in candidate_ids:
            candidate = s._find_candidate(candidate_store, candidate_id)
            if candidate is None:
                raise s.TeamWorkflowOrchestrationError(f"Candidate not found: {candidate_id}")
            checklist, flags = s._research_review_checklist(candidate)
            checklist_all[candidate_id] = checklist
            risk_flags.update(flags)
            reviewed.append(candidate)
        risk_flag_list = sorted(risk_flags)
        recommended = "needs_human" if risk_flag_list else "approve"
        decision = requested_decision or recommended
        if decision == "approve" and risk_flag_list:
            raise s.TeamWorkflowOrchestrationError(f"Cannot approve with blocking risk flags: {risk_flag_list}.")
        if decision == "reject" and not (required_changes or comments):
            raise s.TeamWorkflowOrchestrationError("reject requires a rejectionReason via requiredChanges or comments.")
        review_id = s._new_record_id("candidate")
        review_record = {
            "schemaVersion": s.SCHEMA_VERSION,
            "candidateId": review_id,
            "candidateType": "review_record",
            "teamId": normalized_team_id,
            "title": f"review_record for {', '.join(candidate_ids[:3])}",
            "currentState": "review_ready" if decision == "approve" else decision,
            "qualityStatus": "reviewed",
            "reviewedCandidateIds": candidate_ids,
            "decision": decision,
            "checklist": checklist_all,
            "riskFlags": risk_flag_list,
            "requiredChanges": required_changes,
            "comments": comments,
            "reviewedByAgent": reviewed_by,
            "createdByAgent": reviewed_by,
            "createdAt": now,
            "updatedAt": now,
        }
        review_record["envelopeValidation"] = s.candidate_schema_registry.validate_envelope(review_record)
        candidate_store.setdefault("candidates", []).append(review_record)
        for candidate in reviewed:
            metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
            records = metadata.get("reviewRecords") if isinstance(metadata.get("reviewRecords"), list) else []
            metadata["reviewRecords"] = [
                *records[-23:],
                {"reviewRecordId": review_id, "decision": decision, "edgeType": "reviewed_by", "createdAt": now},
            ]
            candidate["metadata"] = metadata
            candidate["updatedAt"] = now
        candidate_store["updatedAt"] = now
        s._write_json(s._candidate_store_path(normalized_team_id), candidate_store)
        workflow = s._load_or_create_workflow(normalized_team_id)
        experiment_status = None
        if any(
            str(candidate.get("candidateType") or "") == "algorithm_hypothesis"
            for candidate in reviewed
        ):
            stage_store = s._load_stage_round_store(normalized_team_id)
            plan_store = s._load_experiment_plan_store(normalized_team_id)
            experiment_status = s._experiment_planning_status(
                normalized_team_id,
                s._stage_rounds(stage_store),
                candidate_store,
                plan_store,
            )
    s._record_workflow_event(
        "research.review_decided",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "reviewRecordId": review_id,
            "decision": decision,
            "candidateCount": len(candidate_ids),
            "riskFlagCount": len(risk_flag_list),
        },
    )
    response = {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "reviewRecord": review_record,
        "decision": decision,
        "riskFlags": risk_flag_list,
        "checklist": checklist_all,
        "workflow": s._workflow_to_api(normalized_team_id, workflow, candidate_store),
    }
    if experiment_status is not None:
        response["experimentStatus"] = experiment_status
    return response


def validate_prd(team_id: str, payload: dict[str, Any] | None = None, *, registered_paths: list[str] | None = None) -> dict[str, Any]:
    """N-14：PRD 校验门禁（节点 13）。校验代码侧契约一致性，避免 PRD 与实现脱节（R7）。

    检查项：①schemas/ 声明文件存在且可加载；②registry 与 service 的 s.CANDIDATE_TYPES /
    s.LOCAL_RESEARCH_TASKS 一致（防漂移）；③科研生成链端点已注册（需路由层传入 registered_paths）；
    ④smoke runner 具白名单 + 固定 seed + artifactHash。任一失败 → valid=False。
    """
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.get_team(normalized_team_id)
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    schema_ids = s.candidate_schema_registry.candidate_schema_ids()
    try:
        for name in schema_ids:
            s.candidate_schema_registry.load_schema(name)
        add("schemas_present", True, f"{len(schema_ids)} schema file(s)")
    except (OSError, ValueError) as exc:
        add("schemas_present", False, str(exc))

    add(
        "candidate_types_in_sync",
        set(s.candidate_schema_registry.CANDIDATE_TYPES) == set(s.CANDIDATE_TYPES),
        "registry vs service s.CANDIDATE_TYPES",
    )
    task_sync = set(s.candidate_schema_registry.RESEARCH_TASK_REQUIRED_OUTPUT) == set(s.LOCAL_RESEARCH_TASKS) and all(
        tuple(s.LOCAL_RESEARCH_TASKS[task]["requiredOutput"]) == fields
        for task, fields in s.candidate_schema_registry.RESEARCH_TASK_REQUIRED_OUTPUT.items()
    )
    add("research_task_outputs_in_sync", task_sync, "registry vs s.LOCAL_RESEARCH_TASKS requiredOutput")

    if registered_paths is not None:
        joined = "\n".join(str(path) for path in registered_paths)
        missing = [endpoint for endpoint in s._PRD_EXPECTED_ENDPOINTS if endpoint not in joined]
        add("research_endpoints_registered", not missing, f"missing={missing}" if missing else "all present")

    try:
        sample = s.smoke_runner.run_smoke_adapter("synthetic_classification_baseline_vs_variant", seed=42)
        runner_ok = (
            bool(s.smoke_runner.WHITELIST_ADAPTERS)
            and str(sample.get("artifactHash", "")).startswith("sha256:")
            and "seed" in sample
        )
        add("smoke_runner_markers", runner_ok, f"whitelist={len(s.smoke_runner.WHITELIST_ADAPTERS)}")
    except s.smoke_runner.SmokeRunnerError as exc:
        add("smoke_runner_markers", False, str(exc))

    failed = [item for item in checks if not item["ok"]]
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "valid": not failed,
        "checks": checks,
        "failedCount": len(failed),
    }


def sync_official_research_graph(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """N-07：正式知识图谱同步（节点 09）。

    边界（硬约束）：本函数**不创建 KnowledgeItem**（正式知识只能经 知识库管理员 门禁产生），
    只对**已审批的 official 知识**做图谱关系投影并写可逆 sync log。门禁：formalKnowledgeItemCount==0
    （candidate-only）→ 拒绝同步。对相同知识状态幂等（除非 force）。
    """
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    synced_by = s._trim_text(payload.get("syncedByAgent"), max_length=160) or "Ingestion Approval Gate"
    force = bool(payload.get("force"))
    status_view = s.get_knowledge_ingestion_status(normalized_team_id)
    summary = status_view.get("summary") if isinstance(status_view.get("summary"), dict) else {}
    formal_count = int(summary.get("formalKnowledgeItemCount") or 0)
    if formal_count <= 0:
        raise s.TeamWorkflowOrchestrationError(
            "No approved official KnowledgeItem to sync; candidate-only state cannot sync to official graph."
        )
    now = s.utc_now_iso()
    store_path = s._workflow_path(normalized_team_id).parent / "official_graph_sync.json"
    with s._WORKFLOW_LOCK:
        store = s._read_json(store_path)
        log = store.get("syncs") if isinstance(store.get("syncs"), list) else []
        if not force:
            existing = next(
                (
                    item
                    for item in log
                    if isinstance(item, dict)
                    and item.get("status") == "completed"
                    and int(item.get("knowledgeItemCount") or 0) == formal_count
                ),
                None,
            )
            if existing is not None:
                return {
                    "schemaVersion": s.SCHEMA_VERSION,
                    "teamId": normalized_team_id,
                    "sync": existing,
                    "status": "completed",
                    "idempotentReuse": True,
                }
        sync_id = s._new_record_id("graphsync")
        record = {
            "syncId": sync_id,
            "status": "completed",
            "graphStatus": "synced",
            "ragStatus": "synced",
            "knowledgeItemCount": formal_count,
            "edges": [{"edgeType": "approved_for_ingestion", "official": True, "knowledgeItemCount": formal_count}],
            "syncedByAgent": synced_by,
            "officialBoundary": {
                "writesOfficialGraph": True,
                "requiresStewardApproval": True,
                "reversible": True,
                "createsKnowledgeItem": False,
            },
            "syncedAt": now,
        }
        log.append(record)
        store["syncs"] = log[-24:]
        store["activeOfficialGraphSyncId"] = sync_id
        store["schemaVersion"] = s.SCHEMA_VERSION
        store["updatedAt"] = now
        s._write_json(store_path, store)
    s._record_workflow_event(
        "official_graph.synced",
        normalized_team_id,
        fields={"syncId": sync_id, "knowledgeItemCount": formal_count},
    )
    return {"schemaVersion": s.SCHEMA_VERSION, "teamId": normalized_team_id, "sync": record, "status": "completed"}


def rollback_official_research_graph(team_id: str, sync_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """N-08：回滚一次正式图谱同步。按 sync_id 将 status/graphStatus/ragStatus 置为 rolled_back，保留审计。"""
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_sync_id = s._normalize_required_id(sync_id, "Sync id is required.")
    s.team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    rolled_back_by = s._trim_text(payload.get("rolledBackByAgent"), max_length=160) or "Ingestion Approval Gate"
    now = s.utc_now_iso()
    store_path = s._workflow_path(normalized_team_id).parent / "official_graph_sync.json"
    with s._WORKFLOW_LOCK:
        store = s._read_json(store_path)
        log = store.get("syncs") if isinstance(store.get("syncs"), list) else []
        target = next(
            (item for item in log if isinstance(item, dict) and item.get("syncId") == normalized_sync_id), None
        )
        if target is None:
            raise s.TeamWorkflowOrchestrationError("Official graph sync record not found.")
        if target.get("status") == "rolled_back":
            raise s.TeamWorkflowOrchestrationError("Official graph sync is already rolled back.")
        target["status"] = "rolled_back"
        target["graphStatus"] = "rolled_back"
        target["ragStatus"] = "rolled_back"
        target["rolledBackByAgent"] = rolled_back_by
        target["rolledBackAt"] = now
        if store.get("activeOfficialGraphSyncId") == normalized_sync_id:
            store["activeOfficialGraphSyncId"] = ""
        store["syncs"] = log
        store["updatedAt"] = now
        s._write_json(store_path, store)
    s._record_workflow_event(
        "official_graph.rolled_back",
        normalized_team_id,
        fields={"syncId": normalized_sync_id},
    )
    return {"schemaVersion": s.SCHEMA_VERSION, "teamId": normalized_team_id, "sync": target, "status": "rolled_back"}


def plan_paper_note_chunks_from_source_candidate(team_id: str, candidate_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_candidate_id = s._normalize_required_id(candidate_id, "Candidate id is required.")
    s.team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    created_by_agent = s._trim_text(payload.get("createdByAgent"), max_length=160) or "Paper Note Extraction Agent"
    max_pages_per_chunk = s._normalize_int(
        payload.get("maxPagesPerChunk"),
        default=s.PAPER_NOTE_CHUNK_DEFAULT_MAX_PAGES,
        minimum=1,
        maximum=s.PAPER_NOTE_CHUNK_HARD_MAX_PAGES,
    )
    max_chars_per_chunk = s._normalize_int(
        payload.get("maxCharsPerChunk"),
        default=s.PAPER_NOTE_CHUNK_DEFAULT_MAX_CHARS,
        minimum=2000,
        maximum=s.PAPER_NOTE_CHUNK_HARD_MAX_CHARS,
    )
    now = s.utc_now_iso()
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        candidate_store = s._load_candidate_store(normalized_team_id)
        source_candidate = s._find_candidate(candidate_store, normalized_candidate_id)
        if source_candidate is None:
            raise s.TeamWorkflowOrchestrationError("Candidate not found.")
        if str(source_candidate.get("candidateType") or "") != "source_manifest":
            raise s.TeamWorkflowOrchestrationError("Paper note chunk planning requires a source_manifest candidate.")
        extraction = s._ready_source_extraction(source_candidate)
        chunks = s._build_paper_note_chunks(
            source_candidate,
            extraction,
            max_pages_per_chunk=max_pages_per_chunk,
            max_chars_per_chunk=max_chars_per_chunk,
        )
        if not chunks:
            raise s.TeamWorkflowOrchestrationError("Source extraction does not contain usable page anchors for paper_note chunks.")
        metadata = source_candidate.get("metadata") if isinstance(source_candidate.get("metadata"), dict) else {}
        chunk_plan = {
            "schemaVersion": s.SCHEMA_VERSION,
            "planId": s._new_record_id("paper-note-plan"),
            "planKind": "paper_note_chunk_plan",
            "status": "planned",
            "sourceCandidateId": normalized_candidate_id,
            "sourceLabel": s._source_manifest_label(source_candidate),
            "sourceSha256": str(extraction.get("sha256") or source_candidate.get("sha256") or ""),
            "pageScope": str(extraction.get("pageScope") or source_candidate.get("pageScope") or ""),
            "targetTaskType": "paper_note_draft",
            "targetWorkflowNode": "paper_note",
            "chunkStrategy": "page_anchor_window",
            "maxPagesPerChunk": max_pages_per_chunk,
            "maxCharsPerChunk": max_chars_per_chunk,
            "chunkCount": len(chunks),
            "completedChunkCount": 0,
            "needsRevisionChunkCount": 0,
            "chunks": chunks,
            "createdByAgent": created_by_agent,
            "createdAt": now,
            "updatedAt": now,
            "officialBoundary": {
                "writesFormalKnowledge": False,
                "writesRag": False,
                "writesOfficialGraph": False,
                "requiresPaperNoteReview": True,
            },
        }
        metadata["paperNoteChunkPlan"] = chunk_plan
        source_candidate["metadata"] = metadata
        source_candidate["updatedAt"] = now
        candidate_store["updatedAt"] = now
        s._write_json(s._candidate_store_path(normalized_team_id), candidate_store)
        workflow["updatedAt"] = now
        workflow["activeWorkflowItems"] = s._upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=normalized_candidate_id,
            current_node=str(source_candidate.get("currentWorkflowNode") or "knowledge_collection"),
            status=str(source_candidate.get("currentState") or "source_registered"),
            transfer_id=str(source_candidate.get("pendingTransferId") or ""),
        )
        s._write_json(s._workflow_path(normalized_team_id), workflow)
    s._record_workflow_event(
        "candidate.paper_note_chunk_plan_created",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "sourceCandidateId": normalized_candidate_id,
            "planId": chunk_plan["planId"],
            "chunkCount": chunk_plan["chunkCount"],
            "maxPagesPerChunk": max_pages_per_chunk,
        },
    )
    return {
        "candidate": source_candidate,
        "chunkPlan": chunk_plan,
        "workflow": s._workflow_to_api(normalized_team_id, workflow, candidate_store),
        "nextActions": [
            "Paper Note Extraction Agent should draft one paper_note per planned chunk.",
            "Use chunkId when calling paper-note-draft to keep page anchors and plan progress traceable.",
            "Do not promote chunk drafts to formal Team Knowledge without steward approval.",
        ],
    }


def get_paper_note_chunk_status(team_id: str) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.get_team(normalized_team_id)
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        candidate_store = s._load_candidate_store(normalized_team_id)
        candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
    source_candidates = [item for item in candidates if str(item.get("candidateType") or "") == "source_manifest"]
    ready_sources = [item for item in source_candidates if s._source_candidate_has_ready_extraction(item)]
    plans = [s._paper_note_chunk_plan_summary(item) for item in source_candidates]
    plans = [item for item in plans if item is not None]
    chunk_count = sum(int(item.get("chunkCount") or 0) for item in plans)
    drafted_count = sum(int(item.get("draftedChunkCount") or 0) for item in plans)
    needs_revision_count = sum(int(item.get("needsRevisionChunkCount") or 0) for item in plans)
    open_count = max(0, chunk_count - drafted_count - needs_revision_count)
    missing_plan_sources = [
        {
            "candidateId": str(item.get("candidateId") or ""),
            "title": str(item.get("title") or s._source_manifest_label(item)),
            "pageScope": str(((item.get("metadata") if isinstance(item.get("metadata"), dict) else {}).get("sourceExtraction") or {}).get("pageScope") or item.get("pageScope") or ""),
        }
        for item in ready_sources
        if s._candidate_paper_note_chunk_plan(item) is None
    ]
    action_items = s._paper_note_chunk_action_items(missing_plan_sources, plans, open_count)
    status = "empty"
    if plans:
        status = "ready" if open_count == 0 and needs_revision_count == 0 else "in_progress"
    elif missing_plan_sources:
        status = "needs_plan"
    payload = {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "workflowId": workflow["workflowId"],
        "workflowKind": workflow["workflowKind"],
        "status": status,
        "summary": {
            "sourceCandidateCount": len(source_candidates),
            "readySourceCandidateCount": len(ready_sources),
            "plannedSourceCandidateCount": len(plans),
            "missingPlanSourceCandidateCount": len(missing_plan_sources),
            "planCount": len(plans),
            "chunkCount": chunk_count,
            "draftedChunkCount": drafted_count,
            "needsRevisionChunkCount": needs_revision_count,
            "openChunkCount": open_count,
            "actionItemCount": len(action_items),
        },
        "plans": sorted(plans, key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)[:12],
        "missingPlanSources": missing_plan_sources[:12],
        "actionItems": action_items,
        "officialBoundary": {
            "writesFormalKnowledge": False,
            "writesRag": False,
            "writesOfficialGraph": False,
            "candidateOnly": True,
        },
        "storage": {
            "candidateStorePath": s._relative_path(s._candidate_store_path(normalized_team_id)),
        },
        "updatedAt": s.utc_now_iso(),
    }
    s._record_workflow_event(
        "paper_note_chunks.status_viewed",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "status": status,
            "planCount": len(plans),
            "chunkCount": chunk_count,
            "openChunkCount": open_count,
            "missingPlanSourceCandidateCount": len(missing_plan_sources),
            "plannedSourceCandidateIds": s._workflow_log_sample_values(plans, "sourceCandidateId"),
            "missingPlanSourceCandidateIds": s._workflow_log_sample_values(missing_plan_sources, "candidateId"),
            "actionItemCodes": s._workflow_log_sample_values(action_items, "code"),
        },
    )
    return payload


def _default_source_quality_required_fixes(
    candidate: dict[str, Any],
    scores: dict[str, int],
    validation: dict[str, Any],
) -> list[str]:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    extraction = (
        metadata.get("contentExtraction")
        if isinstance(metadata.get("contentExtraction"), dict)
        else metadata.get("sourceExtraction")
        if isinstance(metadata.get("sourceExtraction"), dict)
        else {}
    )
    evidence_refs = extraction.get("evidenceRefs") if isinstance(extraction.get("evidenceRefs"), list) else []
    page_anchors = extraction.get("pageAnchors") if isinstance(extraction.get("pageAnchors"), list) else []
    key_findings = extraction.get("keyFindings") if isinstance(extraction.get("keyFindings"), list) else []
    extraction_summary = str(extraction.get("summary") or "").strip()
    required_fixes: list[str] = []
    if not validation.get("valid"):
        required_fixes.append("修复 source_manifest 校验错误后再通过质量筛选。")
    if metadata.get("metadataOnlyDownload") is True and not extraction_summary and not key_findings:
        required_fixes.append("补充可核验的全文或公开摘要。")
    if not evidence_refs and not page_anchors:
        required_fixes.append("提取可定位的页码、段落或 DOI 证据锚点。")
    if int(scores.get("accessibility") or 0) < 55:
        required_fixes.append("确认来源可访问且允许分析，或更换可访问来源。")
    if int(scores.get("reliability") or 0) < 55:
        required_fixes.append("补充 DOI、出版信息或本地文件 sha256。")
    if int(scores.get("relevance") or 0) < 55:
        required_fixes.append("补充与研究问题的相关性说明，或更换来源。")
    if not required_fixes:
        required_fixes.append("打开资料详情确认质量缺口，补充来源证据后重新评估。")
    return required_fixes[:12]


def assess_source_candidate_quality(team_id: str, candidate_id: str, payload: dict[str, Any] | None = None, *, run_id: str = "") -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_candidate_id = s._normalize_required_id(candidate_id, "Candidate id is required.")
    s.team_service.get_team(normalized_team_id)
    # Run-scoped auto chains resolve the store through the authority run's
    # owner project; the assessment update must not drift to the active store.
    normalized_run_id = s._resolve_candidate_store_write_run(normalized_team_id, run_id)
    payload = payload if isinstance(payload, dict) else {}
    assessed_by_agent = s._trim_text(payload.get("assessedByAgent"), max_length=160) or "资料提炼 Agent"
    requested_decision = s._trim_text(payload.get("decision"), max_length=80)
    if requested_decision and requested_decision not in s.SOURCE_QUALITY_DECISIONS:
        raise s.TeamWorkflowOrchestrationError("Source quality decision must be approved, needs_revision, or rejected.")
    notes = s._trim_text(payload.get("notes"), max_length=4000)
    required_fixes = s._normalize_text_list(payload.get("requiredFixes"), max_items=12, max_length=240)
    risk_flags = s._normalize_text_list(payload.get("riskFlags"), max_items=12, max_length=120)
    evidence_refs = s._normalize_ref_list(payload.get("evidenceRefs"), max_items=24)
    now = s.utc_now_iso()
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        candidate_store = (
            s._load_candidate_store(normalized_team_id, run_id=normalized_run_id)
            if normalized_run_id
            else s._load_candidate_store(normalized_team_id)
        )
        candidate = s._find_candidate(candidate_store, normalized_candidate_id)
        if candidate is None:
            raise s.TeamWorkflowOrchestrationError("Candidate not found.")
        if str(candidate.get("candidateType") or "") != "source_manifest":
            raise s.TeamWorkflowOrchestrationError("Source quality assessment only supports source_manifest candidates.")
        validation = s.validate_candidate_record(candidate)
        scores = s._source_quality_scores(candidate, payload, validation)
        decision = requested_decision or s._default_source_quality_decision(scores, validation)
        if decision == "approved" and not validation.get("valid"):
            decision = "needs_revision"
        if decision == "needs_revision" and not required_fixes:
            required_fixes = _default_source_quality_required_fixes(candidate, scores, validation)
        source_label = s._source_manifest_label(candidate)
        assessment = {
            "schemaVersion": s.SCHEMA_VERSION,
            "assessmentId": s._new_record_id("source-quality"),
            "assessmentKind": "source_quality_assessment",
            "candidateId": normalized_candidate_id,
            "sourceLabel": source_label,
            "decision": decision,
            "status": decision,
            "scores": scores,
            "requiredFixes": required_fixes,
            "riskFlags": risk_flags,
            "notes": notes,
            "evidenceRefs": evidence_refs,
            "assessedByAgent": assessed_by_agent,
            "assessedAt": now,
            "officialBoundary": {
                "writesFormalKnowledge": False,
                "writesRag": False,
                "writesOfficialGraph": False,
                "candidateOnly": True,
            },
        }
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        history = metadata.get("sourceQualityAssessments") if isinstance(metadata.get("sourceQualityAssessments"), list) else []
        metadata["sourceQualityAssessment"] = assessment
        metadata["sourceQualityAssessments"] = [*history[-11:], assessment]
        candidate["metadata"] = metadata
        candidate["validation"] = validation
        if decision == "approved":
            candidate["currentWorkflowNode"] = "knowledge_collection"
            candidate["currentState"] = "source_screened"
            candidate["qualityStatus"] = "source_quality_approved"
        elif decision == "rejected":
            candidate["currentWorkflowNode"] = "rejection_archive"
            candidate["currentState"] = "rejected"
            candidate["qualityStatus"] = "source_quality_rejected"
            metadata["rejectionArchive"] = {
                "reason": notes or "资料提炼 Agent 判定该资料无有效内容或不适合进入本轮。",
                "rejectedByAgent": assessed_by_agent,
                "rejectedAt": now,
                "assessmentId": assessment["assessmentId"],
            }
        else:
            candidate["currentWorkflowNode"] = "knowledge_collection"
            candidate["currentState"] = "source_needs_quality_revision"
            candidate["qualityStatus"] = "source_quality_needs_revision"
        candidate["updatedAt"] = now
        candidate_store["updatedAt"] = now
        s._write_json(s._candidate_store_path(normalized_team_id, normalized_run_id), candidate_store)
        workflow["updatedAt"] = now
        workflow["activeWorkflowItems"] = s._upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=normalized_candidate_id,
            current_node=str(candidate.get("currentWorkflowNode") or "knowledge_collection"),
            status=str(candidate.get("currentState") or ""),
            transfer_id=str(candidate.get("pendingTransferId") or ""),
        )
        s._write_json(s._workflow_path(normalized_team_id), workflow)
    s._record_workflow_event(
        "candidate.source_quality_assessed",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "candidateId": normalized_candidate_id,
            "decision": decision,
            "overallScore": scores["overall"],
            "assessedByAgent": assessed_by_agent,
            "sourceCollectionRunId": normalized_run_id,
        },
    )
    return {
        "candidate": candidate,
        "assessment": assessment,
        "status": s.get_source_quality_status(normalized_team_id),
        "workflow": s._workflow_to_api(normalized_team_id, workflow, candidate_store),
        "nextActions": s._source_quality_next_actions(decision),
    }


def assess_source_quality_batch(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    batch_run_id = s._new_record_id("source-quality-batch")
    assessed_by_agent = s._trim_text(payload.get("assessedByAgent"), max_length=160) or "资料提炼 Agent"
    max_candidates = s._normalize_int(payload.get("maxCandidates"), default=100, minimum=1, maximum=200)
    force = bool(payload.get("force"))
    requested_candidate_ids = s._normalize_text_list(payload.get("candidateIds"), max_items=200, max_length=128)
    notes = s._trim_text(payload.get("notes"), max_length=4000) or "资料提炼 Agent 已完成本轮批量提炼和审查。"
    evidence_refs = s._normalize_ref_list(payload.get("evidenceRefs"), max_items=24)
    evidence_refs = [
        *evidence_refs,
        {"type": "source_quality_batch", "id": batch_run_id, "label": "Source quality batch assessment"},
    ][:24]
    with s._WORKFLOW_LOCK:
        candidate_store = s._load_candidate_store(normalized_team_id)
        source_candidates = [
            item
            for item in list(candidate_store.get("candidates") or [])
            if isinstance(item, dict) and str(item.get("candidateType") or "") == "source_manifest"
        ]
        source_candidates, _source_family_summary = project_source_version_families(source_candidates)
        source_by_id = {str(item.get("candidateId") or ""): item for item in source_candidates if str(item.get("candidateId") or "")}
        if requested_candidate_ids:
            selection = [source_by_id[item] for item in requested_candidate_ids if item in source_by_id]
            skipped_candidates = [
                {"candidateId": item, "reason": "not_found_or_not_source_manifest"}
                for item in requested_candidate_ids
                if item not in source_by_id
            ]
        else:
            selection = source_candidates
            skipped_candidates = []
        reviewable_selection = [
            item
            for item in selection
            if not (
                isinstance(item.get("sourceVersionFamily"), dict)
                and item["sourceVersionFamily"].get("state") == "superseded"
            )
        ]
        skipped_candidates.extend(
            {
                "candidateId": str(item.get("candidateId") or ""),
                "title": str(item.get("title") or s._source_manifest_label(item)),
                "reason": "superseded_source_version",
            }
            for item in selection
            if item not in reviewable_selection
        )
        target_candidates = [
            item
            for item in reviewable_selection
            if force or s._candidate_source_quality_assessment(item) is None
        ][:max_candidates]
        skipped_candidates.extend(
            {
                "candidateId": str(item.get("candidateId") or ""),
                "title": str(item.get("title") or s._source_manifest_label(item)),
                "reason": "already_assessed",
            }
            for item in reviewable_selection
            if item not in target_candidates and s._candidate_source_quality_assessment(item) is not None
        )
        target_candidate_ids = [str(item.get("candidateId") or "") for item in target_candidates if str(item.get("candidateId") or "")]
    assessments: list[dict[str, Any]] = []
    failed_candidates: list[dict[str, str]] = []
    for candidate_id in target_candidate_ids:
        try:
            assessment_response = s.assess_source_candidate_quality(
                normalized_team_id,
                candidate_id,
                {
                    "assessedByAgent": assessed_by_agent,
                    "notes": notes,
                    "evidenceRefs": evidence_refs,
                },
            )
        except (s.team_service.TeamServiceError, s.TeamWorkflowOrchestrationError) as exc:
            failed_candidates.append({"candidateId": candidate_id, "error": str(exc)})
            continue
        assessments.append(
            s._source_quality_batch_assessment_summary(
                assessment_response.get("candidate", {}),
                assessment_response.get("assessment", {}),
            )
        )
    decision_counts = {
        "approved": sum(1 for item in assessments if item.get("decision") == "approved"),
        "needsRevision": sum(1 for item in assessments if item.get("decision") == "needs_revision"),
        "rejected": sum(1 for item in assessments if item.get("decision") == "rejected"),
    }
    source_quality_status = s.get_source_quality_status(normalized_team_id)
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        candidate_store = s._load_candidate_store(normalized_team_id)
    if failed_candidates and not assessments:
        run_status = "failed"
    elif not source_candidates:
        run_status = "no_candidates"
    elif not target_candidate_ids:
        run_status = "no_pending_candidates"
    else:
        run_status = "completed"
    summary = {
        "targetCandidateCount": len(target_candidate_ids),
        "assessedCandidateCount": len(assessments),
        "approvedCandidateCount": decision_counts["approved"],
        "needsRevisionCandidateCount": decision_counts["needsRevision"],
        "rejectedCandidateCount": decision_counts["rejected"],
        "failedCandidateCount": len(failed_candidates),
        "skippedCandidateCount": len(skipped_candidates),
    }
    s._record_workflow_event(
        "source_quality.batch_assessed",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "batchRunId": batch_run_id,
            "status": run_status,
            "assessedByAgent": assessed_by_agent,
            **summary,
            "assessedCandidateIds": s._workflow_log_sample_values(assessments, "candidateId"),
        },
        child_log_path=f"artifacts/source-quality-{s._safe_token(batch_run_id, default='batch', max_length=96)}-batch-assessment.jsonl",
        child_log_payload={
            "kind": "source_quality_batch_assessment",
            "teamId": normalized_team_id,
            "workflowId": workflow["workflowId"],
            "batchRunId": batch_run_id,
            "status": run_status,
            "assessedByAgent": assessed_by_agent,
            "summary": summary,
            "assessments": assessments[:80],
            "skippedCandidates": skipped_candidates[:80],
            "failedCandidates": failed_candidates[:80],
            "truncatedAssessmentCount": max(0, len(assessments) - 80),
            "truncatedSkippedCandidateCount": max(0, len(skipped_candidates) - 80),
            "truncatedFailedCandidateCount": max(0, len(failed_candidates) - 80),
        },
    )
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "workflowId": workflow["workflowId"],
        "batchRunId": batch_run_id,
        "executionMode": "source_quality_agent_batch",
        "status": run_status,
        "assessedByAgent": assessed_by_agent,
        "summary": summary,
        "assessments": assessments,
        "skippedCandidates": skipped_candidates[:24],
        "failedCandidates": failed_candidates[:24],
        "sourceQualityStatus": source_quality_status,
        "workflow": s._workflow_to_api(normalized_team_id, workflow, candidate_store),
        "officialBoundary": {
            "writesFormalKnowledge": False,
            "writesRag": False,
            "writesOfficialGraph": False,
            "candidateOnly": True,
        },
        "nextActions": [
            "Review failed or needs_revision candidates before downstream paper_note extraction.",
            "Approved candidates may proceed to candidate-only paper_note planning.",
        ],
        "updatedAt": s.utc_now_iso(),
    }


def get_source_quality_status(team_id: str) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.assert_team_exists(normalized_team_id)
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        candidate_store = s._load_candidate_store(normalized_team_id)
        candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
    source_candidates = [item for item in candidates if str(item.get("candidateType") or "") == "source_manifest"]
    projected_source_candidates, source_family_summary = project_source_version_families(source_candidates)
    reviewable_source_candidates = [
        item
        for item in projected_source_candidates
        if not (
            isinstance(item.get("sourceVersionFamily"), dict)
            and item["sourceVersionFamily"].get("state") == "superseded"
        )
    ]
    assessed = [item for item in reviewable_source_candidates if s._candidate_source_quality_assessment(item) is not None]
    approved = [item for item in reviewable_source_candidates if s._source_quality_bucket(item) == "approved"]
    needs_revision = [item for item in reviewable_source_candidates if s._source_quality_bucket(item) == "needs_revision"]
    rejected = [item for item in reviewable_source_candidates if s._source_quality_bucket(item) == "rejected"]
    unassessed = [item for item in reviewable_source_candidates if s._source_quality_bucket(item) == "pending"]
    extraction_ready = [item for item in reviewable_source_candidates if s._source_candidate_has_ready_extraction(item)]
    candidate_summaries = [s._source_quality_candidate_summary(item) for item in source_candidates]
    action_items = s._source_quality_action_items(reviewable_source_candidates, unassessed, needs_revision)
    status = "empty"
    if reviewable_source_candidates:
        status = "ready" if approved else "needs_screening"
        if needs_revision or unassessed:
            status = "in_progress" if approved else "needs_screening"
        if len(rejected) == len(reviewable_source_candidates):
            status = "blocked"
    payload = {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "workflowId": workflow["workflowId"],
        "workflowKind": workflow["workflowKind"],
        "scope": s._team_aggregate_workflow_scope(),
        "status": status,
        "summary": {
            "sourceCandidateCount": len(source_candidates),
            "independentSourceCandidateCount": source_family_summary["independentSourceCount"],
            "supersededSourceCandidateCount": source_family_summary["supersededRecordCount"],
            "assessedSourceCandidateCount": len(assessed),
            "approvedSourceCandidateCount": len(approved),
            "needsRevisionSourceCandidateCount": len(needs_revision),
            "rejectedSourceCandidateCount": len(rejected),
            "unassessedSourceCandidateCount": len(unassessed),
            "extractionReadySourceCandidateCount": len(extraction_ready),
            "actionItemCount": len(action_items),
        },
        "candidates": sorted(candidate_summaries, key=lambda item: str(item.get("updatedAt") or ""), reverse=True)[:16],
        "actionItems": action_items,
        "screeningContract": {
            "agentRole": "资料提炼 Agent",
            "targetCandidateType": "source_manifest",
            "decisions": sorted(s.SOURCE_QUALITY_DECISIONS),
            "writesCandidateStore": True,
            "writesFormalKnowledge": False,
            "writesRag": False,
            "writesOfficialGraph": False,
        },
        "officialBoundary": {
            "writesFormalKnowledge": False,
            "writesRag": False,
            "writesOfficialGraph": False,
            "candidateOnly": True,
        },
        "storage": {
            "candidateStorePath": s._relative_path(s._candidate_store_path(normalized_team_id)),
        },
        "updatedAt": s.utc_now_iso(),
    }
    s._record_workflow_event(
        "source_quality.status_viewed",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "status": status,
            "sourceCandidateCount": len(source_candidates),
            "independentSourceCandidateCount": source_family_summary["independentSourceCount"],
            "supersededSourceCandidateCount": source_family_summary["supersededRecordCount"],
            "approvedSourceCandidateCount": len(approved),
            "needsRevisionSourceCandidateCount": len(needs_revision),
            "rejectedSourceCandidateCount": len(rejected),
            "unassessedSourceCandidateCount": len(unassessed),
            "extractionReadySourceCandidateCount": len(extraction_ready),
            "approvedSourceCandidateIds": s._workflow_log_sample_values(approved, "candidateId"),
            "needsRevisionSourceCandidateIds": s._workflow_log_sample_values(needs_revision, "candidateId"),
            "rejectedSourceCandidateIds": s._workflow_log_sample_values(rejected, "candidateId"),
            "unassessedSourceCandidateIds": s._workflow_log_sample_values(unassessed, "candidateId"),
            "extractionReadySourceCandidateIds": s._workflow_log_sample_values(extraction_ready, "candidateId"),
            "actionItemCodes": s._workflow_log_sample_values(action_items, "code"),
        },
    )
    return payload


def get_knowledge_ingestion_status(team_id: str) -> dict[str, Any]:
    """Return a read-only status view for the Challenge Cup knowledge ingestion funnel."""
    s = _service()

    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.assert_team_exists(normalized_team_id)
    ingestion_store = s._knowledge_ingestion_work_run_store()
    ingestion_active_snapshot = s._decorate_knowledge_ingestion_work_run_snapshot(
        ingestion_store.load_active_snapshot(s.KNOWLEDGE_INGESTION_WORK_RUN_KIND)
    )
    if not s._knowledge_ingestion_snapshot_is_active(ingestion_active_snapshot, normalized_team_id):
        ingestion_active_snapshot = None
    ingestion_latest_snapshot = s._decorate_knowledge_ingestion_work_run_snapshot(
        ingestion_store.load_latest_snapshot(s.KNOWLEDGE_INGESTION_WORK_RUN_KIND)
    )
    if isinstance(ingestion_latest_snapshot, dict) and s._trim_text(ingestion_latest_snapshot.get("teamId"), max_length=160) != normalized_team_id:
        ingestion_latest_snapshot = None
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        candidate_store = s._load_candidate_store(normalized_team_id)
        candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
        candidate_reports = [
            {
                "candidateId": str(candidate.get("candidateId") or ""),
                "candidateType": str(candidate.get("candidateType") or ""),
                "currentWorkflowNode": str(candidate.get("currentWorkflowNode") or ""),
                "currentState": str(candidate.get("currentState") or ""),
                "qualityStatus": str(candidate.get("qualityStatus") or ""),
                "validation": s.validate_candidate_record(candidate),
            }
            for candidate in candidates
        ]
        active_graph_candidates = [
            item
            for item in candidates
            if str(item.get("candidateType") or "") != "candidate_graph" and not s._candidate_is_archived(item)
        ]
        archived_candidates = [
            item
            for item in candidates
            if str(item.get("candidateType") or "") != "candidate_graph" and s._candidate_is_archived(item)
        ]
        graph_candidates = [
            item
            for item in candidates
            if str(item.get("candidateType") or "") == "candidate_graph" and not s._candidate_is_archived(item)
        ]
        latest_graph = s._latest_candidate_record(graph_candidates)
        latest_graph_metadata = latest_graph.get("metadata") if isinstance((latest_graph or {}).get("metadata"), dict) else {}
        candidate_graph = latest_graph_metadata.get("graph") if isinstance(latest_graph_metadata.get("graph"), dict) else s._build_candidate_graph_payload(normalized_team_id, workflow["workflowId"], active_graph_candidates)
        candidate_graph["summary"]["archivedCandidateCount"] = len(archived_candidates)

    try:
        knowledge_overview = s.team_knowledge_service.list_team_knowledge_bases(normalized_team_id, internal=True)
    except (s.team_knowledge_service.TeamKnowledgeError, s.team_knowledge_service.TeamKnowledgeNotFoundError) as exc:
        raise s.TeamWorkflowOrchestrationError(str(exc)) from exc

    candidate_summary = s._knowledge_ingestion_candidate_summary(candidates, candidate_reports, candidate_graph)
    knowledge_summary = s._knowledge_ingestion_knowledge_summary(knowledge_overview)
    stages = s._knowledge_ingestion_stages(candidate_summary, knowledge_summary)
    action_items = s._knowledge_ingestion_action_items(candidates, candidate_reports, candidate_graph, candidate_summary, knowledge_summary)
    overall_status = s._knowledge_ingestion_overall_status(stages, action_items, candidate_summary, knowledge_summary)
    non_graph_candidates = [item for item in candidates if str(item.get("candidateType") or "") != "candidate_graph"]
    pending_source_review_candidates = [
        item for item in non_graph_candidates if s._candidate_knowledge_ingestion_status(item) == "pending_source_review"
    ]
    pending_knowledge_review_candidates = [
        item for item in non_graph_candidates if s._candidate_knowledge_ingestion_status(item) == "pending_review"
    ]
    steward_candidates = [
        item
        for item in non_graph_candidates
        if str(item.get("currentWorkflowNode") or "") == "steward_ingestion"
        or str((item.get("metadata") if isinstance(item.get("metadata"), dict) else {}).get("taskType") or "") == "steward_pack_draft"
    ]
    invalid_candidate_reports = [item for item in candidate_reports if not bool((item.get("validation") or {}).get("valid"))]
    summary = {
        **candidate_summary,
        **knowledge_summary,
        "actionItemCount": len(action_items),
    }
    payload = {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "workflowId": workflow["workflowId"],
        "workflowKind": workflow["workflowKind"],
        "scope": s._team_aggregate_workflow_scope(),
        "status": overall_status,
        "summary": summary,
        "stages": stages,
        "actionItems": action_items,
        "candidateBreakdown": s._candidate_breakdown(candidates),
        "candidateGraphSummary": candidate_graph["summary"],
        "officialBoundary": {
            "candidateStoreOfficialState": "candidate_only_until_steward_approval",
            "teamKnowledgeRequiresReview": True,
            "candidateGraphWritesOfficialGraph": False,
            "formalKnowledgeItemCreated": summary["formalKnowledgeItemCount"] > 0,
            "writesOfficialKnowledge": summary["officialSyncedCandidateCount"] > 0,
            "writesOfficialRag": False,
            "writesOfficialGraph": summary["officialGraphSyncedCandidateCount"] > 0,
            "graphStatus": "official_research_trace_synced"
            if summary["officialGraphSyncedCandidateCount"] > 0
            else "candidate_graph_preview_only",
            "ragStatus": "queryable_via_reviewed_team_knowledge"
            if summary["formalKnowledgeItemCount"] > 0
            else "not_synced",
        },
        "knowledgeBases": s._knowledge_ingestion_knowledge_bases(knowledge_overview),
        "storage": {
            "workflowPath": s._relative_path(s._workflow_path(normalized_team_id)),
            "candidateStorePath": s._relative_path(s._candidate_store_path(normalized_team_id)),
            "transferRecordsPath": s._relative_path(s._transfer_records_path(normalized_team_id)),
        },
        "activeWorkRun": ingestion_active_snapshot,
        "latestWorkRun": ingestion_latest_snapshot,
        "updatedAt": s.utc_now_iso(),
    }
    _view_key = f"knowledge_ingestion.status_viewed:{normalized_team_id}:{workflow['workflowId']}"
    _view_value = f"{overall_status}:{summary['candidateCount']}:{summary['formalKnowledgeItemCount']}"
    if _WORKFLOW_EVENT_STATUS_VIEW_MEMORY.get(_view_key) != _view_value:
        _WORKFLOW_EVENT_STATUS_VIEW_MEMORY[_view_key] = _view_value
        s._record_workflow_event(
            "knowledge_ingestion.status_viewed",
            normalized_team_id,
            fields={
                "workflowId": workflow["workflowId"],
                "status": overall_status,
                "candidateCount": summary["candidateCount"],
                "pendingProposalCount": summary["pendingProposalCount"],
                "formalKnowledgeItemCount": summary["formalKnowledgeItemCount"],
                "actionItemCount": summary["actionItemCount"],
                "candidateBreakdown": s._candidate_breakdown(candidates),
                "pendingSourceReviewCandidateIds": s._workflow_log_sample_values(pending_source_review_candidates, "candidateId"),
                "pendingKnowledgeReviewCandidateIds": s._workflow_log_sample_values(pending_knowledge_review_candidates, "candidateId"),
                "stewardCandidateIds": s._workflow_log_sample_values(steward_candidates, "candidateId"),
                "invalidCandidateIds": s._workflow_log_sample_values(invalid_candidate_reports, "candidateId"),
                "actionItemCodes": s._workflow_log_sample_values(action_items, "code"),
            },
        )
    return payload


def get_official_model_evidence_status(team_id: str) -> dict[str, Any]:
    """Return a read-only model-call evidence coverage view for the research workflow."""
    s = _service()

    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.get_team(normalized_team_id)
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        evidence_store = s._load_official_model_evidence_store(normalized_team_id)
        candidate_store = s._load_candidate_store(normalized_team_id)
        stored_evidence = s._official_model_evidence_entries(evidence_store)
        candidate_evidence = s._official_model_evidence_from_candidates(candidate_store, workflow)
    evidence = s._dedupe_official_model_evidence([*stored_evidence, *candidate_evidence])
    coverage = s._official_model_evidence_coverage(evidence)
    missing_nodes = [item for item in coverage if item["status"] == "missing"]
    provider_counts = s._count_by_field(evidence, "modelProvider")
    evidence_kind_counts = s._count_by_field(evidence, "evidenceKind")
    linked_candidate_count = len({str(item.get("candidateId") or "") for item in evidence if item.get("candidateId")})
    linked_stage_count = len({str(item.get("stageRoundId") or "") for item in evidence if item.get("stageRoundId")})
    summary = {
        "evidenceCount": len(evidence),
        "storedEvidenceCount": len(stored_evidence),
        "candidateOutputEvidenceCount": len(candidate_evidence),
        "requiredNodeCount": len(s.OFFICIAL_MODEL_EVIDENCE_REQUIRED_TASKS),
        "coveredNodeCount": len(coverage) - len(missing_nodes),
        "missingNodeCount": len(missing_nodes),
        "qwenEvidenceCount": sum(
            count for provider, count in provider_counts.items() if "qwen" in provider.lower() or provider.lower() in {"dashscope", "bailian"}
        ),
        "bailianEvidenceCount": sum(count for provider, count in provider_counts.items() if "bailian" in provider.lower() or "百炼" in provider),
        "localEvidenceCount": sum(count for provider, count in provider_counts.items() if provider.lower().startswith("local")),
        "linkedCandidateCount": linked_candidate_count,
        "linkedStageRoundCount": linked_stage_count,
    }
    status = "empty" if not evidence else ("ready" if not missing_nodes else "needs_evidence")
    action_items = s._official_model_evidence_action_items(missing_nodes, summary)
    payload = {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "workflowId": workflow["workflowId"],
        "workflowKind": workflow["workflowKind"],
        "scope": s._team_aggregate_workflow_scope(),
        "status": status,
        "summary": {**summary, "actionItemCount": len(action_items)},
        "coverage": coverage,
        "providerCounts": provider_counts,
        "evidenceKindCounts": evidence_kind_counts,
        "recentEvidence": sorted(evidence, key=lambda item: str(item.get("createdAt") or ""), reverse=True)[:12],
        "actionItems": action_items,
        "officialBoundary": s._official_model_evidence_boundary(),
        "storage": {
            "workflowPath": s._relative_path(s._workflow_path(normalized_team_id)),
            "candidateStorePath": s._relative_path(s._candidate_store_path(normalized_team_id)),
            "evidenceStorePath": s._relative_path(s._official_model_evidence_store_path(normalized_team_id)),
        },
        "updatedAt": s.utc_now_iso(),
    }
    s._record_workflow_event(
        "official_model_evidence.status_viewed",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "status": status,
            "evidenceCount": summary["evidenceCount"],
            "coveredNodeCount": summary["coveredNodeCount"],
            "missingNodeCount": summary["missingNodeCount"],
            "actionItemCount": len(action_items),
            "missingWorkflowNodes": s._workflow_log_sample_values(missing_nodes, "workflowNode"),
            "missingTaskTypes": s._workflow_log_sample_values(missing_nodes, "taskType"),
            "modelProviderCounts": s._workflow_log_count_sample(provider_counts),
            "evidenceKindCounts": s._workflow_log_count_sample(evidence_kind_counts),
            "actionItemCodes": s._workflow_log_sample_values(action_items, "code"),
        },
    )
    return payload


def register_official_model_evidence(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Register a model-call evidence record without promoting it to formal knowledge."""
    s = _service()

    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.get_team(normalized_team_id)
    request_payload = dict(payload) if isinstance(payload, dict) else {}
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        candidate_store = s._load_candidate_store(normalized_team_id)
        evidence_store = s._load_official_model_evidence_store(normalized_team_id)
        evidence = s._build_official_model_evidence_record(
            normalized_team_id,
            workflow,
            candidate_store,
            request_payload,
        )
        evidence_store.setdefault("evidence", []).append(evidence)
        evidence_store["updatedAt"] = evidence["createdAt"]
        s._write_json(s._official_model_evidence_store_path(normalized_team_id), evidence_store)
    s._record_workflow_event(
        "official_model_evidence.recorded",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "evidenceId": evidence["evidenceId"],
            "taskType": evidence["taskType"],
            "workflowNode": evidence["workflowNode"],
            "modelProvider": evidence["modelProvider"],
            "evidenceKind": evidence["evidenceKind"],
            "candidateId": evidence.get("candidateId", ""),
        },
    )
    return {
        "evidence": evidence,
        "status": s.get_official_model_evidence_status(normalized_team_id),
    }


def get_team_workflow_coordination_status(team_id: str) -> dict[str, Any]:
    """Return a read-only coordination queue for the Challenge Cup research workflow."""
    s = _service()

    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.assert_team_exists(normalized_team_id)
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        candidate_store = s._load_candidate_store(normalized_team_id)
        transfers = s._load_transfer_records(normalized_team_id)
        candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]

    validation_reports = {str(candidate.get("candidateId") or ""): s.validate_candidate_record(candidate) for candidate in candidates}
    requested_transfers = [transfer for transfer in transfers if str(transfer.get("status") or "") == "requested"]
    active_candidates = [candidate for candidate in candidates if str(candidate.get("candidateType") or "") != "candidate_graph" and not s._candidate_is_archived(candidate)]
    archived_candidates = [candidate for candidate in candidates if str(candidate.get("candidateType") or "") != "candidate_graph" and s._candidate_is_archived(candidate)]
    queues = s._coordination_queues(active_candidates, requested_transfers, validation_reports)
    summary = s._coordination_summary(active_candidates, archived_candidates, requested_transfers, queues)
    action_items = s._coordination_action_items(summary, queues)
    status = s._coordination_status(summary, action_items)
    payload = {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "workflowId": workflow["workflowId"],
        "workflowKind": workflow["workflowKind"],
        "scope": s._team_aggregate_workflow_scope(),
        "status": status,
        "ownerAgentId": workflow.get("ownerAgentId") or s.DEFAULT_OWNER_AGENT_ID,
        "summary": summary,
        "queues": queues,
        "actionItems": action_items,
        "communication": s._coordination_communication_summary(summary, queues),
        "coordinationPolicy": {
            "coordinationAgentId": str(workflow.get("routingPolicy", {}).get("coordinationAgentId") or workflow.get("ownerAgentId") or s.DEFAULT_OWNER_AGENT_ID),
            "organizingAgentId": str(workflow.get("ownerAgentId") or s.DEFAULT_OWNER_AGENT_ID),
            "functionalAgentsMayRequestTransfer": bool(workflow.get("routingPolicy", {}).get("functionalAgentsMayRequestTransfer")),
            "requiresUserConfirmation": bool(workflow.get("transferPolicy", {}).get("requiresUserConfirmation")),
            "finalStateWriter": str(workflow.get("routingPolicy", {}).get("finalStateWriter") or workflow.get("ownerAgentId") or s.DEFAULT_OWNER_AGENT_ID),
            "readOnlyStatus": True,
            "autoTransferEnabled": False,
        },
        "storage": {
            "workflowPath": s._relative_path(s._workflow_path(normalized_team_id)),
            "candidateStorePath": s._relative_path(s._candidate_store_path(normalized_team_id)),
            "transferRecordsPath": s._relative_path(s._transfer_records_path(normalized_team_id)),
        },
        "updatedAt": s.utc_now_iso(),
    }
    s._record_workflow_event(
        "coordination.status_viewed",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "status": status,
            "activeCandidateCount": summary["activeCandidateCount"],
            "pendingTransferCount": summary["pendingTransferCount"],
            "reworkCandidateCount": summary["reworkCandidateCount"],
            "blockedCandidateCount": summary["blockedCandidateCount"],
            "actionItemCount": summary["actionItemCount"],
            "communicationBriefCount": summary["communicationBriefCount"],
            "pendingTransferCandidateIds": s._workflow_log_queue_candidate_ids(queues, "pendingTransfers"),
            "reworkCandidateIds": s._workflow_log_queue_candidate_ids(queues, "needsRework"),
            "stewardshipCandidateIds": s._workflow_log_queue_candidate_ids(queues, "stewardship"),
            "blockedCandidateIds": s._workflow_log_queue_candidate_ids(queues, "blocked"),
            "activeCandidateIds": s._workflow_log_queue_candidate_ids(queues, "active"),
            "actionItemCodes": s._workflow_log_sample_values(action_items, "code"),
        },
    )
    return payload


def build_candidate_graph(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    curation_mode = s._trim_text(payload.get("curationMode"), max_length=80) or "all_active"
    created_by_agent = s._trim_text(payload.get("createdByAgent"), max_length=160) or "资料关系整理 Agent"
    source_quality_agent_id = s._trim_text(payload.get("sourceQualityAgentId"), max_length=160) or "资料提炼 Agent"
    source_collection_run_id = s._trim_text(payload.get("sourceCollectionRunId") or payload.get("runId"), max_length=160)
    force_rebuild = bool(payload.get("forceRebuild"))
    if bool(payload.get("forceReview")):
        s.assess_source_quality_batch(
            normalized_team_id,
            {
                "assessedByAgent": source_quality_agent_id,
                "maxCandidates": s._normalize_int(payload.get("maxCandidates"), default=80, minimum=1, maximum=200),
                "force": True,
                "notes": "Source Relation Mapper requested source review before graph generation.",
            },
        )
    now = s.utc_now_iso()
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        # Run-scoped builds resolve the candidate store through the shared
        # run-owner resolver (owner-first merged read) so the graph
        # materializes into the run's owning project instead of whichever
        # project happens to be active; writes stay normalized to the
        # owner-project store path.
        candidate_store = (
            s._load_candidate_store(normalized_team_id, run_id=source_collection_run_id)
            if source_collection_run_id
            else s._load_candidate_store(normalized_team_id)
        )
        all_candidates = [
            item
            for item in list(candidate_store.get("candidates") or [])
            if isinstance(item, dict) and s._candidate_allowed_for_agent_graph_input(item)
        ]
        if source_collection_run_id:
            all_candidates = [
                item
                for item in all_candidates
                if s._source_collection_candidate_trace_run_id(item) == source_collection_run_id
            ]
        archived_candidates = [item for item in all_candidates if s._candidate_is_archived(item)]
        active_candidates = [item for item in all_candidates if not s._candidate_is_archived(item)]
        filtered_candidates: list[dict[str, Any]] = []
        if curation_mode == "agent_approved_only":
            candidates = [item for item in active_candidates if s._candidate_ready_for_agent_graph(item)]
            filtered_candidates = [item for item in active_candidates if item not in candidates]
        else:
            candidates = active_candidates
        graph_fingerprint = s._knowledge_collection_fingerprint(
            normalized_team_id,
            candidates,
            purpose="candidate_graph",
            curation_mode=curation_mode,
        )
        if not force_rebuild:
            reusable_graph = s._find_reusable_candidate_graph(candidate_store, graph_fingerprint)
            if reusable_graph is not None:
                metadata = reusable_graph.get("metadata") if isinstance(reusable_graph.get("metadata"), dict) else {}
                graph = metadata.get("graph") if isinstance(metadata.get("graph"), dict) else s._build_candidate_graph_payload(normalized_team_id, workflow["workflowId"], candidates)
                graph.setdefault("summary", {})
                graph["summary"]["archivedCandidateCount"] = len(archived_candidates)
                graph["summary"]["curationMode"] = curation_mode
                graph["summary"]["inputCandidateCount"] = len(active_candidates)
                graph["summary"]["filteredCandidateCount"] = len(filtered_candidates)
                graph["summary"]["createdByAgent"] = created_by_agent
                graph["summary"]["stageAgentRole"] = "source_relation_mapper"
                if source_collection_run_id:
                    graph["summary"]["sourceCollectionRunId"] = source_collection_run_id
                s._record_workflow_event(
                    "candidate_graph.reused",
                    normalized_team_id,
                    fields={
                        "workflowId": workflow["workflowId"],
                        "candidateId": str(reusable_graph.get("candidateId") or ""),
                        "nodeCount": len(graph.get("nodes") or []),
                        "edgeCount": len(graph.get("edges") or []),
                        "missingLinkCount": len(graph.get("missingLinks") or []),
                        "unreviewedNodeCount": len(graph.get("unreviewedNodes") or []),
                        "archivedCandidateCount": len(archived_candidates),
                        "filteredCandidateCount": len(filtered_candidates),
                        "curationMode": curation_mode,
                        "sourceCollectionRunId": source_collection_run_id,
                        "createdByAgent": created_by_agent,
                        "ingestionFingerprint": graph_fingerprint,
                    },
                )
                return {
                    "candidateGraph": reusable_graph,
                    "graph": graph,
                    "workflow": s._workflow_to_api(normalized_team_id, workflow, candidate_store),
                    "reusedCandidateGraph": True,
                    "ingestionFingerprint": graph_fingerprint,
                }
        graph = s._build_candidate_graph_payload(normalized_team_id, workflow["workflowId"], candidates)
        graph["summary"]["archivedCandidateCount"] = len(archived_candidates)
        graph["summary"]["curationMode"] = curation_mode
        graph["summary"]["inputCandidateCount"] = len(active_candidates)
        graph["summary"]["filteredCandidateCount"] = len(filtered_candidates)
        graph["summary"]["createdByAgent"] = created_by_agent
        graph["summary"]["stageAgentRole"] = "source_relation_mapper"
        if source_collection_run_id:
            graph["summary"]["sourceCollectionRunId"] = source_collection_run_id
        graph["summary"]["ingestionFingerprint"] = graph_fingerprint
        agent_process = [
            {
                "eventType": "candidate_graph.input_selected",
                "stage": "candidate_graph",
                "agentRole": "source_relation_mapper",
                "agentId": created_by_agent,
                "status": "completed",
                "inputSummary": f"{len(active_candidates)} active candidates, {len(candidates)} selected",
                "outputSummary": f"{len(filtered_candidates)} candidates filtered before graph preview",
                "nextAction": "build_candidate_graph_snapshot",
                "candidateIds": [str(item.get("candidateId") or "") for item in candidates[:64]],
            },
            {
                "eventType": "candidate_graph.snapshot_built",
                "stage": "candidate_graph",
                "agentRole": "source_relation_mapper",
                "agentId": created_by_agent,
                "status": "completed" if not graph["missingLinks"] else "needs_attention",
                "inputSummary": f"{len(candidates)} selected candidates",
                "outputSummary": f"{len(graph['nodes'])} nodes / {len(graph['edges'])} edges",
                "nextAction": "knowledge_ingestion_precheck" if not graph["missingLinks"] else "repair_candidate_graph_links",
                "candidateGraphBoundary": "candidate_only",
            },
        ]
        record = {
            "schemaVersion": s.SCHEMA_VERSION,
            "candidateId": s._new_record_id("candidate-graph"),
            "candidateType": "candidate_graph",
            "teamId": normalized_team_id,
            "workflowId": workflow["workflowId"],
            "title": s._trim_text(payload.get("title"), max_length=240) or "Candidate graph snapshot",
            "sourceKind": "candidate_graph_builder",
            "summary": (
                f"{len(graph['nodes'])} nodes, {len(graph['edges'])} edges, "
                f"{len(graph['missingLinks'])} missing links, {len(archived_candidates)} archived, "
                f"{len(filtered_candidates)} filtered"
            ),
            "sourceRefs": [],
            "evidenceRefs": [],
            "metadata": {
                "generatedFromCandidateIds": [node["candidateId"] for node in graph["nodes"]],
                "curationMode": curation_mode,
                "filteredCandidateIds": [str(item.get("candidateId") or "") for item in filtered_candidates],
                "graph": graph,
                "agentProcess": agent_process,
                "workflowStage": "candidate_graph",
                "stageAgentRole": "source_relation_mapper",
                "missingLinkCount": len(graph["missingLinks"]),
                "unreviewedNodeCount": len(graph["unreviewedNodes"]),
                "officialBoundary": graph["officialBoundary"],
                "knowledgeCollectionIngestion": {
                    "fingerprint": graph_fingerprint,
                    "purpose": "candidate_graph",
                    "inputCandidateIds": [str(item.get("candidateId") or "") for item in candidates],
                    "sourceCollectionRunId": source_collection_run_id,
                },
            },
            "createdByAgent": created_by_agent,
            "currentWorkflowNode": "candidate_graph",
            "currentState": "candidate_graph_visible",
            "qualityStatus": "broken_links" if graph["missingLinks"] else "preview_ready",
            "createdAt": now,
            "updatedAt": now,
        }
        candidate_store.setdefault("candidates", []).append(record)
        candidate_store["updatedAt"] = now
        s._write_json(
            s._candidate_store_path(normalized_team_id, source_collection_run_id),
            candidate_store,
        )
        workflow["updatedAt"] = now
        workflow["activeWorkflowItems"] = s._upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=record["candidateId"],
            current_node=record["currentWorkflowNode"],
            status=record["currentState"],
            transfer_id="",
        )
        s._write_json(s._workflow_path(normalized_team_id), workflow)
    s._record_workflow_event(
        "candidate_graph.built",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "candidateId": record["candidateId"],
            "nodeCount": len(graph["nodes"]),
            "edgeCount": len(graph["edges"]),
            "missingLinkCount": len(graph["missingLinks"]),
            "unreviewedNodeCount": len(graph["unreviewedNodes"]),
            "archivedCandidateCount": len(archived_candidates),
            "filteredCandidateCount": len(filtered_candidates),
            "curationMode": curation_mode,
            "sourceCollectionRunId": source_collection_run_id,
            "createdByAgent": created_by_agent,
            "ingestionFingerprint": graph_fingerprint,
        },
    )
    return {
        "candidateGraph": record,
        "graph": graph,
        "workflow": s._workflow_to_api(normalized_team_id, workflow, candidate_store),
        "reusedCandidateGraph": False,
        "ingestionFingerprint": graph_fingerprint,
    }


def run_knowledge_ingestion_precheck(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Generate a candidate-only steward precheck pack from approved workflow candidates."""
    s = _service()

    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    # 默认必须是团队成员 agentId（而非显示名），否则建库/审核的成员校验会失败。
    steward_agent_id = s._trim_text(payload.get("stewardAgentId"), max_length=160) or s.agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    target_domain = s._trim_text(payload.get("targetDomain"), max_length=240) or "神经机制启发神经网络算法"
    max_candidates = s._normalize_int(payload.get("maxCandidates"), default=32, minimum=1, maximum=200)
    force_rebuild = bool(payload.get("forceRebuild"))
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        candidate_store = s._load_candidate_store(normalized_team_id)
        stored_candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
        active_candidates = [
            item
            for item in stored_candidates
            if str(item.get("candidateType") or "") != "candidate_graph" and not s._candidate_is_archived(item)
        ]
        graph_candidates = [
            item
            for item in stored_candidates
            if str(item.get("candidateType") or "") == "candidate_graph" and not s._candidate_is_archived(item)
        ]
        latest_graph = s._latest_candidate_record(graph_candidates)
        selected_candidates = s._dedupe_candidate_sequence(
            [
                *[item for item in active_candidates if str(item.get("candidateType") or "") != "source_manifest" and s._candidate_ready_for_agent_graph(item)],
                *[item for item in active_candidates if str(item.get("candidateType") or "") == "source_manifest" and s._source_quality_bucket(item) == "approved"],
            ]
        )[:max_candidates]
        workflow_id = str(workflow.get("workflowId") or "")
        filtered_candidate_count = max(0, len(active_candidates) - len(selected_candidates))
        precheck_fingerprint = s._knowledge_collection_fingerprint(
            normalized_team_id,
            selected_candidates,
            purpose="steward_pack",
            target_domain=target_domain,
            steward_agent_id=steward_agent_id,
            candidate_graph_id=str((latest_graph or {}).get("candidateId") or ""),
        )
        if not force_rebuild:
            reusable_pack = s._find_reusable_steward_pack(candidate_store, precheck_fingerprint)
            if reusable_pack is not None:
                status_payload = s.get_knowledge_ingestion_status(normalized_team_id)
                s._record_workflow_event(
                    "knowledge_ingestion.precheck_reused",
                    normalized_team_id,
                    fields={
                        "workflowId": workflow_id,
                        "candidateId": str(reusable_pack.get("candidateId") or ""),
                        "selectedCandidateCount": len(selected_candidates),
                        "filteredCandidateCount": filtered_candidate_count,
                        "stewardAgentId": steward_agent_id,
                        "candidateGraphId": str((latest_graph or {}).get("candidateId") or ""),
                        "ingestionFingerprint": precheck_fingerprint,
                    },
                )
                return {
                    "candidate": reusable_pack,
                    "validation": s.validate_candidate_record(reusable_pack),
                    "precheck": {
                        "status": str(reusable_pack.get("currentState") or "steward_pack_draft"),
                        "generatedByAgent": steward_agent_id,
                        "selectedCandidateCount": len(selected_candidates),
                        "filteredCandidateCount": filtered_candidate_count,
                        "candidateIds": [str(item.get("candidateId") or "") for item in selected_candidates],
                        "candidateGraphId": str((latest_graph or {}).get("candidateId") or ""),
                        "officialBoundary": {
                            "writesOfficialKnowledge": False,
                            "writesOfficialRag": False,
                            "writesOfficialGraph": False,
                            "requiresReviewBeforeOfficialSync": True,
                        },
                    },
                    "status": status_payload,
                    "workflow": s._workflow_to_api(normalized_team_id, workflow, candidate_store),
                    "reusedStewardPack": True,
                    "ingestionFingerprint": precheck_fingerprint,
                }
    if not selected_candidates:
        raise s.TeamWorkflowOrchestrationError("No agent-approved candidates are ready for knowledge ingestion precheck.")

    output = s._build_knowledge_ingestion_precheck_output(
        normalized_team_id,
        workflow_id,
        selected_candidates,
        latest_graph,
        target_domain=target_domain,
    )
    output["knowledgeCollectionIngestion"] = {
        "fingerprint": precheck_fingerprint,
        "purpose": "steward_pack",
        "candidateGraphId": str((latest_graph or {}).get("candidateId") or ""),
    }
    output["agentProcess"] = [
        {
            "eventType": "knowledge_ingestion.precheck_input_selected",
            "stage": "memory_precheck",
            "agentRole": "knowledge_steward",
            "agentId": steward_agent_id,
            "status": "completed",
            "inputSummary": f"{len(selected_candidates)} approved candidates selected",
            "outputSummary": "candidate-only steward precheck package",
            "nextAction": "submit_steward_pack_to_knowledge_ingestion_after_gate",
            "candidateGraphId": str((latest_graph or {}).get("candidateId") or ""),
        }
    ]
    record_response = record_local_research_model_output(
        normalized_team_id,
        {
            "taskType": "steward_pack_draft",
            "title": "资料入库包",
            "summary": f"由 {steward_agent_id} 汇总 {len(selected_candidates)} 条通过资料，生成团队知识库入库包。",
            "createdByAgent": steward_agent_id,
            "output": output,
        },
    )
    status_payload = s.get_knowledge_ingestion_status(normalized_team_id)
    s._record_workflow_event(
        "knowledge_ingestion.precheck_generated",
        normalized_team_id,
        fields={
            "workflowId": workflow_id,
            "candidateId": record_response["candidate"]["candidateId"],
            "selectedCandidateCount": len(selected_candidates),
            "filteredCandidateCount": filtered_candidate_count,
            "stewardAgentId": steward_agent_id,
            "candidateGraphId": str((latest_graph or {}).get("candidateId") or ""),
            "writesOfficialKnowledge": False,
            "writesOfficialRag": False,
            "writesOfficialGraph": False,
        },
    )
    return {
        "candidate": record_response["candidate"],
        "validation": record_response["validation"],
        "precheck": {
            "status": "steward_pack_draft",
            "generatedByAgent": steward_agent_id,
            "selectedCandidateCount": len(selected_candidates),
            "filteredCandidateCount": filtered_candidate_count,
            "candidateIds": [str(item.get("candidateId") or "") for item in selected_candidates],
            "candidateGraphId": str((latest_graph or {}).get("candidateId") or ""),
            "officialBoundary": {
                "writesOfficialKnowledge": False,
                "writesOfficialRag": False,
                "writesOfficialGraph": False,
                "requiresReviewBeforeOfficialSync": True,
            },
        },
        "status": status_payload,
        "workflow": record_response["workflow"],
        "reusedStewardPack": False,
        "ingestionFingerprint": precheck_fingerprint,
    }


def submit_transfer_request(team_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.get_team(normalized_team_id)
    candidate_id = s._normalize_required_id(payload.get("candidateId"), "Candidate id is required.")
    from_node = s._trim_text(payload.get("fromNode"), max_length=120)
    to_node = s._trim_text(payload.get("toNode"), max_length=120)
    if not from_node or not to_node:
        raise s.TeamWorkflowOrchestrationError("fromNode and toNode are required.")
    now = s.utc_now_iso()
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        candidate_store = s._load_candidate_store(normalized_team_id)
        candidate = s._find_candidate(candidate_store, candidate_id)
        if candidate is None:
            raise s.TeamWorkflowOrchestrationError("Candidate not found.")
        transfer = {
            "schemaVersion": s.SCHEMA_VERSION,
            "transferId": s._new_record_id("transfer"),
            "teamId": normalized_team_id,
            "workflowId": workflow["workflowId"],
            "candidateId": candidate_id,
            "fromNode": from_node,
            "toNode": to_node,
            "status": "requested",
            "requiresUserConfirmation": False,
            "requestedByAgent": s._trim_text(payload.get("requestedByAgent"), max_length=160),
            "reason": s._trim_text(payload.get("reason"), max_length=4000),
            "evidenceRefs": s._normalize_ref_list(payload.get("evidenceRefs"), max_items=24),
            "metadata": s._normalize_metadata(payload.get("metadata")),
            "createdAt": now,
            "updatedAt": now,
        }
        s._append_transfer_record(normalized_team_id, transfer)
        candidate["pendingTransferId"] = transfer["transferId"]
        candidate["updatedAt"] = now
        candidate_store["updatedAt"] = now
        s._write_json(s._candidate_store_path(normalized_team_id), candidate_store)
        workflow["updatedAt"] = now
        workflow["activeWorkflowItems"] = s._upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=candidate_id,
            current_node=from_node,
            status="transfer_requested",
            transfer_id=transfer["transferId"],
        )
        s._write_json(s._workflow_path(normalized_team_id), workflow)
    s._record_workflow_event(
        "transfer.requested",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "candidateId": candidate_id,
            "transferId": transfer["transferId"],
            "fromNode": from_node,
            "toNode": to_node,
            "requestedByAgent": transfer["requestedByAgent"],
        },
    )
    return {
        "transfer": transfer,
        "candidate": candidate,
        "workflow": s._workflow_to_api(normalized_team_id, workflow, candidate_store),
    }


def decide_transfer_request(team_id: str, transfer_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_transfer_id = s._normalize_required_id(transfer_id, "Transfer id is required.")
    s.team_service.get_team(normalized_team_id)
    decision = s._trim_text(payload.get("decision"), max_length=32) or "approved"
    if decision not in s.TRANSFER_DECISIONS:
        raise s.TeamWorkflowOrchestrationError("Transfer decision is invalid.")
    decided_by_agent = s._trim_text(payload.get("decidedByAgent"), max_length=160)
    now = s.utc_now_iso()
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        if decided_by_agent != str(workflow.get("ownerAgentId") or s.DEFAULT_OWNER_AGENT_ID):
            raise s.TeamWorkflowOrchestrationError("Only the workflow owner agent can decide transfer requests.")
        candidate_store = s._load_candidate_store(normalized_team_id)
        transfers = s._load_transfer_records(normalized_team_id)
        transfer = s._find_transfer(transfers, normalized_transfer_id)
        if transfer is None:
            raise s.TeamWorkflowOrchestrationError("Transfer request not found.")
        if str(transfer.get("status") or "") != "requested":
            raise s.TeamWorkflowOrchestrationError("Transfer request has already been decided.")
        candidate = s._find_candidate(candidate_store, str(transfer.get("candidateId") or ""))
        if candidate is None:
            raise s.TeamWorkflowOrchestrationError("Candidate not found.")
        transfer.update(
            {
                "status": decision,
                "decisionNote": s._trim_text(payload.get("decisionNote"), max_length=4000),
                "decidedByAgent": decided_by_agent,
                "targetState": s._trim_text(payload.get("targetState"), max_length=120),
                "decisionMetadata": s._normalize_metadata(payload.get("metadata")),
                "decidedAt": now,
                "updatedAt": now,
            }
        )
        target_node = str(transfer.get("toNode") or "").strip()
        current_node = str(transfer.get("fromNode") or "").strip()
        if decision == "approved":
            current_node = target_node
            candidate["currentWorkflowNode"] = target_node
            candidate["currentState"] = s._trim_text(payload.get("targetState"), max_length=120) or "transfer_approved"
            candidate["lastTransferId"] = normalized_transfer_id
            candidate.pop("pendingTransferId", None)
        elif decision == "returned":
            current_node = target_node or current_node
            candidate["currentWorkflowNode"] = current_node
            candidate["currentState"] = s._trim_text(payload.get("targetState"), max_length=120) or "returned_for_rework"
            candidate["qualityStatus"] = "needs_revision"
            candidate["lastTransferId"] = normalized_transfer_id
            candidate.pop("pendingTransferId", None)
        else:
            current_node = "rejection_archive"
            candidate["currentWorkflowNode"] = current_node
            candidate["currentState"] = "rejected"
            candidate["qualityStatus"] = "rejected"
            candidate["lastTransferId"] = normalized_transfer_id
            metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
            metadata["rejectionArchive"] = {
                "status": "archived",
                "transferId": normalized_transfer_id,
                "fromNode": transfer.get("fromNode", ""),
                "toNode": transfer.get("toNode", ""),
                "reason": transfer.get("reason", ""),
                "decisionNote": transfer.get("decisionNote", ""),
                "decidedByAgent": decided_by_agent,
                "archivedAt": now,
                "reopenRequiresTransfer": True,
            }
            candidate["metadata"] = metadata
            candidate.pop("pendingTransferId", None)
        candidate["updatedAt"] = now
        candidate.setdefault("transitionHistory", []).append(
            {
                "transferId": normalized_transfer_id,
                "decision": decision,
                "fromNode": transfer.get("fromNode", ""),
                "toNode": transfer.get("toNode", ""),
                "decidedByAgent": decided_by_agent,
                "decidedAt": now,
                "targetState": candidate["currentState"],
                "metadata": transfer.get("metadata", {}),
            }
        )
        candidate_store["updatedAt"] = now
        s._write_json(s._candidate_store_path(normalized_team_id), candidate_store)
        s._write_transfer_records(normalized_team_id, transfers)
        workflow["updatedAt"] = now
        workflow["activeWorkflowItems"] = s._upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=candidate["candidateId"],
            current_node=current_node,
            status=candidate["currentState"],
            transfer_id="" if decision != "requested" else normalized_transfer_id,
        )
        s._write_json(s._workflow_path(normalized_team_id), workflow)
    s._record_workflow_event(
        "transfer.decided",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "candidateId": candidate["candidateId"],
            "transferId": normalized_transfer_id,
            "decision": decision,
            "decidedByAgent": decided_by_agent,
            "targetState": candidate["currentState"],
            "archiveStatus": "archived" if decision == "rejected" else "",
        },
    )
    return {
        "transfer": transfer,
        "candidate": candidate,
        "workflow": s._workflow_to_api(normalized_team_id, workflow, candidate_store),
    }


def build_local_research_model_task(team_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.get_team(normalized_team_id)
    task_type = s._normalize_local_research_task_type(payload.get("taskType"))
    source_refs = s._normalize_ref_list(payload.get("sourceRefs"), max_items=32)
    evidence_refs = s._normalize_ref_list(payload.get("evidenceRefs"), max_items=32)
    candidate_refs = s._normalize_ref_list(payload.get("candidateRefs"), max_items=24)
    excerpt = s._trim_text(payload.get("excerpt"), max_length=24_000)
    evidence_ledger = s._normalize_local_research_evidence_ledger(payload.get("evidenceLedger"))
    if not (source_refs or evidence_refs or candidate_refs or excerpt or evidence_ledger):
        raise s.TeamWorkflowOrchestrationError(
            "Local research model task requires sourceRefs, evidenceRefs, candidateRefs, excerpt, or evidenceLedger."
        )
    task_spec = s.LOCAL_RESEARCH_TASKS[task_type]
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        candidate_store = s._load_candidate_store(normalized_team_id)
    task = {
        "schemaVersion": s.SCHEMA_VERSION,
        "taskId": s._new_record_id("local-model-task"),
        "teamId": normalized_team_id,
        "workflowId": workflow["workflowId"],
        "workflowKind": workflow["workflowKind"],
        "taskType": task_type,
        "workflowNode": task_spec["workflowNode"],
        "targetCandidateType": task_spec["targetCandidateType"],
        "model": {
            "modelId": s._trim_text(payload.get("modelId"), max_length=160) or s.LOCAL_RESEARCH_MODEL_ID,
            "name": s.LOCAL_RESEARCH_MODEL_NAME,
            "role": s.LOCAL_RESEARCH_MODEL_ROLE,
            "contextWindow": s.LOCAL_RESEARCH_CONTEXT_WINDOW,
            "evidenceTokenTarget": s.LOCAL_RESEARCH_EVIDENCE_TOKEN_TARGET,
        },
        "contextBudget": {
            "schemaAndRules": "10%-15%",
            "taskInstruction": "5%-10%",
            "evidence": "55%-65%",
            "candidateContext": "10%-15%",
            "outputReserve": "10%-15%",
        },
        "sourceRefs": source_refs,
        "evidenceRefs": evidence_refs,
        "candidateRefs": candidate_refs,
        "excerpt": excerpt,
        "evidenceLedger": evidence_ledger,
        "instruction": s._local_research_model_instruction(task_type),
        "outputContract": {
            "format": "json_object",
            "requiredFields": list(task_spec["requiredOutput"]),
            "hardBoundaries": s._local_research_model_boundaries(),
        },
        "candidateStore": {
            "candidateCount": len([item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]),
            "storagePath": s._relative_path(s._candidate_store_path(normalized_team_id)),
        },
        "createdByAgent": s._trim_text(payload.get("createdByAgent"), max_length=160),
        "createdAt": s.utc_now_iso(),
    }
    s._record_workflow_event(
        "local_model.task_built",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "taskId": task["taskId"],
            "taskType": task_type,
            "modelId": task["model"]["modelId"],
        },
    )
    return {"task": task, "workflow": s._workflow_to_api(normalized_team_id, workflow, candidate_store)}


def record_local_research_model_output(team_id: str, payload: dict[str, Any], *, run_id: str = "") -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.get_team(normalized_team_id)
    # Run-scoped callers (stage writeback auto chains) resolve the store
    # through the authority run's owner project; an unresolvable owner keeps
    # the historical active-store target but records an explicit warning
    # instead of drifting silently (SCI-091 incident).
    normalized_run_id = s._resolve_candidate_store_write_run(normalized_team_id, run_id)
    task_type = s._normalize_local_research_task_type(payload.get("taskType"))
    output = payload.get("output")
    if not isinstance(output, dict):
        raise s.TeamWorkflowOrchestrationError("Local research model output must be a JSON object.")
    validation = s.validate_local_research_model_output(task_type, output)
    now = s.utc_now_iso()
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        candidate_store = (
            s._load_candidate_store(normalized_team_id, run_id=normalized_run_id)
            if normalized_run_id
            else s._load_candidate_store(normalized_team_id)
        )
        record = {
            "schemaVersion": s.SCHEMA_VERSION,
            "candidateId": s._new_record_id("local-model-output"),
            "candidateType": str(output.get("candidateType") or s.LOCAL_RESEARCH_TASKS[task_type]["targetCandidateType"]),
            "teamId": normalized_team_id,
            "workflowId": workflow["workflowId"],
            "title": s._trim_text(payload.get("title"), max_length=240) or f"{task_type} draft",
            "sourceKind": "local_research_model_output",
            "summary": s._trim_text(output.get("nextAction") or payload.get("summary"), max_length=4000),
            "sourceRefs": s._normalize_ref_list(output.get("sourceRefs"), max_items=32),
            "evidenceRefs": s._normalize_ref_list(output.get("evidenceRefs"), max_items=32),
            "metadata": {
                "taskType": task_type,
                "modelId": s._trim_text(payload.get("modelId"), max_length=160) or s.LOCAL_RESEARCH_MODEL_ID,
                "validation": validation,
                "output": s._normalize_metadata(output),
            },
            "createdByAgent": s._trim_text(payload.get("createdByAgent"), max_length=160),
            "currentWorkflowNode": s.LOCAL_RESEARCH_TASKS[task_type]["workflowNode"],
            "currentState": s._local_research_output_state(task_type, validation["valid"]),
            "qualityStatus": "prefiltered" if validation["valid"] else "needs_revision",
            "createdAt": now,
            "updatedAt": now,
        }
        candidate_store.setdefault("candidates", []).append(record)
        candidate_store["updatedAt"] = now
        s._write_json(s._candidate_store_path(normalized_team_id, normalized_run_id), candidate_store)
        workflow["updatedAt"] = now
        workflow["activeWorkflowItems"] = s._upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=record["candidateId"],
            current_node=record["currentWorkflowNode"],
            status=record["currentState"],
            transfer_id="",
        )
        s._write_json(s._workflow_path(normalized_team_id), workflow)
    s._record_workflow_event(
        "local_model.output_recorded",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "candidateId": record["candidateId"],
            "taskType": task_type,
            "valid": validation["valid"],
            "issueCount": len(validation["issues"]),
            "sourceCollectionRunId": normalized_run_id,
        },
    )
    response = {
        "candidate": record,
        "validation": validation,
        "workflow": s._workflow_to_api(normalized_team_id, workflow, candidate_store),
    }
    if s._trim_text(run_id, max_length=160):
        # 写入定位证据：owner 解析失败回退活跃店时，返回里带明确 reason。
        response["candidateStoreScope"] = {
            "requestedRunId": s._trim_text(run_id, max_length=160),
            "resolvedRunId": normalized_run_id,
            "resolution": "owner_project" if normalized_run_id else "active_project_owner_unresolved",
        }
    return response


def invoke_local_research_model(team_id: str, payload: dict[str, Any], *, llm_client_factory: Any = None) -> dict[str, Any]:
    s = _service()
    task_response = s.build_local_research_model_task(team_id, payload)
    task = task_response["task"]
    normalized_team_id = str(task["teamId"])
    model_id = str(task["model"]["modelId"] or s.LOCAL_RESEARCH_MODEL_ID)
    messages = s._local_research_model_messages(task)
    metadata = {
        "workflowId": task["workflowId"],
        "taskId": task["taskId"],
        "taskType": task["taskType"],
        "teamId": normalized_team_id,
        "modelId": model_id,
        "surface": "team_workflow_orchestration.local_research_model",
    }
    try:
        client = s._local_research_llm_client(model_id, llm_client_factory=llm_client_factory)
        message = s.invoke_llm(
            client,
            messages,
            context=s.LLMInvocationContext(
                surface="team_workflow_local_research_model",
                run_kind="challenge_cup_local_research",
                run_id=str(task["taskId"]),
                session_id=normalized_team_id,
                agent_id="local_research_model",
                llm_slot="dialogue",
                model_id=model_id,
                cache_scope=s.SOURCE_COLLECTION_PROMPT_CACHE_SCOPE,
                cache_partition=s._source_collection_prompt_cache_partition(
                    normalized_team_id,
                    "local_research_model",
                    model_id=model_id,
                ),
                prompt_purpose=str(task["taskType"] or "local_research"),
                conversation_bound=False,
            ),
            metadata=metadata,
        )
    except Exception as exc:
        s._record_workflow_event(
            "local_model.invoke_failed",
            normalized_team_id,
            fields={
                "workflowId": task["workflowId"],
                "taskId": task["taskId"],
                "taskType": task["taskType"],
                "modelId": model_id,
                "errorType": type(exc).__name__,
            },
        )
        raise s.TeamWorkflowOrchestrationError(f"Local research model invoke failed: {type(exc).__name__}") from exc

    raw_content = s._trim_text(getattr(message, "content", ""), max_length=24_000)
    reasoning_content = ""
    additional_kwargs = getattr(message, "additional_kwargs", {}) or {}
    if isinstance(additional_kwargs, dict):
        reasoning_content = s._trim_text(additional_kwargs.get("reasoning_content"), max_length=24_000)
    parsed_output, parse_source = s._extract_json_object_from_model_text(raw_content, reasoning_content)
    if parsed_output is None:
        s._record_workflow_event(
            "local_model.output_parse_failed",
            normalized_team_id,
            fields={
                "workflowId": task["workflowId"],
                "taskId": task["taskId"],
                "taskType": task["taskType"],
                "modelId": model_id,
                "contentChars": len(raw_content),
                "reasoningChars": len(reasoning_content),
            },
        )
        raise s.TeamWorkflowOrchestrationError("Local research model output did not contain a JSON object.")

    record_response = record_local_research_model_output(
        normalized_team_id,
        {
            "taskType": task["taskType"],
            "modelId": model_id,
            "title": payload.get("title") or f"{task['taskType']} draft",
            "summary": payload.get("summary") or "",
            "output": parsed_output,
            "createdByAgent": payload.get("createdByAgent") or "",
        },
    )
    record_response["task"] = task
    record_response["modelResponse"] = {
        "contentChars": len(raw_content),
        "reasoningChars": len(reasoning_content),
        "jsonSource": parse_source,
        "modelProfileId": s.LOCAL_RESEARCH_INVOKE_PROFILE_ID,
        "modelId": model_id,
    }
    try:
        evidence_response = register_official_model_evidence(
            normalized_team_id,
            {
                "taskType": task["taskType"],
                "workflowNode": task["workflowNode"],
                "candidateId": record_response["candidate"]["candidateId"],
                "taskId": task["taskId"],
                "modelProvider": s._infer_official_model_provider("", model_id),
                "modelId": model_id,
                "modelName": model_id.partition("/")[2] or task["model"]["name"],
                "modelProfileId": s.LOCAL_RESEARCH_INVOKE_PROFILE_ID,
                "evidenceKind": "invocation_log",
                "logRef": "runtime_scene_event:local_model.invoke_recorded",
                "promptSummary": f"{task['taskType']} task with {len(task['sourceRefs'])} sourceRefs, {len(task['evidenceRefs'])} evidenceRefs, {len(task['candidateRefs'])} candidateRefs.",
                "outputSummary": record_response["candidate"].get("summary", ""),
                "sourceRefs": task["sourceRefs"],
                "evidenceRefs": task["evidenceRefs"],
                "recordedByAgent": payload.get("createdByAgent") or "",
                "metadata": {
                    "contentChars": len(raw_content),
                    "reasoningChars": len(reasoning_content),
                    "jsonSource": parse_source,
                    "autoRecordedFromInvoke": True,
                },
            },
        )
        record_response["modelEvidence"] = evidence_response["evidence"]
    except s.TeamWorkflowOrchestrationError as exc:
        record_response["modelEvidence"] = {
            "status": "not_recorded",
            "reason": s._trim_text(str(exc), max_length=500),
        }
    s._record_workflow_event(
        "local_model.invoke_recorded",
        normalized_team_id,
        fields={
            "workflowId": task["workflowId"],
            "taskId": task["taskId"],
            "candidateId": record_response["candidate"]["candidateId"],
            "taskType": task["taskType"],
            "modelId": model_id,
            "valid": record_response["validation"]["valid"],
            "jsonSource": parse_source,
        },
    )
    return record_response


def _steward_pack_local_file_paths(team_id: str, output: dict[str, Any], *, run_id: str = "") -> list[dict[str, Any]]:
    """Collect candidate-local files that can be copied into the central source store."""

    s = _service()
    candidate_ids = s._normalize_text_list(output.get("candidateIds"), max_items=32, max_length=160)
    # Run-scoped submissions read through the owner-project store (merged with
    # the active store as read-compat) so referenced sources stay discoverable.
    candidate_store = (
        s._load_candidate_store(team_id, run_id=run_id)
        if run_id
        else s._load_candidate_store(team_id)
    )
    by_id = {
        str(item.get("candidateId") or ""): item
        for item in list(candidate_store.get("candidates") or [])
        if isinstance(item, dict) and str(item.get("candidateId") or "").strip()
    }
    paths: list[dict[str, Any]] = []
    seen: set[str] = set()
    max_copies = int(getattr(s.team_knowledge_service, "MAX_LOCAL_SOURCE_COPIES", 16) or 16)
    for candidate_id in candidate_ids:
        item = by_id.get(candidate_id)
        if item is None:
            continue
        source_path = s._source_manifest_path(item)
        if not source_path or source_path in seen:
            continue
        seen.add(source_path)
        paths.append(
            {
                "candidateId": candidate_id,
                "path": source_path,
                "title": s._source_manifest_label(item),
            }
        )
        if len(paths) >= max_copies:
            break
    return paths


def submit_steward_pack_to_knowledge_ingestion(team_id: str, candidate_id: str, payload: dict[str, Any], *, run_id: str = "") -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_candidate_id = s._normalize_required_id(candidate_id, "Candidate id is required.")
    s.team_service.get_team(normalized_team_id)
    # Run-scoped auto chains resolve the pack store through the authority
    # run's owner project (unresolvable owners keep the active-store target
    # with an explicit warning); run-less manual submissions keep the
    # historical active-store behavior.
    normalized_run_id = s._resolve_candidate_store_write_run(normalized_team_id, run_id)
    knowledge_base_id = s._trim_text(payload.get("knowledgeBaseId"), max_length=256)
    if not knowledge_base_id:
        raise s.TeamWorkflowOrchestrationError("Knowledge base id is required.")
    proposed_by_agent_id = s._normalize_required_id(payload.get("proposedByAgentId"), "Proposed by Agent id is required.")
    central_source_id = s._trim_text(payload.get("centralSourceId"), max_length=160)

    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        candidate_store = (
            s._load_candidate_store(normalized_team_id, run_id=normalized_run_id)
            if normalized_run_id
            else s._load_candidate_store(normalized_team_id)
        )
        candidate = s._find_candidate(candidate_store, normalized_candidate_id)
        if candidate is None:
            raise s.TeamWorkflowOrchestrationError("Steward pack candidate not found.")
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        task_type = str(metadata.get("taskType") or "")
        output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
        current_state = str(candidate.get("currentState") or "")
        if task_type != "steward_pack_draft" or current_state not in {"steward_pack_draft", "steward_pending_source_review"}:
            raise s.TeamWorkflowOrchestrationError("Only steward_pack_draft or steward_pending_source_review candidates can be submitted to knowledge ingestion.")
        if current_state == "steward_pending_source_review" and not central_source_id:
            raise s.TeamWorkflowOrchestrationError("centralSourceId is required after the steward pack source has entered source review.")
        validation = s.validate_local_research_model_output("steward_pack_draft", output)
        if not validation["valid"]:
            raise s.TeamWorkflowOrchestrationError("Steward pack candidate must be valid before knowledge ingestion submission.")

    ingestion_payload = s._steward_pack_ingestion_payload(
        normalized_team_id,
        candidate,
        output,
        proposed_by_agent_id=proposed_by_agent_id,
    )
    local_file_paths = _steward_pack_local_file_paths(normalized_team_id, output, run_id=normalized_run_id)

    if not central_source_id:
        try:
            inbox_source = s.team_knowledge_service.collect_source_to_inbox(
                "team",
                normalized_team_id,
                source_type="agent_authored",
                source_ref=ingestion_payload["sourceRef"],
                original_content=ingestion_payload["proposalContent"],
                original_filename=f"steward-pack-{s._safe_token(normalized_candidate_id, default='candidate', max_length=72)}.json",
                source_created_at=str(candidate.get("createdAt") or ""),
                captured_by=proposed_by_agent_id,
                evidence_range=ingestion_payload["evidenceRange"],
                title=ingestion_payload["sourceTitle"],
                summary=ingestion_payload["sourceSummary"],
                actor_agent_id=proposed_by_agent_id,
                local_file_paths=local_file_paths,
            )
        except (s.team_knowledge_service.TeamKnowledgeError, s.team_knowledge_service.TeamKnowledgeNotFoundError) as exc:
            raise s.TeamWorkflowOrchestrationError(str(exc)) from exc

        now = s.utc_now_iso()
        with s._WORKFLOW_LOCK:
            workflow = s._load_or_create_workflow(normalized_team_id)
            candidate_store = (
                s._load_candidate_store(normalized_team_id, run_id=normalized_run_id)
                if normalized_run_id
                else s._load_candidate_store(normalized_team_id)
            )
            candidate = s._find_candidate(candidate_store, normalized_candidate_id)
            if candidate is None:
                raise s.TeamWorkflowOrchestrationError("Steward pack candidate not found after source inbox submission.")
            metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
            metadata["knowledgeIngestion"] = {
                "status": "pending_source_review",
                "knowledgeBaseId": knowledge_base_id,
                "inboxSourceId": str(inbox_source.get("inboxSourceId") or ""),
                "centralSourceId": "",
                "sourceArtifactId": "",
                "proposalId": "",
                "ratingSuggestionId": "",
                "submittedByAgentId": proposed_by_agent_id,
                "submittedAt": now,
                "localCopyCount": len(list(inbox_source.get("localCopies") or [])),
                "writesOfficialKnowledge": False,
                "writesOfficialRag": False,
                "writesOfficialGraph": False,
            }
            candidate["metadata"] = metadata
            candidate["currentState"] = "steward_pending_source_review"
            candidate["qualityStatus"] = "pending_source_review"
            candidate["updatedAt"] = now
            candidate_store["updatedAt"] = now
            s._write_json(s._candidate_store_path(normalized_team_id, normalized_run_id), candidate_store)
            workflow["updatedAt"] = now
            workflow["activeWorkflowItems"] = s._upsert_active_item(
                workflow.get("activeWorkflowItems"),
                candidate_id=normalized_candidate_id,
                current_node=str(candidate.get("currentWorkflowNode") or "steward_ingestion"),
                status=str(candidate.get("currentState") or "steward_pending_source_review"),
                transfer_id="",
            )
            s._write_json(s._workflow_path(normalized_team_id), workflow)

        s._record_workflow_event(
            "steward_pack.source_inbox_submitted",
            normalized_team_id,
            fields={
                "workflowId": workflow["workflowId"],
                "candidateId": normalized_candidate_id,
                "knowledgeBaseId": knowledge_base_id,
                "inboxSourceId": str(inbox_source.get("inboxSourceId") or ""),
            },
        )
        return {
            "candidate": candidate,
            "knowledgeIngestion": {
                "status": "pending_source_review",
                "sourceInbox": inbox_source,
                "officialBoundary": {
                    "writesOfficialKnowledge": False,
                    "writesOfficialRag": False,
                    "writesOfficialGraph": False,
                },
            },
            "workflow": s._workflow_to_api(normalized_team_id, workflow, candidate_store),
        }

    try:
        ingestion_package = s.team_knowledge_service.create_ingestion_package(
            knowledge_base_id,
            source_type="agent_authored",
            source_ref=ingestion_payload["sourceRef"],
            source_created_at=str(candidate.get("createdAt") or ""),
            captured_by=proposed_by_agent_id,
            evidence_range=ingestion_payload["evidenceRange"],
            source_title=ingestion_payload["sourceTitle"],
            source_summary=ingestion_payload["sourceSummary"],
            excerpt=ingestion_payload["excerpt"],
            proposed_by_agent_id=proposed_by_agent_id,
            proposal_title=ingestion_payload["proposalTitle"],
            proposal_summary=ingestion_payload["proposalSummary"],
            proposal_content=ingestion_payload["proposalContent"],
            tags=ingestion_payload["tags"],
            central_source_id=central_source_id,
        )
    except (s.team_knowledge_service.TeamKnowledgeError, s.team_knowledge_service.TeamKnowledgeNotFoundError) as exc:
        raise s.TeamWorkflowOrchestrationError(str(exc)) from exc

    rating_result: dict[str, Any] | None = None
    rating_payload = s._steward_pack_rating_suggestion_payload(output, ingestion_package.get("proposal"), proposed_by_agent_id)
    if rating_payload is not None:
        try:
            rating_result = s.team_knowledge_service.create_rating_suggestion(knowledge_base_id, **rating_payload)
        except s.team_knowledge_service.TeamKnowledgeError:
            rating_result = None

    now = s.utc_now_iso()
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        candidate_store = (
            s._load_candidate_store(normalized_team_id, run_id=normalized_run_id)
            if normalized_run_id
            else s._load_candidate_store(normalized_team_id)
        )
        candidate = s._find_candidate(candidate_store, normalized_candidate_id)
        if candidate is None:
            raise s.TeamWorkflowOrchestrationError("Steward pack candidate not found after ingestion submission.")
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        previous_ingestion = metadata.get("knowledgeIngestion") if isinstance(metadata.get("knowledgeIngestion"), dict) else {}
        metadata["knowledgeIngestion"] = {
            "status": "pending_review",
            "knowledgeBaseId": knowledge_base_id,
            "inboxSourceId": str(previous_ingestion.get("inboxSourceId") or ""),
            "centralSourceId": central_source_id,
            "sourceArtifactId": str((ingestion_package.get("sourceArtifact") or {}).get("sourceArtifactId") or ""),
            "proposalId": str((ingestion_package.get("proposal") or {}).get("proposalId") or ""),
            "ratingSuggestionId": str((rating_result or {}).get("suggestionId") or ""),
            "submittedByAgentId": proposed_by_agent_id,
            "submittedAt": now,
            "writesOfficialKnowledge": False,
            "writesOfficialRag": False,
            "writesOfficialGraph": False,
        }
        candidate["metadata"] = metadata
        candidate["currentState"] = "steward_pending_knowledge_review"
        candidate["qualityStatus"] = "pending_knowledge_review"
        candidate["updatedAt"] = now
        candidate_store["updatedAt"] = now
        s._write_json(s._candidate_store_path(normalized_team_id, normalized_run_id), candidate_store)
        workflow["updatedAt"] = now
        workflow["activeWorkflowItems"] = s._upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=normalized_candidate_id,
            current_node=str(candidate.get("currentWorkflowNode") or "steward_ingestion"),
            status=str(candidate.get("currentState") or "steward_pending_knowledge_review"),
            transfer_id="",
        )
        s._write_json(s._workflow_path(normalized_team_id), workflow)

    s._record_workflow_event(
        "steward_pack.knowledge_ingestion_submitted",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "candidateId": normalized_candidate_id,
            "knowledgeBaseId": knowledge_base_id,
            "centralSourceId": central_source_id,
            "proposalId": str((ingestion_package.get("proposal") or {}).get("proposalId") or ""),
            "sourceArtifactId": str((ingestion_package.get("sourceArtifact") or {}).get("sourceArtifactId") or ""),
            "ratingSuggestionCreated": rating_result is not None,
        },
    )
    return {
        "candidate": candidate,
        "knowledgeIngestion": {
            "status": "pending_review",
            "package": ingestion_package,
            "ratingSuggestion": rating_result,
            "officialBoundary": {
                "writesOfficialKnowledge": False,
                "writesOfficialRag": False,
                "writesOfficialGraph": False,
            },
        },
        "workflow": s._workflow_to_api(normalized_team_id, workflow, candidate_store),
    }


def review_steward_pack_knowledge_ingestion(team_id: str, candidate_id: str, payload: dict[str, Any], *, run_id: str = "") -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_candidate_id = s._normalize_required_id(candidate_id, "Candidate id is required.")
    s.team_service.get_team(normalized_team_id)
    # Same run-owner resolution as submit: auto chains must keep pack state
    # updates inside the authority run's owner-project store.
    normalized_run_id = s._resolve_candidate_store_write_run(normalized_team_id, run_id)
    knowledge_base_id = s._trim_text(payload.get("knowledgeBaseId"), max_length=256)
    if not knowledge_base_id:
        raise s.TeamWorkflowOrchestrationError("Knowledge base id is required.")
    reviewed_by_agent_id = s._normalize_required_id(payload.get("reviewedByAgentId"), "Reviewed by Agent id is required.")
    decision = s._normalize_steward_review_decision(payload.get("decision"))
    resolution_note = s._trim_text(payload.get("resolutionNote"), max_length=2000)

    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        candidate_store = (
            s._load_candidate_store(normalized_team_id, run_id=normalized_run_id)
            if normalized_run_id
            else s._load_candidate_store(normalized_team_id)
        )
        candidate = s._find_candidate(candidate_store, normalized_candidate_id)
        if candidate is None:
            raise s.TeamWorkflowOrchestrationError("Steward pack candidate not found.")
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        ingestion = metadata.get("knowledgeIngestion") if isinstance(metadata.get("knowledgeIngestion"), dict) else {}
        if str(candidate.get("currentState") or "") != "steward_pending_knowledge_review":
            raise s.TeamWorkflowOrchestrationError("Only steward_pending_knowledge_review candidates can be reviewed by the ingestion approval gate.")
        if str(ingestion.get("knowledgeBaseId") or "") != knowledge_base_id:
            raise s.TeamWorkflowOrchestrationError("Knowledge base id does not match the steward pack ingestion record.")
        proposal_id = str(ingestion.get("proposalId") or "").strip()
        if not proposal_id:
            raise s.TeamWorkflowOrchestrationError("Steward pack ingestion record is missing proposalId.")
        output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}

    review_status = "applied" if decision == "approved" else "rejected"
    try:
        review_result = s.team_knowledge_service.review_refinement_proposal(
            knowledge_base_id,
            proposal_id,
            status=review_status,
            reviewed_by_agent_id=reviewed_by_agent_id,
            resolution_note=resolution_note,
        )
    except (s.team_knowledge_service.TeamKnowledgeError, s.team_knowledge_service.TeamKnowledgeNotFoundError) as exc:
        raise s.TeamWorkflowOrchestrationError(str(exc)) from exc

    now = s.utc_now_iso()
    item = review_result.get("item") if isinstance(review_result.get("item"), dict) else None
    batch = review_result.get("batch") if isinstance(review_result.get("batch"), dict) else None
    proposal = review_result.get("proposal") if isinstance(review_result.get("proposal"), dict) else {}
    knowledge_item_ids = [str(item.get("knowledgeItemId") or "")] if item else []
    knowledge_item_ids = [item_id for item_id in knowledge_item_ids if item_id]
    batch_id = str((batch or {}).get("batchId") or "")
    official_research_graph = s._official_research_graph_record(
        output,
        knowledge_item_ids=knowledge_item_ids,
        proposal_id=proposal_id,
        batch_id=batch_id,
        knowledge_base_id=knowledge_base_id,
        reviewed_by_agent_id=reviewed_by_agent_id,
        reviewed_at=now,
        decision=decision,
    )
    if decision == "approved" and item and official_research_graph["status"] == "synced":
        try:
            item = s.team_knowledge_service.update_knowledge_item_metadata(
                knowledge_base_id,
                knowledge_item_ids[0],
                metadata_patch={"officialResearchGraph": official_research_graph},
                actor_agent_id=reviewed_by_agent_id,
            )
            review_result["item"] = item
        except (s.team_knowledge_service.TeamKnowledgeError, s.team_knowledge_service.TeamKnowledgeNotFoundError) as exc:
            official_research_graph = {
                **official_research_graph,
                "status": "metadata_update_failed",
                "error": str(exc),
            }
    if decision == "approved":
        rating_migration = s._migrate_steward_pack_rating_suggestion(
            knowledge_base_id,
            source_suggestion_id=str(ingestion.get("ratingSuggestionId") or ""),
            knowledge_item_id=knowledge_item_ids[0] if knowledge_item_ids else "",
            reviewed_by_agent_id=reviewed_by_agent_id,
            resolution_note=resolution_note,
        )
    else:
        rating_migration = {
            "status": "skipped",
            "reason": "decision_not_approved",
            "sourceSuggestionId": str(ingestion.get("ratingSuggestionId") or ""),
            "targetSuggestionId": "",
            "knowledgeItemId": "",
        }
    writes_official_graph = decision == "approved" and str(official_research_graph.get("status") or "") == "synced"
    next_state = "official_synced" if decision == "approved" else "steward_needs_revision"
    quality_status = "approved" if decision == "approved" else "rejected_by_gate"
    official_record = {
        "status": "official_synced" if decision == "approved" else "rejected_by_gate",
        "decision": decision,
        "knowledgeBaseId": knowledge_base_id,
        "proposalId": proposal_id,
        "batchId": batch_id,
        "knowledgeItemIds": knowledge_item_ids,
        "ratingSuggestionId": str(ingestion.get("ratingSuggestionId") or ""),
        "ratingSuggestionMigration": rating_migration,
        "officialResearchGraph": official_research_graph,
        "reviewedByAgentId": reviewed_by_agent_id,
        "reviewedAt": now,
        "resolutionNote": resolution_note,
        "formalKnowledgeItemCreated": decision == "approved" and bool(knowledge_item_ids),
        "writesOfficialKnowledge": decision == "approved",
        "writesOfficialRag": False,
        "writesOfficialGraph": writes_official_graph,
        "ragStatus": "queryable_via_reviewed_team_knowledge" if decision == "approved" else "not_synced",
        "graphStatus": "official_research_trace_synced" if writes_official_graph else ("visible_via_memory_knowledge_graph" if decision == "approved" else "not_synced"),
    }

    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        candidate_store = (
            s._load_candidate_store(normalized_team_id, run_id=normalized_run_id)
            if normalized_run_id
            else s._load_candidate_store(normalized_team_id)
        )
        candidate = s._find_candidate(candidate_store, normalized_candidate_id)
        if candidate is None:
            raise s.TeamWorkflowOrchestrationError("Steward pack candidate not found after approval gate review.")
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        ingestion = metadata.get("knowledgeIngestion") if isinstance(metadata.get("knowledgeIngestion"), dict) else {}
        ingestion.update(
            {
                "status": official_record["status"],
                "decision": decision,
                "proposalStatus": str(proposal.get("status") or ""),
                "batchId": batch_id,
                "knowledgeItemIds": knowledge_item_ids,
                "ratingSuggestionMigration": rating_migration,
                "officialResearchGraph": official_research_graph,
                "reviewedByAgentId": reviewed_by_agent_id,
                "reviewedAt": now,
                "resolutionNote": resolution_note,
                "writesOfficialKnowledge": decision == "approved",
                "writesOfficialRag": False,
                "writesOfficialGraph": writes_official_graph,
            }
        )
        metadata["knowledgeIngestion"] = ingestion
        metadata["officialSyncRecord"] = official_record
        candidate["metadata"] = metadata
        candidate["currentState"] = next_state
        candidate["qualityStatus"] = quality_status
        candidate["updatedAt"] = now
        candidate_store["updatedAt"] = now
        s._write_json(s._candidate_store_path(normalized_team_id, normalized_run_id), candidate_store)
        workflow["updatedAt"] = now
        workflow["activeWorkflowItems"] = s._upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=normalized_candidate_id,
            current_node=str(candidate.get("currentWorkflowNode") or "steward_ingestion"),
            status=str(candidate.get("currentState") or next_state),
            transfer_id="",
        )
        s._write_json(s._workflow_path(normalized_team_id), workflow)

    s._record_workflow_event(
        "steward_pack.knowledge_ingestion_reviewed",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "candidateId": normalized_candidate_id,
            "knowledgeBaseId": knowledge_base_id,
            "proposalId": proposal_id,
            "decision": decision,
            "knowledgeItemCount": len(knowledge_item_ids),
            "ratingSuggestionMigrationStatus": str(rating_migration.get("status") or ""),
            "officialResearchGraphStatus": str(official_research_graph.get("status") or ""),
            "officialResearchGraphEdgeCount": int((official_research_graph.get("summary") or {}).get("edgeCount") or 0),
        },
    )
    return {
        "candidate": candidate,
        "knowledgeIngestion": {
            "status": official_record["status"],
            "decision": decision,
            "review": review_result,
            "officialSyncRecord": official_record,
        },
        "workflow": s._workflow_to_api(normalized_team_id, workflow, candidate_store),
    }


def start_knowledge_collection_completion_background(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Start the phase-card one-click completion path for knowledge collection."""
    s = _service()

    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.get_team(normalized_team_id)
    request_payload = s._knowledge_collection_completion_payload(payload)
    store = s._knowledge_ingestion_work_run_store()
    with s._WORKFLOW_LOCK:
        active_snapshot = store.load_active_snapshot(s.KNOWLEDGE_INGESTION_WORK_RUN_KIND)
        if s._knowledge_ingestion_snapshot_is_active(active_snapshot, normalized_team_id):
            s._record_workflow_event(
                "knowledge_collection.completion_background_already_running",
                normalized_team_id,
                fields={"runId": s._trim_text(active_snapshot.get("runId"), max_length=160)},
            )
            return s._knowledge_ingestion_background_response(normalized_team_id, active_snapshot, already_running=True)
        run_id = s._new_record_id("knowledge-completion")
        initial_steps = [s._knowledge_collection_completion_step("remaining_search", "running")]
        initial_flow = s._knowledge_collection_completion_flow_visualization("running", steps=initial_steps)
        snapshot = s._persist_knowledge_ingestion_work_run(
            normalized_team_id,
            run_id,
            status="running",
            current_phase="running",
            summary="知识搜集一键完成已进入后台执行：搜索→提炼→审查→候选图→入库。",
            active=True,
            completion_steps=initial_steps,
            flow_visualization=initial_flow,
            source_run_id=s._trim_text(request_payload.get("runId") or request_payload.get("sourceRunId"), max_length=160),
        )
    worker = threading.Thread(
        target=s._run_knowledge_collection_completion_background,
        args=(normalized_team_id, run_id, request_payload),
        name=f"knowledge-completion-{run_id[:24]}",
        daemon=True,
    )
    worker.start()
    s._record_workflow_event(
        "knowledge_collection.completion_background_requested",
        normalized_team_id,
        fields={
            "runId": run_id,
            "sourceRunId": s._trim_text(request_payload.get("runId"), max_length=160),
            "threadName": worker.name,
            "sourceQualityAgentId": s._trim_text(request_payload.get("sourceQualityAgentId"), max_length=160),
            "candidateGraphAgentId": s._trim_text(request_payload.get("candidateGraphAgentId"), max_length=160),
            "stewardAgentId": s._trim_text(request_payload.get("stewardAgentId"), max_length=160),
            "maxCandidates": s._normalize_int(request_payload.get("maxCandidates"), default=80, minimum=1, maximum=200),
            "autoApprove": request_payload.get("autoApprove"),
        },
    )
    return s._knowledge_ingestion_background_response(normalized_team_id, snapshot, already_running=False)


def run_knowledge_collection_completion(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the phase-card knowledge collection completion chain.

    The chain continues from the current source collection run when runId is
    provided: remaining search batches, DataRecord extraction, then the existing
    governed ingestion path.
    """
    s = _service()

    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    request_payload = s._knowledge_collection_completion_payload(payload)
    source_run_id = s._trim_text(
        request_payload.get("runId") or request_payload.get("sourceRunId") or request_payload.get("sourceCollectionRunId"),
        max_length=128,
    )
    max_search_batches = s._normalize_int(request_payload.get("maxSearchBatches"), default=20, minimum=0, maximum=100)
    max_queries_per_batch = s._normalize_int(request_payload.get("maxQueriesPerBatch"), default=4, minimum=1, maximum=50)
    max_results_per_query = s._normalize_int(request_payload.get("maxResultsPerQuery"), default=3, minimum=1, maximum=20)
    max_records = s._normalize_int(request_payload.get("maxRecords"), default=500, minimum=1, maximum=1000)
    extraction_agent_id = s._trim_text(request_payload.get("extractionAgentId"), max_length=160) or "Content Extraction Agent"

    search_executions: list[dict[str, Any]] = []
    completion_steps: list[dict[str, Any]] = []
    if source_run_id and max_search_batches > 0:
        try:
            for _index in range(max_search_batches):
                search_result = s.execute_source_collection_search(
                    normalized_team_id,
                    source_run_id,
                    {
                        "maxQueries": max_queries_per_batch,
                        "maxResultsPerQuery": max_results_per_query,
                    },
                )
                search_executions.append(search_result)
                status = s._trim_text(search_result.get("status"), max_length=80).lower()
                summary = search_result.get("summary") if isinstance(search_result.get("summary"), dict) else {}
                open_assignment_count = s._source_collection_count(summary.get("openAssignmentCount"))
                next_query_ids = search_result.get("nextRunnableQueryIds")
                if open_assignment_count <= 0:
                    break
                if isinstance(next_query_ids, list) and not next_query_ids:
                    break
                if status not in {"needs_continue", "running"}:
                    break
        except Exception as exc:
            raise s._attach_knowledge_completion_failure_payload(
                exc,
                team_id=normalized_team_id,
                source_run_id=source_run_id,
                steps=completion_steps,
                failed_stage_id="remaining_search",
            )
        last_search = search_executions[-1] if search_executions else {}
        search_summary = last_search.get("summary") if isinstance(last_search.get("summary"), dict) else {}
        completion_steps.append(
            s._knowledge_collection_completion_step(
                "remaining_search",
                s._trim_text(last_search.get("status"), max_length=120) if last_search else "skipped",
                input_count=len(search_executions),
                output_count=s._source_collection_count(search_summary.get("recordCount")),
            )
        )
    else:
        completion_steps.append(s._knowledge_collection_completion_step("remaining_search", "skipped"))

    extraction: dict[str, Any] | None = None
    if source_run_id:
        try:
            extraction = s.extract_source_collection_candidates(
                normalized_team_id,
                {
                    "runId": source_run_id,
                    "extractionAgentId": extraction_agent_id,
                    "maxRecords": max_records,
                    "force": bool(request_payload.get("forceExtraction", False)),
                    "notes": "One-click knowledge collection completion extracted DataRecords before governed ingestion.",
                },
            )
        except Exception as exc:
            raise s._attach_knowledge_completion_failure_payload(
                exc,
                team_id=normalized_team_id,
                source_run_id=source_run_id,
                steps=completion_steps,
                failed_stage_id="candidate_extraction",
            )
        completion_steps.append(
            s._knowledge_collection_completion_step(
                "candidate_extraction",
                s._trim_text(extraction.get("status"), max_length=120) if extraction else "skipped",
                input_count=s._source_collection_count((extraction or {}).get("importedCount"))
                + s._source_collection_count((extraction or {}).get("skippedCount"))
                + s._source_collection_count((extraction or {}).get("failedCount")),
                output_count=s._source_collection_count((extraction or {}).get("importedCount")),
            )
        )
    else:
        completion_steps.append(s._knowledge_collection_completion_step("candidate_extraction", "skipped"))

    try:
        ingestion = s.run_knowledge_collection_ingestion(normalized_team_id, request_payload)
    except Exception as exc:
        raise s._attach_knowledge_completion_failure_payload(
            exc,
            team_id=normalized_team_id,
            source_run_id=source_run_id,
            steps=completion_steps,
            failed_stage_id="knowledge_ingestion",
        )
    ingestion_summary = ingestion.get("summary") if isinstance(ingestion.get("summary"), dict) else {}
    completion_steps.append(
        s._knowledge_collection_completion_step(
            "knowledge_ingestion",
            s._trim_text(ingestion.get("status"), max_length=120) or "completed",
            input_count=s._source_collection_count(ingestion_summary.get("approvedSourceCandidateCount")),
            output_count=s._source_collection_count(ingestion_summary.get("formalKnowledgeItemCount")),
            artifact_id=s._trim_text(ingestion_summary.get("knowledgeBaseId"), max_length=160),
        )
    )
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": ingestion.get("status") or "completed",
        "sourceRunId": source_run_id,
        "searchExecutions": search_executions,
        "extraction": extraction,
        "ingestion": ingestion,
        "completionSteps": completion_steps,
        "summary": {
            "searchExecutionCount": len(search_executions),
            "extractedCandidateCount": s._source_collection_count((extraction or {}).get("importedCount")),
            "formalKnowledgeItemCount": s._source_collection_count(ingestion_summary.get("formalKnowledgeItemCount")),
            "knowledgeBaseId": s._trim_text(ingestion_summary.get("knowledgeBaseId"), max_length=160),
            "scopedKnowledgeBaseId": s._trim_text(ingestion_summary.get("scopedKnowledgeBaseId"), max_length=256),
        },
    }


def start_knowledge_collection_ingestion_background(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Queue the synchronous knowledge-collection ingestion on a background worker.

    首次入库会现场用真实模型生成 steward pack（耗时分钟级）。后台执行让点击立即返回，
    UI 通过 knowledge-ingestion/status 的 activeWorkRun 轮询进度，避免同步 HTTP 超时。
    """
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.get_team(normalized_team_id)
    request_payload = dict(payload) if isinstance(payload, dict) else {}
    store = s._knowledge_ingestion_work_run_store()
    with s._WORKFLOW_LOCK:
        active_snapshot = store.load_active_snapshot(s.KNOWLEDGE_INGESTION_WORK_RUN_KIND)
        if s._knowledge_ingestion_snapshot_is_active(active_snapshot, normalized_team_id):
            s._record_workflow_event(
                "knowledge_collection.ingestion_background_already_running",
                normalized_team_id,
                fields={"runId": s._trim_text(active_snapshot.get("runId"), max_length=160)},
            )
            return s._knowledge_ingestion_background_response(normalized_team_id, active_snapshot, already_running=True)
        run_id = s._new_record_id("knowledge-ingestion")
        snapshot = s._persist_knowledge_ingestion_work_run(
            normalized_team_id,
            run_id,
            status="running",
            current_phase="running",
            summary="资料入库已进入后台执行：审查→候选图→入库包→提交→审核→正式入库。",
            active=True,
        )
    worker = threading.Thread(
        target=s._run_knowledge_collection_ingestion_background,
        args=(normalized_team_id, run_id, request_payload),
        name=f"knowledge-ingestion-{run_id[:24]}",
        daemon=True,
    )
    worker.start()
    s._record_workflow_event(
        "knowledge_collection.ingestion_background_accepted",
        normalized_team_id,
        fields={"runId": run_id, "threadName": worker.name},
    )
    return s._knowledge_ingestion_background_response(normalized_team_id, snapshot, already_running=False)


def run_knowledge_collection_ingestion(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the four-step knowledge collection gate from screened sources to Team Knowledge.

    The function intentionally reuses the existing source-quality, candidate-graph,
    steward-pack, source-review, and knowledge-review gates instead of writing
    formal Team Knowledge directly.
    """
    s = _service()

    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    team_detail = s.team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    source_agent_ids = s._source_collection_team_agent_ids(team_detail, list(s.SOURCE_COLLECTION_DEFAULT_AGENT_ROLES), payload)
    source_quality_agent_id = (
        s._trim_text(payload.get("sourceExtractorAgentId") or payload.get("sourceQualityAgentId"), max_length=160)
        or source_agent_ids.get("source_extractor")
        or "资料提炼 Agent"
    )
    candidate_graph_agent_id = (
        s._trim_text(payload.get("sourceRelationMapperAgentId") or payload.get("candidateGraphAgentId"), max_length=160)
        or source_agent_ids.get("source_relation_mapper")
        or "资料关系整理 Agent"
    )
    # 默认必须是团队成员 agentId（而非显示名），否则建库/审核的成员校验会失败。
    steward_agent_id = (
        s._trim_text(payload.get("sourceIngestorAgentId") or payload.get("stewardAgentId"), max_length=160)
        or source_agent_ids.get("source_ingestor")
        or s.agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    )
    # 职责分离：steward 提案，由独立的 coordinator/lead 成员审批，避免自提自批。
    reviewer_agent_id = s._trim_text(payload.get("reviewerAgentId"), max_length=160) or s._resolve_team_review_agent_id(
        team_detail, exclude_agent_id=steward_agent_id
    )
    target_domain = s._trim_text(payload.get("targetDomain"), max_length=240) or "神经机制启发神经网络算法"
    max_candidates = s._normalize_int(payload.get("maxCandidates"), default=80, minimum=1, maximum=200)
    force_review = bool(payload.get("forceReview"))
    force_rebuild = bool(payload.get("forceRebuild"))
    auto_create_knowledge_base = bool(payload.get("autoCreateKnowledgeBase", True))
    auto_submit = bool(payload.get("autoSubmit", False))
    auto_review_source = bool(payload.get("autoReviewSource", False))
    auto_approve = bool(payload.get("autoApprove", False))
    notify_steward_agent = bool(payload.get("notifyStewardAgent", True))
    wake_steward_agent = bool(payload.get("wakeStewardAgent", True))
    requester_agent_id = s._trim_text(payload.get("requesterAgentId"), max_length=160) or source_quality_agent_id
    steps: list[dict[str, Any]] = []

    def append_step(
        stage_id: str,
        label: str,
        status: str,
        *,
        input_count: int = 0,
        output_count: int = 0,
        detail: str = "",
        artifact_id: str = "",
    ) -> None:
        steps.append(
            {
                "stageId": stage_id,
                "label": label,
                "status": status,
                "inputCount": input_count,
                "outputCount": output_count,
                "detail": detail,
                "artifactId": artifact_id,
            }
        )

    source_quality = s.assess_source_quality_batch(
        normalized_team_id,
        {
            "assessedByAgent": source_quality_agent_id,
            "maxCandidates": max_candidates,
            "force": force_review,
            "notes": "资料提炼 Agent 执行第一阶段一键入库前的批量提炼和资料审查。",
        },
    )
    source_quality_summary = source_quality.get("sourceQualityStatus", {}).get("summary", {})
    source_candidate_count = int(source_quality_summary.get("sourceCandidateCount") or 0)
    approved_count = int(source_quality_summary.get("approvedSourceCandidateCount") or 0)
    append_step(
        "source_review",
        "资料提炼",
        "completed" if approved_count else str(source_quality.get("status") or "blocked"),
        input_count=source_candidate_count,
        output_count=approved_count,
        detail=f"{source_quality_agent_id} 已完成资料提炼和审查。",
        artifact_id=str(source_quality.get("batchRunId") or ""),
    )
    if approved_count <= 0:
        status_payload = s.get_knowledge_ingestion_status(normalized_team_id)
        s._record_workflow_event(
            "knowledge_collection.ingestion_blocked",
            normalized_team_id,
            fields={
                "reason": "no_approved_sources",
                "sourceCandidateCount": source_candidate_count,
                "sourceQualityAgentId": source_quality_agent_id,
            },
        )
        return {
            "schemaVersion": s.SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "status": "blocked",
            "steps": steps,
            "sourceQuality": source_quality,
            "candidateGraph": None,
            "precheck": None,
            "sourceReview": None,
            "knowledgeSubmission": None,
            "knowledgeReview": None,
            "knowledgeBase": None,
            "statusSnapshot": status_payload,
            "summary": {
                "sourceCandidateCount": source_candidate_count,
                "approvedSourceCandidateCount": approved_count,
                "formalKnowledgeItemCount": status_payload["summary"]["formalKnowledgeItemCount"],
                "nextAction": "补充或重新审查资料后再入库。",
            },
            "workflow": source_quality["workflow"],
        }

    candidate_graph = s.build_candidate_graph(
        normalized_team_id,
        {
            "title": "资料入库候选关系快照",
            "createdByAgent": candidate_graph_agent_id,
            "sourceQualityAgentId": source_quality_agent_id,
            "curationMode": "agent_approved_only",
            "forceRebuild": force_rebuild,
        },
    )
    graph_summary = candidate_graph["graph"]["summary"]
    append_step(
        "candidate_graph",
        "候选关系",
        "completed",
        input_count=int(graph_summary.get("inputCandidateCount") or approved_count),
        output_count=int(graph_summary.get("nodeCount") or 0),
        detail=f"{candidate_graph_agent_id} 已完成候选资料关系整理。",
        artifact_id=str(candidate_graph["candidateGraph"].get("candidateId") or ""),
    )

    precheck = s.run_knowledge_ingestion_precheck(
        normalized_team_id,
        {
            "stewardAgentId": steward_agent_id,
            "targetDomain": target_domain,
            "maxCandidates": max_candidates,
            "forceRebuild": force_rebuild,
        },
    )
    steward_candidate_id = str(precheck["candidate"].get("candidateId") or "")
    append_step(
        "steward_pack",
        "入库审核包",
        "completed",
        input_count=int(precheck["precheck"].get("selectedCandidateCount") or 0),
        output_count=1,
        detail=f"{steward_agent_id} 已生成受治理门禁保护的入库审核包。",
        artifact_id=steward_candidate_id,
    )

    requested_knowledge_base_id = s._trim_text(payload.get("knowledgeBaseId"), max_length=256)
    knowledge_base_id = s._knowledge_base_raw_id(requested_knowledge_base_id)
    scoped_knowledge_base_id = s._knowledge_base_scoped_id_for_team(normalized_team_id, requested_knowledge_base_id)
    knowledge_base: dict[str, Any] | None = None
    if not scoped_knowledge_base_id:
        # 单临界区 get-or-create：先只查不建，维持“有任何 active 库就复用、
        # 无库且允许自动建库才创建”的原语义，同时消除查重与建库之间的锁间隙竞态。
        get_or_create_kwargs = {
            "name": "挑战杯科研知识库",
            "description": "由 ai科学研究团队第一阶段一键入库流程创建。",
            "actor_agent_id": steward_agent_id,
            "reuse_any_existing": True,
        }
        resolved = s.team_knowledge_service.get_or_create_team_knowledge_base(
            normalized_team_id,
            create_if_missing=False,
            **get_or_create_kwargs,
        )
        knowledge_base = resolved["knowledgeBase"]
        if knowledge_base is None and auto_create_knowledge_base:
            try:
                resolved = s.team_knowledge_service.get_or_create_team_knowledge_base(
                    normalized_team_id,
                    **get_or_create_kwargs,
                )
                knowledge_base = resolved["knowledgeBase"]
            except (s.team_knowledge_service.TeamKnowledgeError, s.team_knowledge_service.TeamKnowledgeNotFoundError) as exc:
                raise s.TeamWorkflowOrchestrationError(f"Knowledge base auto-create failed: {exc}") from exc
        if knowledge_base is not None:
            knowledge_base_id = s._knowledge_base_raw_id(knowledge_base.get("knowledgeBaseId"))
            scoped_knowledge_base_id = s._knowledge_base_scoped_id_for_team(
                normalized_team_id,
                knowledge_base_id,
                knowledge_base,
            )
    if not scoped_knowledge_base_id:
        raise s.TeamWorkflowOrchestrationError("Knowledge base id is required before knowledge collection ingestion.")

    # 职责分离下让 coordinator/lead 审批：给该审批人补一条 per-base review 授权，
    # 对新建或既有知识库都生效，避免最终审批关因角色不在 REVIEW_ROLES 而无人可过。
    if auto_approve and reviewer_agent_id:
        try:
            s.team_knowledge_service.ensure_knowledge_base_review_grant(scoped_knowledge_base_id, reviewer_agent_id)
        except (s.team_knowledge_service.TeamKnowledgeError, s.team_knowledge_service.TeamKnowledgeNotFoundError) as exc:
            raise s.TeamWorkflowOrchestrationError(f"Knowledge review grant failed: {exc}") from exc

    source_review: dict[str, Any] | None = None
    knowledge_submission: dict[str, Any] | None = None
    knowledge_review: dict[str, Any] | None = None
    knowledge_steward_activation: dict[str, Any] | None = None
    if auto_submit:
        knowledge_submission = s.submit_steward_pack_to_knowledge_ingestion(
            normalized_team_id,
            steward_candidate_id,
            {
                "knowledgeBaseId": scoped_knowledge_base_id,
                "proposedByAgentId": steward_agent_id,
            },
        )
        inbox_source_id = str(
            ((knowledge_submission.get("candidate") or {}).get("metadata") or {})
            .get("knowledgeIngestion", {})
            .get("inboxSourceId")
            or ""
        )
        append_step(
            "source_gate",
            "来源入库门禁",
            "pending_review" if inbox_source_id else str((knowledge_submission.get("knowledgeIngestion") or {}).get("status") or "submitted"),
            input_count=1,
            output_count=1 if inbox_source_id else 0,
            detail="资料入库包已进入团队来源收件箱。",
            artifact_id=inbox_source_id,
        )
        if auto_review_source and inbox_source_id:
            try:
                source_review = s.team_knowledge_service.review_owner_inbox_source(
                    "team",
                    normalized_team_id,
                    inbox_source_id,
                    decision="accepted",
                    reviewed_by_agent_id=steward_agent_id,
                    resolution_note="一键入库流程由知识治理 Agent 接受资料入库包来源。",
                )
            except (s.team_knowledge_service.TeamKnowledgeError, s.team_knowledge_service.TeamKnowledgeNotFoundError) as exc:
                raise s.TeamWorkflowOrchestrationError(f"Source review failed: {exc}") from exc
            central_source_id = str((source_review.get("centralSource") or {}).get("centralSourceId") or "")
            knowledge_submission = s.submit_steward_pack_to_knowledge_ingestion(
                normalized_team_id,
                steward_candidate_id,
                {
                    "knowledgeBaseId": scoped_knowledge_base_id,
                    "proposedByAgentId": steward_agent_id,
                    "centralSourceId": central_source_id,
                },
            )
            append_step(
                "knowledge_proposal",
                "知识库提案",
                "pending_review",
                input_count=1,
                output_count=1,
                detail="资料入库包已成为知识库待审提案。",
                artifact_id=str(((knowledge_submission.get("knowledgeIngestion") or {}).get("package") or {}).get("proposal", {}).get("proposalId") or ""),
            )
        if (
            auto_approve
            and reviewer_agent_id
            and knowledge_submission
            and str((knowledge_submission.get("knowledgeIngestion") or {}).get("status") or "") == "pending_review"
        ):
            # 职责分离：由 coordinator/lead 审批人（≠ steward 提案人）批准入库。
            knowledge_review = review_steward_pack_knowledge_ingestion(
                normalized_team_id,
                steward_candidate_id,
                {
                    "knowledgeBaseId": scoped_knowledge_base_id,
                    "reviewedByAgentId": reviewer_agent_id,
                    "decision": "approved",
                    "resolutionNote": "一键入库流程通过资料审查、入库关系和知识库门禁后，由团队审批人批准入库。",
                },
            )
            append_step(
                "official_knowledge",
                "正式入库",
                "completed",
                input_count=1,
                output_count=len(
                    ((knowledge_review.get("knowledgeIngestion") or {}).get("officialSyncRecord") or {}).get("knowledgeItemIds")
                    or []
                ),
                detail="正式 KnowledgeItem 已通过现有知识库门禁创建。",
                artifact_id=str((knowledge_review.get("candidate") or {}).get("candidateId") or ""),
            )

    if notify_steward_agent and not knowledge_review:
        knowledge_steward_activation = s._notify_knowledge_steward_for_ingestion(
            normalized_team_id,
            steward_agent_id=steward_agent_id,
            requester_agent_id=requester_agent_id,
            steward_candidate_id=steward_candidate_id,
            knowledge_base_id=knowledge_base_id,
            scoped_knowledge_base_id=scoped_knowledge_base_id,
            target_domain=target_domain,
            wake_target=wake_steward_agent,
        )
        append_step(
            "knowledge_steward_request",
            "通知资料入库 Agent",
            str(knowledge_steward_activation.get("status") or "message_written"),
            input_count=1,
            output_count=1 if knowledge_steward_activation.get("messageId") else 0,
            detail="待入库知识包已发送给资料入库 Agent，等待它执行最终入库。"
            if knowledge_steward_activation.get("messageId")
            else "待入库知识包已生成，但资料入库 Agent 尚未收到消息。",
            artifact_id=str(knowledge_steward_activation.get("messageId") or ""),
        )

    status_payload = s.get_knowledge_ingestion_status(normalized_team_id)
    activation_status = str((knowledge_steward_activation or {}).get("status") or "")
    final_status = (
        "completed"
        if knowledge_review
        else "pending_review"
        if knowledge_submission
        else "agent_notified"
        if activation_status in {"message_written", "agent_wake_started"}
        else "agent_wake_pending"
        if activation_status.startswith("agent_wake_skipped_")
        else "agent_notification_failed"
        if knowledge_steward_activation
        else "precheck_ready"
    )
    s._record_workflow_event(
        "knowledge_collection.ingested",
        normalized_team_id,
        fields={
            "status": final_status,
            "sourceCandidateCount": source_candidate_count,
            "approvedSourceCandidateCount": approved_count,
            "candidateGraphId": str(candidate_graph["candidateGraph"].get("candidateId") or ""),
            "stewardPackCandidateId": steward_candidate_id,
            "knowledgeBaseId": knowledge_base_id,
            "scopedKnowledgeBaseId": scoped_knowledge_base_id,
            "formalKnowledgeItemCount": status_payload["summary"]["formalKnowledgeItemCount"],
            "autoSubmit": auto_submit,
            "autoReviewSource": auto_review_source,
            "autoApprove": auto_approve,
            "notifyStewardAgent": notify_steward_agent,
            "wakeStewardAgent": wake_steward_agent,
            "knowledgeStewardActivationStatus": activation_status,
            "knowledgeStewardInboxMessageId": str((knowledge_steward_activation or {}).get("messageId") or ""),
            "reusedCandidateGraph": bool(candidate_graph.get("reusedCandidateGraph")),
            "reusedStewardPack": bool(precheck.get("reusedStewardPack")),
            "ingestionFingerprint": str(precheck.get("ingestionFingerprint") or candidate_graph.get("ingestionFingerprint") or ""),
        },
        child_log_path=f"artifacts/knowledge-collection-{s._safe_token(normalized_team_id, default='team', max_length=96)}-ingestion.jsonl",
        child_log_payload={
            "kind": "knowledge_collection_ingestion",
            "teamId": normalized_team_id,
            "status": final_status,
            "steps": steps[:24],
            "truncatedStepCount": max(0, len(steps) - 24),
            "sourceCandidateCount": source_candidate_count,
            "approvedSourceCandidateCount": approved_count,
            "candidateGraphId": str(candidate_graph["candidateGraph"].get("candidateId") or ""),
            "candidateGraphNodeCount": int(graph_summary.get("nodeCount") or 0),
            "candidateGraphEdgeCount": int(graph_summary.get("edgeCount") or 0),
            "stewardPackCandidateId": steward_candidate_id,
            "knowledgeBaseId": knowledge_base_id,
            "scopedKnowledgeBaseId": scoped_knowledge_base_id,
            "formalKnowledgeItemCount": status_payload["summary"]["formalKnowledgeItemCount"],
            "autoSubmit": auto_submit,
            "autoReviewSource": auto_review_source,
            "autoApprove": auto_approve,
            "notifyStewardAgent": notify_steward_agent,
            "wakeStewardAgent": wake_steward_agent,
            "knowledgeStewardActivation": s._knowledge_steward_activation_log_payload(knowledge_steward_activation),
            "reusedCandidateGraph": bool(candidate_graph.get("reusedCandidateGraph")),
            "reusedStewardPack": bool(precheck.get("reusedStewardPack")),
            "ingestionFingerprint": str(precheck.get("ingestionFingerprint") or candidate_graph.get("ingestionFingerprint") or ""),
        },
    )
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": final_status,
        "steps": steps,
        "sourceQuality": source_quality,
        "candidateGraph": candidate_graph,
        "precheck": precheck,
        "sourceReview": source_review,
        "knowledgeSubmission": knowledge_submission,
        "knowledgeReview": knowledge_review,
        "knowledgeStewardActivation": knowledge_steward_activation,
        "reusedCandidateGraph": bool(candidate_graph.get("reusedCandidateGraph")),
        "reusedStewardPack": bool(precheck.get("reusedStewardPack")),
        "ingestionFingerprint": str(precheck.get("ingestionFingerprint") or candidate_graph.get("ingestionFingerprint") or ""),
        "knowledgeBase": knowledge_base or {"knowledgeBaseId": knowledge_base_id, "scopedKnowledgeBaseId": scoped_knowledge_base_id},
        "statusSnapshot": status_payload,
        "summary": {
            "sourceCandidateCount": source_candidate_count,
            "approvedSourceCandidateCount": approved_count,
            "candidateGraphNodeCount": int(graph_summary.get("nodeCount") or 0),
            "candidateGraphEdgeCount": int(graph_summary.get("edgeCount") or 0),
            "stewardPackCandidateId": steward_candidate_id,
            "knowledgeBaseId": knowledge_base_id,
            "scopedKnowledgeBaseId": scoped_knowledge_base_id,
            "formalKnowledgeItemCount": status_payload["summary"]["formalKnowledgeItemCount"],
            "knowledgeStewardInboxMessageId": str((knowledge_steward_activation or {}).get("messageId") or ""),
            "knowledgeStewardActivationStatus": activation_status,
            "reusedCandidateGraph": bool(candidate_graph.get("reusedCandidateGraph")),
            "reusedStewardPack": bool(precheck.get("reusedStewardPack")),
            "ingestionFingerprint": str(precheck.get("ingestionFingerprint") or candidate_graph.get("ingestionFingerprint") or ""),
            "nextAction": "进入实验规划" if knowledge_review else ("等待资料入库 Agent 最终入库" if knowledge_steward_activation else "检查入库审核门禁"),
        },
        "workflow": (
            knowledge_review["workflow"]
            if knowledge_review
            else knowledge_submission["workflow"]
            if knowledge_submission
            else precheck["workflow"]
        ),
    }


def validate_local_research_model_output(task_type: str, output: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    normalized_task_type = s._normalize_local_research_task_type(task_type)
    issues: list[dict[str, str]] = []
    required_fields = list(s.LOCAL_RESEARCH_TASKS[normalized_task_type]["requiredOutput"])
    for field in required_fields:
        if field not in output:
            issues.append({"severity": "error", "code": "missing_field", "message": f"Missing required field: {field}"})
    source_refs = output.get("sourceRefs")
    evidence_refs = output.get("evidenceRefs")
    risk_flags = output.get("riskFlags")
    if not isinstance(source_refs, list) or not source_refs:
        issues.append({"severity": "error", "code": "missing_source_refs", "message": "sourceRefs must include at least one source reference."})
    if not isinstance(evidence_refs, list) or not evidence_refs:
        issues.append({"severity": "error", "code": "missing_evidence_refs", "message": "evidenceRefs must include at least one evidence reference."})
    if not isinstance(risk_flags, list):
        issues.append({"severity": "error", "code": "invalid_risk_flags", "message": "riskFlags must be a list."})
    elif not evidence_refs and "weak_evidence" not in [str(item) for item in risk_flags]:
        issues.append({"severity": "error", "code": "weak_evidence_not_flagged", "message": "Missing evidence must be marked as weak_evidence."})
    if normalized_task_type in {"mechanism_mapping", "algorithm_hypothesis_draft"}:
        for field in ("factLayer", "inferenceLayer"):
            if field in required_fields and not s._has_value(output.get(field)):
                issues.append({"severity": "error", "code": "missing_fact_inference_layer", "message": f"{field} is required for analogy control."})
    if normalized_task_type == "algorithm_hypothesis_draft" and not s._has_value(output.get("experimentPlan")):
        issues.append({"severity": "error", "code": "missing_experiment_plan", "message": "algorithm_hypothesis draft requires experimentPlan."})
    if normalized_task_type == "review_prefilter" and "decision" in output:
        issues.append({"severity": "error", "code": "final_decision_not_allowed", "message": "review_prefilter must not write final review.decision."})
    if normalized_task_type == "paper_note_draft":
        issues.extend(s._validate_paper_note_output(output))
    if normalized_task_type == "neuro_mechanism_extract":
        issues.extend(s._validate_neuro_mechanism_output(output))
    if normalized_task_type == "mechanism_mapping":
        issues.extend(s._validate_mechanism_mapping_output(output))
    if normalized_task_type == "algorithm_hypothesis_draft":
        issues.extend(s._validate_algorithm_hypothesis_output(output))
    if normalized_task_type == "review_prefilter":
        issues.extend(s._validate_review_prefilter_output(output))
    if normalized_task_type == "steward_pack_draft":
        issues.extend(s._validate_steward_pack_output(output))
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "taskType": normalized_task_type,
        "valid": not any(item["severity"] == "error" for item in issues),
        "issues": issues,
        "requiredFields": required_fields,
        "hardBoundaries": s._local_research_model_boundaries(),
    }
