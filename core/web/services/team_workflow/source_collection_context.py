"""Pure source-collection context helpers."""

from __future__ import annotations

from typing import Any

from .source_collection.extraction_quote_anchor_supply import (
    QUOTE_BLOCK_MAX_CHARS,
    QUOTE_SOURCES_TOTAL_CHAR_BUDGET,
)
from .source_collection_common import normalize_metadata, normalize_text_list, source_collection_count, trim_text


def normalize_source_collection_context_mode(value: Any) -> str:
    normalized = trim_text(value, max_length=40).lower()
    if normalized in {"full", "compact", "minimal", "evidence", "retry_missing", "retry_evidence"}:
        return normalized
    return "compact"


def source_collection_context_continuation_hint(candidate_page: dict[str, Any], *, context_mode: str) -> str:
    if not isinstance(candidate_page, dict) or not bool(candidate_page.get("hasMore")):
        return ""
    next_offset = source_collection_count(candidate_page.get("nextOffset"))
    limit = source_collection_count(candidate_page.get("limit")) or 5
    mode = normalize_source_collection_context_mode(context_mode)
    return f"hasMore: source_collection_context_tool(candidate_offset={next_offset}, candidate_limit={limit}, context_mode={mode})"


def source_collection_context_record_continuation_hint(record_page: dict[str, Any], *, context_mode: str) -> str:
    if not isinstance(record_page, dict) or not bool(record_page.get("hasMore")):
        return ""
    next_offset = source_collection_count(record_page.get("nextOffset"))
    limit = source_collection_count(record_page.get("limit")) or 5
    mode = normalize_source_collection_context_mode(context_mode)
    return f"hasMore: source_collection_context_tool(record_offset={next_offset}, record_limit={limit}, context_mode={mode})"


def compact_source_collection_stage_task_context(context: dict[str, Any]) -> dict[str, Any]:
    context_mode = normalize_source_collection_context_mode(context.get("contextMode"))
    minimal_mode = context_mode == "minimal"
    steward_mode = isinstance(context.get("stewardActionPacket"), dict)
    evidence_mode = context_mode in {"evidence", "retry_missing", "retry_evidence"} or steward_mode
    finding_stage = trim_text(context.get("stageId"), max_length=80) == "finding"
    candidate_page = context.get("candidatePage") if isinstance(context.get("candidatePage"), dict) else {}
    if finding_stage:
        # finding 闭合化第一步（O3）：不下发续读邀请。candidatePage.hasMore 恒为
        # false（nextOffset 仍可保留，但不再构成续读信号），continuationHint 随之
        # 置空；存量覆盖由系统在写回后评估。
        candidate_page = {**candidate_page, "hasMore": False}
    record_page = context.get("recordPage") if isinstance(context.get("recordPage"), dict) else {}
    usage = context.get("usage") if isinstance(context.get("usage"), dict) else {}
    record_continuation_hint = source_collection_context_record_continuation_hint(record_page, context_mode=context_mode)
    compact_usage = {
        "readTool": "source_collection_context_tool",
        "writebackTool": "source_collection_stage_writeback_tool",
        "continuationHint": source_collection_context_continuation_hint(candidate_page, context_mode=context_mode),
    }
    if not minimal_mode:
        compact_usage["doNotUse"] = usage.get("doNotUse") if isinstance(usage.get("doNotUse"), list) else []
    if trim_text(usage.get("retryInstruction"), max_length=1000):
        compact_usage["retryInstruction"] = trim_text(usage.get("retryInstruction"), max_length=1000)
    if trim_text(usage.get("evidenceInstruction"), max_length=1000):
        compact_usage["evidenceInstruction"] = trim_text(usage.get("evidenceInstruction"), max_length=1000)
    if trim_text(usage.get("quoteAnchorInstruction"), max_length=1200):
        # Quote-anchor supply instructions must survive compaction: the
        # extraction agent reads the compact context by default, and without
        # this line it never learns the verbatim-copy rules (run-882610596ddb).
        compact_usage["quoteAnchorInstruction"] = trim_text(usage.get("quoteAnchorInstruction"), max_length=1200)
    if trim_text(usage.get("extractionWritebackContract"), max_length=2000):
        compact_usage["extractionWritebackContract"] = trim_text(
            usage.get("extractionWritebackContract"),
            max_length=2000,
        )
    records = [
        compact_source_collection_context_record(item, evidence=evidence_mode)
        for item in list(context.get("records") or [])
        if isinstance(item, dict)
    ] if not minimal_mode or not list(context.get("candidates") or []) else []
    candidates = [
        compact_source_collection_context_candidate(item, minimal=minimal_mode, evidence=evidence_mode)
        for item in list(context.get("candidates") or [])
        if isinstance(item, dict)
    ]
    returned_candidate_count = source_collection_count(candidate_page.get("returned"))
    compact = {
        "schemaVersion": context.get("schemaVersion"),
        "status": context.get("status"),
        "contextKind": context.get("contextKind"),
        "contextMode": context_mode,
        "fieldMode": "id_and_locator_only" if minimal_mode else "evidence_source" if evidence_mode else "preview_only",
        "candidateFieldsTruncated": not evidence_mode,
        "doNotUsePreviewAsEvidence": not evidence_mode,
        "teamId": trim_text(context.get("teamId"), max_length=128),
        "runId": trim_text(context.get("runId"), max_length=128),
        "stageId": trim_text(context.get("stageId"), max_length=80),
        "taskId": trim_text(context.get("taskId"), max_length=160),
        "counts": normalize_metadata(context.get("counts")),
        "candidates": candidates,
        "candidatePage": normalize_metadata(candidate_page),
        "usage": compact_usage,
    }
    if not minimal_mode:
        compact["visibleCandidateCount"] = len(candidates)
        compact["omittedReturnedCandidateCount"] = max(0, returned_candidate_count - len(candidates))
        compact["agentId"] = trim_text(context.get("agentId"), max_length=160)
        compact["agentRole"] = trim_text(context.get("agentRole"), max_length=80)
        compact["run"] = compact_source_collection_context_run(context.get("run") if isinstance(context.get("run"), dict) else {})
        compact["task"] = compact_source_collection_context_task(context.get("task") if isinstance(context.get("task"), dict) else {})
        compact["unassessedCandidateIds"] = normalize_text_list(context.get("unassessedCandidateIds"), max_items=80, max_length=160)
        compact["allUnassessedCandidateCount"] = source_collection_count(context.get("allUnassessedCandidateCount"))
    if records:
        compact["records"] = records
    if not minimal_mode:
        compact["writebackContract"] = compact_source_collection_writeback_contract(
            context.get("writebackContract") if isinstance(context.get("writebackContract"), dict) else {}
        )
        compact["boundaries"] = compact_source_collection_boundaries(
            context.get("boundaries") if isinstance(context.get("boundaries"), dict) else {}
        )
    if isinstance(context.get("retryFocus"), dict):
        compact["retryFocus"] = normalize_metadata(context["retryFocus"])
    quotable_sources = compact_source_collection_quotable_sources(context.get("quotableSources"))
    if quotable_sources:
        compact["quotableSources"] = quotable_sources
    if isinstance(context.get("quoteAnchorRemediation"), dict) and context.get("quoteAnchorRemediation"):
        compact["quoteAnchorRemediation"] = normalize_metadata(context["quoteAnchorRemediation"])
    compact_record_ids = [
        trim_text(item.get("recordId"), max_length=160)
        for item in records
        if trim_text(item.get("recordId"), max_length=160)
    ]
    if record_continuation_hint:
        compact_usage["recordContinuationHint"] = record_continuation_hint
    excluded_source_summary = normalize_metadata(context.get("excludedSourceSummary"))
    if source_collection_count(excluded_source_summary.get("excludedCount")):
        compact["excludedSourceSummary"] = compact_source_collection_excluded_summary(excluded_source_summary)
    if compact_record_ids or source_collection_count(record_page.get("total")) or bool(record_page.get("hasMore")):
        compact["recordPage"] = normalize_metadata(record_page)
        compact["recordIds"] = compact_record_ids
    if isinstance(context.get("stewardActionPacket"), dict):
        compact["stewardActionPacket"] = compact_source_collection_steward_action_packet(
            context["stewardActionPacket"]
        )
    return compact


def compact_source_collection_steward_action_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Keep ingestion IDs and writeback shape without duplicating candidate bodies."""

    approved_ids = normalize_text_list(
        packet.get("approvedCandidateIds"),
        max_items=80,
        max_length=160,
    )
    raw_skeleton = (
        packet.get("writebackResultSkeleton")
        if isinstance(packet.get("writebackResultSkeleton"), dict)
        else {}
    )
    raw_summary = (
        raw_skeleton.get("candidate_summary")
        if isinstance(raw_skeleton.get("candidate_summary"), dict)
        else {}
    )
    raw_approved = (
        raw_summary.get("approved")
        if isinstance(raw_summary.get("approved"), dict)
        else {}
    )
    raw_assessment = (
        raw_skeleton.get("steward_assessment")
        if isinstance(raw_skeleton.get("steward_assessment"), dict)
        else {}
    )
    skeleton = {
        "approvedCandidateIds": normalize_text_list(
            raw_skeleton.get("approvedCandidateIds") or approved_ids,
            max_items=80,
            max_length=160,
        ),
        "candidate_summary": {
            "approved": {
                "count": source_collection_count(raw_approved.get("count")),
                "candidateIds": normalize_text_list(
                    raw_approved.get("candidateIds") or approved_ids,
                    max_items=80,
                    max_length=160,
                ),
            },
            "deferredCounts": normalize_metadata(raw_summary.get("deferredCounts")),
        },
        "steward_assessment": {
            "decision": trim_text(raw_assessment.get("decision"), max_length=80),
            "reason": trim_text(raw_assessment.get("reason"), max_length=500),
        },
    }
    compact = {
        key: packet.get(key)
        for key in (
            "schemaVersion",
            "packetKind",
            "action",
            "recommendedStatus",
            "approvedCandidateCount",
            "visibleApprovedCandidateCount",
            "candidateInventoryCounts",
            "deferredCandidateCounts",
            "doNotInferHiddenOrTruncatedCandidates",
            "doNotReviewPendingCandidates",
            "writebackTool",
            "writebackContractTaskId",
        )
        if key in packet
    }
    compact["summary"] = trim_text(packet.get("summary"), max_length=500)
    compact["approvedCandidateIds"] = approved_ids
    compact["writebackResultSkeleton"] = skeleton
    compact["instructions"] = normalize_text_list(
        packet.get("instructions"),
        max_items=8,
        max_length=500,
    )
    return {key: value for key, value in compact.items() if value not in ("", [], {})}


def compact_source_collection_excluded_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        key: summary.get(key)
        for key in ("excludedCount", "activeRecordCount", "rawRecordCount")
        if key in summary
    }


def compact_source_collection_quotable_sources(sources: Any) -> list[dict[str, Any]]:
    """Carry the extraction quotable-source blocks through compaction.

    The full context already applied the per-source block cap and the total
    char budget; compaction re-applies the same bounds defensively so the
    payload can never grow.  Block text is the verbatim-copy material — it
    must not be preview-truncated like the candidate summaries.
    """
    if not isinstance(sources, list):
        return []
    compact_sources: list[dict[str, Any]] = []
    used = 0
    for source in sources:
        if not isinstance(source, dict):
            continue
        blocks_out: list[dict[str, Any]] = []
        for block in list(source.get("blocks") or []):
            if not isinstance(block, dict):
                continue
            text = trim_text(block.get("text"), max_length=QUOTE_BLOCK_MAX_CHARS)
            if not text or used + len(text) > QUOTE_SOURCES_TOTAL_CHAR_BUDGET:
                break
            used += len(text)
            blocks_out.append(
                {
                    "origin": trim_text(block.get("origin"), max_length=40),
                    "text": text,
                    "chars": len(text),
                    "truncated": bool(block.get("truncated")),
                }
            )
        entry = {
            "sourceId": trim_text(source.get("sourceId"), max_length=160),
            "sourceKind": trim_text(source.get("sourceKind"), max_length=40),
            "title": trim_text(source.get("title"), max_length=240),
            "quoteAvailable": bool(source.get("quoteAvailable")),
            "blocks": blocks_out,
            "blockOrigin": trim_text(source.get("blockOrigin"), max_length=40),
            "sourceAccess": normalize_metadata(source.get("sourceAccess")),
        }
        if source.get("blockOmitted"):
            entry["blockOmitted"] = trim_text(source.get("blockOmitted"), max_length=40)
        # ``blocks`` stays explicit even when empty: "no quotable text" is a
        # meaningful supply state for the agent, not a missing field.
        compact_sources.append(
            {
                key: value
                for key, value in entry.items()
                if value not in ("", [], None) or key == "blocks"
            }
        )
    return compact_sources


def compact_source_collection_context_record(record: dict[str, Any], *, evidence: bool = False) -> dict[str, Any]:
    record_id = trim_text(record.get("recordId"), max_length=128)
    title = trim_text(record.get("title"), max_length=240 if evidence else 180)
    compact = {
        "recordId": record_id,
        "title": title,
        "summary": trim_text(record.get("summary"), max_length=1200 if evidence else 260),
        "sourceType": trim_text(record.get("sourceType"), max_length=80),
        "sourceUrl": trim_text(record.get("sourceUrl"), max_length=1000 if evidence else 320),
        "doi": trim_text(record.get("doi"), max_length=160),
        "containerTitle": trim_text(record.get("containerTitle"), max_length=160),
        "issued": trim_text(record.get("issued"), max_length=80),
        "query": trim_text(record.get("query"), max_length=240),
        "assignmentId": trim_text(record.get("assignmentId"), max_length=128),
        "identityKey": trim_text(record.get("identityKey"), max_length=180),
    }
    if evidence:
        compact["sourceRef"] = trim_text(record.get("sourceRef"), max_length=1000)
        compact["rawLocation"] = trim_text(record.get("rawLocation"), max_length=1000)
        if record_id:
            compact["evidenceRefs"] = [{"type": "data_record", "id": record_id, "label": title or record_id}]
            compact["evidenceScope"] = "collected_summary_metadata"
    return {key: value for key, value in compact.items() if value not in ("", [], {})}


def compact_source_collection_context_candidate(
    candidate: dict[str, Any],
    *,
    minimal: bool = False,
    evidence: bool = False,
) -> dict[str, Any]:
    latest_assessment = candidate.get("latestAssessment") if isinstance(candidate.get("latestAssessment"), dict) else {}
    content_extraction = candidate.get("contentExtraction") if isinstance(candidate.get("contentExtraction"), dict) else {}
    doi = trim_text(candidate.get("doi"), max_length=160)
    source_url = trim_text(candidate.get("sourceUrl"), max_length=120 if minimal else 1000 if evidence else 180)
    source_path = trim_text(candidate.get("sourcePath"), max_length=120 if minimal else 1000 if evidence else 180)
    source_record_id = trim_text(candidate.get("sourceRecordId"), max_length=128)
    locator = doi or source_url or source_path
    compact: dict[str, Any] = {
        "candidateId": trim_text(candidate.get("candidateId"), max_length=128),
        "title": trim_text(candidate.get("title"), max_length=80 if minimal else 240 if evidence else 120),
        "sourceKind": trim_text(candidate.get("sourceKind"), max_length=80),
        "locator": locator,
        "sourceRecordId": source_record_id,
        "qualityStatus": trim_text(candidate.get("qualityStatus"), max_length=80),
        "qualityBucket": trim_text(candidate.get("qualityBucket"), max_length=80),
        "sourceVersionFamily": normalize_metadata(candidate.get("sourceVersionFamily")),
    }
    if evidence:
        compact["summary"] = trim_text(candidate.get("summary"), max_length=1200)
        compact["sourceUrl"] = source_url
        compact["sourcePath"] = source_path
        compact["doi"] = doi
        evidence_ref = _source_collection_candidate_evidence_ref(
            source_record_id=source_record_id,
            doi=doi,
            source_url=source_url,
            source_path=source_path,
            label=trim_text(candidate.get("title"), max_length=240),
        )
        if evidence_ref:
            compact["evidenceRefs"] = [evidence_ref]
            compact["evidenceScope"] = "collected_summary_metadata"
    else:
        compact["summaryPreview"] = trim_text(candidate.get("summary"), max_length=48 if minimal else 24)
    if latest_assessment and not minimal:
        compact["latestAssessment"] = {
            "decision": trim_text(latest_assessment.get("decision"), max_length=80),
            "assessedByAgent": trim_text(latest_assessment.get("assessedByAgent"), max_length=160),
            "notes": trim_text(latest_assessment.get("notes"), max_length=220),
        }
    if content_extraction and not minimal:
        compact["contentExtraction"] = {
            "status": trim_text(content_extraction.get("status"), max_length=80),
            "decision": trim_text(content_extraction.get("decision"), max_length=80),
            "summary": trim_text(content_extraction.get("summary"), max_length=140),
            "evidenceStatus": trim_text(content_extraction.get("evidenceStatus"), max_length=80),
            "taskId": trim_text(content_extraction.get("taskId"), max_length=160),
        }
        if evidence:
            compact["contentExtraction"]["evidenceRefs"] = [
                normalize_metadata(item)
                for item in list(content_extraction.get("evidenceRefs") or [])[:24]
                if isinstance(item, dict)
            ]
            compact["contentExtraction"]["evidenceLedger"] = normalize_metadata(
                content_extraction.get("evidenceLedger") or {}
            )
        compact["contentExtraction"] = {
            key: value
            for key, value in compact["contentExtraction"].items()
            if value not in ("", [], {})
        }
    return {
        key: value
        for key, value in compact.items()
        if value not in ("", [], {})
    }


def _source_collection_candidate_evidence_ref(
    *,
    source_record_id: str,
    doi: str,
    source_url: str,
    source_path: str,
    label: str,
) -> dict[str, str]:
    ref_type = ""
    ref_id = ""
    if source_record_id:
        ref_type, ref_id = "data_record", source_record_id
    elif doi:
        ref_type, ref_id = "doi", doi
    elif source_url:
        ref_type, ref_id = "source_url", source_url
    elif source_path:
        ref_type, ref_id = "source_path", source_path
    if not ref_id:
        return {}
    return {"type": ref_type, "id": ref_id, "label": label or ref_id}


def compact_source_collection_context_run(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "runId": trim_text(run.get("runId"), max_length=128),
        "status": trim_text(run.get("status"), max_length=80),
    }


def compact_source_collection_context_task(task: dict[str, Any]) -> dict[str, Any]:
    compact = {
        "taskId": trim_text(task.get("taskId"), max_length=160),
        "stageId": trim_text(task.get("stageId"), max_length=80),
        "agentId": trim_text(task.get("agentId"), max_length=160),
        "agentRole": trim_text(task.get("agentRole"), max_length=80),
        "status": trim_text(task.get("status"), max_length=80),
        "summary": trim_text(task.get("summary"), max_length=240),
    }
    task_status = trim_text(task.get("status"), max_length=80).lower()
    should_show_gate = task_status not in {"", "running", "queued"}
    if should_show_gate and isinstance(task.get("taskToolProgress"), dict):
        progress = task["taskToolProgress"]
        compact["taskToolProgress"] = {
            key: progress.get(key)
            for key in (
                "complete",
                "completed",
                "total",
                "pendingIds",
                "pendingReason",
                "traceAvailable",
                "taskCreateObserved",
                "toolCallCount",
                "completedByTrace",
            )
            if key in progress
        }
    if should_show_gate and isinstance(task.get("completionGate"), dict):
        gate = task["completionGate"]
        compact["completionGate"] = {
            key: gate.get(key)
            for key in ("passed", "artifactComplete", "taskChecklistComplete")
            if key in gate
        }
    return compact


def compact_source_collection_writeback_contract(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        key: contract.get(key)
        for key in (
            "taskId",
            "teamId",
            "runId",
            "stageId",
            "writebackTool",
            "requiresStructuredResult",
            "resultAuthority",
            "writesFormalKnowledge",
            "writesOfficialGraph",
        )
        if key in contract
    }


def compact_source_collection_boundaries(boundaries: dict[str, Any]) -> dict[str, Any]:
    return {
        key: boundaries.get(key)
        for key in (
            "writesFormalKnowledge",
            "writesRag",
            "writesOfficialGraph",
            "requiresStructuredWriteback",
            "externalSearchAllowed",
            "localFileReadAllowed",
        )
        if key in boundaries
    }
