"""Server-owned WorkflowRun authority for hypothesis meeting model receipts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID


class MeetingReceiptAuthorityError(RuntimeError):
    """The server cannot bind a meeting invocation to exactly one formal run."""


_TERMINAL_RUN_STATUSES = frozenset({"succeeded", "failed", "cancelled", "archived"})
_EXECUTION_INACTIVE_RUN_STATUSES = _TERMINAL_RUN_STATUSES | frozenset(
    {"blocked", "reconciliation_required"}
)


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate blocked problem field: {key}")
        payload[key] = value
    return payload


def _is_exact_hypothesis_first_meeting_block(run: Any) -> bool:
    raw_problem = getattr(run, "blocked_problem_json", None)
    if not isinstance(raw_problem, str) or not raw_problem.strip():
        return False
    try:
        problem = json.loads(
            raw_problem,
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    return isinstance(problem, Mapping) and (
        problem.get("code") == "auto_advance_not_ready"
        and problem.get("detail") == "hypothesis_first_meeting_open"
    )


def _required_text(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise MeetingReceiptAuthorityError(f"{field} is required for meeting receipt authority")
    return normalized


def _policy_sha256(run_input: Mapping[str, Any]) -> str:
    policy = (
        run_input.get("modelRoutingPolicy")
        if isinstance(run_input.get("modelRoutingPolicy"), Mapping)
        else {}
    )
    digest = str(policy.get("modelPolicySha256") or "").strip().lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise MeetingReceiptAuthorityError(
            "modelPolicySha256 must be a lowercase sha256 for meeting receipt authority"
        )
    return digest


def _expected_model_route(route: Mapping[str, Any]) -> dict[str, str]:
    normalized = {
        "modelRef": str(route.get("modelRef") or "").strip(),
        "providerId": str(route.get("providerId") or "").strip(),
        "modelId": str(route.get("modelId") or "").strip(),
    }
    if (
        not all(normalized.values())
        or normalized["modelRef"].partition("/")[0].casefold()
        != normalized["providerId"].casefold()
    ):
        raise MeetingReceiptAuthorityError("formal meeting effective model route is invalid")
    return normalized


def build_meeting_receipt_authority(
    *,
    team_id: Any,
    question_id: Any,
    workflow_run_id: Any,
    workflow_id: Any,
    workflow_version_id: Any,
    run_input: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the only server-owned authority accepted by meeting execution."""

    normalized_workflow_id = _required_text(workflow_id, "workflowId")
    if normalized_workflow_id != CHALLENGE_CUP_WORKFLOW_ID:
        raise MeetingReceiptAuthorityError("meeting receipt authority requires Challenge Cup workflow")
    return {
        "schemaVersion": 1,
        "authorityKind": "workflow_run",
        "teamId": _required_text(team_id, "teamId"),
        "questionId": _required_text(question_id, "questionId").upper(),
        "workflowRunId": _required_text(workflow_run_id, "workflowRunId"),
        "workflowId": normalized_workflow_id,
        "workflowVersionId": _required_text(workflow_version_id, "workflowVersionId"),
        "modelPolicySha256": _policy_sha256(run_input),
    }


def authority_from_created_run(
    run_input: Mapping[str, Any],
    created: Mapping[str, Any],
) -> dict[str, Any]:
    return build_meeting_receipt_authority(
        team_id=created.get("teamId") or run_input.get("teamId"),
        question_id=created.get("questionId") or run_input.get("questionId"),
        workflow_run_id=created.get("runId"),
        workflow_id=created.get("workflowId"),
        workflow_version_id=created.get("workflowVersionId"),
        run_input=run_input,
    )


def resolve_active_question_authority(
    team_id: str,
    question_id: str,
    workflow_run_id: str = "",
) -> dict[str, Any] | None:
    """Resolve one active formal run without trusting selection/API payload fields."""

    from .formal_write_runtime import (
        FormalWriteRuntimeUnavailable,
        WorkflowMigrationRequired,
        get_write_store,
    )

    normalized_team = _required_text(team_id, "teamId")
    normalized_question = _required_text(question_id, "questionId").upper()
    normalized_workflow_run_id = str(workflow_run_id or "").strip()
    try:
        store = get_write_store()
    except (FormalWriteRuntimeUnavailable, WorkflowMigrationRequired):
        # Hypothesis preparation is also available before a formal run exists.
        # Only a configured Ledger can be receipt authority; never fall back to
        # client payloads or the legacy JSON run store.
        return None
    if normalized_workflow_run_id:
        selected = store.get_run(normalized_workflow_run_id)
        if selected is None:
            raise MeetingReceiptAuthorityError(
                "workflowRunId does not resolve to a canonical Ledger run"
            )
        candidate_runs = [selected]
    else:
        candidate_runs = store.list_runs_for_team(
            normalized_team,
            CHALLENGE_CUP_WORKFLOW_ID,
        )

    matches: list[tuple[Any, dict[str, Any]]] = []
    for run in candidate_runs:
        if str(getattr(run, "team_id", "") or "").strip() != normalized_team:
            if normalized_workflow_run_id:
                raise MeetingReceiptAuthorityError(
                    "workflowRunId does not belong to this team"
                )
            continue
        if (
            str(getattr(run, "workflow_id", "") or "").strip()
            != CHALLENGE_CUP_WORKFLOW_ID
        ):
            if normalized_workflow_run_id:
                raise MeetingReceiptAuthorityError(
                    "workflowRunId is not a Challenge Cup workflow run"
                )
            continue
        if str(getattr(run, "status", "") or "").strip().lower() in _TERMINAL_RUN_STATUSES:
            if normalized_workflow_run_id:
                raise MeetingReceiptAuthorityError(
                    "workflowRunId is no longer active"
                )
            continue
        try:
            snapshot = json.loads(str(getattr(run, "input_snapshot_json", "") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(snapshot, dict):
            continue
        run_question = str(
            snapshot.get("questionId") or getattr(run, "question_id", "") or ""
        ).strip().upper()
        objective = (
            snapshot.get("researchObjectiveContract")
            if isinstance(snapshot.get("researchObjectiveContract"), Mapping)
            else {}
        )
        if run_question != normalized_question:
            if normalized_workflow_run_id:
                raise MeetingReceiptAuthorityError(
                    "workflowRunId does not belong to this question"
                )
            continue
        if objective.get("hypothesisFirst") is not True:
            if normalized_workflow_run_id:
                raise MeetingReceiptAuthorityError(
                    "workflowRunId is not hypothesis-first"
                )
            continue
        matches.append((run, snapshot))
    if not matches:
        if normalized_workflow_run_id:
            raise MeetingReceiptAuthorityError(
                "workflowRunId has no valid meeting receipt authority"
            )
        return None
    if len(matches) != 1:
        raise MeetingReceiptAuthorityError(
            "multiple active formal runs match this question; meeting receipt authority is ambiguous"
        )
    run, snapshot = matches[0]
    return build_meeting_receipt_authority(
        team_id=normalized_team,
        question_id=normalized_question,
        workflow_run_id=getattr(run, "run_id", ""),
        workflow_id=getattr(run, "workflow_id", ""),
        workflow_version_id=getattr(run, "workflow_version_id", ""),
        run_input=snapshot,
    )


def workflow_run_stop_reason(authority: Mapping[str, Any] | None) -> str:
    """Read the canonical Ledger run before formal meeting fan-out continues."""

    if not isinstance(authority, Mapping):
        return ""
    run_id = str(authority.get("workflowRunId") or "").strip()
    if not run_id:
        return "challenge_workflow_run_missing"
    from .formal_write_runtime import get_write_store

    try:
        run = get_write_store().get_run(run_id)
    except Exception:
        # Formal execution cannot safely continue when its server-owned run
        # authority is unreadable.  Do not fall back to legacy JSON state.
        return "challenge_workflow_run_status_unavailable"
    if run is None:
        return "challenge_workflow_run_missing"
    status = str(getattr(run, "status", "") or "").strip().lower()
    if status == "blocked" and _is_exact_hypothesis_first_meeting_block(run):
        # ``hypothesis_first_meeting_open`` is the RESOLVE_HUMAN readiness
        # gate that this formal candidate-generation meeting is meant to
        # resolve.  Every other blocked shape remains fail-closed below.
        return ""
    return (
        f"challenge_workflow_run_{status}"
        if status in _EXECUTION_INACTIVE_RUN_STATUSES
        else ""
    )


def build_speaker_receipt_context(
    participant: Mapping[str, Any],
    context: Mapping[str, Any],
    *,
    session_id: str,
    turn_identity: str,
    expected_model_route: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Bind one real meeting speaker turn to an explicit package stage."""

    authority = context.get("_modelInvocationReceiptAuthority")
    if not isinstance(authority, Mapping):
        return None
    stage_mapping = {
        "hypothesis_candidate_generation": ("generation", "candidate"),
        "hypothesis_review": ("review", "review"),
    }
    meeting_type = str(context.get("meetingType") or "").strip().lower()
    mapped = stage_mapping.get(meeting_type)
    if mapped is None:
        raise MeetingReceiptAuthorityError(
            "formal model invocation receipt authority is not valid for this meeting type"
        )
    question_stage, outcome_kind = mapped
    outcome_kinds = [outcome_kind]
    if (
        meeting_type == "hypothesis_candidate_generation"
        and str(context.get("candidateAuthority") or "").strip().lower()
        == "formal_grounded_candidate"
    ):
        # This call is the actual R0 -> R1 evidence-grounded rewrite, not a
        # second projection of the exploratory candidate output.
        outcome_kinds.append("revision")
    team_id = str(authority.get("teamId") or "").strip()
    question_id = str(authority.get("questionId") or "").strip().upper()
    workflow_run_id = str(authority.get("workflowRunId") or "").strip()
    workflow_id = str(authority.get("workflowId") or "").strip()
    workflow_version_id = str(authority.get("workflowVersionId") or "").strip()
    policy_sha256 = str(authority.get("modelPolicySha256") or "").strip().lower()
    if (
        authority.get("schemaVersion") != 1
        or str(authority.get("authorityKind") or "").strip() != "workflow_run"
        or team_id != str(context.get("teamId") or "").strip()
        or question_id != str(context.get("questionId") or "").strip().upper()
        or any(
            not value
            for value in (
                question_id,
                workflow_run_id,
                workflow_id,
                workflow_version_id,
                session_id,
                turn_identity,
            )
        )
        or len(policy_sha256) != 64
        or any(char not in "0123456789abcdef" for char in policy_sha256)
    ):
        raise MeetingReceiptAuthorityError("formal meeting receipt authority is invalid")
    route = expected_model_route if isinstance(expected_model_route, Mapping) else {}
    expected_route = _expected_model_route(route)
    meeting_round_id = str(context.get("meetingRoundId") or "").strip()
    chat_room_round_id = str(context.get("roundId") or "").strip()
    participant_id = str(
        participant.get("participantId")
        or participant.get("agentId")
        or session_id
    ).strip()
    if not meeting_round_id or not chat_room_round_id or not participant_id:
        raise MeetingReceiptAuthorityError("formal meeting speaker identity is incomplete")
    formal_node_run_id = (
        f"meeting:{meeting_round_id}:{chat_room_round_id}:{participant_id}"
    )
    task_id = f"meeting-speaker:{meeting_round_id}:{chat_room_round_id}:{participant_id}"
    from core.research.workflow.contracts.question_stage_binding import (
        QuestionStageBinding,
    )

    stage_binding = QuestionStageBinding(
        question_stage=question_stage,
        question_id=question_id,
        question_run_id=workflow_run_id,
        workflow_run_id=workflow_run_id,
        workflow_id=workflow_id,
        workflow_version_id=workflow_version_id,
        # Both discussions are explicit sub-runs of formal hypothesis design.
        formal_node_id="hypothesis_design",
        formal_node_run_id=formal_node_run_id,
        formal_node_attempt=1,
        session_id=session_id,
        task_id=task_id,
        turn_id=turn_identity,
    )
    return {
        "receiptRunAuthority": "workflow_run",
        "receiptRunId": workflow_run_id,
        "modelPolicySha256": policy_sha256,
        "questionStageBinding": stage_binding.to_dict(),
        "outcomeKinds": outcome_kinds,
        "expectedModelRoute": expected_route,
        "evidenceLocator": {
            "kind": "challenge_model_invocation_receipt_registry",
            "executionKind": "chat_room_meeting",
            "meetingRoundId": meeting_round_id,
            "chatRoomRoundId": chat_room_round_id,
            "participantId": participant_id,
        },
    }


def build_review_step_receipt_context(
    context: Mapping[str, Any],
    *,
    review_step: str,
    identity_parts: Sequence[Any],
    session_id: str,
    expected_model_route: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Bind one formal review step call to the server-owned WorkflowRun."""

    authority = context.get("_modelInvocationReceiptAuthority")
    if not isinstance(authority, Mapping):
        return None
    team_id = str(authority.get("teamId") or "").strip()
    question_id = str(authority.get("questionId") or "").strip().upper()
    workflow_run_id = str(authority.get("workflowRunId") or "").strip()
    workflow_id = str(authority.get("workflowId") or "").strip()
    workflow_version_id = str(authority.get("workflowVersionId") or "").strip()
    policy_sha256 = str(authority.get("modelPolicySha256") or "").strip().lower()
    context_question = str(
        context.get("questionId") or context.get("question") or ""
    ).strip().upper()
    normalized_session_id = str(session_id or "").strip()
    context_id = str(context.get("contextId") or "").strip()
    normalized_step = str(review_step or "").strip().lower()
    parts = [str(item or "").strip() for item in identity_parts]
    if (
        authority.get("schemaVersion") != 1
        or str(authority.get("authorityKind") or "").strip() != "workflow_run"
        or workflow_id != CHALLENGE_CUP_WORKFLOW_ID
        or team_id != str(context.get("teamId") or "").strip()
        or question_id != context_question
        or any(
            not value
            for value in (
                team_id,
                question_id,
                workflow_run_id,
                workflow_version_id,
                normalized_session_id,
                context_id,
            )
        )
        or len(policy_sha256) != 64
        or any(char not in "0123456789abcdef" for char in policy_sha256)
    ):
        raise MeetingReceiptAuthorityError("formal review receipt authority is invalid")
    if normalized_step not in {
        "reflection",
        "pairwise",
        "pareto",
        "metareview",
        "revision",
    }:
        raise MeetingReceiptAuthorityError("formal review receipt step is invalid")
    if not parts or any(not part for part in parts):
        raise MeetingReceiptAuthorityError("formal review receipt identity is incomplete")
    route = _expected_model_route(expected_model_route)
    identity_material = json.dumps(
        {
            "workflowRunId": workflow_run_id,
            "contextId": context_id,
            "step": normalized_step,
            "identityParts": parts,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    identity_hash = hashlib.sha256(identity_material.encode("utf-8")).hexdigest()[:24]
    turn_id = f"hypothesis-review:{normalized_step}:{identity_hash}"
    invocation_id = f"hypothesis-review-invocation:{identity_hash}"
    formal_node_run_id = f"hypothesis-review:{workflow_run_id}:{identity_hash}"
    task_id = f"hypothesis-review-step:{normalized_step}:{identity_hash}"
    from core.research.workflow.contracts.question_stage_binding import (
        QuestionStageBinding,
    )

    stage_binding = QuestionStageBinding(
        question_stage="review",
        question_id=question_id,
        question_run_id=workflow_run_id,
        workflow_run_id=workflow_run_id,
        workflow_id=workflow_id,
        workflow_version_id=workflow_version_id,
        formal_node_id="hypothesis_design",
        formal_node_run_id=formal_node_run_id,
        formal_node_attempt=1,
        session_id=normalized_session_id,
        task_id=task_id,
        turn_id=turn_id,
    )
    return {
        "receiptRunAuthority": "workflow_run",
        "receiptRunId": workflow_run_id,
        "modelPolicySha256": policy_sha256,
        "questionStageBinding": stage_binding.to_dict(),
        "outcomeKinds": (
            ["review", "revision"]
            if normalized_step == "revision"
            else ["review"]
        ),
        "expectedModelRoute": route,
        "invocationId": invocation_id,
        "evidenceLocator": {
            "kind": "hypothesis_review_step",
            "executionKind": "hypothesis_review_executor",
            "reviewContextId": context_id,
            "reviewStep": normalized_step,
            "identityParts": parts,
        },
    }


def register_speaker_receipts(
    *,
    project_root: Path,
    team_id: str,
    question_id: str,
    workflow_run_id: str,
    session_id: str,
    turn_identity: str,
    receipts: Sequence[Mapping[str, Any]] = (),
) -> None:
    """Register current receipts without making conversation state an audit store.

    Formal meeting turns bypass the session UI stream, so their caller passes
    captured canonical receipts directly. The existing Challenge Cup registry
    is the current read authority. Journal readback remains only for historical
    turns written before receipt isolation.
    """

    from .model_invocation_receipt_registry import (
        question_model_invocation_receipts,
        register_question_model_invocation_receipts,
    )

    selected = [dict(item) for item in receipts if isinstance(item, Mapping)]
    if not selected:
        selected = question_model_invocation_receipts(
            team_id,
            question_id=question_id,
            workflow_run_id=workflow_run_id,
            session_id=session_id,
            turn_id=turn_identity,
        )
    if not selected:
        from core.chat.conversation_ledger import load_conversation_events
        from core.chat.turn_journal import read_model_invocation_receipts_from_events

        selected = read_model_invocation_receipts_from_events(
            load_conversation_events(project_root, session_id),
            turn_id=turn_identity,
        )
    if not selected:
        raise MeetingReceiptAuthorityError(
            "formal meeting model call completed without a verifiable invocation receipt"
        )
    refs = register_question_model_invocation_receipts(
        team_id,
        question_id=question_id,
        workflow_run_id=workflow_run_id,
        receipts=selected,
    )
    if not refs:
        raise MeetingReceiptAuthorityError(
            "formal meeting model invocation receipts were not registered"
        )


__all__ = [
    "MeetingReceiptAuthorityError",
    "authority_from_created_run",
    "build_meeting_receipt_authority",
    "build_review_step_receipt_context",
    "build_speaker_receipt_context",
    "register_speaker_receipts",
    "resolve_active_question_authority",
    "workflow_run_stop_reason",
]
