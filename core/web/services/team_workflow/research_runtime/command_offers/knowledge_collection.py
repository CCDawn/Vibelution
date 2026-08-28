"""ensure/inspect_knowledge_collection CommandOffers (knowledge sideflow).

The knowledge sideflow leaves the in-graph chain in main flow 3.0.0, so the
run snapshot needs its own offers for requesting and inspecting knowledge
collections.  Both commands are team-authorized (never operator-only):

- ``ensure_knowledge_collection``: available while the run is live (not
  terminal); held while a live invocation already targets the requested
  node lineage (the invocation idempotency would replay it anyway, so the
  offer points at inspection instead).
- ``inspect_knowledge_collection``: available on any non-archived run.

Rollout gating: with ``[research.knowledge_sideflow] mode = "off"`` both
offers are hidden from the snapshot entirely — the disabled semantics stay
unambiguous at the offer layer instead of surfacing blocked placeholders.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from core.research.workflow.contracts import CommandOffer, WorkflowCommandKind
from core.research.workflow.ledger.records import RunRecord

_TERMINAL_RUN_STATUSES = frozenset(
    {"succeeded", "failed", "cancelled", "archived"}
)
_LIVE_INVOCATION_STATUSES = frozenset(
    {"pending", "child_created", "running", "awaiting_handoff"}
)


def build_knowledge_collection_offers(
    *,
    run: RunRecord,
    invocations: Sequence[Any] = (),
    active_node_id: str | None = None,
) -> list[CommandOffer]:
    """One ensure offer anchored at the run's active node plus one inspect
    offer for the whole run."""
    from ..knowledge_rollout import knowledge_commands_enabled

    if not knowledge_commands_enabled():
        # mode="off": the sideflow surface stays invisible; no offer rows at
        # all so clients cannot even render a disabled placeholder.
        return []

    offers: list[CommandOffer] = []

    if str(run.status) in _TERMINAL_RUN_STATUSES:
        offers.append(
            CommandOffer(
                command=WorkflowCommandKind.ENSURE_KNOWLEDGE_COLLECTION,
                node_id=None,
                available=False,
                label="发起知识搜集",
                reason_code="run_terminal",
                blocker_ids=("run_terminal",),
                idempotency_key=(
                    f"offer:{run.run_id}:ensure_knowledge_collection:"
                    f"v{run.run_version}"
                ),
                expected_run_version=run.run_version,
            )
        )
    else:
        node_id = str(active_node_id or run.active_node_id or "").strip() or None
        live = [
            invocation
            for invocation in invocations
            if str(getattr(invocation, "status", "") or "")
            in _LIVE_INVOCATION_STATUSES
        ]
        if live:
            offers.append(
                CommandOffer(
                    command=WorkflowCommandKind.ENSURE_KNOWLEDGE_COLLECTION,
                    node_id=node_id,
                    available=False,
                    label="发起知识搜集",
                    reason_code="knowledge_collection_in_flight",
                    blocker_ids=("knowledge_collection_in_flight",),
                    idempotency_key=(
                        f"offer:{run.run_id}:ensure_knowledge_collection:"
                        f"v{run.run_version}"
                    ),
                    expected_run_version=run.run_version,
                    payload={
                        "invocationId": str(live[0].invocation_id),
                    },
                )
            )
        else:
            offers.append(
                CommandOffer(
                    command=WorkflowCommandKind.ENSURE_KNOWLEDGE_COLLECTION,
                    node_id=node_id,
                    available=True,
                    label="发起知识搜集",
                    reason_code="knowledge_collection_available",
                    blocker_ids=(),
                    idempotency_key=(
                        f"offer:{run.run_id}:ensure_knowledge_collection:"
                        f"v{run.run_version}"
                    ),
                    expected_run_version=run.run_version,
                    payload={},
                )
            )

    inspect_available = str(run.status) != "archived"
    offers.append(
        CommandOffer(
            command=WorkflowCommandKind.INSPECT_KNOWLEDGE_COLLECTION,
            node_id=None,
            available=inspect_available,
            label="查看知识搜集进度",
            reason_code=(
                "inspect_available" if inspect_available else "run_archived"
            ),
            blocker_ids=() if inspect_available else ("run_archived",),
            idempotency_key=(
                f"offer:{run.run_id}:inspect_knowledge_collection:"
                f"v{run.run_version}"
            ),
            expected_run_version=run.run_version,
        )
    )
    return offers
