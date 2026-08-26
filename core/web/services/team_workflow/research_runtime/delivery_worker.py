"""Delivery orchestration worker — runs the post-run Challenge Cup delivery chain.

Leases ``delivery_orchestration`` outbox actions (enqueued atomically with the
run-succeeded transition), executes the chain outside the writer transaction,
then commits exactly one terminal Ledger event plus the outbox settlement in a
single transaction. The run row itself is never touched: delivery outcomes are
diagnosable from the timeline while the run stays ``succeeded``.

Crash safety: the artifact write is idempotent by content hash and the terminal
event + ack commit atomically, so a crashed attempt simply re-runs the chain
and appends a newer artifact row.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from core.research.workflow.ledger import WorkflowLedgerStore
from core.research.workflow.ledger import outbox as outbox_api

from .artifact_readback_registry import build_canonical_ref
from .delivery_orchestration import (
    DELIVERY_ARTIFACT_KIND,
    DELIVERY_OUTBOX_KIND,
    DeliveryOrchestrationError,
    build_delivery_event,
    run_delivery_orchestration,
    run_status_allows_delivery,
)
from .human_gate_artifacts import canonical_sha256
from .workflow_artifact_store import put_workflow_artifact

DEFAULT_DELIVERY_LEASE_MS = 30_000
MAX_DELIVERY_ATTEMPTS = 3


def _record_scene_event(event_code: str, *, outcome: str, fields: dict[str, Any]) -> None:
    """Best-effort worker observability; never breaks the delivery path."""
    from core.web.services.runtime_scene_service import (
        record_runtime_scene_event_quietly,
    )

    record_runtime_scene_event_quietly(
        "team_workflow_orchestration",
        "delivery_worker",
        event_code,
        level="info" if outcome in {"succeeded", "needs_context"} else "warning",
        outcome=outcome,
        fields=fields,
    )


class DeliveryOrchestrationWorker:
    def __init__(
        self,
        *,
        store: WorkflowLedgerStore,
        owner_id: str = "delivery-worker",
        lease_ms: int = DEFAULT_DELIVERY_LEASE_MS,
        now_provider: Callable[[], int] | None = None,
        commit_hook: Callable[[], None] | None = None,
        max_attempts: int = MAX_DELIVERY_ATTEMPTS,
    ) -> None:
        self._store = store
        self._owner = owner_id
        self._lease_ms = lease_ms
        self._now = now_provider or (lambda: int(time.time() * 1000))
        self._commit_hook = commit_hook
        self._max_attempts = max(1, int(max_attempts))

    def _submit(self, mutate, *, force_flush: bool = True):
        hook = self._commit_hook

        def wrapped(uow):
            if hook is not None:
                uow.after_commit(hook)
            return mutate(uow)

        return self._store.submit(wrapped, force_flush=force_flush)

    def run_once(self, limit: int = 4) -> int:
        leased = outbox_api.lease_ready_actions(
            self._store,
            owner=self._owner,
            now_ms=self._now(),
            limit=limit,
            lease_ms=self._lease_ms,
            action_kinds=(DELIVERY_OUTBOX_KIND,),
        )
        for action in leased:
            self._handle(action)
        return len(leased)

    def _handle(self, action: Any) -> None:
        now_ms = self._now()
        run_id = ""
        try:
            payload = json.loads(action.payload_json)
            if isinstance(payload, dict):
                run_id = str(payload.get("runId") or "").strip()
        except (TypeError, ValueError):
            run_id = ""
        if not run_id:
            _record_scene_event(
                "delivery.invalid_action",
                outcome="failed",
                fields={
                    "actionId": str(getattr(action, "action_id", "") or ""),
                    "code": "invalid_delivery_action",
                },
            )
            self._fail(
                action,
                now_ms=now_ms,
                problem={"code": "invalid_delivery_action", "detail": "missing runId"},
            )
            return
        run = self._store.get_run(run_id)
        if run is None or not run_status_allows_delivery(run.status):
            # Run gone or no longer succeeded (e.g. archived): nothing to deliver.
            self._ack_only(action, now_ms=now_ms)
            return
        try:
            outcome = run_delivery_orchestration(self._store, run_id=run_id, now_ms=now_ms)
        except DeliveryOrchestrationError as exc:
            self._commit_terminal(
                action,
                run=run,
                now_ms=now_ms,
                outcome={
                    "status": "failed",
                    "code": exc.code,
                    "detail": exc.detail,
                    "failedStep": exc.step,
                },
            )
            return
        except Exception as exc:  # noqa: BLE001 - transient failures requeue, never sink the action
            if action.attempt_count < self._max_attempts:
                _record_scene_event(
                    "delivery.requeued",
                    outcome="requeued",
                    fields={
                        "runId": run_id,
                        "attemptCount": int(getattr(action, "attempt_count", 0) or 0),
                        "detail": str(exc)[:160],
                    },
                )
                outbox_api.requeue_action(
                    self._store,
                    action.action_id,
                    self._owner,
                    now_ms,
                    retry_at_ms=now_ms + 5_000,
                    problem_json=json.dumps(
                        {"code": "transient", "detail": str(exc)},
                        ensure_ascii=False,
                    ),
                )
                return
            self._commit_terminal(
                action,
                run=run,
                now_ms=now_ms,
                outcome={
                    "status": "failed",
                    "code": "delivery_orchestration_exception",
                    "detail": str(exc),
                    "failedStep": "orchestration",
                },
            )
            return
        self._commit_terminal(action, run=run, now_ms=now_ms, outcome=outcome)

    def _ack_only(self, action: Any, *, now_ms: int) -> None:
        def mutate(uow):
            uow.repository.ack_outbox(action.action_id, self._owner, now_ms)

        self._submit(mutate, force_flush=True).result(timeout=30)

    @staticmethod
    def _authority_run_id(run: Any) -> str:
        try:
            snapshot = json.loads(str(getattr(run, "input_snapshot_json", "") or "{}"))
        except (TypeError, ValueError):
            snapshot = {}
        if isinstance(snapshot, dict):
            source = str(snapshot.get("sourceCollectionRunId") or "").strip()
            if source:
                return source
        return str(getattr(run, "run_id", "") or "").strip()

    def _persist_failure_artifact(
        self,
        action: Any,
        *,
        run: Any,
        outcome: dict[str, Any],
    ) -> dict[str, str]:
        """Persist a projection-safe terminal artifact for pre-artifact failures."""

        team_id = str(getattr(run, "team_id", "") or "").strip()
        workflow_run_id = str(getattr(run, "run_id", "") or "").strip()
        authority_run_id = self._authority_run_id(run)
        failure = {
            "code": str(outcome.get("code") or "delivery_failed"),
            "step": str(outcome.get("failedStep") or "orchestration"),
            "detail": str(outcome.get("detail") or ""),
        }
        payload = {
            "schemaVersion": 1,
            "teamId": team_id,
            "workflowRunId": workflow_run_id,
            "sourceCollectionRunId": authority_run_id,
            "deliveryStatus": "failed",
            "trigger": {
                "nodeId": "result_package",
                "completionKind": str(getattr(run, "completion_kind", "") or ""),
                "terminalReason": str(getattr(run, "terminal_reason", "") or ""),
            },
            "steps": {"failure": failure},
            "formalBlockers": [
                str(item) for item in outcome.get("formalBlockers") or []
            ],
            "programCandidateHandoff": dict(
                outcome.get("programCandidateHandoff") or {}
            ),
            "diagnostics": [str(item) for item in outcome.get("diagnostics") or []],
            "failure": failure,
        }
        record = put_workflow_artifact(
            team_id,
            kind=DELIVERY_ARTIFACT_KIND,
            workflow_run_id=workflow_run_id,
            source_collection_run_id=authority_run_id,
            payload=payload,
            artifact_identity=f"{action.action_id}:failure",
        )
        envelope = {
            "teamId": team_id,
            "kind": DELIVERY_ARTIFACT_KIND,
            "workflowRunId": workflow_run_id,
            "sourceCollectionRunId": authority_run_id,
            "payload": payload,
        }
        content_hash = canonical_sha256(envelope)
        return {
            "artifactRef": build_canonical_ref(
                kind=DELIVERY_ARTIFACT_KIND,
                team_id=team_id,
                authority_run_id=authority_run_id,
                content_hash=content_hash,
            ),
            "artifactContentHash": content_hash,
            "artifactRecordId": str(record.get("recordId") or ""),
        }

    def _fail(self, action: Any, *, now_ms: int, problem: dict[str, str]) -> None:
        def mutate(uow):
            uow.repository.fail_outbox(
                action.action_id,
                self._owner,
                now_ms,
                problem_json=json.dumps(problem, ensure_ascii=False),
            )

        self._submit(mutate, force_flush=True).result(timeout=30)

    def _commit_terminal(
        self,
        action: Any,
        *,
        run: Any,
        now_ms: int,
        outcome: dict[str, Any],
    ) -> None:
        """One tx: settle the outbox action + append the terminal event."""
        status = str(outcome.get("status") or "failed")
        _record_scene_event(
            "delivery.terminal",
            outcome=status,
            fields={
                "teamId": str(getattr(run, "team_id", "") or ""),
                "runId": str(getattr(run, "run_id", "") or ""),
                "deliveryStatus": status,
                "code": str(outcome.get("code") or ""),
                "failedStep": str(outcome.get("failedStep") or ""),
            },
        )
        if status == "failed":
            try:
                outcome.update(
                    self._persist_failure_artifact(action, run=run, outcome=outcome)
                )
            except Exception as exc:  # noqa: BLE001 - event settlement must survive artifact I/O
                diagnostics = [
                    str(item) for item in outcome.get("diagnostics") or []
                ]
                diagnostics.append(
                    f"delivery_failure_artifact_unavailable:{type(exc).__name__}:{exc}"
                )
                outcome["diagnostics"] = list(dict.fromkeys(diagnostics))

        def mutate(uow):
            if status == "failed":
                settled = uow.repository.fail_outbox(
                    action.action_id,
                    self._owner,
                    now_ms,
                    problem_json=json.dumps(
                        {
                            "code": str(outcome.get("code") or "delivery_failed"),
                            "detail": str(outcome.get("detail") or ""),
                        },
                        ensure_ascii=False,
                    ),
                )
            else:
                settled = uow.repository.ack_outbox(
                    action.action_id, self._owner, now_ms
                )
            if not settled:
                return
            sequence = uow.repository.advance_last_sequence(run.run_id, 1, now_ms)
            if sequence is None:
                return
            uow.repository.insert_event(
                build_delivery_event(
                    run=run,
                    sequence=sequence,
                    outcome=outcome,
                    actor_id=self._owner,
                    correlation_id=str(action.action_id or run.run_id),
                    now_ms=now_ms,
                )
            )

        self._submit(mutate, force_flush=True).result(timeout=30)
