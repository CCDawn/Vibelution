"""Durable delivery of Challenge Cup model invocation receipts.

The immutable receipt registry remains the only receipt fact source.  This
module only owns delivery intent: successful LLM outcomes are put in the
existing Ledger ``reconcile`` outbox, then a resident worker leases and
idempotently projects them into the registry.  Conversation state is never a
receipt retry source.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from typing import Any

from core.research.workflow.ledger import OutboxRecord, WorkflowLedgerStore
from core.research.workflow.ledger import outbox as outbox_api

from .ids import new_id
from .model_invocation_receipt_registry import (
    validate_question_model_invocation_receipt,
)

RECEIPT_PERSISTENCE_OUTBOX_KIND = "reconcile"
RECEIPT_PERSISTENCE_PAYLOAD_KIND = "challenge_model_invocation_receipt_persist"
RECEIPT_PERSISTENCE_IDEMPOTENCY_PREFIX = "challenge_receipt:"
DEFAULT_RECEIPT_PERSISTENCE_LEASE_MS = 30_000
DEFAULT_RECEIPT_PERSISTENCE_RETRY_DELAY_MS = 1_000
MAX_RECEIPT_PERSISTENCE_LEASE_ATTEMPTS = 5


def receipt_persistence_idempotency_key(
    *,
    team_id: str,
    question_id: str,
    workflow_run_id: str,
    receipt_id: str,
) -> str:
    return ":".join(
        (
            RECEIPT_PERSISTENCE_IDEMPOTENCY_PREFIX.rstrip(":"),
            str(team_id or "").strip(),
            str(question_id or "").strip().upper(),
            str(workflow_run_id or "").strip(),
            str(receipt_id or "").strip(),
        )
    )


def _canonical_payload_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def enqueue_question_model_invocation_receipt(
    store: WorkflowLedgerStore,
    *,
    team_id: str,
    question_id: str,
    workflow_run_id: str,
    receipt: Mapping[str, Any],
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Persist one idempotent delivery intent before conversation completion."""

    normalized_team = str(team_id or "").strip()
    normalized_question = str(question_id or "").strip().upper()
    normalized_run = str(workflow_run_id or "").strip()
    canonical_receipt = validate_question_model_invocation_receipt(
        receipt,
        question_id=normalized_question,
        workflow_run_id=normalized_run,
    )
    receipt_id = str(canonical_receipt.get("receiptId") or "").strip()
    if not normalized_team or not normalized_question or not normalized_run or not receipt_id:
        raise ValueError("receipt persistence scope is incomplete")
    timestamp = int(now_ms if now_ms is not None else time.time() * 1000)
    idempotency_key = receipt_persistence_idempotency_key(
        team_id=normalized_team,
        question_id=normalized_question,
        workflow_run_id=normalized_run,
        receipt_id=receipt_id,
    )
    payload = {
        "schemaVersion": 1,
        "kind": RECEIPT_PERSISTENCE_PAYLOAD_KIND,
        "teamId": normalized_team,
        "questionId": normalized_question,
        "workflowRunId": normalized_run,
        "receipt": canonical_receipt,
    }
    payload_json = _canonical_payload_json(payload)

    def mutate(uow):
        run = uow.repository.get_run(normalized_run)
        if run is None:
            raise ValueError("receipt workflow run is missing")
        if str(run.team_id or "").strip() != normalized_team or (
            str(run.question_id or "").strip().upper() != normalized_question
        ):
            raise ValueError("receipt workflow run scope mismatch")
        existing = uow.repository.execute(
            "SELECT action_id, payload_json, status FROM outbox_actions "
            "WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing is not None:
            try:
                existing_payload = json.loads(str(existing[1] or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError("receipt persistence outbox payload is corrupt") from exc
            if existing_payload != payload:
                raise ValueError("receipt persistence replay conflict")
            return {
                "actionId": str(existing[0]),
                "status": str(existing[2]),
                "created": False,
            }
        action_id = new_id("act")
        uow.repository.insert_outbox(
            OutboxRecord(
                action_id=action_id,
                run_id=normalized_run,
                command_id=None,
                node_run_id=None,
                action_kind=RECEIPT_PERSISTENCE_OUTBOX_KIND,
                idempotency_key=idempotency_key,
                payload_json=payload_json,
                status="pending",
                attempt_count=0,
                available_at_ms=timestamp,
                lease_owner=None,
                lease_expires_at_ms=None,
                last_problem_json=None,
                created_at_ms=timestamp,
                updated_at_ms=timestamp,
            )
        )
        return {"actionId": action_id, "status": "pending", "created": True}

    return dict(store.submit(mutate, force_flush=True).result(timeout=30))


def _register_receipts(team_id: str, **kwargs: Any) -> list[dict[str, Any]]:
    from .model_invocation_receipt_registry import (
        register_question_model_invocation_receipts,
    )

    return register_question_model_invocation_receipts(team_id, **kwargs)


class ReceiptPersistenceWorker:
    """Lease, validate, register and CAS-ack durable receipt intents."""

    def __init__(
        self,
        *,
        store: WorkflowLedgerStore,
        owner_id: str = "receipt-persistence-worker",
        lease_ms: int = DEFAULT_RECEIPT_PERSISTENCE_LEASE_MS,
        now_provider: Callable[[], int] | None = None,
        retry_delay_ms: int = DEFAULT_RECEIPT_PERSISTENCE_RETRY_DELAY_MS,
        register_receipts: Callable[..., list[dict[str, Any]]] | None = None,
    ) -> None:
        self._store = store
        self._owner = str(owner_id or "receipt-persistence-worker").strip()
        self._lease_ms = max(1, int(lease_ms))
        self._now = now_provider or (lambda: int(time.time() * 1000))
        self._retry_delay_ms = max(1, int(retry_delay_ms))
        self._register_receipts = register_receipts or _register_receipts

    def run_once(self, limit: int = 4) -> int:
        leased = outbox_api.lease_ready_actions(
            self._store,
            owner=self._owner,
            now_ms=self._now(),
            limit=limit,
            lease_ms=self._lease_ms,
            action_kinds=(RECEIPT_PERSISTENCE_OUTBOX_KIND,),
            idempotency_prefix=RECEIPT_PERSISTENCE_IDEMPOTENCY_PREFIX,
            max_attempts=MAX_RECEIPT_PERSISTENCE_LEASE_ATTEMPTS,
        )
        for action in leased:
            self._handle(action)
        return len(leased)

    def _handle(self, action: Any) -> None:
        try:
            team_id, question_id, workflow_run_id, receipt = self._validated_action(
                action
            )
        except (TypeError, ValueError, KeyError) as exc:
            self._fail(
                action,
                code="invalid_challenge_receipt_persistence_action",
                detail=str(exc),
            )
            return

        # Lease transitions stay short.  Registry fsync and its dedicated file
        # lock must not hold the global Workflow Ledger SQLite writer.
        if not outbox_api.renew_lease(
            self._store,
            action.action_id,
            self._owner,
            now_ms=self._now(),
            lease_ms=self._lease_ms,
        ):
            return
        try:
            self._register_receipts(
                team_id,
                question_id=question_id,
                workflow_run_id=workflow_run_id,
                receipts=[receipt],
            )
        except (TypeError, ValueError, KeyError) as exc:
            outbox_api.fail_action(
                self._store,
                action.action_id,
                self._owner,
                self._now(),
                _canonical_payload_json(
                    {
                        "code": "challenge_receipt_persistence_rejected",
                        "detail": str(exc)[:400],
                    }
                ),
            )
            return
        except Exception as exc:  # noqa: BLE001 - bounded durable retry
            now_ms = self._now()
            problem = {
                "code": "challenge_receipt_persistence_transient",
                "errorType": type(exc).__name__,
                "attemptCount": int(getattr(action, "attempt_count", 0) or 0),
                "maxAttempts": MAX_RECEIPT_PERSISTENCE_LEASE_ATTEMPTS,
            }
            if (
                int(getattr(action, "attempt_count", 0) or 0)
                >= MAX_RECEIPT_PERSISTENCE_LEASE_ATTEMPTS
            ):
                problem["code"] = "challenge_receipt_persistence_attempts_exhausted"
                outbox_api.fail_action(
                    self._store,
                    action.action_id,
                    self._owner,
                    now_ms,
                    _canonical_payload_json(problem),
                )
                return
            outbox_api.requeue_action(
                self._store,
                action.action_id,
                self._owner,
                now_ms,
                retry_at_ms=now_ms + self._retry_delay_for(action),
                problem_json=_canonical_payload_json(problem),
            )
            return
        # Registry delivery is idempotent.  If the fresh CAS loses ownership,
        # the next owner safely replays the same receipt and acknowledges it.
        outbox_api.ack_action(
            self._store,
            action.action_id,
            self._owner,
            self._now(),
        )

    def _validated_action(
        self,
        action: Any,
    ) -> tuple[str, str, str, dict[str, Any]]:
        raw = json.loads(str(getattr(action, "payload_json", "") or "{}"))
        if not isinstance(raw, dict):
            raise TypeError("receipt persistence payload must be an object")
        if (
            raw.get("schemaVersion") != 1
            or str(raw.get("kind") or "") != RECEIPT_PERSISTENCE_PAYLOAD_KIND
        ):
            raise ValueError("receipt persistence payload header is invalid")
        team_id = str(raw.get("teamId") or "").strip()
        question_id = str(raw.get("questionId") or "").strip().upper()
        workflow_run_id = str(raw.get("workflowRunId") or "").strip()
        receipt = validate_question_model_invocation_receipt(
            raw.get("receipt") if isinstance(raw.get("receipt"), Mapping) else {},
            question_id=question_id,
            workflow_run_id=workflow_run_id,
        )
        if workflow_run_id != str(getattr(action, "run_id", "") or "").strip():
            raise ValueError("receipt persistence action run mismatch")
        expected_key = receipt_persistence_idempotency_key(
            team_id=team_id,
            question_id=question_id,
            workflow_run_id=workflow_run_id,
            receipt_id=str(receipt.get("receiptId") or ""),
        )
        if expected_key != str(getattr(action, "idempotency_key", "") or ""):
            raise ValueError("receipt persistence idempotency key mismatch")
        run = self._store.get_run(workflow_run_id)
        if run is None or str(run.team_id or "").strip() != team_id or (
            str(run.question_id or "").strip().upper() != question_id
        ):
            raise ValueError("receipt persistence run scope mismatch")
        return team_id, question_id, workflow_run_id, receipt

    def _retry_delay_for(self, action: Any) -> int:
        attempt_count = max(1, int(getattr(action, "attempt_count", 1) or 1))
        return min(
            60_000,
            self._retry_delay_ms * (2 ** min(6, attempt_count - 1)),
        )

    def _fail(self, action: Any, *, code: str, detail: str) -> None:
        outbox_api.fail_action(
            self._store,
            action.action_id,
            self._owner,
            self._now(),
            _canonical_payload_json({"code": code, "detail": str(detail)[:400]}),
        )


__all__ = [
    "RECEIPT_PERSISTENCE_IDEMPOTENCY_PREFIX",
    "ReceiptPersistenceWorker",
    "enqueue_question_model_invocation_receipt",
    "receipt_persistence_idempotency_key",
]
