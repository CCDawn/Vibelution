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
from .archive_run import build_archive_run_offer
from .cancel_run import build_cancel_run_offer
from .extend_budget import build_extend_budget_offers
from .fork_revision import build_fork_revision_offers
from .knowledge_collection import build_knowledge_collection_offers
from .rebind_node import build_rebind_node_offers
from .reconcile_run import build_reconcile_run_offer
from .resolve_human import build_resolve_human_offers
from .retry_node import build_retry_node_offers
from .start_node import build_start_node_offers

# Offer kinds that never move a run.  On a degraded run (the snapshot's
# substituted definition is diagnostic-only) these are the ONLY offers that
# may surface: a stale mutation must not even be renderable as a clickable
# action (plan §6.3).
_READ_ONLY_OFFER_COMMANDS = frozenset(
    {WorkflowCommandKind.INSPECT_KNOWLEDGE_COLLECTION}
)


def _is_registry_era_run(run: Any) -> bool:
    """Runs whose version identity lives in the definition registry.

    Mirrors the mutation gate in ``command_service``: pre-registry runs carry
    literal version ids (``challenge-cup-research-v2.1.0``) that the registry
    can never resolve — their read-layer substitution equals the executing
    legacy default, so legacy mutation semantics stay intact.  Registry-era
    (``wv-*``) runs whose pinned identity cannot be honored are the real
    degraded hazard and lose mutation offers.
    """
    version_id = str(getattr(run, "workflow_version_id", "") or "").strip()
    return version_id.startswith("wv-")


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
    revise_checkpoint_id: str | None = None,
    invocations: Sequence[Any] = (),
    definition_resolution: str = "pinned",
) -> list[CommandOffer]:
    degraded = (
        str(definition_resolution or "pinned").strip().lower() == "degraded"
        and _is_registry_era_run(run)
    )
    offers: list[CommandOffer] = []
    if not degraded:
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
                revise_checkpoint_id=revise_checkpoint_id,
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
        offers.extend(
            build_fork_revision_offers(
                run=run,
                definition=definition,
                revise_checkpoint_id=revise_checkpoint_id,
            )
        )
        offers.extend(build_extend_budget_offers(run=run))
        offers.append(build_reconcile_run_offer(run=run))
        offers.append(build_archive_run_offer(run=run))
        offers.append(build_cancel_run_offer(run=run))
    offers.extend(
        offer
        for offer in build_knowledge_collection_offers(
            run=run,
            invocations=invocations,
        )
        if offer.command in _READ_ONLY_OFFER_COMMANDS or not degraded
    )
    return offers


def can_cancel_run(status: str) -> bool:
    try:
        current = RunStatus(status)
    except ValueError:
        return False
    return can_transition_run(current, RunStatus.CANCELLED) and current != RunStatus.CANCELLED
