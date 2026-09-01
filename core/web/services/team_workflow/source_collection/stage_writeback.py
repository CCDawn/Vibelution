"""Source-collection stage writeback / task context / post-turn reconcile.

Clarity B6: split from stages.py. Shared gates/helpers import from stage_session.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..source_collection_common import project_source_version_families

from .stage_session import (
    _AUTO_FORMAL_RETRY_STATUSES,
    _service,
    _source_collection_run_graph_metrics,
    _source_collection_task_experiment_session_fields,
    assert_source_collection_stage_advance_ready,
)

# Evidence states an extraction entry may declare.  The claim evidence
# materializer skips ``missing_evidence_anchor``/``missing``/``unverified``
# and materializes everything else only with a verbatim quote anchor, so the
# writeback validation and the ``verification_status`` alias routing below
# must accept exactly this enum.
_EXTRACTION_EVIDENCE_STATUS_VALUES = {
    "verified_abstract",
    "evidence_ready",
    "missing_evidence_anchor",
    "missing",
    "unverified",
}

# Bounded diagnostics: at most this many per-writeback quote-anchor errors are
# surfaced in the rejection message.
_EXTRACTION_QUOTE_ANCHOR_ERROR_LIMIT = 3

# Challenge v2 card metadata keys accepted for the retrieval timestamp.  The
# fail-closed evidence contract accepts either spelling, so the backfill must
# respect both and never overwrite an explicit value.
_EXTRACTION_RETRIEVED_AT_KEYS = ("retrieved_at", "retrievedAt")


def _is_timezone_aware_rfc3339_timestamp(value: object) -> bool:
    """True when ``value`` parses as an RFC3339 timestamp with a timezone."""
    text = str(value or "").strip()
    if not text:
        return False
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _source_collection_stage_backfill_extraction_retrieved_at(
    team_id: str,
    run_id: str,
    task: dict[str, Any],
    result_payload: dict[str, Any],
) -> dict[str, Any]:
    """Backfill the Challenge v2 ``retrieved_at`` on extraction writebacks.

    The formal evidence contract fails closed on an extraction without an
    explicit retrieval timestamp (production run SCI-091 was blocked at
    source_extraction because the extraction agent omitted it, and the stage
    context never shows the agent a timestamp it could copy).  The writeback
    boundary owns real upstream retrieval times, so it supplies them here
    instead of letting the node fail later: the extraction's source record
    ``createdAt`` (when that content was fetched into the run), else the
    source candidate's ``createdAt`` (when it was registered), else the real
    writeback time.  Never invents a historical time and never overwrites an
    explicit, contract-compliant value from the agent.
    """
    s = _service()
    stage_id = s._trim_text(task.get("stageId"), max_length=80)
    agent_role = s._trim_text(task.get("agentRole"), max_length=80)
    if stage_id != "extraction" and agent_role != "source_extractor":
        return result_payload
    entries_by_collection: list[tuple[str, list[Any]]] = []
    for key in ("candidateExtractions", "recordExtractions"):
        entries = result_payload.get(key)
        if isinstance(entries, list) and entries:
            entries_by_collection.append((key, entries))
    if not entries_by_collection:
        return result_payload
    candidates_by_id: dict[str, dict[str, Any]] = {}
    records_by_id: dict[str, dict[str, Any]] = {}
    for candidate in s._source_collection_candidates_for_run(team_id, run_id):
        candidate_id = s._trim_text(candidate.get("candidateId"), max_length=160)
        if candidate_id:
            candidates_by_id.setdefault(candidate_id, candidate)
    for record in s._source_collection_stage_records_for_run(run_id):
        record_id = s._trim_text(record.get("recordId"), max_length=160)
        if record_id:
            records_by_id.setdefault(record_id, record)
    for _key, entries in entries_by_collection:
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            if any(
                _is_timezone_aware_rfc3339_timestamp(entry.get(name))
                for name in _EXTRACTION_RETRIEVED_AT_KEYS
            ):
                continue
            candidate = candidates_by_id.get(
                s._source_collection_stage_writeback_candidate_id(entry)
            )
            record = records_by_id.get(
                s._source_collection_stage_writeback_record_id(entry)
            )
            source_time = s._trim_text(
                (record or {}).get("createdAt")
                or (candidate or {}).get("createdAt"),
                max_length=120,
            )
            if not _is_timezone_aware_rfc3339_timestamp(source_time):
                source_time = s.utc_now_iso()
            normalized = dict(entry)
            normalized["retrieved_at"] = source_time
            entries[index] = normalized
    return result_payload

# Bounded diagnostics: at most this many Challenge v2 evidence-card contract
# errors are surfaced in the rejection message.
_EXTRACTION_CARD_CONTRACT_ERROR_LIMIT = 3


def _extraction_entry_with_normalized_evidence_status(entry: dict[str, Any]) -> dict[str, Any]:
    """Return the entry with ``verification_status`` alias routed, if applicable.

    Production incident (dprun-20260831142015208397-93ca7108): the extraction
    agent knew the evidence-state value ``missing_evidence_anchor`` but wrote
    it under the Challenge v2 card metadata key ``verification_status``, so the
    materializer read an empty ``evidenceStatus``.  Only this one key is
    aliased, and only when its value belongs to the extraction evidence-state
    enum; Challenge v2 card values (``metadata_checked`` and friends) stay card
    metadata untouched.
    """
    s = _service()
    if s._trim_text(entry.get("evidenceStatus"), max_length=80):
        return entry
    alias_value = s._trim_text(entry.get("verification_status"), max_length=80).lower()
    if alias_value in _EXTRACTION_EVIDENCE_STATUS_VALUES:
        normalized = dict(entry)
        normalized["evidenceStatus"] = alias_value
        return normalized
    return entry


def _normalize_extraction_evidence_status_aliases_in_payload(
    result: dict[str, Any],
) -> dict[str, Any]:
    """Route the ``verification_status`` alias on canonical extraction lists."""
    for key in ("candidateExtractions", "recordExtractions"):
        entries = result.get(key)
        if not isinstance(entries, list):
            continue
        normalized_entries: list[Any] = []
        changed = False
        for entry in entries:
            if isinstance(entry, dict):
                normalized = _extraction_entry_with_normalized_evidence_status(entry)
                changed = changed or normalized is not entry
                normalized_entries.append(normalized)
            else:
                normalized_entries.append(entry)
        if changed:
            result[key] = normalized_entries
    return result


def _extraction_entry_quote_anchor(
    entry: dict[str, Any],
    source_summary: str,
) -> tuple[bool, bool]:
    """Return ``(has_verbatim_anchor, supplied_quote_without_anchor)``.

    A valid anchor is a nested ``claims[]``/``keyFindings[]`` item with a
    ``quote`` or an ``evidenceRefs[]`` item with ``{id, quote}`` whose quote is
    a verbatim substring of the stored source summary.  A supplied quote that
    never matches verbatim is the strong paraphrase signal the contract
    rejects.
    """
    s = _service()
    supplied_quote = False
    for key in ("claims", "keyFindings", "key_findings", "findings"):
        items = entry.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            quote = s._trim_text(item.get("quote"), max_length=4000)
            if not quote:
                continue
            supplied_quote = True
            if quote in source_summary:
                return True, False
    refs = entry.get("evidenceRefs") or entry.get("evidence_refs")
    if isinstance(refs, list):
        for item in refs:
            if not isinstance(item, dict):
                continue
            quote = s._trim_text(item.get("quote"), max_length=4000)
            if not quote:
                continue
            supplied_quote = True
            ref_id = s._trim_text(
                item.get("id") or item.get("evidenceRefId") or item.get("refId"),
                max_length=240,
            )
            if ref_id and quote in source_summary:
                return True, False
    return False, supplied_quote


def _source_collection_stage_writeback_formal_claim_bound(
    task: dict[str, Any],
    run_id: str,
) -> bool:
    """True when this stage task can cross the claim-evidence boundary.

    The quote-anchor contract exists to feed claim materialization; runs
    without a formal workflow binding never materialize claims, so their
    writebacks keep the permissive legacy behavior.
    """
    s = _service()
    if s._trim_text(task.get("workflowRunId"), max_length=160):
        return True
    try:
        run = s.data_processing_service.get_processing_run(run_id)
    except Exception:  # noqa: BLE001 - absent run leaves the contract inert
        return False
    run_scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    return bool(s._trim_text(run_scope.get("workflowRunId"), max_length=160))


def _source_collection_stage_writeback_quote_anchor_errors(
    team_id: str,
    run_id: str,
    task: dict[str, Any],
    result_payload: dict[str, Any],
) -> list[str]:
    """Validate completed extraction writebacks against verbatim quote anchors.

    Per non-exclude entry whose source summary is stored non-empty: require at
    least one verbatim quote anchor and reject any paraphrased quote.  Sources
    with an empty stored summary must honestly declare
    ``evidenceStatus=missing_evidence_anchor`` (the materializer skips those).
    Returns human-readable errors; an empty list means the writeback passes.
    """
    s = _service()
    stage_id = s._trim_text(task.get("stageId"), max_length=80)
    agent_role = s._trim_text(task.get("agentRole"), max_length=80)
    if stage_id != "extraction" and agent_role != "source_extractor":
        return []
    if not _source_collection_stage_writeback_formal_claim_bound(task, run_id):
        return []
    summary_by_id: dict[str, str] = {}
    known_source_ids: set[str] = set()
    for candidate in s._source_collection_candidates_for_run(team_id, run_id):
        candidate_id = s._trim_text(candidate.get("candidateId"), max_length=160)
        if not candidate_id:
            continue
        known_source_ids.add(candidate_id)
        summary = s._trim_text(candidate.get("summary"), max_length=4000)
        if summary:
            summary_by_id[candidate_id] = summary
    records = s._source_collection_stage_records_for_run(run_id)
    try:
        run = s.data_processing_service.get_processing_run(run_id)
        records, _excluded_source_summary = s._source_collection_filter_active_records(team_id, run, records)
    except s.data_processing_service.DataProcessingError:
        pass
    for record in records:
        record_id = s._trim_text(record.get("recordId"), max_length=160)
        if not record_id:
            continue
        known_source_ids.add(record_id)
        summary = s._trim_text(record.get("summary") or record.get("content"), max_length=4000)
        if summary:
            summary_by_id.setdefault(record_id, summary)
    errors: list[str] = []
    entries = list(s._source_collection_stage_writeback_candidate_extractions(result_payload))
    entries.extend(
        s._source_collection_stage_writeback_record_extractions(
            result_payload,
            include_candidate_fallback=False,
        )
    )
    for entry in entries:
        decision = s._trim_text(entry.get("decision"), max_length=80).lower()
        if decision == "exclude":
            continue
        candidate_id = s._source_collection_stage_writeback_candidate_id(entry)
        record_id = s._source_collection_stage_writeback_record_id(entry)
        source_id = candidate_id or record_id
        if not source_id or source_id not in known_source_ids:
            # Unknown ids stay with candidate-coverage invalid-id handling.
            continue
        source_summary = summary_by_id.get(source_id, "")
        source_label = f"candidate {source_id}" if candidate_id else f"record {source_id}"
        if not source_summary:
            normalized_entry = _extraction_entry_with_normalized_evidence_status(entry)
            evidence_status = s._trim_text(normalized_entry.get("evidenceStatus"), max_length=80).lower()
            if evidence_status != "missing_evidence_anchor":
                errors.append(
                    f"{source_label} 存储摘要为空：条目必须声明 evidenceStatus=missing_evidence_anchor 诚实跳过，"
                    "不能在没有任何锚点的情况下声称证据。"
                )
            continue
        has_anchor, supplied_quote = _extraction_entry_quote_anchor(entry, source_summary)
        if has_anchor:
            continue
        if supplied_quote:
            errors.append(
                f"{source_label} 的 quote 不是存储 summary 的逐字子串："
                "quote 必须从 candidates[].summary 原样复制，禁止改写、拼接或凭记忆重写。"
            )
        else:
            errors.append(
                f"{source_label} 缺少逐字 quote 锚：嵌套 claims[]/keyFindings[] 项需含 quote，"
                "或 evidenceRefs[] 项需含 {id, quote}（quote 为存储 summary 的逐字子串）。"
            )
    return errors


def _source_collection_stage_writeback_extraction_card_contract_errors(
    task: dict[str, Any],
    run_id: str,
    result_payload: dict[str, Any],
) -> list[str]:
    """Validate the merged extraction writeback against the Challenge v2 card contract.

    Production blocker (run-882610596ddb): the fail-closed Challenge v2
    contract only fired at claim materialization — after the task already
    completed — so an extraction writeback with systematically missing
    ``retrieved_at`` passed the completion gate, the agent never got a chance
    to correct it, and the run failed with a generic adapter exception.

    This boundary rejects the same violation at writeback acceptance with a
    precise path so the agent can fix and rewrite within the same task.  The
    rules are NOT duplicated here: this gate reuses the materializer's own
    ``_materializable_claims`` (skip semantics for ``exclude`` and honest
    ``missing_evidence_anchor`` entries) plus
    ``normalize_challenge_evidence_fields`` (the exact validator the
    materializer calls), so a writeback is rejected exactly when
    materialization would raise.

    Returns human-readable errors; an empty list means the writeback passes.
    """
    s = _service()
    stage_id = s._trim_text(task.get("stageId"), max_length=80)
    agent_role = s._trim_text(task.get("agentRole"), max_length=80)
    if stage_id != "extraction" and agent_role != "source_extractor":
        return []
    if not _source_collection_stage_writeback_formal_claim_bound(task, run_id):
        return []
    from ..research_runtime.agent_claim_evidence_materializer import (
        _materializable_claims,
    )
    from ..research_runtime.source_extraction_evidence_cards import (
        SourceExtractionEvidenceContractError,
        normalize_challenge_evidence_fields,
    )

    errors: list[str] = []
    task_like = {"result": result_payload}
    for extraction, claim, claim_path in _materializable_claims(task_like):
        try:
            normalize_challenge_evidence_fields(claim, extraction, path=claim_path)
        except SourceExtractionEvidenceContractError as exc:
            errors.append(s._trim_text(str(exc), max_length=400))
    return errors


def writeback_source_collection_stage_session_task(
    team_id: str,
    task_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_task_id = s._normalize_required_id(task_id, "Stage session task id is required.")
    s.team_service.get_team(normalized_team_id)
    request_payload = dict(payload) if isinstance(payload, dict) else {}
    task, run_id = s._find_source_collection_stage_session_task_by_id(normalized_team_id, normalized_task_id)
    if task is None or not run_id:
        raise s.TeamWorkflowOrchestrationError(f"Stage session task not found: {normalized_task_id}")
    status = s._normalize_source_collection_stage_session_task_status(request_payload.get("status") or request_payload.get("resultStatus"))
    result_payload = s._normalize_source_collection_stage_writeback_result_payload(request_payload.get("result"))
    result_payload = s._merge_source_collection_stage_writeback_evidence_fetch_attempts(
        result_payload,
        request_payload.get("evidenceRefs"),
    )
    incoming_result_payload = result_payload
    result_payload = s._merge_source_collection_stage_writeback_result_payload(normalized_team_id, run_id, task, result_payload)
    result_payload = _normalize_extraction_evidence_status_aliases_in_payload(result_payload)
    result_payload = _source_collection_stage_backfill_extraction_retrieved_at(
        normalized_team_id,
        run_id,
        task,
        result_payload,
    )
    if status == "completed":
        # Fail-closed quote-anchor contract: a completed extraction writeback
        # without verbatim quote anchors used to be accepted and then
        # silently materialize zero claims (production incident
        # stagetask-20260831142807-d31d5a7d).  Reject it at the door instead.
        quote_anchor_errors = _source_collection_stage_writeback_quote_anchor_errors(
            normalized_team_id,
            run_id,
            task,
            incoming_result_payload,
        )
        if quote_anchor_errors:
            raise s.TeamWorkflowOrchestrationError(
                "extraction writeback rejected: 提炼回写缺少逐字 quote 锚 —— "
                + " ".join(quote_anchor_errors[:_EXTRACTION_QUOTE_ANCHOR_ERROR_LIMIT])
            )
        # Fail-closed Challenge v2 evidence-card contract at the acceptance
        # boundary (production blocker run-882610596ddb), layered behind the
        # server-side ``retrieved_at`` backfill above: the backfill resolves
        # the dominant "agent omitted the timestamp" failure with real chain
        # times, and this gate rejects whatever still violates the card
        # contract (missing title/source_type/fact/..., structural
        # violations) with precise paths.  The merged, backfilled result is
        # exactly the payload claim materialization will read, and it is
        # validated here with the materializer's own validators, so a
        # completed writeback is rejected exactly when materialization would
        # raise — while the agent can still correct and rewrite within the
        # same task; completionGate can never pass on contract-violating data.
        card_contract_errors = _source_collection_stage_writeback_extraction_card_contract_errors(
            task,
            run_id,
            result_payload,
        )
        if card_contract_errors:
            raise s.TeamWorkflowOrchestrationError(
                "extraction writeback rejected: Challenge v2 证据卡契约校验失败 —— "
                "请在对应条目补全缺失字段后重写；"
                + " | ".join(card_contract_errors[:_EXTRACTION_CARD_CONTRACT_ERROR_LIMIT])
            )
    writeback = {
        "status": status,
        "agentRequestedStatus": status,
        "summary": s._trim_text(request_payload.get("summary"), max_length=4000),
        "result": s._normalize_source_collection_stage_writeback_result_metadata(result_payload),
        "evidenceRefs": s._normalize_ref_list(request_payload.get("evidenceRefs"), max_items=24),
        "nextActions": s._normalize_text_list(request_payload.get("nextActions"), max_items=12, max_length=500),
        "recordedByAgent": s._trim_text(request_payload.get("recordedByAgent"), max_length=160),
        "metadata": s._normalize_metadata(request_payload.get("metadata")),
        "recordedAt": s.utc_now_iso(),
    }
    coverage_summary = s._source_collection_stage_writeback_candidate_coverage(
        normalized_team_id,
        run_id,
        task,
        writeback,
    )
    if coverage_summary.get("applicable"):
        if status == "completed" and not bool(coverage_summary.get("complete")):
            status = "needs_review"
            writeback["status"] = status
        writeback["coverageSummary"] = coverage_summary
        writeback["invalidCandidateIds"] = list(coverage_summary.get("invalidCandidateIds") or [])
        writeback["invalidRecordIds"] = list(coverage_summary.get("invalidRecordIds") or [])
    materialized_sources = s._materialize_source_collection_stage_writeback_sources(
        normalized_team_id,
        run_id,
        task,
        writeback,
        incoming_result=incoming_result_payload,
    )
    if status == "running":
        from .writeback_materialize import (
            source_collection_finding_writeback_close_status,
        )

        finding_close_status = source_collection_finding_writeback_close_status(
            task,
            writeback["result"],
        )
        if finding_close_status:
            status = finding_close_status
            writeback["status"] = status
            writeback["autoCloseReason"] = "finding_search_envelope_saturated"
    materialized_content_extraction = s._materialize_source_collection_stage_writeback_content_extraction(
        normalized_team_id,
        run_id,
        task,
        writeback,
    )
    materialized_source_quality = s._materialize_source_collection_stage_writeback_quality(
        normalized_team_id,
        run_id,
        task,
        writeback,
    )
    materialized_candidate_graph = s._materialize_source_collection_stage_writeback_candidate_graph(
        normalized_team_id,
        run_id,
        task,
        writeback,
    )
    materialized_knowledge_ingestion = s._materialize_source_collection_stage_writeback_knowledge_ingestion(
        normalized_team_id,
        run_id,
        task,
        writeback,
    )
    if status == "completed" and s._source_collection_count(materialized_content_extraction.get("missingEvidenceAnchorCount")):
        status = "needs_review"
        writeback["status"] = status
        writeback["evidenceReviewRequiredReason"] = "missing_evidence_anchor"
    closure_summary = s._source_collection_stage_writeback_closure_summary(
        task,
        writeback,
        coverage_summary=coverage_summary,
        materialized_sources=materialized_sources,
        materialized_content_extraction=materialized_content_extraction,
        materialized_source_quality=materialized_source_quality,
        materialized_candidate_graph=materialized_candidate_graph,
        materialized_knowledge_ingestion=materialized_knowledge_ingestion,
    )
    if status == "completed" and not bool(closure_summary.get("artifactComplete")):
        status = "needs_review"
        writeback["status"] = status
        closure_summary = s._source_collection_stage_writeback_closure_summary(
            task,
            writeback,
            coverage_summary=coverage_summary,
            materialized_sources=materialized_sources,
            materialized_content_extraction=materialized_content_extraction,
            materialized_source_quality=materialized_source_quality,
            materialized_candidate_graph=materialized_candidate_graph,
            materialized_knowledge_ingestion=materialized_knowledge_ingestion,
        )
    task_checklist = [
        item for item in list(task.get("taskChecklist") or [])
        if isinstance(item, dict)
    ]
    task_tool_progress = closure_summary.get("taskToolProgress") if isinstance(closure_summary.get("taskToolProgress"), dict) else {}
    completion_gate = s._source_collection_stage_completion_gate(
        task_checklist=task_checklist,
        artifact_complete=bool(closure_summary.get("artifactComplete")),
        task_checklist_complete=bool(closure_summary.get("taskChecklistComplete")),
    )
    closure_summary["completionGate"] = completion_gate
    closure_summary["completionGatePassed"] = bool(completion_gate.get("passed"))
    if status == "completed" and not bool(closure_summary.get("completionGatePassed")):
        status = "needs_review"
        writeback["status"] = status
        closure_summary = s._source_collection_stage_writeback_closure_summary(
            task,
            writeback,
            coverage_summary=coverage_summary,
            materialized_sources=materialized_sources,
            materialized_content_extraction=materialized_content_extraction,
            materialized_source_quality=materialized_source_quality,
            materialized_candidate_graph=materialized_candidate_graph,
            materialized_knowledge_ingestion=materialized_knowledge_ingestion,
        )
        task_tool_progress = closure_summary.get("taskToolProgress") if isinstance(closure_summary.get("taskToolProgress"), dict) else {}
        completion_gate = s._source_collection_stage_completion_gate(
            task_checklist=task_checklist,
            artifact_complete=bool(closure_summary.get("artifactComplete")),
            task_checklist_complete=bool(closure_summary.get("taskChecklistComplete")),
        )
        closure_summary["completionGate"] = completion_gate
        closure_summary["completionGatePassed"] = bool(completion_gate.get("passed"))
    writeback["materializedSources"] = materialized_sources
    writeback["materializedContentExtraction"] = materialized_content_extraction
    writeback["materializedSourceQuality"] = materialized_source_quality
    writeback["materializedCandidateGraph"] = materialized_candidate_graph
    writeback["materializedKnowledgeIngestion"] = materialized_knowledge_ingestion
    writeback["closureSummary"] = closure_summary
    task["status"] = status
    task["summary"] = writeback["summary"] or s._trim_text(task.get("summary"), max_length=4000)
    task["result"] = writeback["result"]
    if coverage_summary.get("applicable"):
        task["result"]["coverageSummary"] = coverage_summary
        task["result"]["invalidCandidateIds"] = list(coverage_summary.get("invalidCandidateIds") or [])
        task["result"]["invalidRecordIds"] = list(coverage_summary.get("invalidRecordIds") or [])
    if (
        materialized_sources.get("createdRecordCount")
        or materialized_sources.get("importedCandidateCount")
        or materialized_sources.get("excludedSourceCount")
    ):
        task["result"]["materializedSources"] = materialized_sources
    if materialized_content_extraction.get("extractedCandidateCount"):
        task["result"]["materializedContentExtraction"] = materialized_content_extraction
    if materialized_source_quality.get("assessedCandidateCount"):
        task["result"]["materializedSourceQuality"] = materialized_source_quality
    if materialized_candidate_graph.get("candidateGraphId"):
        task["result"]["materializedCandidateGraph"] = materialized_candidate_graph
    if materialized_knowledge_ingestion.get("stewardPackCandidateId") or materialized_knowledge_ingestion.get("formalKnowledgeItemCount"):
        task["result"]["materializedKnowledgeIngestion"] = materialized_knowledge_ingestion
    task["result"]["closureSummary"] = closure_summary
    task["evidenceRefs"] = writeback["evidenceRefs"]
    task["nextActions"] = writeback["nextActions"]
    task["writeback"] = writeback
    task["taskToolRequired"] = bool(task.get("taskToolRequired", True))
    if task_checklist:
        task["taskChecklist"] = task_checklist
    task["taskToolProgress"] = task_tool_progress or s._source_collection_stage_task_tool_progress(task_checklist)
    task["completionGate"] = completion_gate
    task["writesFormalKnowledge"] = bool(materialized_knowledge_ingestion.get("writesFormalKnowledge"))
    task["writesRag"] = False
    task["writesOfficialGraph"] = bool(materialized_knowledge_ingestion.get("writesOfficialGraph"))
    turn = task.get("turn") if isinstance(task.get("turn"), dict) else {}
    if turn:
        next_turn = dict(turn)
        next_turn["status"] = status
        task["turn"] = next_turn
    task["updatedAt"] = writeback["recordedAt"]
    s._upsert_source_collection_stage_session_task(normalized_team_id, run_id, task)
    s._sync_stage_round_with_source_collection_stage_task(normalized_team_id, run_id, task)
    s._record_workflow_event(
        "source_collection.stage_session_task_writeback",
        normalized_team_id,
        fields={
            "runId": run_id,
            "taskId": normalized_task_id,
            "stageId": task.get("stageId", ""),
            "agentId": task.get("agentId", ""),
            "status": status,
            "sourceLeadCount": materialized_sources.get("sourceLeadCount", 0),
            "createdRecordCount": materialized_sources.get("createdRecordCount", 0),
            "importedCandidateCount": materialized_sources.get("importedCandidateCount", 0),
            "excludedSourceCount": materialized_sources.get("excludedSourceCount", 0),
            "skippedDuplicateCount": materialized_sources.get("skippedDuplicateCount", 0),
            "contentExtractionCandidateCount": materialized_content_extraction.get("extractedCandidateCount", 0),
            "sourceQualityAssessedCandidateCount": materialized_source_quality.get("assessedCandidateCount", 0),
            "coverageProcessedCount": coverage_summary.get("processed", 0) if coverage_summary.get("applicable") else 0,
            "coverageMissingCount": coverage_summary.get("missing", 0) if coverage_summary.get("applicable") else 0,
            "coverageInvalidCount": coverage_summary.get("invalid", 0) if coverage_summary.get("applicable") else 0,
            "sourceQualitySkippedCandidateCount": materialized_source_quality.get("skippedCandidateCount", 0),
            "candidateGraphId": materialized_candidate_graph.get("candidateGraphId", ""),
            "candidateGraphCreatedCount": materialized_candidate_graph.get("createdCandidateGraphCount", 0),
            "candidateGraphReused": bool(materialized_candidate_graph.get("reusedCandidateGraph")),
            "knowledgeIngestionStatus": materialized_knowledge_ingestion.get("status", ""),
            "formalKnowledgeItemCount": materialized_knowledge_ingestion.get("formalKnowledgeItemCount", 0),
            "stewardPackCandidateId": materialized_knowledge_ingestion.get("stewardPackCandidateId", ""),
            "closureUserStatus": closure_summary.get("userStatus", ""),
            "closureArtifactStatus": closure_summary.get("artifactStatus", ""),
            "closureSuccessCount": closure_summary.get("successCount", 0),
        },
        child_log_path=f"artifacts/source-collection-{s._safe_token(run_id, default='run', max_length=96)}-stage-writeback.jsonl",
        child_log_payload=s._source_collection_stage_writeback_child_log_payload(
            team_id=normalized_team_id,
            run_id=run_id,
            task=task,
            materialized_sources=materialized_sources,
            materialized_source_quality=materialized_source_quality,
            materialized_candidate_graph=materialized_candidate_graph,
            materialized_knowledge_ingestion=materialized_knowledge_ingestion,
        ),
    )
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "runId": run_id,
        "taskId": normalized_task_id,
        "stageId": task.get("stageId", ""),
        "agentId": task.get("agentId", ""),
        "agentRole": task.get("agentRole", ""),
        "task": task,
        "writeback": writeback,
        "boundaries": s._source_collection_stage_session_task_boundaries(
            stage_id=s._trim_text(task.get("stageId"), max_length=80),
            agent_role=s._trim_text(task.get("agentRole"), max_length=80),
        ),
    }

def get_source_collection_stage_task_context(
    team_id: str,
    *,
    run_id: str = "",
    stage_id: str = "",
    task_id: str = "",
    max_records: int = 24,
    include_candidates: bool = True,
    record_offset: int = 0,
    record_limit: int | None = None,
    candidate_offset: int = 0,
    candidate_limit: int | None = None,
    context_mode: str = "compact",
) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.assert_team_exists(normalized_team_id)
    normalized_task_id = s._trim_text(task_id, max_length=160)
    task: dict[str, Any] = {}
    task_run_id = ""
    if normalized_task_id:
        found_task, found_run_id = s._find_source_collection_stage_session_task_by_id(normalized_team_id, normalized_task_id)
        if found_task is None or not found_run_id:
            raise s.TeamWorkflowOrchestrationError(f"Stage session task not found: {normalized_task_id}")
        task = s._reconcile_source_collection_stage_session_task(normalized_team_id, found_run_id, dict(found_task))
        task_run_id = found_run_id
    normalized_run_id = (
        s._trim_text(run_id, max_length=128)
        or task_run_id
        or s._trim_text(task.get("runId"), max_length=128)
    )
    normalized_run_id = s._normalize_required_id(normalized_run_id, "Data processing run id is required.")
    normalized_stage_id = s._normalize_source_collection_stage_id(
        s._trim_text(stage_id, max_length=80)
        or s._trim_text(task.get("stageId"), max_length=80),
        default="finding",
    )
    if normalized_stage_id not in s.SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES:
        raise s.TeamWorkflowOrchestrationError(f"Unsupported source collection stage: {normalized_stage_id}")
    normalized_context_mode = s._normalize_source_collection_context_mode(context_mode)
    task_context_mode_raw = s._trim_text(task.get("sourceContextMode"), max_length=40)
    if task_context_mode_raw:
        task_context_mode = s._normalize_source_collection_context_mode(task_context_mode_raw)
        if task_context_mode in {"retry_missing", "retry_evidence"} or (
            normalized_stage_id == "relations" and task_context_mode == "evidence"
        ):
            normalized_context_mode = task_context_mode
    run_bundle = s._source_collection_run_context_bundle(normalized_team_id, normalized_run_id)
    task_agent_id = s._trim_text(task.get("agentId"), max_length=160)
    task_agent_role = s._normalize_source_collection_agent_role(task.get("agentRole"))
    matching_assignments = s._source_collection_matching_assignments(
        run_bundle["assignments"],
        agent_id=task_agent_id,
        agent_role=task_agent_role,
    )
    limit = s._normalize_int(max_records, default=24, minimum=1, maximum=80)
    records = s._rank_source_collection_context_records(
        run_bundle["records"],
        stage_id=normalized_stage_id,
        source_candidates=run_bundle["sourceCandidates"],
    )
    record_page_offset = s._normalize_int(record_offset, default=0, minimum=0, maximum=10000)
    record_page_limit = s._normalize_int(
        record_limit if record_limit is not None else limit,
        default=limit,
        minimum=1,
        maximum=80,
    )
    selected_records = records[record_page_offset:record_page_offset + record_page_limit]
    next_record_offset = record_page_offset + len(selected_records)
    record_has_more = next_record_offset < len(records)
    projected_source_candidates, source_family_summary = project_source_version_families(
        run_bundle["sourceCandidates"],
    )
    inventory_candidates = s._rank_source_collection_context_candidates(
        projected_source_candidates,
        stage_id=normalized_stage_id,
    )
    source_candidates = inventory_candidates if include_candidates else []
    memory_steward_mode = s._source_collection_stage_can_materialize_formal_knowledge(
        normalized_stage_id,
        task_agent_role,
    )
    pageable_candidates = [
        item for item in source_candidates if s._source_quality_bucket(item) == "approved"
    ] if memory_steward_mode else source_candidates
    retry_focus = {}
    retry_source_task = task
    retry_source_task_id = s._trim_text(task.get("retrySourceTaskId"), max_length=160)
    completed_remediation_writeback = bool(
        isinstance(task.get("evidenceRemediationContract"), dict)
        and task.get("evidenceRemediationContract")
        and isinstance(task.get("writeback"), dict)
        and task.get("writeback")
    )
    if retry_source_task_id and not completed_remediation_writeback:
        found_retry_task, found_retry_run_id = s._find_source_collection_stage_session_task_by_id(
            normalized_team_id,
            retry_source_task_id,
        )
        if found_retry_task is not None and found_retry_run_id == normalized_run_id:
            retry_source_task = found_retry_task
    if normalized_context_mode == "retry_missing":
        retry_focus = s._source_collection_stage_retry_focus(retry_source_task, pageable_candidates, records)
        missing_candidate_ids = set(s._normalize_text_list(retry_focus.get("missingCandidateIds"), max_items=500, max_length=160))
        if missing_candidate_ids:
            pageable_candidates = [
                item
                for item in pageable_candidates
                if s._trim_text(item.get("candidateId"), max_length=160) in missing_candidate_ids
            ]
        missing_record_ids = set(s._normalize_text_list(retry_focus.get("missingRecordIds"), max_items=500, max_length=160))
        if missing_record_ids:
            records = [
                item
                for item in records
                if s._trim_text(item.get("recordId"), max_length=160) in missing_record_ids
            ]
            selected_records = records[record_page_offset:record_page_offset + record_page_limit]
            next_record_offset = record_page_offset + len(selected_records)
            record_has_more = next_record_offset < len(records)
    elif normalized_context_mode == "retry_evidence":
        retry_focus = s._source_collection_stage_evidence_retry_focus(retry_source_task, pageable_candidates)
        evidence_gap_ids = set(
            s._normalize_text_list(retry_focus.get("evidenceGapCandidateIds"), max_items=500, max_length=160)
        )
        remediation_contract = (
            task.get("evidenceRemediationContract")
            if isinstance(task.get("evidenceRemediationContract"), dict)
            else {}
        )
        remediation_scope_ids = set(
            s._normalize_text_list(
                remediation_contract.get("scopeCandidateIds"),
                max_items=500,
                max_length=160,
            )
        )
        if remediation_scope_ids:
            evidence_gap_ids &= remediation_scope_ids
            if evidence_gap_ids:
                retry_focus["evidenceGapCandidateIds"] = sorted(evidence_gap_ids)
                retry_focus["missingEvidenceAnchorCount"] = len(evidence_gap_ids)
            else:
                retry_focus = {}
        pageable_candidates = [
            item
            for item in pageable_candidates
            if s._trim_text(item.get("candidateId"), max_length=160) in evidence_gap_ids
        ]
    candidate_page_offset = s._normalize_int(candidate_offset, default=0, minimum=0, maximum=10000)
    candidate_page_limit = s._normalize_int(
        candidate_limit if candidate_limit is not None else limit,
        default=limit,
        minimum=1,
        maximum=80,
    )
    selected_candidates = pageable_candidates[candidate_page_offset:candidate_page_offset + candidate_page_limit]
    next_candidate_offset = candidate_page_offset + len(selected_candidates)
    candidate_has_more = next_candidate_offset < len(pageable_candidates)
    storage_artifacts = s._source_collection_storage_artifacts(normalized_team_id, normalized_run_id)
    selected_unassessed_candidate_ids = [
        s._trim_text(item.get("candidateId"), max_length=128)
        for item in selected_candidates
        if s._trim_text(item.get("candidateId"), max_length=128) and s._source_quality_bucket(item) == "pending"
    ]
    context = {
        "schemaVersion": s.SCHEMA_VERSION,
        "status": "ok",
        "contextKind": "source_collection_stage_task_context",
        "contextMode": normalized_context_mode,
        "teamId": normalized_team_id,
        "runId": normalized_run_id,
        "stageId": normalized_stage_id,
        "taskId": normalized_task_id,
        "agentId": task_agent_id,
        "agentRole": task_agent_role,
        "counts": {
            "recordCount": len(run_bundle["records"]),
            "rawRecordCount": len(run_bundle.get("allRecords") or []),
            "excludedSourceCount": s._source_collection_count((run_bundle.get("excludedSourceSummary") or {}).get("excludedCount")),
            "returnedRecordCount": len(selected_records),
            "candidateCount": len(run_bundle["sourceCandidates"]),
            "independentSourceCount": source_family_summary["independentSourceCount"],
            "versionFamilyCount": source_family_summary["versionFamilyCount"],
            "supersededSourceRecordCount": source_family_summary["supersededRecordCount"],
            "returnedCandidateCount": len(selected_candidates),
            "assignmentCount": len(run_bundle["assignments"]),
            "matchingAssignmentCount": len(matching_assignments),
        },
        "run": s._source_collection_context_run_summary(run_bundle["run"], run_bundle["runStatus"], run_bundle["activeWorkRun"]),
        "task": s._source_collection_context_task_summary(task),
        "assignments": [s._source_collection_context_assignment_summary(item) for item in matching_assignments[:12]],
        "records": [s._source_collection_context_record_summary(item) for item in selected_records],
        "candidates": [
            {
                **s._source_collection_context_candidate_summary(item),
                "sourceVersionFamily": s._normalize_metadata(item.get("sourceVersionFamily")),
            }
            for item in selected_candidates
        ],
        "excludedSourceSummary": s._normalize_metadata(run_bundle.get("excludedSourceSummary")),
        "recordPage": {
            "offset": record_page_offset,
            "limit": record_page_limit,
            "returned": len(selected_records),
            "total": len(records),
            "hasMore": record_has_more,
            "nextOffset": next_record_offset if record_has_more else None,
        },
        "candidatePage": {
            "offset": candidate_page_offset,
            "limit": candidate_page_limit,
            "returned": len(selected_candidates),
            "total": len(pageable_candidates),
            "hasMore": candidate_has_more,
            "nextOffset": next_candidate_offset if candidate_has_more else None,
        },
        "unassessedCandidateIds": selected_unassessed_candidate_ids,
        "allUnassessedCandidateCount": sum(
            1
            for item in inventory_candidates
            if s._source_quality_bucket(item) == "pending"
        ),
        "storageArtifacts": storage_artifacts,
        "writebackContract": task.get("writebackContract") if isinstance(task.get("writebackContract"), dict) else {},
        "evidenceRemediationContract": (
            task.get("evidenceRemediationContract")
            if isinstance(task.get("evidenceRemediationContract"), dict)
            else {}
        ),
        "boundaries": s._source_collection_stage_session_task_boundaries(
            stage_id=normalized_stage_id,
            agent_role=task_agent_role,
        ),
        "usage": {
            "readTool": "source_collection_context_tool",
            "writebackTool": "source_collection_stage_writeback_tool",
            "doNotUse": ["file://", "localhost fetch", "web_fetch_tool for local paths"],
            "fallback": "If required context is missing, write back status=blocked with a short reason.",
        },
    }
    if retry_focus:
        context["retryFocus"] = retry_focus
        context["usage"]["retryInstruction"] = s._trim_text(retry_focus.get("retryInstruction"), max_length=1000)
    if normalized_context_mode in {"evidence", "retry_missing", "retry_evidence"}:
        context["usage"]["evidenceInstruction"] = (
            "candidates[].summary 是搜集阶段保存的摘要或元数据，不等于全文；"
            "quote 只能从 candidates[].summary 逐字复制，不能虚构页码、原文引语或全文结论。"
        )
    if normalized_stage_id == "extraction" or task_agent_role == "source_extractor":
        # Hard writeback contract for the formal claim path: the server
        # rejects completed extraction writebacks without verbatim quote
        # anchors, so the agent must see the exact field names and quote
        # rules before it writes back.
        context["usage"]["extractionWritebackContract"] = (
            "正式 claim 路径的 completed 提炼回写会被服务端逐条校验："
            "(1) 证据状态字段名是 evidenceStatus（不是 verification_status；"
            "verification_status 只属于 Challenge v2 证据卡元数据）；"
            "(2) 候选/记录的存储 summary 非空时，每条非 exclude 条目必须至少带一个逐字 quote 锚："
            "嵌套 claims[]/keyFindings[] 项含 quote，或 evidenceRefs[] 项含 {id, quote}；"
            "(3) quote 必须是 candidates[].summary 的逐字子串，从上下文原样复制，禁止改写；"
            "引述存储摘要时写 evidenceStatus=verified_abstract；"
            "(4) 存储 summary 为空的来源必须声明 evidenceStatus=missing_evidence_anchor（诚实跳过，不物化）；"
            "(5) 缺少逐字 quote 锚的 completed 回写会被拒绝并要求重写。"
        )
    context["usage"]["continuationHint"] = s._source_collection_context_continuation_hint(
        context["candidatePage"],
        context_mode=context["contextMode"],
    )
    context["usage"]["recordContinuationHint"] = s._source_collection_context_record_continuation_hint(
        context["recordPage"],
        context_mode=context["contextMode"],
    )
    if memory_steward_mode:
        context["stewardActionPacket"] = s._source_collection_memory_steward_action_packet(
            inventory_candidates,
            writeback_contract=context["writebackContract"],
        )
        context["usage"]["fallback"] = (
            "Use stewardActionPacket. Do not infer hidden or truncated candidates; "
            "if no approvedCandidateIds are present, write back status=blocked with a short reason."
        )
        context["usage"]["continuationHint"] = s._source_collection_context_continuation_hint(
            context["candidatePage"],
            context_mode=context["contextMode"],
        )
    if context["contextMode"] == "full":
        return context
    return s._compact_source_collection_stage_task_context(context)

def _materialize_extraction_claim_evidence_after_reconcile(
    team_id: str,
    run_id: str,
    reconciled_task: dict[str, Any],
) -> dict[str, Any]:
    """Bridge a canonical completed extraction stage task into the claim ledger.

    Graph-dispatch turn finalization materializes extraction claims in
    ``agent_turn_completion``; stage tasks opened through the session-message
    path (POST /source-collection-runs/{run}/stage-session-tasks) finalize in
    ``reconcile_source_collection_stage_session_task_after_turn``, which
    previously never crossed the Evidence Store boundary, leaving completed
    extraction tasks without claim-ledger rows.  The materializer is
    idempotent (content-hash claim ids), so both paths may call it for the
    same task.  A failure is recorded as a workflow event and returned for
    diagnosis but never flips the completed task status here or blocks the
    reconcile result; the zero-claim fail-loud parking lives in
    ``_apply_extraction_claim_materialization_visibility_and_gate``.
    """
    s = _service()
    normalized_task_id = s._trim_text(reconciled_task.get("taskId"), max_length=160)
    stage_id = s._trim_text(reconciled_task.get("stageId"), max_length=80)
    task_status = s._trim_text(reconciled_task.get("status"), max_length=80)
    if stage_id.lower() != "extraction" or task_status != "completed":
        return {"status": "skipped", "reason": "not_completed_extraction_task"}
    workflow_run_id = s._trim_text(reconciled_task.get("workflowRunId"), max_length=160)
    if not workflow_run_id:
        # Extraction tasks opened by hand carry no workflowRunId field; the
        # canonical source run scope is the one authoritative fallback for
        # their workflow binding.  An absent binding stays empty and the
        # materializer fails closed with a clear scope error below.
        try:
            from core.web.services import data_processing_service

            run = data_processing_service.get_processing_run(run_id)
        except Exception:  # noqa: BLE001 - absent run keeps the empty scope and fails closed downstream
            run = {}
        run_scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
        workflow_run_id = s._trim_text(run_scope.get("workflowRunId"), max_length=160)
    try:
        from ..research_runtime.agent_claim_evidence_materializer import (
            materialize_completed_extraction_task,
        )

        materialized = materialize_completed_extraction_task(
            team_id=team_id,
            workflow_run_id=workflow_run_id,
            source_collection_run_id=run_id,
            task_id=normalized_task_id,
        )
    except Exception as exc:  # noqa: BLE001 - diagnostic event, never a task-status change
        s._record_workflow_event(
            "source_collection.stage_session_task_claim_materialization_failed",
            team_id,
            fields={
                "runId": run_id,
                "taskId": normalized_task_id,
                "stageId": stage_id,
                "taskStatus": task_status,
                "workflowRunId": workflow_run_id,
                "errorType": type(exc).__name__,
                "error": s._trim_text(str(exc), max_length=400),
            },
            level="warning",
            outcome="failed",
        )
        return {
            "status": "failed",
            "workflowRunId": workflow_run_id,
            "errorType": type(exc).__name__,
        }
    return {
        "status": "materialized",
        "workflowRunId": workflow_run_id,
        "claimEvidenceCount": len(materialized) if isinstance(materialized, list) else 0,
    }


def _run_has_summary_bearing_source_collection_candidate(team_id: str, run_id: str) -> bool:
    """True when the run holds at least one candidate with a stored summary.

    Such summaries are the verbatim quote material extraction writebacks must
    anchor to, so their presence with zero materialized claims is exactly the
    silent-zero incident shape.
    """
    s = _service()
    for candidate in s._source_collection_candidates_for_run(team_id, run_id):
        if s._trim_text(candidate.get("summary"), max_length=4000):
            return True
    return False


def _apply_extraction_claim_materialization_visibility_and_gate(
    team_id: str,
    run_id: str,
    task: dict[str, Any],
    claim_materialization: dict[str, Any],
) -> dict[str, Any]:
    """Persist the materialization outcome on the canonical task; park zero-claim completions.

    Production incident (stagetask-20260831142807-d31d5a7d): a completed
    extraction writeback without verbatim quote anchors materialized zero
    claim-evidence rows while the task record showed nothing — the
    ``claimMaterialization`` result lived only on the reconcile response, so
    the run silently lost its evidence.  This boundary (1) writes the
    materialization outcome onto the canonical task record, and (2) fails
    loud: a completed extraction task that materialized zero claims while the
    run holds summary-bearing candidates is parked at ``needs_review`` — the
    stage-task status equivalent of a never-auto-reconciled needs_continue
    stop — with explicit remediation.  Materialization failures keep their
    diagnostic-only contract (workflow event, no status flip); only a
    successful materialization with zero claims trips the gate.
    """
    s = _service()
    materialization_status = s._trim_text(claim_materialization.get("status"), max_length=80)
    if materialization_status not in {"materialized", "failed"}:
        return task
    would_gate = (
        materialization_status == "materialized"
        and not s._source_collection_count(claim_materialization.get("claimEvidenceCount"))
        and s._trim_text(task.get("status"), max_length=80) == "completed"
        and _run_has_summary_bearing_source_collection_candidate(team_id, run_id)
    )
    existing = task.get("claimMaterialization") if isinstance(task.get("claimMaterialization"), dict) else {}
    if (
        existing.get("status") == materialization_status
        and existing.get("claimEvidenceCount") == claim_materialization.get("claimEvidenceCount")
        and bool(existing.get("gate")) == would_gate
    ):
        # Same outcome already recorded on the canonical task; repeated
        # reconciles (adapter dispatch, turn diagnostics, graph finalize all
        # funnel through here) must not churn updatedAt with fresh stamps.
        return task
    recorded = {**claim_materialization, "recordedAt": s.utc_now_iso()}
    next_task = dict(task)
    next_result = dict(task.get("result")) if isinstance(task.get("result"), dict) else {}
    next_result["claimMaterialization"] = recorded
    next_task["result"] = next_result
    next_task["claimMaterialization"] = recorded
    if materialization_status == "materialized" and not s._source_collection_count(
        recorded.get("claimEvidenceCount")
    ) and _run_has_summary_bearing_source_collection_candidate(team_id, run_id):
        remediation = (
            "提炼回写缺少逐字 quote 锚：候选存储摘要非空但物化出 0 条 claim 证据。"
            "请重新回写 completed：每条非 exclude 条目至少带一个 quote 锚"
            "（嵌套 claims[]/keyFindings[] 项含 quote，或 evidenceRefs[] 项含 {id, quote}），"
            "quote 必须从 candidates[].summary 逐字复制，并写 evidenceStatus=verified_abstract。"
        )
        recorded["gate"] = "needs_quote_anchor_retry"
        recorded["remediation"] = remediation
        next_result["claimMaterializationRemediation"] = remediation
        previous_status = s._trim_text(next_task.get("status"), max_length=80)
        next_task["status"] = "needs_review"
        next_writeback = dict(task.get("writeback")) if isinstance(task.get("writeback"), dict) else {}
        next_writeback["status"] = "needs_review"
        next_writeback["agentRequestedStatus"] = "needs_review"
        next_task["writeback"] = next_writeback
        next_turn = next_task.get("turn") if isinstance(next_task.get("turn"), dict) else {}
        if next_turn:
            updated_turn = dict(next_turn)
            updated_turn["status"] = "needs_review"
            next_task["turn"] = updated_turn
        next_task["updatedAt"] = recorded["recordedAt"]
        s._record_workflow_event(
            "source_collection.stage_session_task_claim_materialization_gate_parked",
            team_id,
            fields={
                "runId": run_id,
                "taskId": s._trim_text(next_task.get("taskId"), max_length=160),
                "stageId": s._trim_text(next_task.get("stageId"), max_length=80),
                "previousStatus": previous_status,
                "status": "needs_review",
                "claimEvidenceCount": 0,
                "workflowRunId": s._trim_text(recorded.get("workflowRunId"), max_length=160),
            },
            level="warning",
            outcome="needs_review",
        )
    s._upsert_source_collection_stage_session_task(team_id, run_id, next_task)
    if next_task.get("status") != task.get("status"):
        s._sync_stage_round_with_source_collection_stage_task(team_id, run_id, next_task)
    return next_task

def reconcile_source_collection_stage_session_task_after_turn(
    team_id: str,
    task_id: str,
    *,
    run_id: str = "",
    session_id: str = "",
    turn_id: str = "",
    final_status: str = "",
    llm_usage: dict[str, Any] | None = None,
    model_invocation_receipt: Any = None,
    stage_id: str | None = None,
    model_policy_sha256: str | None = None,
    reason: str = "session_turn_completed",
) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_task_id = s._trim_text(task_id, max_length=160)
    if not normalized_task_id:
        return {"schemaVersion": s.SCHEMA_VERSION, "status": "skipped", "reason": "missing_task_id", "changed": False}
    found_task, found_run_id = s._find_source_collection_stage_session_task_by_id(normalized_team_id, normalized_task_id)
    if found_task is None or not found_run_id:
        return {
            "schemaVersion": s.SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "taskId": normalized_task_id,
            "status": "not_found",
            "reason": "stage_session_task_not_found",
            "changed": False,
        }
    normalized_run_id = s._trim_text(run_id, max_length=128)
    if normalized_run_id and normalized_run_id != found_run_id:
        return {
            "schemaVersion": s.SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "runId": found_run_id,
            "requestedRunId": normalized_run_id,
            "taskId": normalized_task_id,
            "status": "skipped",
            "reason": "run_id_mismatch",
            "changed": False,
        }
    normalized_session_id = s._trim_text(session_id, max_length=160)
    task_turn = found_task.get("turn") if isinstance(found_task.get("turn"), dict) else {}
    task_session_id = s._trim_text(found_task.get("sessionId") or task_turn.get("sessionId"), max_length=160)
    if normalized_session_id and task_session_id and normalized_session_id != task_session_id:
        return {
            "schemaVersion": s.SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "runId": found_run_id,
            "taskId": normalized_task_id,
            "status": "skipped",
            "reason": "session_id_mismatch",
            "changed": False,
        }
    normalized_turn_id = s._trim_text(turn_id, max_length=200)
    task_turn_id = s._trim_text(task_turn.get("turnId"), max_length=200)
    original_found_task = dict(found_task)
    if normalized_turn_id and task_turn_id and normalized_turn_id != task_turn_id:
        continuation_task = s._source_collection_stage_session_task_with_continuation_turn(
            found_task,
            session_id=normalized_session_id or task_session_id,
            turn_id=normalized_turn_id,
        )
        if continuation_task is None:
            return {
                "schemaVersion": s.SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "runId": found_run_id,
                "taskId": normalized_task_id,
                "status": "skipped",
                "reason": "turn_id_mismatch",
                "changed": False,
            }
        found_task = continuation_task
        task_turn = found_task.get("turn") if isinstance(found_task.get("turn"), dict) else {}
        task_turn_id = s._trim_text(task_turn.get("turnId"), max_length=200)
        s._upsert_source_collection_stage_session_task(normalized_team_id, found_run_id, found_task)
        s._record_workflow_event(
            "source_collection.stage_session_task_continuation_turn_adopted",
            normalized_team_id,
            fields={
                "runId": found_run_id,
                "taskId": normalized_task_id,
                "sessionId": task_session_id,
                "previousTurnId": s._trim_text(task_turn.get("previousTurnId"), max_length=200),
                "turnId": task_turn_id,
            },
            level="info",
            outcome="reconciled",
            lifecycle=True,
        )
    before_task = dict(found_task)
    before_status = s._trim_text(before_task.get("status"), max_length=80)
    before_gate = before_task.get("completionGate") if isinstance(before_task.get("completionGate"), dict) else {}
    reconciled = s._reconcile_source_collection_stage_session_task(normalized_team_id, found_run_id, dict(found_task))
    official_model_evidence = s.register_challenge_task_model_evidence(
        normalized_team_id,
        reconciled,
        final_status=final_status,
        llm_usage=llm_usage,
        model_invocation_receipt=model_invocation_receipt,
        stage_id=stage_id,
        model_policy_sha256=model_policy_sha256,
    )
    after_gate = reconciled.get("completionGate") if isinstance(reconciled.get("completionGate"), dict) else {}
    task_tool_progress = reconciled.get("taskToolProgress") if isinstance(reconciled.get("taskToolProgress"), dict) else {}
    reconciled_turn = reconciled.get("turn") if isinstance(reconciled.get("turn"), dict) else {}
    claim_materialization = _materialize_extraction_claim_evidence_after_reconcile(
        normalized_team_id,
        found_run_id,
        reconciled,
    )
    reconciled = _apply_extraction_claim_materialization_visibility_and_gate(
        normalized_team_id,
        found_run_id,
        reconciled,
        claim_materialization,
    )
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "runId": found_run_id,
        "taskId": normalized_task_id,
        "sessionId": task_session_id,
        "turnId": s._trim_text(reconciled_turn.get("turnId"), max_length=200) or task_turn_id,
        "status": "reconciled",
        "reason": s._trim_text(reason, max_length=120) or "session_turn_completed",
        "changed": reconciled != original_found_task,
        "previousTaskStatus": before_status,
        "taskStatus": s._trim_text(reconciled.get("status"), max_length=80),
        "previousCompletionGatePassed": bool(before_gate.get("passed")),
        "completionGatePassed": bool(after_gate.get("passed")),
        "taskChecklistComplete": bool(after_gate.get("taskChecklistComplete")),
        "artifactComplete": bool(after_gate.get("artifactComplete")),
        "taskToolProgress": task_tool_progress,
        "officialModelEvidence": official_model_evidence or {},
        "claimMaterialization": claim_materialization,
    }
