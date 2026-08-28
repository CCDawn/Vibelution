"""ensure/inspect_knowledge_collection CommandOffers (knowledge sideflow).

The knowledge sideflow leaves the in-graph chain in main flow 3.0.0, so the
run snapshot needs its own offers for requesting and inspecting knowledge
collections.  Both commands are team-authorized (never operator-only):

- ``ensure_knowledge_collection``: available while the run is live (not
  terminal); held while a live invocation already targets the requested
  node lineage (the invocation idempotency would replay it anyway, so the
  offer points at inspection instead).
- ``inspect_knowledge_collection``: available on any non-archived run.

Rollout gating:
- ``mode = "off"``: both offers hidden — the disabled semantics stay
  unambiguous at the offer layer instead of surfacing blocked placeholders.
- ``mode = "shadow"``: inspection only.  Shadow is a comparison projection
  and must never create a real child run, so the ensure offer does not exist
  there (plan §10.1).
- ``mode = "on"``: both offers surface.
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
    from ..knowledge_rollout import (
        knowledge_ensure_enabled,
        knowledge_inspect_enabled,
    )

    ensure_enabled = knowledge_ensure_enabled()
    inspect_enabled = knowledge_inspect_enabled()
    if not ensure_enabled and not inspect_enabled:
        # mode="off": the sideflow surface stays invisible; no offer rows at
        # all so clients cannot even render a disabled placeholder.
        return []

    offers: list[CommandOffer] = []
    node_id = str(active_node_id or run.active_node_id or "").strip() or None

    if ensure_enabled and not _offer_blocked(run, invocations):
        offers.append(_ensure_offer(run, node_id=node_id, available=True, live=None))
    elif ensure_enabled:
        live = _live_invocation(invocations)
        offers.append(
            _ensure_offer(run, node_id=node_id, available=False, live=live)
        )

    if inspect_enabled:
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


def _offer_blocked(run: RunRecord, invocations: Sequence[Any]) -> bool:
    if str(run.status) in _TERMINAL_RUN_STATUSES:
        return True
    return _live_invocation(invocations) is not None


def _live_invocation(invocations: Sequence[Any]) -> Any | None:
    for invocation in invocations:
        if (
            str(getattr(invocation, "status", "") or "")
            in _LIVE_INVOCATION_STATUSES
        ):
            return invocation
    return None


def _ensure_offer(
    run: RunRecord,
    *,
    node_id: str | None,
    available: bool,
    live: Any | None,
) -> CommandOffer:
    if available:
        return CommandOffer(
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
    if str(run.status) in _TERMINAL_RUN_STATUSES:
        return CommandOffer(
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
    return CommandOffer(
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
            "invocationId": str(live.invocation_id),
        },
    )
