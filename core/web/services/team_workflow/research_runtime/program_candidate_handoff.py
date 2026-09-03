"""Bridge a canonical workflow result package into the Challenge Program.

The research workflow and the Challenge Program have different contracts.  A
generic ``research_result_package`` contains a fact chain and deliverables; it
is not, by itself, a ``challenge_question_output.v2``.  This module is the
small boundary between them:

* read only the scoped workflow-artifact authority;
* require an explicitly embedded canonical v2 output and citation checks;
* bind registration to the immutable result-package content hash; and
* leave the existing Challenge Program registration/review gate authoritative.

If the upstream package does not carry that authority, the bridge returns
``NEEDS_CONTEXT`` and lists the smallest missing contract.  It never derives
question text, hypotheses, citations, or a research plan from generic result
package fields.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any

from core.web.services.team_workflow import challenge_question_runs

from .artifact_readback_registry import load_scoped_artifact_payload

HANDOFF_STATUS_REGISTERED = "registered"
HANDOFF_STATUS_IDEMPOTENT = "idempotent"
HANDOFF_STATUS_NEEDS_CONTEXT = "NEEDS_CONTEXT"
NEEDS_CONTEXT = HANDOFF_STATUS_NEEDS_CONTEXT


class ProgramCandidateHandoffContractError(ValueError):
    """A permanent handoff contract or immutable-binding violation.

    Missing upstream context is represented by the normal ``NEEDS_CONTEXT``
    response.  This exception is reserved for a source that claimed to be
    complete but failed the Challenge Program registration contract, such as a
    changed package binding on an existing immutable record.  Delivery maps it
    to a permanent orchestration error instead of retrying it as I/O.
    """

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_OUTPUT_KEYS = (
    "challengeQuestionOutput",
    "challenge_question_output",
    "challengeQuestionOutputV2",
    "challenge_question_output_v2",
)
_CITATION_CHECK_KEYS = (
    "citationChecks",
    "citation_checks",
    "challengeQuestionCitationChecks",
    "challenge_question_citation_checks",
)
_REQUIRED_OUTPUT_FIELDS = (
    "identity",
    "classification",
    "scope",
    "run",
    "problem_understanding",
    "evidence",
    "hypotheses",
    "dimension_reviews",
    "selection",
    "research_plan",
    "feedback_iterations",
    "result_classification",
    "competition_result_view",
    "collaboration_refs",
    "review",
    "submission",
    "audit",
)


def _first_object(container: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any] | None:
    for key in keys:
        value = container.get(key)
        if isinstance(value, dict):
            return deepcopy(value)
    return None


def _first_present(container: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in container:
            return container.get(key)
    return None


def _first_mapping_from_layers(
    layers: tuple[dict[str, Any], ...], keys: tuple[str, ...]
) -> dict[str, Any] | None:
    for layer in layers:
        value = _first_object(layer, keys)
        if value is not None:
            return value
    return None


def _first_value_from_layers(
    layers: tuple[dict[str, Any], ...], keys: tuple[str, ...]
) -> Any:
    for layer in layers:
        value = _first_present(layer, keys)
        if value is not None and value != "":
            return deepcopy(value)
    return None


def _missing_context(
    *,
    team_id: str,
    workflow_run_id: str,
    source_collection_run_id: str,
    reason: str,
    missing_authorities: list[str] | tuple[str, ...] = (),
    missing_fields: list[str] | tuple[str, ...] = (),
    source_result_package_hash: str = "",
    diagnostics: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    fields = list(dict.fromkeys(str(item) for item in missing_fields if str(item)))
    authorities = list(
        dict.fromkeys(str(item) for item in missing_authorities if str(item))
    )
    return {
        "status": HANDOFF_STATUS_NEEDS_CONTEXT,
        "teamId": team_id,
        "workflowRunId": workflow_run_id,
        "sourceCollectionRunId": source_collection_run_id,
        "sourceResultPackageHash": source_result_package_hash,
        "reason": reason,
        "missingAuthorities": authorities,
        "missingFields": fields,
        "requiredUpstreamContract": {
            "artifactKind": "research_result_package",
            "field": "package.challengeQuestionOutput",
            "schema": "challenge_question_output.v2",
            "citationField": "package.citationChecks",
            "binding": "teamId + questionId + workflowRunId + package.contentHash",
        },
        "diagnostics": list(dict.fromkeys(str(item) for item in diagnostics if str(item))),
    }


def _package_hash(package: dict[str, Any], artifact_payload: dict[str, Any]) -> str:
    value = str(
        package.get("contentHash")
        or package.get("canonicalHash")
        or package.get("canonical_sha256")
        or artifact_payload.get("contentHash")
        or ""
    ).strip().lower()
    return value if _SHA256_RE.fullmatch(value) else ""


def _extract_required_error_fields(issues: list[dict[str, str]]) -> list[str]:
    missing: list[str] = []
    for issue in issues:
        message = str(issue.get("message") or "")
        path = str(issue.get("path") or "$")
        match = re.match(r"^'([^']+)' is a required property$", message)
        missing.append(f"{path}.{match.group(1)}" if match else path)
    return list(dict.fromkeys(missing))


def _read_canonical_package(
    *,
    team_id: str,
    workflow_run_id: str,
    source_collection_run_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    authority_run_id = source_collection_run_id or workflow_run_id
    envelope = load_scoped_artifact_payload(
        "research_result_package",
        team_id=team_id,
        authority_run_id=authority_run_id,
        workflow_run_id=workflow_run_id,
    )
    if not isinstance(envelope, dict):
        return None, _missing_context(
            team_id=team_id,
            workflow_run_id=workflow_run_id,
            source_collection_run_id=authority_run_id,
            reason="canonical research_result_package is unavailable",
            missing_authorities=["research_result_package"],
            missing_fields=["package", "package.contentHash"],
        )

    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        return None, _missing_context(
            team_id=team_id,
            workflow_run_id=workflow_run_id,
            source_collection_run_id=authority_run_id,
            reason="research_result_package payload is not an object",
            missing_authorities=["research_result_package"],
            missing_fields=["payload"],
        )

    package = payload.get("package")
    if not isinstance(package, dict):
        return None, _missing_context(
            team_id=team_id,
            workflow_run_id=workflow_run_id,
            source_collection_run_id=authority_run_id,
            reason="research_result_package does not contain its canonical package",
            missing_authorities=["research_result_package"],
            missing_fields=["package", "package.contentHash"],
        )

    package_hash = _package_hash(package, payload)
    if not package_hash:
        return None, _missing_context(
            team_id=team_id,
            workflow_run_id=workflow_run_id,
            source_collection_run_id=authority_run_id,
            reason="canonical result package contentHash is missing or invalid",
            missing_authorities=["research_result_package"],
            missing_fields=["package.contentHash"],
        )

    envelope_team = str(envelope.get("teamId") or payload.get("teamId") or "").strip()
    envelope_workflow = str(
        envelope.get("workflowRunId") or payload.get("workflowRunId") or ""
    ).strip()
    if envelope_team and envelope_team != team_id:
        return None, _missing_context(
            team_id=team_id,
            workflow_run_id=workflow_run_id,
            source_collection_run_id=authority_run_id,
            reason="result package team scope does not match the delivery run",
            source_result_package_hash=package_hash,
            diagnostics=[f"packageTeamId={envelope_team}"],
        )
    if envelope_workflow and envelope_workflow != workflow_run_id:
        return None, _missing_context(
            team_id=team_id,
            workflow_run_id=workflow_run_id,
            source_collection_run_id=authority_run_id,
            reason="result package workflow scope does not match the delivery run",
            source_result_package_hash=package_hash,
            diagnostics=[f"packageWorkflowRunId={envelope_workflow}"],
        )
    return {
        "envelope": envelope,
        "payload": payload,
        "package": package,
        "packageHash": package_hash,
        "authorityRunId": authority_run_id,
    }, None


def _receipt_trace_digest(refs: list[dict[str, Any]]) -> str:
    """Seal the fresh trace refs into one lowercase 64-hex digest."""

    if not refs:
        return ""
    encoded = json.dumps(
        sorted(str(item.get("receiptSha256") or "") for item in refs),
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fresh_receipt_trace_facts(
    team: str, record: dict[str, Any]
) -> tuple[bool, int, str]:
    """Re-verify the stored trace projection against the live receipt registry.

    The stage-one v2 flow structurally cannot produce the legacy three-stage
    canonical package receipts, so the only honest receipt authority is the
    registry-backed per-invocation trace.  It is re-verified fresh here (never
    trusted from the stored record): any registry/stored mismatch is reported
    by the projection as ``integrityIssue`` and fails closed without raising.
    """

    refs, coverage = challenge_question_runs._question_model_invocation_trace_projection(
        team, record
    )
    stored_refs = record.get("modelInvocationReceiptTraceRefs")
    verified = (
        bool(refs)
        and "integrityIssue" not in coverage
        and (
            "modelInvocationReceiptTraceRefs" not in record
            or stored_refs == refs
        )
    )
    return verified, len(refs), _receipt_trace_digest(refs)


def handoff_result_package_to_challenge_program(
    store: Any = None,
    *,
    team_id: str,
    workflow_run_id: str,
    source_collection_run_id: str = "",
    registered_by: str = "research_result_package_bridge",
) -> dict[str, Any]:
    """Register an explicitly complete v2 output, or return ``NEEDS_CONTEXT``.

    ``store`` is accepted so the bridge can be called from the delivery worker
    without changing its orchestration contract.  Artifact read-back remains
    owned by ``load_scoped_artifact_payload``; the store argument is not used as
    a second source of truth.
    """

    _ = store
    team = str(team_id or "").strip()
    workflow = str(workflow_run_id or "").strip()
    authority = str(source_collection_run_id or "").strip() or workflow
    if not team or not workflow:
        return _missing_context(
            team_id=team,
            workflow_run_id=workflow,
            source_collection_run_id=authority,
            reason="teamId and workflowRunId are required for a scoped handoff",
            missing_fields=["teamId", "workflowRunId"],
        )

    package_context, missing = _read_canonical_package(
        team_id=team,
        workflow_run_id=workflow,
        source_collection_run_id=authority,
    )
    if missing is not None:
        return missing
    assert package_context is not None
    payload = package_context["payload"]
    package = package_context["package"]
    package_hash = str(package_context["packageHash"])

    output = _first_object(payload, _OUTPUT_KEYS) or _first_object(package, _OUTPUT_KEYS)
    if output is None:
        return _missing_context(
            team_id=team,
            workflow_run_id=workflow,
            source_collection_run_id=authority,
            reason="canonical result package has no complete Challenge Question v2 authority",
            missing_authorities=["canonical_challenge_question_output.v2"],
            missing_fields=list(_REQUIRED_OUTPUT_FIELDS) + ["package.challengeQuestionOutput"],
            source_result_package_hash=package_hash,
        )

    issues = challenge_question_runs._schema_issues(output)
    if issues:
        return _missing_context(
            team_id=team,
            workflow_run_id=workflow,
            source_collection_run_id=authority,
            reason="canonical Challenge Question output is not a complete schema v2 artifact",
            missing_authorities=["canonical_challenge_question_output.v2"],
            missing_fields=_extract_required_error_fields(issues),
            source_result_package_hash=package_hash,
            diagnostics=[
                f"{item.get('path')}: {item.get('message')}"
                for item in issues[:12]
            ],
        )

    identity = output.get("identity") if isinstance(output.get("identity"), dict) else {}
    run = output.get("run") if isinstance(output.get("run"), dict) else {}
    question_id = str(identity.get("question_id") or "").strip().upper()
    output_run_id = str(run.get("run_id") or "").strip()
    package_question_id = str(
        package.get("questionId") or package.get("question_id") or ""
    ).strip().upper()
    package_run_id = str(package.get("runId") or package.get("run_id") or "").strip()
    binding_diagnostics: list[str] = []
    if package_question_id and package_question_id != question_id:
        binding_diagnostics.append(
            f"packageQuestionId={package_question_id}; outputQuestionId={question_id}"
        )
    if package_run_id and package_run_id != workflow:
        binding_diagnostics.append(f"packageRunId={package_run_id}; workflowRunId={workflow}")
    if output_run_id != workflow:
        binding_diagnostics.append(f"outputRunId={output_run_id}; workflowRunId={workflow}")
    if binding_diagnostics:
        return _missing_context(
            team_id=team,
            workflow_run_id=workflow,
            source_collection_run_id=authority,
            reason="canonical v2 output and result package identity do not match",
            missing_authorities=["canonical_challenge_question_output.v2"],
            missing_fields=["identity.question_id", "run.run_id"],
            source_result_package_hash=package_hash,
            diagnostics=binding_diagnostics,
        )

    source_status = str(
        (
            output.get("result_classification")
            if isinstance(output.get("result_classification"), dict)
            else {}
        ).get("status")
        or ""
    ).strip()
    if source_status in {"blocked", "failed"}:
        return _missing_context(
            team_id=team,
            workflow_run_id=workflow,
            source_collection_run_id=authority,
            reason="blocked or failed workflow output is not a Challenge Program candidate",
            missing_authorities=["canonical_challenge_question_output.v2"],
            missing_fields=["result_classification.status=review_required"],
            source_result_package_hash=package_hash,
            diagnostics=[f"sourceStatus={source_status}"],
        )

    citation_checks = _first_present(payload, _CITATION_CHECK_KEYS)
    if citation_checks is None:
        citation_checks = _first_present(package, _CITATION_CHECK_KEYS)
    if (
        not isinstance(citation_checks, list)
        or not citation_checks
        or any(not isinstance(item, dict) for item in citation_checks)
    ):
        return _missing_context(
            team_id=team,
            workflow_run_id=workflow,
            source_collection_run_id=authority,
            reason="canonical v2 output has no canonical citation-check authority",
            missing_authorities=["canonical_citation_check_receipt"],
            missing_fields=["package.citationChecks"],
            source_result_package_hash=package_hash,
        )

    try:
        authority_layers = (payload, package)
        canonical_result_package = _first_mapping_from_layers(
            authority_layers,
            ("resultPackage", "result_package", "canonicalResultPackage"),
        )
        registration_payload: dict[str, Any] = {
            "output": output,
            "citationChecks": deepcopy(citation_checks),
            "registeredBy": str(registered_by or "").strip()
            or "research_result_package_bridge",
            "sourceResultPackageHash": package_hash,
        }
        if canonical_result_package is not None:
            registration_payload["resultPackage"] = canonical_result_package

        receipt_values = _first_value_from_layers(
            tuple(
                layer
                for layer in (
                    *authority_layers,
                    canonical_result_package or {},
                )
                if isinstance(layer, dict)
            ),
            (
                "packageReceipts",
                "modelInvocationReceipts",
                "model_invocation_receipts",
                "receipts",
            ),
        )
        if isinstance(receipt_values, (dict, list)) and receipt_values:
            registration_payload["modelInvocationReceipts"] = receipt_values

        model_policy = _first_mapping_from_layers(
            tuple(
                layer
                for layer in (
                    *authority_layers,
                    canonical_result_package or {},
                )
                if isinstance(layer, dict)
            ),
            ("modelPolicy", "model_policy"),
        )
        if model_policy is not None:
            registration_payload["modelPolicy"] = model_policy
        authorized_policy = _first_value_from_layers(
            tuple(
                layer
                for layer in (
                    *authority_layers,
                    canonical_result_package or {},
                )
                if isinstance(layer, dict)
            ),
            (
                "authorizedModelPolicySha256",
                "authorized_model_policy_sha256",
                "expectedModelPolicySha256",
                "expected_model_policy_sha256",
            ),
        )
        if authorized_policy is None and model_policy is not None:
            authorized_policy = model_policy.get("policySha256") or model_policy.get(
                "policy_sha256"
            )
        if authorized_policy:
            registration_payload["authorizedModelPolicySha256"] = str(authorized_policy)
        official_model_call = _first_value_from_layers(
            authority_layers,
            ("officialModelCall", "official_model_call"),
        )
        if official_model_call is not None:
            registration_payload["officialModelCall"] = bool(official_model_call)

        registered = challenge_question_runs.register_challenge_question_output(
            team,
            registration_payload,
        )
    except ValueError as exc:
        raise ProgramCandidateHandoffContractError(str(exc)) from exc
    record = registered.get("record") if isinstance(registered, dict) else {}
    validation = record.get("validation") if isinstance(record, dict) else {}
    validation = validation if isinstance(validation, dict) else {}
    receipt_refs = (
        deepcopy(record.get("modelInvocationReceiptRefs"))
        if isinstance(record, dict)
        and isinstance(record.get("modelInvocationReceiptRefs"), dict)
        else {}
    )
    receipt_status = str(validation.get("modelInvocationReceipts") or "")
    (
        receipt_trace_verified,
        receipt_trace_count,
        receipt_trace_digest,
    ) = _fresh_receipt_trace_facts(team, record)
    result_package = (
        deepcopy(record.get("resultPackage"))
        if isinstance(record, dict) and isinstance(record.get("resultPackage"), dict)
        else deepcopy(registration_payload.get("resultPackage"))
    )
    response = {
        "status": HANDOFF_STATUS_IDEMPOTENT
        if registered.get("idempotent")
        else HANDOFF_STATUS_REGISTERED,
        "teamId": team,
        "workflowRunId": workflow,
        "sourceCollectionRunId": authority,
        "questionId": question_id,
        "runId": output_run_id,
        "sourceResultPackageHash": package_hash,
        "outputSha256": str(record.get("outputSha256") or ""),
        "recordId": str(record.get("recordId") or ""),
        "reviewStatus": str(record.get("status") or ""),
        "humanGates": deepcopy(record.get("humanGates") or {}),
        "resultPackage": result_package,
        "officialModelCall": validation.get("officialModelCall") is True,
        "receipts": receipt_refs,
        "receiptStatus": receipt_status,
        "receiptTraceVerified": receipt_trace_verified,
        "receiptTraceCount": receipt_trace_count,
        "receiptTraceDigest": receipt_trace_digest,
    }
    return response


def stage_one_completion_manifest_from_handoff(
    handoff: dict[str, Any],
    *,
    policy_sha256: str,
) -> dict[str, Any]:
    """Create a terminal manifest only from a fresh approved Program readback."""

    human_gates = handoff.get("humanGates")
    human_gates = human_gates if isinstance(human_gates, dict) else {}
    result_package = handoff.get("resultPackage")
    result_package = result_package if isinstance(result_package, dict) else {}
    source_hash = str(handoff.get("sourceResultPackageHash") or "").lower()
    output_hash = str(handoff.get("outputSha256") or "").lower()
    canonical_hash = str(
        result_package.get("canonicalHash")
        or result_package.get("canonical_sha256")
        or ""
    ).lower()
    try:
        trace_count = int(handoff.get("receiptTraceCount") or 0)
    except (TypeError, ValueError):
        trace_count = 0
    trace_digest = str(handoff.get("receiptTraceDigest") or "").lower()
    # Dual receipt authority, both fail-closed:
    # * canonical — the legacy three-stage ``QuestionResultPackage`` receipts
    #   (generation/review/revision) reported as ``receiptStatus == "passed"``;
    # * trace — the stage-one v2 receipt-registry per-invocation refs, already
    #   hash-verified against the registry at registration and re-verified by
    #   the handoff; the manifest digest seals their integrity.
    if str(handoff.get("receiptStatus") or "") == "passed":
        manifest_receipt_status = "passed"
        receipt_authority = "canonical_result_package"
        trace_fields: dict[str, Any] = {}
        manifest_canonical_hash = canonical_hash
        receipt_gate_ok = _SHA256_RE.fullmatch(canonical_hash) is not None
    elif handoff.get("receiptTraceVerified") is True and trace_count >= 1:
        manifest_receipt_status = "trace_verified"
        receipt_authority = "model_invocation_trace"
        trace_fields = {
            "receiptTraceCount": trace_count,
            "receiptTraceDigest": trace_digest,
        }
        # In the stage-one v2 flow the rrp-v2 result-package content hash is
        # itself the canonical binding, so the manifest binds
        # ``canonicalPackageHash`` to the already hash-checked
        # ``sourceResultPackageHash``.
        manifest_canonical_hash = source_hash
        receipt_gate_ok = _SHA256_RE.fullmatch(trace_digest) is not None
    else:
        manifest_receipt_status = ""
        receipt_authority = ""
        trace_fields = {}
        manifest_canonical_hash = canonical_hash
        receipt_gate_ok = False
    if (
        str(handoff.get("reviewStatus") or "") != "approved"
        or handoff.get("officialModelCall") is not True
        or not receipt_gate_ok
        or human_gates.get("allApproved") is not True
        or int(human_gates.get("approvedCount") or 0) != 4
        or not _SHA256_RE.fullmatch(source_hash)
        or not _SHA256_RE.fullmatch(output_hash)
        or not _SHA256_RE.fullmatch(manifest_canonical_hash)
        or not _SHA256_RE.fullmatch(str(policy_sha256 or ""))
    ):
        raise ProgramCandidateHandoffContractError(
            "Challenge Program record is not approved for stage-one completion"
        )
    manifest = {
        "schemaVersion": 1,
        "manifestKind": "stage_one_completion",
        "workflowRunId": str(handoff.get("workflowRunId") or ""),
        "questionId": str(handoff.get("questionId") or "").upper(),
        "policySha256": str(policy_sha256).lower(),
        "programRecordId": str(handoff.get("recordId") or ""),
        "programOutputSha256": output_hash,
        "programReviewStatus": "approved",
        "sourceResultPackageHash": source_hash,
        "canonicalPackageHash": manifest_canonical_hash,
        "officialModelCall": True,
        "receiptStatus": manifest_receipt_status,
        "receiptAuthority": receipt_authority,
        **trace_fields,
        "humanGates": deepcopy(human_gates),
    }
    if not manifest["workflowRunId"] or not manifest["questionId"] or not manifest["programRecordId"]:
        raise ProgramCandidateHandoffContractError(
            "Challenge Program approval is missing immutable run identity"
        )
    from .stage_one_closeout import _completion_manifest_sha256

    manifest["manifestSha256"] = _completion_manifest_sha256(manifest)
    return manifest


# Short compatibility aliases for callers that use the bridge as a command.
bridge_result_package_to_challenge_question = handoff_result_package_to_challenge_program
register_result_package_candidate = handoff_result_package_to_challenge_program


__all__ = [
    "HANDOFF_STATUS_IDEMPOTENT",
    "HANDOFF_STATUS_NEEDS_CONTEXT",
    "HANDOFF_STATUS_REGISTERED",
    "NEEDS_CONTEXT",
    "ProgramCandidateHandoffContractError",
    "bridge_result_package_to_challenge_question",
    "handoff_result_package_to_challenge_program",
    "register_result_package_candidate",
    "stage_one_completion_manifest_from_handoff",
]
