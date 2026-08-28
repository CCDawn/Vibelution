"""D03 stage-1 knowledge collection single facade.

The Agent-visible surface for stage-1 knowledge collection is exactly one
interface: ``research_knowledge_collection_tool(action=ensure|inspect, scope,
searchEnvelope, requirements, writebackPolicy)``.

This module is the *only* backend facade behind that tool.  It validates the
formal ``ResearchScopeEnvelope`` and the search envelope, then reuses the
existing source-collection node/ledger/storage (data-processing runs, search
plans, stage rounds) instead of building a second state machine.  It never
executes a provider search and never writes formal knowledge.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from core.research.workflow.contracts import ContractValidationError, ResearchScopeEnvelope

FACADE_SCHEMA_VERSION = 1

SEARCH_ENVELOPE_SCHEMA_VERSION = 1

# Version of the source-selection policy that governs how a collection run
# turns its search envelope into evidence.  Bump this whenever the policy
# changes in a way that must invalidate previously collected evidence; it is
# part of the ensure idempotency fingerprint.
KNOWLEDGE_COLLECTION_SOURCE_POLICY_VERSION = "1"

# Metadata key on the processing run that stores the ensure idempotency
# fingerprint (see ``search_envelope_fingerprint``).
SEARCH_ENVELOPE_FINGERPRINT_METADATA_KEY = "searchEnvelopeFingerprint"

SEARCH_ENVELOPE_SOURCE_TYPES = {
    "paper",
    "dataset",
    "url",
    "file",
    "note",
    "api",
    "news",
    "code",
    "repo",
    "report",
    "manual",
    "unknown",
}

SEARCH_ENVELOPE_EVIDENCE_LEVELS = {
    "primary",
    "secondary",
    "tertiary",
    "high",
    "medium",
    "low",
    "peer_reviewed",
    "preprint",
}

_LANGUAGE_PATTERN = re.compile(r"^[a-z]{2}(-[a-z]{2,3})?$")


class ResearchKnowledgeCollectionError(ValueError):
    """Raised when a knowledge-collection facade request is invalid."""

    def __init__(self, message: str, *, code: str = "invalid_request"):
        super().__init__(message)
        self.code = code


def _service():
    from core.web.services import data_processing_service

    return data_processing_service


def _source_collection_runs_module():
    from core.web.services.team_workflow.source_collection import runs

    return runs


def _text(value: Any, *, limit: int = 0) -> str:
    text = str(value or "").strip()
    return text[:limit] if limit else text


def _object(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text_list(value: Any, *, max_items: int = 40, max_length: int = 240) -> list[str]:
    raw = value if isinstance(value, list) else [value] if value is not None else []
    items: list[str] = []
    for item in raw:
        text = _text(item, limit=max_length)
        if not text:
            continue
        items.append(text)
        if len(items) >= max_items:
            break
    return items


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _validated_envelope(scope: Mapping[str, Any] | None) -> ResearchScopeEnvelope:
    raw = _object(scope)
    if not raw:
        raise ResearchKnowledgeCollectionError(
            "scope is required and must be a ResearchScopeEnvelope object.",
            code="scope_missing",
        )
    from core.web.services.team_workflow.research_scope import (
        ResearchScopeHashMismatchError,
        validate_scope_read,
    )

    try:
        validate_scope_read(raw)
    except ResearchScopeHashMismatchError as exc:
        raise ResearchKnowledgeCollectionError(
            str(exc), code="scope_hash_mismatch"
        ) from exc
    except ContractValidationError as exc:
        raise ResearchKnowledgeCollectionError(
            str(exc), code="scope_invalid"
        ) from exc
    return ResearchScopeEnvelope.from_dict(raw)


def _normalize_search_envelope(
    searchEnvelope: Mapping[str, Any] | None,
    *,
    require_keywords: bool = False,
) -> dict[str, Any]:
    raw = _object(searchEnvelope)
    keywords = _text_list(raw.get("keywords"), max_items=40, max_length=200)
    if require_keywords and not keywords:
        raise ResearchKnowledgeCollectionError(
            "searchEnvelope.keywords must contain at least one keyword for ensure.",
            code="search_keywords_required",
        )
    source_types = _normalize_allowed_list(
        raw.get("sourceTypes"),
        allowed=SEARCH_ENVELOPE_SOURCE_TYPES,
        field="sourceTypes",
    )
    evidence_levels = _normalize_allowed_list(
        raw.get("evidenceLevels"),
        allowed=SEARCH_ENVELOPE_EVIDENCE_LEVELS,
        field="evidenceLevels",
    )
    languages: list[str] = []
    for item in _text_list(raw.get("languages"), max_items=20, max_length=32):
        normalized = item.lower()
        if not _LANGUAGE_PATTERN.fullmatch(normalized):
            raise ResearchKnowledgeCollectionError(
                f"Unsupported language: {item}",
                code="search_language_invalid",
            )
        languages.append(normalized)
    time_range = _normalize_time_range(raw.get("timeRange"))
    return {
        "schemaVersion": SEARCH_ENVELOPE_SCHEMA_VERSION,
        "keywords": keywords,
        "sourceTypes": source_types,
        "timeRange": time_range,
        "domains": _text_list(raw.get("domains"), max_items=40, max_length=240),
        "repos": _text_list(raw.get("repos"), max_items=40, max_length=240),
        "kb": _text_list(raw.get("kb"), max_items=40, max_length=240),
        "languages": languages,
        "evidenceLevels": evidence_levels,
        "forbiddenScope": _normalize_forbidden_scope(raw.get("forbiddenScope")),
    }


def _normalize_allowed_list(value: Any, *, allowed: set[str], field: str) -> list[str]:
    items = _text_list(value, max_items=40, max_length=80)
    for item in items:
        normalized = item.lower()
        if normalized not in allowed:
            raise ResearchKnowledgeCollectionError(
                f"Unsupported {field} value: {item}",
                code=f"search_{field}_invalid",
            )
    return [item.lower() for item in items]


def _normalize_time_range(value: Any) -> dict[str, str]:
    raw = _object(value)
    result: dict[str, str] = {}
    for canonical, alias in (("from", "start"), ("to", "end")):
        item = _text(raw.get(canonical) or raw.get(alias), limit=32)
        if item and not _valid_timestamp(item):
            raise ResearchKnowledgeCollectionError(
                f"Invalid timeRange.{canonical}: {item}",
                code="search_time_range_invalid",
            )
        result[canonical] = item
    return result


def _valid_timestamp(value: str) -> bool:
    try:
        datetime.fromisoformat(value)
        return True
    except (TypeError, ValueError):
        return False


def _normalize_forbidden_scope(value: Any) -> list[str]:
    raw = value if isinstance(value, list) else [value] if value is not None else []
    items: list[str] = []
    for item in raw:
        if isinstance(item, Mapping):
            label = (
                item.get("domain")
                or item.get("topic")
                or item.get("value")
                or item.get("label")
                or item.get("keyword")
            )
            text = _text(label, limit=240)
        else:
            text = _text(item, limit=240)
        if text and text not in items:
            items.append(text)
        if len(items) >= 40:
            break
    return items


def _normalize_requirements(requirements: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = _object(requirements)
    result: dict[str, Any] = {}
    min_level = _text(raw.get("minEvidenceLevel"), limit=80).lower()
    if min_level:
        if min_level not in SEARCH_ENVELOPE_EVIDENCE_LEVELS:
            raise ResearchKnowledgeCollectionError(
                f"Unsupported minEvidenceLevel: {min_level}",
                code="requirements_evidence_level_invalid",
            )
        result["minEvidenceLevel"] = min_level
    result["completeness"] = _text(raw.get("completeness"), limit=120)
    result["notes"] = _text(raw.get("notes"), limit=2000)
    return result


def search_envelope_fingerprint(
    search_envelope: Mapping[str, Any] | None,
    requirements: Mapping[str, Any] | None,
    source_policy_version: str = KNOWLEDGE_COLLECTION_SOURCE_POLICY_VERSION,
) -> str:
    """Return the stable sha256 fingerprint of one concrete evidence request.

    ``ensure`` may only reuse an existing collection run when that run provably
    served the same request: the same canonical searchEnvelope (keywords are
    deduplicated and sorted, so ordering is irrelevant), the same normalized
    requirements, and the same source policy version.  The fingerprint is
    persisted in the processing run metadata under
    ``SEARCH_ENVELOPE_FINGERPRINT_METADATA_KEY``; runs created before this
    guard have no fingerprint and can therefore never match, so ``ensure``
    re-creates instead of silently reusing stale state.

    Extend ``source_policy_version`` (currently the constant
    ``KNOWLEDGE_COLLECTION_SOURCE_POLICY_VERSION``) whenever the
    source-selection policy itself starts to change what a given envelope
    should collect.
    """
    keywords = sorted(
        {
            _text(item, limit=200)
            for item in (search_envelope or {}).get("keywords") or []
            if _text(item, limit=200)
        }
    )
    payload = {
        "sourcePolicyVersion": (
            _text(source_policy_version) or KNOWLEDGE_COLLECTION_SOURCE_POLICY_VERSION
        ),
        "searchEnvelope": {**_object(search_envelope), "keywords": keywords},
        "requirements": _object(requirements),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_WRITEBACK_POLICY_KEYS = (
    "writesFormalKnowledge",
    "writesRag",
    "writesOfficialGraph",
    "providerWriteback",
    "directStageWriteback",
    "networkExecution",
    "autoApply",
)


def _normalize_writeback_policy(writebackPolicy: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = _object(writebackPolicy)
    result: dict[str, Any] = {
        "schemaVersion": SEARCH_ENVELOPE_SCHEMA_VERSION,
        "writesFormalKnowledge": False,
        "writesRag": False,
        "writesOfficialGraph": False,
        "providerWriteback": False,
        "directStageWriteback": False,
        "networkExecution": False,
        "autoApply": False,
    }
    for key in _WRITEBACK_POLICY_KEYS:
        if key in raw and bool(raw.get(key)):
            raise ResearchKnowledgeCollectionError(
                f"writebackPolicy.{key} is rejected: the knowledge collection "
                "facade only mediates scoped, non-network ledger state and never "
                "performs provider, formal-knowledge, RAG, or graph writes.",
                code="writeback_policy_rejected",
            )
    return result


def _scope_projection(envelope: ResearchScopeEnvelope) -> dict[str, str]:
    return {
        "program": envelope.program,
        "theme": envelope.theme,
        "campaign": envelope.campaign,
        "question": envelope.question,
        "branch": envelope.branch,
        "workflow": envelope.workflow,
        "agentId": envelope.agentId,
        "mode": envelope.mode.value,
        "scopeHash": envelope.scopeHash,
    }


def _collection_locator(
    envelope: ResearchScopeEnvelope,
    run_id: str,
    team_id: str,
) -> dict[str, str]:
    return {
        "runId": _text(run_id),
        "teamId": _text(team_id),
        "sourceCollectionNode": "knowledge_collection",
        "scopeHash": envelope.scopeHash,
        "artifactLocator": envelope.artifactLocator,
        "ledgerRoot": envelope.ledgerRoot,
        "cacheKey": envelope.cacheKey,
    }


def _collection_boundaries() -> dict[str, bool | str]:
    return {
        "writesFormalKnowledge": False,
        "writesRag": False,
        "writesOfficialGraph": False,
        "networkExecution": False,
        "providerWriteback": False,
        "directStageWriteback": False,
        "singleVisibleInterface": True,
        "boundary": "d03_knowledge_collection_facade_only",
    }


def _find_existing_run(
    team_id: str,
    scope_hash: str,
    search_fingerprint: str = "",
) -> dict[str, Any] | None:
    s = _service()
    metadata_filters: dict[str, str] = {
        "startedFrom": "team_workflow_source_collection",
        "teamId": team_id,
    }
    if search_fingerprint:
        metadata_filters[SEARCH_ENVELOPE_FINGERPRINT_METADATA_KEY] = search_fingerprint
    try:
        payload = s.list_processing_runs(
            limit=200,
            metadata_filters=metadata_filters,
            scope_filters={"researchScopeHash": scope_hash},
        )
    except s.DataProcessingError as exc:
        raise ResearchKnowledgeCollectionError(
            str(exc), code="run_lookup_failed"
        ) from exc

    def _run_fingerprint(item: dict[str, Any]) -> str:
        metadata = item.get("metadata")
        if not isinstance(metadata, Mapping):
            return ""
        return _text(metadata.get(SEARCH_ENVELOPE_FINGERPRINT_METADATA_KEY))

    runs = [
        item
        for item in list(payload.get("runs") or [])
        if isinstance(item, dict)
        and _text(item.get("runId"))
        # Defensive post-filter: a run whose metadata lacks the fingerprint
        # (created before this guard, or by another entrypoint) cannot prove
        # it served the same evidence request and must never be reused by
        # ensure; re-create instead of silently returning stale state.
        and (
            not search_fingerprint
            or _run_fingerprint(item) == search_fingerprint
        )
    ]
    if not runs:
        return None
    return max(
        runs,
        key=lambda item: _text(
            item.get("updatedAt") or item.get("createdAt") or ""
        ),
    )


def _load_distilled_summary(team_id: str, run_id: str) -> dict[str, Any]:
    if not run_id:
        return {
            "status": "not_created",
            "available": False,
            "counts": {},
            "stageCards": [],
        }
    runs = _source_collection_runs_module()
    try:
        payload = runs.get_source_collection_summary(team_id, run_id=run_id)
    except Exception:
        return {
            "status": "unavailable",
            "available": False,
            "counts": {},
            "stageCards": [],
        }
    if not isinstance(payload, dict):
        return {
            "status": "unavailable",
            "available": False,
            "counts": {},
            "stageCards": [],
        }
    run = payload.get("run") if isinstance(payload.get("run"), dict) else {}
    run_status = (
        payload.get("runStatus") if isinstance(payload.get("runStatus"), dict) else {}
    )
    counts = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    stage_cards = payload.get("stageCards") if isinstance(payload.get("stageCards"), list) else []
    return {
        "status": _text(
            payload.get("status")
            or run_status.get("status")
            or run_status.get("currentPhase")
            or run.get("status")
        ),
        "available": True,
        "runId": _text(payload.get("runId") or run.get("runId")),
        "phase": _text(run_status.get("currentPhase")),
        "counts": {
            "recordCount": _int(counts.get("recordCount")),
            "assignmentCount": _int(counts.get("assignmentCount")),
            "outputCount": _int(counts.get("outputCount")),
            "sourceCandidateCount": _int(counts.get("sourceCandidateCount")),
            "approvedSourceCandidateCount": _int(counts.get("approvedSourceCandidateCount")),
        },
        "stageCards": [
            {
                "stageId": _text(card.get("stageId")),
                "status": _text(card.get("status")),
                "label": _text(card.get("label")),
            }
            for card in stage_cards[-12:]
            if isinstance(card, dict)
        ],
    }


def _ensure_payload(
    envelope: ResearchScopeEnvelope,
    search: dict[str, Any],
    requirements: dict[str, Any],
    writeback_policy: dict[str, Any],
    hypothesis_candidate_ids: list[str] | None = None,
) -> dict[str, Any]:
    keywords = list(search.get("keywords") or [])
    return {
        "title": "D03 knowledge collection",
        "goal": " ".join(keywords)[:1000] or envelope.question[:1000],
        "topic": (keywords[0] if keywords else envelope.theme)[:500],
        # Persisted by start_source_collection_run into the processing run
        # metadata so later ensure calls can prove envelope identity.
        SEARCH_ENVELOPE_FINGERPRINT_METADATA_KEY: search_envelope_fingerprint(
            search,
            requirements,
        ),
        "scope": {
            "researchScopeHash": envelope.scopeHash,
            "researchScopeCacheKey": envelope.cacheKey,
            "researchScopeArtifactLocator": envelope.artifactLocator,
            "researchScopeLedgerRoot": envelope.ledgerRoot,
            "searchEnvelope": search,
            "requirements": requirements,
            "writebackPolicy": writeback_policy,
            # Hypothesis candidate ids (the claim belief gate's aggregation
            # dimension) served by this collection run; evidence
            # materialization reads them back to bridge canonical records.
            "hypothesisCandidateIds": list(hypothesis_candidate_ids or []),
            "collectionMode": "web_search",
        },
        "agentRoles": ["source_finder"],
        "requestedByAgent": envelope.agentId,
        "ownerAgentId": envelope.agentId,
    }


def _create_collection_run(
    team_id: str,
    envelope: ResearchScopeEnvelope,
    search: dict[str, Any],
    requirements: dict[str, Any],
    writeback_policy: dict[str, Any],
    hypothesis_candidate_ids: list[str] | None = None,
) -> dict[str, Any]:
    runs = _source_collection_runs_module()
    try:
        response = runs.start_source_collection_run(
            team_id,
            _ensure_payload(
                envelope,
                search,
                requirements,
                writeback_policy,
                hypothesis_candidate_ids,
            ),
        )
    except Exception as exc:
        raise ResearchKnowledgeCollectionError(
            str(exc), code="run_creation_failed"
        ) from exc
    return response if isinstance(response, dict) else {}


def _run_id_from_start_response(response: Mapping[str, Any] | None) -> str:
    """Read both the legacy flat and the current nested start response."""
    payload = _object(response)
    nested_run = payload.get("run")
    return _text(payload.get("runId") or (
        nested_run.get("runId") if isinstance(nested_run, Mapping) else ""
    ))


def research_knowledge_collection_facade(
    *,
    action: str = "inspect",
    scope: Mapping[str, Any] | None = None,
    searchEnvelope: Mapping[str, Any] | None = None,
    requirements: Mapping[str, Any] | None = None,
    writebackPolicy: Mapping[str, Any] | None = None,
    hypothesisCandidateIds: list[str] | None = None,
    team_id: str = "research-team",
) -> dict[str, Any]:
    """Single facade for D03 stage-1 knowledge collection.

    - ``ensure`` reuses the existing source-collection state for the scope hash
      when present (idempotent) and otherwise creates the source-collection run,
      always returning only a distilled summary/status/locator.
    - ``inspect`` is strictly read-only and never creates or mutates state.
    - ``hypothesisCandidateIds`` are the hypothesis candidate ids served by the
      requested collection; ``ensure`` persists them on the created run's scope
      (``scope.hypothesisCandidateIds``) so evidence materialization can bridge
      canonical claims back to the gate's candidate dimension.  An empty list
      keeps the legacy single-dimension behavior.
    """
    normalized_action = _text(action).lower()
    if normalized_action not in {"ensure", "inspect"}:
        raise ResearchKnowledgeCollectionError(
            f"Unsupported action: {action}",
            code="unsupported_action",
        )
    normalized_team_id = _text(team_id, limit=160) or "research-team"
    envelope = _validated_envelope(scope)
    search = _normalize_search_envelope(
        searchEnvelope,
        require_keywords=(normalized_action == "ensure"),
    )
    requirements = _normalize_requirements(requirements)
    writeback_policy = _normalize_writeback_policy(writebackPolicy)
    hypothesis_candidate_ids = list(
        dict.fromkeys(
            _text_list(hypothesisCandidateIds, max_items=24, max_length=160)
        )
    )
    # ensure reuses a run only when its persisted fingerprint proves the same
    # evidence request; inspect stays a pure scope-level reader and must keep
    # surfacing the latest run regardless of the requested envelope.
    search_fingerprint = (
        search_envelope_fingerprint(search, requirements)
        if normalized_action == "ensure"
        else ""
    )
    existing_run = _find_existing_run(
        normalized_team_id,
        envelope.scopeHash,
        search_fingerprint,
    )
    base = {
        "schemaVersion": FACADE_SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "scope": _scope_projection(envelope),
        "searchEnvelope": search,
        "requirements": requirements,
        "writebackPolicy": writeback_policy,
        "boundaries": _collection_boundaries(),
    }
    if normalized_action == "inspect":
        if existing_run is None:
            return {
                **base,
                "action": "inspect",
                "status": "not_found",
                "found": False,
                "created": False,
                "locator": _collection_locator(envelope, "", normalized_team_id),
                "summary": _load_distilled_summary(normalized_team_id, ""),
            }
        run_id = _text(existing_run.get("runId"))
        return {
            **base,
            "action": "inspect",
            "status": "ok",
            "found": True,
            "created": False,
            "locator": _collection_locator(envelope, run_id, normalized_team_id),
            "summary": _load_distilled_summary(normalized_team_id, run_id),
        }
    if existing_run is not None:
        run_id = _text(existing_run.get("runId"))
        return {
            **base,
            "action": "ensure",
            "status": "ok",
            "created": False,
            "idempotent": True,
            "found": True,
            "locator": _collection_locator(envelope, run_id, normalized_team_id),
            "summary": _load_distilled_summary(normalized_team_id, run_id),
        }
    created_run = _create_collection_run(
        normalized_team_id,
        envelope,
        search,
        requirements,
        writeback_policy,
        hypothesis_candidate_ids,
    )
    run_id = _run_id_from_start_response(created_run)
    return {
        **base,
        "action": "ensure",
        "status": "ok",
        "created": bool(run_id),
        "idempotent": False,
        "found": False,
        "locator": _collection_locator(envelope, run_id, normalized_team_id),
        "summary": _load_distilled_summary(normalized_team_id, run_id),
    }
