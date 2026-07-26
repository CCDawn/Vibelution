# -*- coding: utf-8 -*-
"""Serializable contracts for supervised-evolution optimization artifacts.

These models deliberately sit beside Gym v1 rather than changing its one
candidate execution path.  They make a future multi-candidate optimizer
replayable while preserving the current proposal-only runtime boundary.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .models import CandidateImprovement, normalize_dataset_splits


OPTIMIZATION_ARTIFACT_SCHEMA_VERSION = 1
RUNTIME_EFFECT_NOT_APPLIED = "not_applied"
AGENT_CONSUMPTION_ADVISORY = "advisory"


class OptimizationContractError(ValueError):
    """Raised when an optimization artifact cannot be safely replayed."""


def _required_text(value: object, *, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise OptimizationContractError(f"Optimization artifact requires {label}")
    return text


def _json_copy(value: Any, *, label: str) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    except (TypeError, ValueError) as exc:
        raise OptimizationContractError(f"Optimization artifact {label} must be JSON serializable") from exc


def _json_object(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OptimizationContractError(f"Optimization artifact {label} must be an object")
    return _json_copy(value, label=label)


def _stable_texts(values: list[str] | tuple[str, ...], *, label: str) -> list[str]:
    normalized = {_required_text(value, label=label) for value in values}
    return sorted(normalized)


@dataclass
class EvolutionReplayContext:
    """Immutable inputs required to reproduce a candidate evaluation."""

    baseline_agent_version: str
    dataset_bundle_ref: str
    source_commit: str
    strategy_id: str
    strategy_version: str
    seed: int
    model_binding_snapshot: dict[str, Any]
    proposer_visible_splits: list[str] = field(default_factory=lambda: ["train"])

    def __post_init__(self) -> None:
        self.baseline_agent_version = _required_text(self.baseline_agent_version, label="baseline_agent_version")
        self.dataset_bundle_ref = _required_text(self.dataset_bundle_ref, label="dataset_bundle_ref")
        self.source_commit = _required_text(self.source_commit, label="source_commit")
        self.strategy_id = _required_text(self.strategy_id, label="strategy_id")
        self.strategy_version = _required_text(self.strategy_version, label="strategy_version")
        if not isinstance(self.seed, int):
            raise OptimizationContractError("Optimization artifact seed must be an integer")
        self.model_binding_snapshot = _json_object(self.model_binding_snapshot, label="model_binding_snapshot")
        self.proposer_visible_splits = normalize_dataset_splits(self.proposer_visible_splits)
        if "holdout" in self.proposer_visible_splits:
            raise OptimizationContractError("Frozen holdout cannot be visible to an optimization proposer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_agent_version": self.baseline_agent_version,
            "dataset_bundle_ref": self.dataset_bundle_ref,
            "source_commit": self.source_commit,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "seed": self.seed,
            "model_binding_snapshot": _json_copy(self.model_binding_snapshot, label="model_binding_snapshot"),
            "proposer_visible_splits": list(self.proposer_visible_splits),
        }


@dataclass
class ReflectiveFeedback:
    """Bounded actionable feedback; trace bodies remain in referenced artifacts."""

    feedback_id: str
    episode_id: str
    trace_refs: list[str]
    actionable_lessons: list[str]
    source_fingerprint: str
    failure_taxonomy: list[str] = field(default_factory=list)
    successful_patterns: list[str] = field(default_factory=list)
    constraint_violations: list[str] = field(default_factory=list)
    target_components: list[str] = field(default_factory=list)
    confidence: float = 0.0

    def __post_init__(self) -> None:
        self.feedback_id = _required_text(self.feedback_id, label="feedback_id")
        self.episode_id = _required_text(self.episode_id, label="episode_id")
        self.source_fingerprint = _required_text(self.source_fingerprint, label="source_fingerprint")
        self.trace_refs = _stable_texts(self.trace_refs, label="trace_ref")
        self.actionable_lessons = _stable_texts(self.actionable_lessons, label="actionable_lesson")
        self.failure_taxonomy = _stable_texts(self.failure_taxonomy, label="failure_taxonomy")
        self.successful_patterns = _stable_texts(self.successful_patterns, label="successful_pattern")
        self.constraint_violations = _stable_texts(self.constraint_violations, label="constraint_violation")
        self.target_components = _stable_texts(self.target_components, label="target_component")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise OptimizationContractError("Reflective feedback confidence must be between 0 and 1")
        self.confidence = float(self.confidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "feedback_id": self.feedback_id,
            "episode_id": self.episode_id,
            "trace_refs": list(self.trace_refs),
            "actionable_lessons": list(self.actionable_lessons),
            "source_fingerprint": self.source_fingerprint,
            "failure_taxonomy": list(self.failure_taxonomy),
            "successful_patterns": list(self.successful_patterns),
            "constraint_violations": list(self.constraint_violations),
            "target_components": list(self.target_components),
            "confidence": self.confidence,
        }


@dataclass
class EvolutionCandidate:
    """A proposal-only candidate with enough context for deterministic replay."""

    candidate_id: str
    artifact_type: str
    target: dict[str, Any]
    payload: dict[str, Any]
    expected_effect: str
    episode_id: str
    replay_context: EvolutionReplayContext
    parent_ids: list[str] = field(default_factory=list)
    strategy_id: str = ""
    strategy_version: str = ""
    generation: int = 0
    evidence_refs: list[str] = field(default_factory=list)
    feedback_refs: list[str] = field(default_factory=list)
    status: str = "generated"
    runtime_effect: str = RUNTIME_EFFECT_NOT_APPLIED
    agent_consumption: str = AGENT_CONSUMPTION_ADVISORY
    schema_version: int = OPTIMIZATION_ARTIFACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self.candidate_id = _required_text(self.candidate_id, label="candidate_id")
        self.artifact_type = _required_text(self.artifact_type, label="artifact_type")
        self.expected_effect = _required_text(self.expected_effect, label="expected_effect")
        self.episode_id = _required_text(self.episode_id, label="episode_id")
        self.target = _json_object(self.target, label="target")
        self.payload = _json_object(self.payload, label="payload")
        if not isinstance(self.replay_context, EvolutionReplayContext):
            raise OptimizationContractError("Optimization artifact requires an EvolutionReplayContext")
        self.strategy_id = _required_text(self.strategy_id or self.replay_context.strategy_id, label="strategy_id")
        self.strategy_version = _required_text(
            self.strategy_version or self.replay_context.strategy_version,
            label="strategy_version",
        )
        if self.strategy_id != self.replay_context.strategy_id or self.strategy_version != self.replay_context.strategy_version:
            raise OptimizationContractError("Candidate strategy must match its replay context")
        if not isinstance(self.generation, int) or self.generation < 0:
            raise OptimizationContractError("Candidate generation must be a non-negative integer")
        if self.runtime_effect != RUNTIME_EFFECT_NOT_APPLIED:
            raise OptimizationContractError("Evolution candidates must keep runtime_effect=not_applied")
        if self.agent_consumption != AGENT_CONSUMPTION_ADVISORY:
            raise OptimizationContractError("Evolution candidates must keep agent_consumption=advisory")
        if self.schema_version != OPTIMIZATION_ARTIFACT_SCHEMA_VERSION:
            raise OptimizationContractError("Unsupported optimization artifact schema version")
        self.parent_ids = _stable_texts(self.parent_ids, label="parent_id")
        self.evidence_refs = _stable_texts(self.evidence_refs, label="evidence_ref")
        self.feedback_refs = _stable_texts(self.feedback_refs, label="feedback_ref")
        self.status = _required_text(self.status, label="status")

    @property
    def artifact_fingerprint(self) -> str:
        canonical = self.to_dict(include_fingerprint=False)
        encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "artifact_type": self.artifact_type,
            "target": _json_copy(self.target, label="target"),
            "payload": _json_copy(self.payload, label="payload"),
            "expected_effect": self.expected_effect,
            "episode_id": self.episode_id,
            "parent_ids": list(self.parent_ids),
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "generation": self.generation,
            "evidence_refs": list(self.evidence_refs),
            "feedback_refs": list(self.feedback_refs),
            "status": self.status,
            "runtime_effect": self.runtime_effect,
            "agent_consumption": self.agent_consumption,
            "replay_context": self.replay_context.to_dict(),
        }
        if include_fingerprint:
            payload["artifact_fingerprint"] = self.artifact_fingerprint
        return payload

    def to_candidate_improvement(self) -> CandidateImprovement:
        """Project a new candidate onto the Gym v1 adapter contract."""

        return CandidateImprovement(
            improvement_id=self.candidate_id,
            improvement_type=self.artifact_type,
            target=_json_copy(self.target, label="target"),
            expected_effect=self.expected_effect,
            payload=_json_copy(self.payload, label="payload"),
        )


def candidate_from_improvement(
    improvement: CandidateImprovement,
    *,
    episode_id: str,
    replay_context: EvolutionReplayContext,
    evidence_refs: list[str] | None = None,
    feedback_refs: list[str] | None = None,
    parent_ids: list[str] | None = None,
    generation: int = 0,
) -> EvolutionCandidate:
    """Adapt the established Gym v1 candidate shape without changing execution."""

    if not isinstance(improvement, CandidateImprovement):
        raise OptimizationContractError("candidate_from_improvement requires CandidateImprovement")
    return EvolutionCandidate(
        candidate_id=improvement.improvement_id,
        artifact_type=improvement.improvement_type,
        target=improvement.target,
        payload=improvement.payload,
        expected_effect=improvement.expected_effect,
        episode_id=episode_id,
        replay_context=replay_context,
        parent_ids=parent_ids or [],
        strategy_id=replay_context.strategy_id,
        strategy_version=replay_context.strategy_version,
        generation=generation,
        evidence_refs=evidence_refs or [],
        feedback_refs=feedback_refs or [],
    )


__all__ = [
    "AGENT_CONSUMPTION_ADVISORY",
    "OPTIMIZATION_ARTIFACT_SCHEMA_VERSION",
    "RUNTIME_EFFECT_NOT_APPLIED",
    "EvolutionCandidate",
    "EvolutionReplayContext",
    "OptimizationContractError",
    "ReflectiveFeedback",
    "candidate_from_improvement",
]
