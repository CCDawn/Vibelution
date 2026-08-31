"""Immutable single-question result package for the Challenge Cup catalog.

The package is deliberately a pure contract.  It does not call a model, write
an artifact, or own batch execution.  It binds one question attempt to the
tracked catalog scope, the input snapshot, and the three model-backed stages
needed by the 125-question hypothesis loop.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, ClassVar

from core.research.workflow.contracts.model_invocation_receipt import (
    ModelInvocationReceipt,
    ModelInvocationStatus,
)

from .result_set import CatalogScope, is_official_question_id

QUESTION_RESULT_PACKAGE_SCHEMA_VERSION = 2
REQUIRED_RECEIPT_STAGES = ("generation", "review", "revision")
REQUIRED_REVIEW_DIMENSIONS = (
    "evidence_support",
    "factual_accuracy",
    "novelty",
    "falsifiability",
    "plan_feasibility",
    "risk_and_ethics",
    "counterexample_coverage",
)
REVIEW_DIMENSION_RATINGS = (
    "insufficient",
    "weak",
    "mixed",
    "adequate",
    "strong",
)
_REQUIRED_COMPETITION_VIEW_FIELDS = (
    "problem_statement",
    "rationale",
    "technical_details",
    "datasets",
    "paper_title",
    "paper_abstract",
    "methods",
    "experiments",
    "results",
    "references",
)
_REQUIRED_DATASET_FIELDS = ("source", "target")
_ALLOWED_STATUSES = {
    "draft",
    "review_required",
    "needs_revision",
    "approved",
    "blocked",
    "failed",
}
_ALLOWED_RECEIPT_STATUSES = {
    ModelInvocationStatus.SUCCEEDED,
    ModelInvocationStatus.RETRIED,
}
_MODEL_POLICY_FIELDS = frozenset(
    {"family", "providerIds", "modelIds", "requireOfficialProvider", "policySha256"}
)
_QWEN_MODEL_ID_RE = re.compile(r"(?:^|[/._:-])qwen(?:$|[0-9/._:-])", re.IGNORECASE)
_MODEL_FAMILY_RE = re.compile(r"^[a-z]+", re.IGNORECASE)
_SELECTION_FIELDS = frozenset(
    {
        "selected_hypothesis_id",
        "comparison_method",
        "tradeoffs",
        "rejected_hypotheses",
        "human_gate",
    }
)
_RESEARCH_PLAN_FIELDS = frozenset(
    {
        "objective",
        "method",
        "work_packages",
        "variables",
        "controls",
        "data_and_materials",
        "analysis",
        "success_criteria",
        "failure_criteria",
        "stop_conditions",
        "resources",
        "timeline",
        "risks",
        "human_gate",
    }
)
_WORK_PACKAGE_FIELDS = frozenset(
    {"work_package_id", "goal", "inputs", "procedure", "outputs", "dependencies"}
)
_REJECTED_HYPOTHESIS_FIELDS = frozenset({"hypothesis_id", "reason"})
_HUMAN_GATE_REQUIRED_FIELDS = frozenset({"required", "decision", "rationale"})
_HUMAN_GATE_ALLOWED_FIELDS = frozenset(
    {"required", "decision", "rationale", "reviewer", "decided_at"}
)
_HUMAN_GATE_DECISIONS = frozenset(
    {"pending", "approved", "revision_requested", "rejected"}
)
_SELECTION_COMPARISON_METHOD = "multi_dimension_pareto_plus_human_decision"
_ALLOWED_REVIEW_RATINGS = frozenset(REVIEW_DIMENSION_RATINGS)
_REQUIRED_RESEARCH_PLAN_LIST_FIELDS = (
    "work_packages",
    "variables",
    "controls",
    "data_and_materials",
    "analysis",
    "success_criteria",
    "failure_criteria",
    "stop_conditions",
    "resources",
    "timeline",
    "risks",
)
_REQUIRED_FINAL_SUMMARY_TEXT_FIELDS = (
    "answer_boundary",
    "selected_hypothesis",
    "research_plan_summary",
    "next_validation_step",
)
_REQUIRED_FINAL_SUMMARY_LIST_FIELDS = (
    "key_evidence_refs",
    "counterevidence_refs",
    "limitations",
)
_ALLOWED_RESULT_CLASSIFICATIONS = frozenset(
    {
        "proposal_only",
        "executed_positive",
        "executed_negative",
        "executed_inconclusive",
        "blocked",
        "failed",
    }
)
_EXECUTED_CLASSIFICATIONS = frozenset(
    {"executed_positive", "executed_negative", "executed_inconclusive"}
)
_NON_EXECUTION_MARKERS = (
    "not executed",
    "not run",
    "planned",
    "proposal",
    "尚未",
    "未执行",
    "计划",
    "待执行",
)
_CONSTRUCTION_TOKEN = object()


class QuestionResultPackageError(ValueError):
    """A single-question result package is malformed or unsafe to accept."""


def _mapping(value: Any, field: str, *, allow_empty: bool = False) -> dict[str, Any]:
    if not isinstance(value, Mapping) or (not allow_empty and not value):
        suffix = "" if allow_empty else " non-empty"
        raise QuestionResultPackageError(f"{field} must be a{suffix} mapping")
    return deepcopy(dict(value))


def _text(value: Any, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise QuestionResultPackageError(f"{field} must be a non-empty string")
    return result


def _strict_text(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise QuestionResultPackageError(f"{field} must be a string")
    result = value.strip()
    if not result:
        raise QuestionResultPackageError(f"{field} must be a non-empty string")
    return result


def _optional_strict_text(payload: Mapping[str, Any], key: str, field: str) -> str:
    if key not in payload:
        return ""
    return _strict_text(payload[key], field)


def _list(value: Any, field: str, *, allow_empty: bool = True) -> list[Any]:
    if not isinstance(value, list) or (not allow_empty and not value):
        suffix = "" if allow_empty else " non-empty"
        raise QuestionResultPackageError(f"{field} must be a{suffix} list")
    return deepcopy(value)


def _string_list(value: Any, field: str, *, allow_empty: bool = True) -> list[str]:
    values = _list(value, field, allow_empty=allow_empty)
    result = [str(item or "").strip() for item in values]
    if any(not item for item in result):
        raise QuestionResultPackageError(f"{field} must not contain empty entries")
    if len(set(result)) != len(result):
        raise QuestionResultPackageError(f"{field} values must be unique")
    return result


def _alias_value(payload: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return default


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    try:
        encoded = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise QuestionResultPackageError(
            "canonical JSON must contain only finite JSON values"
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def _deep_freeze(value: Any, field: str = "package") -> Any:
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise QuestionResultPackageError(
                    f"{field} JSON object keys must be strings"
                )
            frozen[key] = _deep_freeze(item, f"{field}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(
            _deep_freeze(item, f"{field}[{index}]")
            for index, item in enumerate(value)
        )
    if isinstance(value, float) and not math.isfinite(value):
        raise QuestionResultPackageError(f"{field} must contain only finite numbers")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise QuestionResultPackageError(
        f"{field} contains a value that cannot be represented as canonical JSON"
    )


def _deep_thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _deep_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_deep_thaw(item) for item in value]
    return value


def _reject_non_finite(value: Any, field: str = "package") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise QuestionResultPackageError(f"{field} must contain only finite numbers")
    if isinstance(value, CatalogScope):
        _reject_non_finite(value.to_dict(), field)
        return
    if isinstance(value, ModelInvocationReceipt):
        _reject_non_finite(value.to_dict(), field)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_non_finite(item, f"{field}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_non_finite(item, f"{field}[{index}]")


def _sha256(value: Any, field: str) -> str:
    result = _text(value, field).lower()
    if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
        raise QuestionResultPackageError(f"{field} must be a lowercase sha256 hex digest")
    return result


def _normalize_aliases(
    payload: Mapping[str, Any],
    aliases: Mapping[str, tuple[str, ...]],
) -> dict[str, Any]:
    result = deepcopy(dict(payload))
    for canonical, keys in aliases.items():
        value = _alias_value(payload, *keys, default=None)
        if value is not None:
            result[canonical] = deepcopy(value)
        for key in keys:
            if key != canonical:
                result.pop(key, None)
    return result


def _normalize_candidate(payload: Any, index: int) -> dict[str, Any]:
    raw = _mapping(payload, f"hypotheses[{index}]")
    normalized = _normalize_aliases(
        raw,
        {
            "hypothesis_id": (
                "hypothesis_id",
                "hypothesisId",
                "candidate_id",
                "candidateId",
            ),
            "statement": ("statement", "claim"),
            "mechanism": ("mechanism",),
            "novelty_basis": ("novelty_basis", "noveltyBasis"),
            "falsifiability": ("falsifiability",),
            "predictions": ("predictions",),
            "supporting_evidence_refs": (
                "supporting_evidence_refs",
                "supportingEvidenceRefs",
            ),
            "challenging_evidence_refs": (
                "challenging_evidence_refs",
                "challengingEvidenceRefs",
            ),
            "boundary_conditions": (
                "boundary_conditions",
                "boundaryConditions",
            ),
        },
    )
    normalized["hypothesis_id"] = _text(
        _alias_value(normalized, "hypothesis_id"),
        f"hypotheses[{index}].hypothesis_id",
    )
    normalized["statement"] = _text(
        _alias_value(normalized, "statement"),
        f"hypotheses[{index}].statement",
    )
    normalized["mechanism"] = _text(
        _alias_value(normalized, "mechanism"),
        f"hypotheses[{index}].mechanism",
    )
    # These fields are schema-v2 content, but the machine contract keeps them
    # optional so a producer can assemble the package before the full output
    # projection is materialized.  Present fields are still type-checked.
    for field in (
        "predictions",
        "supporting_evidence_refs",
        "challenging_evidence_refs",
        "boundary_conditions",
    ):
        if field in normalized:
            normalized[field] = _string_list(normalized[field], f"hypotheses[{index}].{field}")
        else:
            normalized[field] = []
    for field in ("novelty_basis", "falsifiability"):
        if field in normalized:
            normalized[field] = _text(normalized[field], f"hypotheses[{index}].{field}")
        else:
            normalized[field] = ""
    return normalized


def _normalized_mechanism(value: str) -> str:
    return " ".join(value.casefold().split())


def is_qwen_model_id(value: Any) -> bool:
    """Return whether an effective upstream model id identifies Qwen."""

    normalized = str(value or "").strip()
    return bool(normalized and _QWEN_MODEL_ID_RE.search(normalized))


def model_family_for_model_id(value: Any) -> str:
    """Return the stable upstream family prefix used by a frozen policy."""

    normalized = str(value or "").strip().casefold().rsplit("/", 1)[-1]
    match = _MODEL_FAMILY_RE.match(normalized)
    return match.group(0) if match else ""


def model_id_matches_family(value: Any, family: Any) -> bool:
    return bool(
        str(family or "").strip()
        and model_family_for_model_id(value) == str(family).strip().casefold()
    )


def _canonical_model_policy_body(payload: Any) -> dict[str, Any]:
    raw = _mapping(payload, "model_policy")
    allowed_without_hash = _MODEL_POLICY_FIELDS - {"policySha256"}
    unknown = sorted(set(raw) - _MODEL_POLICY_FIELDS)
    missing = sorted(allowed_without_hash - set(raw))
    if missing:
        raise QuestionResultPackageError(
            "model_policy is missing required fields: " + ", ".join(missing)
        )
    if unknown:
        raise QuestionResultPackageError(
            "model_policy contains unsupported fields: " + ", ".join(unknown)
        )
    family = _text(raw.get("family"), "model_policy.family").casefold()
    if not _MODEL_FAMILY_RE.fullmatch(family):
        raise QuestionResultPackageError(
            "model_policy.family must be a lowercase model-family identifier"
        )

    def identifiers(field: str) -> list[str]:
        values = _string_list(
            raw.get(field), f"model_policy.{field}", allow_empty=False
        )
        return sorted({value.casefold() for value in values})

    require_official_provider = raw.get("requireOfficialProvider")
    if not isinstance(require_official_provider, bool):
        raise QuestionResultPackageError(
            "model_policy.requireOfficialProvider must be a boolean"
        )
    model_ids = identifiers("modelIds")
    if any(not model_id_matches_family(model_id, family) for model_id in model_ids):
        raise QuestionResultPackageError(
            "model_policy.modelIds must match model_policy.family"
        )
    body = {
        "family": family,
        "providerIds": identifiers("providerIds"),
        "modelIds": model_ids,
        "requireOfficialProvider": require_official_provider,
    }
    return body


def _normalize_model_policy(payload: Any) -> dict[str, Any]:
    raw = _mapping(payload, "model_policy")
    unknown = sorted(set(raw) - _MODEL_POLICY_FIELDS)
    missing = sorted(_MODEL_POLICY_FIELDS - set(raw))
    if missing:
        raise QuestionResultPackageError(
            "model_policy is missing required fields: " + ", ".join(missing)
        )
    if unknown:
        raise QuestionResultPackageError(
            "model_policy contains unsupported fields: " + ", ".join(unknown)
        )
    body = _canonical_model_policy_body(raw)
    expected_hash = _canonical_hash(body)
    supplied_hash = _sha256(raw.get("policySha256"), "model_policy.policySha256")
    if supplied_hash != expected_hash:
        raise QuestionResultPackageError(
            "model_policy policy hash does not match its normalized content"
        )
    return {**body, "policySha256": expected_hash}


def canonical_model_policy(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the canonical policy snapshot used by package validation.

    The server uses this helper to create an allowlist from trusted runtime
    bindings.  It deliberately shares the exact normalization and hashing
    path with persisted package parsing; callers cannot supply a competing
    canonicalization rule.
    """

    body = _canonical_model_policy_body(payload)
    normalized = {**body, "policySha256": _canonical_hash(body)}
    return _normalize_model_policy(normalized)


def _normalize_human_gate(payload: Any, field: str) -> dict[str, Any]:
    gate = _mapping(payload, field)
    missing = sorted(_HUMAN_GATE_REQUIRED_FIELDS - set(gate))
    unknown = sorted(set(gate) - _HUMAN_GATE_ALLOWED_FIELDS)
    if missing:
        raise QuestionResultPackageError(
            f"{field} is missing required fields: " + ", ".join(missing)
        )
    if unknown:
        raise QuestionResultPackageError(
            f"{field} contains unsupported fields: " + ", ".join(unknown)
        )
    if gate.get("required") is not True:
        raise QuestionResultPackageError(f"{field}.required must be true")
    decision = _strict_text(gate.get("decision"), f"{field}.decision").lower()
    if decision not in _HUMAN_GATE_DECISIONS:
        raise QuestionResultPackageError(f"{field}.decision is unsupported")
    normalized = {
        "required": True,
        "decision": decision,
        "rationale": _strict_text(gate.get("rationale"), f"{field}.rationale"),
    }
    reviewer = _optional_strict_text(gate, "reviewer", f"{field}.reviewer")
    decided_at = _optional_strict_text(gate, "decided_at", f"{field}.decided_at")
    if decision == "pending" and (reviewer or decided_at):
        raise QuestionResultPackageError(
            f"{field}.reviewer and {field}.decided_at are not allowed while pending"
        )
    if decision != "pending" and (not reviewer or not decided_at):
        raise QuestionResultPackageError(
            f"{field}.reviewer and {field}.decided_at are required after a decision"
        )
    if decided_at:
        try:
            datetime.fromisoformat(decided_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise QuestionResultPackageError(
                f"{field}.decided_at must be an ISO date-time"
            ) from exc
        normalized["decided_at"] = decided_at
    if reviewer:
        normalized["reviewer"] = reviewer
    return normalized


def _normalize_review(payload: Any, index: int) -> dict[str, Any]:
    raw = _mapping(payload, f"dimension_reviews[{index}]")
    normalized = _normalize_aliases(
        raw,
        {
            "hypothesis_id": ("hypothesis_id", "hypothesisId", "candidate_id", "candidateId"),
            "dimension": ("dimension",),
            "rating": ("rating",),
            "rationale": ("rationale",),
            "evidence_refs": ("evidence_refs", "evidenceRefs"),
            "reviewer": ("reviewer", "reviewerId", "reviewerAgentId"),
        },
    )
    normalized["hypothesis_id"] = _text(
        normalized.get("hypothesis_id"),
        f"dimension_reviews[{index}].hypothesis_id",
    )
    normalized["dimension"] = _text(
        normalized.get("dimension"),
        f"dimension_reviews[{index}].dimension",
    )
    if normalized["dimension"] not in REQUIRED_REVIEW_DIMENSIONS:
        raise QuestionResultPackageError(
            f"dimension_reviews[{index}].dimension is not one of the seven required dimensions"
        )
    normalized["rating"] = _text(
        normalized.get("rating"), f"dimension_reviews[{index}].rating"
    ).lower()
    if normalized["rating"] not in _ALLOWED_REVIEW_RATINGS:
        raise QuestionResultPackageError(
            f"dimension_reviews[{index}].rating is unsupported"
        )
    normalized["rationale"] = _text(
        normalized.get("rationale"), f"dimension_reviews[{index}].rationale"
    )
    normalized["reviewer"] = _text(
        normalized.get("reviewer"), f"dimension_reviews[{index}].reviewer"
    )
    normalized["evidence_refs"] = _string_list(
        normalized.get("evidence_refs"),
        f"dimension_reviews[{index}].evidence_refs",
        allow_empty=False,
    )
    return normalized


def _normalize_selection(payload: Any, hypothesis_ids: set[str]) -> dict[str, Any]:
    normalized = _normalize_aliases(
        _mapping(payload, "selection"),
        {
            "selected_hypothesis_id": (
                "selected_hypothesis_id",
                "selectedHypothesisId",
                "selected_candidate_id",
                "selectedCandidateId",
            ),
            "comparison_method": ("comparison_method", "comparisonMethod"),
        },
    )
    missing = sorted(_SELECTION_FIELDS - set(normalized))
    unknown = sorted(set(normalized) - _SELECTION_FIELDS)
    if missing:
        raise QuestionResultPackageError(
            "selection is missing required fields: " + ", ".join(missing)
        )
    if unknown:
        raise QuestionResultPackageError(
            "selection contains unsupported fields: " + ", ".join(unknown)
        )
    selected = _text(normalized.get("selected_hypothesis_id"), "selection.selected_hypothesis_id")
    if selected not in hypothesis_ids:
        raise QuestionResultPackageError("selection.selected_hypothesis_id must reference a hypothesis")
    normalized["selected_hypothesis_id"] = selected
    comparison_method = _text(
        normalized.get("comparison_method"), "selection.comparison_method"
    )
    if comparison_method != _SELECTION_COMPARISON_METHOD:
        raise QuestionResultPackageError(
            f"selection.comparison_method must be {_SELECTION_COMPARISON_METHOD}"
        )
    normalized["comparison_method"] = comparison_method
    normalized["tradeoffs"] = _string_list(
        normalized.get("tradeoffs"), "selection.tradeoffs", allow_empty=False
    )
    rejected = _list(
        normalized.get("rejected_hypotheses"),
        "selection.rejected_hypotheses",
        allow_empty=False,
    )
    normalized_rejected: list[dict[str, Any]] = []
    rejected_ids: list[str] = []
    for index, item in enumerate(rejected):
        field = f"selection.rejected_hypotheses[{index}]"
        row = _normalize_aliases(
            _mapping(item, field),
            {
                "hypothesis_id": (
                    "hypothesis_id",
                    "hypothesisId",
                    "candidateId",
                ),
                "reason": ("reason",),
            },
        )
        missing_row_fields = sorted(_REJECTED_HYPOTHESIS_FIELDS - set(row))
        unknown_row_fields = sorted(set(row) - _REJECTED_HYPOTHESIS_FIELDS)
        if missing_row_fields:
            raise QuestionResultPackageError(
                f"{field} is missing required fields: "
                + ", ".join(missing_row_fields)
            )
        if unknown_row_fields:
            raise QuestionResultPackageError(
                f"{field} contains unsupported fields: "
                + ", ".join(unknown_row_fields)
            )
        rejected_id = _text(
            row.get("hypothesis_id"),
            f"{field}.hypothesis_id",
        )
        if rejected_id not in hypothesis_ids or rejected_id == selected:
            raise QuestionResultPackageError(
                "selection.rejected_hypotheses must reference only unselected hypotheses"
            )
        row["hypothesis_id"] = rejected_id
        row["reason"] = _text(
            row.get("reason"), f"{field}.reason"
        )
        normalized_rejected.append(row)
        rejected_ids.append(rejected_id)
    expected_rejected = hypothesis_ids - {selected}
    if len(set(rejected_ids)) != len(rejected_ids) or set(rejected_ids) != expected_rejected:
        raise QuestionResultPackageError(
            "selection.rejected_hypotheses must uniquely explain every unselected hypothesis"
        )
    normalized["rejected_hypotheses"] = normalized_rejected
    normalized["human_gate"] = _normalize_human_gate(
        normalized.get("human_gate"), "selection.human_gate"
    )
    return normalized


def _normalize_research_plan(payload: Any) -> dict[str, Any]:
    normalized = _mapping(payload, "research_plan")
    missing = sorted(_RESEARCH_PLAN_FIELDS - set(normalized))
    unknown = sorted(set(normalized) - _RESEARCH_PLAN_FIELDS)
    if missing:
        raise QuestionResultPackageError(
            "research_plan is missing required fields: " + ", ".join(missing)
        )
    if unknown:
        raise QuestionResultPackageError(
            "research_plan contains unsupported fields: " + ", ".join(unknown)
        )
    normalized["objective"] = _text(normalized.get("objective"), "research_plan.objective")
    normalized["method"] = _text(normalized.get("method"), "research_plan.method")
    work_packages = _list(
        normalized.get("work_packages"),
        "research_plan.work_packages",
        allow_empty=False,
    )
    normalized_work_packages: list[dict[str, Any]] = []
    work_package_ids: list[str] = []
    for index, item in enumerate(work_packages):
        field = f"research_plan.work_packages[{index}]"
        work_package = _mapping(item, field)
        missing_work_package_fields = sorted(
            _WORK_PACKAGE_FIELDS - set(work_package)
        )
        unknown_work_package_fields = sorted(
            set(work_package) - _WORK_PACKAGE_FIELDS
        )
        if missing_work_package_fields:
            raise QuestionResultPackageError(
                f"{field} is missing required fields: "
                + ", ".join(missing_work_package_fields)
            )
        if unknown_work_package_fields:
            raise QuestionResultPackageError(
                f"{field} contains unsupported fields: "
                + ", ".join(unknown_work_package_fields)
            )
        work_package["work_package_id"] = _text(
            work_package.get("work_package_id"), f"{field}.work_package_id"
        )
        work_package["goal"] = _text(work_package.get("goal"), f"{field}.goal")
        for list_field in ("inputs", "procedure", "outputs", "dependencies"):
            work_package[list_field] = _string_list(
                work_package.get(list_field),
                f"{field}.{list_field}",
                allow_empty=False,
            )
        work_package_ids.append(work_package["work_package_id"])
        normalized_work_packages.append(work_package)
    if len(set(work_package_ids)) != len(work_package_ids):
        raise QuestionResultPackageError(
            "research_plan.work_package_id values must be unique"
        )
    normalized["work_packages"] = normalized_work_packages
    for field in _REQUIRED_RESEARCH_PLAN_LIST_FIELDS[1:]:
        normalized[field] = _string_list(
            normalized.get(field), f"research_plan.{field}", allow_empty=False
        )
    normalized["human_gate"] = _normalize_human_gate(
        normalized.get("human_gate"), "research_plan.human_gate"
    )
    return normalized


def normalize_research_plan(payload: Any) -> dict[str, Any]:
    """Normalize the canonical v2 research plan outside a full package.

    The formal workflow uses the exact same strict field, list, work-package,
    and human-gate rules as ``QuestionResultPackage``.  Keep the package path
    private so the public helper remains a small compatibility surface.
    """

    return _normalize_research_plan(payload)


def _normalize_feedback(payload: Any) -> tuple[dict[str, Any], ...]:
    values = _list(payload, "feedback_iterations", allow_empty=False)
    result: list[dict[str, Any]] = []
    previous_round = 0
    for index, item in enumerate(values):
        row = _mapping(item, f"feedback_iterations[{index}]")
        round_value = row.get("round")
        if isinstance(round_value, bool) or not isinstance(round_value, int) or round_value < 1:
            raise QuestionResultPackageError(
                f"feedback_iterations[{index}].round must be an integer >= 1"
            )
        if round_value <= previous_round:
            raise QuestionResultPackageError(
                "feedback_iterations.round values must be unique and strictly increasing"
            )
        previous_round = round_value
        for field in ("input_refs", "changes", "unresolved_issues"):
            row[field] = _string_list(
                row.get(field),
                f"feedback_iterations[{index}].{field}",
                allow_empty=False,
            )
        for field in ("trigger", "human_feedback"):
            row[field] = _text(
                row.get(field), f"feedback_iterations[{index}].{field}"
            )
        result.append(row)
    return tuple(result)


def _normalize_result_classification(
    payload: Any,
    *,
    selected_hypothesis_id: str,
    selected_statement: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    result = _mapping(payload, "result_classification")
    status = _text(result.get("status"), "result_classification.status").lower()
    if status not in _ALLOWED_STATUSES:
        raise QuestionResultPackageError(
            "result_classification.status is not a supported package status"
        )
    result["status"] = status
    if not isinstance(result.get("actual_execution"), bool):
        raise QuestionResultPackageError("result_classification.actual_execution must be boolean")
    classification = _text(
        result.get("classification"), "result_classification.classification"
    ).lower()
    if classification not in _ALLOWED_RESULT_CLASSIFICATIONS:
        raise QuestionResultPackageError(
            "result_classification.classification is unsupported"
        )
    actual_execution = result["actual_execution"]
    if classification == "proposal_only" and actual_execution:
        raise QuestionResultPackageError(
            "result_classification.actual_execution must be false for proposal_only"
        )
    if classification in _EXECUTED_CLASSIFICATIONS and not actual_execution:
        raise QuestionResultPackageError(
            "result_classification.actual_execution must be true for executed classifications"
        )
    if status in {"blocked", "failed"} and classification != status:
        raise QuestionResultPackageError(
            "blocked or failed status must use the matching result classification"
        )
    if classification in {"blocked", "failed"} and status != classification:
        raise QuestionResultPackageError(
            "blocked or failed classification must use the matching status"
        )
    result["classification"] = classification
    final_summary = _mapping(
        result.get("final_summary"), "result_classification.final_summary"
    )
    for field in _REQUIRED_FINAL_SUMMARY_TEXT_FIELDS:
        final_summary[field] = _text(
            final_summary.get(field), f"result_classification.final_summary.{field}"
        )
    selected_summary = final_summary["selected_hypothesis"]
    if selected_summary not in {selected_hypothesis_id, selected_statement}:
        raise QuestionResultPackageError(
            "result_classification.final_summary.selected_hypothesis must match selection"
        )
    for field in _REQUIRED_FINAL_SUMMARY_LIST_FIELDS:
        final_summary[field] = _string_list(
            final_summary.get(field),
            f"result_classification.final_summary.{field}",
            allow_empty=False,
        )
    result["final_summary"] = final_summary
    raw_failure = result.pop("failure", None)
    failure = _mapping(raw_failure, "failure") if raw_failure is not None else None
    return result, failure


def _normalize_competition_view(payload: Any) -> dict[str, Any]:
    raw = _mapping(payload, "competition_result_view")
    normalized = _normalize_aliases(
        raw,
        {
            "problem_statement": ("problem_statement", "problemStatement"),
            "technical_details": ("technical_details", "technicalDetails"),
            "paper_title": ("paper_title", "paperTitle"),
            "paper_abstract": ("paper_abstract", "paperAbstract"),
        },
    )
    for field in _REQUIRED_COMPETITION_VIEW_FIELDS:
        if field not in normalized:
            raise QuestionResultPackageError(
                f"competition_result_view is missing required field {field}"
            )
    for field in (
        "problem_statement",
        "rationale",
        "technical_details",
        "paper_title",
        "paper_abstract",
    ):
        normalized[field] = _text(normalized[field], f"competition_result_view.{field}")
    datasets = _mapping(normalized["datasets"], "competition_result_view.datasets")
    for field in _REQUIRED_DATASET_FIELDS:
        if field not in datasets:
            raise QuestionResultPackageError(
                f"competition_result_view.datasets is missing required field {field}"
            )
        datasets[field] = _string_list(
            datasets[field],
            f"competition_result_view.datasets.{field}",
            allow_empty=False,
        )
    normalized["datasets"] = datasets
    for field in ("methods", "experiments", "results", "references"):
        normalized[field] = _string_list(
            normalized[field],
            f"competition_result_view.{field}",
            allow_empty=False,
        )
    return normalized


def _has_non_execution_marker(value: str) -> bool:
    normalized = " ".join(value.casefold().split())
    return any(marker in normalized for marker in _NON_EXECUTION_MARKERS)


def _validate_execution_view(
    result_classification: Mapping[str, Any],
    competition_result_view: Mapping[str, Any],
) -> None:
    classification = str(result_classification["classification"])
    actual_execution = bool(result_classification["actual_execution"])
    experiments = [str(item) for item in competition_result_view["experiments"]]
    results = [str(item) for item in competition_result_view["results"]]
    if classification == "proposal_only":
        if actual_execution or any(not _has_non_execution_marker(item) for item in results):
            raise QuestionResultPackageError(
                "proposal_only competition results must explicitly state that execution is planned or not executed"
            )
        return
    if classification in _EXECUTED_CLASSIFICATIONS and (
        not actual_execution
        or any(
            _has_non_execution_marker(item) for item in experiments + results
        )
    ):
        raise QuestionResultPackageError(
            "executed classification cannot carry planned or not-executed experiment text"
        )


def _scope_value(scope: Mapping[str, Any], *keys: str) -> str:
    values = [
        (key, str(scope.get(key) or "").strip())
        for key in keys
        if key in scope
    ]
    if not values:
        return ""
    first_value = values[0][1]
    if any(value.casefold() != first_value.casefold() for _, value in values[1:]):
        present_keys = ", ".join(key for key, _ in values)
        raise QuestionResultPackageError(
            "receipt scope contains conflicting alias values: " + present_keys
        )
    return first_value


def _validate_receipt(
    stage: str,
    raw_receipt: Any,
    *,
    scope: CatalogScope,
    model_policy: Mapping[str, Any],
    question_id: str,
    run_id: str,
) -> ModelInvocationReceipt:
    try:
        receipt = (
            raw_receipt
            if isinstance(raw_receipt, ModelInvocationReceipt)
            else ModelInvocationReceipt.from_dict(_mapping(raw_receipt, f"receipt.{stage}"))
        )
    except (TypeError, ValueError, KeyError) as exc:
        raise QuestionResultPackageError(f"receipt.{stage} is malformed") from exc
    if receipt.status not in _ALLOWED_RECEIPT_STATUSES:
        raise QuestionResultPackageError(
            f"receipt.{stage} must represent a successful model invocation"
        )
    provider = receipt.provider.strip().lower()
    model = receipt.model.strip().lower()
    requested_model = receipt.requested_model.strip().lower()
    allowed_providers = set(model_policy["providerIds"])
    allowed_models = set(model_policy["modelIds"])
    if (
        provider not in allowed_providers
        or model not in allowed_models
        or requested_model not in allowed_models
    ):
        raise QuestionResultPackageError(
            f"receipt.{stage} must exactly match the authorized model policy"
        )
    if not receipt.evidence_locator:
        raise QuestionResultPackageError(
            f"receipt.{stage} requires a non-empty evidence locator"
        )
    if receipt.run_id != run_id:
        raise QuestionResultPackageError(f"receipt.{stage} run binding does not match package run")
    receipt_scope = dict(receipt.scope or {})
    receipt_question_id = _scope_value(receipt_scope, "questionId", "question_id", "question")
    if receipt_question_id != question_id:
        raise QuestionResultPackageError(
            f"receipt.{stage} question binding does not match package question"
        )
    receipt_scope_run_id = _scope_value(receipt_scope, "runId", "run_id")
    if receipt_scope_run_id and receipt_scope_run_id != run_id:
        raise QuestionResultPackageError(f"receipt.{stage} scope run binding does not match package run")
    receipt_stage = _scope_value(
        receipt_scope,
        "stageId",
        "stage_id",
        "stage",
        "nodeId",
    )
    if receipt_stage != stage:
        raise QuestionResultPackageError(
            f"receipt.{stage} stage binding must match its stage key"
        )
    receipt_policy_sha256 = _scope_value(
        receipt_scope, "modelPolicySha256", "model_policy_sha256"
    )
    if receipt_policy_sha256.casefold() != str(
        model_policy["policySha256"]
    ).casefold():
        raise QuestionResultPackageError(
            f"receipt.{stage} scope model policy binding does not match package policy"
        )
    receipt_scope_node_run_id = _scope_value(
        receipt_scope, "nodeRunId", "node_run_id"
    )
    if receipt_scope_node_run_id and receipt_scope_node_run_id != receipt.node_run_id:
        raise QuestionResultPackageError(
            f"receipt.{stage} node run binding does not match receipt identity"
        )
    expected_values = {
        "catalog_id": scope.catalog_id,
        "catalog_version": scope.catalog_version,
        "catalog_sha256": scope.catalog_sha256,
        "scope_hash": scope.scope_hash,
    }
    receipt_scope_aliases = {
        "catalog_id": ("catalog_id", "catalogId"),
        "catalog_version": ("catalog_version", "catalogVersion"),
        "catalog_sha256": ("catalog_sha256", "catalogSha256"),
        "scope_hash": ("scope_hash", "scopeHash"),
    }
    for field, expected in expected_values.items():
        actual = _scope_value(receipt_scope, *receipt_scope_aliases[field])
        if not actual or actual.casefold() != expected.casefold():
            raise QuestionResultPackageError(
                f"receipt.{stage} scope binding does not match package scope ({field})"
            )
    return receipt


@dataclass(frozen=True, slots=True, init=False)
class QuestionResultPackage:
    """Hash-bound, single-question result package for one catalog run."""

    schema_version: int
    package_id: str
    scope: CatalogScope
    model_policy: Mapping[str, Any]
    question_id: str
    run_id: str
    input_snapshot_sha256: str
    hypotheses: tuple[Mapping[str, Any], ...]
    dimension_reviews: tuple[Mapping[str, Any], ...]
    selection: Mapping[str, Any]
    research_plan: Mapping[str, Any]
    feedback_iterations: tuple[Mapping[str, Any], ...]
    result_classification: Mapping[str, Any]
    competition_result_view: Mapping[str, Any]
    _model_invocation_receipts: Mapping[str, Mapping[str, Any]]
    failure: Mapping[str, Any] | None = None

    SCHEMA_VERSION: ClassVar[int] = QUESTION_RESULT_PACKAGE_SCHEMA_VERSION

    def __init__(
        self,
        *,
        _token: object,
        schema_version: int,
        package_id: str,
        scope: CatalogScope,
        model_policy: dict[str, Any],
        question_id: str,
        run_id: str,
        input_snapshot_sha256: str,
        hypotheses: tuple[dict[str, Any], ...],
        dimension_reviews: tuple[dict[str, Any], ...],
        selection: dict[str, Any],
        research_plan: dict[str, Any],
        feedback_iterations: tuple[dict[str, Any], ...],
        result_classification: dict[str, Any],
        competition_result_view: dict[str, Any],
        model_invocation_receipts: Mapping[str, ModelInvocationReceipt],
        failure: dict[str, Any] | None,
    ) -> None:
        if _token is not _CONSTRUCTION_TOKEN:
            raise QuestionResultPackageError(
                "QuestionResultPackage must be created through create() or from_dict()"
            )
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "package_id", package_id)
        object.__setattr__(self, "scope", scope)
        object.__setattr__(
            self, "model_policy", _deep_freeze(model_policy, "model_policy")
        )
        object.__setattr__(self, "question_id", question_id)
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "input_snapshot_sha256", input_snapshot_sha256)
        object.__setattr__(
            self,
            "hypotheses",
            tuple(_deep_freeze(item, "hypotheses") for item in hypotheses),
        )
        object.__setattr__(
            self,
            "dimension_reviews",
            tuple(
                _deep_freeze(item, "dimension_reviews")
                for item in dimension_reviews
            ),
        )
        object.__setattr__(self, "selection", _deep_freeze(selection, "selection"))
        object.__setattr__(
            self, "research_plan", _deep_freeze(research_plan, "research_plan")
        )
        object.__setattr__(
            self,
            "feedback_iterations",
            tuple(
                _deep_freeze(item, "feedback_iterations")
                for item in feedback_iterations
            ),
        )
        object.__setattr__(
            self,
            "result_classification",
            _deep_freeze(result_classification, "result_classification"),
        )
        object.__setattr__(
            self,
            "competition_result_view",
            _deep_freeze(competition_result_view, "competition_result_view"),
        )
        receipt_payloads = {
            stage: receipt.to_dict()
            for stage, receipt in model_invocation_receipts.items()
        }
        object.__setattr__(
            self,
            "_model_invocation_receipts",
            _deep_freeze(receipt_payloads, "model_invocation_receipts"),
        )
        object.__setattr__(
            self,
            "failure",
            _deep_freeze(failure, "failure") if failure is not None else None,
        )

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        *,
        expected_model_policy_sha256: str,
    ) -> QuestionResultPackage:
        """Restore persisted data only against an externally authorized policy hash."""

        return cls._parse(
            payload,
            require_canonical_hash=True,
            expected_model_policy_sha256=expected_model_policy_sha256,
        )

    @classmethod
    def _parse(
        cls,
        payload: Mapping[str, Any],
        *,
        require_canonical_hash: bool,
        expected_model_policy_sha256: str | None = None,
    ) -> QuestionResultPackage:
        raw = _mapping(payload, "QuestionResultPackage")
        _reject_non_finite(raw)
        allowed_keys = {
            "schema_version",
            "schemaVersion",
            "package_id",
            "packageId",
            "scope",
            "catalog_scope",
            "catalogScope",
            "model_policy",
            "modelPolicy",
            "question_id",
            "questionId",
            "run_id",
            "runId",
            "input_snapshot_sha256",
            "inputSnapshotSha256",
            "input_snapshot_hash",
            "inputSnapshotHash",
            "hypotheses",
            "candidates",
            "dimension_reviews",
            "dimensionReviews",
            "selection",
            "research_plan",
            "researchPlan",
            "feedback_iterations",
            "feedbackIterations",
            "result_classification",
            "resultClassification",
            "competition_result_view",
            "competitionResultView",
            "model_invocation_receipts",
            "modelInvocationReceipts",
            "receipts",
            "failure",
            "idempotency_key",
            "idempotencyKey",
            "canonical_sha256",
            "canonicalSha256",
            "package_sha256",
        }
        unknown = sorted(set(raw) - allowed_keys)
        if unknown:
            raise QuestionResultPackageError(
                "QuestionResultPackage contains unsupported fields: " + ", ".join(unknown)
            )
        supplied_hash = _alias_value(
            raw,
            "canonical_sha256",
            "canonicalSha256",
            "package_sha256",
            default=None,
        )
        if require_canonical_hash and supplied_hash is None:
            raise QuestionResultPackageError(
                "canonical hash is required when restoring a persisted package"
            )
        schema_version = _alias_value(raw, "schema_version", "schemaVersion", default=0)
        if schema_version != QUESTION_RESULT_PACKAGE_SCHEMA_VERSION:
            raise QuestionResultPackageError(
                f"schema_version must be {QUESTION_RESULT_PACKAGE_SCHEMA_VERSION}"
            )
        package_id = _text(
            _alias_value(raw, "package_id", "packageId"),
            "package_id",
        )
        question_id = _text(
            _alias_value(raw, "question_id", "questionId"),
            "question_id",
        )
        if not is_official_question_id(question_id):
            raise QuestionResultPackageError(f"question_id is not an official catalog question: {question_id}")
        run_id = _text(_alias_value(raw, "run_id", "runId"), "run_id")
        input_snapshot_sha256 = _sha256(
            _alias_value(
                raw,
                "input_snapshot_sha256",
                "inputSnapshotSha256",
                "input_snapshot_hash",
                "inputSnapshotHash",
            ),
            "input_snapshot_sha256",
        )
        scope_raw = _alias_value(raw, "scope", "catalog_scope", "catalogScope")
        try:
            scope = (
                scope_raw
                if isinstance(scope_raw, CatalogScope)
                else CatalogScope.from_dict(_mapping(scope_raw, "scope"))
            )
        except (TypeError, ValueError, KeyError) as exc:
            raise QuestionResultPackageError("scope is malformed or its hash is invalid") from exc
        if scope != CatalogScope.from_tracked_resources():
            raise QuestionResultPackageError(
                "scope must exactly match the official tracked catalog scope"
            )
        model_policy = _normalize_model_policy(
            _alias_value(raw, "model_policy", "modelPolicy")
        )
        if expected_model_policy_sha256 is not None:
            authorized_policy_sha256 = _sha256(
                expected_model_policy_sha256,
                "expected_model_policy_sha256",
            )
            if model_policy["policySha256"] != authorized_policy_sha256:
                raise QuestionResultPackageError(
                    "model_policy does not match the externally authorized policy hash"
                )

        raw_hypotheses = _alias_value(raw, "hypotheses", "candidates")
        hypotheses_raw = _list(raw_hypotheses, "hypotheses", allow_empty=False)
        hypotheses = tuple(_normalize_candidate(item, index) for index, item in enumerate(hypotheses_raw))
        if len(hypotheses) < 2:
            raise QuestionResultPackageError("hypotheses must contain at least two candidates")
        hypothesis_ids = [item["hypothesis_id"] for item in hypotheses]
        if len(set(hypothesis_ids)) != len(hypothesis_ids):
            raise QuestionResultPackageError("hypothesis_id values must be unique")
        mechanisms = {_normalized_mechanism(item["mechanism"]) for item in hypotheses}
        if len(mechanisms) < 2:
            raise QuestionResultPackageError(
                "hypotheses must contain at least two mechanism-distinct candidates"
            )

        raw_reviews = _alias_value(raw, "dimension_reviews", "dimensionReviews")
        reviews = tuple(
            _normalize_review(item, index)
            for index, item in enumerate(_list(raw_reviews, "dimension_reviews", allow_empty=False))
        )
        coverage = {(item["hypothesis_id"], item["dimension"]) for item in reviews}
        if len(coverage) != len(reviews):
            raise QuestionResultPackageError(
                "dimension_reviews must be unique for each hypothesis and dimension"
            )
        unknown_review_ids = {item["hypothesis_id"] for item in reviews} - set(hypothesis_ids)
        if unknown_review_ids:
            raise QuestionResultPackageError(
                "dimension_reviews references an unknown hypothesis"
            )
        missing_reviews = {
            hypothesis_id: sorted(
                set(REQUIRED_REVIEW_DIMENSIONS)
                - {dimension for candidate, dimension in coverage if candidate == hypothesis_id}
            )
            for hypothesis_id in hypothesis_ids
        }
        missing_reviews = {key: value for key, value in missing_reviews.items() if value}
        if missing_reviews:
            raise QuestionResultPackageError(
                "dimension_reviews must cover all seven dimensions for every hypothesis"
            )

        selection = _normalize_selection(
            _alias_value(raw, "selection"),
            set(hypothesis_ids),
        )
        research_plan = _normalize_research_plan(
            _alias_value(raw, "research_plan", "researchPlan")
        )
        feedback_iterations = _normalize_feedback(
            _alias_value(raw, "feedback_iterations", "feedbackIterations")
        )
        selected_id = str(selection["selected_hypothesis_id"])
        selected_statement = next(
            str(item["statement"])
            for item in hypotheses
            if item["hypothesis_id"] == selected_id
        )
        result_classification, inferred_failure = _normalize_result_classification(
            _alias_value(raw, "result_classification", "resultClassification"),
            selected_hypothesis_id=selected_id,
            selected_statement=selected_statement,
        )
        supplied_failure = _alias_value(raw, "failure", default=None)
        failure = (
            _mapping(supplied_failure, "failure")
            if supplied_failure is not None
            else inferred_failure
        )
        status = result_classification["status"]
        if status in {"blocked", "failed"} and failure is None:
            raise QuestionResultPackageError(
                "failure is required to close a blocked or failed result"
            )
        if failure is not None:
            for field in ("stage", "code", "message"):
                failure[field] = _text(failure.get(field), f"failure.{field}")
            if not isinstance(failure.get("retryable"), bool):
                raise QuestionResultPackageError("failure.retryable must be boolean")

        competition_result_view = _normalize_competition_view(
            _alias_value(raw, "competition_result_view", "competitionResultView")
        )
        _validate_execution_view(result_classification, competition_result_view)
        raw_receipts = _alias_value(
            raw,
            "model_invocation_receipts",
            "modelInvocationReceipts",
            "receipts",
        )
        receipts_mapping = _mapping(raw_receipts, "model_invocation_receipts")
        missing_stages = [stage for stage in REQUIRED_RECEIPT_STAGES if stage not in receipts_mapping]
        if missing_stages:
            raise QuestionResultPackageError(
                "receipt stages are incomplete: " + ", ".join(missing_stages)
            )
        unexpected_stages = sorted(set(receipts_mapping) - set(REQUIRED_RECEIPT_STAGES))
        if unexpected_stages:
            raise QuestionResultPackageError(
                "receipt stages contain unsupported keys: " + ", ".join(unexpected_stages)
            )
        receipts = {
            stage: _validate_receipt(
                stage,
                receipts_mapping[stage],
                scope=scope,
                model_policy=model_policy,
                question_id=question_id,
                run_id=run_id,
            )
            for stage in REQUIRED_RECEIPT_STAGES
        }
        receipt_ids = [receipt.receipt_id for receipt in receipts.values()]
        node_run_ids = [receipt.node_run_id for receipt in receipts.values()]
        if len(set(receipt_ids)) != len(receipt_ids):
            raise QuestionResultPackageError(
                "receipt_id values must be unique across package stages"
            )
        if len(set(node_run_ids)) != len(node_run_ids):
            raise QuestionResultPackageError(
                "node_run_id values must be unique across package stages"
            )

        package = cls(
            _token=_CONSTRUCTION_TOKEN,
            schema_version=QUESTION_RESULT_PACKAGE_SCHEMA_VERSION,
            package_id=package_id,
            scope=scope,
            model_policy=model_policy,
            question_id=question_id,
            run_id=run_id,
            input_snapshot_sha256=input_snapshot_sha256,
            hypotheses=hypotheses,
            dimension_reviews=reviews,
            selection=selection,
            research_plan=research_plan,
            feedback_iterations=feedback_iterations,
            result_classification=result_classification,
            competition_result_view=competition_result_view,
            model_invocation_receipts=receipts,
            failure=failure,
        )
        expected_idempotency_key = package.idempotency_key
        supplied_idempotency_key = _alias_value(raw, "idempotency_key", "idempotencyKey", default=None)
        if supplied_idempotency_key is not None and str(supplied_idempotency_key) != expected_idempotency_key:
            raise QuestionResultPackageError("idempotency_key does not match package identity")
        if supplied_hash is not None and str(supplied_hash).lower() != package.canonical_hash:
            raise QuestionResultPackageError("canonical hash does not match package content")
        return package

    @classmethod
    def create(
        cls,
        payload: Mapping[str, Any] | None = None,
        *,
        scope: CatalogScope | None = None,
        model_policy: Mapping[str, Any] | None = None,
        question_id: str = "",
        run_id: str = "",
        input_snapshot_sha256: str = "",
        hypotheses: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] | None = None,
        dimension_reviews: list[Mapping[str, Any]]
        | tuple[Mapping[str, Any], ...]
        | None = None,
        selection: Mapping[str, Any] | None = None,
        research_plan: Mapping[str, Any] | None = None,
        feedback_iterations: list[Mapping[str, Any]]
        | tuple[Mapping[str, Any], ...]
        | None = None,
        result_classification: Mapping[str, Any] | None = None,
        competition_result_view: Mapping[str, Any] | None = None,
        model_invocation_receipts: Mapping[str, Any] | None = None,
        package_id: str = "question-result-package",
        failure: Mapping[str, Any] | None = None,
    ) -> QuestionResultPackage:
        """Build from trusted runtime output before persistence.

        This constructor validates and seals an in-memory package but does not
        establish the external model-policy trust boundary.  Raw or persisted
        input must use :meth:`from_dict`, which requires the authorized policy
        hash supplied by the runtime rather than trusting the payload itself.
        """

        if payload is not None:
            if scope is not None or model_policy is not None:
                raise QuestionResultPackageError(
                    "create() accepts either an unsealed payload or keyword fields, not both"
                )
            return cls._parse(payload, require_canonical_hash=False)
        if scope is None:
            raise QuestionResultPackageError("scope is required")
        if model_policy is None:
            raise QuestionResultPackageError("model_policy is required")
        unsealed: dict[str, Any] = {
            "schema_version": QUESTION_RESULT_PACKAGE_SCHEMA_VERSION,
            "package_id": package_id,
            "scope": scope,
            "model_policy": dict(model_policy),
            "question_id": question_id,
            "run_id": run_id,
            "input_snapshot_sha256": input_snapshot_sha256,
            "hypotheses": list(hypotheses or ()),
            "dimension_reviews": list(dimension_reviews or ()),
            "selection": dict(selection or {}),
            "research_plan": dict(research_plan or {}),
            "feedback_iterations": list(feedback_iterations or ()),
            "result_classification": dict(result_classification or {}),
            "competition_result_view": dict(competition_result_view or {}),
            "model_invocation_receipts": dict(model_invocation_receipts or {}),
        }
        if failure is not None:
            unsealed["failure"] = dict(failure)
        return cls._parse(unsealed, require_canonical_hash=False)

    @property
    def model_invocation_receipts(self) -> dict[str, ModelInvocationReceipt]:
        """Return detached receipt objects so callers cannot mutate the seal."""

        return {
            stage: ModelInvocationReceipt.from_dict(_deep_thaw(receipt_payload))
            for stage, receipt_payload in self._model_invocation_receipts.items()
        }

    @property
    def idempotency_key(self) -> str:
        identity = {
            "schema_version": self.schema_version,
            "scope_hash": self.scope.scope_hash,
            "model_policy_sha256": self.model_policy["policySha256"],
            "question_id": self.question_id,
            "run_id": self.run_id,
            "input_snapshot_sha256": self.input_snapshot_sha256,
        }
        return "qrp-v2-" + _canonical_hash(identity)

    @property
    def canonical_hash(self) -> str:
        return _canonical_hash(self.canonical_payload())

    @property
    def canonical_sha256(self) -> str:
        """Compatibility alias for callers naming the digest explicitly."""

        return self.canonical_hash

    @property
    def questionId(self) -> str:
        return self.question_id

    @property
    def runId(self) -> str:
        return self.run_id

    @property
    def inputSnapshotSha256(self) -> str:
        return self.input_snapshot_sha256

    @property
    def idempotencyKey(self) -> str:
        return self.idempotency_key

    def canonical_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "package_id": self.package_id,
            "scope": self.scope.to_dict(),
            "model_policy": _deep_thaw(self.model_policy),
            "question_id": self.question_id,
            "run_id": self.run_id,
            "input_snapshot_sha256": self.input_snapshot_sha256,
            "hypotheses": _deep_thaw(self.hypotheses),
            "dimension_reviews": _deep_thaw(self.dimension_reviews),
            "selection": _deep_thaw(self.selection),
            "research_plan": _deep_thaw(self.research_plan),
            "feedback_iterations": _deep_thaw(self.feedback_iterations),
            "result_classification": _deep_thaw(self.result_classification),
            "competition_result_view": _deep_thaw(self.competition_result_view),
            "model_invocation_receipts": _deep_thaw(
                self._model_invocation_receipts
            ),
            "idempotency_key": self.idempotency_key,
        }
        if self.failure is not None:
            payload["failure"] = _deep_thaw(self.failure)
        return payload

    def to_dict(self) -> dict[str, Any]:
        payload = self.canonical_payload()
        payload["canonical_sha256"] = self.canonical_hash
        return payload


def compute_question_result_package_hash(package: QuestionResultPackage) -> str:
    """Return the canonical SHA-256 for an already validated package."""

    return package.canonical_hash


def question_result_package_idempotency_key(
    *,
    scope: CatalogScope,
    question_id: str,
    run_id: str,
    input_snapshot_sha256: str,
    model_policy_sha256: str,
) -> str:
    """Derive the stable item key without performing model or storage work."""

    if scope != CatalogScope.from_tracked_resources():
        raise QuestionResultPackageError(
            "scope must exactly match the official tracked catalog scope"
        )
    if not is_official_question_id(question_id):
        raise QuestionResultPackageError(
            f"question_id is not an official catalog question: {question_id}"
        )
    identity = {
        "schema_version": QUESTION_RESULT_PACKAGE_SCHEMA_VERSION,
        "scope_hash": scope.scope_hash,
        "model_policy_sha256": _sha256(
            model_policy_sha256, "model_policy_sha256"
        ),
        "question_id": question_id,
        "run_id": _text(run_id, "run_id"),
        "input_snapshot_sha256": _sha256(input_snapshot_sha256, "input_snapshot_sha256"),
    }
    return "qrp-v2-" + _canonical_hash(identity)


__all__ = [
    "QUESTION_RESULT_PACKAGE_SCHEMA_VERSION",
    "REQUIRED_RECEIPT_STAGES",
    "REQUIRED_REVIEW_DIMENSIONS",
    "REVIEW_DIMENSION_RATINGS",
    "QuestionResultPackage",
    "QuestionResultPackageError",
    "canonical_model_policy",
    "compute_question_result_package_hash",
    "is_qwen_model_id",
    "model_family_for_model_id",
    "model_id_matches_family",
    "normalize_research_plan",
    "question_result_package_idempotency_key",
]
