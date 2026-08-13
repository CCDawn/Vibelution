"""CommandOffer builders split by command kind (T6.6)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from core.research.workflow.contracts import CommandOffer, WorkflowCommandKind
from core.research.workflow.ledger.records import NodeAttemptRecord, RunRecord
from core.research.workflow.models import ActorKind, WorkflowDefinition
from core.research.workflow.transitions import RunStatus, can_transition_run

from ..readiness import NodeReadinessService
from ..readiness.common import DomainReadinessContext
from .cancel_run import build_cancel_run_offer
from .extend_budget import build_extend_budget_offers
from .fork_revision import build_fork_revision_offers
from .rebind_node import build_rebind_node_offers
from .reconcile_run import build_reconcile_run_offer
from .resolve_human import build_resolve_human_offers
from .retry_node import build_retry_node_offers
from .start_node import build_start_node_offers


def build_command_offers(
    *,
    readiness_service: NodeReadinessService,
    context: DomainReadinessContext,
    team_id: str,
    run: RunRecord,
    definition: WorkflowDefinition,
    pending_human_tasks: Sequence[Any] = (),
    attempts: Sequence[NodeAttemptRecord] = (),
    evaluated_at_ms: int | None = None,
) -> list[CommandOffer]:
    offers: list[CommandOffer] = []
    offers.extend(
        build_start_node_offers(
            readiness_service=readiness_service,
            context=context,
            team_id=team_id,
            run=run,
            definition=definition,
            attempts=attempts,
            evaluated_at_ms=evaluated_at_ms,
        )
    )
    offers.extend(
        build_resolve_human_offers(
            run=run,
            definition=definition,
            pending_human_tasks=pending_human_tasks,
        )
    )
    offers.extend(
        build_retry_node_offers(
            run=run,
            definition=definition,
            attempts=attempts,
        )
    )
    offers.extend(build_rebind_node_offers(run=run, definition=definition))
    offers.extend(build_fork_revision_offers(run=run, definition=definition))
    offers.extend(build_extend_budget_offers(run=run))
    offers.append(build_reconcile_run_offer(run=run))
    offers.append(build_cancel_run_offer(run=run))
    return offers


def can_cancel_run(status: str) -> bool:
    try:
        current = RunStatus(status)
    except ValueError:
        return False
    return can_transition_run(current, RunStatus.CANCELLED) and current != RunStatus.CANCELLED
