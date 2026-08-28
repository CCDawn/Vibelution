"""Knowledge absorption -> readiness re-check -> successor attempt.

The knowledge sideflow consumer (``absorb_knowledge_result``) never creates
attempts itself.  This module owns the post-absorption hook: after one
``knowledge_result_available`` payload is durably absorbed into the parent
run, the affected node's readiness is re-checked and — only when the
readiness authority says the node can actually execute — a new attempt is
created through the workflow command service (the single write entry), so
idempotency, version CAS and readiness all apply.

Fail-closed properties:

- An unreadable payload/invocation/parent is advisory: the hook records a
  runtime-scene event at most and never raises.
- ``NodeNotReadyError`` (e.g. the accepted-knowledge-package gate still
  blocked by other missing evidence) means NO attempt and NO adapter
  dispatch is created — the node stays blocked/retryable with its blockers.
- The parent checkpoint is never rewritten; the attempt reuses the
  existing START_NODE mechanism at the requesting node.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.research.workflow.contracts import (
    ActorRef,
    CommandRequest,
    WorkflowCommandKind,
)
from core.research.workflow.contracts.knowledge_sideflow import (
    KNOWLEDGE_RESULT_AVAILABLE_EVENT_TYPE,
)
from core.research.workflow.ledger import (
    CommandNotAllowedError,
    IdempotencyConflictError,
    RunVersionConflictError,
    WorkflowLedgerStore,
)

from ..command_service import WorkflowCommandError

_LIVE_ATTEMPT_STATUSES = frozenset(
    {"starting", "dispatching", "running", "waiting_human"}
)
_SKIP_PARENT_STATUSES = frozenset(
    {"archived", "cancelled", "succeeded", "failed"}
)


def build_knowledge_readiness_recheck(
    *,
    store: WorkflowLedgerStore,
    command_service: Any = None,
    readiness_invalidate: Callable[[str, str], None] | None = None,
    now_provider: Callable[[], int] | None = None,
) -> Callable[[dict], None]:
    """Build the ``readiness_recheck`` callback for the event-publish worker.

    ``command_service`` should be the workflow command service; when it is
    omitted (unit tests / dry runs) the hook only invalidates readiness
    caches and records the skip without creating attempts.
    """

    def recheck(payload: dict) -> None:
        try:
            _recheck_once(
                payload,
                store=store,
                command_service=command_service,
                readiness_invalidate=readiness_invalidate,
                now_provider=now_provider,
            )
        except Exception:  # noqa: BLE001 - the re-check is advisory by contract
            _record_recheck_skip(payload, "recheck_error")

    return recheck


def _recheck_once(
    payload: dict,
    *,
    store: WorkflowLedgerStore,
    command_service: Any,
    readiness_invalidate: Callable[[str, str], None] | None,
    now_provider: Callable[[], int] | None,
) -> None:
    if not isinstance(payload, dict):
        return
    if str(payload.get("eventType") or "") != KNOWLEDGE_RESULT_AVAILABLE_EVENT_TYPE:
        return
    consumer_run_id = str(payload.get("consumerRunId") or "").strip()
    invocation_id = str(payload.get("invocationId") or "").strip()
    if not consumer_run_id or not invocation_id:
        return
    parent = store.get_run(consumer_run_id)
    if parent is None:
        _record_recheck_skip(payload, "unknown_parent_run")
        return
    if str(parent.status) in _SKIP_PARENT_STATUSES:
        _record_recheck_skip(payload, f"parent_{parent.status}")
        return
    invocation = store.read(lambda repo: repo.get_knowledge_invocation(invocation_id))
    if invocation is None or str(invocation.parent_run_id) != consumer_run_id:
        _record_recheck_skip(payload, "unknown_invocation")
        return
    node_id = str(invocation.parent_node_id or "").strip()
    if not node_id:
        _record_recheck_skip(payload, "unknown_parent_node")
        return

    if readiness_invalidate is not None:
        try:
            readiness_invalidate(str(parent.team_id), consumer_run_id)
        except Exception:  # noqa: BLE001 - advisory
            pass

    latest = store.latest_attempt(consumer_run_id, node_id)
    if latest is not None and str(latest.status) in _LIVE_ATTEMPT_STATUSES:
        # The requesting node already executes; no successor attempt needed.
        _record_recheck_skip(payload, "node_already_live")
        return
    if command_service is None:
        _record_recheck_skip(payload, "no_command_service")
        return

    # Re-kick the requesting node through the single write entry: command
    # idempotency (deterministic key) + runVersion CAS + a fresh readiness
    # evaluation (the accepted-knowledge-package gate) all apply.  When the
    # gate still blocks, NodeNotReadyError leaves the run untouched.
    request = CommandRequest(
        command_id=f"cmd-kready-{invocation_id}",
        run_id=consumer_run_id,
        team_id=str(parent.team_id),
        command=WorkflowCommandKind.START_NODE,
        node_id=node_id,
        expected_run_version=int(parent.run_version),
        idempotency_key=f"knowledge-ready:{invocation_id}",
        payload={
            "reason": "knowledge_result_absorbed",
            "invocationId": invocation_id,
        },
        requested_by=ActorRef("system", "knowledge-readiness-recheck"),
        requested_at_ms=(now_provider() if now_provider else 0),
    )
    try:
        command_service.submit(request)
    except (
        WorkflowCommandError,
        CommandNotAllowedError,
        RunVersionConflictError,
        IdempotencyConflictError,
    ) as exc:
        # Blocked / retryable stays visible on the readiness surface; the
        # re-check never forces a dispatch past the readiness authority.
        _record_recheck_blocked(payload, node_id, exc)
        return
    _record_recheck_started(payload, node_id)


def _record_recheck_skip(payload: dict, reason: str) -> None:
    _scene_event(
        "knowledge_readiness_recheck_skipped",
        payload,
        {"reason": reason},
        outcome="skipped",
    )


def _record_recheck_blocked(payload: dict, node_id: str, exc: Exception) -> None:
    blockers: list[str] = []
    readiness = getattr(exc, "readiness", None)
    for blocker in getattr(readiness, "blockers", ()) or ():
        code = getattr(blocker, "code", None)
        blockers.append(str(code) if code is not None else str(blocker))
    _scene_event(
        "knowledge_readiness_recheck_blocked",
        payload,
        {"nodeId": node_id, "blockers": blockers[:8]},
        outcome="blocked",
    )


def _record_recheck_started(payload: dict, node_id: str) -> None:
    _scene_event(
        "knowledge_readiness_recheck_attempt_created",
        payload,
        {"nodeId": node_id},
        outcome="success",
    )


def _scene_event(
    name: str, payload: dict, fields: dict, *, outcome: str
) -> None:
    try:
        from core.web.services.runtime_scene_service import (
            record_runtime_scene_event_quietly,
        )

        record_runtime_scene_event_quietly(
            "team_workflow_orchestration",
            "knowledge_readiness_recheck",
            name,
            level="info",
            outcome=outcome,
            fields={
                "invocationId": str(payload.get("invocationId") or ""),
                "parentRunId": str(payload.get("consumerRunId") or ""),
                **fields,
            },
        )
    except Exception:  # noqa: BLE001 - observability must never break delivery
        pass
