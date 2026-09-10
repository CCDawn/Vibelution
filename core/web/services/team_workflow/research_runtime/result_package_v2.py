"""Build the one canonical Challenge Question v2 result-package envelope.

This module is deliberately a strict producer, not a summarizer.  It reads
run-scoped canonical artifacts and only projects fields that those authorities
actually contain.  Missing selection, review, evidence, result-view, model
receipt, or scope facts stop packaging instead of being filled from scores or
free-form task summaries.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from functools import lru_cache
from typing import Any

from core.research.competition import (
    CATALOG_ID,
    CATALOG_SHA256,
    load_science_question_catalog,
)
from core.web.services.team_workflow.research_projects import (
    resolve_research_project_workspace_root,
)

from .artifact_readback_registry import (
    load_scoped_artifact_payload,
    parse_canonical_ref,
)
from .human_gate_artifacts import canonical_sha256
from .model_invocation_receipt_registry import (
    model_invocation_receipt_coverage,
    question_model_invocation_receipt_refs,
    question_model_invocation_receipts,
)
from .workflow_artifact_store import list_workflow_artifacts


class ResultPackageV2Error(ValueError):
    """The formal run does not yet contain a truthful v2 output authority."""

    def __init__(self, message: str, *, code: str = "challenge_v2_authority_missing"):
        super().__init__(message)
        self.code = code


_SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "selection": ("selection",),
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _mapping(value: Any) -> dict[str, Any]:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _first_mapping(container: Mapping[str, Any], *keys: str) -> dict[str, Any] | None:
    for key in keys:
        value = container.get(key)
        if isinstance(value, Mapping) and value:
            return deepcopy(dict(value))
    return None


def _list_of_mappings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [deepcopy(dict(item)) for item in value if isinstance(item, Mapping)]


def _pick(mapping: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in mapping:
            return mapping[name]
    return None


def _require_text(value: Any, field: str) -> str:
    result = _text(value)
    if not result:
        raise ResultPackageV2Error(f"canonical authority is missing {field}")
    return result


def _require_section(
    artifacts: Sequence[Mapping[str, Any]], field: str
) -> dict[str, Any]:
    aliases = _SECTION_ALIASES[field]
    found: list[dict[str, Any]] = []
    for artifact in artifacts:
        for alias in aliases:
            value = artifact.get(alias)
            if isinstance(value, Mapping) and value:
                found.append(deepcopy(dict(value)))
                break
    if not found:
        raise ResultPackageV2Error(f"canonical authority is missing {field}")
    first = found[0]
    if any(item != first for item in found[1:]):
        raise ResultPackageV2Error(
            f"canonical authorities disagree on {field}",
            code="challenge_v2_authority_conflict",
        )
    return first


def _artifact_payload(
    kind: str,
    *,
    team_id: str,
    workflow_run_id: str,
    authority_run_id: str,
) -> dict[str, Any]:
    envelope = load_scoped_artifact_payload(
        kind,
        team_id=team_id,
        authority_run_id=authority_run_id,
        workflow_run_id=workflow_run_id,
    )
    if not isinstance(envelope, Mapping):
        raise ResultPackageV2Error(f"canonical artifact is missing: {kind}")
    payload = envelope.get("payload")
    if isinstance(payload, Mapping):
        return deepcopy(dict(payload))
    return deepcopy(dict(envelope))


def _catalog_question(question_id: str) -> dict[str, Any]:
    questions = load_science_question_catalog().get("questions") or []
    result = next(
        (
            dict(item)
            for item in questions
            if isinstance(item, Mapping) and _text(item.get("id")).upper() == question_id
        ),
        None,
    )
    if result is None:
        raise ResultPackageV2Error(
            f"question is not in the official 125-question catalog: {question_id}",
            code="challenge_v2_question_not_official",
        )
    return result


def _scope(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    frozen = _mapping(snapshot.get("researchScopeEnvelope"))
    constraint = _mapping(snapshot.get("constraintSnapshot"))
    scope = {
        "theme_id": _text(
            snapshot.get("themeId")
            or frozen.get("themeId")
            or frozen.get("theme")
            or constraint.get("themeId")
        ),
        "campaign_id": _text(
            snapshot.get("campaignId")
            or frozen.get("campaignId")
            or frozen.get("campaign")
            or constraint.get("campaignId")
        ),
        "research_project_id": _text(
            snapshot.get("researchProjectId")
            or snapshot.get("projectId")
            or frozen.get("researchProjectId")
        ),
        "memory_scope": _text(
            snapshot.get("memoryScope") or frozen.get("memoryScope")
        )
        or "same_theme",
    }
    missing = [key for key, value in scope.items() if not value]
    if missing:
        raise ResultPackageV2Error(
            "frozen run scope is missing: " + ", ".join(missing)
        )
    branch = _text(
        snapshot.get("hypothesisBranchId")
        or frozen.get("hypothesisBranchId")
        or frozen.get("branch")
    )
    if branch:
        scope["hypothesis_branch_id"] = branch
    return scope


def _model_run(
    record: Mapping[str, Any],
    *,
    team_id: str,
    question_id: str,
    workflow_run_id: str,
    authority_run_id: str,
) -> dict[str, Any]:
    lineage = [workflow_run_id]
    cursor = workflow_run_id
    feedback_artifacts = [
        dict(item)
        for item in list_workflow_artifacts(team_id, kind="feedback_iterations")
        if _text(item.get("sourceCollectionRunId")) == authority_run_id
        and isinstance(item.get("payload"), Mapping)
    ]
    while True:
        parents = {
            _text(_mapping(item.get("payload")).get("parentRunId"))
            for item in feedback_artifacts
            if _text(_mapping(item.get("payload")).get("childRunId")) == cursor
        }
        parents.discard("")
        if not parents:
            break
        if len(parents) != 1:
            raise ResultPackageV2Error(
                "model receipt run lineage is ambiguous",
                code="challenge_v2_receipts_incomplete",
            )
        cursor = parents.pop()
        if cursor in lineage:
            raise ResultPackageV2Error(
                "model receipt run lineage contains a cycle",
                code="challenge_v2_receipts_incomplete",
            )
        lineage.append(cursor)
    refs: list[dict[str, Any]] = []
    current_refs: list[dict[str, Any]] = []
    for run_id in reversed(lineage):
        run_refs = question_model_invocation_receipt_refs(
            team_id,
            question_id=question_id,
            workflow_run_id=run_id,
        )
        refs.extend(run_refs)
        if run_id == workflow_run_id:
            current_refs = run_refs
    receipt_ids = [_text(ref.get("receiptId")) for ref in refs]
    if any(not item for item in receipt_ids) or len(set(receipt_ids)) != len(receipt_ids):
        raise ResultPackageV2Error(
            "model invocation receipt lineage contains an invalid or duplicate receipt",
            code="challenge_v2_receipts_incomplete",
        )
    proposal_only = is_proposal_only_challenge_run(record)
    if proposal_only:
        # Stage-one proposal runs register no final_output outcome and carry
        # no frozen modelRoutingDecisions; the receipt registry itself is the
        # route authority (see _stage_one_model_route).
        provider, model_id = _stage_one_model_route(record, current_refs or refs)
    else:
        coverage = model_invocation_receipt_coverage(refs)
        if coverage.get("status") != "passed":
            raise ResultPackageV2Error(
                "registered model invocation receipts do not cover the complete research loop",
                code="challenge_v2_receipts_incomplete",
            )
        final_node_ids = {
            _text(ref.get("nodeRunId"))
            for ref in current_refs
            if "final_output" in list(ref.get("outcomeKinds") or [])
        }
        routes = [
            dict(item)
            for item in list(record.get("modelRoutingDecisions") or [])
            if isinstance(item, Mapping)
            and _text(item.get("nodeRunId")) in final_node_ids
        ]
        if len(routes) != 1:
            raise ResultPackageV2Error(
                "final_output receipt has no unique frozen model route",
                code="challenge_v2_model_route_missing",
            )
        route = routes[0]
        provider = _require_text(route.get("providerId"), "run.model_provider")
        model_id = _require_text(
            route.get("modelRef") or route.get("modelId"), "run.model_id"
        )
    # The route/receipt authority names concrete deployment ids; the schema
    # run block projects the official-model family token (see
    # _official_provider_family).  Unknown families stay verbatim and keep
    # failing the exact-match official-provider gate downstream.
    provider = _official_provider_family(provider)
    started_at = _require_text(
        record.get("createdAt") or record.get("startedAt"), "run.started_at"
    )
    result = {
        "run_id": workflow_run_id,
        "started_at": started_at,
        "model_provider": provider,
        "model_id": model_id,
        "platform": _platform_for_provider(provider),
        "invocation_evidence_refs": [
            f"model-invocation-receipt:{_require_text(ref.get('receiptId'), 'receiptId')}"
            for ref in refs
        ],
    }
    completed_at = _text(record.get("completedAt") or record.get("updatedAt"))
    if completed_at:
        result["completed_at"] = completed_at
    workflow_version = _text(record.get("workflowVersionId"))
    if workflow_version:
        result["workflow_version"] = workflow_version
    return result


def _platform_for_provider(provider: str) -> str:
    normalized = str(provider or "").strip().casefold()
    if any(marker in normalized for marker in ("dashscope", "aliyun", "bailian")):
        return "aliyun_bailian"
    if "qoderwork" in normalized:
        return "qoderwork"
    if "qoder" in normalized:
        return "qoder"
    if "meoo" in normalized:
        return "meoo"
    return "other_official_tool"


def _official_provider_family(provider: str) -> str:
    """Collapse a concrete provider id onto its official-model family token.

    ``challenge_question_runs.OFFICIAL_PROVIDERS`` matches exactly against
    {"dashscope", "bailian", "aliyun"}, while frozen routes and receipts carry
    concrete deployment ids (e.g. ``dashscope_main``).  This mirrors the
    substring markers used by ``_platform_for_provider`` and only collapses
    the known official families; any other provider id stays verbatim so the
    exact-match official-provider gate keeps failing closed for it.  The full
    provider id remains queryable from the registered receipt refs.
    """
    normalized = str(provider or "").strip().casefold()
    if "dashscope" in normalized:
        return "dashscope"
    if "aliyun" in normalized:
        return "aliyun"
    if "bailian" in normalized:
        return "bailian"
    return str(provider or "").strip()


def _stage_one_model_route(
    record: Mapping[str, Any],
    refs: Sequence[Mapping[str, Any]],
) -> tuple[str, str]:
    """Resolve (provider, model_id) from the run's registered receipts.

    Stage-one proposal runs are multi-model by frozen policy and register no
    ``final_output``-outcome receipts, so the existing single-final-route
    read cannot apply.  The receipt registry is still the only route
    authority: every registered receipt of the run must share one provider,
    and the model id is the deterministic projection of the models that
    actually produced the run's succeeded invocations (a single model, or
    the sorted join when the frozen policy used several).  No route fact is
    invented: an empty or provider-ambiguous receipt set fails closed.
    """

    if not refs:
        raise ResultPackageV2Error(
            "stage-one run has no registered model invocation receipts",
            code="challenge_v2_receipts_incomplete",
        )
    receipts = question_model_invocation_receipts(
        team_id=_text(record.get("teamId")),
        question_id=_text(
            _mapping(record.get("inputSnapshot")).get("questionId")
            or record.get("questionId")
        ),
        workflow_run_id=_text(record.get("runId")),
    )
    providers = {_text(item.get("provider")) for item in receipts}
    providers.discard("")
    if len(providers) != 1:
        raise ResultPackageV2Error(
            "stage-one run receipts do not establish a unique model provider: "
            + (", ".join(sorted(providers)) or "none registered"),
            code="challenge_v2_model_route_missing",
        )
    models = {
        _text(item.get("model")) or _text(item.get("requestedModel"))
        for item in receipts
        if _text(item.get("status")) == "succeeded"
    }
    models.discard("")
    if not models:
        raise ResultPackageV2Error(
            "stage-one run receipts contain no succeeded model invocation",
            code="challenge_v2_model_route_missing",
        )
    model_id = models.pop() if len(models) == 1 else "+".join(sorted(models))
    return providers.pop(), model_id



# Canonical claim-evidence records (``ClaimEvidenceStore``) persist the
# verbatim fact anchor as ``quote`` and encode support/verification as
# ``supportLevel``/``reviewStatus``.  Projecting those exact fields is the
# faithful inverse of the materializer's forward mapping
# (``agent_claim_evidence_materializer``: relation supports -> supports,
# challenges -> contradicts, everything else -> insufficient); no fact that
# the authority does not carry is ever synthesized here.
_SUPPORT_LEVEL_RELATIONS = {
    "supports": "supports",
    "contradicts": "challenges",
    "insufficient": "context",
    "unverified": "context",
}

# Authority chain for ``verification_status``: card-level human review >
# source candidate collection-stage screening > fail-closed floor.  A
# card-level human acceptance is the only ``human_verified`` authority, and a
# rejected/stale verdict keeps the fail-closed floor — it is never overridden
# by the weaker source-level authority.  ``pending`` (and any unknown status)
# deliberately falls through to that source-level check.
_REVIEW_STATUS_VERIFICATIONS = {
    "accepted": "human_verified",
    "rejected": "unverified",
    "stale": "unverified",
}

# A source candidate the collection stage already screened with metadata-level
# verification (``qualityStatus == "source_quality_approved"`` and
# ``currentState == "source_screened"`` — the stage that persisted the
# abstract) is the schema's ``metadata_checked`` made concrete.  This reads
# the existing source_candidate_batch authority; it verifies nothing new.
_SOURCE_SCREENED_VERIFICATION = "metadata_checked"

# Candidate ``sourceKind`` values outside the curated set (e.g. ``url``) fall
# back to the schema's explicit non-authoritative umbrella classification.
_SOURCE_KIND_SOURCE_TYPES = {
    "paper": "peer_reviewed_paper",
    "preprint": "preprint",
    "dataset": "dataset",
    "standard": "standard",
    "official": "official_document",
    "book": "book",
    "url": "other",
}


def _support_level_relation(card: Mapping[str, Any]) -> str:
    support_level = _text(card.get("supportLevel")).strip().casefold()
    return _SUPPORT_LEVEL_RELATIONS.get(support_level, "")


def _review_status_verification(
    card: Mapping[str, Any], candidate: Mapping[str, Any]
) -> str:
    review_status = _text(card.get("reviewStatus")).strip().casefold()
    card_decision = _REVIEW_STATUS_VERIFICATIONS.get(review_status, "")
    if card_decision:
        return card_decision
    if (
        _text(candidate.get("qualityStatus")).strip().casefold()
        == "source_quality_approved"
        and _text(candidate.get("currentState")).strip().casefold()
        == "source_screened"
    ):
        return _SOURCE_SCREENED_VERIFICATION
    return "unverified"


def _evidence_item(card: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    locator = _mapping(card.get("citationLocator"))
    source_type = _text(
        _pick(card, "source_type", "sourceType")
        or _pick(candidate, "source_type", "sourceType")
    )
    if not source_type:
        source_type = _SOURCE_KIND_SOURCE_TYPES.get(
            _text(candidate.get("sourceKind")).lower(), "other"
        )
    result: dict[str, Any] = {
        "evidence_id": _require_text(
            _pick(card, "evidence_id", "evidenceId", "claimEvidenceId")
            or card.get("sourceId"),
            "evidence.evidence_id",
        ),
        "title": _require_text(card.get("title") or candidate.get("title"), "evidence.title"),
        "source_type": _require_text(source_type, "evidence.source_type"),
        "source_url": _require_text(
            _pick(card, "source_url", "sourceUrl")
            or locator.get("sourceRef")
            or candidate.get("sourceUrl"),
            "evidence.source_url",
        ),
        "retrieved_at": _require_text(
            _pick(card, "retrieved_at", "retrievedAt")
            or candidate.get("retrievedAt")
            or candidate.get("updatedAt"),
            "evidence.retrieved_at",
        ),
        # ``quote`` is the claim-evidence authority's verbatim fact anchor;
        # a card without it (and without fact/claim) still fails closed.
        "fact": _require_text(
            card.get("fact") or card.get("claim") or card.get("quote"),
            "evidence.fact",
        ),
        "relation": _require_text(
            card.get("relation") or _support_level_relation(card),
            "evidence.relation",
        ),
        "verification_status": _require_text(
            _pick(card, "verification_status", "verificationStatus")
            or _review_status_verification(card, candidate),
            "evidence.verification_status",
        ),
    }
    for target, aliases in (
        ("doi", ("doi",)),
        ("publication_date", ("publication_date", "publicationDate")),
    ):
        value = _text(_pick(card, *aliases) or _pick(candidate, *aliases))
        if value:
            result[target] = value
    limitations = card.get("limitations")
    if isinstance(limitations, list):
        result["limitations"] = deepcopy(limitations)
    return result


def _evidence(
    evidence_payload: Mapping[str, Any],
    candidate_payload: Mapping[str, Any],
    hypothesis_candidates: Sequence[Mapping[str, Any]] | None = None,
    project_candidates: Sequence[Mapping[str, Any]] | None = None,
    dimension_hypothesis_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    direct = _list_of_mappings(evidence_payload.get("evidence"))
    if direct:
        return direct
    cards = _list_of_mappings(
        evidence_payload.get("evidenceCards") or evidence_payload.get("cards")
    )
    candidates = _list_of_mappings(
        candidate_payload.get("candidates") or candidate_payload.get("candidateSources")
    )
    by_id = {
        _text(item.get("candidateId") or item.get("sourceId") or item.get("recordId")): item
        for item in candidates
    }
    # Aggregated review-cited batches layer three more real identity
    # authorities onto the authority-run batch, each filling only the ids the
    # previous layers do not already know (first-seen wins, so the strongest
    # authority keeps precedence):
    #   - the hypothesis_set candidates: review-cited batches carry
    #     hypothesis-level card bindings under the hypothesis candidate id, a
    #     space disjoint from the source candidate ids;
    #   - the run owner project's candidate store records: production cards
    #     cite source ids whose full records live on an earlier collection
    #     run of the same project that the authority batch does not carry;
    #   - the hypothesis ids the dimension_reviews payload itself binds:
    #     production review rows persist chain ids the formal run's
    #     hypothesis_set does not carry, so the review authority confirms the
    #     id exists as a reviewed candidate while the empty record mapped
    #     here makes no envelope claims.
    # Ids unknown to ALL authorities still fail closed below, and only
    # aggregated payloads receive these parameters, so the single
    # authority-run path keeps its exact fail-closed behavior.
    if hypothesis_candidates:
        for item in hypothesis_candidates:
            hypothesis_id = _text(
                item.get("candidateId")
                or item.get("hypothesisId")
                or item.get("hypothesis_id")
            )
            if hypothesis_id and hypothesis_id not in by_id:
                by_id[hypothesis_id] = item
    if project_candidates:
        for item in project_candidates:
            candidate_id = _text(
                item.get("candidateId") or item.get("sourceId") or item.get("recordId")
            )
            if candidate_id and candidate_id not in by_id:
                by_id[candidate_id] = item
    if dimension_hypothesis_ids:
        for hypothesis_id in dimension_hypothesis_ids:
            if hypothesis_id and hypothesis_id not in by_id:
                by_id[hypothesis_id] = {}
    if not cards:
        raise ResultPackageV2Error("canonical evidence_card_batch contains no evidence")
    projected: list[dict[str, Any]] = []
    for card in cards:
        candidate_id = _text(card.get("candidateId") or card.get("recordId"))
        if candidate_id and candidate_id not in by_id:
            # Fail closed naming the orphaned candidate instead of projecting
            # a card whose source identity cannot be resolved.
            raise ResultPackageV2Error(
                "canonical evidence card "
                f"{_text(card.get('claimEvidenceId') or card.get('evidenceId') or card.get('evidence_id'))} "
                f"references candidate {candidate_id} missing from source_candidate_batch"
            )
        projected.append(
            _evidence_item(card, by_id.get(candidate_id or _text(card.get("sourceId")), {}))
        )
    return projected


def _cited_evidence_run_ids(dimension_payload: Mapping[str, Any]) -> list[str]:
    """Authority run ids of the evidence-card batches cited by the reviews.

    Review rows persist canonical ``evidence_card_batch://`` refs (grounded
    by ``dimension_reviews_input_binding``), so the set of source-collection
    runs whose cards the review actually read is derivable from the
    dimension_reviews authority alone.  Bare citations, other kinds, and
    unparsable refs are ignored; duplicates collapse into a sorted list.
    """

    runs: set[str] = set()
    rows = _list_of_mappings(
        dimension_payload.get("dimensionReviews")
        or dimension_payload.get("dimension_reviews")
    )
    for candidate in _list_of_mappings(dimension_payload.get("candidates")):
        rows.extend(
            _list_of_mappings(
                candidate.get("dimensionReviews")
                or candidate.get("dimension_reviews")
            )
        )
    for row in rows:
        for ref in list(row.get("evidence_refs") or row.get("evidenceRefs") or []):
            parsed = parse_canonical_ref(_text(ref))
            if parsed and parsed["kind"] == "evidence_card_batch":
                run_id = _text(parsed["authorityRunId"])
                if run_id:
                    runs.add(run_id)
    return sorted(runs)


def _dimension_hypothesis_ids(dimension_payload: Mapping[str, Any]) -> list[str]:
    """Hypothesis ids the dimension_reviews authority itself binds.

    Production review rows persist ``hypothesis_id`` (the hypothesis-first
    chain ids) that the formal run's hypothesis_set artifact does not carry,
    so the reviews are themselves a real identity authority for the evidence
    gate: an id the reviews bound is a known reviewed candidate, and the
    empty record mapped for it in ``_evidence`` makes no envelope claims.
    Row gathering reuses the ``_cited_evidence_run_ids`` pattern (top-level
    rows plus rows nested under per-candidate containers); the selection
    block's candidate ids (selected, rejected, listed candidates) are
    harvested too.  Duplicates collapse into a sorted list.
    """

    ids: set[str] = set()
    rows = _list_of_mappings(
        dimension_payload.get("dimensionReviews")
        or dimension_payload.get("dimension_reviews")
    )
    for candidate in _list_of_mappings(dimension_payload.get("candidates")):
        rows.extend(
            _list_of_mappings(
                candidate.get("dimensionReviews")
                or candidate.get("dimension_reviews")
            )
        )
    for row in rows:
        hypothesis_id = _text(row.get("hypothesis_id") or row.get("hypothesisId"))
        if hypothesis_id:
            ids.add(hypothesis_id)
    selection = _mapping(dimension_payload.get("selection"))
    selected = _text(selection.get("selected_hypothesis_id"))
    if selected:
        ids.add(selected)
    for key in ("rejected_hypotheses", "candidates"):
        entries = selection.get(key)
        if not isinstance(entries, Sequence) or isinstance(
            entries, (str, bytes, bytearray)
        ):
            continue
        for entry in entries:
            if isinstance(entry, Mapping):
                entry_id = _text(
                    entry.get("hypothesis_id")
                    or entry.get("hypothesisId")
                    or entry.get("candidateId")
                )
            else:
                entry_id = _text(entry)
            if entry_id:
                ids.add(entry_id)
    return sorted(ids)


def _index_candidate_records(records: Sequence[Any]) -> dict[str, dict[str, str]]:
    """Reduce candidate-store records to ``sourceUrl -> {title, source_kind}``.

    Top-level fields win with the ``metadata`` envelope as fallback; the kind
    is read from ``sourceKind`` then ``sourceType`` (then
    ``metadata.sourceKind``).  ``candidate_graph`` rows are not source
    manifests and records without a URL+title pair contribute nothing; the
    first record seen for a URL wins (store order is the persistence order).
    """

    index: dict[str, dict[str, str]] = {}
    for candidate in records:
        if not isinstance(candidate, Mapping):
            continue
        if _text(candidate.get("candidateType")) == "candidate_graph":
            continue
        metadata = candidate.get("metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}
        url = _text(candidate.get("sourceUrl") or metadata.get("sourceUrl"))
        title = _text(candidate.get("title") or metadata.get("title"))
        source_kind = _text(
            candidate.get("sourceKind")
            or candidate.get("sourceType")
            or metadata.get("sourceKind")
        )
        if url and title and url not in index:
            index[url] = {"title": title, "source_kind": source_kind}
    return index


def _cited_runs_candidate_record_index(
    *, team_id: str, cited_run_ids: Sequence[str]
) -> dict[str, dict[str, str]]:
    """Cited-runs fallback authority: scoped per-run candidate batches.

    Used only when the frozen run scope names no research project; reads the
    same strict scoped loader as every other artifact authority here, so no
    run the reviews did not cite is ever read.
    """

    records: list[Any] = []
    for run_id in cited_run_ids:
        envelope = load_scoped_artifact_payload(
            "source_candidate_batch",
            team_id=team_id,
            authority_run_id=run_id,
        )
        if isinstance(envelope, Mapping):
            records.extend(
                envelope.get("candidates") or envelope.get("candidateSources") or []
            )
    return _index_candidate_records(records)


def _project_candidate_records(
    *, team_id: str, research_project_id: str
) -> list[dict[str, Any]]:
    """Read the run owner project's whole candidate store (one file read).

    The strict per-run scope is what canonical artifacts need, but the
    aggregated evidence path's truth domain is "sources this project
    collected": production cards cite ids and DOIs whose records live on
    earlier collection runs of the same project that the dimension reviews
    never cite, so the scoped read-back under-covers while the project-wide
    store covers every card.  This reads the store's own
    ``candidate_store/index.json`` under the project workspace root directly —
    deliberately bypassing ``load_scoped_artifact_payload`` — exactly once per
    package build, and returns the raw non-``candidate_graph`` candidate
    records so BOTH derived views come from that single read: the
    ``sourceUrl -> {title, source_kind}`` index for the lean projection and
    the ``candidateId -> record`` id authority for the evidence gate.  A store
    that cannot be resolved or read yields an empty list, so the cards keep
    failing closed instead of being guessed at.
    """

    try:
        workspace = resolve_research_project_workspace_root(
            team_id, research_project_id
        )
        payload = json.loads(
            (workspace / "candidate_store" / "index.json").read_text(encoding="utf-8")
        )
    except Exception:
        return []
    records = payload.get("candidates") if isinstance(payload, Mapping) else None
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
        return []
    return [
        deepcopy(dict(record))
        for record in records
        if isinstance(record, Mapping)
        and _text(record.get("candidateType")) != "candidate_graph"
    ]


def _project_candidates_reader(
    *, team_id: str, research_project_id: str
) -> Callable[[], list[dict[str, Any]]]:
    """Memoize the single project-store read for one package build.

    The aggregated evidence path consumes the project records twice — as the
    lean title/kind index inside the aggregation layer and as the
    ``candidateId`` id authority in ``_evidence`` — and both consumers must be
    served by the same single file read.  The returned closure reads the store
    at most once per build; the single-run path never invokes it.
    """

    records: list[dict[str, Any]] | None = None

    def read() -> list[dict[str, Any]]:
        nonlocal records
        if records is None:
            records = _project_candidate_records(
                team_id=team_id, research_project_id=research_project_id
            )
        return records

    return read


def _project_candidate_record_index(
    *, team_id: str, research_project_id: str
) -> dict[str, dict[str, str]]:
    """Derive the lean projection's url title/kind index from one store read."""

    return _index_candidate_records(
        _project_candidate_records(
            team_id=team_id, research_project_id=research_project_id
        )
    )


def _source_candidate_record_index(
    *,
    team_id: str,
    cited_run_ids: Sequence[str],
    research_project_id: str = "",
) -> dict[str, dict[str, str]]:
    """Resolve lean-card title/kind from the project store, cited runs fallback.

    The frozen run scope names the owning research project for every formal
    challenge run, so the project-wide store is the primary authority; without
    a project id there is nothing to resolve against but the cited runs' own
    scoped batches, and guessing a project is never an option.
    """

    if research_project_id:
        return _project_candidate_record_index(
            team_id=team_id, research_project_id=research_project_id
        )
    return _cited_runs_candidate_record_index(team_id=team_id, cited_run_ids=cited_run_ids)


def _project_lean_evidence_card(
    card: Mapping[str, Any], record_index: Mapping[str, Mapping[str, str]]
) -> dict[str, Any]:
    """Project the v2 envelope fields a claim-evidence card lacks (fill-missing).

    Hypothesis-first stores persist cards with only ``quote`` / ``sourceId`` /
    ``locator`` / store timestamps / ``evidenceKind`` — no collection-stage
    envelope — and candidateId-bearing cards can resolve to authorities that
    carry no envelope either (a dimension-harvested hypothesis id maps to an
    empty record; a project-store record may lack individual fields), so the
    strict ``_evidence_item`` requirements would fail closed.  Each missing
    field is filled only from an authority the card already carries: the
    ``kind: "url"`` locator becomes ``source_url``, the store timestamps
    become ``retrieved_at``, and the URL-shaped ``sourceId`` resolves title
    and source kind against the project-wide (or cited runs') candidate
    records — a recognized candidate kind maps through the existing
    ``_SOURCE_KIND_SOURCE_TYPES`` vocabulary (``paper`` →
    ``peer_reviewed_paper``), and only an unrecognized or missing candidate
    kind falls back to the evidence-kind vocabulary (``primary_result`` lands
    on the schema's non-authoritative ``other``).  Nothing is invented and
    nothing is overwritten: the projection is idempotent fill-missing, so a
    card whose envelope is already complete is returned unchanged, and a
    field that cannot be resolved from those authorities stays absent so the
    strict producer still raises.  The id-authority resolution (or orphan
    gate) in ``_evidence`` stays untouched.
    """

    projected = dict(card)
    matched = record_index.get(_text(card.get("sourceId"))) or {}
    locator = card.get("locator")
    if isinstance(locator, Mapping) and _text(locator.get("kind")).casefold() == "url":
        if not _text(_pick(projected, "source_url", "sourceUrl")):
            url = _text(locator.get("url"))
            if url:
                projected["source_url"] = url
    if not _text(_pick(projected, "retrieved_at", "retrievedAt")):
        retrieved_at = _text(card.get("updatedAt")) or _text(card.get("createdAt"))
        if retrieved_at:
            projected["retrieved_at"] = retrieved_at
    if not _text(_pick(projected, "source_type", "sourceType")):
        candidate_kind = _text(matched.get("source_kind")).casefold()
        mapped = _SOURCE_KIND_SOURCE_TYPES.get(candidate_kind, "")
        if mapped:
            projected["source_type"] = mapped
        else:
            evidence_kind = _text(card.get("evidenceKind")).casefold()
            if evidence_kind:
                projected["source_type"] = _SOURCE_KIND_SOURCE_TYPES.get(
                    evidence_kind, "other"
                )
    if not _text(_pick(projected, "title")):
        title = _text(matched.get("title"))
        if title:
            projected["title"] = title
    return projected


def _aggregated_evidence_card_payload(
    *,
    team_id: str,
    cited_run_ids: Sequence[str],
    research_project_id: str = "",
    project_candidates: Callable[[], list[dict[str, Any]]] | None = None,
) -> dict[str, Any] | None:
    """Merge every review-cited run's evidence-card batch into one payload.

    Stage-one runs accumulate claim-evidence cards across several
    source-collection runs (production SCI-009: 26 material requests spread
    over 6 runs) while the formal run's snapshot names only the earliest one
    as its authority, so the single-run read legitimately finds no cards.
    The cited run ids come from the dimension_reviews authority and each
    batch is read through the same strict scoped loader the single-run path
    uses — no run the reviews did not cite is ever read, and a batch that
    yields no cards contributes nothing.  Cards deduplicate by their
    claim-evidence identity (the append-only store gives one id one
    content).  ``None`` means nothing was aggregatable and the caller keeps
    the original fail-closed behavior.

    ``project_candidates`` is the memoized single-read loader for the run
    owner project's candidate store; when the frozen scope names no project
    the caller passes ``None`` and the cited runs' scoped batches stay the
    lean projection's index authority.
    """

    cards: list[dict[str, Any]] = []
    seen_card_ids: set[str] = set()
    aggregated_runs: list[str] = []
    for run_id in cited_run_ids:
        envelope = load_scoped_artifact_payload(
            "evidence_card_batch",
            team_id=team_id,
            authority_run_id=run_id,
        )
        run_cards = (
            _list_of_mappings(
                envelope.get("evidenceCards") or envelope.get("cards")
            )
            if isinstance(envelope, Mapping)
            else []
        )
        if not run_cards:
            continue
        aggregated_runs.append(run_id)
        for card in run_cards:
            card_id = _text(
                _pick(card, "claimEvidenceId", "evidenceId", "evidence_id")
            )
            if card_id:
                if card_id in seen_card_ids:
                    continue
                seen_card_ids.add(card_id)
            cards.append(card)
    if not cards:
        return None
    # Cards missing envelope fields — lean hypothesis-first cards, and
    # candidateId-bearing cards whose id may resolve to an envelope-less
    # authority — would fail closed at ``_evidence_item``; fill the missing
    # fields from the authorities the cards already carry.  The projection
    # is fill-missing and idempotent, so complete cards pass through
    # unchanged, and the id-authority resolution (or orphan gate) below
    # stays untouched.
    lean_projection = any(
        not _text(card.get("candidateId") or card.get("recordId"))
        or not _text(card.get("title"))
        for card in cards
    )
    if lean_projection:
        if project_candidates is not None:
            record_index = _index_candidate_records(project_candidates())
        else:
            record_index = _source_candidate_record_index(
                team_id=team_id,
                cited_run_ids=cited_run_ids,
                research_project_id=research_project_id,
            )
        cards = [_project_lean_evidence_card(card, record_index) for card in cards]
    return {
        "teamId": team_id,
        "sourceCollectionRunIds": aggregated_runs,
        "evidenceCards": cards,
        "cardCount": len(cards),
        "aggregatedFromDimensionReviews": True,
    }


def _evidence_card_payload(
    *,
    team_id: str,
    workflow_run_id: str,
    authority_run_id: str,
    dimension_payload: Mapping[str, Any],
    research_project_id: str = "",
    project_candidates: Callable[[], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Read evidence cards: authority run first, review-cited runs second.

    The frozen authority run stays the only first-layer source, so the
    single-run chain (e.g. SCI-091) is unchanged.  Only when that read fails
    with the canonical missing error — or comes back without cards — does
    the aggregation layer read the runs the dimension_reviews actually cite.
    When nothing is aggregatable, the original fail-closed error stands.
    Cards that lack collection-stage envelope fields (the lean hypothesis-
    first store shape, and cards whose candidateId may resolve to an
    envelope-less authority) get those fields filled from authorities the
    cards already carry; the fill is idempotent, so complete cards pass
    through unchanged.  Lean resolution reads the run owner project's
    candidate store when the frozen scope names the project (through the
    memoized single-read loader, shared with the id authority below), and
    falls back to the cited runs' scoped batches otherwise.
    """

    missing_error: ResultPackageV2Error | None = None
    try:
        payload = _artifact_payload(
            "evidence_card_batch",
            team_id=team_id,
            workflow_run_id=workflow_run_id,
            authority_run_id=authority_run_id,
        )
    except ResultPackageV2Error as exc:
        if "canonical artifact is missing: evidence_card_batch" not in str(exc):
            raise
        missing_error = exc
    else:
        if _list_of_mappings(payload.get("evidence")) or _list_of_mappings(
            payload.get("evidenceCards") or payload.get("cards")
        ):
            return payload
    aggregated = _aggregated_evidence_card_payload(
        team_id=team_id,
        cited_run_ids=_cited_evidence_run_ids(dimension_payload),
        research_project_id=research_project_id,
        project_candidates=project_candidates,
    )
    if aggregated is not None:
        return aggregated
    if missing_error is not None:
        raise missing_error
    return payload


def _citation_checks(evidence: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Build the citation receipts consumed by the Challenge Program gate.

    Citation validation is intentionally derived from the canonical evidence
    rows, rather than being an empty placeholder or a client-supplied pass
    flag.  Each check binds one evidence id to the exact source URL and
    verification status that the v2 output exposes.  Only canonical evidence
    verification states that establish a check (metadata, full text, or human
    verification) are marked as passed; all other states fail closed.  The
    status is a projection of the canonical verification authority, not a new
    validation authority.  The downstream validator still applies the evidence
    quality thresholds (authoritative and challenge/boundary counts).
    """

    passed_verification_statuses = {
        "metadata_checked",
        "full_text_checked",
        "human_verified",
    }
    checks: list[dict[str, Any]] = []
    for item in evidence:
        evidence_id = _require_text(
            item.get("evidence_id") or item.get("evidenceId"),
            "citation.evidence_id",
        )
        source_url = _require_text(
            item.get("source_url") or item.get("sourceUrl"),
            "citation.source_url",
        )
        verification_status = _require_text(
            _pick(item, "verification_status", "verificationStatus"),
            "citation.verification_status",
        )
        checks.append(
            {
                "evidenceId": evidence_id,
                "sourceUrl": source_url,
                "verificationStatus": verification_status,
                "status": (
                    "passed"
                    if verification_status.casefold() in passed_verification_statuses
                    else "failed"
                ),
            }
        )
    if not checks:
        raise ResultPackageV2Error(
            "canonical evidence has no citation receipts",
            code="challenge_v2_citations_missing",
        )
    return checks


def _accepted_round_record(
    *,
    team_id: str,
    dimension_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Read the accepted hypothesis round record referenced by the reviews.

    Returns {} when no round reference is available (fixture payloads without
    team/round binding keep their legacy behavior).  An unreadable round fails
    closed naming the round: the final-version binding below must never
    silently degrade to pre-revision content.
    """

    from core.web.services.team_workflow import hypothesis_rounds

    round_id = _text(dimension_payload.get("reviewRoundId"))
    if not team_id or not round_id:
        return {}
    try:
        round_payload = hypothesis_rounds.get_hypothesis_round(team_id, round_id)
    except Exception as exc:  # noqa: BLE001 - fail closed naming the round
        raise ResultPackageV2Error(
            f"canonical hypothesis round {round_id} is unreadable: {exc}"
        ) from exc
    return _mapping((round_payload or {}).get("round"))


def _final_revision_bindings_from_round(
    round_record: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Pin the accepted round's FORMAL R2 revision as the final version.

    The FORMAL review executor deliberately keeps ``round.candidates`` at R1
    and stores the actual R2 only inside ``revisionEnvelope``.  This returns
    ``{candidateId: canonical R2 snapshot row}`` for the revised candidate so
    every consumer projects the same final version.  The envelope content is
    verified against its own ``revision.outputHash`` using the exact canonical
    snapshot convention the executor wrote, so a stale or tampered envelope
    fails closed here at the handoff instead of at export time.  Rounds
    without a review-revision envelope bind nothing.
    """

    if not round_record:
        return {}
    round_id = _text(round_record.get("roundId"))
    envelope = _mapping(round_record.get("revisionEnvelope"))
    if not envelope or _text(envelope.get("phase")) != "review_revision":
        return {}
    revision = _mapping(envelope.get("revision"))
    if (
        revision.get("actual") is not True
        or _text(revision.get("status")) != "completed"
    ):
        return {}
    revised_id = _text(envelope.get("parentCandidateId"))
    output_rows = _list_of_mappings(_mapping(revision.get("output")).get("candidates"))
    matches = [
        row for row in output_rows if _text(row.get("candidateId")) == revised_id
    ]
    if not revised_id or len(matches) != 1:
        raise ResultPackageV2Error(
            f"canonical hypothesis round {round_id} revision envelope does not "
            f"carry exactly one R2 output row for candidate {revised_id or '<missing>'}",
            code="challenge_v2_feedback_conflict",
        )
    from core.web.services.team_workflow import hypothesis_review_executor

    # Hash authority alignment: the envelope outputHash was written by the
    # review executor's canonical snapshot + stable hash, so the same functions
    # verify the version here (never a locally re-invented hash).
    recomputed = hypothesis_review_executor._stable_hash(
        hypothesis_review_executor.canonical_hypothesis_revision_snapshot(output_rows)
    )
    recorded = _text(revision.get("outputHash")).lower()
    if recomputed != recorded:
        raise ResultPackageV2Error(
            f"canonical hypothesis round {round_id} revision envelope outputHash "
            f"does not match its R2 snapshot for candidate {revised_id}; the "
            "final version binding failed closed",
            code="challenge_v2_feedback_conflict",
        )
    return {revised_id: matches[0]}


def _apply_final_revision_binding(
    row: dict[str, Any],
    r2: Mapping[str, Any],
    *,
    hypothesis_id: str,
    round_id: str,
) -> None:
    """Overwrite one projected hypothesis row with its bound R2 final version.

    claim/testablePrediction/falsifier/axisProfile/lineageRefs come from the
    same hash-pinned R2 snapshot row; no field is stitched from the R1 round
    record or the chain candidate store.  ``novelty_basis`` is the one
    exception the revision contract itself defines: the canonical revision
    snapshot deliberately excludes prose, so the parent's
    ``differenceFromAlternatives`` remains the only persisted novelty
    statement and stays in the row.  Historical R1 scores are untouched and
    are never presented as R2 review verdicts.
    """

    def _required_r2_text(field: str, value: Any) -> str:
        text = _text(value)
        if not text:
            raise ResultPackageV2Error(
                f"canonical hypothesis {hypothesis_id} final revision (R2) is "
                f"missing {field} (round {round_id})"
            )
        return text

    axis = _mapping(r2.get("axisProfile"))
    row["statement"] = _required_r2_text("claim", r2.get("claim"))
    row["falsifiability"] = _required_r2_text("falsifier", r2.get("falsifier"))
    row["mechanism"] = _required_r2_text(
        "axisProfile.mechanism", axis.get("mechanism")
    )
    row["predictions"] = [
        text for text in (_text(r2.get("testablePrediction")),) if text
    ]
    row["boundary_conditions"] = [
        text for text in (_text(axis.get("boundary")),) if text
    ]
    row["supporting_evidence_refs"] = [
        _text(ref) for ref in list(r2.get("lineageRefs") or []) if _text(ref)
    ]


def _hypotheses_from_accepted_round(
    *,
    team_id: str,
    question_id: str,
    dimension_payload: Mapping[str, Any],
    _accepted_round: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Project hypotheses from the accepted hypothesis-first round authority.

    The stage-one hypothesis-first flow persists the ``hypothesis_set``
    portfolio without a per-candidate detail map, so the schema-required
    falsification criteria cannot come from it.  The real per-hypothesis
    authorities are (a) the accepted ``hypothesis_rounds`` record referenced
    by the dimension reviews' ``reviewRoundId`` (ids, claim, rationale,
    differenceFromAlternatives, noveltyContrast, lineageRefs) and (b) the
    run's ``hypothesis_first_chain`` ``hypothesis_candidate`` records
    (``falsifier``, ``testablePrediction`` and the structured
    ``axisProfile`` with ``mechanism``/``boundary``), matched by candidateId.
    Every projected value comes verbatim from those records; a candidate
    whose chain record carries no ``falsifier`` fails closed naming the
    candidate and its round.

    A04 final-version binding: when the accepted round carries a FORMAL
    ``revisionEnvelope`` (review_revision, actual=True), the revised
    candidate is projected from its hash-pinned R2 snapshot row instead of
    the pre-revision R1/chain content — the same binding every other
    consumer resolves through ``_final_revision_bindings_from_round``.
    """

    round_id = _text(dimension_payload.get("reviewRoundId"))
    if not round_id:
        raise ResultPackageV2Error(
            "canonical dimension_reviews is missing reviewRoundId; "
            "the accepted hypothesis round cannot be resolved"
        )
    if isinstance(_accepted_round, Mapping) and _accepted_round:
        round_record = _mapping(_accepted_round)
    else:
        round_record = _accepted_round_record(
            team_id=team_id, dimension_payload=dimension_payload
        )
    final_bindings = _final_revision_bindings_from_round(round_record)
    round_candidates = _list_of_mappings(round_record.get("candidates"))
    if not round_candidates:
        raise ResultPackageV2Error(
            f"canonical hypothesis round {round_id} contains no candidates"
        )
    try:
        from .hypothesis_first_chain import list_hypothesis_candidates

        chain_by_id = {
            _text(item.get("candidateId")): item
            for item in _list_of_mappings(
                list_hypothesis_candidates(team_id, question_id=question_id).get(
                    "candidates"
                )
            )
        }
    except ResultPackageV2Error:
        raise
    except Exception as exc:  # noqa: BLE001 - fail closed naming the authority
        raise ResultPackageV2Error(
            f"canonical chain hypothesis candidates are unreadable: {exc}"
        ) from exc

    result: list[dict[str, Any]] = []
    for candidate in round_candidates:
        hypothesis_id = _require_text(
            candidate.get("candidateId"), "hypothesis.round_candidate_id"
        )
        binding = final_bindings.get(hypothesis_id)
        if binding is not None:
            # R2 is the final version: take the body verbatim from the
            # hash-pinned revision snapshot instead of the R1/chain stores.
            novelty = _mapping(candidate.get("noveltyContrast"))
            novelty_basis = _text(
                candidate.get("differenceFromAlternatives")
                or novelty.get("deltaStatement")
            )
            if not novelty_basis:
                raise ResultPackageV2Error(
                    f"canonical hypothesis {hypothesis_id} is missing novelty_basis"
                )
            row = {
                "hypothesis_id": hypothesis_id,
                "statement": "",
                "mechanism": "",
                "novelty_basis": novelty_basis,
                "falsifiability": "",
                "predictions": [],
                "supporting_evidence_refs": [],
                "challenging_evidence_refs": [],
                "boundary_conditions": [],
            }
            _apply_final_revision_binding(
                row, binding, hypothesis_id=hypothesis_id, round_id=round_id
            )
            result.append(row)
            continue
        chain = _mapping(chain_by_id.get(hypothesis_id))
        axis = _mapping(chain.get("axisProfile"))
        novelty = _mapping(candidate.get("noveltyContrast"))
        falsifier = _text(chain.get("falsifier"))
        if not falsifier:
            raise ResultPackageV2Error(
                f"canonical hypothesis {hypothesis_id} is missing falsification criteria "
                f"(chain hypothesis_candidate record carries no falsifier; round {round_id})"
            )
        statement = _text(candidate.get("claim") or chain.get("statement"))
        if not statement:
            raise ResultPackageV2Error(
                f"canonical hypothesis {hypothesis_id} is missing statement"
            )
        mechanism = _text(axis.get("mechanism") or candidate.get("rationale"))
        if not mechanism:
            raise ResultPackageV2Error(
                f"canonical hypothesis {hypothesis_id} is missing mechanism"
            )
        novelty_basis = _text(
            candidate.get("differenceFromAlternatives")
            or novelty.get("deltaStatement")
        )
        if not novelty_basis:
            raise ResultPackageV2Error(
                f"canonical hypothesis {hypothesis_id} is missing novelty_basis"
            )
        predictions = [
            text
            for text in (_text(chain.get("testablePrediction")),)
            if text
        ]
        boundary = [
            text for text in (_text(axis.get("boundary")),) if text
        ]
        result.append(
            {
                "hypothesis_id": hypothesis_id,
                "statement": statement,
                "mechanism": mechanism,
                "novelty_basis": novelty_basis,
                "falsifiability": falsifier,
                "predictions": predictions,
                "supporting_evidence_refs": [
                    _text(ref)
                    for ref in list(candidate.get("lineageRefs") or [])
                    if _text(ref)
                ],
                "challenging_evidence_refs": [],
                "boundary_conditions": boundary,
            }
        )
    return result


def _hypotheses(
    payload: Mapping[str, Any],
    *,
    team_id: str = "",
    question_id: str = "",
    dimension_payload: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    direct = _list_of_mappings(payload.get("hypotheses"))
    if direct:
        return direct
    candidates = _list_of_mappings(payload.get("candidates"))
    details = _mapping(payload.get("candidateDetails"))
    # A04 unified final-version resolution: both the fragment candidateDetails
    # branch below and the accepted-round fallback bind the same hash-pinned
    # R2 revision envelope, so the package never projects pre-revision R1
    # content (or cross-version stitched fields) for a revised candidate.
    accepted_round = _accepted_round_record(
        team_id=team_id, dimension_payload=dimension_payload or {}
    )
    final_bindings = _final_revision_bindings_from_round(accepted_round)
    bound_round_id = _text(accepted_round.get("roundId"))
    result: list[dict[str, Any]] = []
    needs_round_projection = not candidates
    for candidate in candidates:
        hypothesis_id = _require_text(candidate.get("candidateId"), "hypothesis_id")
        detail = _mapping(details.get(hypothesis_id))
        criteria = detail.get("falsificationCriteria")
        if not isinstance(criteria, list) or not criteria:
            needs_round_projection = True
            break
        row = {
            "hypothesis_id": hypothesis_id,
            "statement": _require_text(
                detail.get("statement") or candidate.get("claim"), "hypothesis.statement"
            ),
            "mechanism": _require_text(detail.get("mechanism"), "hypothesis.mechanism"),
            "novelty_basis": _require_text(
                detail.get("novelty_basis") or detail.get("noveltyBasis"),
                "hypothesis.novelty_basis",
            ),
            "falsifiability": "; ".join(_require_text(item, "falsificationCriteria[]") for item in criteria),
            "predictions": deepcopy(list(detail.get("predictions") or [])),
            "supporting_evidence_refs": deepcopy(list(detail.get("evidenceRefs") or [])),
            "challenging_evidence_refs": deepcopy(list(detail.get("counterEvidenceRefs") or [])),
            "boundary_conditions": deepcopy(
                list(detail.get("boundary_conditions") or detail.get("boundaryConditions") or [])
            ),
        }
        binding = final_bindings.get(hypothesis_id)
        if binding is not None:
            _apply_final_revision_binding(
                row, binding, hypothesis_id=hypothesis_id, round_id=bound_round_id
            )
        result.append(row)
    if needs_round_projection:
        if dimension_payload is None or not team_id:
            raise ResultPackageV2Error(
                "canonical hypothesis_set candidates carry no falsification criteria "
                "and no accepted-round authority is available"
            )
        result = _hypotheses_from_accepted_round(
            team_id=team_id,
            question_id=question_id,
            dimension_payload=dimension_payload,
            _accepted_round=accepted_round or None,
        )
    if len(result) < 2:
        raise ResultPackageV2Error("canonical hypothesis_set contains fewer than two hypotheses")
    return result


def _same_run_hypothesis_feedback_iterations(
    artifacts: Sequence[Mapping[str, Any]],
    *,
    workflow_run_id: str,
) -> list[dict[str, Any]] | None:
    """Read the node-7 R0->R1->R2 lineage recorded inside one WorkflowRun."""

    payloads = [
        _mapping(item.get("payload"))
        for item in artifacts
        if _text(item.get("workflowRunId")) == workflow_run_id
        and _mapping(item.get("payload")).get("schemaVersion") == 2
        and _text(_mapping(item.get("payload")).get("nodeId"))
        == "hypothesis_design"
    ]
    if not payloads:
        return None
    expected_phases = {1: "grounded_revision", 2: "review_revision"}
    if len(payloads) != len(expected_phases):
        raise ResultPackageV2Error(
            "canonical same-run hypothesis feedback lineage is incomplete",
            code="challenge_v2_feedback_conflict",
        )
    by_round: dict[int, tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = {}
    for payload in payloads:
        iteration_round = payload.get("iterationRound")
        phase = _text(payload.get("revisionPhase"))
        envelope = _mapping(payload.get("revisionEnvelope"))
        row = _mapping(payload.get("feedbackIteration"))
        if (
            isinstance(iteration_round, bool)
            or not isinstance(iteration_round, int)
            or expected_phases.get(iteration_round) != phase
            or _text(envelope.get("phase")) != phase
            or row.get("round") != iteration_round
            or iteration_round in by_round
        ):
            raise ResultPackageV2Error(
                "canonical same-run hypothesis feedback lineage is invalid",
                code="challenge_v2_feedback_conflict",
            )
        parent = _mapping(envelope.get("parentOutput"))
        child = _mapping(envelope.get("childOutput"))
        for endpoint in (parent, child):
            refs = endpoint.get("refs")
            sha256 = _text(endpoint.get("sha256")).lower()
            if (
                not isinstance(refs, list)
                or not refs
                or any(not _text(ref) for ref in refs)
                or len(sha256) != 64
                or any(char not in "0123456789abcdef" for char in sha256)
            ):
                raise ResultPackageV2Error(
                    "canonical same-run hypothesis feedback lineage is invalid",
                    code="challenge_v2_feedback_conflict",
                )
        by_round[iteration_round] = (row, parent, child, payload)
    if set(by_round) != set(expected_phases):
        raise ResultPackageV2Error(
            "canonical same-run hypothesis feedback lineage is incomplete",
            code="challenge_v2_feedback_conflict",
        )
    for round_value, (row, parent, child, payload) in sorted(by_round.items()):
        # The canonical writer binds each revision envelope to its own row:
        # parentOutput == the row's input hash, childOutput == its output
        # hash.  Later rounds re-ground on their own review cycle instead of
        # chaining onto the previous child, so continuity is per-row, not
        # cross-round.
        if (
            _text(parent.get("sha256")).lower()
            != _text(payload.get("inputHash")).lower()
            or _text(child.get("sha256")).lower()
            != _text(payload.get("outputHash")).lower()
            or not _text(payload.get("inputHash"))
            or not _text(payload.get("outputHash"))
        ):
            raise ResultPackageV2Error(
                "canonical same-run hypothesis feedback lineage is discontinuous",
                code="challenge_v2_feedback_conflict",
            )
    return [
        deepcopy(by_round[index][0]) for index in sorted(by_round)
    ]


def _feedback_iterations(
    *, team_id: str, workflow_run_id: str, authority_run_id: str
) -> list[dict[str, Any]]:
    artifacts = [
        dict(item)
        for item in list_workflow_artifacts(team_id, kind="feedback_iterations")
        if _text(item.get("sourceCollectionRunId")) == authority_run_id
        and isinstance(item.get("payload"), Mapping)
    ]
    same_run_rows = _same_run_hypothesis_feedback_iterations(
        artifacts,
        workflow_run_id=workflow_run_id,
    )
    if same_run_rows is not None:
        return same_run_rows
    rows: list[dict[str, Any]] = []
    cursor = workflow_run_id
    seen_runs: set[str] = set()
    while cursor:
        if cursor in seen_runs:
            raise ResultPackageV2Error(
                "canonical feedback lineage contains a cycle",
                code="challenge_v2_feedback_conflict",
            )
        seen_runs.add(cursor)
        matches = [
            item
            for item in artifacts
            if _text(_mapping(item.get("payload")).get("childRunId")) == cursor
            or (
                _text(item.get("workflowRunId")) == cursor
                and not _text(_mapping(item.get("payload")).get("childRunId"))
            )
        ]
        if not matches:
            break
        if len(matches) != 1:
            raise ResultPackageV2Error(
                "canonical feedback lineage is ambiguous",
                code="challenge_v2_feedback_conflict",
            )
        payload = _mapping(matches[0].get("payload"))
        item = payload.get("feedbackIteration")
        if not isinstance(item, Mapping):
            raise ResultPackageV2Error(
                "canonical feedback lineage contains an invalid iteration",
                code="challenge_v2_feedback_conflict",
            )
        rows.append(deepcopy(dict(item)))
        cursor = _text(payload.get("parentRunId"))
    rows.sort(key=lambda item: int(item.get("round") or 0))
    if not rows:
        raise ResultPackageV2Error("canonical feedback_iterations contains no actual revision")
    if [item.get("round") for item in rows] != list(range(1, len(rows) + 1)):
        raise ResultPackageV2Error(
            "canonical feedback iterations are not contiguous",
            code="challenge_v2_feedback_conflict",
        )
    return rows


def _output_sha256(output: Mapping[str, Any]) -> str:
    hashable = deepcopy(dict(output))
    audit = hashable.setdefault("audit", {})
    audit["output_sha256"] = "0" * 64
    return canonical_sha256(hashable)


def _looks_like_canonical_result_package(value: Mapping[str, Any]) -> bool:
    """Avoid forwarding a thin result-package metadata projection as a package."""

    has_schema = value.get("schema_version") is not None or value.get("schemaVersion") is not None
    has_policy = value.get("model_policy") is not None or value.get("modelPolicy") is not None
    has_receipts = (
        value.get("model_invocation_receipts") is not None
        or value.get("modelInvocationReceipts") is not None
    )
    has_business_content = any(
        value.get(key) is not None
        for key in (
            "hypotheses",
            "dimension_reviews",
            "dimensionReviews",
            "selection",
            "research_plan",
            "researchPlan",
        )
    )
    return bool(has_schema and has_policy and has_receipts and has_business_content)


def _copy_package_authorities(
    package_core: dict[str, Any],
    *,
    generic_package: Mapping[str, Any],
    record: Mapping[str, Any],
) -> None:
    """Keep trusted package/receipt authority available at the handoff boundary."""

    canonical_package = _first_mapping(
        generic_package,
        "resultPackage",
        "result_package",
        "canonicalResultPackage",
    )
    if canonical_package is not None and not _looks_like_canonical_result_package(
        canonical_package
    ):
        canonical_package = None
    if canonical_package is None:
        candidate = _first_mapping(record, "resultPackage", "result_package")
        if candidate is not None and _looks_like_canonical_result_package(candidate):
            canonical_package = candidate
    if canonical_package is not None:
        package_core["resultPackage"] = canonical_package

    layers: tuple[Mapping[str, Any], ...] = (
        canonical_package or {},
        generic_package,
        record,
    )
    aliases: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("officialModelCall", ("officialModelCall", "official_model_call")),
        (
            "modelInvocationReceipts",
            ("modelInvocationReceipts", "model_invocation_receipts", "receipts"),
        ),
        ("modelPolicy", ("modelPolicy", "model_policy")),
        (
            "authorizedModelPolicySha256",
            (
                "authorizedModelPolicySha256",
                "authorized_model_policy_sha256",
                "expectedModelPolicySha256",
                "expected_model_policy_sha256",
            ),
        ),
        (
            "inputSnapshotSha256",
            ("inputSnapshotSha256", "input_snapshot_sha256", "inputSnapshotHash"),
        ),
    )
    for target, names in aliases:
        for layer in layers:
            value = _pick(layer, *names)
            if value is None or value == "":
                continue
            package_core[target] = deepcopy(value)
            break

    if "modelPolicy" not in package_core and canonical_package is not None:
        policy = _first_mapping(canonical_package, "modelPolicy", "model_policy")
        if policy is not None:
            package_core["modelPolicy"] = policy
    if "authorizedModelPolicySha256" not in package_core:
        policy = _mapping(package_core.get("modelPolicy"))
        policy_hash = _text(policy.get("policySha256") or policy.get("policy_sha256"))
        if policy_hash:
            package_core["authorizedModelPolicySha256"] = policy_hash


def _research_plan(plan_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Project the canonical plan authority into the v2 research plan.

    A nested ``researchPlan``/``research_plan`` mapping is already v2-shaped
    and is passed through.  The stage-one writer instead stores the proposal
    plan fields at the payload top level (``objective``/``method``/
    ``work_packages``/``human_gate``), so those are projected directly.  The
    execution-design list sections (variables, controls, timeline, ...) are
    stage-two protocol facts that a proposal-only plan genuinely does not
    carry — the completion policy defers those nodes — so they are projected
    as the empty lists the schema accepts rather than being fabricated.
    Missing objective/method/work_packages/human_gate still fail closed.
    """

    nested = _first_mapping(plan_payload, "researchPlan", "research_plan")
    if nested is not None:
        return nested
    objective = _text(plan_payload.get("objective"))
    method = _text(plan_payload.get("method"))
    work_packages = _list_of_mappings(plan_payload.get("work_packages"))
    gate = _mapping(plan_payload.get("human_gate"))
    missing = [
        name
        for name, value in (
            ("research_plan.objective", objective),
            ("research_plan.method", method),
            ("research_plan.work_packages", work_packages),
            ("research_plan.human_gate", gate),
        )
        if not value
    ]
    if missing:
        raise ResultPackageV2Error(
            "canonical research_plan contains no v2 research plan (missing: "
            + ", ".join(missing)
            + ")"
        )
    projected_packages: list[dict[str, Any]] = []
    for package in work_packages:
        projected_packages.append(
            {
                "work_package_id": _require_text(
                    package.get("work_package_id"), "research_plan.work_package_id"
                ),
                "goal": _require_text(
                    package.get("goal"), "research_plan.work_package.goal"
                ),
                "inputs": [
                    _text(value)
                    for value in list(package.get("inputs") or [])
                    if _text(value)
                ],
                "procedure": [
                    _text(value)
                    for value in list(package.get("procedure") or [])
                    if _text(value)
                ],
                "outputs": [
                    _text(value)
                    for value in list(package.get("outputs") or [])
                    if _text(value)
                ],
                "dependencies": [
                    _text(value)
                    for value in list(package.get("dependencies") or [])
                    if _text(value)
                ],
            }
        )
    projected_gate = {
        key: deepcopy(gate[key])
        for key in ("required", "decision", "rationale", "reviewer", "decided_at")
        if key in gate
    }
    plan: dict[str, Any] = {
        "objective": objective,
        "method": method,
        "work_packages": projected_packages,
        # Stage-two protocol sections are genuinely unplanned at stage one.
        "variables": [],
        "controls": [],
        "data_and_materials": [],
        "analysis": [],
        "success_criteria": [],
        "failure_criteria": [],
        "stop_conditions": [],
        "resources": [],
        "timeline": [],
        "risks": [],
        "human_gate": projected_gate,
    }
    return plan


def _final_summary(
    *,
    problem: Mapping[str, Any],
    selection: Mapping[str, Any],
    hypotheses: Sequence[Mapping[str, Any]],
    research_plan: Mapping[str, Any],
    dimension_payload: Mapping[str, Any],
    evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Derive the required final summary from the canonical sections.

    Stage-one runs persist no standalone final-summary artifact; the v2
    schema requires the section, so it is derived exactly like the citation
    checks: each field is a projection of an existing canonical authority
    (frozen problem scope, the selected hypothesis, the plan objective, the
    selected candidate's evidence lineage, counter-evidence rows from the
    canonical evidence cards, the meta-review risk notes and the first work
    package).  A field whose canonical source is empty fails closed.
    """

    answer_boundary = _text(problem.get("scope"))
    selected_id = _text(selection.get("selected_hypothesis_id"))
    selected = next(
        (
            item
            for item in hypotheses
            if _text(item.get("hypothesis_id")) == selected_id
        ),
        None,
    )
    statement = _text(selected.get("statement")) if selected else ""
    plan_summary = _text(research_plan.get("objective"))
    work_packages = _list_of_mappings(research_plan.get("work_packages"))
    next_step = _text(work_packages[0].get("goal")) if work_packages else ""
    missing = [
        name
        for name, value in (
            ("final_summary.answer_boundary (problem_understanding.scope)", answer_boundary),
            (
                "final_summary.selected_hypothesis "
                f"(selection references {selected_id or 'nothing'})",
                statement,
            ),
            ("final_summary.research_plan_summary (research_plan.objective)", plan_summary),
            ("final_summary.next_validation_step (work_packages[0].goal)", next_step),
        )
        if not value
    ]
    if missing:
        raise ResultPackageV2Error(
            "canonical authorities are missing: " + "; ".join(missing)
        )
    key_refs = [
        _text(ref)
        for ref in list(selected.get("supporting_evidence_refs") or [])
        if _text(ref)
    ]
    counter_refs = [
        _text(item.get("evidence_id") or item.get("evidenceId"))
        for item in evidence
        if _text(item.get("relation")) in {"challenges", "boundary"}
    ]
    meta_review = _mapping(dimension_payload.get("metaReview"))
    risk_notes = _text(meta_review.get("riskNotes"))
    return {
        "answer_boundary": answer_boundary,
        "selected_hypothesis": statement,
        "research_plan_summary": plan_summary,
        "key_evidence_refs": key_refs,
        "counterevidence_refs": [ref for ref in counter_refs if ref],
        "limitations": [risk_notes] if risk_notes else [],
        "next_validation_step": next_step,
    }


_COMPETITION_VIEW_TEXT_FIELDS = (
    "problem_statement",
    "rationale",
    "technical_details",
    "paper_title",
    "paper_abstract",
)
_COMPETITION_VIEW_LIST_FIELDS = ("methods", "experiments", "results", "references")
# The canonical schema closes competition_result_view (additionalProperties:
# false), so per-field caps are read from that schema instead of restated here.
_COMPETITION_VIEW_SENTENCE_TERMINATORS = "。！？；.!?;"
_DEFAULT_COMPETITION_VIEW_MAX_LENGTH = 500


@lru_cache(maxsize=1)
def _claim_boundary_max_length() -> int:
    """Read result_classification.claim_boundary's cap from the real schema.

    Same contract-ownership rule as the view caps: the frozen maxLength is
    derived from the schema file, with the uniform 500 fallback when the file
    is unreadable (packaging-time validation still fails closed).
    """

    from core.web.services.team_workflow import challenge_question_runs

    schema = challenge_question_runs._read_json(challenge_question_runs._schema_path(2))
    properties = (
        (schema.get("properties") or {}).get("result_classification") or {}
    ).get("properties") or {}
    cap = int((properties.get("claim_boundary") or {}).get("maxLength") or 0)
    return cap if cap > 0 else _DEFAULT_COMPETITION_VIEW_MAX_LENGTH


@lru_cache(maxsize=1)
def _competition_view_max_lengths() -> dict[str, int]:
    """Read the competition result view's per-field caps from the real schema.

    The frozen Challenge Cup submission contract owns these maxLengths; the
    projection derives them from ``schemas/challenge_question_output.v2.schema.json``
    so a contract change cannot drift past the builder.  Text fields cap the
    whole string; list (and dataset) fields cap each item.  When the schema
    file is unreadable the contract's uniform 500 applies — the real-schema
    validation at packaging time still fails closed regardless.
    """

    fields = _COMPETITION_VIEW_TEXT_FIELDS + _COMPETITION_VIEW_LIST_FIELDS
    caps: dict[str, int] = {
        field: _DEFAULT_COMPETITION_VIEW_MAX_LENGTH for field in fields
    }
    caps["datasets"] = _DEFAULT_COMPETITION_VIEW_MAX_LENGTH
    from core.web.services.team_workflow import challenge_question_runs

    schema = challenge_question_runs._read_json(challenge_question_runs._schema_path(2))
    properties = (
        (schema.get("properties") or {}).get("competition_result_view") or {}
    ).get("properties") or {}
    for field in _COMPETITION_VIEW_TEXT_FIELDS:
        cap = int((properties.get(field) or {}).get("maxLength") or 0)
        caps[field] = cap if cap > 0 else _DEFAULT_COMPETITION_VIEW_MAX_LENGTH
    for field in _COMPETITION_VIEW_LIST_FIELDS:
        cap = int(((properties.get(field) or {}).get("items") or {}).get("maxLength") or 0)
        caps[field] = cap if cap > 0 else _DEFAULT_COMPETITION_VIEW_MAX_LENGTH
    dataset_properties = ((properties.get("datasets") or {}).get("properties") or {})
    dataset_caps = [
        int(((dataset_properties.get(key) or {}).get("items") or {}).get("maxLength") or 0)
        for key in ("source", "target")
    ]
    dataset_caps = [cap for cap in dataset_caps if cap > 0]
    if dataset_caps:
        caps["datasets"] = min(dataset_caps)
    return caps


def _clamp_view_text(value: str, max_length: int) -> tuple[str, bool]:
    """Clamp one view string under the schema cap without decoration.

    Truncation prefers the last sentence boundary that keeps at least half the
    allowed budget, falls back to the last word boundary, and finally to a hard
    slice for unsegmentable text.  No ellipsis or marker is appended (that
    would break the same contract's constraints); the untouched authority keeps
    the full text.
    """

    text = value.strip()
    if len(text) <= max_length:
        return text, False
    window = text[:max_length]
    sentence_cut = 0
    for index, char in enumerate(window):
        if char in _COMPETITION_VIEW_SENTENCE_TERMINATORS and index + 1 >= max_length // 2:
            sentence_cut = index + 1
    if sentence_cut:
        return window[:sentence_cut].strip(), True
    word_cut = window.rfind(" ")
    if word_cut > 0:
        return window[:word_cut].strip(), True
    return window.strip(), True


def clamp_competition_result_view(
    view: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Clamp an already-shaped competition result view to the schema caps.

    Returns the clamped deep copy plus additive truncation records — the
    canonical view object itself is schema-closed, so those records are
    surfaced at the generic package level by the caller instead.
    """

    caps = _competition_view_max_lengths()
    clamped = deepcopy(dict(view))
    truncations: list[dict[str, Any]] = []

    def _clamp_string(field: str, value: Any, cap: int) -> Any:
        if not isinstance(value, str):
            return value
        result, truncated = _clamp_view_text(value, cap)
        if truncated:
            truncations.append(
                {
                    "field": field,
                    "originalLength": len(value.strip()),
                    "truncatedLength": len(result),
                }
            )
        return result

    def _clamp_string_list(field: str, values: Any, cap: int) -> Any:
        if not isinstance(values, list):
            return values
        return [
            _clamp_string(f"{field}[{index}]", item, cap)
            for index, item in enumerate(values)
        ]

    for field in _COMPETITION_VIEW_TEXT_FIELDS:
        clamped[field] = _clamp_string(field, clamped.get(field), caps[field])
    datasets = clamped.get("datasets")
    if isinstance(datasets, Mapping):
        # The writer stores ``used``/``planned`` aliases; clamp every list
        # under datasets so aliasing survives alongside canonical keys.
        for key in list(datasets):
            datasets[key] = _clamp_string_list(
                f"datasets.{key}", datasets[key], caps["datasets"]
            )
    for field in _COMPETITION_VIEW_LIST_FIELDS:
        clamped[field] = _clamp_string_list(field, clamped.get(field), caps[field])
    return clamped, truncations


def _competition_result_view(
    *,
    team_id: str,
    workflow_run_id: str,
    authority_run_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Project the competition alignment authority's result view.

    The stage-one ``competition_alignment`` artifact is the only real
    competition-result authority; its view keys already match the v2 schema
    except ``datasets`` (the stage-one writer stores ``used``/``planned``),
    which project onto the schema's ``source``/``target`` lists.  Missing
    required view fields fail closed naming the field.  Fields that exceed the
    frozen contract's per-field maxLengths are clamped at a sentence boundary
    and reported additively so one oversized stage-one scope statement can no
    longer invalidate the whole canonical output.
    """

    payload = _artifact_payload(
        "competition_alignment",
        team_id=team_id,
        workflow_run_id=workflow_run_id,
        authority_run_id=authority_run_id,
    )
    return _competition_view_from_payload(payload)


def _competition_view_from_payload(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    view = _first_mapping(payload, "competitionResultView", "competition_result_view")
    if view is None:
        raise ResultPackageV2Error(
            "canonical competition_alignment is missing competition_result_view"
        )
    datasets = _mapping(view.get("datasets"))
    result: dict[str, Any] = {}
    for field in _COMPETITION_VIEW_TEXT_FIELDS:
        result[field] = _require_text(
            view.get(field), f"competition_result_view.{field}"
        )
    result["datasets"] = {
        "source": [
            _text(value)
            for value in list(
                datasets.get("source") or datasets.get("used") or []
            )
            if _text(value)
        ],
        "target": [
            _text(value)
            for value in list(
                datasets.get("target") or datasets.get("planned") or []
            )
            if _text(value)
        ],
    }
    for field in _COMPETITION_VIEW_LIST_FIELDS:
        values = [
            _text(value)
            for value in list(view.get(field) or [])
            if _text(value)
        ]
        result[field] = values
    return clamp_competition_result_view(result)


def build_challenge_result_package_v2(
    *,
    generic_package: Mapping[str, Any],
    record: Mapping[str, Any],
    team_id: str,
    workflow_run_id: str,
    source_collection_run_id: str,
) -> dict[str, Any]:
    """Attach a schema-valid v2 output to a deterministic generic package."""

    snapshot = _mapping(record.get("inputSnapshot"))
    question_id = _require_text(
        snapshot.get("questionId") or record.get("questionId"), "identity.question_id"
    ).upper()
    question = _catalog_question(question_id)
    # The frozen run scope names the owning research project; the lean-card
    # resolver below reads that project's candidate store, not just the runs
    # the reviews cite.
    scope = _scope(snapshot)
    authority = _text(source_collection_run_id) or workflow_run_id
    # The aggregated evidence path consumes the project store twice — as the
    # lean title/kind index and as the candidateId id authority — so the read
    # is memoized here: at most one file read per package build, and none on
    # the single-run path.
    project_candidates_reader = (
        _project_candidates_reader(
            team_id=team_id, research_project_id=scope["research_project_id"]
        )
        if scope["research_project_id"]
        else None
    )
    problem = _artifact_payload(
        "problem_understanding",
        team_id=team_id,
        workflow_run_id=workflow_run_id,
        authority_run_id=authority,
    )
    candidates = _artifact_payload(
        "source_candidate_batch",
        team_id=team_id,
        workflow_run_id=workflow_run_id,
        authority_run_id=authority,
    )
    # The review authorities load before evidence: when the authority run
    # holds no evidence-card batch, the aggregation fallback derives the
    # review-cited evidence runs from dimension_reviews.
    hypothesis_set = _artifact_payload(
        "hypothesis_set",
        team_id=team_id,
        workflow_run_id=workflow_run_id,
        authority_run_id=authority,
    )
    dimension_payload = _artifact_payload(
        "dimension_reviews",
        team_id=team_id,
        workflow_run_id=workflow_run_id,
        authority_run_id=authority,
    )
    evidence_cards = _evidence_card_payload(
        team_id=team_id,
        workflow_run_id=workflow_run_id,
        authority_run_id=authority,
        dimension_payload=dimension_payload,
        research_project_id=scope["research_project_id"],
        project_candidates=project_candidates_reader,
    )
    research_payload = _artifact_payload(
        "stage1_research_plan" if is_proposal_only_challenge_run(record) else "research_plan",
        team_id=team_id,
        workflow_run_id=workflow_run_id,
        authority_run_id=authority,
    )
    authority_sections = [dimension_payload, hypothesis_set, research_payload]
    aggregated_cards = bool(evidence_cards.get("aggregatedFromDimensionReviews"))
    evidence = _evidence(
        evidence_cards,
        candidates,
        hypothesis_candidates=(
            _list_of_mappings(
                hypothesis_set.get("candidates") or hypothesis_set.get("hypotheses")
            )
            if aggregated_cards
            else None
        ),
        project_candidates=(
            project_candidates_reader() or None
            if aggregated_cards and project_candidates_reader is not None
            else None
        ),
        dimension_hypothesis_ids=(
            _dimension_hypothesis_ids(dimension_payload)
            if aggregated_cards
            else None
        ),
    )
    # The schema's hypothesis items are closed (additionalProperties: false),
    # so the per-candidate novelty contrast stays in its dimension_reviews
    # artifact authority; the hypothesis rows carry the novelty_basis
    # conclusion itself.
    hypotheses = _hypotheses(
        hypothesis_set,
        team_id=team_id,
        question_id=question_id,
        dimension_payload=dimension_payload,
    )
    reviews = _list_of_mappings(
        dimension_payload.get("dimensionReviews")
        or dimension_payload.get("dimension_reviews")
    )
    if not reviews:
        raise ResultPackageV2Error("canonical dimension_reviews contains no review rows")
    selection = _require_section(authority_sections, "selection")
    research_plan = _research_plan(research_payload)
    final_summary = _final_summary(
        problem=problem,
        selection=selection,
        hypotheses=hypotheses,
        research_plan=research_plan,
        dimension_payload=dimension_payload,
        evidence=evidence,
    )
    competition_view, view_truncations = _competition_result_view(
        team_id=team_id,
        workflow_run_id=workflow_run_id,
        authority_run_id=authority,
    )
    boundary_text = _require_text(
        _pick(final_summary, "answer_boundary", "answerBoundary"),
        "result_classification.claim_boundary",
    )
    boundary_clamped, boundary_truncated = _clamp_view_text(
        boundary_text, _claim_boundary_max_length()
    )
    classification_truncations: list[dict[str, Any]] = []
    if boundary_truncated:
        # final_summary keeps the full answer_boundary as the untouched
        # authority; only the classification's schema-capped copy is clamped.
        classification_truncations.append(
            {
                "field": "result_classification.claim_boundary",
                "originalLength": len(boundary_text.strip()),
                "truncatedLength": len(boundary_clamped),
            }
        )
    result_classification = {
        "status": "review_required",
        "actual_execution": False,
        "classification": "proposal_only",
        "claim_boundary": boundary_clamped,
        "final_summary": final_summary,
    }
    output: dict[str, Any] = {
        "schema_version": 2,
        "identity": {
            "catalog_id": CATALOG_ID,
            "question_id": question_id,
            "question_en": _require_text(question.get("question_en"), "identity.question_en"),
        },
        "classification": {
            "domain": _require_text(question.get("domain"), "classification.domain"),
            "specialization_profile_id": "SPEC-COMP-INFO-NEURO-v1",
            "is_specialty_question": question.get("domain")
            in {"information_science", "neuroscience"},
        },
        "scope": scope,
        "run": _model_run(
            record,
            team_id=team_id,
            question_id=question_id,
            workflow_run_id=workflow_run_id,
            authority_run_id=authority,
        ),
        "problem_understanding": problem,
        "evidence": evidence,
        "hypotheses": hypotheses,
        "dimension_reviews": reviews,
        "selection": selection,
        "research_plan": research_plan,
        "feedback_iterations": _feedback_iterations(
            team_id=team_id,
            workflow_run_id=workflow_run_id,
            authority_run_id=authority,
        ),
        "result_classification": result_classification,
        "competition_result_view": competition_view,
        "collaboration_refs": {
            "team_id": team_id,
            "meeting_digest_ids": deepcopy(list(snapshot.get("meetingDigestIds") or [])),
            "knowledge_item_ids": [str(item["evidence_id"]) for item in evidence],
            "template_version": "challenge-question-v2",
        },
        "review": {
            "human_review_status": "pending",
            "question_review_digest_ids": [],
        },
        "submission": {
            "eligible": False,
            "projection_version": "1.0-review.1",
            "blockers": ["human_review_pending"],
        },
        "audit": {
            "source_catalog_sha256": CATALOG_SHA256.lower(),
            "output_sha256": "0" * 64,
            "schema_validation": "passed",
            "citation_validation": "pending",
            "human_review_status": "pending",
        },
    }
    output["audit"]["output_sha256"] = _output_sha256(output)

    # Reuse the existing canonical schema dispatch; do not create a second
    # validator or add a JSON Schema dependency for this producer.
    from core.web.services.team_workflow import challenge_question_runs

    issues = challenge_question_runs._schema_issues(output)
    semantic = challenge_question_runs._semantic_validation(output)
    if semantic.get("status") != "passed":
        issues.extend(
            item
            for item in list(semantic.get("issues") or [])
            if isinstance(item, Mapping)
        )
    if issues:
        summary = "; ".join(
            f"{item.get('path')}: {item.get('message')}" for item in issues[:8]
        )
        raise ResultPackageV2Error(
            "canonical Challenge Question v2 output is invalid: " + summary,
            code="challenge_v2_schema_invalid",
        )

    package_core = deepcopy(dict(generic_package))
    for key in ("packageId", "packageRef", "contentHash"):
        package_core.pop(key, None)
    package_core.update(
        {
            "questionId": question_id,
            "challengeQuestionOutput": output,
            "citationChecks": _citation_checks(evidence),
        }
    )
    if view_truncations:
        # competition_result_view is schema-closed (additionalProperties:
        # false), so the truncation record stays at the generic package level.
        package_core["competitionResultViewTruncations"] = view_truncations
    if classification_truncations:
        # result_classification is schema-closed the same way; its truncation
        # record rides at the generic package level beside the view's.
        package_core["resultClassificationTruncations"] = classification_truncations
    _copy_package_authorities(
        package_core,
        generic_package=generic_package,
        record=record,
    )
    content_hash = canonical_sha256(package_core)
    return {
        **package_core,
        "packageId": f"rrp-v2:{workflow_run_id}:{question_id.lower()}:{content_hash[:16]}",
        "packageRef": f"research-result-package:{content_hash}",
        "contentHash": content_hash,
    }


def is_official_challenge_run(record: Mapping[str, Any]) -> bool:
    snapshot = _mapping(record.get("inputSnapshot"))
    question_id = _text(snapshot.get("questionId") or record.get("questionId")).upper()
    return question_id.startswith("SCI-")


def is_proposal_only_challenge_run(record: Mapping[str, Any]) -> bool:
    """Return true only for the frozen non-execution 125-question path."""

    if not is_official_challenge_run(record):
        return False
    snapshot = _mapping(record.get("inputSnapshot"))
    constraint = _mapping(snapshot.get("constraintSnapshot"))
    return constraint.get("formalWrites") is False


def build_proposal_result_package_base(record: Mapping[str, Any]) -> dict[str, Any]:
    """Build a deterministic generic envelope without claiming an experiment.

    The existing generic package requires controlled-run/evaluation facts.  A
    catalog hypothesis proposal intentionally has none, so its generic half is
    a lineage envelope only; the v2 half carries the actual research content.
    """

    run_id = _require_text(record.get("runId"), "package.runId")
    team_id = _require_text(record.get("teamId"), "package.teamId")
    project_id = _require_text(record.get("projectId"), "package.projectId")
    workflow_id = _require_text(record.get("workflowId"), "package.workflowId")
    workflow_version = _require_text(
        record.get("workflowVersionId"), "package.workflowVersionId"
    )
    terminal_reason = _require_text(
        record.get("terminalReason"), "package.terminalReason"
    )
    snapshot = _mapping(record.get("inputSnapshot"))
    snapshot_hash = _require_text(
        snapshot.get("snapshotHash")
        or record.get("inputSnapshotHash")
        or record.get("researchBriefHash"),
        "package.inputSnapshotHash",
    )
    artifact_refs = sorted(
        {
            _text(item.get("artifactId"))
            for item in list(record.get("artifactManifests") or [])
            if isinstance(item, Mapping) and _text(item.get("artifactId"))
        }
        | {
            _text(item)
            for item in list(record.get("inheritedArtifactRefs") or [])
            if _text(item)
        }
    )
    fact_chain = {
        "runId": run_id,
        "workflowVersionId": workflow_version,
        "questionId": _require_text(snapshot.get("questionId"), "package.questionId"),
        "inputSnapshotHash": snapshot_hash,
        "terminalReason": terminal_reason,
        "artifactRefs": artifact_refs,
        "classification": "proposal_only",
        "actualExecution": False,
    }
    fact_chain_hash = canonical_sha256(fact_chain)
    core: dict[str, Any] = {
        "runId": run_id,
        "workflowId": workflow_id,
        "workflowVersionId": workflow_version,
        "teamId": team_id,
        "projectId": project_id,
        "factChainHash": fact_chain_hash,
        "terminalReason": terminal_reason,
        "builtAt": _require_text(
            record.get("completedAt")
            or record.get("updatedAt")
            or record.get("createdAt"),
            "package.builtAt",
        ),
        "resultClassification": {
            "classification": "proposal_only",
            "actualExecution": False,
        },
        "traceability": {
            "artifactCount": len(artifact_refs),
            "artifactRefs": artifact_refs,
        },
    }
    official_version = record.get("officialVersion")
    if isinstance(official_version, Mapping) and official_version:
        core["officialVersion"] = deepcopy(dict(official_version))
    content_hash = canonical_sha256(core)
    return {
        **core,
        "packageId": f"rrp-proposal:{run_id}:{content_hash[:16]}",
        "packageRef": f"research-result-package:{content_hash}",
        "contentHash": content_hash,
    }


__all__ = [
    "ResultPackageV2Error",
    "build_challenge_result_package_v2",
    "build_proposal_result_package_base",
    "clamp_competition_result_view",
    "is_official_challenge_run",
    "is_proposal_only_challenge_run",
]
