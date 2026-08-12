"""Durable checkpoint_fork outbox worker (T5.1 P1).

Checkpoint I/O never runs inside a Ledger writer transaction. The fork command
inserts a pending ``checkpoint_fork`` outbox row; this worker leases it, forks
LangGraph state, then — only on success — inserts the child ``graph_dispatch``.
Failures mark the child run ``reconciliation_required`` and fail the outbox.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from core.research.workflow.challenge_cup_runtime import ChallengeCupGraphCoordinator
from core.research.workflow.ledger import WorkflowLedgerStore, outbox as outbox_api
from core.research.workflow.transitions import NodeAttemptStatus

from .fork_coordinator import ForkCoordinatorError, execute_checkpoint_fork
from .graph_dispatch_factory import build_graph_dispatch_record


class CheckpointForkWorker:
    def __init__(
        self,
        *,
        store: WorkflowLedgerStore,
        coordinator: ChallengeCupGraphCoordinator,
        owner_id: str = "checkpoint-fork-worker",
        lease_ms: int = 30_000,
        now_provider: Callable[[], int] | None = None,
        commit_hook: Callable[[], None] | None = None,
    ) -> None:
        self._store = store
        self._coordinator = coordinator
        self._owner = owner_id
        self._lease_ms = lease_ms
        self._now = now_provider or (lambda: int(time.time() * 1000))
        self._commit_hook = commit_hook

    def _submit(self, mutate, *, force_flush: bool = True):
        hook = self._commit_hook

        def wrapped(uow):
            if hook is not None:
                uow.after_commit(hook)
            return mutate(uow)

        return self._store.submit(wrapped, force_flush=force_flush)

    def run_once(self, limit: int = 8) -> int:
        leased = outbox_api.lease_ready_actions(
            self._store,
            owner=self._owner,
            now_ms=self._now(),
            limit=limit,
            lease_ms=self._lease_ms,
            action_kinds=("checkpoint_fork",),
        )
        for action in leased:
            self._handle(action)
        return len(leased)

    def _handle(self, action: Any) -> None:
        payload = json.loads(action.payload_json)
        parent_run_id = str(payload.get("parentRunId") or "").strip()
        checkpoint_id = str(payload.get("checkpointId") or "").strip()
        child_run_id = str(payload.get("childRunId") or action.run_id).strip()
        resume_node_id = str(payload.get("resumeNodeId") or "").strip()
        command_id = str(payload.get("commandId") or action.command_id or "").strip()
        node_run_id = str(payload.get("nodeRunId") or action.node_run_id or "").strip()

        # execute_checkpoint_fork is crash-replay idempotent: an existing child
        # checkpoint for this child_run_id at resume_node is treated as success.
        try:
            execute_checkpoint_fork(
                self._coordinator,
                parent_run_id=parent_run_id,
                checkpoint_id=checkpoint_id,
                child_run_id=child_run_id,
                resume_node_id=resume_node_id,
                state_patch={
                    "run_id": child_run_id,
                    "parent_run_id": parent_run_id,
                    "active_node_id": resume_node_id,
                    "active_attempt": 1,
                    "node_attempts": {resume_node_id: 1},
                },
            )
        except ForkCoordinatorError as exc:
            self._fail_fork(
                action,
                child_run_id=child_run_id,
                node_run_id=node_run_id,
                problem={
                    "code": getattr(exc, "code", None) or "checkpoint_fork_failed",
                    "detail": str(exc),
                    "parentRunId": parent_run_id,
                    "checkpointId": checkpoint_id,
                },
            )
            return
        except Exception as exc:
            self._fail_fork(
                action,
                child_run_id=child_run_id,
                node_run_id=node_run_id,
                problem={
                    "code": "checkpoint_fork_failed",
                    "detail": str(exc),
                    "parentRunId": parent_run_id,
                    "checkpointId": checkpoint_id,
                },
            )
            return

        now_ms = self._now()

        def mutate(uow):
            child = uow.repository.get_run(child_run_id)
            attempt = uow.repository.get_attempt(node_run_id) if node_run_id else None
            if child is None or attempt is None or not command_id:
                uow.repository.fail_outbox(
                    action.action_id,
                    self._owner,
                    now_ms,
                    problem_json=json.dumps(
                        {
                            "code": "checkpoint_fork_incomplete",
                            "detail": "child run/attempt/command missing after fork",
                        },
                        ensure_ascii=False,
                    ),
                )
                return
            # Child graph_dispatch only after durable checkpoint fork succeeds.
            existing = uow.repository.execute(
                "SELECT action_id FROM outbox_actions "
                "WHERE run_id = ? AND action_kind = 'graph_dispatch' "
                "AND node_run_id = ? LIMIT 1",
                (child_run_id, node_run_id),
            ).fetchone()
            if existing is None:
                uow.repository.insert_outbox(
                    build_graph_dispatch_record(
                        run=child,
                        attempt=attempt,
                        command_id=command_id,
                        dispatch_kind="start",
                        now_ms=now_ms,
                    )
                )
            uow.repository.ack_outbox(action.action_id, self._owner, now_ms)

        self._submit(mutate, force_flush=True).result(timeout=30)

    def _fail_fork(
        self,
        action: Any,
        *,
        child_run_id: str,
        node_run_id: str,
        problem: dict[str, Any],
    ) -> None:
        now_ms = self._now()
        problem_json = json.dumps(problem, ensure_ascii=False)

        def mutate(uow):
            uow.repository.fail_outbox(
                action.action_id, self._owner, now_ms, problem_json=problem_json
            )
            uow.repository.execute(
                "UPDATE workflow_runs SET status = 'reconciliation_required', "
                "blocked_problem_json = ?, updated_at_ms = ? WHERE run_id = ?",
                (problem_json, now_ms, child_run_id),
            )
            if node_run_id:
                attempt = uow.repository.get_attempt(node_run_id)
                if attempt is not None and attempt.status in {
                    NodeAttemptStatus.STARTING.value,
                    NodeAttemptStatus.DISPATCHING.value,
                }:
                    uow.repository.update_attempt_status(
                        node_run_id,
                        NodeAttemptStatus.FAILED.value,
                        now_ms,
                        problem_json=problem_json,
                        finished_at_ms=now_ms,
                    )

        self._submit(mutate, force_flush=True).result(timeout=30)
