"""Build the one canonical Challenge Question v2 result-package envelope.

This module is deliberately a strict producer, not a summarizer.  It reads
run-scoped canonical artifacts and only projects fields that those authorities
actually contain.  Missing selection, review, evidence, result-view, model
receipt, or scope facts stop packaging instead of being filled from scores or
free-form task summaries.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

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
        by_round[iteration_round] = (row, parent, child)
    if set(by_round) != set(expected_phases):
        raise ResultPackageV2Error(
            "canonical same-run hypothesis feedback lineage is incomplete",
            code="challenge_v2_feedback_conflict",
        )
    first_child = by_round[1][2]
    second_parent = by_round[2][1]
    if (
        first_child.get("refs") != second_parent.get("refs")
        or _text(first_child.get("sha256")).lower()
        != _text(second_parent.get("sha256")).lower()
    ):
        raise ResultPackageV2Error(
            "canonical same-run hypothesis feedback lineage is discontinuous",
            code="challenge_v2_feedback_conflict",
        )
    return [deepcopy(by_round[index][0]) for index in sorted(by_round)]


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
    "is_official_challenge_run",
    "is_proposal_only_challenge_run",
]
