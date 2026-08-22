"""Canonical adapter for Challenge Cup question-run output packages."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from core.research.competition.question_result_package import (
    REQUIRED_RECEIPT_STAGES,
    QuestionResultPackage,
    QuestionResultPackageError,
)
from core.research.competition.result_set import CatalogScope
from core.research.workflow.contracts.model_invocation_receipt import (
    ModelInvocationStatus,
)


class QuestionResultPackageAdapterError(QuestionResultPackageError):
    """A v2 output cannot be promoted to a trusted result package."""


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _pick(payload: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return default


def _mapping(value: Any, field: str, *, allow_empty: bool = False) -> dict[str, Any]:
    if not isinstance(value, Mapping) or (not allow_empty and not value):
        raise QuestionResultPackageAdapterError(f"{field} must be a non-empty mapping")
    return deepcopy(dict(value))


def _text(value: Any, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise QuestionResultPackageAdapterError(f"{field} is required")
    return result


def _sha256(value: Any, field: str) -> str:
    result = _text(value, field).removeprefix("sha256:").lower()
    if not _SHA256_RE.fullmatch(result):
        raise QuestionResultPackageAdapterError(
            f"{field} must be a lowercase sha256 hex digest"
        )
    return result


def _scope_value(payload: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


def _receipt_rows(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        receipts = value.get("receipts")
        if isinstance(receipts, (list, Mapping)):
            value = receipts
        else:
            return deepcopy(dict(value))
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise QuestionResultPackageAdapterError(
            "model_invocation_receipts are required and must be a mapping or list"
        )
    result: dict[str, Any] = {}
    for item in value:
        if not isinstance(item, Mapping):
            raise QuestionResultPackageAdapterError(
                "model_invocation_receipts contains a non-object receipt"
            )
        stage = _scope_value(item.get("scope") or {}, "stageId", "stage_id", "stage")
        if not stage:
            raise QuestionResultPackageAdapterError(
                "model_invocation_receipt is missing scope.stageId"
            )
        result[stage] = deepcopy(dict(item))
    return result


def _evidence_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        if isinstance(value.get("evidence"), list):
            value = value["evidence"]
        else:
            value = list(value.values())
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise QuestionResultPackageAdapterError(
            "official_model_evidence is required and must be a list of rows"
        )
    rows = [deepcopy(dict(item)) for item in value if isinstance(item, Mapping)]
    if len(rows) != len(value):
        raise QuestionResultPackageAdapterError(
            "official_model_evidence contains a non-object row"
        )
    return rows


def _row_value(row: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value:
            return value
    metadata = row.get("metadata")
    if isinstance(metadata, Mapping):
        for key in keys:
            value = str(metadata.get(key) or "").strip()
            if value:
                return value
    return ""


def _validate_receipt_evidence(
    package: QuestionResultPackage,
    official_model_evidence: Any,
) -> None:
    rows = _evidence_rows(official_model_evidence)
    for stage, receipt in package.model_invocation_receipts.items():
        receipt_dict = receipt.to_dict()
        receipt_id = receipt.receipt_id
        locator = dict(receipt.evidence_locator or {})
        locator_evidence_id = _scope_value(locator, "evidenceId", "evidence_id", "id")
        locator_output_ref = _scope_value(locator, "outputRef", "output_ref", "ref")
        matches = [
            row
            for row in rows
            if (
                _row_value(row, "receiptId", "receipt_id") == receipt_id
                or (
                    locator_evidence_id
                    and _row_value(row, "evidenceId", "evidence_id", "id")
                    == locator_evidence_id
                )
                or (
                    locator_output_ref
                    and _row_value(row, "outputRef", "output_ref", "ref", "logRef")
                    == locator_output_ref
                )
            )
        ]
        if not matches:
            raise QuestionResultPackageAdapterError(
                f"receipt.{stage} is not linked to registered official_model_evidence"
            )
        if len(matches) != 1:
            raise QuestionResultPackageAdapterError(
                f"receipt.{stage} has ambiguous official_model_evidence binding"
            )
        row = matches[0]
        required = {
            "questionId": _row_value(row, "questionId", "question_id", "question"),
            "runId": _row_value(row, "sourceRunId", "runId", "run_id"),
            "taskId": _row_value(row, "taskId", "task_id", "task"),
            "turnId": _row_value(row, "turnId", "turn_id", "turn"),
            "stageId": _row_value(row, "stageId", "stage_id", "stage", "workflowNode"),
            "modelPolicySha256": _row_value(
                row,
                "modelPolicySha256",
                "model_policy_sha256",
                "modelPolicyHash",
            ),
            "modelProvider": _row_value(row, "modelProvider", "provider"),
            "modelId": _row_value(row, "modelId", "model"),
            "status": _row_value(row, "status"),
            "outputSha256": _row_value(row, "outputSha256", "output_sha256", "outputHash"),
            "outputRef": _row_value(row, "outputRef", "output_ref", "ref", "logRef"),
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise QuestionResultPackageAdapterError(
                f"official_model_evidence for receipt.{stage} is incomplete; "
                "missing fields: "
                + ", ".join(missing)
            )
        if required["status"] not in {"canonical_success", "published_to_challenge_program"}:
            raise QuestionResultPackageAdapterError(
                f"official_model_evidence for receipt.{stage} status is not official"
            )
        if required["questionId"] != package.question_id:
            raise QuestionResultPackageAdapterError(
                f"official_model_evidence for receipt.{stage} question binding mismatch"
            )
        if required["runId"] != package.run_id:
            raise QuestionResultPackageAdapterError(
                f"official_model_evidence for receipt.{stage} run binding mismatch"
            )
        if required["stageId"] != stage:
            raise QuestionResultPackageAdapterError(
                f"official_model_evidence for receipt.{stage} stage binding mismatch"
            )
        if required["modelProvider"].lower() != receipt.provider.lower():
            raise QuestionResultPackageAdapterError(
                f"official_model_evidence for receipt.{stage} provider binding mismatch"
            )
        if required["modelId"].lower() != receipt.model.lower():
            raise QuestionResultPackageAdapterError(
                f"official_model_evidence for receipt.{stage} model binding mismatch"
            )
        if _sha256(required["modelPolicySha256"], f"evidence.{stage}.modelPolicySha256") != package.model_policy["policySha256"]:
            raise QuestionResultPackageAdapterError(
                f"official_model_evidence for receipt.{stage} model policy mismatch"
            )
        _sha256(required["outputSha256"], f"evidence.{stage}.outputSha256")
        if locator_output_ref and required["outputRef"] != locator_output_ref:
            raise QuestionResultPackageAdapterError(
                f"official_model_evidence for receipt.{stage} output ref mismatch"
            )
        locator_output_hash = _scope_value(
            locator,
            "outputSha256",
            "output_sha256",
            "outputHash",
        )
        if locator_output_hash and _sha256(
            locator_output_hash,
            f"receipt.{stage}.evidenceLocator.outputSha256",
        ) != _sha256(required["outputSha256"], f"evidence.{stage}.outputSha256"):
            raise QuestionResultPackageAdapterError(
                f"official_model_evidence for receipt.{stage} output hash mismatch"
            )
        if receipt.status not in {ModelInvocationStatus.SUCCEEDED, ModelInvocationStatus.RETRIED}:
            raise QuestionResultPackageAdapterError(
                f"receipt.{stage} must be a successful Qwen invocation"
            )
        if receipt_dict["receiptId"] != receipt_id:
            raise QuestionResultPackageAdapterError(
                f"receipt.{stage} receipt identity changed during validation"
            )


def adapt_question_result_package(
    output: Mapping[str, Any],
    *,
    catalog_scope: CatalogScope,
    run_binding: Mapping[str, Any],
    authorized_model_policy_sha256: str,
    result_package: Mapping[str, Any] | None = None,
    model_policy: Mapping[str, Any] | None = None,
    model_invocation_receipts: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    official_model_evidence: Any = None,
    input_snapshot_sha256: str = "",
    package_id: str = "",
) -> QuestionResultPackage:
    """Validate and restore one canonical package through ``from_dict``."""

    raw_output = _mapping(output, "output")
    source = _mapping(result_package, "resultPackage") if result_package is not None else raw_output
    nested = source.get("package")
    if isinstance(nested, Mapping):
        source = deepcopy(dict(nested))
    identity = raw_output.get("identity") if isinstance(raw_output.get("identity"), Mapping) else {}
    run = raw_output.get("run") if isinstance(raw_output.get("run"), Mapping) else {}
    question_id = _text(
        _pick(source, "question_id", "questionId", default=None)
        or _pick(identity, "question_id", "questionId", default=None),
        "question_id",
    )
    run_id = _text(
        _pick(source, "run_id", "runId", default=None)
        or _pick(run, "run_id", "runId", default=None),
        "run_id",
    )
    bound_question_id = _text(
        _pick(run_binding, "questionId", "question_id", "question", default=None),
        "run_binding.questionId",
    )
    bound_run_id = _text(
        _pick(run_binding, "runId", "run_id", default=None),
        "run_binding.runId",
    )
    if question_id != bound_question_id or run_id != bound_run_id:
        raise QuestionResultPackageAdapterError(
            "run binding does not match output question/run"
        )
    policy = model_policy
    if policy is None:
        policy = _pick(source, "model_policy", "modelPolicy", default=None)
    if not isinstance(policy, Mapping):
        raise QuestionResultPackageAdapterError(
            "model_policy is required; do not derive policy from model evidence"
        )
    receipts_value = model_invocation_receipts
    if receipts_value is None:
        receipts_value = _pick(
            source,
            "model_invocation_receipts",
            "modelInvocationReceipts",
            "receipts",
            default=None,
        )
    receipts = _receipt_rows(receipts_value)
    missing_stages = [stage for stage in REQUIRED_RECEIPT_STAGES if stage not in receipts]
    if missing_stages:
        raise QuestionResultPackageAdapterError(
            "missing receipt stages: " + ", ".join(missing_stages)
        )
    snapshot = _pick(
        source,
        "input_snapshot_sha256",
        "inputSnapshotSha256",
        "input_snapshot_hash",
        "inputSnapshotHash",
        default=input_snapshot_sha256,
    )
    snapshot = _sha256(snapshot, "input_snapshot_sha256")
    package_payload: dict[str, Any] = {
        "schema_version": 2,
        "package_id": str(
            package_id
            or _pick(source, "package_id", "packageId", default="")
            or f"qrp-{question_id.lower()}-{run_id}"
        ).strip(),
        "scope": catalog_scope.to_dict(),
        "model_policy": deepcopy(dict(policy)),
        "question_id": question_id,
        "run_id": run_id,
        "input_snapshot_sha256": snapshot,
        "hypotheses": _pick(source, "hypotheses", "candidates", default=_pick(raw_output, "hypotheses")),
        "dimension_reviews": _pick(
            source,
            "dimension_reviews",
            "dimensionReviews",
            default=_pick(raw_output, "dimension_reviews"),
        ),
        "selection": _pick(source, "selection", default=_pick(raw_output, "selection")),
        "research_plan": _pick(
            source,
            "research_plan",
            "researchPlan",
            default=_pick(raw_output, "research_plan"),
        ),
        "feedback_iterations": _pick(
            source,
            "feedback_iterations",
            "feedbackIterations",
            default=_pick(raw_output, "feedback_iterations"),
        ),
        "result_classification": _pick(
            source,
            "result_classification",
            "resultClassification",
            default=_pick(raw_output, "result_classification"),
        ),
        "competition_result_view": _pick(
            source,
            "competition_result_view",
            "competitionResultView",
            default=_pick(raw_output, "competition_result_view"),
        ),
        "model_invocation_receipts": receipts,
    }
    failure = _pick(source, "failure", default=None)
    if failure is not None:
        package_payload["failure"] = deepcopy(failure)
    try:
        unsealed = QuestionResultPackage.create(package_payload)
        canonical = unsealed.to_dict()
        package = QuestionResultPackage.from_dict(
            canonical,
            expected_model_policy_sha256=_sha256(
                authorized_model_policy_sha256,
                "authorized_model_policy_sha256",
            ),
        )
    except QuestionResultPackageError as exc:
        raise QuestionResultPackageAdapterError(str(exc)) from exc
    if official_model_evidence is None:
        raise QuestionResultPackageAdapterError(
            "official_model_evidence is required to bind package receipts"
        )
    _validate_receipt_evidence(package, official_model_evidence)
    return package


__all__ = [
    "QuestionResultPackageAdapterError",
    "adapt_question_result_package",
]
