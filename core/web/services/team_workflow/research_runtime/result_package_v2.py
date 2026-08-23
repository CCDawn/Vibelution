"""Readiness probe for the future Challenge Question output v2 producer.

This module intentionally does *not* produce ``challenge_question_output.v2``.
The current workflow has canonical artifacts for sources, hypotheses and
execution, but it does not yet have independent authorities for every v2
business group (notably problem understanding, question review,
feedback/revision and the research plan).  Accepting a complete v2 blob from
``run_artifacts`` would make that blob its own authority and create a circular
fact chain.

The probe therefore fails closed with ``NEEDS_CONTEXT`` until the independent
artifact contract is materialized.  Once those artifacts exist, the caller
must use the existing ``adapt_question_result_package`` and
``QuestionResultPackage`` validation path; receipt binding is deliberately not
reimplemented here.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .human_gate_artifacts import canonical_sha256

_SCHEMA_VERSION = 2
_MISSING = object()

# These are contract-level authorities, not suggestions for fields to copy
# from an arbitrary execution payload.  In particular, ``run_artifacts`` is
# never accepted as the authority for question-level business groups.
_BUSINESS_AUTHORITY_GROUPS: dict[str, tuple[str, ...]] = {
    "problem_understanding": ("problem_understanding",),
    "evidence": ("evidence_card_batch",),
    "hypotheses": ("hypothesis_set",),
    "dimension_reviews": ("dimension_reviews",),
    "selection": ("selection",),
    "research_plan": ("research_plan",),
    "feedback_iterations": ("feedback_iterations",),
    "result_classification": ("evaluation_report", "result_classification"),
    "competition_result_view": ("competition_result_view",),
    "collaboration_refs": ("collaboration_refs",),
    "review": ("question_review",),
    "submission": ("submission_gate",),
}

# A group is not authoritative merely because an artifact of the right kind
# exists.  Its payload must expose the named canonical value.  Aliases here
# are transport spellings only; no value is normalized or inferred.
_GROUP_PAYLOAD_KEYS: dict[str, tuple[str, ...]] = {
    "problem_understanding": ("problem_understanding", "problemUnderstanding"),
    "evidence": ("evidenceCards", "evidence", "evidence_cards"),
    "hypotheses": ("hypotheses", "candidates", "hypothesisPortfolio"),
    "dimension_reviews": ("dimension_reviews", "dimensionReviews"),
    "selection": ("selection", "selectionDecision", "selection_decision"),
    "research_plan": ("research_plan", "researchPlan"),
    "feedback_iterations": ("feedback_iterations", "feedbackIterations"),
    "result_classification": (
        "result_classification",
        "resultClassification",
        "evaluation",
        "evaluationReport",
    ),
    "competition_result_view": (
        "competition_result_view",
        "competitionResultView",
    ),
    "collaboration_refs": ("collaboration_refs", "collaborationRefs"),
    "review": ("review", "questionReview", "question_review"),
    "submission": ("submission", "submissionGate", "submission_gate"),
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _blocker(
    code: str,
    field: str,
    message: str,
    *,
    authority: str = "",
    missing_inputs: tuple[str, ...] = (),
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "code": code,
        "field": field,
        "message": message,
    }
    if authority:
        result["authority"] = authority
    if missing_inputs:
        result["missing_inputs"] = list(missing_inputs)
    return result


def _artifact_kind(artifact_id: Any) -> str:
    value = _text(artifact_id)
    return value.split(":", 1)[0] if ":" in value else ""


def _canonical_refs(ledger: Mapping[str, Any]) -> set[str]:
    raw = ledger.get("canonicalArtifactRefs")
    if not isinstance(raw, list):
        return set()
    refs: set[str] = set()
    for item in raw:
        value = item
        if isinstance(item, Mapping):
            value = _first(item, "artifactId", "artifact_id", "canonicalRef", "canonical_ref")
        text = _text(value)
        if text:
            refs.add(text)
    return refs


def _artifact_rows(
    record: Mapping[str, Any],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    manifests = record.get("artifactManifests")
    payloads = record.get("artifactPayloads")
    if not isinstance(manifests, list) or not isinstance(payloads, Mapping):
        return {}, [
            _blocker(
                "canonical_artifacts_missing",
                "artifacts",
                "artifactManifests and artifactPayloads are required read-only inputs",
                authority="WorkflowRun.artifactManifests/artifactPayloads",
                missing_inputs=("artifactManifests", "artifactPayloads"),
            )
        ]

    by_kind: dict[str, list[dict[str, Any]]] = {}
    blockers: list[dict[str, Any]] = []
    for index, raw_manifest in enumerate(manifests):
        if not isinstance(raw_manifest, Mapping):
            blockers.append(
                _blocker(
                    "artifact_manifest_invalid",
                    f"artifactManifests[{index}]",
                    "artifact manifest must be an object",
                )
            )
            continue

        manifest = dict(raw_manifest)
        artifact_id = _text(manifest.get("artifactId"))
        kind = _artifact_kind(artifact_id)
        content_hash = _text(manifest.get("contentHash")).lower()
        payload = payloads.get(artifact_id)
        if not artifact_id or not kind or len(content_hash) != 64:
            blockers.append(
                _blocker(
                    "artifact_manifest_invalid",
                    f"artifactManifests[{index}]",
                    "artifactId and a sha256 contentHash are required",
                    authority="ArtifactManifest",
                )
            )
            continue
        if not isinstance(payload, Mapping):
            blockers.append(
                _blocker(
                    "artifact_payload_missing",
                    artifact_id,
                    "canonical artifact payload is missing",
                    authority="WorkflowRun.artifactPayloads",
                    missing_inputs=(artifact_id,),
                )
            )
            continue
        payload_copy = deepcopy(dict(payload))
        if canonical_sha256(payload_copy).lower() != content_hash:
            blockers.append(
                _blocker(
                    "artifact_hash_mismatch",
                    artifact_id,
                    "canonical artifact payload does not match ArtifactManifest.contentHash",
                    authority="ArtifactManifest.contentHash",
                )
            )
            continue
        by_kind.setdefault(kind, []).append(
            {
                "artifactId": artifact_id,
                "manifest": manifest,
                "payload": payload_copy,
            }
        )
    return by_kind, blockers


def _has_complete_v2_blob(value: Any) -> bool:
    """Return whether a payload embeds the projection it is supposed to feed."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = _text(key).replace("-", "_").lower()
            if normalized in {
                "challengequestionoutputv2",
                "challenge_question_output_v2",
            } and isinstance(item, Mapping):
                return True
            if _has_complete_v2_blob(item):
                return True
        return False
    if isinstance(value, list):
        return any(_has_complete_v2_blob(item) for item in value)
    return False


def _has_payload_value(payload: Mapping[str, Any], group: str) -> bool:
    return any(
        key in payload and payload[key] not in (None, "", [], {})
        for key in _GROUP_PAYLOAD_KEYS[group]
    )


def _missing_authorities(
    by_kind: Mapping[str, list[dict[str, Any]]],
    refs: set[str],
) -> tuple[list[str], list[str]]:
    missing_groups: list[str] = []
    present_groups: list[str] = []
    for group, kinds in _BUSINESS_AUTHORITY_GROUPS.items():
        present = any(
            row["artifactId"] in refs
            and _has_payload_value(row["payload"], group)
            for kind in kinds
            for row in by_kind.get(kind, [])
        )
        (present_groups if present else missing_groups).append(group)
    return missing_groups, present_groups


def _blocked(
    record: Mapping[str, Any],
    blockers: list[dict[str, Any]],
    *,
    missing_groups: list[str],
    present_groups: list[str],
) -> dict[str, Any]:
    snapshot = record.get("inputSnapshot")
    snapshot = snapshot if isinstance(snapshot, Mapping) else {}
    run_id = _text(record.get("runId"))
    question_id = _text(_first(snapshot, "questionId", "question_id"))
    ordered = sorted(
        (deepcopy(item) for item in blockers),
        key=lambda item: (
            _text(item.get("field")),
            _text(item.get("code")),
            _text(item.get("message")),
        ),
    )
    probe_hash = canonical_sha256(
        {
            "schema_version": _SCHEMA_VERSION,
            "run_id": run_id,
            "question_id": question_id,
            "missing_groups": sorted(missing_groups),
            "present_groups": sorted(present_groups),
            "blockers": ordered,
        }
    )
    return {
        "status": "blocked",
        "reason": "NEEDS_CONTEXT",
        "schema_version": _SCHEMA_VERSION,
        "output": None,
        "blockers": ordered,
        "missing_inputs": sorted(
            {
                _text(value)
                for item in ordered
                for value in item.get("missing_inputs") or []
                if _text(value)
            }
        ),
        "readiness": {
            "status": "blocked",
            "required_business_groups": sorted(_BUSINESS_AUTHORITY_GROUPS),
            "present_business_groups": sorted(present_groups),
            "missing_business_groups": sorted(missing_groups),
            "producer_available": False,
            "next_step": (
                "materialize independent canonical artifacts, then call "
                "adapt_question_result_package"
            ),
        },
        "result_classification": {
            "status": "blocked",
            "actual_execution": False,
            "classification": "proposal_only",
        },
        "review": {
            "human_review_status": "pending",
            "question_review_digest_ids": [],
        },
        "submission": {
            "eligible": False,
            "projection_version": "1.0-review.1",
            "blockers": [
                _text(item.get("code")) or "v2_readiness_blocked"
                for item in ordered
            ],
        },
        "probe_hash": probe_hash,
        "idempotency_key": f"{run_id}:{question_id}:v2-readiness:{probe_hash}",
    }


def assess_challenge_question_output_v2_readiness(
    record: Mapping[str, Any],
    *,
    research_ledger: Mapping[str, Any],
) -> dict[str, Any]:
    """Assess independent authorities for a future v2 producer.

    The function never returns a v2 output and never calls a model or writes an
    artifact.  ``NEEDS_CONTEXT`` is the expected result until every required
    business group is independently materialized and can be passed through
    the existing question-result adapter.
    """

    safe_record = record if isinstance(record, Mapping) else {}
    safe_ledger = research_ledger if isinstance(research_ledger, Mapping) else {}
    blockers: list[dict[str, Any]] = []
    if not isinstance(record, Mapping) or not isinstance(research_ledger, Mapping):
        blockers.append(
            _blocker(
                "canonical_input_invalid",
                "record",
                "WorkflowRun record and read-only ResearchLedger are required",
                authority="WorkflowRun + ResearchLedger",
            )
        )

    run_id = _text(safe_record.get("runId"))
    if _text(safe_ledger.get("runId")) != run_id:
        blockers.append(
            _blocker(
                "ledger_run_mismatch",
                "research_ledger.runId",
                "ResearchLedger must be bound to the same WorkflowRun",
                authority="ResearchLedger.runId",
            )
        )
    boundaries = safe_ledger.get("boundaries")
    if not isinstance(boundaries, Mapping) or boundaries.get("readOnly") is not True:
        blockers.append(
            _blocker(
                "ledger_not_read_only",
                "research_ledger.boundaries.readOnly",
                "readiness accepts only a read-only ResearchLedger",
                authority="ResearchLedger.boundaries",
            )
        )

    snapshot = safe_record.get("inputSnapshot")
    if not isinstance(snapshot, Mapping):
        blockers.append(
            _blocker(
                "scope_authority_missing",
                "inputSnapshot",
                "frozen WorkflowRun input snapshot is required",
                authority="WorkflowRun.inputSnapshot",
                missing_inputs=("inputSnapshot",),
            )
        )
    else:
        for field in ("questionId", "themeId", "campaignId", "researchProjectId", "memoryScope"):
            if not _text(snapshot.get(field) or snapshot.get(_camel_to_snake(field))):
                blockers.append(
                    _blocker(
                        "scope_authority_missing",
                        f"inputSnapshot.{field}",
                        "frozen WorkflowRun scope authority is missing",
                        authority="WorkflowRun.inputSnapshot",
                        missing_inputs=(f"inputSnapshot.{field}",),
                    )
                )

    by_kind, artifact_blockers = _artifact_rows(safe_record)
    blockers.extend(artifact_blockers)
    refs = _canonical_refs(safe_ledger)
    if not refs:
        blockers.append(
            _blocker(
                "canonical_refs_missing",
                "research_ledger.canonicalArtifactRefs",
                "canonical artifact references are required; summaries are not sufficient",
                authority="ResearchLedger.canonicalArtifactRefs",
                missing_inputs=("canonicalArtifactRefs",),
            )
        )

    manifest_ids = {
        row["artifactId"] for rows in by_kind.values() for row in rows
    }
    unbound_refs = sorted(ref for ref in refs if ref not in manifest_ids)
    if unbound_refs:
        blockers.append(
            _blocker(
                "canonical_ref_unbound",
                "research_ledger.canonicalArtifactRefs",
                "every canonical reference must bind to a verified ArtifactManifest",
                authority="ArtifactManifest + ResearchLedger.canonicalArtifactRefs",
                missing_inputs=tuple(unbound_refs),
            )
        )

    # A complete v2 blob is never accepted as an authority, even when its
    # enclosing manifest hash is correct.  It must be rebuilt from independent
    # artifacts and validated by the existing adapter instead.
    for kind, rows in by_kind.items():
        for row in rows:
            if row["artifactId"] not in refs:
                continue
            if _has_complete_v2_blob(row["payload"]):
                blockers.append(
                    _blocker(
                        "self_referential_projection",
                        f"artifacts.{kind}",
                        "a complete challengeQuestionOutputV2 blob cannot be its own canonical authority",
                        authority="independent canonical artifacts",
                        missing_inputs=(
                            "problem_understanding",
                            "dimension_reviews",
                            "feedback_iterations",
                            "research_plan",
                        ),
                    )
                )

    missing_groups, present_groups = _missing_authorities(by_kind, refs)
    for group in missing_groups:
        kinds = ", ".join(_BUSINESS_AUTHORITY_GROUPS[group])
        blockers.append(
            _blocker(
                "independent_authority_missing",
                f"business_groups.{group}",
                f"independent canonical authority is missing for {group}",
                authority=f"ArtifactManifest kind in {{{kinds}}}",
                missing_inputs=(f"canonical artifact for {group}",),
            )
        )

    # This is deliberately a readiness result, not a producer result.  Even
    # when the probe eventually sees every group, output assembly remains the
    # existing QuestionResultPackage adapter's responsibility.
    if not blockers:
        blockers.append(
            _blocker(
                "producer_not_implemented",
                "output",
                "v2 producer assembly is intentionally not available in this probe",
                authority="adapt_question_result_package",
            )
        )
    return _blocked(
        safe_record,
        blockers,
        missing_groups=missing_groups,
        present_groups=present_groups,
    )


def _camel_to_snake(value: str) -> str:
    chars: list[str] = []
    for char in value:
        if char.isupper():
            chars.extend(("_", char.lower()))
        else:
            chars.append(char)
    return "".join(chars).lstrip("_")


__all__ = ["assess_challenge_question_output_v2_readiness"]
