"""Project retryable adapter failures into one consistent workflow state."""

from __future__ import annotations

import json
from typing import Any

from core.research.workflow.ledger import EventRecord
from core.research.workflow.transitions import NodeAttemptStatus

from .block_projection import sync_run_blocked
from .blocked_reason import format_blocked_reason
from .ids import new_id


def apply_node_run_failure(
    uow: Any,
    *,
    run_id: str,
    node_run_id: str,
    node_id: str,
    problem: dict[str, Any],
    now_ms: int,
    actor_id: str,
    correlation_id: str,
) -> None:
    """Fail the attempt, block the retryable run, and emit both SSE facts."""
    problem_json = json.dumps(problem, ensure_ascii=False)
    uow.repository.update_attempt_status(
        node_run_id,
        NodeAttemptStatus.FAILED.value,
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
        "reason": format_blocked_reason(problem),
    }
    for offset, event_type in enumerate(("node_failed", "run_blocked"), start=1):
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
