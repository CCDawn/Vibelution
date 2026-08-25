"""Server-owned WorkflowRun authority for hypothesis meeting model receipts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID


class MeetingReceiptAuthorityError(RuntimeError):
    """The server cannot bind a meeting invocation to exactly one formal run."""


_TERMINAL_RUN_STATUSES = frozenset({"succeeded", "failed", "cancelled", "archived"})


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
) -> dict[str, Any] | None:
    """Resolve one active formal run without trusting selection/API payload fields."""

    from .formal_write_runtime import (
        FormalWriteRuntimeUnavailable,
        WorkflowMigrationRequired,
        get_write_store,
    )

    normalized_team = _required_text(team_id, "teamId")
    normalized_question = _required_text(question_id, "questionId").upper()
    try:
        store = get_write_store()
    except (FormalWriteRuntimeUnavailable, WorkflowMigrationRequired):
        # Hypothesis preparation is also available before a formal run exists.
        # Only a configured Ledger can be receipt authority; never fall back to
        # client payloads or the legacy JSON run store.
        return None
    matches: list[tuple[Any, dict[str, Any]]] = []
    for run in store.list_runs_for_team(
        normalized_team,
        CHALLENGE_CUP_WORKFLOW_ID,
    ):
        if str(getattr(run, "status", "") or "").strip().lower() in _TERMINAL_RUN_STATUSES:
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
        if run_question == normalized_question and objective.get("hypothesisFirst") is True:
            matches.append((run, snapshot))
    if not matches:
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
    expected_route = {
        "modelRef": str(route.get("modelRef") or "").strip(),
        "providerId": str(route.get("providerId") or "").strip(),
        "modelId": str(route.get("modelId") or "").strip(),
    }
    if (
        not all(expected_route.values())
        or expected_route["modelRef"].partition("/")[0].casefold()
        != expected_route["providerId"].casefold()
    ):
        raise MeetingReceiptAuthorityError("formal meeting effective model route is invalid")
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
        "outcomeKinds": [outcome_kind],
        "expectedModelRoute": expected_route,
        "evidenceLocator": {
            "kind": "turn_journal",
            "executionKind": "chat_room_meeting",
            "meetingRoundId": meeting_round_id,
            "chatRoomRoundId": chat_room_round_id,
            "participantId": participant_id,
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
) -> None:
    """Read back provider receipts and register them before content can land."""

    from core.chat.conversation_ledger import load_conversation_events
    from core.chat.turn_journal import read_model_invocation_receipts_from_events

    from .model_invocation_receipt_registry import (
        register_question_model_invocation_receipts,
    )

    receipts = read_model_invocation_receipts_from_events(
        load_conversation_events(project_root, session_id),
        turn_id=turn_identity,
    )
    if not receipts:
        raise MeetingReceiptAuthorityError(
            "formal meeting model call completed without a verifiable invocation receipt"
        )
    refs = register_question_model_invocation_receipts(
        team_id,
        question_id=question_id,
        workflow_run_id=workflow_run_id,
        receipts=receipts,
    )
    if not refs:
        raise MeetingReceiptAuthorityError(
            "formal meeting model invocation receipts were not registered"
        )


__all__ = [
    "MeetingReceiptAuthorityError",
    "authority_from_created_run",
    "build_speaker_receipt_context",
    "build_meeting_receipt_authority",
    "register_speaker_receipts",
    "resolve_active_question_authority",
]
