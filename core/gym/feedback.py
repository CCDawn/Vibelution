# -*- coding: utf-8 -*-
"""Deterministic, bounded reflective feedback derived from Gym evidence."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Sequence

from .models import Attempt, Trace
from .optimization_models import OptimizationContractError, ReflectiveFeedback


_ENVIRONMENT_MARKERS = ("environment", "workspace_unavailable")
_TRANSPORT_MARKERS = ("transport", "provider", "network", "server_error", "timeout")
_EVENT_MARKER_KEYS = ("type", "status", "category", "failure_class", "reason_code")
_VALIDATION_EVIDENCE_KEYS = ("passed", "failed", "requirements_met", "environment_unavailable")


def build_reflective_feedback(
    *,
    episode_id: str,
    attempts: Sequence[Attempt],
    traces: Sequence[Trace],
    feedback_id: str | None = None,
) -> ReflectiveFeedback:
    """Summarize observed Gym outcomes without exposing trace bodies or mutating an Agent."""

    if not str(episode_id or "").strip():
        raise OptimizationContractError("Reflective feedback requires episode_id")
    if not attempts:
        raise OptimizationContractError("Reflective feedback requires at least one attempt")

    traces_by_id: dict[str, Trace] = {}
    for trace in traces:
        if trace.trace_id in traces_by_id:
            raise OptimizationContractError(f"Reflective feedback has duplicate trace: {trace.trace_id}")
        traces_by_id[trace.trace_id] = trace

    ordered_attempts = sorted(attempts, key=lambda item: (item.attempt_id, item.trace_id))
    trace_refs: list[str] = []
    failure_taxonomy: list[str] = []
    actionable_lessons: list[str] = []
    successful_patterns: list[str] = []
    constraint_violations: list[str] = []
    target_components: list[str] = []
    fingerprint_records: list[dict[str, Any]] = []
    external_evidence = False

    for attempt in ordered_attempts:
        if "holdout" in attempt.dataset_splits:
            raise OptimizationContractError("Frozen holdout evidence cannot enter reflective feedback")
        trace = traces_by_id.get(attempt.trace_id)
        if trace is None:
            raise OptimizationContractError(f"Reflective feedback missing trace: {attempt.trace_id}")
        if trace.case_id != attempt.case_id:
            raise OptimizationContractError(f"Reflective feedback trace case mismatch: {attempt.trace_id}")

        trace_ref = _trace_ref(trace)
        trace_refs.append(trace_ref)
        external_kind = _external_failure_kind(attempt, trace)
        if external_kind:
            external_evidence = True
            failure_taxonomy.append(external_kind)
        else:
            _add_agent_findings(
                attempt,
                failure_taxonomy=failure_taxonomy,
                actionable_lessons=actionable_lessons,
                constraint_violations=constraint_violations,
                target_components=target_components,
            )
        if attempt.score.success:
            successful_patterns.append("validated_success")
        fingerprint_records.append(_fingerprint_record(attempt, trace, trace_ref))

    source_fingerprint = _fingerprint(episode_id=episode_id, records=fingerprint_records)
    if feedback_id is None:
        feedback_id = f"feedback:{episode_id}:{source_fingerprint[:12]}"
    confidence = _confidence(
        external_evidence=external_evidence,
        actionable_lessons=actionable_lessons,
        successful_patterns=successful_patterns,
    )
    return ReflectiveFeedback(
        feedback_id=feedback_id,
        episode_id=episode_id,
        trace_refs=trace_refs,
        actionable_lessons=actionable_lessons,
        source_fingerprint=source_fingerprint,
        failure_taxonomy=failure_taxonomy,
        successful_patterns=successful_patterns,
        constraint_violations=constraint_violations,
        target_components=target_components,
        confidence=confidence,
    )


def _trace_ref(trace: Trace) -> str:
    for key in ("artifact_ref", "report_path", "path"):
        value = trace.artifacts.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"trace:{trace.trace_id}"


def _external_failure_kind(attempt: Attempt, trace: Trace) -> str | None:
    validation = attempt.score.validation if isinstance(attempt.score.validation, dict) else {}
    markers = _event_markers(trace)
    if bool(validation.get("environment_unavailable")) or any(
        marker in value for marker in _ENVIRONMENT_MARKERS for value in markers
    ):
        return "environment_unavailable"
    if any(marker in value for marker in _TRANSPORT_MARKERS for value in markers):
        return "transport_unavailable"
    return None


def _add_agent_findings(
    attempt: Attempt,
    *,
    failure_taxonomy: list[str],
    actionable_lessons: list[str],
    constraint_violations: list[str],
    target_components: list[str],
) -> None:
    validation = attempt.score.validation if isinstance(attempt.score.validation, dict) else {}
    validation_failed = (not attempt.score.success) or int(validation.get("failed") or 0) > 0
    if validation_failed:
        failure_taxonomy.append("validation_failure")
        actionable_lessons.append("Reproduce the failed validation before proposing a candidate mutation.")
        constraint_violations.append("validation_failed")
        target_components.append("validation_contract")
    if attempt.score.tool_errors > 0:
        failure_taxonomy.append("tool_error")
        actionable_lessons.append("Tighten the Agent tool policy around the observed tool-error path.")
        target_components.append("agent_tool_policy")
    if attempt.score.regression_risk > 0:
        failure_taxonomy.append("regression_risk")
        actionable_lessons.append("Preserve the baseline path while addressing the observed regression risk.")
        constraint_violations.append("regression_risk")
        target_components.append("agent_execution_policy")
    if attempt.score.safety_risk > 0:
        failure_taxonomy.append("safety_risk")
        actionable_lessons.append("Reduce unsafe side effects before proposing a candidate mutation.")
        constraint_violations.append("safety_risk")
        target_components.append("agent_execution_policy")


def _event_markers(trace: Trace) -> list[str]:
    markers: list[str] = []
    for event in trace.events:
        if not isinstance(event, dict):
            continue
        for key in _EVENT_MARKER_KEYS:
            value = event.get(key)
            if isinstance(value, str) and value.strip():
                markers.append(value.strip().lower())
    return sorted(set(markers))


def _fingerprint_record(attempt: Attempt, trace: Trace, trace_ref: str) -> dict[str, Any]:
    validation = attempt.score.validation if isinstance(attempt.score.validation, dict) else {}
    return {
        "attempt_id": attempt.attempt_id,
        "case_id": attempt.case_id,
        "agent_version": attempt.agent_version,
        "trace_id": attempt.trace_id,
        "trace_ref": trace_ref,
        "dataset_splits": sorted(attempt.dataset_splits),
        "score": {
            "success": bool(attempt.score.success),
            "tool_errors": int(attempt.score.tool_errors),
            "regression_risk": float(attempt.score.regression_risk),
            "safety_risk": float(attempt.score.safety_risk),
            "validation": {key: validation[key] for key in _VALIDATION_EVIDENCE_KEYS if key in validation},
        },
        "event_markers": _event_markers(trace),
    }


def _fingerprint(*, episode_id: str, records: list[dict[str, Any]]) -> str:
    canonical = {"episode_id": episode_id, "records": records}
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _confidence(*, external_evidence: bool, actionable_lessons: list[str], successful_patterns: list[str]) -> float:
    if external_evidence:
        return 0.7
    if actionable_lessons:
        return 0.9
    if successful_patterns:
        return 0.8
    return 0.5


__all__ = ["build_reflective_feedback"]
