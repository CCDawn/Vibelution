"""Compatibility facade — prefer ``command_offers.build_command_offers``."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from core.research.workflow.contracts import CommandOffer
from core.research.workflow.ledger.records import NodeAttemptRecord, RunRecord
from core.research.workflow.models import WorkflowDefinition

from .command_offers import build_command_offers as _build
from .readiness import NodeReadinessService
from .readiness.common import DomainReadinessContext


def build_command_offers(
    *,
    readiness_service: NodeReadinessService,
    context: DomainReadinessContext,
    team_id: str,
    run_id: str | None = None,
    run_version: int | None = None,
    run: RunRecord | None = None,
    definition: WorkflowDefinition,
    pending_human_tasks: Sequence[Any] = (),
    attempts: Sequence[NodeAttemptRecord] = (),
    evaluated_at_ms: int | None = None,
    revise_checkpoint_id: str | None = None,
) -> list[CommandOffer]:
    if run is None:
        if run_id is None or run_version is None:
            raise TypeError("build_command_offers requires run= or run_id+run_version")
        # Legacy callers: synthesize a minimal RunRecord for offer signing.
        run = RunRecord(
            run_id=run_id,
            team_id=team_id,
            workflow_id=definition.workflowId,
            workflow_version_id=definition.schemaVersion,
            thread_id=f"thread-{run_id}",
            project_id="",
            question_id="",
            status="running",
            run_version=run_version,
            last_event_sequence=0,
            input_snapshot_json="{}",
            input_snapshot_hash="",
            safety_limits_json="{}",
            binding_snapshot_set_id="",
            active_node_id=None,
            parent_run_id=None,
            forked_from_checkpoint_id=None,
            completion_kind=None,
            terminal_reason=None,
            blocked_problem_json=None,
            created_at_ms=0,
            updated_at_ms=0,
            completed_at_ms=None,
        )
    return _build(
        readiness_service=readiness_service,
        context=context,
        team_id=team_id,
        run=run,
        definition=definition,
        pending_human_tasks=pending_human_tasks,
        attempts=attempts,
        evaluated_at_ms=evaluated_at_ms,
        revise_checkpoint_id=revise_checkpoint_id,
    )
