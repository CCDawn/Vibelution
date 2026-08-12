"""GraphDispatch payload factory (P1-1).

The single place that builds a ``graph_dispatch`` outbox payload with every
frozen field the coordinator needs: commandId, runId, nodeRunId, nodeId,
attempt, teamId, workflowVersionId, inputSnapshotHash, bindingSnapshotId and
budgetPolicyHash. No other writer may construct a graph_dispatch payload;
this keeps the LangGraph thread and the Ledger consistent even for
non-starting nodes (crash recovery re-derives the same fields).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from core.research.workflow.ledger import OutboxRecord

from .ids import new_id


def budget_policy_hash_from_input_snapshot(input_snapshot: Mapping[str, Any]) -> str:
    """Canonical hash of the frozen budgetPolicy (mirrors budget_lifecycle)."""
    policy = input_snapshot.get("budgetPolicy") or {}
    if not policy:
        return ""
    raw = json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def binding_snapshot_id_for_node(
    input_snapshot: Mapping[str, Any], node_id: str
) -> str | None:
    """Look up the frozen binding snapshot id for a node, if any."""
    for binding in input_snapshot.get("agentBindingSnapshot") or []:
        if not isinstance(binding, Mapping):
            continue
        if str(binding.get("nodeId") or "") == node_id:
            snapshot_id = str(binding.get("snapshotId") or "")
            return snapshot_id or None
    return None


def build_graph_dispatch_payload(
    *,
    run: Any,
    attempt: Any,
    command_id: str,
    dispatch_kind: str,
    receipt_payload: Mapping[str, Any] | None = None,
    state_update: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the full typed graph_dispatch payload from Ledger records."""
    input_snapshot = {}
    if run.input_snapshot_json:
        try:
            input_snapshot = json.loads(run.input_snapshot_json)
        except (TypeError, ValueError):
            input_snapshot = {}

    payload: dict[str, Any] = {
        "commandId": command_id,
        "runId": run.run_id,
        "nodeRunId": attempt.node_run_id,
        "nodeId": attempt.node_id,
        "attempt": attempt.attempt,
        "dispatchKind": dispatch_kind,
        "teamId": run.team_id,
        "workflowVersionId": run.workflow_version_id,
        "inputSnapshotHash": run.input_snapshot_hash
        or str(input_snapshot.get("snapshotHash") or ""),
        "budgetPolicyHash": budget_policy_hash_from_input_snapshot(input_snapshot),
    }
    binding_snapshot_id = attempt.binding_snapshot_id or binding_snapshot_id_for_node(
        input_snapshot, attempt.node_id
    )
    if binding_snapshot_id:
        payload["bindingSnapshotId"] = binding_snapshot_id
    if receipt_payload:
        payload["receipt"] = dict(receipt_payload)
    if state_update:
        payload["stateUpdate"] = dict(state_update)
    return payload


def build_graph_dispatch_record(
    *,
    run: Any,
    attempt: Any,
    command_id: str,
    dispatch_kind: str,
    now_ms: int,
    receipt_payload: Mapping[str, Any] | None = None,
    state_update: Mapping[str, Any] | None = None,
    idempotency_key: str | None = None,
    action_id: str | None = None,
) -> OutboxRecord:
    """Outbox record for the graph worker; stable idempotency key per dispatch."""
    payload = build_graph_dispatch_payload(
        run=run,
        attempt=attempt,
        command_id=command_id,
        dispatch_kind=dispatch_kind,
        receipt_payload=receipt_payload,
        state_update=state_update,
    )
    if idempotency_key is None:
        if dispatch_kind == "start":
            idempotency_key = f"graph:{command_id}"
        else:
            receipt = payload.get("receipt") or {}
            action_id_identity = str(receipt.get("actionId") or attempt.pending_action_id or new_id("act"))
            idempotency_key = f"graph:resume:{action_id_identity}"
    return OutboxRecord(
        action_id=action_id or new_id("act"),
        run_id=run.run_id,
        command_id=command_id,
        node_run_id=attempt.node_run_id,
        action_kind="graph_dispatch",
        idempotency_key=idempotency_key,
        payload_json=json.dumps(payload, ensure_ascii=False),
        status="pending",
        attempt_count=0,
        available_at_ms=now_ms,
        lease_owner=None,
        lease_expires_at_ms=None,
        last_problem_json=None,
        created_at_ms=now_ms,
        updated_at_ms=now_ms,
    )
