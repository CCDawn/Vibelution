"""Wait for canonical Task/Turn terminal and collect scoped domain artifact refs.

Production RealDomainPorts must not invent deterministic example.local payloads.
After Session/Task/Turn reaches a terminal success status, this module reconciles
Source Collection stage writeback and builds refs from real SC / ClaimEvidence
stores scoped by teamId + sourceCollectionRunId + workflowRunId.
"""

from __future__ import annotations

import json
import time
from dataclasses import replace
from typing import Any

from core.research.workflow.contracts import PendingAction

from .challenge_turn_policy import (
    CHALLENGE_TURN_WAIT_WINDOW_MS,
    ChallengeTaskDeadlineExceeded,
    challenge_deadline_problem,
    challenge_deadline_waited_ms,
    challenge_task_deadline_scope,
    current_challenge_task_resume_problem,
    current_challenge_task_started_at_ms,
    remaining_challenge_task_ms,
)
from .domain_ports import AgentTaskHandle, AgentTurnResult

_SUCCESS_TERMINAL_STATUSES = frozenset({"ready", "completed", "done", "success"})
_FAILURE_TERMINAL_STATUSES = frozenset(
    {
        "failed",
        "failed_provider",
        "failed_runtime",
        "error",
        "cancelled",
        "canceled",
        "stopped",
        "stopped_by_user",
        "superseded",
        "paused_limit",
        "needs_continue",
    }
)

_PROJECT_TASK_RECONCILABLE_TURN_STATUSES = frozenset({"needs_continue"})

# Canonical resumable terminal turn statuses per the session protocol: a turn
# that stops here is parked awaiting an explicit continue request, not broken
# (persist.py marks these "resumeAllowed"; runtime_service maps them to the
# ready/resumable session phase).  "stopped_by_user" is deliberately absent:
# a workflow node must never silently resume a turn a user stopped on purpose.
AGENT_TURN_CONTINUABLE_TERMINAL_STATUSES = frozenset(
    {"needs_continue", "paused_limit"}
)

# Consecutive no-progress allowance per complete_agent_turn_outputs call. Every
# continuation remains a first-class protocol step on the SAME session. New
# canonical progress resets this counter; the logical-task deadline remains
# the absolute bound for a legitimately long progressing chain.
MAX_AGENT_TURN_CONTINUATIONS = 3

# A source-collection stage task whose canonical status settled to
# "completed" is domain-verified finished work: the writeback tool downgrades
# any completed-but-gate-failed outcome to "needs_review", so canonical
# "completed" implies the stage completion gate passed and the node's work
# product (materialized records / artifact refs) exists.  The bounded
# continuation consults this authority at both decision points: a parked turn
# whose task already settled must not trigger a "继续" LLM round-trip, and a
# failed continuation turn must not retroactively poison an attempt whose
# main turn already completed the work.  The same authority covers the main
# turn failing after its own work settled (e.g. a post-writeback budget
# exhaustion): with the attempt-keyed idempotency key re-anchoring retries to
# the failed turn, the settled verdict must win over re-raising.  The failure
# itself is never swallowed -- it stays visible in the session turn record
# and is surfaced as a structured warning scene event.
_STAGE_TASK_SETTLED_COMPLETED_STATUS = "completed"

DEFAULT_AGENT_TURN_TIMEOUT_MS = CHALLENGE_TURN_WAIT_WINDOW_MS


def _stage_task_work_already_complete(*, team_id: str, task_id: str) -> bool:
    """Read the stage-task authority: did this node's work already settle?"""

    normalized_team = str(team_id or "").strip()
    normalized_task = str(task_id or "").strip()
    if not normalized_team or not normalized_task:
        return False
    try:
        from core.web.services.team_workflow.source_collection.stage_task_query import (
            get_source_collection_stage_session_task,
        )

        record = get_source_collection_stage_session_task(normalized_team, normalized_task)
    except Exception:
        # Read-only optimization guard: when the authority cannot answer, keep
        # the existing continuation/failure semantics (fail-closed).
        return False
    task_record = record.get("task") if isinstance(record, dict) else None
    if not isinstance(task_record, dict):
        return False
    return (
        str(task_record.get("status") or "").strip().lower()
        == _STAGE_TASK_SETTLED_COMPLETED_STATUS
    )


def _canonical_agent_task_started_at_ms(
    *,
    team_id: str,
    task_id: str,
    project_id: str,
    adapter_spec: Any | None,
) -> int:
    """Read the logical-task clock from its existing domain authority."""

    normalized_team = str(team_id or "").strip()
    normalized_task = str(task_id or "").strip()
    if not normalized_team or not normalized_task or adapter_spec is None:
        return 0
    try:
        if adapter_spec.family == "source_collection":
            from core.web.services.team_workflow.source_collection.stage_task_query import (
                get_source_collection_stage_session_task,
            )

            response = get_source_collection_stage_session_task(
                normalized_team,
                normalized_task,
            )
            task = response.get("task") if isinstance(response, dict) else None
        elif adapter_spec.family == "research_project":
            from core.web.services.team_workflow.research_project_agent_tasks import (
                _read_research_project_agent_task_record,
            )

            task = _read_research_project_agent_task_record(
                normalized_team,
                str(project_id or "").strip(),
                normalized_task,
            )
        else:
            task = None
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return 0
    if not isinstance(task, dict):
        return 0
    turn = task.get("turn") if isinstance(task.get("turn"), dict) else {}
    from core.web.services.session.timebase import parse_timestamp_utc

    started = parse_timestamp_utc(
        task.get("createdAt")
        or task.get("startedAt")
        or turn.get("acceptedAt")
    )
    return int(started.timestamp() * 1000) if started is not None else 0


def _persist_question_model_invocation_receipts(
    snapshot: dict[str, Any],
    *,
    team_id: str,
    question_id: str,
    workflow_run_id: str,
) -> list[dict[str, Any]]:
    raw = snapshot.get("modelInvocationReceipts")
    receipts = [item for item in list(raw or []) if isinstance(item, dict)]
    if not receipts:
        legacy = snapshot.get("modelInvocationReceipt")
        receipts = [legacy] if isinstance(legacy, dict) else []
    if not receipts or not question_id:
        return []
    from .model_invocation_receipt_registry import (
        register_question_model_invocation_receipts,
    )

    return register_question_model_invocation_receipts(
        team_id,
        question_id=question_id,
        workflow_run_id=workflow_run_id,
        receipts=receipts,
    )


def _attach_registered_model_invocation_receipts(
    snapshot: dict[str, Any],
    *,
    team_id: str,
    question_id: str,
    workflow_run_id: str,
    session_id: str,
    turn_id: str,
) -> dict[str, Any]:
    """Project Challenge Cup audit receipts without reading conversation JSONL."""

    if snapshot.get("modelInvocationReceipts") or snapshot.get("modelInvocationReceipt"):
        return snapshot
    from .model_invocation_receipt_registry import (
        question_model_invocation_receipts,
    )

    receipts = question_model_invocation_receipts(
        team_id,
        question_id=question_id,
        workflow_run_id=workflow_run_id,
        session_id=session_id,
        turn_id=turn_id,
    )
    if not receipts:
        return snapshot
    projected = dict(snapshot)
    projected["modelInvocationReceipts"] = receipts
    projected["modelInvocationReceipt"] = receipts[-1]
    return projected


def _formal_receipt_writeback_context(
    snapshot: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str, str, dict[str, Any]]:
    """Return a validated receipt and its explicit stage/policy binding.

    The stage is read only from the receipt scope.  A formal workflow node or
    task name must never be guessed as ``generation``/``review``/``revision``;
    an incomplete or malformed receipt therefore falls back to the existing
    legacy evidence path and remains ineligible for the formal package gate.
    """

    raw = snapshot.get("modelInvocationReceipt") if isinstance(snapshot, dict) else None
    if not isinstance(raw, dict):
        return None, "", "", {}
    try:
        from core.research.workflow.contracts.model_invocation_receipt import (
            ModelInvocationReceipt,
        )

        receipt = ModelInvocationReceipt.from_dict(raw)
    except (TypeError, ValueError, KeyError):
        return None, "", "", {}
    scope = dict(receipt.scope or {})
    stage_id = str(
        scope.get("stageId") or scope.get("stage_id") or ""
    ).strip().lower()
    policy_sha256 = str(
        scope.get("modelPolicySha256") or scope.get("model_policy_sha256") or ""
    ).strip().lower()
    if stage_id not in {"generation", "review", "revision"} or len(policy_sha256) != 64:
        return None, "", "", {}
    usage = {
        "source": "canonical_turn_outcome",
        "provider": receipt.provider,
        "model": receipt.model,
        "llmModelId": "",
    }
    for source_key, target_key in (
        ("inputTokens", "inputTokens"),
        ("outputTokens", "outputTokens"),
        ("totalTokens", "totalTokens"),
        ("cachedInputTokens", "cachedInputTokens"),
    ):
        value = receipt.token_usage.get(source_key)
        if value is not None:
            usage[target_key] = int(value or 0)
    return receipt.to_dict(), stage_id, policy_sha256, usage


def _require_formal_model_invocation_receipt(
    snapshot: dict[str, Any],
    *,
    input_snapshot: dict[str, Any],
    task_started_at_ms: int,
    formal_receipt: dict[str, Any] | None = None,
) -> None:
    """Keep a formal task retryable until its durable receipt is visible."""

    routing = input_snapshot.get("modelRoutingPolicy")
    receipt_required = isinstance(routing, dict) and all(
        (
            isinstance(routing.get("requiredModelPolicy"), dict),
            bool(str(routing.get("modelPolicySha256") or "").strip()),
            isinstance(routing.get("routes"), dict),
        )
    )
    if not receipt_required or formal_receipt is not None:
        return
    raise TurnNotReadyError(
        "model invocation receipt persistence is pending",
        snapshot={
            **snapshot,
            "terminal": False,
            "terminalStatus": "",
            "completionSource": "receipt_registry_pending",
            "turnTerminal": bool(snapshot.get("terminal")),
            "turnTerminalStatus": str(snapshot.get("terminalStatus") or ""),
            "turnCompletionSource": str(snapshot.get("completionSource") or ""),
            "receiptPersistencePending": True,
            "challengeTaskStartedAtMs": int(task_started_at_ms or 0),
        },
    )


class TurnNotReadyError(RuntimeError):
    """Turn is still running; adapter should requeue rather than fail permanently."""

    def __init__(self, message: str, *, snapshot: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.snapshot = dict(snapshot or {})


class SourceExtractionContractViolation(RuntimeError):
    """source_extraction turn-final materialization hit the fail-closed contract.

    Production blocker (run-882610596ddb): a Challenge v2 evidence-card
    violation used to escape as a bare exception and get wrapped into the
    generic ``adapter_execution_exception`` problem, leaving the failed node
    undiagnosable.  This error carries a structured problem dict so the
    dispatch layer records the dedicated
    ``source_extraction_contract_violation`` code with the precise failing
    path.  It is never swallowed: the attempt still fails fail-closed — only
    the classification and message become actionable.
    """

    def __init__(self, problem: dict[str, Any]) -> None:
        self.problem = dict(problem)
        super().__init__(json.dumps(self.problem, ensure_ascii=False, sort_keys=True))


def _turn_terminal_failure_detail(exc: Exception) -> dict[str, Any] | None:
    """Parse the canonical ``agent_turn_terminal_failed`` rejection, if exc is one.

    ``wait_for_agent_turn_terminal`` signals a failure-terminal turn by raising
    ``RuntimeError(json.dumps({code: agent_turn_terminal_failed, ...}))``.  Any
    other error shape (anchor incomplete, arbitrary runtime error,
    ``TurnNotReadyError``) must keep propagating untouched.
    """

    try:
        detail = json.loads(str(exc))
    except (TypeError, ValueError):
        return None
    if not isinstance(detail, dict):
        return None
    if str(detail.get("code") or "").strip() != "agent_turn_terminal_failed":
        return None
    return detail


def _propagate_turn_terminal_failure_to_stage_task(
    *,
    team_id: str,
    task_id: str,
    failure_detail: dict[str, Any],
) -> None:
    """Mirror a terminal Agent turn failure onto its source-collection stage task.

    The writeback tool can leave the stage task in a non-terminal state (for
    example ``needs_review``) even though the turn itself ended in a failure
    terminal status.  ``prepare_source_collection_stage_task_replay`` only
    switches to a fresh session for ``status == "failed"`` tasks whose
    recorded failure matches the poisoned-context loop, so without this mirror
    the formal retry keeps reusing the failed session forever.  The turn's
    structured reason wins as ``failureCode`` so the existing loop markers
    keep matching.  Idempotent and best-effort: a settled ``completed`` task
    is never overwritten, an identical failure is not rewritten, and any
    store error is logged without breaking the dispatch failure path.
    """

    normalized_team = str(team_id or "").strip()
    normalized_task = str(task_id or "").strip()
    if not normalized_team or not normalized_task:
        return
    detail = failure_detail if isinstance(failure_detail, dict) else {}
    terminal_status = str(detail.get("terminalStatus") or "").strip().lower()
    reason_code = str(
        detail.get("terminalProblemCode")
        or detail.get("terminalReason")
        or ""
    ).strip()
    failure_code = (reason_code or "agent_turn_terminal_failed")[:120]
    failure_message = " ".join(
        part
        for part in (
            (
                f"Agent turn ended in terminal status '{terminal_status}'."
                if terminal_status
                else "Agent turn ended in a terminal failure."
            ),
            f"Reason: {reason_code}." if reason_code else "",
            "Stage task marked failed so the formal replay can pick a recovery path.",
        )
        if part
    )
    try:
        from core.web.services import team_workflow_orchestration_service

        s = team_workflow_orchestration_service
        task, run_id = s._find_source_collection_stage_session_task_by_id(
            normalized_team,
            normalized_task,
        )
        if task is None or not run_id:
            _record_turn_continuation_scene_event(
                "agent_turn.stage_task_failure_propagation_skipped",
                level="warning",
                outcome="skipped",
                fields={
                    "teamId": normalized_team,
                    "taskId": normalized_task,
                    "reason": "stage_session_task_not_found",
                },
            )
            return
        current_status = str(task.get("status") or "").strip().lower()
        if current_status == "completed":
            # Domain-verified finished work is never retroactively failed.
            return
        if (
            current_status == "failed"
            and str(task.get("failureCode") or "").strip() == failure_code
            and str(task.get("failureMessage") or "").strip() == failure_message
        ):
            # Same failure already recorded: keep the original timestamps.
            return
        now = s.utc_now_iso()
        failed = dict(task)
        failed["status"] = "failed"
        failed["failureCode"] = failure_code
        failed["failureMessage"] = failure_message
        failed["failedAt"] = now
        failed["updatedAt"] = now
        s._upsert_source_collection_stage_session_task(normalized_team, run_id, failed)
        s._record_workflow_event(
            "source_collection.stage_session_task_turn_terminal_failed",
            normalized_team,
            fields={
                "runId": run_id,
                "taskId": normalized_task,
                "sessionId": str(detail.get("sessionId") or "").strip(),
                "turnId": str(detail.get("turnId") or "").strip(),
                "terminalStatus": terminal_status,
                "failureCode": failure_code,
            },
        )
    except Exception as exc:  # noqa: BLE001 - failure propagation is best-effort
        _record_turn_continuation_scene_event(
            "agent_turn.stage_task_failure_propagation_failed",
            level="warning",
            outcome="failed",
            fields={
                "teamId": normalized_team,
                "taskId": normalized_task,
                "errorType": type(exc).__name__,
                "error": str(exc)[:200],
            },
        )


def wait_for_agent_turn_terminal(
    session_id: str,
    turn_id: str,
    *,
    timeout_ms: int = DEFAULT_AGENT_TURN_TIMEOUT_MS,
    poll_ms: int = 200,
    reconcilable_terminal_statuses: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Poll canonical turn completion until terminal success, failure, or timeout."""
    from core.web.services.session.turn_diagnostics import (
        get_session_turn_completion_snapshot,
    )

    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_session_id or not normalized_turn_id:
        raise RuntimeError(
            json.dumps(
                {
                    "code": "agent_turn_anchor_incomplete",
                    "sessionId": normalized_session_id,
                    "turnId": normalized_turn_id,
                },
                ensure_ascii=False,
            )
        )

    deadline = time.monotonic() + max(0, int(timeout_ms)) / 1000.0
    sleep_s = max(1, int(poll_ms)) / 1000.0
    last_snapshot: dict[str, Any] = {}
    while True:
        last_snapshot = get_session_turn_completion_snapshot(
            normalized_session_id, normalized_turn_id
        )
        if bool(last_snapshot.get("terminal")):
            status = str(
                last_snapshot.get("terminalStatus")
                or last_snapshot.get("lastTurnStatus")
                or ""
            ).strip().lower()
            if (
                status in _SUCCESS_TERMINAL_STATUSES
                or status in reconcilable_terminal_statuses
            ):
                return last_snapshot
            detail = {
                "code": "agent_turn_terminal_failed",
                "sessionId": normalized_session_id,
                "turnId": normalized_turn_id,
                "terminalStatus": status,
                "completionSource": last_snapshot.get("completionSource"),
                "terminalProblemCode": last_snapshot.get("terminalProblemCode"),
                "terminalReason": last_snapshot.get("terminalReason"),
                "failureClass": (
                    "terminal_failure"
                    if status in _FAILURE_TERMINAL_STATUSES
                    else "terminal_non_success"
                ),
            }
            raise RuntimeError(json.dumps(detail, ensure_ascii=False))
        if time.monotonic() >= deadline:
            raise TurnNotReadyError(
                json.dumps(
                    {
                        "code": "agent_turn_not_ready",
                        "sessionId": normalized_session_id,
                        "turnId": normalized_turn_id,
                        "terminal": False,
                        "terminalStatus": last_snapshot.get("terminalStatus"),
                        "completionSource": last_snapshot.get("completionSource"),
                        "timeoutMs": timeout_ms,
                    },
                    ensure_ascii=False,
                ),
                snapshot=last_snapshot,
            )
        time.sleep(sleep_s)


def probe_agent_turn_terminal(
    session_id: str,
    turn_id: str,
) -> dict[str, Any]:
    """One non-blocking canonical turn state probe (no polling, no sleep).

    Same contract as :func:`wait_for_agent_turn_terminal` minus the wait:
    the returned snapshot carries ``terminal`` (``True`` with a success
    terminal status, ``False`` while the turn is still live, including its
    ``turnCurrent`` liveness signal); a failure-terminal turn raises the same
    ``agent_turn_terminal_failed`` rejection shape.  Callers that must not
    hold the single-threaded dispatch pump use this to requeue durably
    instead of sleeping inside the node action.
    """

    from core.web.services.session.turn_diagnostics import (
        get_session_turn_completion_snapshot,
    )

    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_session_id or not normalized_turn_id:
        raise RuntimeError(
            json.dumps(
                {
                    "code": "agent_turn_anchor_incomplete",
                    "sessionId": normalized_session_id,
                    "turnId": normalized_turn_id,
                },
                ensure_ascii=False,
            )
        )
    snapshot = get_session_turn_completion_snapshot(
        normalized_session_id, normalized_turn_id
    )
    if not bool(snapshot.get("terminal")):
        return snapshot
    status = str(
        snapshot.get("terminalStatus") or snapshot.get("lastTurnStatus") or ""
    ).strip().lower()
    if status in _SUCCESS_TERMINAL_STATUSES:
        return snapshot
    raise RuntimeError(
        json.dumps(
            {
                "code": "agent_turn_terminal_failed",
                "sessionId": normalized_session_id,
                "turnId": normalized_turn_id,
                "terminalStatus": status,
                "completionSource": snapshot.get("completionSource"),
                "terminalProblemCode": snapshot.get("terminalProblemCode"),
                "terminalReason": snapshot.get("terminalReason"),
                "failureClass": (
                    "terminal_failure"
                    if status in _FAILURE_TERMINAL_STATUSES
                    else "terminal_non_success"
                ),
            },
            ensure_ascii=False,
        )
    )


def collect_required_artifact_refs(
    *,
    required_kinds: tuple[str, ...],
    team_id: str,
    workflow_run_id: str,
    source_collection_run_id: str,
) -> list[dict[str, str]]:
    """Build canonical refs from scoped SC / ClaimEvidence store payloads."""
    from .artifact_readback_registry import (
        build_canonical_ref,
        load_scoped_artifact_payload,
    )
    from .human_gate_artifacts import canonical_sha256

    if not required_kinds:
        return []
    normalized_team = str(team_id or "").strip()
    authority_run_id = (
        str(source_collection_run_id or "").strip()
        or str(workflow_run_id or "").strip()
    )
    if not normalized_team or not authority_run_id:
        raise RuntimeError(
            "team_id and source_collection_run_id/workflow_run_id are required "
            "to collect artifact refs"
        )

    refs: list[dict[str, str]] = []
    for kind in required_kinds:
        payload = load_scoped_artifact_payload(
            kind,
            team_id=normalized_team,
            authority_run_id=authority_run_id,
            workflow_run_id=str(workflow_run_id or "").strip(),
        )
        if payload is None:
            continue
        content_hash = canonical_sha256(payload)
        version = "1.0.0"
        refs.append(
            {
                "canonicalRef": build_canonical_ref(
                    kind=kind,
                    team_id=normalized_team,
                    authority_run_id=authority_run_id,
                    content_hash=content_hash,
                ),
                "kind": kind,
                "sha256": content_hash,
                "version": version,
            }
        )
    return refs


def _record_turn_continuation_scene_event(
    event_code: str,
    *,
    outcome: str,
    fields: dict[str, Any],
    level: str = "info",
) -> None:
    """Best-effort worker observability; never breaks the dispatch path."""
    from core.web.services.runtime_scene_service import (
        record_runtime_scene_event_quietly,
    )

    record_runtime_scene_event_quietly(
        "team_workflow_orchestration",
        "agent_turn_completion",
        event_code,
        level=level,
        outcome=outcome,
        fields=fields,
    )


def _submit_agent_turn_continuation(
    handle: AgentTaskHandle,
    *,
    action: PendingAction,
    input_snapshot: dict[str, Any],
    attempt: int,
    from_turn_id: str,
    paused_status: str,
) -> str:
    """First-class protocol step: continue the parked turn on the same session.

    The canonical continue request reuses the session resume channel
    (persist.py resumeAllowed).  Source-collection stage sessions inherit
    their stage-task continuation contract from the previous messages in the
    submit layer, and the parked model keeps its full history.  The metadata
    deliberately carries no ``kind`` key: that keeps the stage-task
    continuation inheritance working and keeps project-task strict output
    bindings (which pin exactly one stored turn id) from being hijacked by
    the continuation turn.
    """
    from core.web.services.session.submit import submit_session_message

    _record_turn_continuation_scene_event(
        "agent_turn.continuation_requested",
        outcome="submitting",
        fields={
            "sessionId": handle.session_id,
            "fromTurnId": from_turn_id,
            "pausedStatus": paused_status,
            "continuationAttempt": attempt,
            "maxContinuations": MAX_AGENT_TURN_CONTINUATIONS,
            "workflowRunId": str(action.run_id or ""),
            "workflowNodeId": str(action.node_id or ""),
            "nodeRunId": str(action.node_run_id or ""),
            "taskId": str(handle.task_id or ""),
        },
    )
    turn = submit_session_message(
        handle.session_id,
        "继续",
        mental_model_enabled=False,
        turn_mode="task",
        write_intent=False,
        message_source="agent_inbox",
        message_metadata={
            "sourceSurface": "team_workflow_agent_turn_continuation",
            "teamId": str(input_snapshot.get("teamId") or "").strip(),
            "workflowRunId": str(action.run_id or ""),
            "workflowNodeId": str(action.node_id or ""),
            "nodeRunId": str(action.node_run_id or ""),
            "taskId": str(handle.task_id or ""),
            "continuationAttempt": attempt,
            "continuationOfTurnId": from_turn_id,
            "continuationPausedStatus": paused_status,
        },
        include_started_turn_id=True,
        lightweight_response=True,
    )
    new_turn_id = str(
        (turn or {}).get("turnId") or (turn or {}).get("startedTurnId") or ""
    ).strip()
    if not new_turn_id:
        raise RuntimeError(
            json.dumps(
                {
                    "code": "agent_turn_continuation_not_accepted",
                    "sessionId": handle.session_id,
                    "turnId": from_turn_id,
                    "continuationAttempt": attempt,
                    "response": turn
                    if isinstance(turn, dict)
                    else {"raw": str(turn)[:200]},
                },
                ensure_ascii=False,
            )
        )
    _record_turn_continuation_scene_event(
        "agent_turn.continuation_submitted",
        outcome="continued",
        fields={
            "sessionId": handle.session_id,
            "fromTurnId": from_turn_id,
            "toTurnId": new_turn_id,
            "pausedStatus": paused_status,
            "continuationAttempt": attempt,
            "maxContinuations": MAX_AGENT_TURN_CONTINUATIONS,
            "workflowRunId": str(action.run_id or ""),
            "workflowNodeId": str(action.node_id or ""),
            "nodeRunId": str(action.node_run_id or ""),
            "taskId": str(handle.task_id or ""),
        },
    )
    return new_turn_id


def _wait_with_bounded_turn_continuation(
    handle: AgentTaskHandle,
    *,
    action: PendingAction,
    input_snapshot: dict[str, Any],
    adapter_spec: Any | None,
    timeout_ms: int,
    poll_ms: int,
) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    """Wait for the canonical turn, continuing parked turns within protocol.

    A turn that reaches ``needs_continue``/``paused_limit`` is resumable per
    the session protocol, so instead of failing the node attempt this loop
    submits the canonical continue request to the same session and keeps
    waiting. ``MAX_AGENT_TURN_CONTINUATIONS`` bounds consecutive continuations
    without canonical progress, not the total number of productive turns.
    Exhausting that no-progress allowance raises
    ``agent_turn_continuation_exhausted`` with the full turn chain; a failure
    is never downgraded into success.

    Source-collection family turns are additionally anchored to their domain
    authority (the stage task store) at both decision points:

    - Before submitting a continuation: if the stage task already settled to
      canonical ``completed`` (completion gate passed during the parked main
      turn), the work is done and a ``继续`` round-trip must not be spent on
      it -- the parked snapshot is returned as the attempt verdict with a
      structured scene event.
    - When a continuation turn fails terminally: if the stage task settled
      ``completed``, the attempt is judged by the main turn's snapshot (its
      receipts and writeback are the real work) and the continuation failure
      is surfaced as a structured warning -- it is never silently swallowed
      (the session turn record keeps the failure and its user-readable
      reason).
    - When the main turn itself fails terminally: the same authority question
      decides.  A settled ``completed`` stage task means the gate passed and
      the work product exists; because the stage-task idempotency key omits
      the node-run attempt, every retry re-anchors to that same failed turn,
      so re-raising would deadlock the node permanently.  The attempt then
      returns the failed turn's snapshot with a structured warning scene
      event -- the failure stays visible, never reclassified as success.  If
      the authority does not confirm completed work, the failure raises as
      before (fail-closed).

    Research-project tasks are excluded: their task authority
    (``research_project_agent_tasks`` reconcile) deliberately classifies a
    needs_continue session as ``stopped/session_needs_continue``; reviving
    those turns requires rebinding the stored task turn, which is that
    authority's decision, not this adapter's.
    """
    if adapter_spec is not None and adapter_spec.family == "research_project":
        # Project task authority (research_project_agent_tasks reconcile)
        # owns the needs_continue verdict for project tasks: keep returning
        # the parked snapshot so its existing classification
        # (stopped/session_needs_continue) decides, instead of auto-resuming
        # behind its back.
        reconcilable = _PROJECT_TASK_RECONCILABLE_TURN_STATUSES
        continuable: frozenset[str] = frozenset()
    else:
        reconcilable = AGENT_TURN_CONTINUABLE_TERMINAL_STATUSES
        continuable = AGENT_TURN_CONTINUABLE_TERMINAL_STATUSES
    source_collection_scope = (
        adapter_spec is not None and adapter_spec.family == "source_collection"
    )
    team_id = str(input_snapshot.get("teamId") or "").strip()
    original_turn_id = handle.turn_id
    original_snapshot: dict[str, Any] | None = None
    turn_chain: list[str] = [handle.turn_id]
    continuations: list[dict[str, Any]] = []
    turn_id = handle.turn_id
    resume_problem = current_challenge_task_resume_problem()
    resume_chain = [
        str(item or "").strip()
        for item in list(resume_problem.get("continuationTurnChain") or [])
        if str(item or "").strip()
    ]
    try:
        resume_used = max(0, int(resume_problem.get("continuationsUsed") or 0))
    except (TypeError, ValueError):
        resume_used = 0
    try:
        resume_no_progress_continuations = max(
            0,
            int(resume_problem.get("continuationNoProgressCount") or 0),
        )
    except (TypeError, ValueError):
        resume_no_progress_continuations = 0
    consecutive_no_progress_continuations = 0
    if (
        str(resume_problem.get("code") or "").strip() == "live_turn_wait"
        and resume_used > 0
        and len(resume_chain) == resume_used + 1
        and resume_chain[0] == handle.turn_id
        and resume_chain[-1]
        == str(resume_problem.get("continuationTurnId") or "").strip()
    ):
        consecutive_no_progress_continuations = resume_no_progress_continuations
        turn_chain = resume_chain
        turn_id = resume_chain[-1]
        continuations = [
            {
                "attempt": index,
                "fromTurnId": resume_chain[index - 1],
                "toTurnId": resume_chain[index],
                "pausedStatus": "persisted_live_wait",
            }
            for index in range(1, resume_used + 1)
        ]
        original_snapshot = {
            "sessionId": handle.session_id,
            "turnId": handle.turn_id,
            "terminal": True,
            "terminalStatus": "needs_continue",
            "completionSource": "persisted_continuation_chain",
        }

    def _bounded_wait_timeout_ms() -> tuple[int, bool]:
        remaining_ms = remaining_challenge_task_ms()
        if remaining_ms is None:
            return max(0, int(timeout_ms)), False
        if remaining_ms <= 0:
            raise ChallengeTaskDeadlineExceeded(
                challenge_deadline_problem(
                    waited_ms=challenge_deadline_waited_ms(),
                    turn_chain=turn_chain,
                )
            )
        requested_ms = max(0, int(timeout_ms))
        return min(requested_ms, remaining_ms), remaining_ms < requested_ms

    def _rescue_settled_main_turn(
        failed_turn_id: str,
        status: str,
        *,
        event_code: str = "agent_turn.continuation_failed_work_complete",
    ) -> None:
        _record_turn_continuation_scene_event(
            event_code,
            level="warning",
            outcome="resolved_by_stage_task_authority",
            fields={
                "sessionId": handle.session_id,
                "mainTurnId": original_turn_id,
                "failedTurnId": failed_turn_id,
                "failedTurnStatus": status,
                "turnChain": list(turn_chain),
                "continuationsUsed": len(continuations),
                "taskId": str(handle.task_id or ""),
                "workflowRunId": str(action.run_id or ""),
                "workflowNodeId": str(action.node_id or ""),
            },
        )

    while True:
        effective_timeout_ms, logical_deadline_bounded = _bounded_wait_timeout_ms()
        try:
            snapshot = wait_for_agent_turn_terminal(
                handle.session_id,
                turn_id,
                timeout_ms=effective_timeout_ms,
                poll_ms=poll_ms,
                reconcilable_terminal_statuses=reconcilable,
            )
        except TurnNotReadyError as exc:
            if logical_deadline_bounded:
                raise ChallengeTaskDeadlineExceeded(
                    challenge_deadline_problem(
                        waited_ms=challenge_deadline_waited_ms(),
                        turn_chain=turn_chain,
                    )
                ) from exc
            started_at_ms = current_challenge_task_started_at_ms()
            if started_at_ms:
                exc.snapshot.setdefault(
                    "challengeTaskStartedAtMs",
                    int(started_at_ms),
                )
            if continuations:
                exc.snapshot.update(
                    {
                        "continuationRootTurnId": handle.turn_id,
                        "continuationTurnId": turn_id,
                        "continuationTurnChain": list(turn_chain),
                        "continuationsUsed": len(continuations),
                        "continuationNoProgressCount": (
                            consecutive_no_progress_continuations
                        ),
                    }
                )
            raise
        except RuntimeError as exc:
            failure_detail = _turn_terminal_failure_detail(exc)
            if failure_detail is None:
                raise
            failure_status = str(failure_detail.get("terminalStatus") or "").strip().lower()
            failure_problem_code = str(
                failure_detail.get("terminalProblemCode")
                or failure_detail.get("terminalReason")
                or ""
            ).strip().lower()
            if failure_problem_code == "challenge_logical_task_deadline_exhausted":
                raise ChallengeTaskDeadlineExceeded(
                    challenge_deadline_problem(
                        waited_ms=challenge_deadline_waited_ms(),
                        turn_chain=turn_chain,
                    )
                ) from exc
            if source_collection_scope and _stage_task_work_already_complete(
                team_id=team_id, task_id=handle.task_id
            ):
                if original_snapshot is not None:
                    # The main turn finished the work before parking; a later
                    # continuation turn's failure must not erase that.  Judge
                    # the attempt by the main turn and expose the failure as a
                    # structured warning instead of poisoning the verdict.
                    # The failure itself stays visible in the session turn
                    # record.
                    _rescue_settled_main_turn(turn_id, failure_status)
                    return original_snapshot, original_turn_id, continuations
                # The main turn itself failed terminally after the stage task
                # settled "completed" (production run-16cfab646d08: the
                # writeback tool passed the completion gate, then a later LLM
                # call died with budget_exhausted).  The stage-task idempotency
                # key omits the node-run attempt, so every retry re-anchors to
                # this same failed turn: re-raising here would deadlock the
                # node forever even though gate-verified work exists.  The
                # attempt is judged by the failed turn's own snapshot -- the
                # failure stays visible (session turn record plus a structured
                # warning scene event) instead of being swallowed.
                _rescue_settled_main_turn(
                    turn_id,
                    failure_status,
                    event_code="agent_turn.main_turn_failed_work_complete",
                )
                failure_snapshot = {
                    **failure_detail,
                    "sessionId": handle.session_id,
                    "turnId": original_turn_id,
                    "terminal": True,
                    "rescuedByStageTaskAuthority": True,
                }
                return failure_snapshot, original_turn_id, continuations
            if source_collection_scope and str(handle.task_id or "").strip():
                # The attempt is about to fail on this terminal turn failure:
                # mirror the failure onto the stage task so the formal replay
                # sees status=failed plus a structured reason instead of the
                # writeback-time status (poisoned-session retry loop).
                _propagate_turn_terminal_failure_to_stage_task(
                    team_id=team_id,
                    task_id=handle.task_id,
                    failure_detail=failure_detail,
                )
            raise
        status = str(
            snapshot.get("terminalStatus") or snapshot.get("lastTurnStatus") or ""
        ).strip().lower()
        if status not in continuable:
            return snapshot, turn_id, continuations
        if original_snapshot is None:
            original_snapshot = snapshot
        if source_collection_scope and _stage_task_work_already_complete(
            team_id=team_id, task_id=handle.task_id
        ):
            # Parked turn, but the stage-task authority already settled the
            # work as gate-verified complete: there is nothing left to
            # continue, so do not spend a "继续" LLM round-trip (and its
            # protocol-error failure surface) on finished work.
            _record_turn_continuation_scene_event(
                "agent_turn.continuation_not_needed_work_complete",
                outcome="settled",
                fields={
                    "sessionId": handle.session_id,
                    "mainTurnId": original_turn_id,
                    "pausedStatus": status,
                    "taskId": str(handle.task_id or ""),
                    "workflowRunId": str(action.run_id or ""),
                    "workflowNodeId": str(action.node_id or ""),
                },
            )
            return snapshot, turn_id, continuations
        progress_advanced = bool(snapshot.get("continuationProgressAdvanced"))
        if continuations:
            if progress_advanced:
                consecutive_no_progress_continuations = 0
            else:
                consecutive_no_progress_continuations += 1
        if (
            consecutive_no_progress_continuations
            >= MAX_AGENT_TURN_CONTINUATIONS
        ):
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "agent_turn_continuation_exhausted",
                        "sessionId": handle.session_id,
                        "turnId": turn_id,
                        "terminalStatus": status,
                        "continuationsUsed": len(continuations),
                        "maxContinuations": MAX_AGENT_TURN_CONTINUATIONS,
                        "consecutiveNoProgressContinuations": (
                            consecutive_no_progress_continuations
                        ),
                        "turnChain": list(turn_chain),
                    },
                    ensure_ascii=False,
                )
            )
        _bounded_wait_timeout_ms()
        next_turn_id = _submit_agent_turn_continuation(
            handle,
            action=action,
            input_snapshot=input_snapshot,
            attempt=len(continuations) + 1,
            from_turn_id=turn_id,
            paused_status=status,
        )
        continuations.append(
            {
                "attempt": len(continuations) + 1,
                "fromTurnId": turn_id,
                "toTurnId": next_turn_id,
                "pausedStatus": status,
                "progressAdvanced": progress_advanced,
                "consecutiveNoProgressContinuations": (
                    consecutive_no_progress_continuations
                ),
            }
        )
        turn_chain.append(next_turn_id)
        turn_id = next_turn_id


def complete_agent_turn_outputs(
    *,
    action: PendingAction,
    handle: AgentTaskHandle,
    input_snapshot: dict[str, Any],
    required_kinds: tuple[str, ...],
    timeout_ms: int = DEFAULT_AGENT_TURN_TIMEOUT_MS,
    poll_ms: int = 200,
    return_result: bool = False,
) -> list[dict[str, str]] | AgentTurnResult:
    """Wait for turn terminal, reconcile its task authority, collect store refs."""
    from .task_adapter_registry import resolve_agent_task_adapter

    team_id = str(input_snapshot.get("teamId") or "").strip()
    if not team_id:
        raise RuntimeError("input snapshot has no teamId for agent turn completion")
    source_collection_run_id = (
        str(input_snapshot.get("sourceCollectionRunId") or "").strip()
        or str(action.run_id or "").strip()
    )

    adapter_spec = resolve_agent_task_adapter(action.node_id)
    task_started_at_ms = _canonical_agent_task_started_at_ms(
        team_id=team_id,
        task_id=handle.task_id,
        project_id=str(input_snapshot.get("projectId") or "").strip(),
        adapter_spec=adapter_spec,
    ) or current_challenge_task_started_at_ms() or 0
    with challenge_task_deadline_scope(
        task_started_at_ms,
        resume_problem=current_challenge_task_resume_problem(),
    ):
        snapshot, final_turn_id, continuations = _wait_with_bounded_turn_continuation(
            handle,
            action=action,
            input_snapshot=input_snapshot,
            adapter_spec=adapter_spec,
            timeout_ms=timeout_ms,
            poll_ms=poll_ms,
        )
    if continuations:
        # Downstream reconciliation must reference the final continuation
        # turn, not the originally parked one.
        handle = replace(handle, turn_id=final_turn_id)
    question_id = str(input_snapshot.get("questionId") or "").strip().upper()
    workflow_run_id = str(action.run_id or "").strip()
    snapshot = _attach_registered_model_invocation_receipts(
        snapshot,
        team_id=team_id,
        question_id=question_id,
        workflow_run_id=workflow_run_id,
        session_id=handle.session_id,
        turn_id=handle.turn_id,
    )
    formal_receipt, receipt_stage_id, receipt_policy_sha256, receipt_usage = (
        _formal_receipt_writeback_context(snapshot)
    )
    _require_formal_model_invocation_receipt(
        snapshot,
        input_snapshot=input_snapshot,
        task_started_at_ms=task_started_at_ms,
        formal_receipt=formal_receipt,
    )
    _persist_question_model_invocation_receipts(
        snapshot,
        team_id=team_id,
        question_id=question_id,
        workflow_run_id=workflow_run_id,
    )

    task_id = str(handle.task_id or "").strip()
    if task_id and adapter_spec is not None and adapter_spec.family == "source_collection":
        from core.web.services.team_workflow.source_collection.stage_writeback import (
            reconcile_source_collection_stage_session_task_after_turn,
        )

        reconcile_source_collection_stage_session_task_after_turn(
            team_id,
            task_id,
            run_id=source_collection_run_id,
            session_id=handle.session_id,
            turn_id=handle.turn_id,
            final_status=str(snapshot.get("terminalStatus") or ""),
            llm_usage=receipt_usage or None,
            model_invocation_receipt=formal_receipt,
            stage_id=receipt_stage_id or None,
            model_policy_sha256=receipt_policy_sha256 or None,
            reason="session_turn_completed",
        )

        if action.node_id == "source_extraction":
            from .agent_claim_evidence_materializer import (
                materialize_completed_extraction_task,
            )
            from .source_extraction_evidence_cards import (
                SourceExtractionEvidenceContractError,
            )

            try:
                materialize_completed_extraction_task(
                    team_id=team_id,
                    workflow_run_id=str(action.run_id or ""),
                    source_collection_run_id=source_collection_run_id,
                    task_id=task_id,
                )
            except SourceExtractionEvidenceContractError as exc:
                # Fail-closed, but diagnosable: surface the contract violation
                # with its precise path as a dedicated problem code instead of
                # letting the dispatch layer wrap it into the generic
                # adapter_execution_exception.  The exception keeps propagating
                # (chained), so the attempt still fails.
                raise SourceExtractionContractViolation(
                    {
                        "code": "source_extraction_contract_violation",
                        "detail": str(exc),
                        "taskId": task_id,
                        "workflowRunId": str(action.run_id or ""),
                        "sourceCollectionRunId": source_collection_run_id,
                    }
                ) from exc

    refs = collect_required_artifact_refs(
        required_kinds=required_kinds,
        team_id=team_id,
        workflow_run_id=str(action.run_id or ""),
        source_collection_run_id=source_collection_run_id,
    )
    project_task_authority: dict[str, Any] | None = None
    if task_id and adapter_spec is not None and adapter_spec.family == "research_project":
        project_task_authority = _require_project_task_terminal(
            team_id=team_id,
            project_id=str(input_snapshot.get("projectId") or "").strip(),
            task_id=task_id,
        )
        challenge_contract = project_task_authority.get("challengeTaskContract")
        if formal_receipt is not None and isinstance(challenge_contract, dict):
            from core.web.services.team_workflow.challenge_question_runs import (
                register_challenge_task_model_evidence,
            )

            register_challenge_task_model_evidence(
                team_id,
                project_task_authority,
                final_status=str(project_task_authority.get("status") or "").strip(),
                llm_usage=receipt_usage or None,
                model_invocation_receipt=formal_receipt,
                stage_id=str(challenge_contract.get("stageId") or "").strip(),
                model_policy_sha256=str(
                    challenge_contract.get("modelPolicySha256") or ""
                ).strip().lower(),
            )
    if return_result:
        return AgentTurnResult(
            materialized_refs=tuple(refs),
            handle=handle,
            usage=receipt_usage or None,
        )
    return refs


def _require_project_task_terminal(
    *, team_id: str, project_id: str, task_id: str
) -> dict[str, Any]:
    """Close the canonical project task before the same Agent can take a successor."""
    if not project_id:
        raise RuntimeError("input snapshot has no projectId for project Agent task completion")
    from core.web.services.team_workflow.research_project_agent_tasks import (
        _read_research_project_agent_task_record,
        reconcile_research_project_agent_task_statuses,
    )

    # Reconcile the canonical turn into the task store first, then read the
    # internal record so status and contract come from one server authority.
    reconcile_research_project_agent_task_statuses(team_id, project_id)
    task = _read_research_project_agent_task_record(team_id, project_id, task_id)
    if task is None:
        raise RuntimeError("completed project Agent task is missing from its authority")
    task_status = str(task.get("status") or "").strip().lower()
    if task_status in {"queued", "running"}:
        # The canonical turn already completed; only the task store lags its
        # reconcile. This is live progress, not a broken dispatch: carrying a
        # proper non-terminal snapshot keeps the dispatcher on the bounded
        # live-wait path instead of consuming the transient retry budget
        # (a slow model makes the lag exceed the 5-attempt transient cap and
        # fail the node as transient_exhausted).
        raise TurnNotReadyError(
            json.dumps(
                {
                    "code": "project_agent_task_not_reconciled",
                    "taskId": task_id,
                    "status": task_status,
                },
                ensure_ascii=False,
            ),
            snapshot={
                "terminal": False,
                "completionSource": "running",
                "taskId": task_id,
                "taskStatus": task_status,
            },
        )
    if task_status != "completed":
        raise RuntimeError(
            json.dumps(
                {
                    "code": "project_agent_task_terminal_failed",
                    "taskId": task_id,
                    "status": task_status,
                    "failureCode": task.get("failureCode"),
                },
                ensure_ascii=False,
            )
        )
    return task
