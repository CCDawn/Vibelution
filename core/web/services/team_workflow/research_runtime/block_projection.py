"""Persist node/run blocked status plus formal workflow events."""

from __future__ import annotations

import json
from typing import Any

from core.research.workflow.ledger import EventRecord
from core.research.workflow.transitions import NodeAttemptStatus, RunStatus

from .blocked_reason import format_blocked_reason
from .ids import new_id

_TERMINAL_RUN = {
    RunStatus.SUCCEEDED.value,
    RunStatus.FAILED.value,
    RunStatus.CANCELLED.value,
    RunStatus.ARCHIVED.value,
}


def sync_run_blocked(
    uow: Any,
    *,
    run_id: str,
    node_id: str,
    problem: dict[str, Any],
    now_ms: int,
) -> None:
    run = uow.repository.get_run(run_id)
    if run is None or run.status in _TERMINAL_RUN | {RunStatus.BLOCKED.value}:
        return
    uow.repository.update_run_status(
        run_id,
        run.team_id,
        RunStatus.BLOCKED.value,
        now_ms,
        active_node_id=node_id,
        blocked_problem_json=json.dumps(problem, ensure_ascii=False),
    )


def mark_run_reconciliation_required(
    uow: Any,
    *,
    run_id: str,
    problem: dict[str, Any],
    now_ms: int,
    actor_id: str,
    correlation_id: str,
    node_run_id: str | None = None,
    action_id: str | None = None,
    extra_payload: dict[str, Any] | None = None,
) -> bool:
    """Translate an unrecoverable dispatch failure into operator-visible state.

    A terminal-failed ``graph_dispatch`` whose node attempt is already past the
    point where blocking it would be legal (typically ``succeeded``) leaves the
    run stranded as ``running`` with no advancing mechanism behind it. Moving
    the run to ``reconciliation_required`` surfaces the reconcile_run offer
    instead of leaving the advancement chain silently dead. Idempotent: only
    ``running`` / ``waiting_human`` runs transition; every other status keeps
    its own recovery entry (ordinary BLOCKED runs already offer one).

    Returns True when this call transitioned the run.
    """
    run = uow.repository.get_run(run_id)
    if run is None:
        return False
    if run.status not in {
        RunStatus.RUNNING.value,
        RunStatus.WAITING_HUMAN.value,
    }:
        return False
    reason = format_blocked_reason(problem)
    problem_json = json.dumps(problem, ensure_ascii=False)
    uow.repository.update_run_status(
        run_id,
        run.team_id,
        RunStatus.RECONCILIATION_REQUIRED.value,
        now_ms,
        blocked_problem_json=problem_json,
    )
    sequence = uow.repository.advance_last_sequence(run_id, 1, now_ms)
    if sequence is None:
        return True
    payload = {
        "nodeRunId": node_run_id,
        "actionId": action_id,
        "code": problem.get("code"),
        "reason": reason or None,
        "reconciliation": "terminal_dispatch_failed",
        **dict(extra_payload or {}),
    }
    uow.repository.insert_event(
        EventRecord(
            run_id=run_id,
            sequence=sequence,
            event_id=new_id("evt"),
            run_version=run.run_version,
            event_type="reconciliation_required",
            actor_json=json.dumps(
                {"actorType": "system", "actorId": actor_id},
                ensure_ascii=False,
            ),
            correlation_id=correlation_id,
            causation_id=None,
            payload_json=json.dumps(payload, ensure_ascii=False),
            occurred_at_ms=now_ms,
        )
    )
    return True


def apply_node_run_block(
    uow: Any,
    *,
    run_id: str,
    node_run_id: str,
    node_id: str,
    problem: dict[str, Any],
    now_ms: int,
    actor_id: str,
    correlation_id: str,
    update_attempt: bool = True,
    extra_payload: dict[str, Any] | None = None,
) -> None:
    reason = format_blocked_reason(problem)
    problem_json = json.dumps(problem, ensure_ascii=False)
    if update_attempt:
        uow.repository.update_attempt_status(
            node_run_id,
            NodeAttemptStatus.BLOCKED.value,
            now_ms,
            problem_json=problem_json,
            finished_at_ms=now_ms,
        )
    run = uow.repository.get_run(run_id)
    sync_run_blocked(
        uow,
        run_id=run_id,
        node_id=node_id,
        problem=problem,
        now_ms=now_ms,
    )
    last_sequence = uow.repository.advance_last_sequence(run_id, 2, now_ms)
    if last_sequence is None:
        return
    base_sequence = last_sequence - 2
    run_version = run.run_version if run is not None else 1
    payload = {
        "nodeRunId": node_run_id,
        "nodeId": node_id,
        "code": problem.get("code"),
        "detail": problem.get("detail"),
        "reason": reason,
        **dict(extra_payload or {}),
    }
    for offset, event_type in enumerate(("node_blocked", "run_blocked"), start=1):
        uow.repository.insert_event(
            EventRecord(
                run_id=run_id,
                sequence=base_sequence + offset,
                event_id=new_id("evt"),
                run_version=run_version,
                event_type=event_type,
                actor_json=json.dumps(
                    {"actorType": "system", "actorId": actor_id},
                    ensure_ascii=False,
                ),
                correlation_id=correlation_id,
                causation_id=None,
                payload_json=json.dumps(payload, ensure_ascii=False),
                occurred_at_ms=now_ms,
            )
        )


def _normalized_terminal_decision(value: str) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "promote": "promote_candidate",
        "rollback": "rollback_candidate",
    }
    return aliases.get(text, text)


def terminal_facts_for_run(run: Any) -> tuple[str, str]:
    """``(completionKind, terminalReason)`` from the package / governance."""
    snapshot: dict[str, Any] = {}
    if getattr(run, "input_snapshot_json", None):
        try:
            loaded = json.loads(run.input_snapshot_json)
        except (TypeError, ValueError):
            loaded = {}
        if isinstance(loaded, dict):
            snapshot = loaded
    team_id = str(snapshot.get("teamId") or getattr(run, "team_id", "") or "").strip()
    run_id = str(getattr(run, "run_id", "") or "").strip()
    authority = str(snapshot.get("sourceCollectionRunId") or run_id).strip()

    def _body(kind: str) -> dict[str, Any]:
        if not team_id or not run_id:
            return {}
        from .real_readiness_context import _readiness_artifact_envelope

        envelope = _readiness_artifact_envelope(
            kind,
            team_id=team_id,
            run_id=run_id,
            authority_run_id=authority,
        )
        if not isinstance(envelope, dict) or not envelope:
            from .artifact_readback_registry import load_scoped_artifact_payload

            envelope = load_scoped_artifact_payload(
                kind,
                team_id=team_id,
                authority_run_id=authority,
                workflow_run_id=run_id,
            )
        if not isinstance(envelope, dict):
            return {}
        payload = envelope.get("payload")
        return dict(payload) if isinstance(payload, dict) else dict(envelope)

    package_body = _body("research_result_package")
    package = (
        package_body.get("package")
        if isinstance(package_body.get("package"), dict)
        else package_body
    )
    terminal = str(
        package.get("terminalReason")
        or package_body.get("terminalReason")
        or ""
    ).strip()
    decision = str(package.get("decisionKind") or package.get("operation") or "").strip()
    governance = _body("version_governance_record")
    operation = str(
        governance.get("operation")
        or governance.get("decision_kind")
        or decision
        or ""
    ).strip()
    if not terminal:
        terminal = str(governance.get("terminalReason") or "").strip()
    kind = _normalized_terminal_decision(operation or decision)
    if kind == "rollback_candidate":
        return "rolled_back", terminal or "rollback"
    if kind == "promote_candidate":
        return "promoted", terminal
    return "stopped", terminal or "formal_runner_unavailable"


def sync_run_succeeded(
    uow: Any,
    *,
    run_id: str,
    now_ms: int,
    completion_kind: str,
    terminal_reason: str,
    node_id: str = "result_package",
    actor_id: str = "graph-worker",
) -> bool:
    """Mark a STOP/rollback package as the run terminal. Idempotent."""
    run = uow.repository.get_run(run_id)
    if run is None or run.status in _TERMINAL_RUN:
        return False
    if run.status not in {
        RunStatus.RUNNING.value,
        RunStatus.BLOCKED.value,
        RunStatus.WAITING_HUMAN.value,
    }:
        return False
    uow.repository.update_run_status(
        run_id,
        run.team_id,
        RunStatus.SUCCEEDED.value,
        now_ms,
        active_node_id="",
        completion_kind=completion_kind,
        terminal_reason=terminal_reason,
        blocked_problem_json=None,
    )
    # Post-run delivery chain rides the same transaction: the outbox row is
    # committed atomically with the terminal transition, so a crash between
    # run close and worker pickup can never lose the orchestration.
    from .delivery_orchestration import enqueue_delivery_orchestration

    enqueue_delivery_orchestration(uow, run=run, now_ms=now_ms)
    sequence = uow.repository.advance_last_sequence(run_id, 1, now_ms)
    if sequence is None:
        return True
    uow.repository.insert_event(
        EventRecord(
            run_id=run_id,
            sequence=sequence,
            event_id=new_id("evt"),
            run_version=run.run_version,
            event_type="run_succeeded",
            actor_json=json.dumps(
                {"actorType": "system", "actorId": actor_id},
                ensure_ascii=False,
            ),
            correlation_id=run_id,
            causation_id=None,
            payload_json=json.dumps(
                {
                    "nodeId": node_id,
                    "completionKind": completion_kind,
                    "terminalReason": terminal_reason,
                },
                ensure_ascii=False,
            ),
            occurred_at_ms=now_ms,
        )
    )
    return True
