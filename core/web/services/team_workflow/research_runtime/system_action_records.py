"""Durable action/observation records for external System adapters."""

from __future__ import annotations

import uuid
from typing import Any

from .node_execution_support import build_event, iso, replace_by_id, utc_now
from .store import WorkflowRunStore


class SystemActionError(ValueError):
    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


def find_system_action(
    record: dict[str, Any],
    *,
    node_id: str,
    command: str,
    idempotency_key: str,
) -> dict[str, Any] | None:
    return next(
        (
            dict(item)
            for item in record.get("systemActions") or []
            if item.get("nodeId") == node_id
            and item.get("command") == command
            and item.get("idempotencyKey") == idempotency_key
        ),
        None,
    )


def begin_system_action(
    store: WorkflowRunStore,
    *,
    record: dict[str, Any],
    node_id: str,
    node_run_id: str,
    attempt: int,
    command: str,
    idempotency_key: str,
    input_summary: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    existing = find_system_action(
        record,
        node_id=node_id,
        command=command,
        idempotency_key=idempotency_key,
    )
    if existing is not None:
        if existing.get("status") == "succeeded":
            return existing, False
        raise SystemActionError(
            "system action is incomplete; reconciliation is required",
            code="system_action_reconciliation_required",
        )
    now = iso(utc_now())
    action = {
        "actionId": f"action-{uuid.uuid4().hex[:12]}",
        "runId": record["runId"],
        "nodeId": node_id,
        "nodeRunId": node_run_id,
        "attempt": attempt,
        "command": command,
        "idempotencyKey": idempotency_key,
        "status": "issued",
        "inputSummary": dict(input_summary),
        "issuedAt": now,
        "completedAt": "",
        "observation": {},
        "artifactRef": "",
    }

    def mutation(current: dict[str, Any]) -> dict[str, Any]:
        prior = find_system_action(
            current,
            node_id=node_id,
            command=command,
            idempotency_key=idempotency_key,
        )
        if prior is not None:
            return current
        event = build_event(
            current,
            workflowId=current["workflowId"],
            workflowVersionId=current["workflowVersionId"],
            checkpointId=(current.get("langGraph") or {}).get("checkpointId") or "",
            nodeId=node_id,
            nodeRunId=node_run_id,
            attempt=attempt,
            type="ActionIssued",
            summary={
                "actionId": action["actionId"],
                "command": command,
                **input_summary,
            },
        )
        return {
            **current,
            "systemActions": [*(current.get("systemActions") or []), action],
            "events": [*(current.get("events") or []), event],
        }

    store.mutate_run(record["runId"], mutation)
    return action, True


def complete_system_action(
    store: WorkflowRunStore,
    *,
    run_id: str,
    action: dict[str, Any],
    observation: dict[str, Any],
    artifact_manifest: dict[str, Any] | None = None,
    artifact_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = iso(utc_now())

    def mutation(current: dict[str, Any]) -> dict[str, Any]:
        current_action = find_system_action(
            current,
            node_id=str(action["nodeId"]),
            command=str(action["command"]),
            idempotency_key=str(action["idempotencyKey"]),
        )
        if current_action is None:
            raise SystemActionError(
                "system action record disappeared",
                code="system_action_not_found",
            )
        if current_action.get("status") == "succeeded":
            return current
        completed = {
            **current_action,
            "status": "succeeded",
            "completedAt": now,
            "observation": dict(observation),
            "artifactRef": (
                str((artifact_manifest or {}).get("artifactId") or "")
            ),
        }
        actions = list(current.get("systemActions") or [])
        replace_by_id(actions, "actionId", completed["actionId"], completed)
        manifests = list(current.get("artifactManifests") or [])
        payloads = dict(current.get("artifactPayloads") or {})
        if artifact_manifest is not None:
            manifests.append(dict(artifact_manifest))
            if artifact_payload is not None:
                payloads[str(artifact_manifest["artifactId"])] = dict(artifact_payload)
        observation_event = build_event(
            current,
            workflowId=current["workflowId"],
            workflowVersionId=current["workflowVersionId"],
            checkpointId=(current.get("langGraph") or {}).get("checkpointId") or "",
            nodeId=completed["nodeId"],
            nodeRunId=completed["nodeRunId"],
            attempt=completed["attempt"],
            type="ObservationRecorded",
            summary={
                "actionId": completed["actionId"],
                "command": completed["command"],
                "status": observation.get("status"),
                "observationRef": observation.get("observationRef"),
            },
            artifactRefs=(
                [str(artifact_manifest["artifactId"])]
                if artifact_manifest is not None
                else []
            ),
        )
        receipt = {
            "receiptId": f"receipt-{uuid.uuid4().hex[:10]}",
            "runId": run_id,
            "nodeId": completed["nodeId"],
            "nodeRunId": completed["nodeRunId"],
            "command": completed["command"],
            "idempotencyKey": completed["idempotencyKey"],
            "status": "applied",
            "recordedAt": now,
        }
        event_record = {
            **current,
            "events": [*(current.get("events") or []), observation_event],
        }
        receipt_event = build_event(
            event_record,
            workflowId=current["workflowId"],
            workflowVersionId=current["workflowVersionId"],
            checkpointId=(current.get("langGraph") or {}).get("checkpointId") or "",
            nodeId=completed["nodeId"],
            nodeRunId=completed["nodeRunId"],
            attempt=completed["attempt"],
            type="CommandReceiptRecorded",
            summary={
                "receiptId": receipt["receiptId"],
                "command": completed["command"],
            },
        )
        return {
            **current,
            "systemActions": actions,
            "artifactManifests": manifests,
            "artifactPayloads": payloads,
            "commandReceipts": [*(current.get("commandReceipts") or []), receipt],
            "outbox": [
                *(current.get("outbox") or []),
                {
                    "outboxId": f"outbox-{uuid.uuid4().hex[:10]}",
                    "runId": run_id,
                    "nodeRunId": completed["nodeRunId"],
                    "effectType": "system.action.completed",
                    "idempotencyKey": completed["idempotencyKey"],
                    "receiptId": receipt["receiptId"],
                    "status": "delivered",
                    "recordedAt": now,
                },
            ],
            "events": [
                *(current.get("events") or []),
                observation_event,
                receipt_event,
            ],
        }

    updated = store.mutate_run(run_id, mutation)
    resolved = find_system_action(
        updated,
        node_id=str(action["nodeId"]),
        command=str(action["command"]),
        idempotency_key=str(action["idempotencyKey"]),
    )
    if resolved is None:
        raise SystemActionError(
            "system action completion was not persisted",
            code="system_action_not_found",
        )
    return resolved


def fail_system_action(
    store: WorkflowRunStore,
    *,
    run_id: str,
    action: dict[str, Any],
    error_code: str,
    message: str,
) -> None:
    now = iso(utc_now())

    def mutation(current: dict[str, Any]) -> dict[str, Any]:
        current_action = find_system_action(
            current,
            node_id=str(action["nodeId"]),
            command=str(action["command"]),
            idempotency_key=str(action["idempotencyKey"]),
        )
        if current_action is None or current_action.get("status") != "issued":
            return current
        failed = {
            **current_action,
            "status": "failed",
            "completedAt": now,
            "observation": {"status": "failed", "errorCode": error_code},
        }
        actions = list(current.get("systemActions") or [])
        replace_by_id(actions, "actionId", failed["actionId"], failed)
        event = build_event(
            current,
            workflowId=current["workflowId"],
            workflowVersionId=current["workflowVersionId"],
            checkpointId=(current.get("langGraph") or {}).get("checkpointId") or "",
            nodeId=failed["nodeId"],
            nodeRunId=failed["nodeRunId"],
            attempt=failed["attempt"],
            type="ObservationRecorded",
            summary={
                "actionId": failed["actionId"],
                "status": "failed",
                "errorCode": error_code,
                "message": message[:240],
            },
        )
        return {
            **current,
            "status": "blocked",
            "blockedReason": error_code,
            "systemActions": actions,
            "events": [*(current.get("events") or []), event],
        }

    store.mutate_run(run_id, mutation)
