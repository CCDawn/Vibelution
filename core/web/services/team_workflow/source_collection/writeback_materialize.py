"""Source-collection stage writeback materialization kernel.

Claim scope: normalize/merge writeback result payloads and materialize
sources / content extraction / quality / candidate graph / knowledge
ingestion side effects after a stage session task writeback.

Public writeback entry remains in ``stages.py``.

Late-bound facade keeps route imports and monkeypatches on
``team_workflow_orchestration_service`` stable.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

from ..source_collection_common import project_source_version_families
from .relation_endpoints import build_relation_endpoint_registry, resolve_relation_endpoint


# finding 阶段写回批次硬上限（finding 闭合化第一步，O5）：滚动写回仍然成立，
# 但每批 candidateLeads[] 有界、每任务总批次有上限；超过即拒绝该批并返回结构化
# 错误，闭合 finding 阶段的开放式检索循环。默认值可用环境变量覆盖。
FINDING_TOTAL_ACCEPTED_LEAD_BUDGET = 8
FINDING_MAX_WRITEBACK_BATCHES_PER_TASK = 4
FINDING_MAX_LEADS_PER_WRITEBACK_BATCH = 4
FINDING_REQUIRED_PERSPECTIVES = (
    "mechanism",
    "independent_baseline",
    "limitation_or_null",
    "falsification",
)
_FINDING_MAX_WRITEBACK_BATCHES_PER_TASK_ENV = "VIBELUTION_FINDING_MAX_WRITEBACK_BATCHES_PER_TASK"
_FINDING_MAX_LEADS_PER_WRITEBACK_BATCH_ENV = "VIBELUTION_FINDING_MAX_LEADS_PER_WRITEBACK_BATCH"


def _finding_writeback_limit_from_env(env_key: str, default: int) -> int:
    raw = str(os.environ.get(env_key) or "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError:
            return default
        if value > 0:
            return value
    return default


def finding_max_writeback_batches_per_task() -> int:
    """Per-task cap on accepted finding writeback batches (env-overridable)."""
    return _finding_writeback_limit_from_env(
        _FINDING_MAX_WRITEBACK_BATCHES_PER_TASK_ENV,
        FINDING_MAX_WRITEBACK_BATCHES_PER_TASK,
    )


def finding_max_leads_per_writeback_batch() -> int:
    """Per-batch cap on candidateLeads[] entries in one finding writeback."""
    return _finding_writeback_limit_from_env(
        _FINDING_MAX_LEADS_PER_WRITEBACK_BATCH_ENV,
        FINDING_MAX_LEADS_PER_WRITEBACK_BATCH,
    )


def finding_resolved_search_envelope() -> dict[str, Any]:
    """Resolve compatibility inputs once when a finding task is created."""
    max_batches = finding_max_writeback_batches_per_task()
    max_leads = finding_max_leads_per_writeback_batch()
    return {
        "schemaVersion": 1,
        "totalAcceptedLeadBudget": FINDING_TOTAL_ACCEPTED_LEAD_BUDGET,
        "maxLeadsPerWriteback": max_leads,
        "maxWritebackBatches": max_batches,
        "effectiveAcceptedLeadLimit": min(
            FINDING_TOTAL_ACCEPTED_LEAD_BUDGET,
            max_batches * max_leads,
        ),
        "requiredPerspectives": list(FINDING_REQUIRED_PERSPECTIVES),
        "authority": "task_creation_resolved",
    }


def _finding_search_envelope_for_task(task: dict[str, Any]) -> dict[str, Any]:
    writeback_contract = (
        task.get("writebackContract")
        if isinstance(task.get("writebackContract"), dict)
        else {}
    )
    frozen = (
        writeback_contract.get("searchEnvelope")
        if isinstance(writeback_contract.get("searchEnvelope"), dict)
        else {}
    )
    if frozen:
        return dict(frozen)
    # Read compatibility inputs only for pre-envelope tasks.
    return finding_resolved_search_envelope()


def _finding_writeback_batch_fingerprints(leads: list[dict[str, Any]]) -> list[str]:
    s = _service()
    return sorted(
        {
            s._source_collection_stage_writeback_lead_fingerprint(lead)
            for lead in leads
            if isinstance(lead, dict)
        }
    )


def _finding_writeback_batch_digest(lead_fingerprints: list[str]) -> str:
    digest_source = json.dumps(lead_fingerprints, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(digest_source.encode("utf-8", errors="replace")).hexdigest()[:24]


def _enforce_source_collection_finding_writeback_batch_limits(
    task: dict[str, Any],
    leads: list[dict[str, Any]],
) -> None:
    """Reject finding writeback batches beyond the per-task / per-batch budget.

    Idempotent by construction: replaying an already-accepted batch (same lead
    fingerprint set) never counts as a new batch, so retried writebacks of the
    same batch stay accepted. The accepted-batch ledger lives on the stage
    session task record and persists with the next task upsert.
    """
    s = _service()
    if not leads:
        return
    stage_id = s._normalize_source_collection_stage_id(task.get("stageId"), default="")
    agent_role = s._normalize_source_collection_agent_role(task.get("agentRole"))
    if stage_id != "finding" and agent_role != "source_finder":
        return
    envelope = _finding_search_envelope_for_task(task)
    max_leads = max(1, int(envelope.get("maxLeadsPerWriteback") or 1))
    if len(leads) > max_leads:
        raise s.TeamWorkflowOrchestrationError(
            f"单批写回 candidateLeads[] 超过上限（{len(leads)} 条 > 每批最多 {max_leads} 条）；"
            "请把本批压缩到上限内写回；检索批次已达上限时，"
            "请立即以现有 searchTrace[] 与 candidateLeads[] 写回收口并结束任务。"
        )
    max_batches = max(1, int(envelope.get("maxWritebackBatches") or 1))
    accepted_lead_limit = max(
        1,
        int(envelope.get("effectiveAcceptedLeadLimit") or 1),
    )
    lead_fingerprints = _finding_writeback_batch_fingerprints(leads)
    batch_fingerprint = _finding_writeback_batch_digest(lead_fingerprints)
    ledger = [
        item
        for item in list(task.get("sourceCollectionWritebackBatches") or [])
        if isinstance(item, dict) and s._trim_text(item.get("batchFingerprint"), max_length=64)
    ]
    if any(s._trim_text(item.get("batchFingerprint"), max_length=64) == batch_fingerprint for item in ledger):
        # 幂等重放：同一批已接受过，不计新批次、不拒绝。
        return
    if len(ledger) >= max_batches:
        raise s.TeamWorkflowOrchestrationError(
            f"检索批次已达上限（本任务最多 {max_batches} 批）；"
            "请立即以现有 searchTrace[] 与 candidateLeads[] 写回收口并结束任务。"
        )
    previously_accepted = {
        s._trim_text(fingerprint, max_length=240)
        for item in ledger
        for fingerprint in list(item.get("leadFingerprints") or [])
        if s._trim_text(fingerprint, max_length=240)
    }
    new_fingerprints = [
        fingerprint
        for fingerprint in lead_fingerprints
        if fingerprint not in previously_accepted
    ]
    if len(previously_accepted) + len(new_fingerprints) > accepted_lead_limit:
        raise s.TeamWorkflowOrchestrationError(
            "检索候选已达任务接受上限"
            f"（最多 {accepted_lead_limit} 条去重来源）；"
            "请立即以现有服务端检索回执与 candidateLeads[] 写回收口并结束任务。"
        )
    task["sourceCollectionWritebackBatches"] = [
        *ledger,
        {
            "batchFingerprint": batch_fingerprint,
            "leadCount": len(leads),
            "leadFingerprints": lead_fingerprints[:80],
            "newAcceptedLeadCount": len(new_fingerprints),
            "recordedAt": s.utc_now_iso(),
        },
    ]


def source_collection_finding_writeback_close_status(
    task: dict[str, Any],
    result: dict[str, Any],
) -> str:
    """Resolve the server-owned terminal status at a frozen finding limit."""

    s = _service()
    stage_id = s._normalize_source_collection_stage_id(task.get("stageId"), default="")
    agent_role = s._normalize_source_collection_agent_role(task.get("agentRole"))
    if stage_id != "finding" and agent_role != "source_finder":
        return ""
    envelope = _finding_search_envelope_for_task(task)
    ledger = [
        item
        for item in list(task.get("sourceCollectionWritebackBatches") or [])
        if isinstance(item, dict)
        and s._trim_text(item.get("batchFingerprint"), max_length=64)
    ]
    accepted_fingerprints = {
        s._trim_text(fingerprint, max_length=240)
        for item in ledger
        for fingerprint in list(item.get("leadFingerprints") or [])
        if s._trim_text(fingerprint, max_length=240)
    }
    accepted_limit = max(1, int(envelope.get("effectiveAcceptedLeadLimit") or 1))
    batch_limit = max(1, int(envelope.get("maxWritebackBatches") or 1))
    if len(accepted_fingerprints) < accepted_limit and len(ledger) < batch_limit:
        return ""
    required_perspectives = {
        s._trim_text(item, max_length=80).lower()
        for item in list(envelope.get("requiredPerspectives") or [])
        if s._trim_text(item, max_length=80)
    }
    observed_perspectives = {
        s._trim_text(item.get("perspective"), max_length=80).lower()
        for item in s._source_collection_stage_writeback_source_leads(result)
        if isinstance(item, dict)
        and s._trim_text(item.get("perspective"), max_length=80)
    }
    return (
        "completed"
        if required_perspectives.issubset(observed_perspectives)
        else "needs_review"
    )


def _service():
    from core.web.services import team_workflow_orchestration_service

    return team_workflow_orchestration_service


def _source_collection_stage_writeback_candidate_id(payload: dict[str, Any]) -> str:
    s = _service()
    return s._trim_text(
        payload.get("candidateId")
        or payload.get("candidate_id")
        or payload.get("sourceCandidateId")
        or payload.get("source_candidate_id")
        or payload.get("id"),
        max_length=160,
    )


def _source_collection_stage_writeback_record_id(payload: dict[str, Any]) -> str:
    s = _service()
    return s._trim_text(
        payload.get("recordId")
        or payload.get("record_id")
        or payload.get("sourceRecordId")
        or payload.get("source_record_id")
        or payload.get("dataRecordId")
        or payload.get("data_record_id")
        or payload.get("sourceDataRecordId")
        or payload.get("id"),
        max_length=160,
    )


def _source_collection_stage_writeback_record_extractions(
    result: dict[str, Any],
    *,
    include_candidate_fallback: bool = True,
) -> list[dict[str, Any]]:
    s = _service()
    extractions: list[dict[str, Any]] = []
    for key in (
        "recordExtractions",
        "record_extractions",
        "dataRecordExtractions",
        "data_record_extractions",
        "sourceRecordExtractions",
        "source_record_extractions",
    ):
        value = result.get(key)
        if isinstance(value, list):
            extractions.extend(item for item in value if isinstance(item, dict))
    for container_key in ("contentExtraction", "content_extraction", "extractionSummary", "outputs", "summary"):
        container = result.get(container_key)
        if not isinstance(container, dict):
            continue
        for key in (
            "recordExtractions",
            "record_extractions",
            "dataRecordExtractions",
            "sourceRecordExtractions",
        ):
            value = container.get(key)
            if isinstance(value, list):
                extractions.extend(item for item in value if isinstance(item, dict))
    if extractions or not include_candidate_fallback:
        return extractions[:300]

    # Backward compatibility for failed historical/agent attempts: when no
    # source_manifest candidates exist yet, some agents wrote raw DataRecord
    # suffixes in candidateExtractions.candidateId. Treat them as record ids
    # only at the record-coverage layer, never as real candidate ids.
    fallback: list[dict[str, Any]] = []
    for item in s._source_collection_stage_writeback_candidate_extractions(result):
        record_id = s._source_collection_stage_writeback_record_id(item) or s._source_collection_stage_writeback_candidate_id(item)
        if not record_id:
            continue
        next_item = dict(item)
        next_item["recordId"] = record_id
        fallback.append(next_item)
    return fallback[:300]


def _source_collection_stage_writeback_candidate_extractions(result: dict[str, Any]) -> list[dict[str, Any]]:
    extractions: list[dict[str, Any]] = []
    for key in (
        "candidateExtractions",
        "candidate_extractions",
        "extractions",
        "candidateFindings",
        "candidate_findings",
        "extractedCandidates",
        "extracted_candidates",
    ):
        value = result.get(key)
        if isinstance(value, list):
            extractions.extend(item for item in value if isinstance(item, dict))
    for container_key in ("contentExtraction", "content_extraction", "extractionSummary", "outputs", "summary"):
        container = result.get(container_key)
        if not isinstance(container, dict):
            continue
        for key in ("candidateExtractions", "candidate_extractions", "extractions", "candidateFindings", "extractedCandidates"):
            value = container.get(key)
            if isinstance(value, list):
                extractions.extend(item for item in value if isinstance(item, dict))
    return extractions[:300]


def _source_collection_stage_writeback_candidate_coverage(
    team_id: str,
    run_id: str,
    task: dict[str, Any],
    writeback: dict[str, Any],
) -> dict[str, Any]:
    s = _service()
    stage_id = s._normalize_source_collection_stage_id(task.get("stageId"), default="")
    agent_role = s._normalize_source_collection_agent_role(task.get("agentRole"))
    result = writeback.get("result") if isinstance(writeback.get("result"), dict) else {}
    source_candidates = s._source_collection_candidates_for_run(team_id, run_id)
    source_candidate_ids = [
        s._trim_text(item.get("candidateId"), max_length=160)
        for item in source_candidates
        if s._trim_text(item.get("candidateId"), max_length=160)
    ]
    records = s._source_collection_stage_records_for_run(run_id)
    try:
        run = s.data_processing_service.get_processing_run(run_id)
        records, _excluded_source_summary = s._source_collection_filter_active_records(team_id, run, records)
    except s.data_processing_service.DataProcessingError:
        pass
    record_ids = [
        s._trim_text(item.get("recordId"), max_length=160)
        for item in records
        if s._trim_text(item.get("recordId"), max_length=160)
    ]
    if stage_id == "extraction" or agent_role == "source_extractor":
        candidate_extraction_entries = s._source_collection_stage_writeback_candidate_extractions(result)
        candidate_decision_entries = s._source_collection_stage_writeback_candidate_decisions(result)
        record_entries = s._source_collection_stage_writeback_record_extractions(
            result,
            include_candidate_fallback=not bool(source_candidate_ids),
        )
        if not source_candidate_ids and (record_entries or not candidate_extraction_entries):
            coverage_kind = "record_extractions"
            processed_ids: list[str] = []
            invalid_ids: list[str] = []
            blocked_ids: list[str] = []
            duplicate_ids: list[str] = []
            alias_warnings: list[dict[str, str]] = []
            seen: set[str] = set()
            for entry in record_entries:
                raw_record_id = s._source_collection_stage_writeback_record_id(entry) or s._source_collection_stage_writeback_candidate_id(entry)
                resolved_record_id, warning = s._resolve_source_collection_record_id(raw_record_id, records)
                if not resolved_record_id:
                    invalid_ids.append(raw_record_id)
                    continue
                if warning:
                    alias_warnings.append({"inputId": raw_record_id, "recordId": resolved_record_id, "warning": warning})
                if resolved_record_id in seen:
                    duplicate_ids.append(resolved_record_id)
                    continue
                seen.add(resolved_record_id)
                processed_ids.append(resolved_record_id)
                entry_status = s._trim_text(
                    entry.get("status")
                    or entry.get("decision")
                    or entry.get("result")
                    or entry.get("bucket"),
                    max_length=80,
                ).lower()
                if entry_status in {"blocked", "needs_more_info", "need_more_info", "needs_fulltext", "missing_source", "needs_revision"}:
                    blocked_ids.append(resolved_record_id)
            missing_ids = [record_id for record_id in record_ids if record_id not in set(processed_ids)]
            invalid_clean = [record_id for record_id in invalid_ids if record_id]
            complete = bool(record_ids) and not missing_ids and not invalid_clean
            if not record_ids:
                complete = True
            return {
                "applicable": True,
                "coverageKind": coverage_kind,
                "total": len(record_ids),
                "processed": len(processed_ids),
                "missing": len(missing_ids),
                "invalid": len(invalid_clean),
                "blocked": len(blocked_ids),
                "duplicate": len(duplicate_ids),
                "complete": complete,
                "processedRecordIds": processed_ids[:120],
                "missingRecordIds": missing_ids[:120],
                "invalidRecordIds": invalid_clean[:80],
                "blockedRecordIds": blocked_ids[:80],
                "duplicateRecordIds": duplicate_ids[:80],
                "recordIdAliasWarnings": alias_warnings[:80],
            }
        if candidate_decision_entries and not candidate_extraction_entries:
            coverage_kind = "candidate_decisions"
            entries = candidate_decision_entries
        else:
            coverage_kind = "candidate_extractions"
            entries = candidate_extraction_entries
    else:
        return {"applicable": False, "coverageKind": ""}

    source_candidate_id_set = set(source_candidate_ids)
    processed_ids: list[str] = []
    invalid_ids: list[str] = []
    blocked_ids: list[str] = []
    duplicate_ids: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        candidate_id = s._source_collection_stage_writeback_candidate_id(entry)
        if not candidate_id:
            invalid_ids.append("")
            continue
        if candidate_id in seen:
            duplicate_ids.append(candidate_id)
            continue
        seen.add(candidate_id)
        if candidate_id not in source_candidate_id_set:
            invalid_ids.append(candidate_id)
            continue
        processed_ids.append(candidate_id)
        entry_status = s._trim_text(
            entry.get("status")
            or entry.get("decision")
            or entry.get("result")
            or entry.get("bucket"),
            max_length=80,
        ).lower()
        if entry_status in {"blocked", "needs_more_info", "need_more_info", "needs_fulltext", "missing_source", "needs_revision"}:
            blocked_ids.append(candidate_id)

    missing_ids = [candidate_id for candidate_id in source_candidate_ids if candidate_id not in set(processed_ids)]
    invalid_clean = [candidate_id for candidate_id in invalid_ids if candidate_id]
    complete = bool(source_candidate_ids) and not missing_ids and not invalid_clean
    if not source_candidate_ids:
        complete = True
    return {
        "applicable": True,
        "coverageKind": coverage_kind,
        "total": len(source_candidate_ids),
        "processed": len(processed_ids),
        "missing": len(missing_ids),
        "invalid": len(invalid_clean),
        "blocked": len(blocked_ids),
        "duplicate": len(duplicate_ids),
        "complete": complete,
        "processedCandidateIds": processed_ids[:120],
        "missingCandidateIds": missing_ids[:120],
        "invalidCandidateIds": invalid_clean[:80],
        "blockedCandidateIds": blocked_ids[:80],
        "duplicateCandidateIds": duplicate_ids[:80],
    }


def _source_collection_stage_writeback_content_extraction_summary(
    *,
    status: str,
    extracted: list[dict[str, Any]] | None = None,
    skipped: list[dict[str, Any]] | None = None,
    failed: list[dict[str, Any]] | None = None,
    evidence_ledgers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    s = _service()
    extracted_items = [item for item in list(extracted or []) if isinstance(item, dict)]
    skipped_items = [item for item in list(skipped or []) if isinstance(item, dict)]
    failed_items = [item for item in list(failed or []) if isinstance(item, dict)]
    summary = {
        "status": status,
        "extractedCandidateCount": len(extracted_items),
        "extractedCandidateIds": [
            s._trim_text(item.get("candidateId"), max_length=160)
            for item in extracted_items
            if s._trim_text(item.get("candidateId"), max_length=160)
        ][:120],
        "skippedCandidateCount": len(skipped_items),
        "failedCandidateCount": len(failed_items),
        "skipped": skipped_items[:24],
        "failed": failed_items[:24],
    }
    if evidence_ledgers is not None:
        ledger_items = [item for item in list(evidence_ledgers or []) if isinstance(item, dict)]
        summary.update(
            {
                "evidenceLedgerCandidateCount": len(ledger_items),
                "evidenceReadyCandidateCount": sum(
                    1 for item in ledger_items if s._trim_text(item.get("evidenceStatus"), max_length=80) == "evidence_ready"
                ),
                "missingEvidenceAnchorCount": sum(
                    1 for item in ledger_items if s._trim_text(item.get("evidenceStatus"), max_length=80) == "missing_evidence_anchor"
                ),
                "evidenceLedgerCandidateIds": [
                    s._trim_text(item.get("candidateId"), max_length=160)
                    for item in ledger_items
                    if s._trim_text(item.get("candidateId"), max_length=160)
                ][:120],
            }
        )
    return summary


def _source_collection_stage_writeback_record_extraction_decision(extraction: dict[str, Any]) -> str:
    s = _service()
    raw = (
        extraction.get("decision")
        or extraction.get("status")
        or extraction.get("result")
        or extraction.get("bucket")
        or extraction.get("outcome")
    )
    return re.sub(r"[^a-z0-9]+", "_", s._trim_text(raw, max_length=120).lower()).strip("_")


def _source_collection_stage_writeback_record_exclusion_reason(extraction: dict[str, Any]) -> str:
    s = _service()
    for key in (
        "excludeReason",
        "exclude_reason",
        "exclusionReason",
        "exclusion_reason",
        "reasonCode",
        "reason_code",
        "invalidReason",
        "invalid_reason",
    ):
        reason = s._normalize_source_collection_exclusion_reason(extraction.get(key))
        if reason:
            return reason
    decision = s._source_collection_stage_writeback_record_extraction_decision(extraction)
    if decision in s.SOURCE_COLLECTION_EXCLUSION_DECISIONS:
        return s._normalize_source_collection_exclusion_reason(decision) or "no_effective_content"
    return ""


def _source_collection_stage_writeback_record_extraction_evidence(extraction: dict[str, Any]) -> list[str]:
    s = _service()
    return s._normalize_text_list(
        extraction.get("evidence")
        or extraction.get("evidenceRefs")
        or extraction.get("evidence_refs")
        or extraction.get("reasons")
        or extraction.get("reason"),
        max_items=8,
        max_length=500,
    )


def _materialize_source_collection_stage_writeback_content_extraction(
    team_id: str,
    run_id: str,
    task: dict[str, Any],
    writeback: dict[str, Any],
) -> dict[str, Any]:
    s = _service()
    stage_id = s._trim_text(task.get("stageId"), max_length=80)
    agent_role = s._trim_text(task.get("agentRole"), max_length=80)
    if stage_id != "extraction" and agent_role != "source_extractor":
        return s._source_collection_stage_writeback_content_extraction_summary(status="skipped_stage")
    status = s._trim_text(writeback.get("status"), max_length=80).lower()
    if status not in s.SOURCE_COLLECTION_STAGE_WRITEBACK_MATERIALIZED_STATUSES:
        return s._source_collection_stage_writeback_content_extraction_summary(status="skipped_status")
    result = writeback.get("result") if isinstance(writeback.get("result"), dict) else {}
    extractions = s._source_collection_stage_writeback_candidate_extractions(result)
    if not extractions:
        return s._source_collection_stage_writeback_content_extraction_summary(status="no_candidate_extractions")

    source_candidate_ids = {
        s._trim_text(item.get("candidateId"), max_length=160)
        for item in s._source_collection_candidates_for_run(team_id, run_id)
        if s._trim_text(item.get("candidateId"), max_length=160)
    }
    task_id = s._trim_text(task.get("taskId"), max_length=160)
    recorded_by_agent = (
        s._trim_text(writeback.get("recordedByAgent"), max_length=160)
        or s._trim_text(task.get("agentId"), max_length=160)
        or "Content Extraction Agent"
    )
    extracted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    evidence_ledgers: list[dict[str, Any]] = []
    seen: set[str] = set()
    now = s.utc_now_iso()
    with s._WORKFLOW_LOCK:
        candidate_store = s._load_candidate_store(team_id, run_id=run_id)
        candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
        candidate_by_id = {
            s._trim_text(item.get("candidateId"), max_length=160): item
            for item in candidates
            if s._trim_text(item.get("candidateId"), max_length=160)
        }
        changed = False
        for extraction in extractions:
            candidate_id = s._source_collection_stage_writeback_candidate_id(extraction)
            if not candidate_id:
                skipped.append({"reason": "missing_candidate_id"})
                continue
            if candidate_id in seen:
                skipped.append({"candidateId": candidate_id, "reason": "duplicate_extraction"})
                continue
            seen.add(candidate_id)
            if candidate_id not in source_candidate_ids:
                skipped.append({"candidateId": candidate_id, "reason": "candidate_not_in_source_collection_run"})
                continue
            candidate = candidate_by_id.get(candidate_id)
            if not candidate:
                skipped.append({"candidateId": candidate_id, "reason": "candidate_not_found"})
                continue
            metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
            normalized_extraction = {
                "status": s._trim_text(extraction.get("status") or "extracted", max_length=80),
                "decision": s._source_collection_stage_writeback_record_extraction_decision(extraction),
                "summary": s._trim_text(
                    extraction.get("summary")
                    or extraction.get("finding")
                    or extraction.get("notes")
                    or extraction.get("reason"),
                    max_length=2000,
                ),
                "keyFindings": s._source_collection_extraction_key_finding_texts(extraction)
                or s._normalize_text_list(
                    extraction.get("keyFindings") or extraction.get("key_findings") or extraction.get("findings"),
                    max_items=12,
                    max_length=240,
                ),
                "riskFlags": s._normalize_text_list(
                    extraction.get("riskFlags") or extraction.get("risk_flags") or extraction.get("risks"),
                    max_items=12,
                    max_length=120,
                ),
                "evidenceRefs": s._normalize_ref_list(
                    extraction.get("evidenceRefs") or extraction.get("evidence_refs") or writeback.get("evidenceRefs"),
                    max_items=24,
                ),
                "taskId": task_id,
                "runId": s._trim_text(run_id, max_length=160),
                "stageId": stage_id,
                "recordedByAgent": recorded_by_agent,
                "recordedAt": now,
            }
            evidence_ledger = s._source_collection_extraction_evidence_ledger(
                extraction,
                fallback_evidence_refs=writeback.get("evidenceRefs"),
            )
            if evidence_ledger:
                normalized_extraction["evidenceLedger"] = evidence_ledger
                normalized_extraction["evidenceStatus"] = evidence_ledger["status"]
                evidence_ledgers.append({"candidateId": candidate_id, "evidenceStatus": evidence_ledger["status"]})
            metadata["contentExtraction"] = normalized_extraction
            candidate["metadata"] = metadata
            candidate["updatedAt"] = now
            extracted.append({"candidateId": candidate_id, "status": normalized_extraction["status"]})
            changed = True
        if changed:
            candidate_store["updatedAt"] = now
            s._write_json(s._candidate_store_path(team_id, run_id), candidate_store)
    summary = s._source_collection_stage_writeback_content_extraction_summary(
        status="completed" if extracted else "no_valid_candidate_extractions",
        extracted=extracted,
        skipped=skipped,
        evidence_ledgers=evidence_ledgers,
    )
    if extracted or skipped:
        s._record_workflow_event(
            "source_collection.stage_session_task_content_extraction_materialized",
            team_id,
            fields={
                "runId": s._trim_text(run_id, max_length=160),
                "taskId": task_id,
                "stageId": stage_id,
                "agentId": s._trim_text(task.get("agentId"), max_length=160),
                "extractedCandidateCount": summary["extractedCandidateCount"],
                "skippedCandidateCount": summary["skippedCandidateCount"],
            },
            level="warning" if skipped and not extracted else "info",
            outcome="failed" if skipped and not extracted else "completed",
            lifecycle=bool(skipped and not extracted),
        )
    return summary


def _materialize_source_collection_stage_writeback_record_extractions(
    team_id: str,
    run_id: str,
    task: dict[str, Any],
    writeback: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    s = _service()
    result = writeback.get("result") if isinstance(writeback.get("result"), dict) else {}
    source_candidates = s._source_collection_candidates_for_run(team_id, run_id)
    try:
        run = s.data_processing_service.get_processing_run(run_id)
    except s.data_processing_service.DataProcessingError:
        run = {"runId": run_id, "scope": {}}
    extractions = s._source_collection_stage_writeback_record_extractions(
        result,
        include_candidate_fallback=not bool(source_candidates),
    )
    if not extractions:
        return s._source_collection_stage_writeback_materialization_summary(status="no_record_extractions")
    record_by_id = {
        s._trim_text(record.get("recordId"), max_length=160): record
        for record in records
        if s._trim_text(record.get("recordId"), max_length=160)
    }
    if not record_by_id:
        return s._source_collection_stage_writeback_materialization_summary(
            status="failed",
            failed=[{"reason": "records_unavailable"}],
        )
    task_id = s._trim_text(task.get("taskId"), max_length=160)
    stage_id = s._trim_text(task.get("stageId"), max_length=80)
    agent_id = s._trim_text(task.get("agentId"), max_length=160)
    agent_role = s._trim_text(task.get("agentRole"), max_length=80)
    recorded_by_agent = s._trim_text(writeback.get("recordedByAgent"), max_length=160) or agent_id or agent_role or "Content Extraction Agent"
    imported_candidates: list[dict[str, Any]] = []
    excluded_sources: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for extraction in extractions:
        raw_record_id = s._source_collection_stage_writeback_record_id(extraction) or s._source_collection_stage_writeback_candidate_id(extraction)
        record_id, warning = s._resolve_source_collection_record_id(raw_record_id, records)
        if not record_id:
            skipped.append({"recordId": raw_record_id, "reason": warning or "record_not_in_source_collection_run"})
            continue
        if record_id in seen:
            skipped.append({"recordId": record_id, "reason": "duplicate_record_extraction"})
            continue
        seen.add(record_id)
        record = record_by_id.get(record_id) or {}
        existing_exclusion = s._source_collection_record_is_excluded(team_id, run, record)
        if existing_exclusion:
            skipped.append(
                {
                    "recordId": record_id,
                    "reason": "source_excluded",
                    "sourceIdentityKey": s._trim_text(existing_exclusion.get("sourceIdentityKey"), max_length=240),
                }
            )
            continue
        extraction_status = s._trim_text(extraction.get("status"), max_length=80).lower()
        if extraction_status in {"blocked", "failed", "tool_failed", "temporarily_unavailable"}:
            skipped.append({"recordId": record_id, "reason": extraction_status or "record_extraction_blocked"})
            continue
        exclusion_reason = s._source_collection_stage_writeback_record_exclusion_reason(extraction)
        has_effective_content = s._source_collection_record_extraction_has_effective_content(extraction, record)
        if exclusion_reason or not has_effective_content:
            normalized_reason = exclusion_reason or "no_effective_content"
            exclusion_entry = s._record_source_collection_exclusion(
                team_id,
                run,
                record,
                reason=normalized_reason,
                evidence=s._source_collection_stage_writeback_record_extraction_evidence(extraction),
                task_id=task_id,
                agent_id=agent_id,
                stage_id=stage_id,
            )
            excluded_sources.append(
                {
                    "recordId": record_id,
                    "title": s._trim_text(record.get("title"), max_length=240),
                    "reason": normalized_reason,
                    "sourceIdentityKey": s._trim_text(exclusion_entry.get("sourceIdentityKey"), max_length=240),
                    "exclusionId": s._trim_text(exclusion_entry.get("exclusionId"), max_length=160),
                    "recordIdAliasWarning": warning,
                }
            )
            continue
        content_extraction = s._source_collection_record_extraction_metadata(
            extraction,
            record_id=record_id,
            task_id=task_id,
            run_id=run_id,
            stage_id=stage_id,
            recorded_by_agent=recorded_by_agent,
        )
        try:
            import_response = s.import_data_record_as_source_candidate(
                team_id,
                run_id,
                record_id,
                {
                    "summary": content_extraction["summary"] or s._trim_text(record.get("summary"), max_length=4000),
                    "createdByAgent": agent_id or agent_role or "source_collection_stage_writeback",
                    "tags": [item for item in ["source_collection", "stage_writeback", agent_role] if item],
                    "metadata": {
                        "sourceCollectionStageWriteback": True,
                        "sourceCollectionStageTaskId": task_id,
                        "sourceCollectionStageId": stage_id,
                        "sourceCollectionStageAgentId": agent_id,
                        "sourceCollectionStageAgentRole": agent_role,
                        "workflowRunId": s._trim_text(task.get("workflowRunId"), max_length=160),
                        "contentExtraction": content_extraction,
                    },
                    "evidenceRefs": content_extraction.get("evidenceRefs"),
                },
            )
        except (s.TeamWorkflowOrchestrationError, s.data_processing_service.DataProcessingError) as exc:
            failed.append({"recordId": record_id, "reason": "candidate_import_failed", "error": str(exc)})
            continue
        candidate = import_response.get("candidate") if isinstance(import_response.get("candidate"), dict) else {}
        candidate_id = s._trim_text(candidate.get("candidateId"), max_length=160)
        if candidate_id:
            s._update_source_candidate_content_extraction(team_id, candidate_id, content_extraction, run_id=run_id)
        imported_candidates.append(
            {
                "candidateId": candidate_id,
                "recordId": record_id,
                "title": s._trim_text(candidate.get("title") or record.get("title"), max_length=240),
                "created": bool(import_response.get("created")),
                "recordIdAliasWarning": warning,
            }
        )
    status = "completed" if imported_candidates else "no_valid_record_extractions"
    summary = s._source_collection_stage_writeback_materialization_summary(
        status=status,
        source_lead_count=len(extractions),
        imported_candidates=imported_candidates,
        excluded_sources=excluded_sources,
        skipped=skipped,
        failed=failed,
    )
    if imported_candidates or excluded_sources or skipped or failed:
        s._record_workflow_event(
            "source_collection.stage_session_task_record_extractions_materialized",
            team_id,
            fields={
                "runId": s._trim_text(run_id, max_length=160),
                "taskId": task_id,
                "stageId": stage_id,
                "agentId": agent_id,
                "recordExtractionCount": len(extractions),
                "importedCandidateCount": summary["importedCandidateCount"],
                "excludedSourceCount": summary["excludedSourceCount"],
                "skippedCount": summary["skippedCount"],
                "failedCount": summary["failedCount"],
            },
            level="warning" if not imported_candidates else "info",
            outcome="failed" if not imported_candidates and not excluded_sources else "completed",
            lifecycle=not bool(imported_candidates or excluded_sources),
        )
    return summary


def _materialize_source_collection_stage_writeback_sources(
    team_id: str,
    run_id: str,
    task: dict[str, Any],
    writeback: dict[str, Any],
    *,
    incoming_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    s = _service()
    status = s._trim_text(writeback.get("status"), max_length=80).lower()
    result = writeback.get("result") if isinstance(writeback.get("result"), dict) else {}
    stage_id = s._normalize_source_collection_stage_id(task.get("stageId"), default="")
    agent_role = s._normalize_source_collection_agent_role(task.get("agentRole"))
    rolling_finding_writeback = bool(
        status == "running"
        and (stage_id == "finding" or agent_role == "source_finder")
    )
    if (
        status not in s.SOURCE_COLLECTION_STAGE_WRITEBACK_MATERIALIZED_STATUSES
        and not rolling_finding_writeback
    ):
        return s._source_collection_stage_writeback_materialization_summary(status="skipped_status")

    records = s._source_collection_stage_records_for_run(run_id)
    record_materialized = s._materialize_source_collection_stage_writeback_record_extractions(
        team_id,
        run_id,
        task,
        writeback,
        records,
    )
    if record_materialized.get("status") != "no_record_extractions":
        return record_materialized

    leads = s._source_collection_stage_writeback_source_leads(result)
    task_id = s._trim_text(task.get("taskId"), max_length=160)
    for lead in leads:
        fingerprint = s._source_collection_stage_writeback_lead_fingerprint(lead)
        lead["fingerprint"] = fingerprint
        lead["leadId"] = "lead-" + hashlib.sha256(
            f"{task_id}|{fingerprint}".encode("utf-8", errors="replace")
        ).hexdigest()[:24]
    # finding 写回批次硬上限（O5）：在物化任何来源前强制，超限即拒绝整批。
    incoming_leads = s._source_collection_stage_writeback_source_leads(
        incoming_result if isinstance(incoming_result, dict) else result
    )
    _enforce_source_collection_finding_writeback_batch_limits(task, incoming_leads)
    invalid_sources = s._source_collection_stage_writeback_invalid_sources(result)
    excluded_sources, invalid_skipped = s._materialize_source_collection_stage_invalid_sources(
        team_id,
        run_id,
        task,
        invalid_sources,
    )
    if not leads:
        if excluded_sources or invalid_skipped:
            return s._source_collection_stage_writeback_materialization_summary(
                status="completed" if excluded_sources else "no_structured_sources",
                excluded_sources=excluded_sources,
                skipped=invalid_skipped,
            )
        return s._source_collection_stage_writeback_materialization_summary(status="no_structured_sources")

    existing_records = records
    existing_identity_records = s._source_collection_existing_identity_records(existing_records)

    created_records: list[dict[str, Any]] = []
    imported_candidates: list[dict[str, Any]] = []
    lineage: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = [*invalid_skipped]
    failed: list[dict[str, Any]] = []
    normalized_team_id = s._trim_text(team_id, max_length=128)
    normalized_run_id = s._trim_text(run_id, max_length=128)
    stage_id = s._trim_text(task.get("stageId"), max_length=80)
    agent_id = s._trim_text(task.get("agentId"), max_length=160)
    agent_role = s._trim_text(task.get("agentRole"), max_length=80)

    for index, lead in enumerate(leads, start=1):
        fingerprint = s._trim_text(lead.get("fingerprint"), max_length=240)
        lead_id = s._trim_text(lead.get("leadId"), max_length=160)
        lineage_entry: dict[str, Any] = {
            "fingerprint": fingerprint,
            "leadId": lead_id,
            "record": {"status": "failed", "recordId": ""},
            "candidate": {"status": "not_attempted", "candidateId": ""},
            "reason": "",
        }
        record_payload = s._source_collection_stage_writeback_record_payload(
            lead,
            team_id=normalized_team_id,
            run_id=normalized_run_id,
            task_id=task_id,
            stage_id=stage_id,
            agent_id=agent_id,
            agent_role=agent_role,
            index=index,
        )
        if not record_payload:
            lineage_entry["reason"] = "insufficient_source_identity"
            lineage.append(lineage_entry)
            skipped.append(
                {
                    "reason": "insufficient_source_identity",
                    "leadId": s._trim_text(lead.get("leadId") or lead.get("id"), max_length=160),
                    "title": s._trim_text(lead.get("title"), max_length=240),
                }
            )
            continue
        source_identity_key = s._source_collection_record_identity_key(record_payload)
        record = existing_identity_records.get(source_identity_key) if source_identity_key else None
        record_reused = record is not None
        if record is None:
            try:
                record = s.data_processing_service.add_record(normalized_run_id, record_payload)
            except s.data_processing_service.DataProcessingError as exc:
                lineage_entry["reason"] = "data_record_create_failed"
                lineage.append(lineage_entry)
                failed.append(
                    {
                        "reason": "data_record_create_failed",
                        "leadId": s._trim_text(lead.get("leadId") or lead.get("id"), max_length=160),
                        "title": s._trim_text(record_payload.get("title"), max_length=240),
                        "error": str(exc),
                    }
                )
                continue
            created_records.append(record)
            if source_identity_key:
                existing_identity_records[source_identity_key] = record
        record_id = s._trim_text(record.get("recordId"), max_length=160)
        lineage_entry["record"] = {
            "status": "reused" if record_reused else "created",
            "recordId": record_id,
            "sourceRef": s._trim_text(
                record.get("sourceRef") or record.get("rawLocation"),
                max_length=2000,
            ),
        }
        try:
            import_response = s.import_data_record_as_source_candidate(
                normalized_team_id,
                normalized_run_id,
                s._trim_text(record.get("recordId"), max_length=160),
                {
                    "createdByAgent": agent_id or agent_role or "source_collection_stage_writeback",
                    "tags": [item for item in ["source_collection", "stage_writeback", agent_role] if item],
                    "metadata": {
                        "sourceCollectionStageWriteback": True,
                        "sourceCollectionStageTaskId": task_id,
                        "sourceCollectionStageId": stage_id,
                        "sourceCollectionStageAgentId": agent_id,
                        "sourceCollectionStageAgentRole": agent_role,
                        "sourceCollectionLeadId": s._trim_text(lead.get("leadId") or lead.get("id"), max_length=160),
                        "workflowRunId": s._trim_text(task.get("workflowRunId"), max_length=160),
                    },
                },
            )
        except s.TeamWorkflowOrchestrationError as exc:
            lineage_entry["candidate"] = {"status": "failed", "candidateId": ""}
            lineage_entry["reason"] = "candidate_import_failed"
            lineage.append(lineage_entry)
            failed.append(
                {
                    "reason": "candidate_import_failed",
                    "recordId": s._trim_text(record.get("recordId"), max_length=160),
                    "error": str(exc),
                }
            )
            continue
        if import_response.get("created"):
            candidate = import_response.get("candidate") if isinstance(import_response.get("candidate"), dict) else {}
            imported_candidates.append(
                {
                    "candidateId": s._trim_text(candidate.get("candidateId"), max_length=160),
                    "recordId": s._trim_text(record.get("recordId"), max_length=160),
                    "title": s._trim_text(candidate.get("title") or record.get("title"), max_length=240),
                }
            )
            lineage_entry["candidate"] = {
                "status": "created",
                "candidateId": s._trim_text(candidate.get("candidateId"), max_length=160),
            }
        else:
            candidate = import_response.get("candidate") if isinstance(import_response.get("candidate"), dict) else {}
            skipped.append(
                {
                    "reason": "duplicate_source_candidate",
                    "recordId": s._trim_text(record.get("recordId"), max_length=160),
                    "candidateId": s._trim_text(candidate.get("candidateId"), max_length=160),
                }
            )
            lineage_entry["candidate"] = {
                "status": "reused",
                "candidateId": s._trim_text(candidate.get("candidateId"), max_length=160),
            }
            lineage_entry["reason"] = "duplicate_source_candidate"
        lineage.append(lineage_entry)

    summary = s._source_collection_stage_writeback_materialization_summary(
        status="completed",
        source_lead_count=len(leads),
        created_records=created_records,
        imported_candidates=imported_candidates,
        excluded_sources=excluded_sources,
        skipped=skipped,
        failed=failed,
        lineage=lineage,
    )
    s._record_workflow_event(
        "source_collection.stage_session_task_sources_materialized",
        normalized_team_id,
        fields={
            "runId": normalized_run_id,
            "taskId": task_id,
            "stageId": stage_id,
            "agentId": agent_id,
            "sourceLeadCount": summary["sourceLeadCount"],
            "createdRecordCount": summary["createdRecordCount"],
            "importedCandidateCount": summary["importedCandidateCount"],
            "excludedSourceCount": summary["excludedSourceCount"],
            "skippedDuplicateCount": summary["skippedDuplicateCount"],
            "failedCount": summary["failedCount"],
        },
        level="warning" if summary["failedCount"] else "info",
        outcome="failed" if summary["failedCount"] and not summary["createdRecordCount"] else "completed",
        lifecycle=bool(summary["failedCount"]),
    )
    return summary


def _materialize_source_collection_stage_writeback_quality(
    team_id: str,
    run_id: str,
    task: dict[str, Any],
    writeback: dict[str, Any],
) -> dict[str, Any]:
    s = _service()
    stage_id = s._normalize_source_collection_stage_id(task.get("stageId"), default="")
    agent_role = s._normalize_source_collection_agent_role(task.get("agentRole"))
    if stage_id != "extraction" and agent_role != "source_extractor":
        return s._source_collection_stage_writeback_quality_summary(status="skipped_stage")
    status = s._trim_text(writeback.get("status"), max_length=80).lower()
    if status not in s.SOURCE_COLLECTION_STAGE_WRITEBACK_MATERIALIZED_STATUSES:
        return s._source_collection_stage_writeback_quality_summary(status="skipped_status")
    result = writeback.get("result") if isinstance(writeback.get("result"), dict) else {}
    decisions = s._source_collection_stage_writeback_candidate_decisions(result)
    if not decisions:
        return s._source_collection_stage_writeback_quality_summary(status="no_candidate_decisions")

    source_candidates, _source_family_summary = project_source_version_families(
        s._source_collection_candidates_for_run(team_id, run_id)
    )
    source_candidate_ids = {
        s._trim_text(item.get("candidateId"), max_length=160)
        for item in source_candidates
        if s._trim_text(item.get("candidateId"), max_length=160)
    }
    superseded_candidate_ids = {
        s._trim_text(item.get("candidateId"), max_length=160)
        for item in source_candidates
        if isinstance(item.get("sourceVersionFamily"), dict)
        and item["sourceVersionFamily"].get("state") == "superseded"
        and s._trim_text(item.get("candidateId"), max_length=160)
    }
    assessed_by_agent = (
        s._trim_text(writeback.get("recordedByAgent"), max_length=160)
        or s._trim_text(task.get("agentId"), max_length=160)
        or "资料提炼 Agent"
    )
    assessed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for decision_payload in decisions:
        candidate_id = s._trim_text(
            decision_payload.get("candidateId")
            or decision_payload.get("candidate_id")
            or decision_payload.get("id"),
            max_length=160,
        )
        if not candidate_id:
            skipped.append({"reason": "missing_candidate_id"})
            continue
        if candidate_id in seen:
            skipped.append({"candidateId": candidate_id, "reason": "duplicate_decision"})
            continue
        seen.add(candidate_id)
        if candidate_id not in source_candidate_ids:
            skipped.append({"candidateId": candidate_id, "reason": "candidate_not_in_source_collection_run"})
            continue
        if candidate_id in superseded_candidate_ids:
            skipped.append({"candidateId": candidate_id, "reason": "superseded_source_version"})
            continue
        normalized_decision = s._source_collection_stage_writeback_quality_decision(decision_payload)
        if not normalized_decision:
            skipped.append({"candidateId": candidate_id, "reason": "unsupported_decision"})
            continue
        assessment_payload = {
            "assessedByAgent": assessed_by_agent,
            "decision": normalized_decision,
            "notes": s._source_collection_stage_writeback_quality_notes(decision_payload, writeback),
            "requiredFixes": s._normalize_text_list(
                decision_payload.get("requiredFixes") or decision_payload.get("required_fixes") or decision_payload.get("fixes"),
                max_items=12,
                max_length=240,
            ),
            "riskFlags": s._normalize_text_list(
                decision_payload.get("riskFlags") or decision_payload.get("risk_flags") or decision_payload.get("risks"),
                max_items=12,
                max_length=120,
            ),
            "evidenceRefs": s._normalize_ref_list(
                decision_payload.get("evidenceRefs") or decision_payload.get("evidence_refs") or writeback.get("evidenceRefs"),
                max_items=24,
            ),
        }
        try:
            response = s.assess_source_candidate_quality(team_id, candidate_id, assessment_payload, run_id=run_id)
        except (s.team_service.TeamServiceError, s.TeamWorkflowOrchestrationError) as exc:
            failed.append({"candidateId": candidate_id, "reason": "assessment_failed", "error": str(exc)})
            continue
        assessment = response.get("assessment") if isinstance(response.get("assessment"), dict) else {}
        assessed.append(
            {
                "candidateId": candidate_id,
                "decision": normalized_decision,
                "assessmentId": s._trim_text(assessment.get("assessmentId"), max_length=160),
            }
        )

    summary = s._source_collection_stage_writeback_quality_summary(
        status="completed" if assessed else ("failed" if failed else "no_assessable_decisions"),
        assessed=assessed,
        skipped=skipped,
        failed=failed,
    )
    s._record_workflow_event(
        "source_collection.stage_session_task_quality_materialized",
        team_id,
        fields={
            "runId": s._trim_text(run_id, max_length=160),
            "taskId": s._trim_text(task.get("taskId"), max_length=160),
            "stageId": stage_id,
            "agentId": s._trim_text(task.get("agentId"), max_length=160),
            "assessedCandidateCount": summary["assessedCandidateCount"],
            "approvedCandidateCount": summary["approvedCandidateCount"],
            "needsRevisionCandidateCount": summary["needsRevisionCandidateCount"],
            "rejectedCandidateCount": summary["rejectedCandidateCount"],
            "skippedCandidateCount": summary["skippedCandidateCount"],
            "failedCandidateCount": summary["failedCandidateCount"],
        },
        level="warning" if summary["failedCandidateCount"] else "info",
        outcome="failed" if summary["failedCandidateCount"] and not summary["assessedCandidateCount"] else "completed",
        lifecycle=bool(summary["failedCandidateCount"]),
    )
    return summary


def _source_collection_stage_writeback_closure_summary(
    task: dict[str, Any],
    writeback: dict[str, Any],
    *,
    coverage_summary: dict[str, Any],
    materialized_sources: dict[str, Any],
    materialized_content_extraction: dict[str, Any],
    materialized_source_quality: dict[str, Any],
    materialized_candidate_graph: dict[str, Any],
    materialized_knowledge_ingestion: dict[str, Any],
    conversation_events_by_session: dict[str, list[Any]] | None = None,
) -> dict[str, Any]:
    s = _service()
    stage_id = s._trim_text(task.get("stageId"), max_length=80)
    agent_role = s._trim_text(task.get("agentRole"), max_length=80)
    task_status = s._trim_text(writeback.get("status"), max_length=80) or s._trim_text(task.get("status"), max_length=80)
    coverage = coverage_summary if isinstance(coverage_summary, dict) and coverage_summary.get("applicable") else {}
    total = s._source_collection_count(coverage.get("total"))
    processed = s._source_collection_count(coverage.get("processed"))
    missing = s._source_collection_count(coverage.get("missing"))
    invalid = s._source_collection_count(coverage.get("invalid"))
    blocked = s._source_collection_count(coverage.get("blocked"))
    complete = bool(coverage.get("complete")) if coverage else False
    invalid_ids = [
        *[str(item) for item in list(coverage.get("invalidRecordIds") or []) if str(item or "")],
        *[str(item) for item in list(coverage.get("invalidCandidateIds") or []) if str(item or "")],
    ][:24]

    success_count = 0
    artifact_status = "no_effect"
    target_label = "阶段产物"
    action_label = "继续处理"
    retry_instruction = "重试时请先读取 source_collection_context_tool 的 compact 上下文，按分页读完后再回写真实 ID。"
    relation_edge_claim_count = 0
    materialized_relation_edge_count = 0
    relation_edges_not_materialized = False
    relation_dangling_edge_count = 0
    excluded_source_count = s._source_collection_count(materialized_sources.get("excludedSourceCount"))
    if stage_id == "finding" or agent_role == "source_finder":
        target_label = "原始资料"
        action_label = "寻找"
        created_count = s._source_collection_count(materialized_sources.get("createdRecordCount"))
        imported_count = s._source_collection_count(materialized_sources.get("importedCandidateCount"))
        duplicate_count = s._source_collection_count(materialized_sources.get("skippedDuplicateCount"))
        success_count = max(created_count, imported_count, duplicate_count)
        artifact_status = "source_records_ready" if success_count else "no_effect"
        retry_instruction = (
            "重试时请调用 source_collection_context_tool(context_mode=compact, record_offset=0, record_limit=5)，"
            "新资料必须用 candidateLeads[] 写回；无效来源写入 invalidSources[]。"
        )
    elif stage_id == "extraction" or agent_role == "source_extractor":
        target_label = "候选资料"
        action_label = "提炼"
        source_count = s._source_collection_count(materialized_sources.get("importedCandidateCount"))
        extraction_count = s._source_collection_count(materialized_content_extraction.get("extractedCandidateCount"))
        quality_count = s._source_collection_count(materialized_source_quality.get("assessedCandidateCount"))
        success_count = max(source_count, extraction_count, quality_count)
        artifact_status = "source_manifest_ready" if success_count else "no_effect"
        retry_instruction = (
            "重试时请调用 source_collection_context_tool(context_mode=compact, record_offset=0, record_limit=5)，"
            "按 recordPage.nextOffset 读完整个批次；没有候选时用 recordExtractions[] 绑定完整 recordId，"
            "不要使用短 ID、remaining_N_candidates 或隐藏候选推断。"
        )
    elif stage_id == "relations" or agent_role == "source_relation_mapper":
        target_label = "候选关系图"
        action_label = "建图"
        success_count = s._source_collection_count(materialized_candidate_graph.get("createdCandidateGraphCount")) or (
            1 if materialized_candidate_graph.get("candidateGraphId") else 0
        )
        agent_graph = s._source_collection_stage_writeback_agent_graph_payload(
            writeback.get("result") if isinstance(writeback.get("result"), dict) else {}
        )
        relation_edge_claim_count = len(s._source_collection_agent_graph_edges(agent_graph))
        materialized_relation_edge_count = s._source_collection_count(materialized_candidate_graph.get("edgeCount"))
        relation_dangling_edge_count = s._source_collection_count(materialized_candidate_graph.get("danglingEdgeCount"))
        relation_edges_not_materialized = relation_edge_claim_count > 0 and materialized_relation_edge_count <= 0
        artifact_status = (
            "candidate_graph_relation_edges_missing"
            if relation_edges_not_materialized
            else "candidate_graph_dangling_edges"
            if relation_dangling_edge_count > 0
            else "candidate_graph_ready"
            if success_count
            else "no_effect"
        )
        if relation_edges_not_materialized:
            retry_instruction = (
                "本轮声称生成了候选关系，但候选图没有物化任何可用边。"
                "请在 Agent 私聊中读取本轮候选图节点，使用节点的 candidateId（不要使用 n1、n2 等展示别名）重新回写关系。"
            )
        elif relation_dangling_edge_count > 0:
            retry_instruction = (
                f"本轮有 {relation_dangling_edge_count} 条候选关系边因端点不在本轮候选图节点表中被丢弃。"
                "请调用 source_collection_context_tool 重读本批候选的完整 candidateId（主题枢纽端点用已声明主题的 source-theme ID），"
                "记不住完整 ID 时可写候选标题或主题 label 作语义端点，服务端会确定性解析；"
                "语义枢纽必须先在同一轮回写的 themeNodes[] 中声明再连边，"
                "不要发明 rh_claim 之类未声明的逻辑端点，重新回写这些关系。"
            )
    elif stage_id == "ingestion" or agent_role == "source_ingestor":
        target_label = "入库审核包"
        action_label = "入库审核"
        success_count = s._source_collection_count(materialized_knowledge_ingestion.get("formalKnowledgeItemCount")) or (
            1 if materialized_knowledge_ingestion.get("stewardPackCandidateId") else 0
        )
        artifact_status = "knowledge_ingestion_ready" if success_count else "no_effect"

    artifact_complete = bool(
        success_count > 0
        and (not coverage or complete)
        and not relation_edges_not_materialized
        and not relation_dangling_edge_count
    )
    if not artifact_complete and excluded_source_count > 0 and (not coverage or complete):
        artifact_complete = True
    evidence_fetch_progress = s._source_collection_evidence_fetch_progress(
        task,
        writeback.get("result") if isinstance(writeback.get("result"), dict) else {},
    )
    if evidence_fetch_progress.get("required") and not evidence_fetch_progress.get("complete"):
        artifact_complete = False
        artifact_status = "evidence_fetch_incomplete"
        retry_instruction = (
            "必须对 remediation scope 中每个候选的既有 DOI/URL 执行 web_fetch_tool，"
            "并用 evidenceFetchAttempts[] 记录 fetched 或带 failureCode 的 failed 结果。"
        )
    task_checklist = [
        item for item in list(task.get("taskChecklist") or [])
        if isinstance(item, dict)
    ]
    task_tool_progress = s._source_collection_stage_task_tool_progress_from_trace(
        task,
        task_checklist,
        artifact_complete=artifact_complete,
        conversation_events_by_session=conversation_events_by_session,
    )
    task_checklist_complete = bool(task_tool_progress.get("complete"))
    completion_gate = s._source_collection_stage_completion_gate(
        task_checklist=task_checklist,
        artifact_complete=artifact_complete,
        task_checklist_complete=task_checklist_complete,
    )

    if relation_edges_not_materialized:
        user_status = "partial"
        message = (
            f"Agent 声称生成了 {relation_edge_claim_count} 条候选关系，但候选图实际物化为 "
            f"{materialized_relation_edge_count} 条；请按真实 candidateId 重新建图。"
        )
    elif relation_dangling_edge_count > 0:
        user_status = "partial"
        message = (
            f"候选关系图已生成，但有 {relation_dangling_edge_count} 条边的端点不在本轮节点表中，"
            "已被丢弃；请按真实 candidateId 补齐这些关系后再推进。"
        )
    elif success_count > 0 and (not coverage or complete) and task_checklist_complete:
        user_status = "success"
        message = f"已生成 {success_count} 个{target_label}，本阶段闭环成功。"
    elif success_count > 0 and (not coverage or complete):
        user_status = "partial"
        message = f"已生成 {success_count} 个{target_label}，等待 Agent 完成检查清单打勾。"
    elif success_count > 0:
        user_status = "partial"
        message = f"已{action_label} {processed}/{total}，已生成 {success_count} 个{target_label}；还有 {missing} 条待补，{invalid} 个 ID 未匹配。"
    elif excluded_source_count > 0 and (not coverage or complete) and task_checklist_complete:
        user_status = "success"
        artifact_status = "source_manifest_filtered"
        message = f"已移出 {excluded_source_count} 条无有效内容来源，未生成候选资料；需要继续搜索或补充新来源。"
    elif excluded_source_count > 0 and (not coverage or complete):
        user_status = "partial"
        artifact_status = "source_manifest_filtered"
        message = f"已移出 {excluded_source_count} 条无有效内容来源，等待 Agent 完成检查清单打勾。"
    elif task_status in {"interrupted", "stopped"}:
        user_status = "interrupted"
        artifact_status = "interrupted_before_writeback"
        message = f"Agent 私聊已中断，尚未完成阶段写回，因此还没有生成{target_label}。请继续这次任务或重新启动本阶段。"
        retry_instruction = (
            "继续时请先查看上一轮已完成的 checklist 和分页读取结果，只补未完成的写回步骤；"
            "如果无法继续，请调用 source_collection_stage_writeback_tool 写入 blocked/failed 和原因。"
        )
    elif coverage and total > 0:
        user_status = "failed"
        message = f"Agent 已回写，但没有生成{target_label}；已{action_label} {processed}/{total}，{missing} 条待补，{invalid} 个 ID 未匹配。"
    elif task_status in {"blocked", "failed"}:
        user_status = "failed"
        message = f"Agent 任务未完成，尚未生成{target_label}。推进结果：失败（不合格）。"
        if stage_id == "ingestion" or agent_role == "source_ingestor":
            retry_instruction = (
                "系统判定本轮入库未产生正式知识/入库包。"
                "不要用 status=blocked 当作结束：请用 completed 或 needs_review，"
                "并在 result 中写入通过候选与入库决策；若关系图缺边请先完成整理关系再重试。"
                "写回必须带 team_id 与 task_id。"
            )
        else:
            retry_instruction = (
                "系统判定本轮阶段未产生可用产物。请用 completed/needs_review 回写真实结果；"
                "不要用 blocked 代替未完成的工作。写回必须带 team_id 与 task_id。"
            )
    else:
        user_status = "failed" if artifact_status == "no_effect" else "partial"
        message = (
            f"Agent 已回写，但没有生成可用{target_label}。推进结果：失败（不合格）。"
            if artifact_status == "no_effect"
            else f"Agent 已回写，但{target_label}仍不完整。"
        )
        if artifact_status == "no_effect" and (stage_id == "ingestion" or agent_role == "source_ingestor"):
            retry_instruction = (
                "本轮 writeback 没有物化正式知识。请重新打开入库任务，"
                "以 completed/needs_review 写回入库决策与通过候选；关系图未就绪时先修关系阶段。"
            )

    return {
        "schemaVersion": 1,
        "stageId": stage_id,
        "agentRole": agent_role,
        "agentTurnStatus": task_status,
        "artifactStatus": artifact_status,
        "userStatus": user_status,
        "targetLabel": target_label,
        "message": message,
        "artifactComplete": artifact_complete,
        "taskChecklistComplete": task_checklist_complete,
        "completionGatePassed": bool(completion_gate.get("passed")),
        "completionGate": completion_gate,
        "taskToolProgress": task_tool_progress,
        "evidenceFetchProgress": evidence_fetch_progress,
        "progressLabel": f"{action_label} {processed}/{total}" if coverage and total else "",
        "successCount": success_count,
        "excludedSourceCount": excluded_source_count,
        "failedCount": missing + invalid,
        "blockedCount": blocked,
        "coverageSummary": s._normalize_metadata(coverage),
        "invalidIds": invalid_ids,
        "retryInstruction": retry_instruction,
        "nextAction": retry_instruction,
        "advanceOutcome": "failed" if user_status in {"failed", "interrupted"} and not artifact_complete else (
            "succeeded" if user_status == "success" and artifact_complete else "partial"
        ),
    }


def _materialize_source_collection_stage_writeback_candidate_graph(
    team_id: str,
    run_id: str,
    task: dict[str, Any],
    writeback: dict[str, Any],
) -> dict[str, Any]:
    s = _service()
    stage_id = s._normalize_source_collection_stage_id(task.get("stageId"), default="")
    agent_role = s._normalize_source_collection_agent_role(task.get("agentRole"))
    if stage_id != "relations" and agent_role != "source_relation_mapper":
        return s._source_collection_stage_writeback_candidate_graph_summary(status="skipped_stage")
    status = s._trim_text(writeback.get("status"), max_length=80).lower()
    if status not in s.SOURCE_COLLECTION_STAGE_WRITEBACK_MATERIALIZED_STATUSES:
        return s._source_collection_stage_writeback_candidate_graph_summary(status="skipped_status")
    result = writeback.get("result") if isinstance(writeback.get("result"), dict) else {}
    agent_graph = s._source_collection_stage_writeback_agent_graph_payload(result)
    created_by_agent = (
        s._trim_text(writeback.get("recordedByAgent"), max_length=160)
        or s._trim_text(task.get("agentId"), max_length=160)
        or "Source Relation Mapper Agent"
    )
    try:
        graph_response = s.build_candidate_graph(
            team_id,
            {
                "createdByAgent": created_by_agent,
                "sourceCollectionRunId": run_id,
                "title": s._trim_text(writeback.get("summary"), max_length=240) or "Source collection candidate graph",
            },
        )
    except (s.team_service.TeamServiceError, s.TeamWorkflowOrchestrationError) as exc:
        summary = s._source_collection_stage_writeback_candidate_graph_summary(
            status="failed",
            failed=[{"reason": "candidate_graph_build_failed", "error": str(exc)}],
        )
        s._record_workflow_event(
            "source_collection.stage_session_task_candidate_graph_materialized",
            team_id,
            fields={
                "runId": s._trim_text(run_id, max_length=160),
                "taskId": s._trim_text(task.get("taskId"), max_length=160),
                "stageId": stage_id,
                "agentId": s._trim_text(task.get("agentId"), max_length=160),
                "failedCount": summary["failedCandidateGraphCount"],
            },
            level="warning",
            outcome="failed",
            lifecycle=True,
        )
        return summary

    candidate_graph = graph_response.get("candidateGraph") if isinstance(graph_response.get("candidateGraph"), dict) else {}
    graph = graph_response.get("graph") if isinstance(graph_response.get("graph"), dict) else {}
    if agent_graph:
        graph_response = dict(graph_response)
        graph = s._merge_source_collection_stage_writeback_agent_graph(graph, agent_graph)
        graph_response["graph"] = graph
    graph_summary = graph.get("summary") if isinstance(graph.get("summary"), dict) else {}
    candidate_graph_id = s._trim_text(candidate_graph.get("candidateId"), max_length=160)
    if candidate_graph_id:
        task_for_metadata = dict(task)
        task_for_metadata["stageId"] = stage_id
        task_for_metadata["agentRole"] = agent_role
        s._attach_candidate_graph_stage_writeback_metadata(
            team_id,
            candidate_graph_id,
            task=task_for_metadata,
            writeback=writeback,
            graph_response=graph_response,
            agent_graph=agent_graph,
            run_id=run_id,
        )
    materialized = {
        "candidateGraphId": candidate_graph_id,
        "nodeCount": s._source_collection_count(graph_summary.get("nodeCount")),
        "edgeCount": s._source_collection_count(graph_summary.get("edgeCount")),
        "missingLinkCount": s._source_collection_count(graph_summary.get("missingLinkCount")),
        "danglingEdgeCount": s._source_collection_count(graph_summary.get("danglingEdgeCount")),
        "semanticBindingEdgeCount": s._source_collection_count(graph_summary.get("semanticBindingEdgeCount")),
        "unreviewedNodeCount": s._source_collection_count(graph_summary.get("unreviewedNodeCount")),
        "inputCandidateCount": s._source_collection_count(graph_summary.get("inputCandidateCount")),
        "filteredCandidateCount": s._source_collection_count(graph_summary.get("filteredCandidateCount")),
        "reusedCandidateGraph": bool(graph_response.get("reusedCandidateGraph")),
        "ingestionFingerprint": s._trim_text(graph_response.get("ingestionFingerprint"), max_length=160),
    }
    summary = s._source_collection_stage_writeback_candidate_graph_summary(
        status="completed" if candidate_graph_id else "failed",
        candidate_graph=materialized,
        failed=[] if candidate_graph_id else [{"reason": "candidate_graph_missing_id"}],
    )
    s._record_workflow_event(
        "source_collection.stage_session_task_candidate_graph_materialized",
        team_id,
        fields={
            "runId": s._trim_text(run_id, max_length=160),
            "taskId": s._trim_text(task.get("taskId"), max_length=160),
            "stageId": stage_id,
            "agentId": s._trim_text(task.get("agentId"), max_length=160),
            "candidateGraphId": candidate_graph_id,
            "nodeCount": summary["nodeCount"],
            "edgeCount": summary["edgeCount"],
            "createdCandidateGraphCount": summary["createdCandidateGraphCount"],
            "reusedCandidateGraph": summary["reusedCandidateGraph"],
            "failedCount": summary["failedCandidateGraphCount"],
        },
        level="warning" if summary["failedCandidateGraphCount"] else "info",
        outcome="failed" if summary["failedCandidateGraphCount"] else "completed",
        lifecycle=bool(summary["failedCandidateGraphCount"]),
    )
    return summary


def _materialize_source_collection_stage_writeback_knowledge_ingestion(
    team_id: str,
    run_id: str,
    task: dict[str, Any],
    writeback: dict[str, Any],
) -> dict[str, Any]:
    s = _service()
    stage_id = s._normalize_source_collection_stage_id(task.get("stageId"), default="")
    agent_role = s._normalize_source_collection_agent_role(task.get("agentRole"))
    if not s._source_collection_stage_can_materialize_formal_knowledge(stage_id, agent_role):
        return s._source_collection_stage_writeback_knowledge_ingestion_summary(status="skipped_stage")
    status = s._trim_text(writeback.get("status"), max_length=80).lower()
    if status not in s.SOURCE_COLLECTION_STAGE_WRITEBACK_MATERIALIZED_STATUSES:
        return s._source_collection_stage_writeback_knowledge_ingestion_summary(status="skipped_status")
    previous_writeback = task.get("writeback") if isinstance(task.get("writeback"), dict) else {}
    previous_materialized = previous_writeback.get("materializedKnowledgeIngestion") if isinstance(previous_writeback.get("materializedKnowledgeIngestion"), dict) else {}
    if str(previous_materialized.get("status") or "") == "completed" and previous_materialized.get("stewardPackCandidateId"):
        reused_materialized = dict(previous_materialized)
        reused_materialized["reusedOfficialSync"] = True
        return reused_materialized

    result = writeback.get("result") if isinstance(writeback.get("result"), dict) else {}
    source_candidates = s._source_collection_candidates_for_run(team_id, run_id)
    source_candidates_by_id = {
        s._trim_text(item.get("candidateId"), max_length=160): item
        for item in source_candidates
        if s._trim_text(item.get("candidateId"), max_length=160)
    }
    pack_output = s._source_collection_stage_writeback_steward_pack_output(result)
    approved_candidate_ids_from_result = s._source_collection_stage_writeback_approved_candidate_ids(result, writeback)
    if not pack_output and approved_candidate_ids_from_result:
        selected_candidates = [
            source_candidates_by_id[candidate_id]
            for candidate_id in approved_candidate_ids_from_result
            if candidate_id in source_candidates_by_id and s._source_quality_bucket(source_candidates_by_id[candidate_id]) == "approved"
        ]
        if selected_candidates:
            source_candidate_ids = set(source_candidates_by_id.keys())
            with s._WORKFLOW_LOCK:
                workflow = s._load_or_create_workflow(team_id)
                candidate_store = s._load_candidate_store(team_id, run_id=run_id)
                stored_candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
                graph_candidates = [
                    item
                    for item in stored_candidates
                    if str(item.get("candidateType") or "") == "candidate_graph"
                    and not s._candidate_is_archived(item)
                    and s._source_collection_candidate_graph_matches_run(item, source_candidate_ids)
                ]
                latest_graph = s._latest_candidate_record(graph_candidates)
                workflow_id = str(workflow.get("workflowId") or "")
            pack_output = s._build_knowledge_ingestion_precheck_output(
                team_id,
                workflow_id,
                selected_candidates,
                latest_graph,
                target_domain=s._source_collection_stage_writeback_target_domain(result),
            )
            if len(selected_candidates) == 1:
                proposal_payload = pack_output.get("proposalPayload") if isinstance(pack_output.get("proposalPayload"), dict) else {}
                proposal_payload["title"] = s._source_manifest_label(selected_candidates[0])
                proposal_payload["summary"] = s._trim_text(selected_candidates[0].get("summary"), max_length=1000) or proposal_payload.get("summary", "")
                pack_output["proposalPayload"] = proposal_payload
            confidence_from_summary = s._source_collection_stage_writeback_approved_confidence(result)
            pack_output["confidence"] = max(s._source_collection_stage_writeback_knowledge_confidence({}, pack_output), confidence_from_summary)
            rating = pack_output.get("ratingSuggestion") if isinstance(pack_output.get("ratingSuggestion"), dict) else {}
            rating["confidence"] = max(s._source_collection_stage_writeback_knowledge_confidence({}, pack_output), confidence_from_summary)
            pack_output["ratingSuggestion"] = rating
            source_trace = pack_output.get("sourceTrace") if isinstance(pack_output.get("sourceTrace"), dict) else {}
            source_trace.update(
                {
                    "sourceCollectionRunId": s._trim_text(run_id, max_length=160),
                    "stageTaskId": s._trim_text(task.get("taskId"), max_length=160),
                    "stageId": stage_id,
                }
            )
            pack_output["sourceTrace"] = source_trace
    if not pack_output:
        return s._source_collection_stage_writeback_knowledge_ingestion_summary(status="no_steward_pack")
    pack_output = s._source_collection_stage_writeback_standardize_steward_pack_output(
        team_id,
        run_id,
        task,
        result,
        pack_output,
        source_candidates_by_id,
    )

    decision: dict[str, Any] = {}
    for key in (
        "autoIngestDecision",
        "auto_ingest_decision",
        "steward_assessment",
        "stewardAssessment",
        "ingestionDecision",
        "ingestion_decision",
    ):
        candidate_decision = result.get(key)
        if isinstance(candidate_decision, dict):
            decision = candidate_decision
            break
        if isinstance(candidate_decision, str) and candidate_decision.strip():
            decision = {"decision": candidate_decision}
            break
    if not decision and approved_candidate_ids_from_result:
        decision = {"decision": "approved", "confidence": s._source_collection_stage_writeback_approved_confidence(result)}
    normalized_decision = s._safe_token(decision.get("decision"), default="", max_length=80)
    confidence = s._source_collection_stage_writeback_knowledge_confidence(decision, pack_output)
    approved_decisions = {
        "approved",
        "approve",
        "approve_all",
        "accepted",
        "approved_for_ingestion",
        "approve_for_ingestion",
        "accepted_for_ingestion",
        "ingestion_approved",
        "approved_to_ingest",
    }
    if normalized_decision not in approved_decisions or confidence < 0.8:
        return s._source_collection_stage_writeback_knowledge_ingestion_summary(
            status="pending_review",
            skipped=[{"reason": "auto_ingest_gate_not_satisfied", "decision": normalized_decision, "confidence": confidence}],
        )

    requested_candidate_ids = s._normalize_text_list(pack_output.get("candidateIds"), max_items=64, max_length=160)
    in_run_candidate_ids = [candidate_id for candidate_id in requested_candidate_ids if candidate_id in source_candidates_by_id]
    if not in_run_candidate_ids:
        return s._source_collection_stage_writeback_knowledge_ingestion_summary(
            status="no_current_run_candidates",
            skipped=[{"reason": "candidate_not_in_source_collection_run", "candidateIds": requested_candidate_ids[:12]}],
        )
    approved_candidate_ids = [
        candidate_id
        for candidate_id in in_run_candidate_ids
        if s._source_quality_bucket(source_candidates_by_id[candidate_id]) == "approved"
    ]
    if set(approved_candidate_ids) != set(in_run_candidate_ids):
        return s._source_collection_stage_writeback_knowledge_ingestion_summary(
            status="source_quality_pending",
            approved_candidate_ids=approved_candidate_ids,
            skipped=[
                {
                    "reason": "source_quality_not_approved",
                    "candidateIds": [candidate_id for candidate_id in in_run_candidate_ids if candidate_id not in approved_candidate_ids][:12],
                }
            ],
        )

    steward_agent_id = (
        s._trim_text(writeback.get("recordedByAgent"), max_length=160)
        or s._trim_text(task.get("agentId"), max_length=160)
        or s.agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    )
    requested_knowledge_base_id = s._trim_text(
        result.get("scopedKnowledgeBaseId")
        or decision.get("scopedKnowledgeBaseId")
        or result.get("knowledgeBaseId")
        or decision.get("knowledgeBaseId"),
        max_length=256,
    )
    knowledge_base_id = s._knowledge_base_raw_id(requested_knowledge_base_id)
    scoped_knowledge_base_id = s._knowledge_base_scoped_id_for_team(team_id, requested_knowledge_base_id)
    knowledge_base = None
    try:
        if not knowledge_base_id:
            # 单临界区 get-or-create：查重与建库共享 _LOCK，关闭两段锁之间的竞态。
            resolved = s.team_knowledge_service.get_or_create_team_knowledge_base(
                team_id,
                name="Knowledge Expansion Library",
                actor_agent_id=steward_agent_id,
            )
            knowledge_base = resolved["knowledgeBase"]
            knowledge_base_id = s._knowledge_base_raw_id(knowledge_base.get("knowledgeBaseId"))
            scoped_knowledge_base_id = s._knowledge_base_scoped_id_for_team(team_id, knowledge_base_id, knowledge_base)
        s.team_knowledge_service.ensure_knowledge_base_review_grant(scoped_knowledge_base_id, steward_agent_id)
        # 与 KB review grant 对称的 trusted-gate 授权确保：只把本次自动链实际执行
        # owner source 审阅的 steward agent 加进该 team 的 localStewardAgentIds，
        # 不扩 REVIEW_ROLES、不影响其他 agent。
        s.team_knowledge_service.ensure_owner_source_review_grant("team", team_id, steward_agent_id)
        # 候选写入必须落在 authority run 的 owner 工程店里：pack/提交/审核整条
        # 链都带 run_id 走 run-owner 解析；owner 解析失败时保留历史活跃店目标
        # 并记录带 reason 的 warning 事件，不再静默漂移（SCI-091 事故根因）。
        pack_record = s.record_local_research_model_output(
            team_id,
            {
                "taskType": "steward_pack_draft",
                "title": s._trim_text(result.get("title") or writeback.get("summary"), max_length=240) or "Knowledge expansion steward pack",
                "createdByAgent": steward_agent_id,
                "output": pack_output,
            },
            run_id=run_id,
        )["candidate"]
        source_pending = s.submit_steward_pack_to_knowledge_ingestion(
            team_id,
            pack_record["candidateId"],
            {"knowledgeBaseId": scoped_knowledge_base_id, "proposedByAgentId": steward_agent_id},
            run_id=run_id,
        )
        ingestion = source_pending["candidate"].get("metadata", {}).get("knowledgeIngestion", {}) if isinstance(source_pending.get("candidate"), dict) else {}
        inbox_source_id = s._trim_text(ingestion.get("inboxSourceId"), max_length=160)
        reviewed_source = s.team_knowledge_service.review_owner_inbox_source(
            "team",
            team_id,
            inbox_source_id,
            decision="accepted",
            reviewed_by_agent_id=steward_agent_id,
        )
        central_source_id = s._trim_text(reviewed_source.get("centralSource", {}).get("centralSourceId") if isinstance(reviewed_source.get("centralSource"), dict) else "", max_length=160)
        knowledge_pending = s.submit_steward_pack_to_knowledge_ingestion(
            team_id,
            pack_record["candidateId"],
            {
                "knowledgeBaseId": scoped_knowledge_base_id,
                "proposedByAgentId": steward_agent_id,
                "centralSourceId": central_source_id,
            },
            run_id=run_id,
        )
        knowledge_review = s.review_steward_pack_knowledge_ingestion(
            team_id,
            pack_record["candidateId"],
            {
                "knowledgeBaseId": scoped_knowledge_base_id,
                "reviewedByAgentId": steward_agent_id,
                "decision": "approved",
                "resolutionNote": s._trim_text(decision.get("reason") or writeback.get("summary"), max_length=2000),
            },
            run_id=run_id,
        )
    except (s.TeamWorkflowOrchestrationError, s.team_knowledge_service.TeamKnowledgeError, s.team_knowledge_service.TeamKnowledgeNotFoundError) as exc:
        summary = s._source_collection_stage_writeback_knowledge_ingestion_summary(
            status="failed",
            knowledge_base_id=knowledge_base_id,
            scoped_knowledge_base_id=scoped_knowledge_base_id,
            approved_candidate_ids=approved_candidate_ids,
            failed=[{"reason": "knowledge_ingestion_failed", "error": str(exc)}],
        )
        s._record_workflow_event(
            "source_collection.stage_session_task_knowledge_ingestion_materialized",
            team_id,
            fields={
                "runId": s._trim_text(run_id, max_length=160),
                "taskId": s._trim_text(task.get("taskId"), max_length=160),
                "stageId": stage_id,
                "agentId": steward_agent_id,
                "status": "failed",
                "failedCount": summary["failedCount"],
            },
            level="warning",
            outcome="failed",
            child_log_path=f"artifacts/source-collection-{s._safe_token(run_id, default='run', max_length=96)}-knowledge-ingestion-materialization.jsonl",
            child_log_payload=s._source_collection_stage_knowledge_ingestion_child_log_payload(
                team_id=team_id,
                run_id=run_id,
                task=task,
                summary=summary,
                decision=decision,
            ),
            lifecycle=True,
        )
        return summary

    official_record = (
        knowledge_review.get("knowledgeIngestion", {}).get("officialSyncRecord", {})
        if isinstance(knowledge_review.get("knowledgeIngestion"), dict)
        else {}
    )
    knowledge_item_ids = [
        s._trim_text(item, max_length=160)
        for item in list(official_record.get("knowledgeItemIds") or [])
        if s._trim_text(item, max_length=160)
    ]
    summary = s._source_collection_stage_writeback_knowledge_ingestion_summary(
        status="completed",
        steward_pack_candidate_id=s._trim_text(pack_record.get("candidateId"), max_length=160),
        knowledge_base_id=knowledge_base_id,
        scoped_knowledge_base_id=scoped_knowledge_base_id,
        approved_candidate_ids=approved_candidate_ids,
        formal_knowledge_item_ids=knowledge_item_ids,
        source_pending=source_pending,
        knowledge_pending=knowledge_pending,
        knowledge_review=knowledge_review,
        confidence=confidence,
        knowledge_base=knowledge_base,
    )
    s._record_workflow_event(
        "source_collection.stage_session_task_knowledge_ingestion_materialized",
        team_id,
        fields={
            "runId": s._trim_text(run_id, max_length=160),
            "taskId": s._trim_text(task.get("taskId"), max_length=160),
            "stageId": stage_id,
            "agentId": steward_agent_id,
            "status": summary["status"],
            "stewardPackCandidateId": summary["stewardPackCandidateId"],
            "knowledgeBaseId": summary["knowledgeBaseId"],
            "approvedCandidateCount": summary["approvedCandidateCount"],
            "formalKnowledgeItemCount": summary["formalKnowledgeItemCount"],
        },
        child_log_path=f"artifacts/source-collection-{s._safe_token(run_id, default='run', max_length=96)}-knowledge-ingestion-materialization.jsonl",
        child_log_payload=s._source_collection_stage_knowledge_ingestion_child_log_payload(
            team_id=team_id,
            run_id=run_id,
            task=task,
            summary=summary,
            decision=decision,
        ),
    )
    return summary


def _source_collection_stage_writeback_candidate_decisions(result: dict[str, Any]) -> list[dict[str, Any]]:
    s = _service()
    candidates: list[dict[str, Any]] = []
    for key in (
        "candidateDecisions",
        "candidate_decisions",
        "decisions",
        "candidateReviews",
        "candidate_reviews",
        "reviewedCandidates",
        "reviewed_candidates",
    ):
        value = result.get(key)
        if isinstance(value, list):
            candidates.extend(item for item in value if isinstance(item, dict))
    for container_key in ("reviewSummary", "sourceQuality", "qualityReview", "handoff", "outputs", "summary"):
        container = result.get(container_key)
        if not isinstance(container, dict):
            continue
        for key in ("candidateDecisions", "candidate_decisions", "decisions", "candidateReviews", "reviewedCandidates"):
            value = container.get(key)
            if isinstance(value, list):
                candidates.extend(item for item in value if isinstance(item, dict))
    if candidates:
        return candidates[:200]

    # The extraction task contract asks the Agent to return one
    # candidateExtractions[] item per source. A separate candidateDecisions[]
    # payload is optional, so recognized extraction decisions must feed the
    # same quality materialization path instead of leaving the UI in a false
    # "extraction finished / quality not started" split state.
    return [
        dict(item)
        for item in s._source_collection_stage_writeback_candidate_extractions(result)
        if s._source_collection_stage_writeback_quality_decision(item)
    ][:200]


def _source_collection_stage_writeback_quality_decision(payload: dict[str, Any]) -> str:
    s = _service()
    raw = s._trim_text(
        payload.get("decision")
        or payload.get("status")
        or payload.get("result")
        or payload.get("bucket"),
        max_length=80,
    ).lower()
    normalized = raw.replace("-", "_").replace(" ", "_")
    if normalized in {
        "pass",
        "passed",
        "approve",
        "approved",
        "accept",
        "accepted",
        "keep",
        "kept",
        "retain",
        "retained",
        "keep_with_notes",
        "conditional_keep",
        "source_quality_approved",
    }:
        return "approved"
    if normalized in {"reject", "rejected", "irrelevant", "discard", "discarded", "source_quality_rejected"}:
        return "rejected"
    if normalized in {
        "needs_more_info",
        "need_more_info",
        "needs_revision",
        "needs_review",
        "return",
        "returned",
        "revise",
        "revision",
        "uncertain",
        "conditional_pass",
        "source_quality_needs_revision",
    }:
        return "needs_revision"
    return ""


def _source_collection_stage_writeback_quality_notes(payload: dict[str, Any], writeback: dict[str, Any]) -> str:
    s = _service()
    return (
        s._trim_text(payload.get("reason"), max_length=4000)
        or s._trim_text(payload.get("notes"), max_length=4000)
        or s._trim_text(payload.get("rationale"), max_length=4000)
        or s._trim_text(writeback.get("summary"), max_length=4000)
    )


def _source_collection_stage_writeback_quality_summary(
    *,
    status: str,
    assessed: list[dict[str, Any]] | None = None,
    skipped: list[dict[str, Any]] | None = None,
    failed: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    assessed_items = [item for item in list(assessed or []) if isinstance(item, dict)]
    skipped_items = [item for item in list(skipped or []) if isinstance(item, dict)]
    failed_items = [item for item in list(failed or []) if isinstance(item, dict)]
    return {
        "status": status,
        "assessedCandidateCount": len(assessed_items),
        "approvedCandidateCount": sum(1 for item in assessed_items if item.get("decision") == "approved"),
        "needsRevisionCandidateCount": sum(1 for item in assessed_items if item.get("decision") == "needs_revision"),
        "rejectedCandidateCount": sum(1 for item in assessed_items if item.get("decision") == "rejected"),
        "skippedCandidateCount": len(skipped_items),
        "failedCandidateCount": len(failed_items),
        "assessedCandidates": assessed_items[:80],
        "skippedCandidates": skipped_items[:80],
        "failedCandidates": failed_items[:80],
    }


def _source_collection_stage_writeback_candidate_graph_summary(
    *,
    status: str,
    candidate_graph: dict[str, Any] | None = None,
    failed: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    s = _service()
    graph = candidate_graph if isinstance(candidate_graph, dict) else {}
    failed_items = [item for item in list(failed or []) if isinstance(item, dict)]
    candidate_graph_id = s._trim_text(graph.get("candidateGraphId"), max_length=160)
    reused = bool(graph.get("reusedCandidateGraph"))
    return {
        "status": status,
        "candidateGraphId": candidate_graph_id,
        "createdCandidateGraphCount": 0 if reused or not candidate_graph_id else 1,
        "reusedCandidateGraph": reused,
        "nodeCount": s._source_collection_count(graph.get("nodeCount")),
        "edgeCount": s._source_collection_count(graph.get("edgeCount")),
        "missingLinkCount": s._source_collection_count(graph.get("missingLinkCount")),
        "danglingEdgeCount": s._source_collection_count(graph.get("danglingEdgeCount")),
        "semanticBindingEdgeCount": s._source_collection_count(graph.get("semanticBindingEdgeCount")),
        "unreviewedNodeCount": s._source_collection_count(graph.get("unreviewedNodeCount")),
        "inputCandidateCount": s._source_collection_count(graph.get("inputCandidateCount")),
        "filteredCandidateCount": s._source_collection_count(graph.get("filteredCandidateCount")),
        "ingestionFingerprint": s._trim_text(graph.get("ingestionFingerprint"), max_length=160),
        "failedCandidateGraphCount": len(failed_items),
        "failedCandidateGraphs": failed_items[:24],
    }


def _source_collection_stage_writeback_agent_graph_payload(result: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    explicit_graph = result.get("candidateGraph") if isinstance(result.get("candidateGraph"), dict) else {}
    if not explicit_graph and isinstance(result.get("candidate_graph"), dict):
        explicit_graph = result["candidate_graph"]
    if not explicit_graph and any(isinstance(result.get(key), list) for key in ("nodes", "edges", "missingLinks", "unreviewedNodes")):
        explicit_graph = {
            key: result[key]
            for key in ("nodes", "edges", "missingLinks", "unreviewedNodes", "clusters", "gaps", "qualityNotes", "scope")
            if result.get(key) is not None
        }
    theme_nodes = (
        result.get("themeNodes")
        or result.get("theme_nodes")
        or result.get("topicNodes")
        or result.get("topic_nodes")
        or result.get("themes")
    )
    normalized_theme_nodes = [
        dict(item) for item in list(theme_nodes or []) if isinstance(item, dict)
    ]
    theme_ids = {
        s._trim_text(
            item.get("themeId")
            or item.get("theme_id")
            or item.get("topicId")
            or item.get("topic_id")
            or item.get("id"),
            max_length=160,
        )
        for item in normalized_theme_nodes
    }
    theme_ids.discard("")

    source_theme_edges = [
        dict(item)
        for item in list(
            result.get("sourceThemeEdges")
            or result.get("source_theme_edges")
            or result.get("sourceTopicEdges")
            or result.get("source_topic_edges")
            or []
        )
        if isinstance(item, dict)
    ]
    topic_relations = [
        dict(item)
        for item in list(
            result.get("topicRelations")
            or result.get("topic_relations")
            or result.get("themeRelations")
            or result.get("theme_relations")
            or []
        )
        if isinstance(item, dict)
    ]
    # Raw ``edges`` already belong to ``explicit_graph`` when present. Keep this
    # list only for prompt-contract ``candidateRelations`` that need canonical
    # candidate graph edge fields, otherwise an implicit graph would duplicate
    # its raw edges during the merge below.
    direct_edges: list[dict[str, Any]] = []
    candidate_relations = [
        dict(item)
        for item in list(
            result.get("candidateRelations") or result.get("candidate_relations") or []
        )
        if isinstance(item, dict)
    ]
    for item in candidate_relations:
        source_id = s._trim_text(
            item.get("from")
            or item.get("source")
            or item.get("sourceCandidateId")
            or item.get("candidateId"),
            max_length=160,
        )
        target_id = s._trim_text(
            item.get("to")
            or item.get("target")
            or item.get("targetCandidateId")
            or item.get("themeId"),
            max_length=160,
        )
        relation = s._trim_text(
            item.get("relation") or item.get("relationType") or item.get("type"),
            max_length=160,
        )
        if not source_id or not target_id or not relation:
            continue
        evidence_refs = s._normalize_text_list(
            item.get("evidenceRefs")
            or item.get("evidence_refs")
            or item.get("evidenceRef"),
            max_items=64,
            max_length=320,
        )
        if source_id in theme_ids and target_id in theme_ids:
            topic_relations.append(
                {
                    "from": source_id,
                    "to": target_id,
                    "relation": relation,
                    "evidenceRefs": evidence_refs,
                }
            )
        elif target_id in theme_ids:
            source_theme_edges.append(
                {
                    "candidateId": source_id,
                    "themeId": target_id,
                    "relation": relation,
                    "evidenceRefs": evidence_refs,
                }
            )
        else:
            direct_edges.append(
                {
                    "sourceCandidateId": (
                        s._source_collection_agent_graph_theme_node_id(source_id)
                        if source_id in theme_ids
                        else source_id
                    ),
                    "targetCandidateId": target_id,
                    "relation": relation,
                    "evidenceRefs": evidence_refs,
                }
            )
    relation_payload = {
        "relationCoverage": result.get("relationCoverage") or result.get("relation_coverage"),
        "themeNodes": normalized_theme_nodes,
        "sourceThemeEdges": source_theme_edges,
        "topicRelations": topic_relations,
        "edges": direct_edges,
    }
    relation_payload = {
        key: value
        for key, value in relation_payload.items()
        if value
    }
    if not explicit_graph:
        return relation_payload
    merged = dict(explicit_graph)
    for key, value in relation_payload.items():
        if isinstance(value, list) and isinstance(merged.get(key), list):
            merged[key] = [*merged[key], *value]
        else:
            merged.setdefault(key, value)
    return merged


def _merge_source_collection_stage_writeback_agent_graph(
    graph: dict[str, Any],
    agent_graph: dict[str, Any],
) -> dict[str, Any]:
    s = _service()
    if not isinstance(graph, dict):
        graph = {}
    merged_graph = dict(graph)
    nodes = [dict(item) for item in list(merged_graph.get("nodes") or []) if isinstance(item, dict)]
    edges = [dict(item) for item in list(merged_graph.get("edges") or []) if isinstance(item, dict)]
    missing_links = [dict(item) for item in list(merged_graph.get("missingLinks") or []) if isinstance(item, dict)]
    unreviewed_nodes = [dict(item) for item in list(merged_graph.get("unreviewedNodes") or []) if isinstance(item, dict)]
    node_ids = {s._trim_text(node.get("candidateId"), max_length=160) for node in nodes if s._trim_text(node.get("candidateId"), max_length=160)}
    agent_relation_nodes = s._source_collection_agent_graph_nodes(agent_graph)
    # 结构约束两段式绑定：闭集注册表（服务端节点 + 本轮声明节点）之上做
    # 确定性语义端点解析（标题/主题别名），解析结果在入图前改写回真实
    # candidateId；解析不了的端点仍走 fail-closed 降级，不放宽门禁。
    endpoint_registry = build_relation_endpoint_registry([*nodes, *agent_relation_nodes])
    semantic_binding_edge_count = 0
    for node in agent_relation_nodes:
        node_id = s._trim_text(node.get("candidateId"), max_length=160)
        if not node_id or node_id in node_ids:
            continue
        nodes.append(node)
        node_ids.add(node_id)
    seen_edges = {
        (
            s._trim_text(edge.get("sourceCandidateId"), max_length=160),
            s._trim_text(edge.get("targetCandidateId"), max_length=160),
            s._trim_text(edge.get("relation"), max_length=160),
        )
        for edge in edges
        if s._trim_text(edge.get("sourceCandidateId"), max_length=160)
        and s._trim_text(edge.get("targetCandidateId"), max_length=160)
        and s._trim_text(edge.get("relation"), max_length=160)
    }
    dangling_edge_count = 0
    for edge in s._source_collection_agent_graph_edges(agent_graph):
        source_id = s._trim_text(edge.get("sourceCandidateId"), max_length=160)
        target_id = s._trim_text(edge.get("targetCandidateId"), max_length=160)
        relation = s._trim_text(edge.get("relation"), max_length=160)
        if not source_id or not target_id or not relation:
            continue
        effective_source = resolve_relation_endpoint(source_id, endpoint_registry) or source_id
        effective_target = resolve_relation_endpoint(target_id, endpoint_registry) or target_id
        edge_key = (effective_source, effective_target, relation)
        if edge_key in seen_edges:
            continue
        if effective_source in node_ids and effective_target in node_ids:
            if (effective_source, effective_target) != (source_id, target_id):
                edge = {
                    **edge,
                    "sourceCandidateId": effective_source,
                    "targetCandidateId": effective_target,
                }
                semantic_binding_edge_count += 1
            edges.append(edge)
        else:
            # Fail-closed: 端点经语义解析仍未命中节点表的边降级为 missingLink，
            # 并单独计数，供 relations 阶段完整性判定（danglingEdgeCount>0 即图不完整）。
            missing_links.append(edge)
            dangling_edge_count += 1
        seen_edges.add(edge_key)
    summary = merged_graph.get("summary") if isinstance(merged_graph.get("summary"), dict) else {}
    summary = dict(summary)
    summary.update(
        {
            "nodeCount": len(nodes),
            "edgeCount": len(edges),
            "missingLinkCount": len(missing_links),
            "danglingEdgeCount": dangling_edge_count,
            "unreviewedNodeCount": len(unreviewed_nodes),
            "agentRelationNodeCount": len(agent_relation_nodes),
            "agentRelationEdgeCount": len(s._source_collection_agent_graph_edges(agent_graph)),
            "semanticBindingEdgeCount": semantic_binding_edge_count,
        }
    )
    coverage = agent_graph.get("relationCoverage") if isinstance(agent_graph.get("relationCoverage"), dict) else {}
    if coverage:
        summary["relationCoverage"] = s._normalize_metadata(coverage)
    merged_graph["nodes"] = nodes
    merged_graph["edges"] = edges
    merged_graph["missingLinks"] = missing_links
    merged_graph["unreviewedNodes"] = unreviewed_nodes
    merged_graph["summary"] = summary
    return merged_graph


def _source_collection_stage_writeback_steward_pack_output(result: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    for key in ("stewardPackDraft", "steward_pack_draft", "stewardPack", "knowledgeIngestionPack"):
        value = result.get(key)
        if isinstance(value, dict):
            normalized = s._normalize_metadata(value)
            candidate_ids = s._normalize_text_list(normalized.get("candidateIds"), max_items=64, max_length=160)
            if not candidate_ids:
                candidate_ids = s._source_collection_stage_writeback_approved_candidate_ids(normalized, {})
            if candidate_ids:
                normalized["candidateIds"] = candidate_ids
            return normalized
    return {}


def _source_collection_stage_writeback_standardize_steward_pack_output(
    team_id: str,
    run_id: str,
    task: dict[str, Any],
    result: dict[str, Any],
    pack_output: dict[str, Any],
    source_candidates_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    s = _service()
    issues = s._validate_steward_pack_output(pack_output)
    if not any(item.get("severity") == "error" for item in issues):
        return pack_output
    candidate_ids = s._normalize_text_list(pack_output.get("candidateIds"), max_items=64, max_length=160)
    if not candidate_ids:
        candidate_ids = s._source_collection_stage_writeback_approved_candidate_ids(result, {})
    if not candidate_ids:
        return pack_output
    selected_candidates = [
        source_candidates_by_id[candidate_id]
        for candidate_id in candidate_ids
        if candidate_id in source_candidates_by_id and s._source_quality_bucket(source_candidates_by_id[candidate_id]) == "approved"
    ]
    if not selected_candidates:
        return pack_output
    source_candidate_ids = set(source_candidates_by_id.keys())
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(team_id)
        candidate_store = s._load_candidate_store(team_id, run_id=run_id)
        stored_candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
        graph_candidates = [
            item
            for item in stored_candidates
            if str(item.get("candidateType") or "") == "candidate_graph"
            and not s._candidate_is_archived(item)
            and s._source_collection_candidate_graph_matches_run(item, source_candidate_ids)
        ]
        latest_graph = s._latest_candidate_record(graph_candidates)
        workflow_id = str(workflow.get("workflowId") or "")
    target_domain = s._trim_text(pack_output.get("targetDomain"), max_length=160) or s._source_collection_stage_writeback_target_domain(result)
    standardized = s._build_knowledge_ingestion_precheck_output(
        team_id,
        workflow_id,
        selected_candidates,
        latest_graph,
        target_domain=target_domain,
    )
    standardized["candidateIds"] = candidate_ids
    proposal_payload = standardized.get("proposalPayload") if isinstance(standardized.get("proposalPayload"), dict) else {}
    incoming_proposal = pack_output.get("proposalPayload") if isinstance(pack_output.get("proposalPayload"), dict) else {}
    if incoming_proposal:
        proposal_payload.update(s._normalize_metadata(incoming_proposal))
        standardized["proposalPayload"] = proposal_payload
    risk_summary = s._trim_text(pack_output.get("riskSummary"), max_length=4000)
    if risk_summary:
        standardized["riskSummary"] = risk_summary
    incoming_rating = pack_output.get("ratingSuggestion") if isinstance(pack_output.get("ratingSuggestion"), dict) else {}
    rating = standardized.get("ratingSuggestion") if isinstance(standardized.get("ratingSuggestion"), dict) else {}
    if incoming_rating:
        rating.update(s._normalize_metadata(incoming_rating))
    confidence = max(
        s._source_collection_stage_writeback_knowledge_confidence({}, pack_output),
        s._source_collection_stage_writeback_approved_confidence(pack_output),
        s._source_collection_stage_writeback_approved_confidence(result),
        s._source_collection_stage_writeback_knowledge_confidence({}, standardized),
    )
    if confidence:
        standardized["confidence"] = confidence
        rating["confidence"] = confidence
    standardized["ratingSuggestion"] = rating
    source_trace = standardized.get("sourceTrace") if isinstance(standardized.get("sourceTrace"), dict) else {}
    incoming_trace = pack_output.get("sourceTrace") if isinstance(pack_output.get("sourceTrace"), dict) else {}
    if incoming_trace:
        source_trace.update(s._normalize_metadata(incoming_trace))
    source_trace.update(
        {
            "sourceCollectionRunId": s._trim_text(run_id, max_length=160),
            "stageTaskId": s._trim_text(task.get("taskId"), max_length=160),
            "stageId": s._trim_text(task.get("stageId"), max_length=80),
        }
    )
    standardized["sourceTrace"] = source_trace
    return standardized


def _source_collection_stage_writeback_approved_candidate_ids(result: dict[str, Any], writeback: dict[str, Any]) -> list[str]:
    s = _service()
    candidate_ids: list[str] = []

    def add(value: Any) -> None:
        values = s._normalize_id_values(value) if isinstance(value, list) else [s._trim_text(value, max_length=160)]
        for candidate_id in values:
            if candidate_id not in candidate_ids:
                candidate_ids.append(candidate_id)

    for key in ("approvedCandidateIds", "approved_candidate_ids", "candidateIds", "candidate_ids"):
        add(result.get(key))
    for key in ("approvedCandidates", "approved_candidates"):
        candidates = result.get(key)
        if isinstance(candidates, list):
            for candidate in candidates:
                if isinstance(candidate, dict):
                    add(candidate.get("candidateId") or candidate.get("id"))
                else:
                    add(candidate)

    for container_key in (
        "autoIngestDecision",
        "auto_ingest_decision",
        "ingestionDecision",
        "ingestion_decision",
        "stewardPackDraft",
        "steward_pack_draft",
        "stewardPack",
        "knowledgeIngestionPack",
    ):
        container = result.get(container_key)
        if not isinstance(container, dict):
            continue
        add(container.get("approvedCandidateIds") or container.get("approved_candidate_ids"))
        add(container.get("candidateIds") or container.get("candidate_ids"))
        candidates = container.get("approvedCandidates") or container.get("approved_candidates")
        if isinstance(candidates, list):
            for candidate in candidates:
                if isinstance(candidate, dict):
                    add(candidate.get("candidateId") or candidate.get("id"))
                else:
                    add(candidate)

    for container_key in ("candidate_summary", "candidateSummary", "summary", "sourceSummary", "steward_assessment", "stewardAssessment"):
        container = result.get(container_key)
        if not isinstance(container, dict):
            continue
        approved = container.get("approved")
        if isinstance(approved, dict):
            add(approved.get("candidateIds") or approved.get("candidate_ids"))
            candidates = approved.get("candidates")
            if isinstance(candidates, list):
                for candidate in candidates:
                    if isinstance(candidate, dict):
                        add(candidate.get("candidateId") or candidate.get("id"))
                    else:
                        add(candidate)
        elif isinstance(approved, list):
            add(approved)
        add(container.get("approvedCandidateIds") or container.get("approved_candidate_ids"))

    for key in ("candidateDecisions", "candidate_decisions", "decisions", "candidateReviews", "candidate_reviews"):
        decisions = result.get(key)
        if not isinstance(decisions, list):
            continue
        for decision in decisions:
            if not isinstance(decision, dict):
                continue
            normalized = s._source_collection_stage_writeback_quality_decision(decision)
            if normalized == "approved":
                add(decision.get("candidateId") or decision.get("id"))

    if not candidate_ids:
        for ref in s._normalize_ref_list(writeback.get("evidenceRefs"), max_items=24):
            if str(ref.get("kind") or ref.get("type") or "") == "candidate":
                add(ref.get("ref") or ref.get("id"))
    return candidate_ids[:80]


def _source_collection_stage_writeback_target_domain(result: dict[str, Any]) -> str:
    s = _service()
    for value in (
        result.get("targetDomain"),
        result.get("knowledgeDomain"),
        (result.get("steward_assessment") or {}).get("targetDomain")
        if isinstance(result.get("steward_assessment"), dict)
        else "",
        (result.get("stewardAssessment") or {}).get("targetDomain")
        if isinstance(result.get("stewardAssessment"), dict)
        else "",
        (result.get("autoIngestDecision") or {}).get("targetDomain")
        if isinstance(result.get("autoIngestDecision"), dict)
        else "",
        (result.get("ingestionDecision") or {}).get("targetDomain")
        if isinstance(result.get("ingestionDecision"), dict)
        else "",
    ):
        target = s._trim_text(value, max_length=160)
        if target:
            return target
    return "team_knowledge_expansion"


def _source_collection_stage_writeback_approved_confidence(result: dict[str, Any]) -> float:
    s = _service()
    values: list[float] = []
    for container_key in ("candidate_summary", "candidateSummary", "summary", "sourceSummary"):
        container = result.get(container_key)
        if not isinstance(container, dict):
            continue
        approved = container.get("approved")
        candidates = approved.get("candidates") if isinstance(approved, dict) else approved
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            for key in ("confidence", "overall_score", "overallScore", "relevance_score", "relevanceScore"):
                raw = candidate.get(key)
                try:
                    value = float(raw)
                except (TypeError, ValueError):
                    continue
                if value > 1:
                    value = value / 100
                values.append(max(0.0, min(1.0, value)))
    if values:
        return max(values)
    return 0.9 if s._source_collection_stage_writeback_approved_candidate_ids(result, {}) else 0.0


def _source_collection_stage_writeback_knowledge_confidence(
    decision: dict[str, Any],
    pack_output: dict[str, Any],
) -> float:
    s = _service()
    value = decision.get("confidence")
    if value is None:
        rating = pack_output.get("ratingSuggestion") if isinstance(pack_output.get("ratingSuggestion"), dict) else {}
        value = rating.get("confidence")
    if value is None:
        value = pack_output.get("confidence")
    if value is None:
        approved_confidence = s._source_collection_stage_writeback_approved_confidence(pack_output)
        if approved_confidence:
            return approved_confidence
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _source_collection_stage_writeback_knowledge_ingestion_summary(
    *,
    status: str,
    steward_pack_candidate_id: str = "",
    knowledge_base_id: str = "",
    scoped_knowledge_base_id: str = "",
    approved_candidate_ids: list[str] | None = None,
    formal_knowledge_item_ids: list[str] | None = None,
    source_pending: dict[str, Any] | None = None,
    knowledge_pending: dict[str, Any] | None = None,
    knowledge_review: dict[str, Any] | None = None,
    confidence: float = 0.0,
    knowledge_base: dict[str, Any] | None = None,
    skipped: list[dict[str, Any]] | None = None,
    failed: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    s = _service()
    normalized_approved_ids = [
        s._trim_text(item, max_length=160)
        for item in list(approved_candidate_ids or [])
        if s._trim_text(item, max_length=160)
    ]
    normalized_item_ids = [
        s._trim_text(item, max_length=160)
        for item in list(formal_knowledge_item_ids or [])
        if s._trim_text(item, max_length=160)
    ]
    skipped_items = [item for item in list(skipped or []) if isinstance(item, dict)]
    failed_items = [item for item in list(failed or []) if isinstance(item, dict)]
    return {
        "status": status,
        "stewardPackCandidateId": s._trim_text(steward_pack_candidate_id, max_length=160),
        "knowledgeBaseId": s._trim_text(knowledge_base_id, max_length=160),
        "scopedKnowledgeBaseId": s._trim_text(scoped_knowledge_base_id, max_length=256),
        "approvedCandidateCount": len(normalized_approved_ids),
        "approvedCandidateIds": normalized_approved_ids[:80],
        "formalKnowledgeItemCount": len(normalized_item_ids),
        "formalKnowledgeItemIds": normalized_item_ids[:80],
        "writesFormalKnowledge": status == "completed" and bool(normalized_item_ids),
        "confidence": confidence,
        "sourceReviewStatus": (
            str((source_pending or {}).get("knowledgeIngestion", {}).get("status") or "")
            if isinstance((source_pending or {}).get("knowledgeIngestion"), dict)
            else ""
        ),
        "knowledgeSubmissionStatus": (
            str((knowledge_pending or {}).get("knowledgeIngestion", {}).get("status") or "")
            if isinstance((knowledge_pending or {}).get("knowledgeIngestion"), dict)
            else ""
        ),
        "knowledgeReviewStatus": (
            str((knowledge_review or {}).get("knowledgeIngestion", {}).get("status") or "")
            if isinstance((knowledge_review or {}).get("knowledgeIngestion"), dict)
            else ""
        ),
        "createdKnowledgeBaseId": s._trim_text((knowledge_base or {}).get("knowledgeBaseId"), max_length=160) if isinstance(knowledge_base, dict) else "",
        "skippedCount": len(skipped_items),
        "failedCount": len(failed_items),
        "skipped": skipped_items[:24],
        "failed": failed_items[:24],
    }


def _source_collection_stage_writeback_child_log_payload(
    *,
    team_id: str,
    run_id: str,
    task: dict[str, Any],
    materialized_sources: dict[str, Any],
    materialized_source_quality: dict[str, Any],
    materialized_candidate_graph: dict[str, Any],
    materialized_knowledge_ingestion: dict[str, Any],
) -> dict[str, Any]:
    s = _service()
    return {
        "kind": "source_collection_stage_writeback_materialization",
        "teamId": s._trim_text(team_id, max_length=160),
        "runId": s._trim_text(run_id, max_length=160),
        "taskId": s._trim_text(task.get("taskId"), max_length=160),
        "stageId": s._trim_text(task.get("stageId"), max_length=80),
        "agentId": s._trim_text(task.get("agentId"), max_length=160),
        "agentRole": s._trim_text(task.get("agentRole"), max_length=80),
        "status": s._trim_text(task.get("status"), max_length=80),
        "materializedSources": s._source_collection_stage_writeback_materialization_child_summary(materialized_sources),
        "materializedSourceQuality": s._source_collection_stage_quality_materialization_child_summary(materialized_source_quality),
        "materializedCandidateGraph": s._source_collection_stage_candidate_graph_materialization_child_summary(materialized_candidate_graph),
        "materializedKnowledgeIngestion": s._source_collection_stage_knowledge_ingestion_materialization_child_summary(materialized_knowledge_ingestion),
    }


def _source_collection_stage_writeback_materialization_child_summary(summary: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    return {
        "status": s._trim_text(summary.get("status"), max_length=80),
        "sourceLeadCount": s._source_collection_count(summary.get("sourceLeadCount")),
        "createdRecordCount": s._source_collection_count(summary.get("createdRecordCount")),
        "importedCandidateCount": s._source_collection_count(summary.get("importedCandidateCount")),
        "skippedCount": s._source_collection_count(summary.get("skippedCount")),
        "skippedDuplicateCount": s._source_collection_count(summary.get("skippedDuplicateCount")),
        "failedCount": s._source_collection_count(summary.get("failedCount")),
        "createdRecords": s._bounded_log_items(summary.get("createdRecords"), ("recordId", "title", "sourceRef"), max_items=24),
        "importedCandidates": s._bounded_log_items(summary.get("importedCandidates"), ("candidateId", "recordId", "title"), max_items=24),
        "skipped": s._bounded_log_items(summary.get("skipped"), ("reason", "leadId", "recordId", "candidateId", "title"), max_items=24),
        "failed": s._bounded_log_items(summary.get("failed"), ("reason", "leadId", "recordId", "title", "errorType", "error"), max_items=24),
    }


def _source_collection_stage_writeback_source_leads(result: dict[str, Any]) -> list[dict[str, Any]]:
    s = _service()
    leads: list[dict[str, Any]] = []
    for key in (
        "candidateLeads",
        "candidate_leads",
        "sourceRecords",
        "source_records",
        "sourceCandidates",
        "source_candidates",
        "sources",
        "records",
        "createdRecords",
        "created_records",
        "newPapers",
        "new_papers",
    ):
        value = result.get(key)
        if isinstance(value, list):
            leads.extend(item for item in value if isinstance(item, dict))
    for container_key in ("searchFrame", "handoff", "result", "outputs", "summary"):
        container = result.get(container_key)
        if not isinstance(container, dict):
            continue
        for key in (
            "candidateLeads",
            "candidate_leads",
            "sourceRecords",
            "source_records",
            "sourceCandidates",
            "source_candidates",
            "sources",
            "records",
            "newPapers",
            "new_papers",
        ):
            value = container.get(key)
            if isinstance(value, list):
                leads.extend(item for item in value if isinstance(item, dict))
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for lead in leads:
        fingerprint = s._source_collection_stage_writeback_lead_fingerprint(lead)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        deduped.append(lead)
    return deduped[:80]


def _source_collection_stage_writeback_invalid_sources(result: dict[str, Any]) -> list[dict[str, Any]]:
    s = _service()
    invalid_sources: list[dict[str, Any]] = []
    for key in (
        "invalidSources",
        "invalid_sources",
        "excludedSources",
        "excluded_sources",
        "removedSources",
        "removed_sources",
        "noiseSources",
        "noise_sources",
    ):
        value = result.get(key)
        if isinstance(value, list):
            invalid_sources.extend(item for item in value if isinstance(item, dict))
    for container_key in ("searchFrame", "handoff", "result", "outputs", "summary"):
        container = result.get(container_key)
        if not isinstance(container, dict):
            continue
        for key in ("invalidSources", "invalid_sources", "excludedSources", "excluded_sources", "removedSources", "removed_sources"):
            value = container.get(key)
            if isinstance(value, list):
                invalid_sources.extend(item for item in value if isinstance(item, dict))
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in invalid_sources:
        fingerprint = s._source_collection_stage_writeback_lead_fingerprint(source)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        deduped.append(source)
    return deduped[:80]


def _materialize_source_collection_stage_invalid_sources(
    team_id: str,
    run_id: str,
    task: dict[str, Any],
    invalid_sources: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    s = _service()
    if not invalid_sources:
        return [], []
    try:
        run = s.data_processing_service.get_processing_run(run_id)
    except s.data_processing_service.DataProcessingError:
        run = {"runId": run_id, "scope": {}}
    excluded_sources: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    task_id = s._trim_text(task.get("taskId"), max_length=160)
    agent_id = s._trim_text(task.get("agentId"), max_length=160)
    stage_id = s._trim_text(task.get("stageId"), max_length=80)
    for source in invalid_sources:
        record = s._source_collection_stage_invalid_source_record(source)
        identity_key = s._source_collection_record_identity_or_record_key(record)
        if not identity_key:
            skipped.append(
                {
                    "reason": "invalid_source_missing_identity",
                    "title": s._trim_text(source.get("title"), max_length=240),
                }
            )
            continue
        reason = (
            s._trim_text(source.get("reason"), max_length=160)
            or s._trim_text(source.get("excludeReason"), max_length=160)
            or s._trim_text(source.get("exclude_reason"), max_length=160)
            or s._trim_text(source.get("decisionReason"), max_length=160)
            or "no_effective_content"
        )
        entry = s._record_source_collection_exclusion(
            team_id,
            run,
            record,
            reason=reason,
            evidence=(
                s._normalize_text_list(source.get("evidence"), max_items=8, max_length=500)
                or [
                    text for text in [
                        s._trim_text(source.get("notes"), max_length=500),
                        s._trim_text(source.get("summary"), max_length=500),
                    ]
                    if text
                ]
            ),
            task_id=task_id,
            agent_id=agent_id,
            stage_id=stage_id,
            source="stage_writeback_invalid_sources",
        )
        excluded_sources.append(
            {
                "recordId": s._trim_text(record.get("recordId"), max_length=160),
                "title": s._trim_text(record.get("title"), max_length=240),
                "reason": s._normalize_source_collection_exclusion_reason(reason) or "no_effective_content",
                "sourceIdentityKey": s._trim_text(entry.get("sourceIdentityKey") or identity_key, max_length=240),
                "exclusionId": s._trim_text(entry.get("exclusionId"), max_length=160),
            }
        )
    return excluded_sources, skipped


def _source_collection_stage_writeback_lead_fingerprint(lead: dict[str, Any]) -> str:
    s = _service()
    identity = s._source_collection_identity_key(
        source_ref=lead.get("sourceRef") or lead.get("source_ref") or lead.get("locator") or lead.get("doi"),
        raw_location=lead.get("rawLocation") or lead.get("raw_location") or lead.get("url") or lead.get("sourceUrl"),
        doi=lead.get("doi") or lead.get("DOI"),
        url=lead.get("url") or lead.get("sourceUrl"),
        title=lead.get("title"),
        container=lead.get("container") or lead.get("venue") or lead.get("journal"),
        published=lead.get("published") or lead.get("year"),
    )
    if identity:
        return identity
    fallback = "|".join(
        [
            s._trim_text(lead.get("leadId") or lead.get("id"), max_length=160),
            s._trim_text(lead.get("title"), max_length=260).lower(),
            s._trim_text(lead.get("year"), max_length=20),
        ]
    )
    return hashlib.sha256(fallback.encode("utf-8")).hexdigest()[:24]


def _source_collection_stage_writeback_record_payload(
    lead: dict[str, Any],
    *,
    team_id: str,
    run_id: str,
    task_id: str,
    stage_id: str,
    agent_id: str,
    agent_role: str,
    index: int,
) -> dict[str, Any]:
    s = _service()
    doi = s._source_collection_extract_doi(
        lead.get("doi"),
        lead.get("DOI"),
        lead.get("locator"),
        lead.get("sourceRef"),
        lead.get("sourceUrl"),
        lead.get("url"),
    )
    source_url = s._trim_text(lead.get("sourceUrl") or lead.get("url"), max_length=2000)
    source_ref = s._trim_text(lead.get("sourceRef") or lead.get("source_ref"), max_length=2000)
    locator = s._trim_text(lead.get("locator"), max_length=2000)
    if doi and not source_ref:
        source_ref = f"https://doi.org/{doi}"
    elif s._looks_like_url(source_url) and not source_ref:
        source_ref = source_url
    elif s._looks_like_url(locator) and not source_ref:
        source_ref = locator
        source_url = source_url or locator
    elif doi:
        source_ref = source_ref or f"https://doi.org/{doi}"
    title = s._trim_text(lead.get("title"), max_length=260)
    year = s._trim_text(lead.get("year") or lead.get("published"), max_length=80)
    container = s._trim_text(lead.get("container") or lead.get("venue") or lead.get("journal"), max_length=240)
    if not source_ref and not source_url:
        return {}
    summary = s._trim_text(
        lead.get("summary")
        or lead.get("abstract")
        or lead.get("relevance")
        or lead.get("notes")
        or lead.get("description"),
        max_length=4000,
    )
    metadata = s._normalize_metadata(lead.get("metadata"))
    metadata.update(
        {
            "sourceCollectionStageWriteback": True,
            "sourceCollectionStageTaskId": task_id,
            "sourceCollectionStageId": stage_id,
            "sourceCollectionStageAgentId": agent_id,
            "sourceCollectionStageAgentRole": agent_role,
            "sourceCollectionLeadIndex": index,
            "sourceCollectionLeadId": s._trim_text(lead.get("leadId") or lead.get("id"), max_length=160),
            "teamId": team_id,
            "runId": run_id,
            "doi": doi,
            "year": year,
            "containerTitle": container,
            "authors": s._source_collection_stage_writeback_authors(lead.get("authors")),
            "certainty": s._trim_text(lead.get("certainty"), max_length=120),
            "priority": s._trim_text(lead.get("priority"), max_length=80),
            "perspective": s._trim_text(
                lead.get("perspective") or lead.get("perspectiveId"),
                max_length=80,
            ),
        }
    )
    trace = {
        "teamId": team_id,
        "runId": run_id,
        "taskId": task_id,
        "stageId": stage_id,
        "agentId": agent_id,
        "agentRole": agent_role,
        "query": s._trim_text(lead.get("query"), max_length=1000),
        "perspective": metadata["perspective"],
        "leadId": s._trim_text(lead.get("leadId") or lead.get("id"), max_length=160),
        "searchProvider": s._trim_text(lead.get("searchProvider"), max_length=80) or "agent_stage_writeback",
        "storageTarget": "data_processing.records",
    }
    metadata["sourceCollectionTrace"] = trace
    source_identity_key = s._source_collection_identity_key(
        source_ref=source_ref,
        raw_location=source_url or locator,
        doi=doi,
        url=source_url,
        title=title,
        container=container,
        published=year,
    )
    quality_signals = s._normalize_metadata(lead.get("qualitySignals"))
    if source_identity_key:
        metadata["sourceIdentityKey"] = source_identity_key
        quality_signals["sourceIdentityKey"] = source_identity_key
    quality_signals.update(
        {
            "stageWritebackMaterialized": True,
            "certainty": metadata["certainty"],
            "priority": metadata["priority"],
        }
    )
    return {
        "sourceType": s._source_collection_data_processing_source_type(lead.get("sourceType") or lead.get("source_type") or lead.get("sourceKind") or "paper"),
        "sourceRef": source_ref,
        "rawLocation": source_url or locator,
        "title": title or source_ref or source_url,
        "summary": summary,
        "status": "ready_for_review" if source_ref or source_url else "collected",
        "metadata": metadata,
        "qualitySignals": quality_signals,
        "collectionTrace": trace,
    }


def _source_collection_stage_writeback_authors(value: Any) -> Any:
    s = _service()
    if isinstance(value, list):
        return [s._trim_text(item, max_length=160) for item in value[:24] if s._trim_text(item, max_length=160)]
    return s._trim_text(value, max_length=1000)


def _source_collection_stage_writeback_materialization_summary(
    *,
    status: str,
    source_lead_count: int = 0,
    created_records: list[dict[str, Any]] | None = None,
    imported_candidates: list[dict[str, Any]] | None = None,
    excluded_sources: list[dict[str, Any]] | None = None,
    skipped: list[dict[str, Any]] | None = None,
    failed: list[dict[str, Any]] | None = None,
    lineage: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    s = _service()
    normalized_skipped = [item for item in list(skipped or []) if isinstance(item, dict)]
    normalized_excluded = [item for item in list(excluded_sources or []) if isinstance(item, dict)]
    skipped_duplicate_count = sum(1 for item in normalized_skipped if "duplicate" in s._trim_text(item.get("reason"), max_length=120))
    return {
        "status": status,
        "sourceLeadCount": source_lead_count,
        "createdRecordCount": len(list(created_records or [])),
        "importedCandidateCount": len(list(imported_candidates or [])),
        "excludedSourceCount": len(normalized_excluded),
        "skippedCount": len(normalized_skipped),
        "skippedDuplicateCount": skipped_duplicate_count,
        "failedCount": len(list(failed or [])),
        "createdRecords": [
            {
                "recordId": s._trim_text(item.get("recordId"), max_length=160),
                "title": s._trim_text(item.get("title"), max_length=240),
                "sourceRef": s._trim_text(item.get("sourceRef") or item.get("rawLocation"), max_length=240),
            }
            for item in list(created_records or [])[:24]
            if isinstance(item, dict)
        ],
        "importedCandidates": list(imported_candidates or [])[:24],
        "excludedSources": normalized_excluded[:24],
        "skipped": normalized_skipped[:24],
        "failed": [item for item in list(failed or []) if isinstance(item, dict)][:24],
        # Authoritative identity binding is intentionally complete. The
        # bounded arrays above are diagnostics and must never be joined by
        # position to reconstruct provenance.
        "lineage": [item for item in list(lineage or []) if isinstance(item, dict)],
    }


def _merge_source_collection_stage_writeback_result_payload(
    team_id: str,
    run_id: str,
    task: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, Any]:
    s = _service()
    if not isinstance(incoming, dict) or not incoming:
        return {}
    stage_id = s._normalize_source_collection_stage_id(task.get("stageId"), default="")
    agent_role = s._normalize_source_collection_agent_role(task.get("agentRole"))
    merge_candidate_leads = stage_id == "finding" or agent_role == "source_finder"
    merged_previous: dict[str, Any] = {}
    for ancestor_result in s._source_collection_stage_retry_ancestor_results(team_id, run_id, task):
        merged_previous = s._merge_source_collection_stage_writeback_result_pair(
            team_id,
            run_id,
            merged_previous,
            ancestor_result,
            merge_candidate_leads=merge_candidate_leads,
        )
    previous_writeback = task.get("writeback") if isinstance(task.get("writeback"), dict) else {}
    previous_result = previous_writeback.get("result") if isinstance(previous_writeback.get("result"), dict) else {}
    if not previous_result and isinstance(task.get("result"), dict):
        previous_result = task["result"]
    if previous_result:
        merged_previous = s._merge_source_collection_stage_writeback_result_pair(
            team_id,
            run_id,
            merged_previous,
            previous_result,
            merge_candidate_leads=merge_candidate_leads,
        )
    return s._merge_source_collection_stage_writeback_result_pair(
        team_id,
        run_id,
        merged_previous,
        incoming,
        merge_candidate_leads=merge_candidate_leads,
    )


def _merge_source_collection_stage_writeback_result_pair(
    team_id: str,
    run_id: str,
    previous_result: dict[str, Any],
    incoming: dict[str, Any],
    *,
    merge_candidate_leads: bool,
) -> dict[str, Any]:
    s = _service()
    if not previous_result:
        previous_result = {}

    merged = dict(previous_result)
    merged.update(incoming)
    valid_candidate_ids = {
        s._trim_text(item.get("candidateId"), max_length=160)
        for item in s._source_collection_candidates_for_run(team_id, run_id)
        if s._trim_text(item.get("candidateId"), max_length=160)
    }
    valid_record_ids = {
        s._trim_text(item.get("recordId"), max_length=160)
        for item in s._source_collection_stage_records_for_run(run_id)
        if s._trim_text(item.get("recordId"), max_length=160)
    }
    if merge_candidate_leads:
        s._merge_source_collection_stage_writeback_array_group(
            merged,
            previous_result,
            incoming,
            canonical_key="candidateLeads",
            aliases=(
                "candidateLeads",
                "candidate_leads",
                "sourceRecords",
                "source_records",
                "sourceCandidates",
                "source_candidates",
                "sources",
                "records",
                "createdRecords",
                "created_records",
                "newPapers",
                "new_papers",
            ),
            containers=("searchFrame", "handoff", "result", "outputs", "summary"),
            item_id=lambda item: hashlib.sha256(
                s._source_collection_stage_writeback_lead_fingerprint(item).encode(
                    "utf-8", errors="replace"
                )
            ).hexdigest(),
            valid_existing_ids=set(),
            max_items=80,
        )
    s._merge_source_collection_stage_writeback_array_group(
        merged,
        previous_result,
        incoming,
        canonical_key="candidateExtractions",
        aliases=(
            "candidateExtractions",
            "candidate_extractions",
            "extractions",
            "candidateFindings",
            "candidate_findings",
            "extractedCandidates",
            "extracted_candidates",
        ),
        containers=("contentExtraction", "content_extraction", "extractionSummary", "outputs", "summary"),
        item_id=s._source_collection_stage_writeback_candidate_id,
        valid_existing_ids=valid_candidate_ids,
        max_items=300,
    )
    s._merge_source_collection_stage_writeback_array_group(
        merged,
        previous_result,
        incoming,
        canonical_key="candidateDecisions",
        aliases=(
            "candidateDecisions",
            "candidate_decisions",
            "decisions",
            "candidateReviews",
            "candidate_reviews",
            "reviewedCandidates",
            "reviewed_candidates",
        ),
        containers=("reviewSummary", "sourceQuality", "qualityReview", "handoff", "outputs", "summary"),
        item_id=s._source_collection_stage_writeback_candidate_id,
        valid_existing_ids=valid_candidate_ids,
        max_items=200,
    )
    s._merge_source_collection_stage_writeback_array_group(
        merged,
        previous_result,
        incoming,
        canonical_key="recordExtractions",
        aliases=(
            "recordExtractions",
            "record_extractions",
            "dataRecordExtractions",
            "data_record_extractions",
            "sourceRecordExtractions",
            "source_record_extractions",
        ),
        containers=("contentExtraction", "content_extraction", "extractionSummary", "outputs", "summary"),
        item_id=lambda item: (
            s._source_collection_stage_writeback_record_id(item)
            or s._source_collection_stage_writeback_candidate_id(item)
        ),
        valid_existing_ids=valid_record_ids,
        max_items=300,
    )
    s._merge_source_collection_stage_writeback_array_group(
        merged,
        previous_result,
        incoming,
        canonical_key="evidenceFetchAttempts",
        aliases=("evidenceFetchAttempts", "evidence_fetch_attempts"),
        containers=("contentExtraction", "content_extraction", "outputs", "summary"),
        item_id=lambda item: item.get("candidateId") or item.get("candidate_id"),
        valid_existing_ids=valid_candidate_ids,
        max_items=300,
    )
    s._merge_source_collection_stage_writeback_array_group(
        merged,
        previous_result,
        incoming,
        canonical_key="themeNodes",
        aliases=("themeNodes", "theme_nodes", "topicNodes", "topic_nodes"),
        containers=("candidateGraph", "candidate_graph", "relationGraph", "relation_graph", "outputs", "summary"),
        item_id=lambda item: item.get("themeId") or item.get("theme_id") or item.get("topicId") or item.get("topic_id") or item.get("id"),
        valid_existing_ids=set(),
        max_items=200,
    )
    s._merge_source_collection_stage_writeback_array_group(
        merged,
        previous_result,
        incoming,
        canonical_key="sourceThemeEdges",
        aliases=("sourceThemeEdges", "source_theme_edges", "sourceTopicEdges", "source_topic_edges"),
        containers=("candidateGraph", "candidate_graph", "relationGraph", "relation_graph", "outputs", "summary"),
        item_id=lambda item: (
            f"{item.get('candidateId') or item.get('candidate_id') or item.get('sourceCandidateId') or item.get('source_candidate_id')}:"
            f"{item.get('themeId') or item.get('theme_id') or item.get('topicId') or item.get('topic_id')}:"
            f"{item.get('relation') or item.get('relationType') or item.get('relation_type')}"
        ),
        valid_existing_ids=set(),
        max_items=500,
    )
    s._merge_source_collection_stage_writeback_array_group(
        merged,
        previous_result,
        incoming,
        canonical_key="topicRelations",
        aliases=("topicRelations", "topic_relations", "themeRelations", "theme_relations"),
        containers=("candidateGraph", "candidate_graph", "relationGraph", "relation_graph", "outputs", "summary"),
        item_id=lambda item: (
            f"{item.get('from') or item.get('fromThemeId') or item.get('from_theme_id') or item.get('sourceThemeId') or item.get('source_theme_id')}:"
            f"{item.get('to') or item.get('toThemeId') or item.get('to_theme_id') or item.get('targetThemeId') or item.get('target_theme_id')}:"
            f"{item.get('relation') or item.get('relationType') or item.get('relation_type')}"
        ),
        valid_existing_ids=set(),
        max_items=300,
    )
    return merged


def _merge_source_collection_stage_writeback_array_group(
    target: dict[str, Any],
    previous: dict[str, Any],
    incoming: dict[str, Any],
    *,
    canonical_key: str,
    aliases: tuple[str, ...],
    containers: tuple[str, ...],
    item_id: Any,
    valid_existing_ids: set[str],
    max_items: int,
) -> None:
    s = _service()
    incoming_items = s._source_collection_stage_writeback_array_items(incoming, aliases=aliases, containers=containers)
    if not incoming_items:
        return
    previous_items = s._source_collection_stage_writeback_array_items(previous, aliases=aliases, containers=containers)
    merged_items = s._merge_source_collection_stage_writeback_array_items(
        previous_items,
        incoming_items,
        item_id=item_id,
        valid_existing_ids=valid_existing_ids,
        max_items=max_items,
    )
    for key in aliases:
        target.pop(key, None)
    for container_key in containers:
        container = target.get(container_key)
        if not isinstance(container, dict):
            continue
        next_container = dict(container)
        for key in aliases:
            next_container.pop(key, None)
        target[container_key] = next_container
    target[canonical_key] = merged_items


def _source_collection_stage_writeback_array_items(
    payload: dict[str, Any],
    *,
    aliases: tuple[str, ...],
    containers: tuple[str, ...],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key in aliases:
        value = payload.get(key)
        if isinstance(value, list):
            items.extend(item for item in value if isinstance(item, dict))
    for container_key in containers:
        container = payload.get(container_key)
        if not isinstance(container, dict):
            continue
        for key in aliases:
            value = container.get(key)
            if isinstance(value, list):
                items.extend(item for item in value if isinstance(item, dict))
    return items


def _merge_source_collection_stage_writeback_array_items(
    previous: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    *,
    item_id: Any,
    valid_existing_ids: set[str],
    max_items: int,
) -> list[dict[str, Any]]:
    s = _service()
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for source, item in (
        [("previous", item) for item in previous]
        + [("incoming", item) for item in incoming]
    ):
        key = s._trim_text(item_id(item), max_length=160) if isinstance(item, dict) else ""
        if source == "previous" and valid_existing_ids and key and key not in valid_existing_ids:
            continue
        if not key:
            key = f"__unkeyed_{len(order)}"
        if key not in merged:
            order.append(key)
        merged[key] = dict(item)
    return [merged[key] for key in order[:max_items]]


def _merge_source_collection_stage_writeback_evidence_fetch_attempts(
    result_payload: dict[str, Any],
    evidence_refs: Any,
) -> dict[str, Any]:
    """Fold fetch-attempt-shaped ``evidenceRefs`` into ``evidenceFetchAttempts``.

    The writeback tool documents ``evidence_refs_json`` as the channel for
    evidence references, and agents legitimately submit remediation locator
    fetch attempts there (``{candidateId, locator, status, toolName,
    failureCode}``).  The completion gate only reads
    ``result.evidenceFetchAttempts``, so the writeback boundary normalizes
    attempt-shaped reference entries into that record instead of trusting the
    agent to pick one exact channel.  Later entries win per candidateId.
    """

    s = _service()
    payload = dict(result_payload if isinstance(result_payload, dict) else {})
    attempts: dict[str, dict[str, Any]] = {}
    for item in list(payload.get("evidenceFetchAttempts") or []):
        if not isinstance(item, dict):
            continue
        candidate_id = s._trim_text(item.get("candidateId"), max_length=160)
        if candidate_id:
            attempts[candidate_id] = dict(item)
    for item in list(evidence_refs or []):
        if not isinstance(item, dict):
            continue
        candidate_id = s._trim_text(item.get("candidateId"), max_length=160)
        locator = s._trim_text(item.get("locator"), max_length=1000)
        status = s._trim_text(item.get("status"), max_length=80).lower()
        tool_name = s._trim_text(item.get("toolName"), max_length=120)
        if (
            not candidate_id
            or not locator
            or tool_name != "web_fetch_tool"
            or status not in {"fetched", "failed"}
        ):
            continue
        attempt = {
            "candidateId": candidate_id,
            "locator": locator,
            "status": status,
            "toolName": tool_name,
        }
        failure_code = s._trim_text(item.get("failureCode"), max_length=160)
        if failure_code:
            attempt["failureCode"] = failure_code
        attempts[candidate_id] = attempt
    if attempts:
        payload["evidenceFetchAttempts"] = list(attempts.values())
    return payload


def _normalize_source_collection_stage_writeback_result_payload(value: Any) -> dict[str, Any]:
    s = _service()
    if not isinstance(value, dict):
        return {}
    if any(
        key in value
        for key in (
            "candidateExtractions",
            "candidate_extractions",
            "candidateDecisions",
            "candidate_decisions",
            "recordExtractions",
            "record_extractions",
            "evidenceFetchAttempts",
            "evidence_fetch_attempts",
            "candidateLeads",
            "candidate_leads",
            "sourceRecords",
            "source_records",
            "invalidSources",
            "invalid_sources",
            "candidateGraph",
            "candidate_graph",
            "stewardPackDraft",
            "approvedCandidateIds",
        )
    ):
        return value
    for key in ("text", "value", "result_json", "resultJson"):
        raw = value.get(key)
        if not isinstance(raw, str) or not raw.strip():
            continue
        parsed = s._parse_source_collection_stage_writeback_result_text(raw)
        if parsed:
            parsed.setdefault("_structuredResultRecoveredFrom", key)
            return parsed
    return value


def _normalize_source_collection_stage_writeback_result_metadata(value: Any) -> dict[str, Any]:
    s = _service()
    return s._normalize_source_collection_stage_writeback_result_metadata_dict(value, max_items=500)


def _normalize_source_collection_stage_writeback_result_metadata_dict(value: Any, *, max_items: int) -> dict[str, Any]:
    s = _service()
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, Any] = {}
    for key, item in value.items():
        normalized_key = s._trim_text(key, max_length=80)
        if not normalized_key:
            continue
        normalized[normalized_key] = s._normalize_source_collection_stage_writeback_result_metadata_value(
            item,
            max_items=s._source_collection_stage_writeback_result_metadata_max_items(normalized_key, max_items),
        )
    return normalized


def _normalize_source_collection_stage_writeback_result_metadata_value(value: Any, *, max_items: int) -> Any:
    s = _service()
    if isinstance(value, str):
        return s._trim_text(value, max_length=1000)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [
            s._normalize_source_collection_stage_writeback_result_metadata_value(item, max_items=max_items)
            for item in value[:max_items]
        ]
    if isinstance(value, dict):
        return s._normalize_source_collection_stage_writeback_result_metadata_dict(value, max_items=max_items)
    return s._trim_text(value, max_length=1000)


def _source_collection_stage_writeback_result_metadata_max_items(key: str, default: int) -> int:
    if key in {
        "candidateExtractions",
        "recordExtractions",
        "evidenceFetchAttempts",
        "sourceThemeEdges",
        "sourceTopicEdges",
        "source_theme_edges",
        "source_topic_edges",
    }:
        return 500
    if key in {
        "candidateDecisions",
        "themeNodes",
        "topicNodes",
        "topicRelations",
        "themeRelations",
        "theme_nodes",
        "topic_nodes",
        "topic_relations",
        "theme_relations",
    }:
        return 300
    return default


def _parse_source_collection_stage_writeback_result_text(text: str) -> dict[str, Any]:
    s = _service()
    stripped = str(text or "").strip()
    if not stripped:
        return {}
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, str) and parsed.strip() != stripped:
        nested = s._parse_source_collection_stage_writeback_result_text(parsed)
        if nested:
            return nested
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        nested = s._parse_source_collection_stage_writeback_result_text(fenced.group(1))
        if nested:
            return nested
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", stripped):
        try:
            candidate, _end_index = decoder.raw_decode(stripped[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            return candidate
    return {}
