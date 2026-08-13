"""Formal protocol-draft context for the protocol-review Agent task."""

from __future__ import annotations

from typing import Any

from .research_runtime.artifact_readback_registry import (
    load_scoped_artifact_payload,
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def build_protocol_review_input_context(
    team_id: str,
    task: dict[str, Any],
) -> dict[str, Any]:
    """Load the protocol draft bound to the exact workflow run."""
    workflow_run_id = _text(task.get("workflowRunId"))
    source_run_id = _text(task.get("sourceCollectionRunId"))
    if not workflow_run_id or not source_run_id:
        return {
            "status": "blocked",
            "authority": "workflow_protocol_draft",
            "workflowRunId": workflow_run_id,
            "reason": "bound_workflow_identity_missing",
            "protocolDraft": None,
        }
    envelope = load_scoped_artifact_payload(
        "protocol_draft",
        team_id=_text(team_id),
        authority_run_id=source_run_id,
        workflow_run_id=workflow_run_id,
    )
    payload = (
        envelope.get("payload")
        if isinstance(envelope, dict) and isinstance(envelope.get("payload"), dict)
        else None
    )
    if not payload:
        return {
            "status": "blocked",
            "authority": "workflow_protocol_draft",
            "workflowRunId": workflow_run_id,
            "reason": "formal_protocol_draft_missing",
            "protocolDraft": None,
        }
    return {
        "status": "ready",
        "authority": "workflow_protocol_draft",
        "workflowRunId": workflow_run_id,
        "sourceCollectionRunId": source_run_id,
        "protocolDraft": payload,
    }
