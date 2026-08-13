"""Wait for canonical Task/Turn terminal and collect scoped domain artifact refs.

Production RealDomainPorts must not invent deterministic example.local payloads.
After Session/Task/Turn reaches a terminal success status, this module reconciles
Source Collection stage writeback and builds refs from real SC / ClaimEvidence
stores scoped by teamId + sourceCollectionRunId + workflowRunId.
"""

from __future__ import annotations

import json
import time
from typing import Any

from core.research.workflow.contracts import PendingAction

from .domain_ports import AgentTaskHandle

_SUCCESS_TERMINAL_STATUSES = frozenset({"ready", "completed", "done", "success"})
_FAILURE_TERMINAL_STATUSES = frozenset(
    {
        "failed",
        "failed_provider",
        "failed_runtime",
        "error",
        "cancelled",
        "canceled",
        "stopped",
        "stopped_by_user",
        "superseded",
        "paused_limit",
        "needs_continue",
    }
)

DEFAULT_AGENT_TURN_TIMEOUT_MS = 120_000


class TurnNotReadyError(RuntimeError):
    """Turn is still running; adapter should requeue rather than fail permanently."""

    def __init__(self, message: str, *, snapshot: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.snapshot = dict(snapshot or {})


def wait_for_agent_turn_terminal(
    session_id: str,
    turn_id: str,
    *,
    timeout_ms: int = DEFAULT_AGENT_TURN_TIMEOUT_MS,
    poll_ms: int = 200,
) -> dict[str, Any]:
    """Poll canonical turn completion until terminal success, failure, or timeout."""
    from core.web.services.session.turn_diagnostics import (
        get_session_turn_completion_snapshot,
    )

    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_session_id or not normalized_turn_id:
        raise RuntimeError(
            json.dumps(
                {
                    "code": "agent_turn_anchor_incomplete",
                    "sessionId": normalized_session_id,
                    "turnId": normalized_turn_id,
                },
                ensure_ascii=False,
            )
        )

    deadline = time.monotonic() + max(0, int(timeout_ms)) / 1000.0
    sleep_s = max(1, int(poll_ms)) / 1000.0
    last_snapshot: dict[str, Any] = {}
    while True:
        last_snapshot = get_session_turn_completion_snapshot(
            normalized_session_id, normalized_turn_id
        )
        if bool(last_snapshot.get("terminal")):
            status = str(
                last_snapshot.get("terminalStatus")
                or last_snapshot.get("lastTurnStatus")
                or ""
            ).strip().lower()
            if status in _SUCCESS_TERMINAL_STATUSES:
                return last_snapshot
            detail = {
                "code": "agent_turn_terminal_failed",
                "sessionId": normalized_session_id,
                "turnId": normalized_turn_id,
                "terminalStatus": status,
                "completionSource": last_snapshot.get("completionSource"),
                "failureClass": (
                    "terminal_failure"
                    if status in _FAILURE_TERMINAL_STATUSES
                    else "terminal_non_success"
                ),
            }
            raise RuntimeError(json.dumps(detail, ensure_ascii=False))
        if time.monotonic() >= deadline:
            raise TurnNotReadyError(
                json.dumps(
                    {
                        "code": "agent_turn_not_ready",
                        "sessionId": normalized_session_id,
                        "turnId": normalized_turn_id,
                        "terminal": False,
                        "terminalStatus": last_snapshot.get("terminalStatus"),
                        "completionSource": last_snapshot.get("completionSource"),
                        "timeoutMs": timeout_ms,
                    },
                    ensure_ascii=False,
                ),
                snapshot=last_snapshot,
            )
        time.sleep(sleep_s)


def collect_required_artifact_refs(
    node_id: str,
    *,
    team_id: str,
    workflow_run_id: str,
    source_collection_run_id: str,
) -> list[dict[str, str]]:
    """Build canonical refs from scoped SC / ClaimEvidence store payloads."""
    from .artifact_readback_registry import (
        build_canonical_ref,
        load_scoped_artifact_payload,
        required_artifact_kinds,
    )
    from .human_gate_artifacts import canonical_sha256

    kinds = required_artifact_kinds(node_id)
    if not kinds:
        return []
    normalized_team = str(team_id or "").strip()
    authority_run_id = (
        str(source_collection_run_id or "").strip()
        or str(workflow_run_id or "").strip()
    )
    if not normalized_team or not authority_run_id:
        raise RuntimeError(
            "team_id and source_collection_run_id/workflow_run_id are required "
            "to collect artifact refs"
        )

    refs: list[dict[str, str]] = []
    for kind in kinds:
        payload = load_scoped_artifact_payload(
            kind,
            team_id=normalized_team,
            authority_run_id=authority_run_id,
            workflow_run_id=str(workflow_run_id or "").strip(),
        )
        if payload is None:
            continue
        content_hash = canonical_sha256(payload)
        version = "1.0.0"
        refs.append(
            {
                "canonicalRef": build_canonical_ref(
                    kind=kind,
                    team_id=normalized_team,
                    authority_run_id=authority_run_id,
                    content_hash=content_hash,
                ),
                "kind": kind,
                "sha256": content_hash,
                "version": version,
            }
        )
    return refs


def complete_agent_turn_outputs(
    *,
    action: PendingAction,
    handle: AgentTaskHandle,
    input_snapshot: dict[str, Any],
    timeout_ms: int = DEFAULT_AGENT_TURN_TIMEOUT_MS,
    poll_ms: int = 200,
) -> list[dict[str, str]]:
    """Wait for turn terminal, reconcile SC stage writeback, collect store refs."""
    team_id = str(input_snapshot.get("teamId") or "").strip()
    if not team_id:
        raise RuntimeError("input snapshot has no teamId for agent turn completion")
    source_collection_run_id = (
        str(input_snapshot.get("sourceCollectionRunId") or "").strip()
        or str(action.run_id or "").strip()
    )

    snapshot = wait_for_agent_turn_terminal(
        handle.session_id,
        handle.turn_id,
        timeout_ms=timeout_ms,
        poll_ms=poll_ms,
    )

    task_id = str(handle.task_id or "").strip()
    if task_id:
        from core.web.services.team_workflow.source_collection.stage_writeback import (
            reconcile_source_collection_stage_session_task_after_turn,
        )

        reconcile_source_collection_stage_session_task_after_turn(
            team_id,
            task_id,
            run_id=source_collection_run_id,
            session_id=handle.session_id,
            turn_id=handle.turn_id,
            final_status=str(snapshot.get("terminalStatus") or ""),
            reason="session_turn_completed",
        )

    return collect_required_artifact_refs(
        action.node_id,
        team_id=team_id,
        workflow_run_id=str(action.run_id or ""),
        source_collection_run_id=source_collection_run_id,
    )
