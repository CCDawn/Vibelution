"""Canonical adapter for Challenge Cup question-run output packages."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
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
_MISSING = object()
_OFFICIAL_EVIDENCE_SCHEMA_VERSION = 2
_OFFICIAL_EVIDENCE_STORE_KIND = "official_model_evidence_store"
_BUSINESS_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("hypotheses", ("hypotheses", "candidates")),
    ("dimension_reviews", ("dimension_reviews", "dimensionReviews")),
    ("selection", ("selection",)),
    ("research_plan", ("research_plan", "researchPlan")),
    ("feedback_iterations", ("feedback_iterations", "feedbackIterations")),
    (
        "result_classification",
        ("result_classification", "resultClassification"),
    ),
    (
        "competition_result_view",
        ("competition_result_view", "competitionResultView"),
    ),
)
_PACKAGE_ID_ALIASES = ("package_id", "packageId")
_CANONICAL_HASH_ALIASES = (
    "canonical_sha256",
    "canonicalSha256",
    "canonicalHash",
    "package_sha256",
)
_IDEMPOTENCY_KEY_ALIASES = ("idempotency_key", "idempotencyKey")


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


def _present_values(
    payload: Mapping[str, Any],
    *keys: str,
) -> list[tuple[str, Any]]:
    return [(key, deepcopy(payload[key])) for key in keys if key in payload]


def _consistent_identity_value(
    layers: Sequence[tuple[str, Mapping[str, Any]]],
    aliases: tuple[str, ...],
    field: str,
    *,
    extra_value: str = "",
) -> str:
    supplied: list[tuple[str, str]] = []
    for layer_name, layer in layers:
        supplied.extend(
            (f"{layer_name}.{key}", str(value or "").strip())
            for key, value in _present_values(layer, *aliases)
        )
    if extra_value:
        supplied.append((field, str(extra_value).strip()))
    if not supplied:
        return ""
    first = supplied[0][1]
    if not first or any(value != first for _, value in supplied[1:]):
        raise QuestionResultPackageAdapterError(
            f"{field} identity fields conflict: "
            + ", ".join(name for name, _ in supplied)
        )
    return first


def _business_value(
    authority: Mapping[str, Any],
    layers: Sequence[tuple[str, Mapping[str, Any]]],
    field: str,
    aliases: tuple[str, ...],
) -> Any:
    authoritative = _pick(authority, *aliases, default=_MISSING)
    if authoritative is _MISSING:
        raise QuestionResultPackageAdapterError(
            f"canonical output is missing {field}"
        )
    for layer_name, layer in layers:
        for key, value in _present_values(layer, *aliases):
            if value != authoritative:
                raise QuestionResultPackageAdapterError(
                    f"{layer_name}.{key} does not match canonical output {field}"
                )
    return deepcopy(authoritative)


def _optional_business_value(
    authority: Mapping[str, Any],
    layers: Sequence[tuple[str, Mapping[str, Any]]],
    field: str,
    aliases: tuple[str, ...],
) -> Any:
    authoritative = _pick(authority, *aliases, default=_MISSING)
    for layer_name, layer in layers:
        for key, value in _present_values(layer, *aliases):
            if authoritative is _MISSING or value != authoritative:
                raise QuestionResultPackageAdapterError(
                    f"{layer_name}.{key} does not match canonical output {field}"
                )
    return authoritative


def _receipt_rows(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        receipts = value.get("receipts")
        if isinstance(receipts, (list, Mapping)):
            value = receipts
        else:
            return deepcopy(dict(value))
    if isinstance(value, Mapping):
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
        if stage in result:
            raise QuestionResultPackageAdapterError(
                f"model_invocation_receipts contains duplicate stage: {stage}"
            )
        result[stage] = deepcopy(dict(item))
    return result


def _evidence_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Mapping):
        raise QuestionResultPackageAdapterError(
            "official_model_evidence must be the authoritative evidence store"
        )
    store_schema_version = value.get("schemaVersion")
    if (
        type(store_schema_version) is not int
        or store_schema_version != _OFFICIAL_EVIDENCE_SCHEMA_VERSION
    ):
        raise QuestionResultPackageAdapterError(
            "official_model_evidence.schemaVersion must be 2"
        )
    if str(value.get("storeKind") or "") != _OFFICIAL_EVIDENCE_STORE_KIND:
        raise QuestionResultPackageAdapterError(
            "official_model_evidence.storeKind must be official_model_evidence_store"
        )
    evidence = value.get("evidence")
    if not isinstance(evidence, list):
        raise QuestionResultPackageAdapterError(
            "official_model_evidence.evidence must be a list of rows"
        )
    rows = [deepcopy(dict(item)) for item in evidence if isinstance(item, Mapping)]
    if len(rows) != len(evidence):
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
    canonical_turn_resolver: Callable[
        [Mapping[str, Any]], Mapping[str, Any] | None
    ],
) -> dict[str, dict[str, Any]]:
    rows = _evidence_rows(official_model_evidence)
    canonical_bindings: dict[str, dict[str, Any]] = {}
    stage_identity_owners: dict[str, dict[object, str]] = {
        "receiptId": {},
        "evidenceId": {},
        "outputRef": {},
        "canonicalTurn": {},
    }

    def require_independent_identity(kind: str, value: object, stage: str) -> None:
        previous_stage = stage_identity_owners[kind].get(value)
        if previous_stage is not None:
            raise QuestionResultPackageAdapterError(
                f"receipt stages {previous_stage} and {stage} must use independent "
                f"{kind} invocation identities"
            )
        stage_identity_owners[kind][value] = stage

    for stage, receipt in package.model_invocation_receipts.items():
        receipt_dict = receipt.to_dict()
        receipt_id = receipt.receipt_id
        require_independent_identity("receiptId", receipt_id, stage)
        receipt_scope = dict(receipt.scope or {})
        receipt_scope_fields = {
            "questionId": _scope_value(
                receipt_scope, "questionId", "question_id", "question"
            ),
            "runId": _scope_value(receipt_scope, "runId", "run_id"),
            "taskId": _scope_value(
                receipt_scope, "taskId", "task_id", "task"
            ),
            "turnId": _scope_value(
                receipt_scope, "turnId", "turn_id", "turn"
            ),
            "stageId": _scope_value(
                receipt_scope, "stageId", "stage_id", "stage", "nodeId"
            ),
        }
        missing_scope = [
            key for key, value in receipt_scope_fields.items() if not value
        ]
        if missing_scope:
            raise QuestionResultPackageAdapterError(
                f"receipt.{stage} scope is incomplete; missing fields: "
                + ", ".join(missing_scope)
            )
        locator = dict(receipt.evidence_locator or {})
        locator_evidence_id = _scope_value(locator, "evidenceId", "evidence_id", "id")
        locator_output_ref = _scope_value(locator, "outputRef", "output_ref", "ref")
        if not locator_output_ref:
            raise QuestionResultPackageAdapterError(
                f"receipt.{stage}.evidenceLocator.outputRef is required"
            )
        locator_output_hash = _sha256(
            _scope_value(
                locator,
                "outputSha256",
                "output_sha256",
                "outputHash",
            ),
            f"receipt.{stage}.evidenceLocator.outputSha256",
        )
        matches = [
            row
            for row in rows
            if _row_value(row, "receiptId", "receipt_id") == receipt_id
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
        row_schema_version = row.get("schemaVersion")
        if (
            type(row_schema_version) is not int
            or row_schema_version != _OFFICIAL_EVIDENCE_SCHEMA_VERSION
        ):
            raise QuestionResultPackageAdapterError(
                f"official_model_evidence for receipt.{stage}.schemaVersion must be 2"
            )
        required = {
            "receiptId": _row_value(row, "receiptId", "receipt_id"),
            "evidenceId": _row_value(row, "evidenceId", "evidence_id", "id"),
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
        if required["receiptId"] != receipt_id:
            raise QuestionResultPackageAdapterError(
                f"official_model_evidence for receipt.{stage} receipt binding mismatch"
            )
        if locator_evidence_id and required["evidenceId"] != locator_evidence_id:
            raise QuestionResultPackageAdapterError(
                f"official_model_evidence for receipt.{stage} evidence id mismatch"
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
        for field in ("questionId", "runId", "taskId", "turnId", "stageId"):
            if required[field] != receipt_scope_fields[field]:
                raise QuestionResultPackageAdapterError(
                    f"official_model_evidence for receipt.{stage} {field} "
                    "does not match receipt scope"
                )
        require_independent_identity("evidenceId", required["evidenceId"], stage)
        require_independent_identity("outputRef", required["outputRef"], stage)
        require_independent_identity(
            "canonicalTurn",
            (required["taskId"], required["turnId"]),
            stage,
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
        evidence_output_hash = _sha256(
            required["outputSha256"], f"evidence.{stage}.outputSha256"
        )
        if required["outputRef"] != locator_output_ref:
            raise QuestionResultPackageAdapterError(
                f"official_model_evidence for receipt.{stage} output ref mismatch"
            )
        if locator_output_hash != evidence_output_hash:
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
        resolved = canonical_turn_resolver(row)
        if not isinstance(resolved, Mapping):
            raise QuestionResultPackageAdapterError(
                f"canonical turn output for receipt.{stage} was not found"
            )
        binding = deepcopy(dict(resolved))
        canonical_output = binding.get("output")
        if not isinstance(canonical_output, Mapping):
            raise QuestionResultPackageAdapterError(
                f"canonical turn output for receipt.{stage} is missing output content"
            )
        binding_fields = {
            "questionId": _scope_value(
                binding, "questionId", "question_id", "question"
            ),
            "runId": _scope_value(
                binding, "sourceRunId", "runId", "run_id"
            ),
            "taskId": _scope_value(binding, "taskId", "task_id", "task"),
            "turnId": _scope_value(binding, "turnId", "turn_id", "turn"),
            "outputRef": _scope_value(
                binding, "outputRef", "output_ref", "ref"
            ),
            "outputSha256": _scope_value(
                binding, "outputSha256", "output_sha256", "outputHash"
            ),
        }
        missing_binding = [
            key for key, value in binding_fields.items() if not value
        ]
        if missing_binding:
            raise QuestionResultPackageAdapterError(
                f"canonical turn binding for receipt.{stage} is incomplete; "
                "missing fields: "
                + ", ".join(missing_binding)
            )
        if (
            binding_fields["questionId"] != package.question_id
            or binding_fields["runId"] != package.run_id
            or binding_fields["taskId"] != receipt_scope_fields["taskId"]
            or binding_fields["turnId"] != receipt_scope_fields["turnId"]
            or binding_fields["outputRef"] != locator_output_ref
            or _sha256(
                binding_fields["outputSha256"],
                f"canonical.{stage}.outputSha256",
            )
            != locator_output_hash
        ):
            raise QuestionResultPackageAdapterError(
                f"receipt.{stage}, official evidence and canonical turn binding disagree"
            )
        canonical_identity = (
            canonical_output.get("identity")
            if isinstance(canonical_output.get("identity"), Mapping)
            else {}
        )
        canonical_run = (
            canonical_output.get("run")
            if isinstance(canonical_output.get("run"), Mapping)
            else {}
        )
        if (
            _scope_value(canonical_identity, "question_id", "questionId")
            != package.question_id
            or _scope_value(canonical_run, "run_id", "runId") != package.run_id
        ):
            raise QuestionResultPackageAdapterError(
                f"canonical turn output for receipt.{stage} has wrong question/run identity"
            )
        canonical_bindings[stage] = binding
    return canonical_bindings


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
    request_identity: Mapping[str, Any] | None = None,
    canonical_turn_resolver: Callable[
        [Mapping[str, Any]], Mapping[str, Any] | None
    ]
    | None = None,
) -> QuestionResultPackage:
    """Validate and restore one canonical package through ``from_dict``."""

    raw_output = _mapping(output, "output")
    outer_package = (
        _mapping(result_package, "resultPackage", allow_empty=True)
        if result_package is not None
        else {}
    )
    nested_value = outer_package.get("package")
    nested_package = (
        _mapping(nested_value, "resultPackage.package", allow_empty=True)
        if isinstance(nested_value, Mapping)
        else {}
    )
    source = nested_package or outer_package
    package_layers: list[tuple[str, Mapping[str, Any]]] = []
    if outer_package:
        package_layers.append(("resultPackage", outer_package))
    if nested_package:
        package_layers.append(("resultPackage.package", nested_package))
    identity_layers: list[tuple[str, Mapping[str, Any]]] = []
    if isinstance(request_identity, Mapping):
        identity_layers.append(("request", request_identity))
    identity_layers.extend(package_layers)
    identity = raw_output.get("identity") if isinstance(raw_output.get("identity"), Mapping) else {}
    run = raw_output.get("run") if isinstance(raw_output.get("run"), Mapping) else {}
    question_id = _text(
        _pick(identity, "question_id", "questionId", default=None),
        "question_id",
    )
    run_id = _text(
        _pick(run, "run_id", "runId", default=None),
        "run_id",
    )
    for layer_name, layer in package_layers:
        for key, value in _present_values(layer, "question_id", "questionId"):
            if str(value or "").strip() != question_id:
                raise QuestionResultPackageAdapterError(
                    f"{layer_name}.{key} does not match canonical output question_id"
                )
        for key, value in _present_values(layer, "run_id", "runId"):
            if str(value or "").strip() != run_id:
                raise QuestionResultPackageAdapterError(
                    f"{layer_name}.{key} does not match canonical output run_id"
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
    supplied_package_id = _consistent_identity_value(
        identity_layers,
        _PACKAGE_ID_ALIASES,
        "packageId",
        extra_value=package_id,
    )
    effective_package_id = (
        supplied_package_id or f"qrp-{question_id.lower()}-{run_id}"
    )

    def build_package(authority_output: Mapping[str, Any]) -> QuestionResultPackage:
        package_payload: dict[str, Any] = {
            "schema_version": 2,
            "package_id": effective_package_id,
            "scope": catalog_scope.to_dict(),
            "model_policy": deepcopy(dict(policy)),
            "question_id": question_id,
            "run_id": run_id,
            "input_snapshot_sha256": snapshot,
            "model_invocation_receipts": receipts,
        }
        for field, aliases in _BUSINESS_FIELDS:
            package_payload[field] = _business_value(
                authority_output,
                package_layers,
                field,
                aliases,
            )
        failure = _optional_business_value(
            authority_output,
            package_layers,
            "failure",
            ("failure",),
        )
        if failure is not _MISSING:
            package_payload["failure"] = deepcopy(failure)
        try:
            unsealed = QuestionResultPackage.create(package_payload)
            canonical = unsealed.to_dict()
            return QuestionResultPackage.from_dict(
                canonical,
                expected_model_policy_sha256=_sha256(
                    authorized_model_policy_sha256,
                    "authorized_model_policy_sha256",
                ),
            )
        except QuestionResultPackageError as exc:
            raise QuestionResultPackageAdapterError(str(exc)) from exc

    provisional_package = build_package(raw_output)
    if official_model_evidence is None:
        raise QuestionResultPackageAdapterError(
            "official_model_evidence is required to bind package receipts"
        )
    if canonical_turn_resolver is None:
        raise QuestionResultPackageAdapterError(
            "canonical_turn_resolver is required to bind package receipts"
        )
    canonical_bindings = _validate_receipt_evidence(
        provisional_package,
        official_model_evidence,
        canonical_turn_resolver,
    )
    revision_binding = canonical_bindings.get("revision") or {}
    canonical_output = revision_binding.get("output")
    if not isinstance(canonical_output, Mapping):
        raise QuestionResultPackageAdapterError(
            "revision receipt is missing canonical output content"
        )
    canonical_comparison_layers = [("output", raw_output), *package_layers]
    for field, aliases in _BUSINESS_FIELDS:
        _business_value(
            canonical_output,
            canonical_comparison_layers,
            field,
            aliases,
        )
    _optional_business_value(
        canonical_output,
        canonical_comparison_layers,
        "failure",
        ("failure",),
    )
    package = build_package(canonical_output)
    supplied_canonical_hash = _consistent_identity_value(
        identity_layers,
        _CANONICAL_HASH_ALIASES,
        "canonicalHash",
    )
    if (
        supplied_canonical_hash
        and supplied_canonical_hash.lower() != package.canonical_hash
    ):
        raise QuestionResultPackageAdapterError(
            "canonicalHash does not match rebuilt canonical package"
        )
    supplied_idempotency_key = _consistent_identity_value(
        identity_layers,
        _IDEMPOTENCY_KEY_ALIASES,
        "idempotencyKey",
    )
    if supplied_idempotency_key and supplied_idempotency_key != package.idempotency_key:
        raise QuestionResultPackageAdapterError(
            "idempotencyKey does not match rebuilt canonical package"
        )
    if package.package_id != effective_package_id:
        raise QuestionResultPackageAdapterError(
            "packageId does not match rebuilt canonical package"
        )
    return package


__all__ = [
    "QuestionResultPackageAdapterError",
    "adapt_question_result_package",
]
