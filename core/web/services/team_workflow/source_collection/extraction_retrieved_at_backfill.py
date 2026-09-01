"""Single-authoritative Challenge v2 ``retrieved_at`` backfill for extractions.

Two consumption paths read the same extraction result shape and both must see
contract-compliant retrieval timestamps:

1. the writeback acceptance boundary (``stage_writeback``) — normalizes the
   agent's fresh payload before it is accepted and persisted;
2. the claim materializer's read point
   (``agent_claim_evidence_materializer``) — a node retry (RETRY_NODE)
   replays the previously persisted task result straight into
   materialization without crossing the writeback boundary, so old
   contract-violating payloads must be normalized at the read point too
   (production run-882610596ddb: RETRY_NODE source_extraction failed 3s
   later with ``candidateExtractions[0].claims[0] is missing explicit
   retrieved_at`` because the replay bypassed the writeback backfill).

This module owns that normalization once — parent extraction entries AND
every materializable nested claim — so both boundaries enforce one rule set:

- only fill what is missing: an explicit, contract-compliant (RFC3339 with
  timezone) ``retrieved_at``/``retrievedAt`` value is never overwritten;
- never invent history: the time source is the extraction's own chain — the
  source record ``createdAt`` (when the content was fetched into the run),
  else the source candidate's ``createdAt`` (when it was registered); only
  when no chain time resolves does it fall back to the real current time,
  matching the established fail-loud-but-servicable semantics;
- nested claims inherit their own extraction's parent time (the parent value
  after the same backfill), so one extraction cannot carry conflicting
  retrieval timestamps across its claims.

Skip semantics for nested claims deliberately mirror the materializer's own
``_materializable_claims`` (``exclude`` decisions and honest
``missing_evidence_anchor``/``missing``/``unverified`` evidence states never
reach the contract validator), so the backfill touches exactly the claims
that will be validated.  A backfill that still leaves other contract
violations in place is not hidden: the writeback contract gate and the
materializer keep failing closed with their dedicated problem code.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

# Challenge v2 card metadata keys accepted for the retrieval timestamp.  The
# fail-closed evidence contract accepts either spelling, so the backfill must
# respect both and never overwrite an explicit value.
EXTRACTION_RETRIEVED_AT_KEYS = ("retrieved_at", "retrievedAt")

# Nested claim lists the claim materializer reads.  Only these keys carry
# materializable claims; the flat evidenceRefs shape has no nested claim
# dicts and is fully covered by the parent-entry backfill.
_MATERIALIZABLE_CLAIM_LIST_KEYS = ("claims", "keyFindings")

# Mirror of ``agent_claim_evidence_materializer._materializable_claims``:
# entries in these evidence states are honestly skipped by the materializer
# and the writeback contract gate, so their claims never need backfill.
_SKIPPED_EVIDENCE_STATUSES = {"missing_evidence_anchor", "missing", "unverified"}

_EXTRACTION_RESULT_COLLECTION_KEYS = ("candidateExtractions", "recordExtractions")


def is_timezone_aware_rfc3339_timestamp(value: object) -> bool:
    """True when ``value`` parses as an RFC3339 timestamp with a timezone."""
    text = str(value or "").strip()
    if not text:
        return False
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _service():
    from core.web.services import team_workflow_orchestration_service

    return team_workflow_orchestration_service


def _compliant_retrieved_at(item: Mapping[str, Any]) -> str:
    """Return the item's explicit contract-compliant retrieval time, if any."""
    for name in EXTRACTION_RETRIEVED_AT_KEYS:
        value = str(item.get(name) or "").strip()
        if is_timezone_aware_rfc3339_timestamp(value):
            return value
    return ""


def _is_extraction_backfill_scope(stage_id: str, agent_role: str) -> bool:
    return stage_id == "extraction" or agent_role == "source_extractor"


def _entry_is_materializable(entry: Mapping[str, Any]) -> bool:
    decision = str(entry.get("decision") or "").strip().lower()
    if decision == "exclude":
        return False
    evidence_status = str(entry.get("evidenceStatus") or "").strip().lower()
    return evidence_status not in _SKIPPED_EVIDENCE_STATUSES


def _iter_extraction_entries(result_payload: Mapping[str, Any]):
    for key in _EXTRACTION_RESULT_COLLECTION_KEYS:
        entries = result_payload.get(key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict):
                yield entry


def _payload_needs_retrieved_at_backfill(result_payload: Mapping[str, Any]) -> bool:
    """Cheap pre-scan so already-compliant payloads skip all store lookups."""
    for entry in _iter_extraction_entries(result_payload):
        if not _compliant_retrieved_at(entry):
            return True
        if not _entry_is_materializable(entry):
            continue
        for list_key in _MATERIALIZABLE_CLAIM_LIST_KEYS:
            items = entry.get(list_key)
            if not isinstance(items, list):
                continue
            if any(
                isinstance(item, dict) and not _compliant_retrieved_at(item)
                for item in items
            ):
                return True
    return False


def backfill_extraction_retrieved_at(
    result_payload: dict[str, Any],
    *,
    stage_id: str,
    agent_role: str,
    candidate_created_at_by_id: Mapping[str, str],
    record_created_at_by_id: Mapping[str, str],
    resolve_candidate_id: Callable[[Mapping[str, Any]], str],
    resolve_record_id: Callable[[Mapping[str, Any]], str],
    utc_now: Callable[[], str],
) -> dict[str, Any]:
    """Backfill parent entries and materializable nested claims in place.

    The single authoritative implementation shared by the writeback boundary
    and the materializer replay read point.  See the module docstring for the
    three invariants (fill-missing-only, no invented history, parent-sourced
    claim times).
    """
    if not _is_extraction_backfill_scope(stage_id, agent_role):
        return result_payload
    for key in _EXTRACTION_RESULT_COLLECTION_KEYS:
        entries = result_payload.get(key)
        if not isinstance(entries, list):
            continue
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            parent_time = _compliant_retrieved_at(entry)
            if not parent_time:
                source_time = ""
                for chain_time in (
                    record_created_at_by_id.get(resolve_record_id(entry)),
                    candidate_created_at_by_id.get(resolve_candidate_id(entry)),
                ):
                    if is_timezone_aware_rfc3339_timestamp(chain_time):
                        source_time = str(chain_time).strip()
                        break
                if not source_time:
                    # No chain time resolves: the real current time is the
                    # only honest fallback (established writeback semantics).
                    source_time = utc_now()
                normalized = dict(entry)
                normalized["retrieved_at"] = source_time
                entries[index] = normalized
                entry = normalized
                parent_time = source_time
            if not _entry_is_materializable(entry):
                continue
            for list_key in _MATERIALIZABLE_CLAIM_LIST_KEYS:
                items = entry.get(list_key)
                if not isinstance(items, list):
                    continue
                for claim_index, raw_claim in enumerate(items):
                    if not isinstance(raw_claim, dict):
                        continue
                    if _compliant_retrieved_at(raw_claim):
                        continue
                    patched = dict(raw_claim)
                    patched["retrieved_at"] = parent_time
                    items[claim_index] = patched
    return result_payload


def _chain_created_at_maps(
    team_id: str,
    run_id: str,
) -> tuple[dict[str, str], dict[str, str]]:
    """Resolve ``(candidate, record)`` createdAt maps from the live run stores."""
    s = _service()
    candidate_created_at_by_id: dict[str, str] = {}
    for candidate in s._source_collection_candidates_for_run(team_id, run_id):
        candidate_id = s._trim_text(candidate.get("candidateId"), max_length=160)
        created_at = s._trim_text(candidate.get("createdAt"), max_length=120)
        if candidate_id and created_at:
            candidate_created_at_by_id.setdefault(candidate_id, created_at)
    record_created_at_by_id: dict[str, str] = {}
    for record in s._source_collection_stage_records_for_run(run_id):
        record_id = s._trim_text(record.get("recordId"), max_length=160)
        created_at = s._trim_text(record.get("createdAt"), max_length=120)
        if record_id and created_at:
            record_created_at_by_id.setdefault(record_id, created_at)
    return candidate_created_at_by_id, record_created_at_by_id


def backfill_source_collection_stage_writeback_retrieved_at(
    task: Mapping[str, Any],
    result_payload: dict[str, Any],
    *,
    team_id: str,
    run_id: str,
) -> dict[str, Any]:
    """Writeback-boundary entry: chain times come from the live run stores.

    Store failures keep the historical writeback behavior (they propagate —
    the writeback cannot claim a chain time it could not read, and the agent
    rewrite loop covers transient store errors).
    """
    s = _service()
    stage_id = s._trim_text(task.get("stageId"), max_length=80)
    agent_role = s._trim_text(task.get("agentRole"), max_length=80)
    if not _is_extraction_backfill_scope(stage_id, agent_role):
        return result_payload
    if not _payload_needs_retrieved_at_backfill(result_payload):
        return result_payload
    candidate_map, record_map = _chain_created_at_maps(team_id, run_id)
    return backfill_extraction_retrieved_at(
        result_payload,
        stage_id=stage_id,
        agent_role=agent_role,
        candidate_created_at_by_id=candidate_map,
        record_created_at_by_id=record_map,
        resolve_candidate_id=s._source_collection_stage_writeback_candidate_id,
        resolve_record_id=s._source_collection_stage_writeback_record_id,
        utc_now=s.utc_now_iso,
    )


def _replay_chain_created_at_maps(
    team_id: str,
    run_id: str,
) -> tuple[dict[str, str], dict[str, str]]:
    """Best-effort chain times for a replayed persisted task result.

    A replayed task may be legacy data or belong to a run whose stores are
    momentarily unreadable.  Both are "no chain time available" shapes: the
    core backfill then falls back to the real current time per entry, which
    is the established honest fallback rather than a swallowed failure.  The
    run-scope probe first keeps hand-built tasks (tests, foreign runs) from
    touching or creating candidate stores at all.
    """
    if not team_id or not run_id:
        return {}, {}
    from core.web.services import data_processing_service

    try:
        data_processing_service.get_processing_run_scope(run_id)
    except Exception:  # noqa: BLE001 - absent/foreign run: no chain times to read
        return {}, {}
    try:
        return _chain_created_at_maps(team_id, run_id)
    except Exception:  # noqa: BLE001 - unreadable stores degrade to real-now fallback
        return {}, {}


def backfill_persisted_extraction_task_retrieved_at(
    task: dict[str, Any],
) -> dict[str, Any]:
    """Materializer read-point entry for a persisted (replayed) task result.

    Normalizes ``task["result"]`` in place and returns the task, so a node
    retry that replays previously persisted data sees the same normalization
    the writeback boundary applied to fresh payloads.  This is a read-point
    repair only: it never writes the task back — the canonical store keeps
    exactly what the writeback boundary accepted.
    """
    result = task.get("result")
    if not isinstance(result, dict):
        return task
    if not _payload_needs_retrieved_at_backfill(result):
        return task
    s = _service()
    stage_id = s._trim_text(task.get("stageId"), max_length=80)
    agent_role = s._trim_text(task.get("agentRole"), max_length=80)
    if not _is_extraction_backfill_scope(stage_id, agent_role):
        return task
    team_id = s._trim_text(task.get("teamId"), max_length=160)
    run_id = s._trim_text(task.get("runId"), max_length=128)
    candidate_map, record_map = _replay_chain_created_at_maps(team_id, run_id)
    backfill_extraction_retrieved_at(
        result,
        stage_id=stage_id,
        agent_role=agent_role,
        candidate_created_at_by_id=candidate_map,
        record_created_at_by_id=record_map,
        resolve_candidate_id=s._source_collection_stage_writeback_candidate_id,
        resolve_record_id=s._source_collection_stage_writeback_record_id,
        utc_now=s.utc_now_iso,
    )
    return task
