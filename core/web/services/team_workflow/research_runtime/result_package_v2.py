"""Build the one canonical Challenge Question v2 result-package envelope.

This module is deliberately a strict producer, not a summarizer.  It reads
run-scoped canonical artifacts and only projects fields that those authorities
actually contain.  Missing selection, review, evidence, result-view, model
receipt, or scope facts stop packaging instead of being filled from scores or
free-form task summaries.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

from core.research.competition import (
    CATALOG_ID,
    CATALOG_SHA256,
    load_science_question_catalog,
)

from .artifact_readback_registry import load_scoped_artifact_payload
from .human_gate_artifacts import canonical_sha256
from .model_invocation_receipt_registry import (
    model_invocation_receipt_coverage,
    question_model_invocation_receipt_refs,
)
from .workflow_artifact_store import list_workflow_artifacts


class ResultPackageV2Error(ValueError):
    """The formal run does not yet contain a truthful v2 output authority."""

    def __init__(self, message: str, *, code: str = "challenge_v2_authority_missing"):
        super().__init__(message)
        self.code = code


_SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "selection": ("selection",),
    "final_summary": ("final_summary", "finalSummary"),
    "competition_result_view": ("competition_result_view", "competitionResultView"),
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _mapping(value: Any) -> dict[str, Any]:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}


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
            snapshot.get("themeId") or frozen.get("themeId") or constraint.get("themeId")
        ),
        "campaign_id": _text(
            snapshot.get("campaignId")
            or frozen.get("campaignId")
            or constraint.get("campaignId")
        ),
        "research_project_id": _text(
            snapshot.get("researchProjectId")
            or snapshot.get("projectId")
            or frozen.get("researchProjectId")
        ),
        "memory_scope": _text(
            snapshot.get("memoryScope") or frozen.get("memoryScope")
        ),
    }
    missing = [key for key, value in scope.items() if not value]
    if missing:
        raise ResultPackageV2Error(
            "frozen run scope is missing: " + ", ".join(missing)
        )
    branch = _text(snapshot.get("hypothesisBranchId") or frozen.get("hypothesisBranchId"))
    if branch:
        scope["hypothesis_branch_id"] = branch
    return scope


def _model_run(
    record: Mapping[str, Any],
    *,
    team_id: str,
    question_id: str,
    workflow_run_id: str,
) -> dict[str, Any]:
    refs = question_model_invocation_receipt_refs(
        team_id,
        question_id=question_id,
        workflow_run_id=workflow_run_id,
    )
    coverage = model_invocation_receipt_coverage(refs)
    if coverage.get("status") != "passed":
        raise ResultPackageV2Error(
            "official model invocation receipts do not cover the complete research loop",
            code="challenge_v2_receipts_incomplete",
        )
    final_node_ids = {
        _text(ref.get("nodeRunId"))
        for ref in refs
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
    normalized_provider = provider.lower()
    if "dashscope" not in normalized_provider and "aliyun" not in normalized_provider:
        raise ResultPackageV2Error(
            "final_output receipt is not bound to an Alibaba Cloud Qwen provider",
            code="challenge_v2_provider_not_official",
        )
    started_at = _require_text(
        record.get("createdAt") or record.get("startedAt"), "run.started_at"
    )
    result = {
        "run_id": workflow_run_id,
        "started_at": started_at,
        "model_provider": provider,
        "model_id": model_id,
        "platform": "aliyun_bailian",
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


def _evidence_item(card: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    locator = _mapping(card.get("citationLocator"))
    source_type = _text(
        _pick(card, "source_type", "sourceType")
        or _pick(candidate, "source_type", "sourceType")
    )
    if not source_type:
        source_type = {
            "paper": "peer_reviewed_paper",
            "preprint": "preprint",
            "dataset": "dataset",
            "standard": "standard",
            "official": "official_document",
            "book": "book",
        }.get(_text(candidate.get("sourceKind")).lower(), "")
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
        "fact": _require_text(card.get("fact") or card.get("claim"), "evidence.fact"),
        "relation": _require_text(card.get("relation"), "evidence.relation"),
        "verification_status": _require_text(
            _pick(card, "verification_status", "verificationStatus"),
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
    evidence_payload: Mapping[str, Any], candidate_payload: Mapping[str, Any]
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
    if not cards:
        raise ResultPackageV2Error("canonical evidence_card_batch contains no evidence")
    return [
        _evidence_item(
            card,
            by_id.get(_text(card.get("candidateId") or card.get("sourceId")), {}),
        )
        for card in cards
    ]


def _hypotheses(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    direct = _list_of_mappings(payload.get("hypotheses"))
    if direct:
        return direct
    candidates = _list_of_mappings(payload.get("candidates"))
    details = _mapping(payload.get("candidateDetails"))
    result: list[dict[str, Any]] = []
    for candidate in candidates:
        hypothesis_id = _require_text(candidate.get("candidateId"), "hypothesis_id")
        detail = _mapping(details.get(hypothesis_id))
        criteria = detail.get("falsificationCriteria")
        if not isinstance(criteria, list) or not criteria:
            raise ResultPackageV2Error(
                f"canonical hypothesis {hypothesis_id} is missing falsification criteria"
            )
        result.append(
            {
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
        )
    if len(result) < 2:
        raise ResultPackageV2Error("canonical hypothesis_set contains fewer than two hypotheses")
    return result


def _feedback_iterations(
    *, team_id: str, workflow_run_id: str, authority_run_id: str
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for artifact in list_workflow_artifacts(
        team_id, kind="feedback_iterations", workflow_run_id=workflow_run_id
    ):
        if _text(artifact.get("sourceCollectionRunId")) != authority_run_id:
            continue
        payload = _mapping(artifact.get("payload"))
        item = payload.get("feedbackIteration")
        if isinstance(item, Mapping):
            rows.append(deepcopy(dict(item)))
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
    authority = _text(source_collection_run_id) or workflow_run_id
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
    evidence_cards = _artifact_payload(
        "evidence_card_batch",
        team_id=team_id,
        workflow_run_id=workflow_run_id,
        authority_run_id=authority,
    )
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
    research_payload = _artifact_payload(
        "research_plan",
        team_id=team_id,
        workflow_run_id=workflow_run_id,
        authority_run_id=authority,
    )
    authority_sections = [dimension_payload, hypothesis_set, research_payload]
    evidence = _evidence(evidence_cards, candidates)
    hypotheses = _hypotheses(hypothesis_set)
    reviews = _list_of_mappings(
        dimension_payload.get("dimensionReviews")
        or dimension_payload.get("dimension_reviews")
    )
    if not reviews:
        raise ResultPackageV2Error("canonical dimension_reviews contains no review rows")
    selection = _require_section(authority_sections, "selection")
    research_plan = _mapping(
        research_payload.get("researchPlan") or research_payload.get("research_plan")
    )
    if not research_plan:
        raise ResultPackageV2Error("canonical research_plan contains no v2 research plan")
    final_summary = _require_section(authority_sections, "final_summary")
    competition_view = _require_section(authority_sections, "competition_result_view")
    result_classification = {
        "status": "review_required",
        "actual_execution": False,
        "classification": "proposal_only",
        "claim_boundary": _require_text(
            _pick(final_summary, "answer_boundary", "answerBoundary"),
            "result_classification.claim_boundary",
        ),
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
        "scope": _scope(snapshot),
        "run": _model_run(
            record,
            team_id=team_id,
            question_id=question_id,
            workflow_run_id=workflow_run_id,
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
            "citationChecks": [],
        }
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


__all__ = [
    "ResultPackageV2Error",
    "build_challenge_result_package_v2",
    "is_official_challenge_run",
]
