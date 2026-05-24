# -*- coding: utf-8 -*-
"""Supervised evaluation intake boundary helpers."""

from __future__ import annotations

from typing import Any


REVIEWED_CHAT_DATASET_NAME = "chat_reviewed_multiturn"
GENERATED_CASES_DATASET_NAME = "generated_cases"

SUPERVISED_EVALUATION_USE = "supervised_evaluation"
GYM_CANDIDATE_CASE_USE = "gym_candidate_case"
FUTURE_TRAINING_EXPORT_USE = "future_training_export"
REGRESSION_OBSERVATION_USE = "regression_observation"
SUPERVISED_REVIEW_USE = "supervised_review"

REVIEWED_CHAT_ALLOWED_DOWNSTREAM_USES = [
    SUPERVISED_EVALUATION_USE,
    GYM_CANDIDATE_CASE_USE,
    FUTURE_TRAINING_EXPORT_USE,
]

GENERATED_CASE_ALLOWED_DOWNSTREAM_USES = [
    SUPERVISED_EVALUATION_USE,
    GYM_CANDIDATE_CASE_USE,
    REGRESSION_OBSERVATION_USE,
]

BLOCKED_SELF_EVOLUTION_BYPASS_USES = [
    "accepted_baseline",
    "selection_policy",
    "runtime_prompt_override",
]


def reviewed_chat_dataset_metadata() -> dict[str, Any]:
    """Return registry metadata for reviewed chat cases."""

    return {
        "review_required": True,
        "source_track": "dialogue",
        "allowed_downstream_uses": list(REVIEWED_CHAT_ALLOWED_DOWNSTREAM_USES),
        "holdout_allowed": False,
        "raw_chat_direct_training_allowed": False,
    }


def generated_case_dataset_metadata() -> dict[str, Any]:
    """Return registry metadata for generated cases."""

    return {
        "review_required": False,
        "source_track": "generated",
        "allowed_downstream_uses": list(GENERATED_CASE_ALLOWED_DOWNSTREAM_USES),
        "holdout_allowed": False,
        "raw_chat_direct_training_allowed": False,
    }


def protected_dataset_boundary_fields() -> set[str]:
    """Fields that must not drift for protected supervised intake datasets."""

    return {
        "review_required",
        "source_track",
        "allowed_downstream_uses",
        "holdout_allowed",
        "raw_chat_direct_training_allowed",
    }


def dataset_intake_boundary(
    *,
    name: str,
    kind: str,
    review_required: bool,
    source_track: str,
    allowed_downstream_uses: list[str],
    holdout_allowed: bool,
    raw_chat_direct_training_allowed: bool,
) -> dict[str, Any]:
    """Build the public supervised intake boundary for a dataset."""

    dataset_name = str(name or "").strip()
    dataset_kind = str(kind or "").strip()
    normalized_track = str(source_track or "").strip()
    downstream_uses = _unique_texts(allowed_downstream_uses)
    reasons: list[str] = []
    contract = "general_dataset"

    if dataset_name == REVIEWED_CHAT_DATASET_NAME or normalized_track == "dialogue":
        contract = "reviewed_chat_case"
        if not review_required:
            reasons.append("review_required_missing")
        if raw_chat_direct_training_allowed:
            reasons.append("raw_chat_direct_training_not_blocked")
        if holdout_allowed:
            reasons.append("holdout_not_frozen_reviewed")
        if SUPERVISED_EVALUATION_USE not in downstream_uses:
            reasons.append("supervised_evaluation_not_allowed")
    elif dataset_name == GENERATED_CASES_DATASET_NAME or dataset_kind == "generated_case_jsonl":
        contract = "generated_case"
        if holdout_allowed:
            reasons.append("generated_holdout_not_blocked")
        if raw_chat_direct_training_allowed:
            reasons.append("raw_chat_direct_training_not_blocked")
        if SUPERVISED_EVALUATION_USE not in downstream_uses:
            reasons.append("supervised_evaluation_not_allowed")

    return {
        "contract": contract,
        "formal_supervised_evaluation_allowed": not reasons,
        "review_required": bool(review_required),
        "source_track": normalized_track,
        "allowed_downstream_uses": downstream_uses,
        "holdout_allowed": bool(holdout_allowed),
        "raw_chat_direct_training_allowed": bool(raw_chat_direct_training_allowed),
        "boundary_reasons": reasons,
    }


def reviewed_chat_row_status(row: dict[str, Any]) -> str:
    """Return the review status encoded in a chat-derived dataset row."""

    approval = row.get("approval") if isinstance(row.get("approval"), dict) else {}
    review = row.get("review") if isinstance(row.get("review"), dict) else {}
    return str(approval.get("status") or review.get("decision") or "").strip().lower()


def self_evolution_blocked_downstream_uses(candidate_type: str) -> list[str]:
    """Return downstream uses that self-evolution candidates may not claim."""

    blocked = list(BLOCKED_SELF_EVOLUTION_BYPASS_USES)
    normalized = str(candidate_type or "").strip()
    if normalized == "skill_candidate":
        blocked.append("skill_registry_install")
    if normalized == "proposal_candidate":
        blocked.append("accepted_baseline")
    return _unique_texts(blocked)


def self_evolution_allowed_downstream_uses(candidate_type: str) -> list[str]:
    """Return allowed candidate-only supervised review uses."""

    normalized = str(candidate_type or "").strip()
    if normalized == "skill_candidate":
        return [SUPERVISED_REVIEW_USE, "skill_candidate_review"]
    if normalized == "prompt_candidate":
        return [SUPERVISED_REVIEW_USE, "prompt_candidate_review"]
    if normalized == "proposal_candidate":
        return [SUPERVISED_REVIEW_USE, "proposal_review"]
    return [SUPERVISED_REVIEW_USE]


def self_evolution_candidate_boundary(record: dict[str, Any]) -> dict[str, Any]:
    """Build the candidate-only boundary for a self-evolution output."""

    candidate_type = str(record.get("candidate_type") or "").strip()
    blocked = _unique_texts(
        _unique_texts(record.get("blocked_downstream_uses"))
        + self_evolution_blocked_downstream_uses(candidate_type)
    )
    allowed = [
        item
        for item in _unique_texts(record.get("allowed_downstream_uses"))
        if item not in set(blocked)
    ] or self_evolution_allowed_downstream_uses(candidate_type)
    return {
        "contract": "self_evolution_candidate",
        "formal_supervised_review_allowed": SUPERVISED_REVIEW_USE in allowed,
        "review_state": "pending",
        "candidate_only": True,
        "supervised_required": True,
        "auto_apply": False,
        "allowed_downstream_uses": allowed,
        "blocked_downstream_uses": blocked,
        "runtime_effect": "not_applied",
    }


def _unique_texts(value: Any) -> list[str]:
    raw_items = value if isinstance(value, list) else [] if value is None else [value]
    items: list[str] = []
    for raw in raw_items:
        item = str(raw or "").strip()
        if item and item not in items:
            items.append(item)
    return items


__all__ = [
    "GENERATED_CASES_DATASET_NAME",
    "GENERATED_CASE_ALLOWED_DOWNSTREAM_USES",
    "GYM_CANDIDATE_CASE_USE",
    "REVIEWED_CHAT_ALLOWED_DOWNSTREAM_USES",
    "REVIEWED_CHAT_DATASET_NAME",
    "SUPERVISED_EVALUATION_USE",
    "SUPERVISED_REVIEW_USE",
    "dataset_intake_boundary",
    "generated_case_dataset_metadata",
    "protected_dataset_boundary_fields",
    "reviewed_chat_dataset_metadata",
    "reviewed_chat_row_status",
    "self_evolution_allowed_downstream_uses",
    "self_evolution_blocked_downstream_uses",
    "self_evolution_candidate_boundary",
]
