"""Knowledge sideflow service: invocations, child runs, cross-run handoff.

Owns the three write surfaces of the knowledge child run (Task 3):

1. ``ensure_knowledge_invocation`` — call idempotency (same
   (parentRunId, parentNodeId, requestHash) replays the same invocation) and
   knowledge reuse (same envelope fingerprint tuple among completed
   invocations re-references the existing package; every invocation still
   gets its own row and receipt event).
2. ``ensure_knowledge_child_run`` — registers-or-resolves the pinned sideflow
   definition, creates the child ``WorkflowRun`` with parent lineage and its
   initial checkpoint, schedules the first node, and appends exactly one
   event to the parent run.  The parent's checkpoint / status / active node
   never move.
3. Producer/consumer of the durable ``event_publish`` outbox: the child
   terminal commit and the ``knowledge_result_available`` outbox row land in
   the SAME ledger transaction; the consumer absorbs into the parent run
   idempotently (deterministic event id) and never rewrites a parent
   checkpoint.

Envelope fingerprints deliberately reuse
``source_collection.facade.search_envelope_fingerprint`` so reuse decisions
can never drift from the collection ensure semantics.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from core.research.workflow.contracts._canonical import canonical_json, sha256_hex
from core.research.workflow.contracts.knowledge_sideflow import (
    KNOWLEDGE_INVOCATION_TERMINAL_STATUSES,
    KnowledgeHandoffState,
    KnowledgeInvocationStatus,
    KnowledgeResultAvailablePayload,
    knowledge_result_event_id,
)
from core.research.workflow.definition_registry import (
    register_or_resolve,
    resolve_definition_for_run_record,
)
from core.research.workflow.knowledge_sideflow_definition import (
    KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,
    build_knowledge_sideflow_workflow_definition,
)
from core.research.workflow.ledger import (
    EventRecord,
    KnowledgeInvocationRecord,
    OutboxRecord,
    RunRecord,
)

from .ids import new_id
from .paths import research_workflow_data_root
from .run_lifecycle import run_id_for_create

KNOWLEDGE_SIDEFLOW_COMPLETION_KIND = "knowledge_sideflow"
KNOWLEDGE_SIDEFLOW_ENTRY_NODE_ID = "source_finding"
KNOWLEDGE_SIDEFLOW_TERMINAL_NODE_ID = "knowledge_handoff"

PARENT_EVENT_INVOCATION_CREATED = "knowledge_invocation_created"
PARENT_EVENT_INVOCATION_REUSED = "knowledge_invocation_reused"
PARENT_EVENT_RESULT_ABSORBED = "knowledge_result_absorbed"

_KNOWLEDGE_PACKAGE_ARTIFACT_KIND = "knowledge_package"


class KnowledgeSideflowError(RuntimeError):
    """Typed failure; ``code`` is stable for worker reconciliation."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _default_now() -> int:
    return int(time.time() * 1000)


def default_checkpoint_path() -> str:
    return str(research_workflow_data_root() / "checkpoints.sqlite")


# --------------------------------------------------------------------------
# Fingerprints (aligned with source_collection ensure semantics)
# --------------------------------------------------------------------------


def search_envelope_hash(
    search_envelope: Mapping[str, Any] | None,
    source_policy_version: str,
) -> str:
    """Envelope-only fingerprint through the facade's canonicalization."""
    from core.web.services.team_workflow.source_collection.facade import (
        search_envelope_fingerprint,
    )

    return search_envelope_fingerprint(
        dict(search_envelope or {}),
        {},
        source_policy_version,
    )


def requirements_hash(
    requirements: Mapping[str, Any] | None,
    source_policy_version: str,
) -> str:
    """Requirements-only fingerprint through the facade's canonicalization."""
    from core.web.services.team_workflow.source_collection.facade import (
        search_envelope_fingerprint,
    )

    return search_envelope_fingerprint(
        {},
        dict(requirements or {}),
        source_policy_version,
    )


def knowledge_invocation_request_hash(
    *,
    question_id: str,
    scope_hash: str,
    search_envelope_hash: str,
    requirements_hash: str,
    source_policy_version: str,
) -> str:
    """Call-idempotency hash: request content, not lineage or attempt."""
    return sha256_hex(
        {
            "kind": "knowledge_invocation_request",
            "questionId": str(question_id or "").strip().upper(),
            "scopeHash": scope_hash,
            "searchEnvelopeHash": search_envelope_hash,
            "requirementsHash": requirements_hash,
            "sourcePolicyVersion": source_policy_version,
        }
    )


def compute_invocation_fingerprints(
    *,
    question_id: str,
    scope: Mapping[str, Any],
    search_envelope: Mapping[str, Any] | None,
    requirements: Mapping[str, Any] | None,
    source_policy_version: str,
) -> dict[str, str]:
    scope_hash = sha256_hex(dict(scope or {}))
    envelope_hash = search_envelope_hash(search_envelope, source_policy_version)
    req_hash = requirements_hash(requirements, source_policy_version)
    return {
        "scopeHash": scope_hash,
        "searchEnvelopeHash": envelope_hash,
        "requirementsHash": req_hash,
        "requestHash": knowledge_invocation_request_hash(
            question_id=str(question_id or "").strip().upper(),
            scope_hash=scope_hash,
            search_envelope_hash=envelope_hash,
            requirements_hash=req_hash,
            source_policy_version=source_policy_version,
        ),
    }


# --------------------------------------------------------------------------
# 1) ensure_knowledge_invocation — call idempotency + knowledge reuse
# --------------------------------------------------------------------------


def ensure_knowledge_invocation(
    store: Any,
    *,
    parent_run_id: str,
    parent_node_id: str,
    question_id: str,
    scope: Mapping[str, Any],
    search_envelope: Mapping[str, Any] | None,
    requirements: Mapping[str, Any] | None,
    source_policy_version: str,
    parent_node_run_id: str = "",
    parent_attempt: int = 1,
    source_manifest_ref: str = "",
    managed_source_root_ids: Sequence[str] | None = None,
    wake_worker: Callable[[], None] | None = None,
    now_provider: Callable[[], int] | None = None,
) -> dict[str, Any]:
    """Create-or-replay one knowledge invocation, then serve it.

    Returns ``{"invocation": record, "replayed": bool, "reused": bool,
    "childRunId": str | None}``.  A replay never creates a second child run;
    a reuse never creates any child run.

    ``managed_source_root_ids`` is the operator's managed-root selection: it
    is fingerprinted through the scope hash and carried verbatim onto the
    child run's input snapshot so the child's source_finding collection run
    imports exactly those registered roots.
    """
    now = now_provider or _default_now
    parent = store.get_run(parent_run_id)
    if parent is None:
        raise KnowledgeSideflowError(
            f"parent run {parent_run_id} not found", code="unknown_parent_run"
        )
    normalized_question = str(question_id or "").strip().upper()
    if not normalized_question:
        raise KnowledgeSideflowError("questionId is required", code="invalid_request")
    if str(parent.question_id or "").strip().upper() != normalized_question:
        raise KnowledgeSideflowError(
            "questionId does not match the parent run",
            code="question_mismatch",
        )
    normalized_root_ids = _normalize_root_id_sequence(
        managed_source_root_ids
        if managed_source_root_ids is not None
        else (scope or {}).get("managedSourceRootIds")
    )
    fingerprints = compute_invocation_fingerprints(
        question_id=normalized_question,
        scope=scope,
        search_envelope=search_envelope,
        requirements=requirements,
        source_policy_version=source_policy_version,
    )

    outcome: dict[str, Any] = {}

    def mutate(uow) -> None:
        existing = uow.repository.find_knowledge_invocation_by_request(
            parent_run_id, parent_node_id, fingerprints["requestHash"]
        )
        if existing is not None:
            # Call idempotency: same requestHash replays the SAME invocation.
            # A request that gains root ids after its first submission keeps
            # replaying the original invocation (the requestHash did not move
            # because root ids ride in the scope, which callers must include
            # in the command payload to change the fingerprint at all).
            outcome.update(
                {"invocation": existing, "replayed": True, "reused": False}
            )
            return
        reusable = uow.repository.find_reusable_knowledge_invocation(
            scope_hash=fingerprints["scopeHash"],
            search_envelope_hash=fingerprints["searchEnvelopeHash"],
            requirements_hash=fingerprints["requirementsHash"],
            source_policy_version=source_policy_version,
        )
        now_ms = now()
        if reusable is not None:
            # Knowledge reuse: reference the existing package, no child run.
            record = KnowledgeInvocationRecord(
                invocation_id=new_id("kinv"),
                parent_run_id=parent_run_id,
                parent_node_id=parent_node_id,
                parent_node_run_id=str(parent_node_run_id or ""),
                parent_attempt=int(parent_attempt or 1),
                question_id=normalized_question,
                scope_hash=fingerprints["scopeHash"],
                request_hash=fingerprints["requestHash"],
                search_envelope_hash=fingerprints["searchEnvelopeHash"],
                requirements_hash=fingerprints["requirementsHash"],
                source_policy_version=source_policy_version,
                knowledge_child_run_id=None,
                status=KnowledgeInvocationStatus.COMPLETED.value,
                knowledge_package_ref=reusable.knowledge_package_ref,
                package_content_hash=reusable.package_content_hash,
                handoff_state=KnowledgeHandoffState.ACCEPTED.value,
                error_json=None,
                created_at_ms=now_ms,
                updated_at_ms=now_ms,
            )
            uow.repository.insert_knowledge_invocation(record)
            sequence = uow.repository.advance_last_sequence(parent_run_id, 1, now_ms)
            if sequence is not None:
                uow.repository.insert_event(
                    EventRecord(
                        run_id=parent_run_id,
                        sequence=sequence,
                        event_id=f"evt-{record.invocation_id}-reused",
                        run_version=_run_version_of(uow, parent_run_id),
                        event_type=PARENT_EVENT_INVOCATION_REUSED,
                        actor_json=json.dumps(
                            {"actorType": "system", "actorId": "knowledge_sideflow"}
                        ),
                        correlation_id=record.invocation_id,
                        causation_id=None,
                        payload_json=json.dumps(
                            {
                                "invocationId": record.invocation_id,
                                "reusedFromInvocationId": reusable.invocation_id,
                                "knowledgePackageRef": record.knowledge_package_ref,
                                "packageContentHash": record.package_content_hash,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        occurred_at_ms=now_ms,
                    )
                )
            outcome.update(
                {"invocation": record, "replayed": False, "reused": True}
            )
            return
        record = KnowledgeInvocationRecord(
            invocation_id=new_id("kinv"),
            parent_run_id=parent_run_id,
            parent_node_id=parent_node_id,
            parent_node_run_id=str(parent_node_run_id or ""),
            parent_attempt=int(parent_attempt or 1),
            question_id=normalized_question,
            scope_hash=fingerprints["scopeHash"],
            request_hash=fingerprints["requestHash"],
            search_envelope_hash=fingerprints["searchEnvelopeHash"],
            requirements_hash=fingerprints["requirementsHash"],
            source_policy_version=source_policy_version,
            knowledge_child_run_id=None,
            status=KnowledgeInvocationStatus.PENDING.value,
            knowledge_package_ref=None,
            package_content_hash=None,
            handoff_state=KnowledgeHandoffState.PENDING.value,
            error_json=None,
            created_at_ms=now_ms,
            updated_at_ms=now_ms,
        )
        uow.repository.insert_knowledge_invocation(record)
        outcome.update(
            {"invocation": record, "replayed": False, "reused": False}
        )

    store.submit(mutate, force_flush=True).result(timeout=30)

    invocation = outcome["invocation"]
    child_run_id = invocation.knowledge_child_run_id
    if not outcome["reused"]:
        if child_run_id is None and invocation.status not in (
            KNOWLEDGE_INVOCATION_TERMINAL_STATUSES
        ):
            child_run_id = ensure_knowledge_child_run(
                store,
                invocation,
                source_manifest_ref=source_manifest_ref,
                managed_source_root_ids=normalized_root_ids,
                wake_worker=wake_worker,
                now_provider=now_provider,
            )
    return {
        "invocation": invocation,
        "replayed": bool(outcome["replayed"]),
        "reused": bool(outcome["reused"]),
        "childRunId": child_run_id,
    }


def _normalize_root_id_sequence(raw: Sequence[str] | None) -> list[str]:
    """Lower-cased, trimmed, de-duplicated root ids for the child snapshot."""
    normalized: list[str] = []
    for item in list(raw or [])[:32]:
        root_id = str(item or "").strip().lower()[:64]
        if root_id and root_id not in normalized:
            normalized.append(root_id)
    return normalized


def _run_version_of(uow, run_id: str) -> int:
    run = uow.repository.get_run(run_id)
    return int(run.run_version) if run is not None else 1


# --------------------------------------------------------------------------
# 2) ensure_knowledge_child_run — child run + parent append-only event
# --------------------------------------------------------------------------


def knowledge_sideflow_child_run_id(invocation_id: str) -> str:
    """Deterministic child run id: crash replays land on the same run."""
    return run_id_for_create(
        KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,
        f"knowledge-invocation:{invocation_id}",
    )


def ensure_knowledge_child_run(
    store: Any,
    invocation: KnowledgeInvocationRecord,
    *,
    source_manifest_ref: str = "",
    managed_source_root_ids: Sequence[str] | None = None,
    wake_worker: Callable[[], None] | None = None,
    now_provider: Callable[[], int] | None = None,
) -> str:
    """Create (or replay) the knowledge_sideflow child run for one invocation.

    Parent effects are limited to one appended ``knowledge_invocation_created``
    event; the parent's run_version, checkpoint, status and active node are
    untouched.  All ledger writes — child run, command, attempt,
    graph_dispatch, invocation update, parent event — commit in ONE
    transaction.  No checkpoint I/O happens here at all: the graph worker's
    start dispatch compiles the pinned sideflow graph and creates the child
    thread on its empty-thread start path.

    ``managed_source_root_ids`` lands verbatim in the child input snapshot so
    the source_finding stage creates its collection run with the operator's
    root selection (the managed-root import bypass reads it from the run
    payload).
    """
    from .graph_dispatch_factory import build_graph_dispatch_record

    now = now_provider or _default_now
    if invocation.knowledge_child_run_id:
        child_run_id = str(invocation.knowledge_child_run_id)
        _link_invocation_to_child(
            store, invocation, child_run_id, now_provider=now
        )
        return child_run_id
    child_run_id = knowledge_sideflow_child_run_id(str(invocation.invocation_id))
    _link_invocation_to_child(store, invocation, child_run_id, now_provider=now)

    parent = store.get_run(str(invocation.parent_run_id))
    if parent is None:
        raise KnowledgeSideflowError(
            f"parent run {invocation.parent_run_id} not found",
            code="unknown_parent_run",
        )

    definition = build_knowledge_sideflow_workflow_definition()
    identity = register_or_resolve(definition)

    input_snapshot = {
        "kind": "knowledge_sideflow_child",
        "schemaVersion": 1,
        "invocationId": invocation.invocation_id,
        "parentRunId": parent.run_id,
        "parentNodeId": invocation.parent_node_id,
        "parentNodeRunId": invocation.parent_node_run_id,
        "parentAttempt": invocation.parent_attempt,
        "teamId": parent.team_id,
        "questionId": invocation.question_id,
        "scopeHash": invocation.scope_hash,
        "requestHash": invocation.request_hash,
        "searchEnvelopeHash": invocation.search_envelope_hash,
        "requirementsHash": invocation.requirements_hash,
        "sourcePolicyVersion": invocation.source_policy_version,
        "sourceManifestRef": str(source_manifest_ref or ""),
        "managedSourceRootIds": _normalize_root_id_sequence(
            managed_source_root_ids
        ),
    }
    snapshot_hash = hashlib.sha256(
        canonical_json(input_snapshot).encode("utf-8")
    ).hexdigest()
    input_snapshot["snapshotHash"] = snapshot_hash

    thread_id = child_run_id  # threadId == runId (spec 7.3)

    now_ms = now()
    created_at = parent.created_at_ms
    child = RunRecord(
        run_id=child_run_id,
        team_id=parent.team_id,
        workflow_id=KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,
        workflow_version_id=identity.workflowVersionId,
        thread_id=thread_id,
        project_id=parent.project_id,
        question_id=parent.question_id,
        # The synthesized start command is accepted inside the creation
        # transaction (command + attempt + graph_dispatch), which is exactly
        # the START_NODE-accepted state; mirror it as ``running`` so the
        # terminal commit accepts the run later.
        status="running",
        run_version=1,
        last_event_sequence=2,
        input_snapshot_json=json.dumps(input_snapshot, ensure_ascii=False),
        input_snapshot_hash=snapshot_hash,
        safety_limits_json=parent.safety_limits_json,
        binding_snapshot_set_id=f"binding-{child_run_id}",
        active_node_id=KNOWLEDGE_SIDEFLOW_ENTRY_NODE_ID,
        parent_run_id=parent.run_id,
        forked_from_checkpoint_id=None,
        completion_kind=KNOWLEDGE_SIDEFLOW_COMPLETION_KIND,
        terminal_reason=None,
        blocked_problem_json=None,
        created_at_ms=created_at,
        updated_at_ms=now_ms,
        completed_at_ms=None,
        structure_hash=identity.structureHash,
    )
    run_created_event = EventRecord(
        run_id=child_run_id,
        sequence=1,
        event_id=f"evt-created-{child_run_id}",
        run_version=1,
        event_type="run_created",
        actor_json=json.dumps(
            {"actorType": "system", "actorId": "knowledge_sideflow_service"}
        ),
        correlation_id=invocation.invocation_id,
        causation_id=None,
        payload_json=json.dumps(
            {
                "inputSnapshotHash": snapshot_hash,
                "parentRunId": parent.run_id,
                "invocationId": invocation.invocation_id,
            },
            ensure_ascii=False,
        ),
        occurred_at_ms=now_ms,
    )
    node_starting_event = EventRecord(
        run_id=child_run_id,
        sequence=2,
        event_id=f"evt-node-starting-{child_run_id}-{KNOWLEDGE_SIDEFLOW_ENTRY_NODE_ID}-a1",
        run_version=1,
        event_type="node_starting",
        actor_json=json.dumps(
            {"actorType": "system", "actorId": "knowledge_sideflow_service"}
        ),
        correlation_id=invocation.invocation_id,
        causation_id=run_created_event.event_id,
        payload_json=json.dumps(
            {
                "nodeId": KNOWLEDGE_SIDEFLOW_ENTRY_NODE_ID,
                "nodeRunId": f"nr-{child_run_id}-{KNOWLEDGE_SIDEFLOW_ENTRY_NODE_ID}-a1",
                "attempt": 1,
            },
            ensure_ascii=False,
        ),
        occurred_at_ms=now_ms,
    )
    from core.research.workflow.ledger import CommandRecord, NodeAttemptRecord

    command_id = f"cmd-ksf-{invocation.invocation_id}"
    command = CommandRecord(
        command_id=command_id,
        run_id=child_run_id,
        team_id=parent.team_id,
        node_id=KNOWLEDGE_SIDEFLOW_ENTRY_NODE_ID,
        command_kind="start_node",
        expected_run_version=1,
        accepted_run_version=1,
        idempotency_key=f"knowledge_sideflow:{invocation.invocation_id}:start",
        request_hash=invocation.request_hash,
        request_json=json.dumps(
            {
                "command": "start_node",
                "invocationId": invocation.invocation_id,
                "workflowId": KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,
            },
            ensure_ascii=False,
        ),
        requested_by_json=json.dumps(
            {"actorType": "system", "actorId": "knowledge_sideflow_service"}
        ),
        status="completed",
        result_json=None,
        problem_json=None,
        created_at_ms=now_ms,
        completed_at_ms=now_ms,
    )
    attempt = NodeAttemptRecord(
        node_run_id=f"nr-{child_run_id}-{KNOWLEDGE_SIDEFLOW_ENTRY_NODE_ID}-a1",
        run_id=child_run_id,
        node_id=KNOWLEDGE_SIDEFLOW_ENTRY_NODE_ID,
        attempt=1,
        actor_kind="agent",
        status="starting",
        command_id=command_id,
        binding_snapshot_id=None,
        input_snapshot_hash=snapshot_hash,
        pending_action_id=None,
        execution_anchor_id=None,
        retry_of_node_run_id=None,
        problem_json=None,
        started_at_ms=now_ms,
        updated_at_ms=now_ms,
        finished_at_ms=None,
    )

    parent_event_sequence: dict[str, int | None] = {"sequence": None}

    def mutate(uow) -> None:
        # Single-writer serialization makes this re-check race-free.
        existing = uow.repository.get_run(child_run_id)
        if existing is None:
            uow.repository.insert_run(child)
            uow.repository.insert_event(run_created_event)
            uow.repository.insert_event(node_starting_event)
            uow.repository.insert_command(command)
            uow.repository.insert_attempt(attempt)
            uow.repository.insert_outbox(
                build_graph_dispatch_record(
                    run=child,
                    attempt=attempt,
                    command_id=command_id,
                    dispatch_kind="start",
                    now_ms=now_ms,
                )
            )
        uow.repository.update_knowledge_invocation(
            invocation.invocation_id,
            now_ms,
            knowledge_child_run_id=child_run_id,
            status=(
                invocation.status
                if invocation.status
                not in (
                    KnowledgeInvocationStatus.PENDING.value,
                    KnowledgeInvocationStatus.CHILD_CREATED.value,
                )
                else KnowledgeInvocationStatus.CHILD_CREATED.value
            ),
        )
        # Parent: append one event only. No runVersion bump, no status or
        # active_node change, no checkpoint write.
        parent_sequence = uow.repository.advance_last_sequence(parent.run_id, 1, now_ms)
        if parent_sequence is not None:
            uow.repository.insert_event(
                EventRecord(
                    run_id=parent.run_id,
                    sequence=parent_sequence,
                    event_id=f"evt-{invocation.invocation_id}-invocation-created",
                    run_version=_run_version_of(uow, parent.run_id),
                    event_type=PARENT_EVENT_INVOCATION_CREATED,
                    actor_json=json.dumps(
                        {"actorType": "system", "actorId": "knowledge_sideflow_service"}
                    ),
                    correlation_id=invocation.invocation_id,
                    causation_id=None,
                    payload_json=json.dumps(
                        {
                            "invocationId": invocation.invocation_id,
                            "childRunId": child_run_id,
                            "parentNodeId": invocation.parent_node_id,
                            "parentNodeRunId": invocation.parent_node_run_id,
                            "parentAttempt": invocation.parent_attempt,
                            "requestHash": invocation.request_hash,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    occurred_at_ms=now_ms,
                )
            )
        parent_event_sequence["sequence"] = parent_sequence

    store.submit(mutate, force_flush=True).result(timeout=30)
    if wake_worker is not None:
        wake_worker()
    return child_run_id


def _link_invocation_to_child(
    store: Any,
    invocation: KnowledgeInvocationRecord,
    child_run_id: str,
    *,
    now_provider: Callable[[], int],
) -> None:
    if str(invocation.knowledge_child_run_id or "") == child_run_id:
        return

    def mutate(uow) -> None:
        uow.repository.update_knowledge_invocation(
            invocation.invocation_id,
            now_provider(),
            knowledge_child_run_id=child_run_id,
        )

    store.submit(mutate, force_flush=True).result(timeout=30)


# --------------------------------------------------------------------------
# 3) Producer hooks (run INSIDE the graph worker's ledger transaction)
# --------------------------------------------------------------------------


def is_knowledge_sideflow_run(run: Any) -> bool:
    return (
        str(getattr(run, "workflow_id", "") or "") == KNOWLEDGE_SIDEFLOW_WORKFLOW_ID
    )


def record_knowledge_sideflow_child_success(
    uow, *, run_id: str, now_ms: int
) -> str | None:
    """Close the invocation and emit ``knowledge_result_available`` atomically.

    Called from the SAME mutate that committed the child run's terminal
    success — the outbox row and the child terminal facts cannot be separated
    by a crash (that is the definition of the outbox pattern).  A child
    without ``knowledge_package`` receipt evidence never fakes a handoff: the
    invocation is failed instead and no event is published.
    """
    run = uow.repository.get_run(run_id)
    if run is None or not is_knowledge_sideflow_run(run):
        return None
    invocation = uow.repository.find_knowledge_invocation_by_child_run(run_id)
    if invocation is None:
        return None
    if (
        invocation.status == KnowledgeInvocationStatus.COMPLETED.value
        and invocation.handoff_state == KnowledgeHandoffState.ACCEPTED.value
        and invocation.package_content_hash
    ):
        # Crash replay: the terminal tx already committed once.
        return None

    package_row = uow.repository.execute(
        """
        SELECT receipt_id, canonical_ref_json, sha256 FROM artifact_receipts
        WHERE run_id = ? AND artifact_kind = ?
        ORDER BY verified_at_ms DESC, receipt_id DESC LIMIT 1
        """,
        (run_id, _KNOWLEDGE_PACKAGE_ARTIFACT_KIND),
    ).fetchone()
    if package_row is None:
        # Fail-closed: no package evidence, no cross-run handoff.
        uow.repository.update_knowledge_invocation(
            invocation.invocation_id,
            now_ms,
            status=KnowledgeInvocationStatus.FAILED.value,
            error_json=json.dumps(
                {
                    "code": "knowledge_package_missing",
                    "detail": (
                        "child run reached its handoff terminal without a "
                        "knowledge_package artifact receipt"
                    ),
                },
                ensure_ascii=False,
            ),
        )
        return None

    receipt_id = str(package_row[0])
    package_ref = str(package_row[1] or "")
    package_hash = str(package_row[2] or "").lower()
    handoff_row = uow.repository.execute(
        """
        SELECT handoff_id FROM handoffs
        WHERE run_id = ? AND status = 'accepted'
        ORDER BY offered_at_ms DESC, handoff_id DESC LIMIT 1
        """,
        (run_id,),
    ).fetchone()
    handoff_decision_ref = (
        str(handoff_row[0]) if handoff_row else f"node_run:{run_id}:terminal"
    )
    source_manifest_ref = _source_manifest_ref_of(uow, run_id)
    payload = KnowledgeResultAvailablePayload(
        producerRunId=run_id,
        consumerRunId=str(invocation.parent_run_id),
        invocationId=str(invocation.invocation_id),
        knowledgePackageRef=package_ref or f"artifact_receipt:{receipt_id}",
        packageContentHash=package_hash,
        sourceManifestRef=source_manifest_ref,
        handoffDecisionRef=handoff_decision_ref,
        correlationId=str(invocation.invocation_id),
    )
    idempotency_key = (
        f"event_publish:{payload.eventType}:{invocation.invocation_id}:"
        f"{package_hash[:16]}"
    )
    existing = uow.repository.execute(
        "SELECT action_id FROM outbox_actions WHERE idempotency_key = ?",
        (idempotency_key,),
    ).fetchone()
    if existing is None:
        terminal_attempt = uow.repository.execute(
            """
            SELECT node_run_id, command_id FROM node_attempts
            WHERE run_id = ?
            ORDER BY attempt DESC, node_run_id DESC LIMIT 1
            """,
            (run_id,),
        ).fetchone()
        node_run_id = str(terminal_attempt[0]) if terminal_attempt else None
        command_id = str(terminal_attempt[1] or "") if terminal_attempt else ""
        uow.repository.insert_outbox(
            OutboxRecord(
                action_id=new_id("act"),
                run_id=run_id,
                command_id=command_id or None,
                node_run_id=node_run_id,
                action_kind="event_publish",
                idempotency_key=idempotency_key,
                payload_json=json.dumps(
                    payload.to_dict(), ensure_ascii=False, sort_keys=True
                ),
                status="pending",
                attempt_count=0,
                available_at_ms=now_ms,
                lease_owner=None,
                lease_expires_at_ms=None,
                last_problem_json=None,
                created_at_ms=now_ms,
                updated_at_ms=now_ms,
            )
        )
    uow.repository.update_knowledge_invocation(
        invocation.invocation_id,
        now_ms,
        status=KnowledgeInvocationStatus.COMPLETED.value,
        knowledge_package_ref=payload.knowledgePackageRef,
        package_content_hash=package_hash,
        handoff_state=KnowledgeHandoffState.ACCEPTED.value,
        error_json=None,
    )
    sequence = uow.repository.advance_last_sequence(run_id, 1, now_ms)
    if sequence is not None:
        uow.repository.insert_event(
            EventRecord(
                run_id=run_id,
                sequence=sequence,
                event_id=f"evt-{invocation.invocation_id}-result-published",
                run_version=_run_version_of(uow, run_id),
                event_type="knowledge_result_published",
                actor_json=json.dumps(
                    {"actorType": "system", "actorId": "graph-worker"}
                ),
                correlation_id=invocation.invocation_id,
                causation_id=None,
                payload_json=json.dumps(
                    {
                        "invocationId": invocation.invocation_id,
                        "parentRunId": invocation.parent_run_id,
                        "packageContentHash": package_hash,
                        "dedupKey": payload.dedupKey,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                occurred_at_ms=now_ms,
            )
        )
    return payload.dedupKey


def record_knowledge_sideflow_child_failure(
    uow, *, run_id: str, outcome: str, now_ms: int
) -> str | None:
    """A failed/cancelled child never fakes a successful handoff.

    ``blocked`` is deliberately not terminal: the operator can still repair
    the child, so the invocation stays in its current non-terminal status.
    """
    run = uow.repository.get_run(run_id)
    if run is None or not is_knowledge_sideflow_run(run):
        return None
    invocation = uow.repository.find_knowledge_invocation_by_child_run(run_id)
    if invocation is None:
        return None
    if invocation.status in KNOWLEDGE_INVOCATION_TERMINAL_STATUSES:
        return None
    if str(outcome) not in {"failed", "cancelled"}:
        return None
    uow.repository.update_knowledge_invocation(
        invocation.invocation_id,
        now_ms,
        status=(
            KnowledgeInvocationStatus.CANCELLED.value
            if str(outcome) == "cancelled"
            else KnowledgeInvocationStatus.FAILED.value
        ),
        error_json=json.dumps(
            {"code": "knowledge_sideflow_child_failed", "outcome": str(outcome)},
            ensure_ascii=False,
        ),
    )
    return invocation.invocation_id


def _source_manifest_ref_of(uow, run_id: str) -> str:
    row = uow.repository.execute(
        "SELECT input_snapshot_json FROM workflow_runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        return ""
    try:
        snapshot = json.loads(str(row[0] or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return ""
    if not isinstance(snapshot, dict):
        return ""
    return str(snapshot.get("sourceManifestRef") or "")


# --------------------------------------------------------------------------
# 4) Consumer — parent-side absorption (writer lock held only for the write)
# --------------------------------------------------------------------------


def _record_absorb_replay(
    invocation_id: str, payload: KnowledgeResultAvailablePayload
) -> None:
    """Best-effort observability for an idempotent absorb replay."""
    try:
        from core.web.services.runtime_scene_service import (
            record_runtime_scene_event_quietly,
        )

        record_runtime_scene_event_quietly(
            "team_workflow_orchestration",
            "knowledge_sideflow_service",
            "knowledge_sideflow.absorb_replayed",
            level="info",
            outcome="recovered",
            fields={
                "invocationId": invocation_id,
                "parentRunId": payload.consumerRunId,
                "dedupKey": payload.dedupKey,
            },
        )
    except Exception:  # noqa: BLE001 - observability must never break delivery
        pass


def absorb_knowledge_result(
    store: Any,
    payload: Mapping[str, Any],
    *,
    now_provider: Callable[[], int] | None = None,
    notify_readiness: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Validate + absorb one ``knowledge_result_available`` into the parent.

    Validation runs OUTSIDE the ledger writer lock.  Absorption appends one
    deterministic-id event to the parent run (idempotent under re-delivery),
    never rewrites the parent checkpoint, and leaves attempt creation to the
    readiness re-check interface (later tasks).
    """
    now = now_provider or _default_now
    typed = KnowledgeResultAvailablePayload.from_dict(dict(payload))
    invocation_id = typed.invocationId

    invocation = store.read(
        lambda repo: repo.get_knowledge_invocation(invocation_id)
    )
    if invocation is None:
        raise KnowledgeSideflowError(
            f"knowledge invocation {invocation_id} not found",
            code="unknown_invocation",
        )
    if str(invocation.knowledge_child_run_id or "") != typed.producerRunId:
        raise KnowledgeSideflowError(
            "payload producerRunId does not match the invocation child run",
            code="producer_lineage_mismatch",
        )
    if str(invocation.parent_run_id) != typed.consumerRunId:
        raise KnowledgeSideflowError(
            "payload consumerRunId does not match the invocation parent run",
            code="consumer_lineage_mismatch",
        )
    if invocation.status != KnowledgeInvocationStatus.COMPLETED.value:
        raise KnowledgeSideflowError(
            f"invocation {invocation_id} is not completed",
            code="invocation_not_completed",
        )
    if str(invocation.package_content_hash or "") != typed.packageContentHash:
        raise KnowledgeSideflowError(
            "package content hash does not match the invocation record",
            code="package_hash_mismatch",
        )
    parent = store.get_run(typed.consumerRunId)
    if parent is None:
        raise KnowledgeSideflowError(
            f"parent run {typed.consumerRunId} not found", code="unknown_parent_run"
        )
    if str(parent.status) in {"archived", "cancelled"}:
        raise KnowledgeSideflowError(
            f"parent run {typed.consumerRunId} is {parent.status}",
            code="parent_not_absorbable",
        )
    # Fail-closed lineage: the parent's pinned definition must still contain
    # the requesting node.
    resolve_definition_for_run_record(
        {
            "runId": parent.run_id,
            "workflowId": parent.workflow_id,
            "workflowVersionId": parent.workflow_version_id,
            "structureHash": parent.structure_hash,
            "completedNodeIds": [invocation.parent_node_id],
            "runtimeCurrentNodeIds": [],
        },
        expected_node_ids=[invocation.parent_node_id],
    )

    event_id = knowledge_result_event_id(invocation_id, typed.packageContentHash)
    existing = store.get_event_by_id(event_id)
    if existing is not None:
        # Crash boundary ③: parent already absorbed; replay must not re-write.
        _record_absorb_replay(invocation_id, typed)
        return {"status": "already_absorbed", "dedupKey": typed.dedupKey}

    now_ms = now()

    def mutate(uow) -> None:
        # Re-check inside the single writer: redelivery between the outside
        # read and this transaction is caught by the deterministic event id.
        if uow.repository.get_event_by_id(event_id) is not None:
            return
        sequence = uow.repository.advance_last_sequence(typed.consumerRunId, 1, now_ms)
        if sequence is None:
            raise KnowledgeSideflowError(
                f"parent run {typed.consumerRunId} disappeared",
                code="unknown_parent_run",
            )
        uow.repository.insert_event(
            EventRecord(
                run_id=typed.consumerRunId,
                sequence=sequence,
                event_id=event_id,
                run_version=_run_version_of(uow, typed.consumerRunId),
                event_type=PARENT_EVENT_RESULT_ABSORBED,
                actor_json=json.dumps(
                    {"actorType": "system", "actorId": "event-publish-worker"}
                ),
                correlation_id=typed.correlationId,
                causation_id=None,
                payload_json=json.dumps(
                    {**typed.to_dict(), "dedupKey": typed.dedupKey},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                occurred_at_ms=now_ms,
            )
        )

    store.submit(mutate, force_flush=True).result(timeout=30)
    if notify_readiness is not None:
        # Interface for later tasks: re-check readiness of the parent nodes
        # waiting on this knowledge package (attempt creation is NOT done here;
        # a completed parent checkpoint is never rewritten).
        try:
            notify_readiness()
        except Exception:  # noqa: BLE001 - re-check is advisory
            pass
    return {"status": "absorbed", "dedupKey": typed.dedupKey}
