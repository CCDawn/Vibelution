"""Graph dispatch governance — P2-e scheduling guardrails.

Borrowed from ZCode's ``workflow/scheduler.ts`` executor loop, adapted to the
durable outbox/graph-dispatch architecture (the reference pauses an in-process
loop; here the hold must survive process restarts, so it is a ledger status):

- **Consecutive-error pause** — after a node attempt lands ``failed``, the
  trailing streak of consecutive failed attempts for the run is recomputed
  from the ledger; at ``max_consecutive_errors`` the run transitions to
  ``PAUSED`` with a structured reason. Like the reference, the pause waits
  for in-flight work to settle: nothing in flight is cancelled, and only
  NEW work (``start`` dispatches) is gated off — settlement receipts of
  already-running nodes keep landing.
- **Deadlock pause** — a serial maintenance sweep classifies live runs whose
  ready set is empty (no active attempt, no queued outbox action, no
  accepted-handoff successor awaiting repair) while a blocked-node inventory
  is non-empty, and parks them as ``PAUSED(deadlock)`` with that inventory.
  Ordinary ``blocked`` runs are deliberately skipped: BLOCKED already is the
  designed operator-visible hold with recovery offers, and flipping it would
  change existing scheduling behavior. Idempotent: already-paused runs are
  never re-judged.
- **Per-node-type WIP cap** — before invoking a ``start`` dispatch, count the
  in-flight attempts of that node type across the ledger (excluding the
  dispatch's own attempt); at the cap the action is requeued (short retry) so
  the ready node simply waits for the next round — never blocked, never
  STALE. Disabled by default (no limit configured = unlimited).

PAUSED is a recoverable hold, not a failure: ``resume_from_pause`` (and the
ordinary start/retry command path, which writes ``RUNNING``) clears it.

Behavior conservation: with no consecutive errors, no deadlock and no WIP
limits configured, none of these paths mutate any ledger row.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from core.research.workflow.ledger import EventRecord, WorkflowLedgerStore
from core.research.workflow.transitions import RunStatus, can_pause_run

from .ids import new_id

MAX_CONSECUTIVE_ERRORS_ENV = "VIBELUTION_WORKFLOW_MAX_CONSECUTIVE_ERRORS"
DEADLOCK_PAUSE_ENV = "VIBELUTION_WORKFLOW_DEADLOCK_PAUSE"
NODE_TYPE_WIP_LIMIT_ENV = "VIBELUTION_WORKFLOW_NODE_TYPE_WIP_LIMIT"

# Default consecutive-error threshold: five failed attempts in a row park the
# run instead of leaving it silently cycling on retry. ``0`` (or a negative
# value) via the env disables the pause entirely.
DEFAULT_MAX_CONSECUTIVE_ERRORS = 5

# Requeue delay for a ``start`` dispatch deferred by the paused/WIP gate: long
# enough not to busy-loop a claim cycle, short enough that resume/WIP relief
# redrives without operator action.
GATED_DISPATCH_RETRY_MS = 60_000
WIP_GATE_RETRY_MS = 1_000

# Ledger-active attempt statuses: work that is either executing or waiting on
# a running execution. ``waiting_human`` counts as active so a run holding a
# human gate is never classified as deadlocked.
ACTIVE_ATTEMPT_STATUSES = frozenset(
    {"starting", "dispatching", "running", "waiting_human"}
)

# Sweep page size: one writer transaction classifies at most this many live
# runs per maintenance tick.
DEADLOCK_SWEEP_LIMIT = 100

CONSECUTIVE_ERRORS_PAUSE_CODE = "consecutive_errors_paused"
DEADLOCK_PAUSE_CODE = "deadlock_paused"
RUN_PAUSED_EVENT_TYPE = "run_paused"


@dataclass(frozen=True)
class GovernancePolicy:
    """Frozen governance knobs; ``from_env()`` is the production default."""

    max_consecutive_errors: int | None = DEFAULT_MAX_CONSECUTIVE_ERRORS
    deadlock_detection_enabled: bool = True
    node_type_wip_limits: Mapping[str, int] = field(default_factory=dict)
    default_node_wip_limit: int | None = None

    @classmethod
    def from_env(cls) -> GovernancePolicy:
        raw_errors = os.environ.get(MAX_CONSECUTIVE_ERRORS_ENV, "")
        max_errors: int | None = DEFAULT_MAX_CONSECUTIVE_ERRORS
        if raw_errors.strip():
            try:
                parsed = int(str(raw_errors).strip())
            except (TypeError, ValueError):
                parsed = DEFAULT_MAX_CONSECUTIVE_ERRORS
            max_errors = parsed if parsed > 0 else None

        raw_deadlock = os.environ.get(DEADLOCK_PAUSE_ENV, "").strip().lower()
        deadlock_enabled = raw_deadlock not in {"0", "false", "off", "no"}

        limits: dict[str, int] = {}
        default_limit: int | None = None
        raw_wip = os.environ.get(NODE_TYPE_WIP_LIMIT_ENV, "").strip()
        if raw_wip:
            default_limit = _parse_wip_spec(raw_wip, limits)

        return cls(
            max_consecutive_errors=max_errors,
            deadlock_detection_enabled=deadlock_enabled,
            node_type_wip_limits=limits,
            default_node_wip_limit=default_limit,
        )

    @classmethod
    def disabled(cls) -> GovernancePolicy:
        """All guardrails off — the pre-P2-e scheduling behavior."""
        return cls(
            max_consecutive_errors=None,
            deadlock_detection_enabled=False,
            node_type_wip_limits={},
            default_node_wip_limit=None,
        )

    @property
    def pause_gates_enabled(self) -> bool:
        """Whether ``start`` dispatches must check the run's paused status."""
        return self.max_consecutive_errors is not None or (
            self.deadlock_detection_enabled
        )

    @property
    def wip_enabled(self) -> bool:
        return self.default_node_wip_limit is not None or bool(
            self.node_type_wip_limits
        )

    def wip_limit_for(self, node_id: str) -> int | None:
        """Per-node-type in-flight cap; ``None`` means unlimited."""
        override = self.node_type_wip_limits.get(str(node_id))
        if override is not None:
            return override if override > 0 else None
        return self.default_node_wip_limit


def _parse_wip_spec(raw: str, limits: dict[str, int]) -> int | None:
    """Parse ``NODE_TYPE_WIP_LIMIT``: a plain int or a JSON {nodeId: limit}."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return None
        if isinstance(parsed, dict):
            for key, item in parsed.items():
                try:
                    node_limit = int(item)
                except (TypeError, ValueError):
                    continue
                if node_limit > 0:
                    limits[str(key)] = node_limit
        return None
    return value if value > 0 else None


def consecutive_error_count(attempts: list[Any]) -> int:
    """Trailing streak of consecutive FAILED attempts, ledger-derived.

    ``attempts`` MUST be in commit order (see
    :func:`list_attempts_commit_order`); ``STALE`` rows are superseded
    history and skipped. Any terminal outcome other than ``failed`` resets
    the streak — a success, a designed blocked hold, a human gate or a
    cancellation all mean the operator/loop made progress or changed state
    since the last error.
    """
    streak = 0
    for record in reversed(list(attempts)):
        status = str(getattr(record, "status", "") or "")
        if status == "stale":
            continue
        if status == "failed":
            streak += 1
            continue
        break
    return streak


def list_attempts_commit_order(repository: Any, run_id: str) -> list[Any]:
    """Attempt rows in commit order.

    ``list_attempts`` orders by ``(attempt, node_id)`` which interleaves
    nodes of the same attempt number — a trailing streak needs the order the
    attempts were actually committed in. ``started_at_ms`` is the primary
    key; the insert rowid breaks frozen-clock ties (tests) the same way the
    writer serialized them.
    """
    rows = repository.execute(
        """
        SELECT node_run_id, run_id, node_id, attempt, actor_kind, status,
               command_id, binding_snapshot_id, input_snapshot_hash,
               pending_action_id, execution_anchor_id, retry_of_node_run_id,
               problem_json, started_at_ms, updated_at_ms, finished_at_ms
        FROM node_attempts
        WHERE run_id = ?
        ORDER BY started_at_ms ASC, rowid ASC
        """,
        (run_id,),
    ).fetchall()
    records: list[Any] = []
    for row in rows:
        record = repository._row_attempt(row)
        if record is not None:
            records.append(record)
    return records


def consecutive_errors_pause_problem(
    *,
    streak: int,
    threshold: int,
    last_node_id: str,
    last_node_run_id: str,
) -> dict[str, Any]:
    """Structured pause reason stored on ``workflow_runs.blocked_problem_json``."""
    return {
        "code": CONSECUTIVE_ERRORS_PAUSE_CODE,
        "pauseKind": "consecutive_errors",
        "detail": (
            f"连续 {streak} 次节点尝试失败，达到阈值 {threshold}，"
            "调度已暂停；在飞任务收口后不再派发新节点，重试入口可恢复"
        ),
        "consecutiveErrors": streak,
        "threshold": threshold,
        "lastNodeId": str(last_node_id or ""),
        "lastNodeRunId": str(last_node_run_id or ""),
    }


def maybe_pause_for_consecutive_errors(
    repository: Any,
    *,
    run_id: str,
    policy: GovernancePolicy,
    now_ms: int,
    actor_id: str,
    last_node_id: str = "",
    last_node_run_id: str = "",
) -> bool:
    """Pause the run when the consecutive-failure streak reaches the threshold.

    MUST run inside the same writer transaction that landed the failed
    attempt, so the streak read and the pause write are serialized against
    every other dispatch commit (no pause/successor race). Idempotent: a run
    already paused or outside the pauseable live statuses is left untouched.
    """
    threshold = policy.max_consecutive_errors
    if threshold is None or threshold <= 0:
        return False
    run = repository.get_run(run_id)
    if run is None:
        return False
    try:
        current = RunStatus(str(run.status))
    except ValueError:
        return False
    if not can_pause_run(current):
        return False
    streak = consecutive_error_count(
        list_attempts_commit_order(repository, run_id)
    )
    if streak < threshold:
        return False
    problem = consecutive_errors_pause_problem(
        streak=streak,
        threshold=threshold,
        last_node_id=last_node_id,
        last_node_run_id=last_node_run_id,
    )
    return _commit_pause(
        repository,
        run=run,
        problem=problem,
        now_ms=now_ms,
        actor_id=actor_id,
    )


@dataclass(frozen=True)
class DeadlockVerdict:
    problem: dict[str, Any]
    blocked_nodes: tuple[dict[str, Any], ...]


def classify_deadlock(
    attempts: list[Any],
    live_outbox_count: int,
    accepted_handoff_successors: set[str],
) -> DeadlockVerdict | None:
    """Deadlock = ready empty + nothing active + blocked inventory non-empty.

    ``ready empty`` is read from durable facts: no active attempt, no queued
    or leased outbox action, and no accepted handoff whose successor node
    still lacks an attempt (that state is repairable by the existing sweeps,
    so it counts as ready work rather than deadlock).
    """
    if live_outbox_count > 0:
        return None
    latest_by_node: dict[str, Any] = {}
    for record in attempts:
        node_id = str(getattr(record, "node_id", "") or "")
        if not node_id:
            continue
        existing = latest_by_node.get(node_id)
        if existing is None or int(getattr(record, "attempt", 0)) >= int(
            getattr(existing, "attempt", 0)
        ):
            latest_by_node[node_id] = record
    for record in latest_by_node.values():
        if str(getattr(record, "status", "") or "") in ACTIVE_ATTEMPT_STATUSES:
            return None
    for successor in accepted_handoff_successors:
        if successor not in latest_by_node:
            # An accepted handoff without an attempt is ready work the repair
            # sweeps will redispatch — not a deadlock.
            return None
    blocked_nodes: list[dict[str, Any]] = []
    for node_id, record in sorted(latest_by_node.items()):
        if str(getattr(record, "status", "") or "") != "blocked":
            continue
        problem: dict[str, Any] = {}
        raw_problem = getattr(record, "problem_json", None)
        if raw_problem:
            try:
                loaded = json.loads(raw_problem)
                if isinstance(loaded, dict):
                    problem = loaded
            except (TypeError, ValueError):
                problem = {"detail": str(raw_problem)[:200]}
        blocked_nodes.append(
            {
                "nodeId": node_id,
                "nodeRunId": str(getattr(record, "node_run_id", "") or ""),
                "code": str(problem.get("code") or ""),
                "detail": str(problem.get("detail") or "")[:200],
            }
        )
    if not blocked_nodes:
        return None
    detail = "; ".join(
        f"{item['nodeId']}({item['code'] or 'blocked'})" for item in blocked_nodes[:5]
    )
    return DeadlockVerdict(
        problem={
            "code": DEADLOCK_PAUSE_CODE,
            "pauseKind": "deadlock",
            "detail": (
                "就绪队列为空、无在飞任务且存在阻塞节点，图调度无法继续推进，"
                "已暂停；解除阻塞后通过重试/恢复入口继续"
                f"：{detail}"
            ),
            "blockedNodes": blocked_nodes,
        },
        blocked_nodes=tuple(blocked_nodes),
    )


def run_deadlock_sweep(
    store: WorkflowLedgerStore,
    *,
    policy: GovernancePolicy,
    now_ms: int,
    actor_id: str = "graph-worker",
) -> int:
    """Park stranded live runs as ``PAUSED(deadlock)``; returns pauses taken.

    Runs on the serial maintenance lane. One writer transaction classifies
    and pauses, so the read of attempts/outbox and the status write are
    serialized against every dispatch commit — a run that gained active work
    between page and verdict is simply not deadlocked anymore.
    """
    if not policy.deadlock_detection_enabled:
        return 0
    live_statuses = (
        RunStatus.RUNNING.value,
        RunStatus.WAITING_HUMAN.value,
    )

    def mutate(uow: Any) -> int:
        repository = uow.repository
        rows = repository.execute(
            """
            SELECT run_id, team_id, run_version, status
            FROM workflow_runs
            WHERE status IN (?, ?)
            ORDER BY run_id ASC
            LIMIT ?
            """,
            (*live_statuses, DEADLOCK_SWEEP_LIMIT),
        ).fetchall()
        paused = 0
        for row in rows:
            run = repository.get_run(str(row[0] or ""))
            if run is None:
                continue
            try:
                current = RunStatus(str(run.status))
            except ValueError:
                continue
            if not can_pause_run(current):
                continue
            attempts = repository.list_attempts(run.run_id)
            queued = _count_live_outbox(repository, run.run_id)
            successors = _accepted_handoff_successors(repository, run.run_id)
            verdict = classify_deadlock(attempts, queued, successors)
            if verdict is None:
                continue
            if _commit_pause(
                repository,
                run=run,
                problem=verdict.problem,
                now_ms=now_ms,
                actor_id=actor_id,
            ):
                paused += 1
        return paused

    return int(store.submit(mutate, force_flush=True).result(timeout=30))


def _count_live_outbox(repository: Any, run_id: str) -> int:
    """Pending (queued) plus leased (in-flight) outbox actions for the run."""
    row = repository.execute(
        """
        SELECT COUNT(*) FROM outbox_actions
        WHERE run_id = ? AND status IN ('pending', 'leased')
        """,
        (run_id,),
    ).fetchone()
    return int(row[0] or 0) if row is not None else 0


def _accepted_handoff_successors(repository: Any, run_id: str) -> set[str]:
    rows = repository.execute(
        """
        SELECT to_node_id FROM handoffs
        WHERE run_id = ? AND status = 'accepted'
        """,
        (run_id,),
    ).fetchall()
    return {str(row[0] or "") for row in rows if str(row[0] or "")}


def _commit_pause(
    repository: Any,
    *,
    run: Any,
    problem: dict[str, Any],
    now_ms: int,
    actor_id: str,
) -> bool:
    if not repository.update_run_status(
        run.run_id,
        run.team_id,
        RunStatus.PAUSED.value,
        now_ms,
        active_node_id=str(getattr(run, "active_node_id", "") or ""),
        blocked_problem_json=json.dumps(problem, ensure_ascii=False),
    ):
        return False
    sequence = repository.advance_last_sequence(run.run_id, 1, now_ms)
    if sequence is None:
        return True
    repository.insert_event(
        EventRecord(
            run_id=run.run_id,
            sequence=sequence,
            event_id=new_id("evt"),
            run_version=run.run_version,
            event_type=RUN_PAUSED_EVENT_TYPE,
            actor_json=json.dumps(
                {"actorType": "system", "actorId": actor_id},
                ensure_ascii=False,
            ),
            correlation_id=run.run_id,
            causation_id=None,
            payload_json=json.dumps(problem, ensure_ascii=False),
            occurred_at_ms=now_ms,
        )
    )
    return True


def active_attempt_counts_by_node(repository: Any) -> dict[str, int]:
    """In-flight attempt counts per node type across the whole ledger."""
    placeholders = ", ".join("?" for _ in ACTIVE_ATTEMPT_STATUSES)
    rows = repository.execute(
        f"""
        SELECT node_id, COUNT(*) FROM node_attempts
        WHERE status IN ({placeholders})
        GROUP BY node_id
        """,
        tuple(sorted(ACTIVE_ATTEMPT_STATUSES)),
    ).fetchall()
    return {str(row[0] or ""): int(row[1] or 0) for row in rows}


_ALLOWED_RESUME_TARGETS = frozenset(
    {
        RunStatus.RUNNING,
        RunStatus.WAITING_HUMAN,
        RunStatus.BLOCKED,
        RunStatus.RECONCILIATION_REQUIRED,
    }
)


def resume_from_pause(
    store: WorkflowLedgerStore,
    *,
    run_id: str,
    team_id: str,
    now_ms: int,
    actor_id: str = "operator",
    target: RunStatus = RunStatus.RUNNING,
) -> bool:
    """Explicit recovery entry: clear PAUSED back to a live status.

    The ordinary start/retry command path clears the pause implicitly by
    writing ``RUNNING``; this function is the direct operator/worker entry
    for redrives that bypass a command (e.g. a scheduler sweep resuming after
    the blocking condition is gone).
    """
    if target not in _ALLOWED_RESUME_TARGETS:
        raise ValueError(f"illegal resume target {target.value}")

    def mutate(uow: Any) -> bool:
        repository = uow.repository
        run = repository.get_run(run_id)
        if run is None or str(run.status) != RunStatus.PAUSED.value:
            return False
        if not repository.update_run_status(
            run_id,
            team_id,
            target.value,
            now_ms,
            active_node_id=str(getattr(run, "active_node_id", "") or ""),
            blocked_problem_json=None,
        ):
            return False
        sequence = repository.advance_last_sequence(run_id, 1, now_ms)
        if sequence is None:
            return True
        repository.insert_event(
            EventRecord(
                run_id=run_id,
                sequence=sequence,
                event_id=new_id("evt"),
                run_version=run.run_version,
                event_type="run_resumed",
                actor_json=json.dumps(
                    {"actorType": "system", "actorId": actor_id},
                    ensure_ascii=False,
                ),
                correlation_id=run_id,
                causation_id=None,
                payload_json=json.dumps(
                    {"resumedFromPause": True, "target": target.value},
                    ensure_ascii=False,
                ),
                occurred_at_ms=now_ms,
            )
        )
        return True

    return bool(store.submit(mutate, force_flush=True).result(timeout=30))
