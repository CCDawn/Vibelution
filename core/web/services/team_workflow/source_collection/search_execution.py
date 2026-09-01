"""Source-collection search execution kernel.

Claim scope: background search thread target, search impl, query execution,
quality gate, record mapping, and post-search stage-round sync helpers.

Public entrypoints remain in ``runs.py``; this module owns the heavy bodies
that used to live only on ``team_workflow_orchestration_service``.

Late-bound facade keeps route imports and monkeypatches on
``team_workflow_orchestration_service`` stable.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any


def _service():
    from core.web.services import team_workflow_orchestration_service

    return team_workflow_orchestration_service


def _source_collection_search_background_response(
    *,
    team_id: str,
    run_id: str,
    provider: str,
    run: dict[str, Any],
    run_status: dict[str, Any],
    storage_artifacts: dict[str, str],
    assignments: list[dict[str, Any]],
    records: list[dict[str, Any]],
    active_snapshot: dict[str, Any],
    already_running: bool,
) -> dict[str, Any]:
    s = _service()
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": team_id,
        "runId": run_id,
        "status": "accepted",
        "executionMode": "background",
        "accepted": True,
        "alreadyRunning": already_running,
        "provider": provider,
        "executedQueryCount": 0,
        "skippedQueryCount": 0,
        "failedQueryCount": 0,
        "resultCount": 0,
        "recordCount": len(records),
        "outputCount": 0,
        "importedCount": 0,
        "run": run,
        "runStatus": run_status,
        "storageArtifacts": storage_artifacts,
        "assignments": assignments,
        "outputs": [],
        "createdRecords": [],
        "imported": [],
        "executionEvents": [],
        "activeWorkRun": active_snapshot,
        "boundaries": {
            "externalSearchTriggered": False,
            "externalSearchQueued": True,
            "metadataOnlyDownload": True,
            "writesFormalKnowledge": False,
            "writesRag": False,
            "writesOfficialGraph": False,
        },
        "nextActions": [
            "The background source collection worker is running and will write DataRecords and source_manifest candidates.",
            "Keep this page open or return later; run status and assignments can refresh without blocking the request.",
        ],
    }


def _source_collection_circuit_provider_order(run: dict[str, Any]) -> list[str]:
    """Read the evidence-request circuit provider order off a rewrite run.

    Returns [] for every run without ``metadata.searchCircuit`` (all legacy
    and original-path runs), keeping the default provider order unchanged.
    """
    s = _service()
    metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    circuit = metadata.get("searchCircuit") if isinstance(metadata.get("searchCircuit"), dict) else {}
    order = [s._trim_text(item, max_length=80) for item in list(circuit.get("providerOrder") or [])]
    supported = [item for item in order if item in s.SOURCE_COLLECTION_SEARCH_PROVIDERS]
    return list(dict.fromkeys(supported))


def _run_source_collection_search_background(team_id: str, run_id: str, payload: dict[str, Any]) -> None:
    s = _service()
    try:
        result = s.execute_source_collection_search(team_id, run_id, payload)
    except Exception as exc:
        s._record_workflow_event(
            "source_collection.search_background_failed",
            team_id,
            fields={
                "runId": run_id,
                "errorType": type(exc).__name__,
                "error": s._trim_text(exc, max_length=500),
            },
        )
        return
    s._record_workflow_event(
        "source_collection.search_background_completed",
        team_id,
        fields={
            "runId": run_id,
            "status": s._trim_text(result.get("status"), max_length=80),
            "executedQueryCount": s._source_collection_count(result.get("executedQueryCount")),
            "recordCount": s._source_collection_count(result.get("recordCount")),
            "importedCount": s._source_collection_count(result.get("importedCount")),
        },
    )


def _execute_source_collection_search_impl(team_id: str, run_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_run_id = s._normalize_required_id(run_id, "Data processing run id is required.")
    s.team_service.get_team(normalized_team_id)
    request_payload = payload if isinstance(payload, dict) else {}
    requested_provider = s._trim_text(request_payload.get("provider"), max_length=80)
    if requested_provider and requested_provider not in s.SOURCE_COLLECTION_SEARCH_PROVIDERS:
        raise s.TeamWorkflowOrchestrationError(f"Unsupported source collection search provider: {requested_provider}")
    providers = (requested_provider,) if requested_provider else tuple(s.SOURCE_COLLECTION_SEARCH_PROVIDERS)
    provider = requested_provider or s.SOURCE_COLLECTION_SEARCH_PROVIDERS[0]
    max_queries = s._normalize_int(
        request_payload.get("maxQueries"),
        default=s.SOURCE_COLLECTION_SEARCH_EXECUTION_DEFAULT_MAX_QUERIES,
        minimum=1,
        maximum=s.SOURCE_COLLECTION_SEARCH_EXECUTION_MAX_QUERIES,
    )
    max_results_per_query = s._normalize_int(
        request_payload.get("maxResultsPerQuery"),
        default=s.SOURCE_COLLECTION_SEARCH_EXECUTION_DEFAULT_RESULTS_PER_QUERY,
        minimum=1,
        maximum=s.SOURCE_COLLECTION_SEARCH_EXECUTION_MAX_RESULTS_PER_QUERY,
    )
    target_assignment_ids = set(s._normalize_text_list(request_payload.get("assignmentIds"), max_items=16, max_length=128))
    target_agent_role = s._normalize_source_collection_agent_role(request_payload.get("agentRole"))
    force = bool(request_payload.get("force"))
    try:
        run = s.data_processing_service.get_processing_run(normalized_run_id)
        assignments_payload = s.data_processing_service.list_collection_assignments(normalized_run_id)
        records_payload = s.data_processing_service.list_records(normalized_run_id)
        outputs_payload = s.data_processing_service.list_collection_outputs(normalized_run_id)
    except s.data_processing_service.DataProcessingError as exc:
        raise s.TeamWorkflowOrchestrationError(str(exc)) from exc
    run_scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    run_team_id = s._trim_text(run_scope.get("teamId"), max_length=128)
    if run_team_id and run_team_id != normalized_team_id:
        raise s.TeamWorkflowOrchestrationError("Data processing run does not belong to this team.")
    if not requested_provider:
        circuit_provider_order = _source_collection_circuit_provider_order(run)
        if circuit_provider_order:
            # Evidence-request circuit rewrite run: execute the variant's
            # provider priority order instead of the default order.  Only
            # runs carrying run.metadata.searchCircuit are affected.
            providers = tuple(circuit_provider_order)
            provider = circuit_provider_order[0]
    assignments = [item for item in list(assignments_payload.get("assignments") or []) if isinstance(item, dict)]
    existing_records = [item for item in list(records_payload.get("records") or []) if isinstance(item, dict)]
    existing_outputs = [item for item in list(outputs_payload.get("outputs") or []) if isinstance(item, dict)]
    existing_query_ids = s._source_collection_attempted_query_ids(existing_records, existing_outputs)
    existing_identity_records = s._source_collection_existing_identity_records(existing_records)
    execution_events: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    created_records: list[dict[str, Any]] = []
    imported: list[dict[str, Any]] = []
    storage_artifacts = s._source_collection_storage_artifacts(normalized_team_id, normalized_run_id)
    attempted_query_count = 0
    executed_query_count = 0
    skipped_query_count = 0
    failed_query_count = 0
    result_count = 0
    rejected_result_count = 0
    skipped_duplicate_count = 0
    filtered_excluded_count = 0
    duplicate_source_keys: list[str] = []
    excluded_source_keys: list[str] = []
    cancelled = str(run.get("status") or "").strip().lower() == "cancelled"

    for assignment in assignments:
        if cancelled or attempted_query_count >= max_queries:
            break
        assignment_id = s._trim_text(assignment.get("assignmentId"), max_length=128)
        agent_role = s._normalize_source_collection_agent_role(assignment.get("agentRole"))
        if agent_role not in s.SOURCE_COLLECTION_SEARCH_EXECUTION_AGENT_ROLES:
            continue
        assignment = dict(assignment)
        assignment["agentRole"] = agent_role
        if target_assignment_ids and assignment_id not in target_assignment_ids:
            continue
        if target_agent_role and agent_role != target_agent_role:
            continue
        if not force and str(assignment.get("status") or "") not in {"open", "in_progress", "returned"}:
            continue
        assigned_queries = s._source_collection_assigned_queries(assignment)
        if not assigned_queries:
            execution_events.append(
                s._source_collection_execution_event(
                    "assignment.no_query",
                    assignment=assignment,
                    status="blocked",
                    title=f"{agent_role or assignment_id} has no assigned query",
                    summary="This assignment has no query seed in its source collection scope.",
                    refs=[assignment_id],
                )
            )
            continue
        attempted_query_ids: list[str] = []
        assignment_skipped_duplicate_count = 0
        assignment_query_ids = {
            s._trim_text(item.get("queryId"), max_length=160)
            for item in assigned_queries
            if s._trim_text(item.get("queryId"), max_length=160)
        }
        for query in assigned_queries:
            if attempted_query_count >= max_queries:
                break
            try:
                cancelled = (
                    str(
                        s.data_processing_service.get_processing_run(normalized_run_id).get("status")
                        or ""
                    ).strip().lower()
                    == "cancelled"
                )
            except s.data_processing_service.DataProcessingError:
                cancelled = True
            if cancelled:
                break
            query_id = s._trim_text(query.get("queryId"), max_length=160)
            query_text = s._trim_text(query.get("query"), max_length=1000)
            if not query_id or not query_text:
                continue
            if query_id in existing_query_ids and not force:
                skipped_query_count += 1
                continue
            attempted_query_ids.append(query_id)
            query_records: list[dict[str, Any]] = []
            query_skipped_duplicate_count = 0
            query_filtered_excluded_count = 0
            query_executed_providers: list[str] = []
            query_failed_provider_count = 0
            for query_provider in providers:
                search_response = s._execute_source_collection_query(query, max_results=max_results_per_query, provider=query_provider)
                if search_response.get("error"):
                    query_failed_provider_count += 1
                    execution_events.append(
                        s._source_collection_execution_event(
                            "search.failed",
                            assignment=assignment,
                            query=query,
                            status="blocked",
                            title=f"Search failed: {query_text}",
                            summary=s._trim_text(search_response.get("error"), max_length=500),
                            refs=[query_id, query_provider],
                            provider=query_provider,
                        )
                    )
                    continue
                query_executed_providers.append(query_provider)
                existing_query_ids.add(query_id)
                search_results = [item for item in list(search_response.get("results") or []) if isinstance(item, dict)]
                result_count += len(search_results)
                execution_events.append(
                    s._source_collection_execution_event(
                        "search.executed",
                        assignment=assignment,
                        query=query,
                        status="completed" if search_results else "returned",
                        title=f"Searched {query_provider}: {query_text}",
                        summary=f"Fetched {len(search_results)} metadata result(s); full text was not downloaded.",
                        refs=[query_id, s._trim_text(search_response.get("searchUrl"), max_length=240)],
                        raw_location=s._trim_text(search_response.get("searchUrl"), max_length=1000),
                        provider=query_provider,
                    )
                )
                for result in search_results:
                    quality_gate = s._source_collection_search_result_quality_gate(query, result)
                    if not bool(quality_gate.get("accepted")):
                        rejected_result_count += 1
                        execution_events.append(
                            s._source_collection_execution_event(
                                "search.low_quality_rejected",
                                assignment=assignment,
                                query=query,
                                status="blocked",
                                title=f"Rejected low-quality source: {result.get('title') or result.get('sourceRef')}",
                                summary=(
                                    "The metadata result did not pass query relevance and quality gates: "
                                    + ", ".join(str(reason) for reason in list(quality_gate.get("reasons") or [])[:4])
                                ),
                                refs=[
                                    s._trim_text(result.get("sourceRef"), max_length=240),
                                    *[
                                        f"matched:{term}"
                                        for term in list(quality_gate.get("matchedTerms") or [])[:4]
                                    ],
                                    *[
                                        f"blocked:{term}"
                                        for term in list(quality_gate.get("blockingTerms") or [])[:4]
                                    ],
                                ],
                                raw_location=s._trim_text(result.get("rawLocation") or result.get("sourceRef"), max_length=1000),
                                provider=query_provider,
                            )
                        )
                        continue
                    result_quality_signals = s._normalize_metadata(result.get("qualitySignals"))
                    result_quality_signals["sourceCollectionQualityGate"] = quality_gate
                    result = dict(result)
                    result["qualitySignals"] = result_quality_signals
                    candidate_record = s._source_collection_record_from_search_result(
                        normalized_team_id,
                        run,
                        assignment,
                        query,
                        result,
                        provider=query_provider,
                        search_url=s._trim_text(search_response.get("searchUrl"), max_length=1000),
                    )
                    source_identity_key = s._source_collection_record_identity_key(candidate_record)
                    excluded_entry = s._source_collection_exclusion_match(normalized_team_id, run, source_identity_key)
                    if excluded_entry is not None:
                        filtered_excluded_count += 1
                        query_filtered_excluded_count += 1
                        if source_identity_key:
                            excluded_source_keys.append(source_identity_key)
                        s._record_source_collection_exclusion_hit(
                            normalized_team_id,
                            run,
                            candidate_record,
                            excluded_entry,
                        )
                        execution_events.append(
                            s._source_collection_execution_event(
                                "search.excluded_source_filtered",
                                assignment=assignment,
                                query=query,
                                status="completed",
                                title=f"Filtered excluded source: {candidate_record.get('title') or candidate_record.get('sourceRef')}",
                                summary=(
                                    "This result matched the source exclusion ledger for the current topic and was not written back into the active source collection flow."
                                ),
                                refs=[source_identity_key, s._trim_text(excluded_entry.get("reason"), max_length=120)],
                                raw_location=s._trim_text(candidate_record.get("rawLocation") or candidate_record.get("sourceRef"), max_length=1000),
                                provider=query_provider,
                            )
                        )
                        continue
                    duplicate_record = existing_identity_records.get(source_identity_key) if source_identity_key else None
                    if duplicate_record is not None:
                        skipped_duplicate_count += 1
                        assignment_skipped_duplicate_count += 1
                        query_skipped_duplicate_count += 1
                        if source_identity_key:
                            duplicate_source_keys.append(source_identity_key)
                        execution_events.append(
                            s._source_collection_execution_event(
                                "search.duplicate_skipped",
                                assignment=assignment,
                                query=query,
                                status="completed",
                                title=f"Skipped duplicate source: {candidate_record.get('title') or candidate_record.get('sourceRef')}",
                                summary="The search result matched an existing DataRecord source identity and was not written again.",
                                refs=[source_identity_key, duplicate_record.get("recordId", "")],
                                raw_location=s._trim_text(candidate_record.get("rawLocation") or candidate_record.get("sourceRef"), max_length=1000),
                                provider=query_provider,
                            )
                        )
                        continue
                    if source_identity_key:
                        existing_identity_records[source_identity_key] = candidate_record
                    query_records.append(candidate_record)
            if not query_executed_providers and query_failed_provider_count:
                # Every provider failed for this query: keep the query runnable
                # for a later batch instead of recording an empty output.
                attempted_query_count += 1
                failed_query_count += 1
                continue
            attempted_query_count += 1
            if query_executed_providers:
                # Query-level counting: a query that succeeded on at least one
                # provider counts as executed once.
                executed_query_count += 1
            remaining_query_ids = assignment_query_ids - existing_query_ids
            if query_records:
                output_status = "completed" if not remaining_query_ids else "returned"
                try:
                    output_response = s.data_processing_service.record_collection_output(
                        normalized_run_id,
                        assignment_id,
                        {
                            "status": output_status,
                            "records": query_records,
                            "notes": "Automated source collection search executed one metadata-only query and wrote DataRecords for review.",
                            "qualitySignals": {
                                "searchProvider": query_executed_providers[0] if len(query_executed_providers) == 1 else "multi_provider",
                                "searchProviders": query_executed_providers,
                                "executedQueryCount": max(1, len(query_executed_providers)),
                                "queryId": query_id,
                                "metadataOnlyDownload": True,
                                "remainingQueryCount": len(remaining_query_ids),
                            },
                        },
                    )
                except s.data_processing_service.DataProcessingError as exc:
                    raise s.TeamWorkflowOrchestrationError(str(exc)) from exc
                outputs.append(output_response["output"])
                created_records.extend(output_response["createdRecords"])
                for index, record in enumerate(output_response["createdRecords"]):
                    original_record = query_records[index] if index < len(query_records) else {}
                    trace = s._source_collection_record_search_trace(original_record)
                    execution_events.append(
                        s._source_collection_execution_event(
                            "storage.data_record_written",
                            assignment=assignment,
                            query=trace,
                            status="completed",
                            title=f"Stored DataRecord: {record.get('title') or record.get('recordId')}",
                            summary="The search result was stored in the generic data processing run before candidate import.",
                            refs=[record.get("recordId", ""), record.get("sourceRef", "") or record.get("rawLocation", "")],
                            storage_refs=[*s._source_collection_storage_refs(run), storage_artifacts["recordsPath"]],
                            provider=s._trim_text(trace.get("searchProvider"), max_length=80),
                        )
                    )
                    import_response = s.import_data_record_as_source_candidate(
                        normalized_team_id,
                        normalized_run_id,
                        str(record.get("recordId") or ""),
                        {
                            "createdByAgent": s._trim_text(assignment.get("agentId"), max_length=160) or agent_role or "source_collection_search_executor",
                            "tags": ["source_collection", "search_execution", agent_role],
                            "metadata": {
                                "sourceCollectionSearchExecution": True,
                                "searchProvider": s._trim_text(trace.get("searchProvider"), max_length=80) or provider,
                                "metadataOnlyDownload": True,
                                "assignmentId": assignment_id,
                                "agentRole": agent_role,
                                "queryId": s._trim_text(trace.get("queryId"), max_length=160),
                                "query": s._trim_text(trace.get("query"), max_length=1000),
                            },
                        },
                    )
                    if import_response.get("duplicate"):
                        skipped_duplicate_count += 1
                        candidate = import_response.get("candidate") if isinstance(import_response.get("candidate"), dict) else {}
                        candidate_metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
                        duplicate_key = s._trim_text(candidate_metadata.get("sourceIdentityKey"), max_length=200)
                        if duplicate_key:
                            duplicate_source_keys.append(duplicate_key)
                        execution_events.append(
                            s._source_collection_execution_event(
                                "storage.source_manifest_duplicate_skipped",
                                assignment=assignment,
                                query=trace,
                                status="completed",
                                title=f"Skipped duplicate source_manifest: {candidate.get('title') or candidate.get('candidateId')}",
                                summary="The DataRecord matched an existing source_manifest identity and was not imported again.",
                                refs=[candidate.get("candidateId", ""), str(record.get("recordId") or "")],
                                storage_refs=[storage_artifacts["candidatesPath"], storage_artifacts["candidateStorePath"]],
                                provider=s._trim_text(trace.get("searchProvider"), max_length=80),
                            )
                        )
                    else:
                        imported.append(import_response)
                        execution_events.append(
                            s._source_collection_execution_event(
                                "storage.source_manifest_imported",
                                assignment=assignment,
                                query=trace,
                                status="completed",
                                title=f"Imported source_manifest: {import_response['candidate'].get('title')}",
                                summary="The DataRecord was imported as a source_manifest candidate, still outside formal Team Knowledge/RAG/official graph.",
                                refs=[import_response["candidate"].get("candidateId", ""), str(record.get("recordId") or "")],
                                storage_refs=[storage_artifacts["candidatesPath"], storage_artifacts["candidateStorePath"]],
                                provider=s._trim_text(trace.get("searchProvider"), max_length=80),
                            )
                        )
            elif query_id in attempted_query_ids:
                duplicate_only = query_skipped_duplicate_count > 0
                excluded_only = query_filtered_excluded_count > 0
                no_record_notes = (
                    f"Automated metadata search only found {query_skipped_duplicate_count} duplicate source(s) already present in this run; no repair is required."
                    if duplicate_only
                    else (
                        f"Automated metadata search only found {query_filtered_excluded_count} source(s) already excluded for this topic; no active record was created."
                        if excluded_only
                        else "Automated metadata search returned no importable records for this query."
                    )
                )
                try:
                    output_response = s.data_processing_service.record_collection_output(
                        normalized_run_id,
                        assignment_id,
                        {
                            "status": "completed" if (duplicate_only or excluded_only) and not remaining_query_ids else "returned",
                            "records": [],
                            "notes": no_record_notes,
                            "blockingIssues": [] if (duplicate_only or excluded_only) else ["no_importable_search_result"],
                            "qualitySignals": {
                                "searchProvider": query_executed_providers[0] if len(query_executed_providers) == 1 else "multi_provider",
                                "searchProviders": query_executed_providers,
                                "executedQueryCount": max(1, len(query_executed_providers)),
                                "metadataOnlyDownload": True,
                                "queryId": query_id,
                                "remainingQueryCount": len(remaining_query_ids),
                                "skippedDuplicateCount": query_skipped_duplicate_count,
                                "filteredExcludedCount": query_filtered_excluded_count,
                                "duplicateOnly": duplicate_only,
                                "excludedOnly": excluded_only,
                            },
                        },
                    )
                except s.data_processing_service.DataProcessingError as exc:
                    raise s.TeamWorkflowOrchestrationError(str(exc)) from exc
                outputs.append(output_response["output"])
                if duplicate_only:
                    execution_events.append(
                        s._source_collection_execution_event(
                            "search.duplicates_only_output_recorded",
                            assignment=assignment,
                            query=query,
                            status="completed",
                            title=f"Recorded duplicate-only query result: {query_text}",
                            summary=no_record_notes,
                            refs=[query_id],
                            storage_refs=[storage_artifacts["recordsPath"]],
                        )
                    )
                if excluded_only:
                    execution_events.append(
                        s._source_collection_execution_event(
                            "search.excluded_sources_only_output_recorded",
                            assignment=assignment,
                            query=query,
                            status="completed",
                            title=f"Recorded excluded-only query result: {query_text}",
                            summary=no_record_notes,
                            refs=[query_id],
                            storage_refs=[storage_artifacts["recordsPath"]],
                        )
                    )

    final_run = s.data_processing_service.get_processing_run(normalized_run_id)
    final_assignments = s.data_processing_service.list_collection_assignments(normalized_run_id)["assignments"]
    final_records_payload = s.data_processing_service.list_records(normalized_run_id)
    final_outputs_payload = s.data_processing_service.list_collection_outputs(normalized_run_id)
    final_status = s.data_processing_service.get_processing_status(normalized_run_id)
    final_existing_query_ids = s._source_collection_attempted_query_ids(
        [item for item in list(final_records_payload.get("records") or []) if isinstance(item, dict)],
        [item for item in list(final_outputs_payload.get("outputs") or []) if isinstance(item, dict)],
    )
    next_runnable_query_ids = s._source_collection_next_runnable_query_ids(
        [item for item in list(final_assignments or []) if isinstance(item, dict)],
        final_existing_query_ids,
        force=False,
        target_assignment_ids=target_assignment_ids,
        target_agent_role=target_agent_role,
    )
    remaining_query_count = len(next_runnable_query_ids)
    source_collection_summary = s._source_collection_assignment_stage_summary(
        [item for item in list(final_assignments or []) if isinstance(item, dict)]
    )
    final_status_summary = final_status.get("summary") if isinstance(final_status.get("summary"), dict) else {}
    final_status_summary.update(source_collection_summary)
    final_status["summary"] = final_status_summary
    s._append_source_collection_execution_artifacts(
        normalized_team_id,
        normalized_run_id,
        execution_events=execution_events,
        created_records=created_records,
        imported=imported,
    )
    s._record_workflow_event(
        "source_collection.search_executed",
        normalized_team_id,
        fields={
            "runId": normalized_run_id,
            "provider": provider,
            "providers": list(providers),
            "attemptedQueryCount": attempted_query_count,
            "executedQueryCount": executed_query_count,
            "skippedQueryCount": skipped_query_count,
            "failedQueryCount": failed_query_count,
            "recordCount": len(created_records),
            "createdUniqueRecordCount": len(created_records),
            "importedCount": len(imported),
            "rejectedResultCount": rejected_result_count,
            "skippedDuplicateCount": skipped_duplicate_count,
            "filteredExcludedCount": filtered_excluded_count,
            "duplicateSourceKeys": duplicate_source_keys[:20],
            "excludedSourceKeys": excluded_source_keys[:20],
            "remainingQueryCount": remaining_query_count,
            "hasMore": remaining_query_count > 0,
            "sourceCollectionRunDirectory": storage_artifacts["runDirectory"],
        },
        child_log_path=f"artifacts/source-collection-{s._safe_token(normalized_run_id, default='run', max_length=96)}-query-summary.jsonl",
        child_log_payload={
            "teamId": normalized_team_id,
            "runId": normalized_run_id,
            "provider": provider,
            "providers": list(providers),
            "queryEvents": s._source_collection_query_event_summaries(execution_events),
            "summary": {
                "attemptedQueryCount": attempted_query_count,
                "executedQueryCount": executed_query_count,
                "skippedQueryCount": skipped_query_count,
                "failedQueryCount": failed_query_count,
                "recordCount": len(created_records),
                "importedCount": len(imported),
                "rejectedResultCount": rejected_result_count,
                "skippedDuplicateCount": skipped_duplicate_count,
                "filteredExcludedCount": filtered_excluded_count,
                "remainingQueryCount": remaining_query_count,
            },
        },
    )
    status_label = "cancelled" if cancelled or str(final_run.get("status") or "").strip().lower() == "cancelled" else ("executed" if created_records else ("excluded_filtered" if filtered_excluded_count else ("duplicates_skipped" if skipped_duplicate_count else ("partial" if executed_query_count or failed_query_count else "no_open_assignment"))))
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "runId": normalized_run_id,
        "status": status_label,
        "provider": provider,
        "providers": list(providers),
        "attemptedQueryCount": attempted_query_count,
        "executedQueryCount": executed_query_count,
        "skippedQueryCount": skipped_query_count,
        "failedQueryCount": failed_query_count,
        "resultCount": result_count,
        "recordCount": len(created_records),
        "createdUniqueRecordCount": len(created_records),
        "outputCount": len(outputs),
        "importedCount": len(imported),
        "rejectedResultCount": rejected_result_count,
        "skippedDuplicateCount": skipped_duplicate_count,
        "filteredExcludedCount": filtered_excluded_count,
        "duplicateSourceKeys": duplicate_source_keys[:20],
        "excludedSourceKeys": excluded_source_keys[:20],
        "remainingQueryCount": remaining_query_count,
        "nextRunnableQueryIds": next_runnable_query_ids[:12],
        "hasMore": remaining_query_count > 0,
        "run": final_run,
        "runStatus": final_status,
        "sourceCollectionSummary": source_collection_summary,
        "storageArtifacts": storage_artifacts,
        "assignments": final_assignments,
        "outputs": outputs,
        "createdRecords": created_records,
        "imported": imported,
        "executionEvents": execution_events,
        "boundaries": {
            "externalSearchTriggered": attempted_query_count > 0,
            "metadataOnlyDownload": True,
            "writesFormalKnowledge": False,
            "writesRag": False,
            "writesOfficialGraph": False,
        },
        "nextActions": [
            "Review imported source_manifest candidates before source quality screening.",
            "Run source quality assessment for accepted candidates.",
            "Keep formal Team Knowledge/RAG/official graph writes behind the later governance gate.",
        ],
    }


def _sync_source_collection_stage_round_after_search(
    team_id: str,
    run_id: str,
    result: dict[str, Any],
    *,
    terminal_status: str,
    terminal_summary: str,
) -> dict[str, Any] | None:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_run_id = s._normalize_required_id(run_id, "Data processing run id is required.")
    try:
        run_status = s.data_processing_service.get_processing_status(normalized_run_id)
    except s.data_processing_service.DataProcessingError:
        run_status = {}
    run_status_summary = run_status.get("summary") if isinstance(run_status.get("summary"), dict) else {}
    candidate_store = s._load_candidate_store(normalized_team_id)
    run_candidate_count = s._source_collection_candidate_count_for_run(candidate_store, normalized_run_id)
    source_collection_summary = result.get("sourceCollectionSummary") if isinstance(result.get("sourceCollectionSummary"), dict) else {}
    stage_status = s._source_collection_stage_round_status_after_search(
        terminal_status,
        result=result,
        run_status_summary=run_status_summary,
        source_collection_summary=source_collection_summary,
        run_candidate_count=run_candidate_count,
    )
    now = s.utc_now_iso()
    synced_round: dict[str, Any] | None = None
    workflow_id = ""
    with s._WORKFLOW_LOCK:
        store = s._load_stage_round_store(normalized_team_id)
        rounds = s._stage_rounds(store)
        stage_round = s._latest_stage_round(
            [
                item
                for item in rounds
                if str(item.get("stageType") or "") == "knowledge_collection"
                and normalized_run_id in {str(source_run_id) for source_run_id in list(item.get("sourceRunIds") or [])}
            ]
        )
        if stage_round is not None:
            workflow = s._load_or_create_workflow(normalized_team_id)
            workflow_id = str(workflow.get("workflowId") or "")
            previous_execution = stage_round.get("sourceCollectionSearchExecution") if isinstance(stage_round.get("sourceCollectionSearchExecution"), dict) else {}
            stage_round["sourceCollectionSearchExecution"] = {
                **previous_execution,
                "runId": normalized_run_id,
                "status": terminal_status,
                "resultStatus": s._trim_text(result.get("status"), max_length=80),
                "executionMode": previous_execution.get("executionMode") or "background",
                "accepted": bool(previous_execution.get("accepted")),
                "provider": s._trim_text(result.get("provider"), max_length=80) or previous_execution.get("provider") or s.SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF,
                "executedQueryCount": s._source_collection_count(result.get("executedQueryCount")),
                "failedQueryCount": s._source_collection_count(result.get("failedQueryCount")),
                "recordCount": s._source_collection_count(run_status_summary.get("recordCount") or result.get("recordCount")),
                "importedCount": s._source_collection_count(result.get("importedCount")),
                "skippedDuplicateCount": s._source_collection_count(result.get("skippedDuplicateCount")),
                "remainingQueryCount": s._source_collection_count(result.get("remainingQueryCount")),
                "hasMore": bool(result.get("hasMore")),
                "activeWorkRunId": "",
                "summary": s._trim_text(terminal_summary, max_length=500),
                "updatedAt": now,
            }
            stage_round["sourceCollectionSummary"] = {
                **source_collection_summary,
                "recordCount": s._source_collection_count(run_status_summary.get("recordCount")),
                "candidateCount": run_candidate_count,
            }
            stage_round["status"] = stage_status
            stage_round["updatedAt"] = now
            stage_round["teamMemoryRecord"] = s._stage_memory_record(stage_round, workflow)
            stage_round["teamMemoryRecordId"] = stage_round["teamMemoryRecord"]["recordId"]
            workflow["activeWorkflowItems"] = s._upsert_active_item(
                workflow.get("activeWorkflowItems"),
                candidate_id=normalized_run_id,
                current_node="knowledge_collection",
                status=f"source_collection_{stage_status}",
                transfer_id="",
            )
            workflow["updatedAt"] = now
            store["updatedAt"] = now
            s._write_json(s._stage_round_store_path(normalized_team_id), store)
            s._write_json(s._workflow_path(normalized_team_id), workflow)
            synced_round = dict(stage_round)
    if synced_round is not None:
        s._record_workflow_event(
            "research_stage_round.source_collection_search_synced",
            normalized_team_id,
            fields={
                "workflowId": workflow_id,
                "runId": normalized_run_id,
                "stageRoundId": synced_round.get("stageRoundId", "") if synced_round else "",
                "status": stage_status,
                "searchStatus": terminal_status,
                "recordCount": s._source_collection_count(run_status_summary.get("recordCount")),
                "candidateCount": run_candidate_count,
            },
        )
    try:
        from core.web.services.team_workflow.research_runtime import hypothesis_first_chain

        hypothesis_first_chain.notify_collection_run_terminal(
            normalized_team_id,
            normalized_run_id,
            terminal_status,
        )
    except Exception:
        pass
    return synced_round


def _source_collection_stage_round_status_after_search(
    terminal_status: str,
    *,
    result: dict[str, Any],
    run_status_summary: dict[str, Any],
    source_collection_summary: dict[str, Any],
    run_candidate_count: int,
) -> str:
    s = _service()
    normalized = str(terminal_status or "").lower()
    if normalized in {"failed", "cancelled"}:
        return "needs_attention"
    if normalized == "needs_continue":
        return "needs_continue"
    if s._source_collection_count(result.get("remainingQueryCount")) or bool(result.get("hasMore")):
        return "needs_continue"
    if s._source_collection_count(source_collection_summary.get("searchOpenAssignmentCount")):
        return "needs_continue"
    if (
        s._source_collection_count(source_collection_summary.get("downstreamOpenAssignmentCount"))
        or run_candidate_count
        or s._source_collection_count(run_status_summary.get("recordCount"))
        or s._source_collection_count(result.get("importedCount"))
    ):
        return "needs_screening"
    return "completed"


def _execute_source_collection_query(query: dict[str, Any], *, max_results: int, provider: str) -> dict[str, Any]:
    s = _service()
    if provider not in s.SOURCE_COLLECTION_SEARCH_PROVIDERS:
        return {"provider": provider, "results": [], "error": f"Unsupported provider: {provider}"}
    query_text = s._trim_text(query.get("query"), max_length=1000)
    if not query_text:
        return {"provider": provider, "results": [], "error": "Search query is empty."}
    rows = s._normalize_int(max_results, default=s.SOURCE_COLLECTION_SEARCH_EXECUTION_DEFAULT_RESULTS_PER_QUERY, minimum=1, maximum=s.SOURCE_COLLECTION_SEARCH_EXECUTION_MAX_RESULTS_PER_QUERY)
    if provider == s.SOURCE_COLLECTION_SEARCH_PROVIDER_ARXIV:
        return s._execute_arxiv_source_collection_query(query_text, rows=rows, provider=provider, fallback_source_type=str(query.get("sourceType") or ""))
    if provider == s.SOURCE_COLLECTION_SEARCH_PROVIDER_OPENALEX:
        return s._execute_openalex_source_collection_query(query_text, rows=rows, provider=provider, fallback_source_type=str(query.get("sourceType") or ""))
    search_url = s._crossref_search_url(query_text, rows=rows)
    try:
        request = urllib.request.Request(
            search_url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Vibelution-ChallengeCup/1.0 (metadata-only research source collection)",
            },
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return {"provider": provider, "searchUrl": search_url, "results": [], "error": str(exc)}
    message = payload.get("message") if isinstance(payload, dict) else {}
    items = message.get("items") if isinstance(message, dict) else []
    results = [s._source_collection_result_from_crossref_item(item, fallback_source_type=str(query.get("sourceType") or "")) for item in list(items or [])[:rows] if isinstance(item, dict)]
    return {"provider": provider, "searchUrl": search_url, "results": [item for item in results if item.get("title") or item.get("sourceRef") or item.get("rawLocation")]}


def _execute_arxiv_source_collection_query(
    query_text: str,
    *,
    rows: int,
    provider: str,
    fallback_source_type: str,
) -> dict[str, Any]:
    """Run one metadata-only arXiv Atom API query on the background thread.

    Same synchronous urllib transport as the Crossref branch (no console, no
    subprocess).  arXiv etiquette caps request frequency at one call per 3
    seconds, so the interval is enforced after every request, success or not.
    """
    s = _service()
    arxiv_query = s._arxiv_search_query(query_text)
    search_url = s._arxiv_search_url(arxiv_query, start=0, max_results=rows)
    try:
        request = urllib.request.Request(
            search_url,
            headers={
                "Accept": "application/atom+xml",
                "User-Agent": "Vibelution-ChallengeCup/1.0 (metadata-only research source collection)",
            },
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            payload_bytes = response.read()
    except (OSError, urllib.error.URLError) as exc:
        return {"provider": provider, "searchUrl": search_url, "results": [], "error": str(exc)}
    finally:
        time.sleep(s.SOURCE_COLLECTION_SEARCH_ARXIV_REQUEST_INTERVAL_SECONDS)
    try:
        entries = s._source_collection_arxiv_atom_entries(payload_bytes)
    except ET.ParseError as exc:
        return {"provider": provider, "searchUrl": search_url, "results": [], "error": f"arXiv response parse failed: {exc}"}
    results = [
        s._source_collection_result_from_arxiv_entry(entry, fallback_source_type=fallback_source_type)
        for entry in list(entries)[:rows]
    ]
    return {"provider": provider, "searchUrl": search_url, "results": [item for item in results if item.get("title") or item.get("sourceRef") or item.get("rawLocation")]}


def _execute_openalex_source_collection_query(
    query_text: str,
    *,
    rows: int,
    provider: str,
    fallback_source_type: str,
) -> dict[str, Any]:
    """Run one metadata-only OpenAlex works query on the background thread.

    Same synchronous urllib transport as the other provider branches (no
    console, no subprocess).  The mailto contact embedded by
    ``_openalex_search_url`` keeps the request in OpenAlex's polite pool
    (10 req/s, no artificial interval needed); occasional 429/5xx responses
    surface as a per-query error without retries, matching the Crossref
    branch, so later batches naturally refill the gap.
    """
    s = _service()
    search_url = s._openalex_search_url(query_text, per_page=rows)
    try:
        request = urllib.request.Request(
            search_url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Vibelution-ChallengeCup/1.0 (metadata-only research source collection)",
            },
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return {"provider": provider, "searchUrl": search_url, "results": [], "error": str(exc)}
    items = payload.get("results") if isinstance(payload, dict) else []
    results = [
        s._source_collection_result_from_openalex_work(work, fallback_source_type=fallback_source_type)
        for work in list(items or [])[:rows]
        if isinstance(work, dict)
    ]
    return {"provider": provider, "searchUrl": search_url, "results": [item for item in results if item.get("title") or item.get("sourceRef") or item.get("rawLocation")]}


def _source_collection_search_quality_terms(query_text: str) -> set[str]:
    s = _service()
    text = s._trim_text(query_text, max_length=1000)
    lowered = text.lower()
    terms = {
        token
        for token in re.findall(r"[a-z][a-z0-9_-]{3,}", lowered)
        if token not in s._SOURCE_COLLECTION_GENERIC_SEARCH_TERMS
    }
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", text)
    for size in (2, 3, 4):
        for index in range(0, max(0, len(cjk_chars) - size + 1)):
            term = "".join(cjk_chars[index : index + size])
            if term:
                terms.add(term)
    for cjk_term, translations in s._SOURCE_COLLECTION_QUERY_TERM_TRANSLATIONS.items():
        if cjk_term in text:
            terms.update(translations)
    return {term for term in terms if len(term.strip()) >= 2}


def _source_collection_search_result_quality_gate(query: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    query_text = s._trim_text(query.get("query"), max_length=1000)
    query_terms = s._source_collection_search_quality_terms(query_text)
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    haystack = " ".join(
        s._trim_text(value, max_length=2000)
        for value in (
            result.get("title"),
            result.get("summary"),
            result.get("sourceRef"),
            result.get("rawLocation"),
            metadata.get("containerTitle"),
        )
        if value
    ).lower()
    blocking_terms = sorted(term for term in s._SOURCE_COLLECTION_LOW_QUALITY_TERMS if term.lower() in haystack)
    matched_terms = sorted(term for term in query_terms if term.lower() in haystack)
    required_matches = 1 if len(query_terms) <= 1 else 2
    accepted = bool(query_terms) and len(matched_terms) >= required_matches and not blocking_terms
    reasons: list[str] = []
    if not query_terms:
        reasons.append("query_has_no_quality_terms")
    if len(matched_terms) < required_matches:
        reasons.append("insufficient_query_overlap")
    if blocking_terms:
        reasons.append("low_quality_context_terms")
    return {
        "accepted": accepted,
        "matchedTerms": matched_terms[:12],
        "requiredMatchCount": required_matches,
        "queryTermCount": len(query_terms),
        "blockingTerms": blocking_terms[:12],
        "reasons": reasons,
    }


def _source_collection_record_from_search_result(
    team_id: str,
    run: dict[str, Any],
    assignment: dict[str, Any],
    query: dict[str, Any],
    result: dict[str, Any],
    *,
    provider: str,
    search_url: str,
) -> dict[str, Any]:
    s = _service()
    agent_role = s._trim_text(assignment.get("agentRole"), max_length=80)
    assignment_id = s._trim_text(assignment.get("assignmentId"), max_length=128)
    query_id = s._trim_text(query.get("queryId"), max_length=160)
    query_text = s._trim_text(query.get("query"), max_length=1000)
    source_ref = s._trim_text(result.get("sourceRef"), max_length=1000)
    raw_location = s._trim_text(result.get("rawLocation"), max_length=1000) or search_url
    trace = {
        "teamId": team_id,
        "runId": s._trim_text(run.get("runId"), max_length=128),
        "planId": s._trim_text((query.get("queryId") or "").split("-q", 1)[0], max_length=128),
        "queryId": query_id,
        "query": query_text,
        "assignmentId": assignment_id,
        "agentRole": agent_role,
        "searchProvider": provider,
        "searchUrl": search_url,
        "downloadKind": "metadata",
        "externalSearchTriggered": True,
        "metadataOnlyDownload": True,
        "storageTarget": "data_processing.records",
        "promptCachePartition": s._trim_text((query.get("execution") or {}).get("promptCachePartition") if isinstance(query.get("execution"), dict) else "", max_length=160),
    }
    metadata = s._normalize_metadata(result.get("metadata"))
    metadata.update(
        {
            "sourceCollectionTrace": trace,
            "searchProvider": provider,
            "searchUrl": search_url,
            "metadataOnlyDownload": True,
        }
    )
    source_identity_key = s._source_collection_result_identity_key(result)
    if source_identity_key:
        metadata["sourceIdentityKey"] = source_identity_key
    quality_signals = s._normalize_metadata(result.get("qualitySignals"))
    if source_identity_key:
        quality_signals["sourceIdentityKey"] = source_identity_key
        quality_signals["duplicateState"] = "unique_candidate"
    return {
        "sourceType": s._source_collection_data_processing_source_type(result.get("sourceType")),
        "sourceRef": source_ref,
        "rawLocation": raw_location,
        "title": s._trim_text(result.get("title"), max_length=260) or source_ref or raw_location,
        "summary": s._trim_text(result.get("summary"), max_length=4000),
        "status": "collected",
        "metadata": metadata,
        "qualitySignals": quality_signals,
        "collectionTrace": trace,
    }


def _source_collection_record_search_trace(record: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    trace = metadata.get("sourceCollectionTrace") if isinstance(metadata.get("sourceCollectionTrace"), dict) else {}
    if trace:
        return trace
    return record.get("collectionTrace") if isinstance(record.get("collectionTrace"), dict) else {}


def _source_collection_assigned_queries(assignment: dict[str, Any]) -> list[dict[str, Any]]:
    s = _service()
    scope = assignment.get("scope") if isinstance(assignment.get("scope"), dict) else {}
    return [item for item in list(scope.get("assignedQueries") or []) if isinstance(item, dict)]


def _source_collection_next_runnable_query_ids(
    assignments: list[dict[str, Any]],
    existing_query_ids: set[str],
    *,
    force: bool,
    target_assignment_ids: set[str],
    target_agent_role: str,
) -> list[str]:
    s = _service()
    query_ids: list[str] = []
    seen: set[str] = set()
    for assignment in assignments:
        assignment_id = s._trim_text(assignment.get("assignmentId"), max_length=128)
        agent_role = s._trim_text(assignment.get("agentRole"), max_length=80)
        if agent_role not in s.SOURCE_COLLECTION_SEARCH_EXECUTION_AGENT_ROLES:
            continue
        if target_assignment_ids and assignment_id not in target_assignment_ids:
            continue
        if target_agent_role and agent_role != target_agent_role:
            continue
        if not force and str(assignment.get("status") or "") not in {"open", "in_progress", "returned"}:
            continue
        for query in s._source_collection_assigned_queries(assignment):
            query_id = s._trim_text(query.get("queryId"), max_length=160)
            if not query_id or query_id in seen:
                continue
            if query_id in existing_query_ids and not force:
                continue
            seen.add(query_id)
            query_ids.append(query_id)
    return query_ids


def _source_collection_attempted_query_ids(records: list[dict[str, Any]], outputs: list[dict[str, Any]]) -> set[str]:
    s = _service()
    return s._source_collection_existing_query_ids(records) | s._source_collection_output_query_ids(outputs)


def _source_collection_existing_identity_records(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    s = _service()
    by_key: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        source_identity_key = s._source_collection_record_identity_key(record)
        if source_identity_key and source_identity_key not in by_key:
            by_key[source_identity_key] = record
    return by_key


def _source_collection_exclusion_match(
    team_id: str,
    run: dict[str, Any],
    source_identity_key: str,
) -> dict[str, Any] | None:
    s = _service()
    normalized_key = s._trim_text(source_identity_key, max_length=240)
    if not normalized_key:
        return None
    scope = s._source_collection_exclusion_scope(run)
    with s._WORKFLOW_LOCK:
        store = s._load_source_collection_exclusion_store(team_id)
        for entry in list(store.get("entries") or []):
            if not isinstance(entry, dict):
                continue
            if s._trim_text(entry.get("sourceIdentityKey"), max_length=240) != normalized_key:
                continue
            if s._trim_text(entry.get("scopeKey"), max_length=120) != scope["scopeKey"]:
                continue
            return dict(entry)
    return None


def _record_source_collection_exclusion_hit(
    team_id: str,
    run: dict[str, Any],
    record: dict[str, Any],
    entry: dict[str, Any],
) -> dict[str, Any]:
    s = _service()
    source_identity_key = s._trim_text(entry.get("sourceIdentityKey"), max_length=240)
    scope_key = s._trim_text(entry.get("scopeKey"), max_length=120)
    if not source_identity_key or not scope_key:
        return {}
    now = s.utc_now_iso()
    run_id = s._trim_text(run.get("runId"), max_length=160)
    record_id = s._trim_text(record.get("recordId"), max_length=160)
    with s._WORKFLOW_LOCK:
        store = s._load_source_collection_exclusion_store(team_id)
        entries = [item for item in list(store.get("entries") or []) if isinstance(item, dict)]
        stored: dict[str, Any] | None = None
        for item in entries:
            if (
                s._trim_text(item.get("sourceIdentityKey"), max_length=240) == source_identity_key
                and s._trim_text(item.get("scopeKey"), max_length=120) == scope_key
            ):
                stored = item
                break
        if stored is None:
            return {}
        stored["hitCount"] = max(1, s._source_collection_count(stored.get("hitCount"))) + 1
        stored["lastSeenAt"] = now
        stored["updatedAt"] = now
        stored["lastHitSourceSnapshot"] = s._source_collection_record_source_snapshot(record)
        run_ids = s._normalize_text_list(stored.get("runIds"), max_items=40, max_length=160)
        if run_id and run_id not in run_ids:
            run_ids.append(run_id)
        stored["runIds"] = run_ids[:40]
        record_ids = s._normalize_text_list(stored.get("recordIds"), max_items=80, max_length=160)
        if record_id and record_id not in record_ids:
            record_ids.append(record_id)
        stored["recordIds"] = record_ids[:80]
        store["entries"] = entries
        s._write_source_collection_exclusion_store(team_id, store)
        return dict(stored)


def _source_collection_execution_event(
    event_type: str,
    *,
    assignment: dict[str, Any],
    title: str,
    summary: str,
    status: str,
    query: dict[str, Any] | None = None,
    refs: list[Any] | None = None,
    raw_location: str = "",
    storage_refs: list[str] | None = None,
    provider: str = "",
) -> dict[str, Any]:
    s = _service()
    now = s.utc_now_iso()
    normalized_query = query if isinstance(query, dict) else {}
    return {
        "eventId": s._new_record_id("srcevt"),
        "eventType": event_type,
        "status": s._trim_text(status, max_length=80) or "completed",
        "title": s._trim_text(title, max_length=260),
        "summary": s._trim_text(summary, max_length=1200),
        "agentRole": s._trim_text(assignment.get("agentRole"), max_length=80),
        "agentId": s._trim_text(assignment.get("agentId"), max_length=160),
        "assignmentId": s._trim_text(assignment.get("assignmentId"), max_length=128),
        "queryId": s._trim_text(normalized_query.get("queryId"), max_length=160),
        "query": s._trim_text(normalized_query.get("query"), max_length=1000),
        "perspective": s._trim_text(
            normalized_query.get("perspective")
            or normalized_query.get("perspectiveId"),
            max_length=80,
        ),
        "sourceType": s._trim_text(normalized_query.get("sourceType"), max_length=80),
        "provider": s._trim_text(provider, max_length=80),
        "refs": s._normalize_text_list(refs or [], max_items=8, max_length=240),
        "rawLocation": s._trim_text(raw_location, max_length=1000),
        "storageRefs": s._normalize_text_list(storage_refs or [], max_items=8, max_length=240),
        "createdAt": now,
    }


def _append_source_collection_execution_artifacts(
    team_id: str,
    run_id: str,
    *,
    execution_events: list[dict[str, Any]],
    created_records: list[dict[str, Any]],
    imported: list[dict[str, Any]],
) -> None:
    s = _service()
    paths = s._source_collection_storage_artifact_paths(team_id, run_id)
    paths["runDirectory"].mkdir(parents=True, exist_ok=True)
    paths["artifactsDirectory"].mkdir(parents=True, exist_ok=True)
    if execution_events:
        s._append_jsonl(paths["searchEventsPath"], execution_events)
    if created_records:
        s._append_jsonl(paths["recordsPath"], created_records)
    candidate_records = [
        item.get("candidate")
        for item in imported
        if isinstance(item, dict) and isinstance(item.get("candidate"), dict)
    ]
    if candidate_records:
        s._append_jsonl(paths["candidatesPath"], candidate_records)


def _source_collection_query_event_summaries(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    s = _service()
    summaries: list[dict[str, Any]] = []
    for event in events[:80]:
        if not isinstance(event, dict):
            continue
        assignment = event.get("assignment") if isinstance(event.get("assignment"), dict) else {}
        query = event.get("query") if isinstance(event.get("query"), dict) else {}
        summaries.append(
            {
                "eventType": s._trim_text(event.get("eventType") or event.get("type"), max_length=120),
                "status": s._trim_text(event.get("status"), max_length=80),
                "assignmentId": s._trim_text(event.get("assignmentId") or assignment.get("assignmentId"), max_length=128),
                "agentRole": s._trim_text(event.get("agentRole") or assignment.get("agentRole"), max_length=80),
                "queryId": s._trim_text(event.get("queryId") or query.get("queryId"), max_length=160),
                "provider": s._trim_text(query.get("provider") or event.get("provider"), max_length=80),
                "refCount": len(list(event.get("refs") or [])) if isinstance(event.get("refs"), list) else 0,
                "storageRefCount": len(list(event.get("storageRefs") or [])) if isinstance(event.get("storageRefs"), list) else 0,
            }
        )
    return summaries


def project_source_collection_search_trace(
    team_id: str,
    run_id: str,
    *,
    assignment_id: str = "",
    assignment_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Project immutable search receipts into the workflow artifact trace.

    The JSONL execution log remains the single authority. Agent-authored
    ``searchTrace`` is deliberately not an input. Terminal meaning comes from
    ``eventType`` because duplicate/excluded events legitimately use
    ``status=completed`` without representing a newly found source.
    """
    s = _service()
    normalized_run_id = s._trim_text(run_id, max_length=160)
    normalized_assignment_ids = {
        s._trim_text(item, max_length=128)
        for item in [assignment_id, *(assignment_ids or [])]
        if s._trim_text(item, max_length=128)
    }
    if not normalized_run_id:
        return []
    events_path = s._source_collection_storage_artifact_paths(
        team_id,
        normalized_run_id,
    )["searchEventsPath"]
    events = [
        dict(item)
        for item in s._read_jsonl(events_path)
        if isinstance(item, dict)
        and (
            not normalized_assignment_ids
            or s._trim_text(item.get("assignmentId"), max_length=128)
            in normalized_assignment_ids
        )
        and s._trim_text(item.get("queryId"), max_length=160)
    ]
    providers_by_query: dict[tuple[str, str], set[str]] = {}
    for event in events:
        provider = s._trim_text(event.get("provider"), max_length=80)
        if provider:
            key = (
                s._trim_text(event.get("assignmentId"), max_length=128),
                s._trim_text(event.get("queryId"), max_length=160),
            )
            providers_by_query.setdefault(key, set()).add(provider)

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    order: list[tuple[str, str, str]] = []
    for event in events:
        assignment = s._trim_text(event.get("assignmentId"), max_length=128)
        query_id = s._trim_text(event.get("queryId"), max_length=160)
        provider = s._trim_text(event.get("provider"), max_length=80)
        if not provider:
            candidates = providers_by_query.get((assignment, query_id), set())
            provider = next(iter(candidates)) if len(candidates) == 1 else "unknown"
        key = (assignment, query_id, provider)
        if key not in grouped:
            order.append(key)
            grouped[key] = []
        grouped[key].append(event)

    status_by_event_type = {
        "storage.source_manifest_imported": "found",
        "storage.data_record_written": "found",
        "search.duplicate_skipped": "duplicate",
        "storage.source_manifest_duplicate_skipped": "duplicate",
        "search.duplicates_only_output_recorded": "duplicate",
        "search.excluded_source_filtered": "excluded",
        "search.excluded_sources_only_output_recorded": "excluded",
        "search.low_quality_rejected": "excluded",
        "search.executed": "returned",
        "search.failed": "failed",
    }
    priority = {"failed": 0, "returned": 1, "excluded": 2, "duplicate": 3, "found": 4}
    projected: list[dict[str, Any]] = []
    for assignment, query_id, provider in order:
        group = grouped[(assignment, query_id, provider)]
        terminal_status = ""
        refs: list[str] = []
        event_ids: list[str] = []
        for event in group:
            event_type = s._trim_text(event.get("eventType"), max_length=120)
            candidate_status = status_by_event_type.get(event_type, "")
            if priority.get(candidate_status, -1) > priority.get(terminal_status, -1):
                terminal_status = candidate_status
            for value in [
                *(event.get("refs") if isinstance(event.get("refs"), list) else []),
                event.get("rawLocation"),
            ]:
                text = s._trim_text(value, max_length=1000)
                if text and text not in refs:
                    refs.append(text)
            event_id = s._trim_text(event.get("eventId"), max_length=160)
            if event_id and event_id not in event_ids:
                event_ids.append(event_id)
        if not terminal_status:
            continue
        failure_reason = ""
        if terminal_status == "returned" and not refs:
            terminal_status = "no_credible_source"
            failure_reason = "terminal_provider_receipt_without_results"
        projected.append(
            {
                "sourceCollectionRunId": normalized_run_id,
                "assignmentId": assignment,
                "queryId": query_id,
                "provider": provider,
                "query": s._trim_text(group[0].get("query"), max_length=1000),
                "perspective": s._trim_text(
                    group[0].get("perspective"),
                    max_length=80,
                ),
                "status": terminal_status,
                "resultRefs": refs,
                "eventIds": event_ids,
                "failureReason": failure_reason,
                "startedAt": s._trim_text(group[0].get("createdAt"), max_length=80),
                "terminalAt": s._trim_text(group[-1].get("createdAt"), max_length=80),
            }
        )
    return projected


def _source_collection_record_identity_key(record: dict[str, Any]) -> str:
    s = _service()
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    quality_signals = record.get("qualitySignals") if isinstance(record.get("qualitySignals"), dict) else {}
    existing = s._trim_text(metadata.get("sourceIdentityKey") or quality_signals.get("sourceIdentityKey"), max_length=160)
    if existing:
        return existing
    return s._source_collection_identity_key(
        source_ref=record.get("sourceRef"),
        raw_location=record.get("rawLocation"),
        doi=metadata.get("doi") or quality_signals.get("doi"),
        url=metadata.get("url") or quality_signals.get("url"),
        title=record.get("title"),
        container=metadata.get("containerTitle") or metadata.get("container") or quality_signals.get("containerTitle") or quality_signals.get("container"),
        published=metadata.get("issued") or metadata.get("published") or quality_signals.get("issued") or quality_signals.get("published"),
    )
