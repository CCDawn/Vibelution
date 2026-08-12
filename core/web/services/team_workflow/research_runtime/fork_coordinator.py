"""Checkpoint fork coordinator (T5.1-7).

Ledger transactions never perform checkpoint I/O. Child runs use threadId==runId
and resume from a parent checkpoint via ChallengeCupGraphCoordinator.fork_from_checkpoint
after the Ledger commit.
"""

from __future__ import annotations

from typing import Any, Callable

from core.research.workflow.challenge_cup_runtime import ChallengeCupGraphCoordinator


class ForkCoordinatorError(RuntimeError):
    def __init__(self, message: str, *, code: str = "fork_failed") -> None:
        super().__init__(message)
        self.code = code


def validate_parent_checkpoint(
    coordinator: ChallengeCupGraphCoordinator,
    *,
    parent_run_id: str,
    checkpoint_id: str,
) -> dict[str, Any]:
    checkpoint_id = str(checkpoint_id or "").strip()
    if not checkpoint_id:
        raise ForkCoordinatorError(
            "checkpointId is required for fork", code="checkpoint_required"
        )
    snapshot = coordinator.snapshot(parent_run_id)
    values = dict(snapshot.get("values") or {})
    if not values:
        raise ForkCoordinatorError(
            "parent run has no checkpoint state", code="checkpoint_missing"
        )
    current = str(snapshot.get("checkpointId") or "")
    if checkpoint_id == current:
        return {"checkpointId": checkpoint_id, "values": values}

    # Historical checkpoint must belong to the parent thread.
    try:
        graph, stack = coordinator._compile()  # noqa: SLF001 - intentional
        try:
            state = graph.get_state(
                {
                    "configurable": {
                        "thread_id": parent_run_id,
                        "checkpoint_ns": "",
                        "checkpoint_id": checkpoint_id,
                    }
                }
            )
            owned_values = dict(state.values or {})
            if not owned_values:
                raise ForkCoordinatorError(
                    "checkpointId does not belong to parent run",
                    code="checkpoint_not_owned",
                )
            return {"checkpointId": checkpoint_id, "values": owned_values}
        finally:
            stack.close()
    except ForkCoordinatorError:
        raise
    except Exception as exc:
        raise ForkCoordinatorError(
            f"checkpoint validation failed: {exc}",
            code="checkpoint_unreadable",
        ) from exc


def execute_checkpoint_fork(
    coordinator: ChallengeCupGraphCoordinator,
    *,
    parent_run_id: str,
    checkpoint_id: str,
    child_run_id: str,
    resume_node_id: str,
    state_patch: dict[str, Any] | None = None,
) -> str:
    """Call LangGraph fork outside any Ledger writer transaction."""
    validate_parent_checkpoint(
        coordinator,
        parent_run_id=parent_run_id,
        checkpoint_id=checkpoint_id,
    )
    try:
        return coordinator.fork_from_checkpoint(
            source_thread_id=parent_run_id,
            source_checkpoint_id=checkpoint_id,
            child_thread_id=child_run_id,
            resume_node_id=resume_node_id,
            state_patch=state_patch,
        )
    except Exception as exc:
        raise ForkCoordinatorError(
            f"checkpoint fork failed: {exc}", code="checkpoint_fork_failed"
        ) from exc


def schedule_post_commit_fork(
    uow: Any,
    *,
    coordinator_factory: Callable[[], ChallengeCupGraphCoordinator],
    parent_run_id: str,
    checkpoint_id: str,
    child_run_id: str,
    resume_node_id: str,
    on_failure: Callable[[Exception], None] | None = None,
) -> None:
    """Register after_commit hook; never runs inside the Ledger transaction."""

    def _run() -> None:
        try:
            coordinator = coordinator_factory()
            execute_checkpoint_fork(
                coordinator,
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
        except Exception as exc:
            if on_failure is not None:
                on_failure(exc)
            else:
                raise

    uow.after_commit(_run)
