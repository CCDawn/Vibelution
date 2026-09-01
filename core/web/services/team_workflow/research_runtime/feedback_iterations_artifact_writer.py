"""Canonical writer for Challenge Cup feedback-iteration authority.

``feedback_iterations`` is a workflow-system artifact, not a projection of a
result package.  This module accepts only an explicit feedback record and an
explicit revision record.  A decision reason, score, summary, model receipt,
or child-run placeholder is deliberately not sufficient evidence.

The artifact store and read-back registry own registration of the kind.  This
writer only uses their existing append-only writer so the registration can be
landed independently without creating a second persistence path.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from .artifact_readback_registry import build_canonical_ref
from .human_gate_artifacts import canonical_sha256
from .workflow_artifact_store import (
    list_workflow_artifacts,
    put_workflow_artifact,
)

FEEDBACK_ITERATIONS_KIND = "feedback_iterations"
SCHEMA_VERSION = 1
REVISION_ENVELOPE_SCHEMA_VERSION = 2
HYPOTHESIS_DESIGN_NODE_ID = "hypothesis_design"
_HYPOTHESIS_REVISION_PHASES = frozenset(
    {"grounded_revision", "review_revision"}
)
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class FeedbackIterationAuthorityError(ValueError):
    """Raised by the strict normalizer for incomplete evidence."""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FeedbackIterationAuthorityError(
            f"feedback iteration {field} must be a non-empty string"
        )
    return value.strip()


def _optional_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FeedbackIterationAuthorityError(
            f"feedback iteration {field} must be an object"
        )
    return dict(value)


def _alias(mapping: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in mapping:
            return mapping[name]
    return None


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or not value:
        raise FeedbackIterationAuthorityError(
            f"feedback iteration {field} must be a non-empty array"
        )
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise FeedbackIterationAuthorityError(
                f"feedback iteration {field} contains an empty value"
            )
        text = item.strip()
        if text not in result:
            result.append(text)
    if not result:
        raise FeedbackIterationAuthorityError(
            f"feedback iteration {field} must be a non-empty array"
        )
    return result


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise FeedbackIterationAuthorityError(
            f"feedback iteration {field} must be a SHA-256 hash"
        )
    normalized = value.strip().removeprefix("sha256:").strip()
    if not _SHA256_RE.fullmatch(normalized):
        raise FeedbackIterationAuthorityError(
            f"feedback iteration {field} must be a SHA-256 hash"
        )
    return normalized.lower()


def _round(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise FeedbackIterationAuthorityError(
            "feedback iteration round must be an integer >= 1"
        )
    return value


def _blocked(*codes: str) -> dict[str, Any]:
    blocker_codes = list(dict.fromkeys(code for code in codes if code))
    if not blocker_codes:
        blocker_codes = ["feedback_iteration_authority_missing"]
    return {
        "status": "blocked",
        "reason": "NEEDS_CONTEXT",
        "blockerCodes": blocker_codes,
        "missingAuthorities": [FEEDBACK_ITERATIONS_KIND],
        "artifact": None,
        "canonicalRef": "",
        "feedbackIteration": None,
    }


def _normalize_inputs(
    *,
    team_id: str,
    workflow_run_id: str,
    node_run_id: str,
    question_id: str,
    iteration_round: Any,
    feedback: Mapping[str, Any],
    revision: Mapping[str, Any],
    source_collection_run_id: str,
    parent_run_id: str,
    child_run_id: str,
    decision_id: str,
    node_id: str,
    revision_phase: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Normalize explicit evidence and build the canonical payload."""

    team = _text(team_id, "teamId")
    workflow = _text(workflow_run_id, "workflowRunId")
    node = _text(node_run_id, "nodeRunId")
    question = _text(question_id, "questionId")
    round_value = _round(iteration_round)
    feedback_map = _mapping(feedback, "feedback")
    revision_map = _mapping(revision, "revision")

    # Feedback is intentionally independent from the iteration decision's
    # free-form ``reason`` field.  That field is a summary, not evidence.
    trigger = _text(
        _alias(feedback_map, "trigger", "feedbackTrigger"),
        "trigger",
    )
    human_feedback = _text(
        _alias(feedback_map, "humanFeedback", "human_feedback"),
        "humanFeedback",
    )
    input_refs = _string_list(
        _alias(feedback_map, "inputRefs", "input_refs"),
        "inputRefs",
    )
    input_hash = _sha256(
        _alias(feedback_map, "inputHash", "inputSha256", "input_hash"),
        "inputHash",
    )

    # Revision evidence must identify the produced canonical output.  A child
    # run id, score, receipt id, or a claimed change without output refs/hash
    # cannot establish that a revision actually happened.
    changes = _string_list(
        _alias(revision_map, "changes", "changeSummary"),
        "changes",
    )
    unresolved = _string_list(
        _alias(revision_map, "unresolvedIssues", "unresolved_issues"),
        "unresolvedIssues",
    )
    output_refs = _string_list(
        _alias(revision_map, "outputRefs", "output_refs"),
        "outputRefs",
    )
    output_hash = _sha256(
        _alias(revision_map, "outputHash", "outputSha256", "output_hash"),
        "outputHash",
    )
    status = _optional_text(_alias(revision_map, "status", "revisionStatus")).lower()
    if status in {"", "revised", "completed", "accepted"}:
        pass
    elif status in {"blocked", "failed", "pending", "not_started"}:
        raise FeedbackIterationAuthorityError(
            "feedback iteration revision evidence is not completed"
        )
    else:
        raise FeedbackIterationAuthorityError(
            "feedback iteration revision status is unsupported"
        )
    if _alias(revision_map, "actual", "actualRevision") is False:
        raise FeedbackIterationAuthorityError(
            "feedback iteration revision evidence is marked non-actual"
        )

    source = _optional_text(source_collection_run_id) or workflow
    parent = _optional_text(parent_run_id)
    child = _optional_text(child_run_id)
    decision = _optional_text(decision_id)
    node_identity = _text(node_id, "nodeId")
    phase = _optional_text(revision_phase).lower()
    if node_identity == HYPOTHESIS_DESIGN_NODE_ID:
        if phase not in _HYPOTHESIS_REVISION_PHASES:
            raise FeedbackIterationAuthorityError(
                "feedback iteration hypothesis revision phase is unsupported"
            )
    elif phase:
        raise FeedbackIterationAuthorityError(
            "feedback iteration revision phase is only supported for hypothesis_design"
        )
    row = {
        "round": round_value,
        "trigger": trigger,
        "input_refs": input_refs,
        "changes": changes,
        "unresolved_issues": unresolved,
        "human_feedback": human_feedback,
    }
    payload: dict[str, Any] = {
        "schemaVersion": (
            REVISION_ENVELOPE_SCHEMA_VERSION
            if node_identity == HYPOTHESIS_DESIGN_NODE_ID
            else SCHEMA_VERSION
        ),
        "artifactKind": FEEDBACK_ITERATIONS_KIND,
        "teamId": team,
        "workflowRunId": workflow,
        "sourceCollectionRunId": source,
        "nodeId": node_identity,
        "nodeRunId": node,
        "questionId": question,
        "iterationRound": round_value,
        "inputRefs": input_refs,
        "inputHash": input_hash,
        "outputRefs": output_refs,
        "outputHash": output_hash,
        "feedbackIteration": row,
        "feedbackIterations": [row],
    }
    if phase:
        payload["revisionPhase"] = phase
        payload["revisionEnvelope"] = {
            "phase": phase,
            "parentOutput": {"refs": input_refs, "sha256": input_hash},
            "childOutput": {"refs": output_refs, "sha256": output_hash},
        }
    if parent:
        payload["parentRunId"] = parent
    if child:
        payload["childRunId"] = child
    if decision:
        payload["decisionId"] = decision
    return payload, row


def validate_feedback_iteration(
    *,
    team_id: str,
    workflow_run_id: str,
    node_run_id: str,
    question_id: str,
    iteration_round: Any,
    feedback: Mapping[str, Any],
    revision: Mapping[str, Any],
    source_collection_run_id: str = "",
    parent_run_id: str = "",
    child_run_id: str = "",
    decision_id: str = "",
    node_id: str = "iteration_decision",
    revision_phase: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return strict canonical payload and v2-compatible row."""

    return _normalize_inputs(
        team_id=team_id,
        workflow_run_id=workflow_run_id,
        node_run_id=node_run_id,
        question_id=question_id,
        iteration_round=iteration_round,
        feedback=feedback,
        revision=revision,
        source_collection_run_id=source_collection_run_id,
        parent_run_id=parent_run_id,
        child_run_id=child_run_id,
        decision_id=decision_id,
        node_id=node_id,
        revision_phase=revision_phase,
    )


def _artifact_round(item: Mapping[str, Any]) -> tuple[str, int] | None:
    payload = item.get("payload")
    if not isinstance(payload, Mapping):
        return None
    question = _optional_text(payload.get("questionId") or payload.get("question_id"))
    raw_round = payload.get("iterationRound", payload.get("round"))
    if isinstance(raw_round, bool) or not isinstance(raw_round, int) or raw_round < 1:
        return None
    return question, raw_round


def _artifact_descriptor(
    *,
    team_id: str,
    workflow_run_id: str,
    source_collection_run_id: str,
    payload: Mapping[str, Any],
    record: Mapping[str, Any],
) -> dict[str, Any]:
    envelope = {
        "teamId": team_id,
        "kind": FEEDBACK_ITERATIONS_KIND,
        "workflowRunId": workflow_run_id,
        "sourceCollectionRunId": source_collection_run_id,
        "payload": dict(payload),
    }
    canonical_hash = canonical_sha256(envelope)
    return {
        "recordId": _optional_text(record.get("recordId")),
        "kind": FEEDBACK_ITERATIONS_KIND,
        "workflowRunId": workflow_run_id,
        "sourceCollectionRunId": source_collection_run_id,
        "contentHash": _optional_text(record.get("contentHash")),
        "canonicalHash": canonical_hash,
        "canonicalRef": build_canonical_ref(
            kind=FEEDBACK_ITERATIONS_KIND,
            team_id=team_id,
            authority_run_id=source_collection_run_id,
            content_hash=canonical_hash,
        ),
    }


def write_feedback_iterations_artifact(
    *,
    team_id: str,
    workflow_run_id: str,
    node_run_id: str,
    question_id: str,
    iteration_round: Any,
    feedback: Mapping[str, Any],
    revision: Mapping[str, Any],
    source_collection_run_id: str = "",
    parent_run_id: str = "",
    child_run_id: str = "",
    decision_id: str = "",
    node_id: str = "iteration_decision",
    revision_phase: str = "",
) -> dict[str, Any]:
    """Persist one feedback iteration, or return a fail-closed blocker.

    The deterministic identity is scoped to the server-owned run/node/question
    and round.  Replaying the same evidence returns the existing store record;
    replaying a different evidence set for that round is rejected as a
    conflict rather than appended as a second iteration.
    """

    try:
        payload, row = validate_feedback_iteration(
            team_id=team_id,
            workflow_run_id=workflow_run_id,
            node_run_id=node_run_id,
            question_id=question_id,
            iteration_round=iteration_round,
            feedback=feedback,
            revision=revision,
            source_collection_run_id=source_collection_run_id,
            parent_run_id=parent_run_id,
            child_run_id=child_run_id,
            decision_id=decision_id,
            node_id=node_id,
            revision_phase=revision_phase,
        )
    except FeedbackIterationAuthorityError as exc:
        code = "feedback_iteration_evidence_invalid"
        if "round" in str(exc):
            code = "feedback_iteration_round_invalid"
        return _blocked(code)

    team = payload["teamId"]
    workflow = payload["workflowRunId"]
    source = payload["sourceCollectionRunId"]
    question = payload["questionId"]
    node = payload["nodeRunId"]
    round_value = payload["iterationRound"]
    try:
        existing = list_workflow_artifacts(
            team,
            kind=FEEDBACK_ITERATIONS_KIND,
            workflow_run_id=workflow,
        )
    except Exception:
        return _blocked("feedback_iteration_readback_unavailable")

    scoped_rows: list[tuple[int, Mapping[str, Any]]] = []
    for item in existing:
        parsed = _artifact_round(item)
        if parsed is None:
            return _blocked("feedback_iteration_existing_artifact_invalid")
        item_question, item_round = parsed
        item_source = _optional_text(item.get("sourceCollectionRunId"))
        if item_source and item_source != source:
            return _blocked("feedback_iteration_source_scope_conflict")
        if item_question and item_question != question:
            return _blocked("feedback_iteration_question_scope_conflict")
        scoped_rows.append((item_round, item))
    rounds = [item_round for item_round, _ in scoped_rows]
    if len(rounds) != len(set(rounds)):
        return _blocked("feedback_iteration_round_not_unique")
    if rounds != sorted(rounds):
        return _blocked("feedback_iteration_round_not_strictly_increasing")
    if rounds and round_value <= rounds[-1]:
        identity_seed = {
            "teamId": team,
            "workflowRunId": workflow,
            "nodeRunId": node,
            "questionId": question,
            "round": round_value,
        }
        expected_identity = f"feedback_iterations:{canonical_sha256(identity_seed)[:24]}"
        exact = next(
            (
                item
                for item_round, item in scoped_rows
                if item_round == round_value
                and _optional_text(item.get("recordId")) == expected_identity
            ),
            None,
        )
        if exact is None:
            return _blocked("feedback_iteration_round_conflict")
        if _optional_text(exact.get("contentHash")).lower() != canonical_sha256(
            payload
        ):
            return _blocked("feedback_iteration_round_conflict")

    identity_seed = {
        "teamId": team,
        "workflowRunId": workflow,
        "nodeRunId": node,
        "questionId": question,
        "round": round_value,
    }
    artifact_identity = f"feedback_iterations:{canonical_sha256(identity_seed)[:24]}"
    try:
        record = put_workflow_artifact(
            team,
            kind=FEEDBACK_ITERATIONS_KIND,
            workflow_run_id=workflow,
            source_collection_run_id=source,
            artifact_identity=artifact_identity,
            payload=payload,
        )
    except ValueError as exc:
        # The v2 integration lane registers this kind in the shared store.  If
        # this writer is deployed before that registration, remain blocked and
        # never silently write to a parallel store.
        if "supported kind" in str(exc):
            return _blocked("feedback_iteration_kind_unregistered")
        raise
    descriptor = _artifact_descriptor(
        team_id=team,
        workflow_run_id=workflow,
        source_collection_run_id=source,
        payload=payload,
        record=record,
    )
    return {
        "status": "recorded",
        "reason": "canonical_feedback_iteration_written",
        "artifact": descriptor,
        "canonicalRef": descriptor["canonicalRef"],
        "feedbackIteration": row,
        "inputRefs": list(payload["inputRefs"]),
        "inputHash": payload["inputHash"],
        "outputRefs": list(payload["outputRefs"]),
        "outputHash": payload["outputHash"],
    }


def _find_iteration_node_run(
    parent: Mapping[str, Any], decision: Mapping[str, Any]
) -> str:
    candidates = [
        item
        for item in parent.get("nodeRuns") or []
        if isinstance(item, Mapping)
        and _optional_text(item.get("nodeId")) == "iteration_decision"
    ]
    if not candidates:
        return ""
    latest = max(candidates, key=lambda item: int(item.get("attempt") or 0))
    expected = _optional_text(latest.get("nodeRunId"))
    supplied = _optional_text(decision.get("nodeRunId"))
    if not expected or (supplied and supplied != expected):
        return ""
    return expected


def _mapping_from_aliases(mapping: Mapping[str, Any], *names: str) -> dict[str, Any]:
    for name in names:
        value = mapping.get(name)
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def record_feedback_iteration_from_fork(
    *,
    parent: Mapping[str, Any],
    decision: Mapping[str, Any],
    child: Mapping[str, Any],
) -> dict[str, Any]:
    """Bridge a revision fork using only explicit server-bound evidence."""

    if not isinstance(parent, Mapping) or not isinstance(decision, Mapping):
        return _blocked("feedback_iteration_fork_context_invalid")
    if _optional_text(decision.get("decisionKind")) != "revise_protocol":
        return _blocked("feedback_iteration_requires_revise_protocol")
    node_run_id = _find_iteration_node_run(parent, decision)
    if not node_run_id:
        return _blocked("feedback_iteration_node_scope_missing")

    feedback = _mapping_from_aliases(
        decision,
        "feedback",
        "feedbackEvidence",
        "humanFeedbackEvidence",
    )
    revision = _mapping_from_aliases(
        decision,
        "revision",
        "revisionEvidence",
        "revisionOutputEvidence",
    )
    if not feedback or not revision:
        return _blocked("feedback_iteration_actual_evidence_missing")

    raw_round = _alias(decision, "iterationRound", "round", "iterationAttempt")
    source = _optional_text(parent.get("sourceCollectionRunId"))
    if not source:
        snapshot = parent.get("inputSnapshot")
        if isinstance(snapshot, Mapping):
            source = _optional_text(
                snapshot.get("sourceCollectionRunId")
                or snapshot.get("source_collection_run_id")
            )
    return write_feedback_iterations_artifact(
        team_id=_optional_text(parent.get("teamId")),
        workflow_run_id=_optional_text(parent.get("runId")),
        node_run_id=node_run_id,
        question_id=_optional_text(parent.get("questionId")),
        iteration_round=raw_round,
        feedback=feedback,
        revision=revision,
        source_collection_run_id=source,
        parent_run_id=_optional_text(parent.get("runId")),
        child_run_id=_optional_text(child.get("runId"))
        if isinstance(child, Mapping)
        else "",
        decision_id=_optional_text(decision.get("decisionId")),
    )


# Names used by the other canonical artifact writers and by the v2 producer.
record_feedback_iterations_artifact = write_feedback_iterations_artifact
materialize_feedback_iteration_authority = write_feedback_iterations_artifact


__all__ = [
    "FEEDBACK_ITERATIONS_KIND",
    "FeedbackIterationAuthorityError",
    "materialize_feedback_iteration_authority",
    "record_feedback_iteration_from_fork",
    "record_feedback_iterations_artifact",
    "validate_feedback_iteration",
    "write_feedback_iterations_artifact",
]
