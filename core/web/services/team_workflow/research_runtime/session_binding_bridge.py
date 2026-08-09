"""Session binding bridge for workflow agent nodes.

Owns the NodeAgentSessionBinding write contract:
- only agent nodes with a non-empty run snapshot agentId may bind (unbound
  nodes fail closed — no session can be attached to a node without an agent);
- the bound agentId must match the run snapshot (or be absent and filled from
  it); a mismatch is rejected, never silently rewritten;
- replacing an existing binding records the old one into the run's
  bindingHistory with supersededAt (lineage preserved, no silent overwrite);
- the chat deep link only resolves when sessionId + taskId + turnId are ALL
  present — otherwise fail-closed and reported as degraded.
"""

from __future__ import annotations

import urllib.parse
import uuid
from typing import Any

from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.models import ActorKind

from .store import WorkflowRunStore


def _utc_now() -> str:
    from datetime import datetime, timezone

    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


class SessionBindingError(Exception):
    def __init__(self, message: str, *, code: str = "session_binding_error"):
        super().__init__(message)
        self.code = code


def chat_deep_link(
    *,
    session_id: str,
    task_id: str,
    turn_id: str,
    team_id: str,
    run_id: str,
    node_id: str,
) -> str | None:
    """Exact anchor deep link; None when any anchor field is missing."""
    if (
        not str(session_id or "").strip()
        or not str(task_id or "").strip()
        or not str(turn_id or "").strip()
    ):
        return None
    return_to = "/teams?" + urllib.parse.urlencode(
        {
            "teamId": team_id,
            "researchView": "workflow",
            "runId": run_id,
            "node": node_id,
            "panel": "node",
        }
    )
    return "/chat?" + urllib.parse.urlencode(
        {
            "session": session_id,
            "focusTask": task_id,
            "focusTurn": turn_id,
            "returnTo": return_to,
            "returnLabel": "workflow",
        }
    )


def snapshot_agent_id(record: dict[str, Any], node_id: str) -> str:
    for snap in record.get("bindingSnapshots") or []:
        if str(snap.get("nodeId") or "") == node_id:
            return str(snap.get("agentId") or "").strip()
    return ""


class SessionBindingBridge:
    def __init__(self, store: WorkflowRunStore):
        self._store = store

    def put(
        self,
        record: dict[str, Any],
        node_id: str,
        binding: dict[str, Any],
    ) -> dict[str, Any]:
        definition = build_challenge_cup_workflow_definition()
        node = next((n for n in definition.nodes if n.nodeId == node_id), None)
        if node is None:
            raise SessionBindingError(f"Unknown nodeId: {node_id}", code="unknown_node")
        if node.actorKind is not ActorKind.AGENT:
            raise SessionBindingError(
                f"Node {node_id} is not an agent node; session binding is only valid for agent nodes",
                code="non_agent_node",
            )
        snap_agent_id = snapshot_agent_id(record, node_id)
        if not snap_agent_id:
            raise SessionBindingError(
                f"Node {node_id} is unbound (no run snapshot agentId); bind an agent before attaching a session",
                code="unbound_node",
            )
        requested_agent_id = str(binding.get("agentId") or "").strip()
        agent_id = requested_agent_id or snap_agent_id
        if requested_agent_id and requested_agent_id != snap_agent_id:
            raise SessionBindingError(
                f"Session binding agentId {requested_agent_id} does not match run snapshot agentId {snap_agent_id} for {node_id}",
                code="binding_agent_mismatch",
            )

        required = ("sessionId", "taskId", "turnId")
        missing = [k for k in required if not str(binding.get(k) or "").strip()]
        run_id = str(record.get("runId") or "")
        previous = self._store.get_session_binding(run_id, node_id)
        if previous and all(
            str(previous.get(key) or "") == str(binding.get(key) or "")
            for key in ("nodeRunId", "agentId", "sessionId", "taskId", "turnId")
        ):
            return previous
        previous_binding_id = str(previous.get("bindingId") or "") if previous else ""
        supersedes = str(
            binding.get("supersedesBindingId") or previous_binding_id or ""
        )
        new_binding = {
            "bindingId": str(
                binding.get("bindingId") or f"nsb-{uuid.uuid4().hex[:10]}"
            ),
            "runId": run_id,
            "nodeId": node_id,
            "nodeRunId": str(binding.get("nodeRunId") or f"nr-{node_id}"),
            "nodeAttempt": int(binding.get("nodeAttempt") or 1),
            "agentId": agent_id,
            "roleKey": str(binding.get("roleKey") or "")
            or str(node.primaryRoleKey or ""),
            "sessionId": str(binding.get("sessionId") or ""),
            "sessionAttempt": int(binding.get("sessionAttempt") or 1),
            "taskId": str(binding.get("taskId") or ""),
            "turnId": str(binding.get("turnId") or ""),
            "checkpointId": str(binding.get("checkpointId") or ""),
            "status": "degraded" if missing else "bound",
            "boundAt": _utc_now(),
            "supersedesBindingId": supersedes,
            "missingFields": missing,
        }
        self._store.put_session_binding(run_id, node_id, new_binding)

        # Lineage: the superseded binding moves into bindingHistory (never
        # silently overwritten away).
        if previous and previous.get("bindingId") != new_binding["bindingId"]:
            history = list(record.get("bindingHistory") or [])
            if not any(
                str(h.get("bindingId") or "") == str(previous.get("bindingId") or "")
                for h in history
            ):
                history.append({**previous, "supersededAt": _utc_now()})
                self._store.update_run(run_id, {"bindingHistory": history})
        return new_binding

    def deep_link_for(
        self, record: dict[str, Any], node_id: str
    ) -> tuple[str | None, bool]:
        """Return (href, degraded). Fail-closed: missing anchor => no href + degraded."""
        binding = self._store.get_session_binding(
            str(record.get("runId") or ""), node_id
        )
        if not binding:
            return None, True
        href = chat_deep_link(
            session_id=str(binding.get("sessionId") or ""),
            task_id=str(binding.get("taskId") or ""),
            turn_id=str(binding.get("turnId") or ""),
            team_id=str(record.get("teamId") or ""),
            run_id=str(record.get("runId") or ""),
            node_id=node_id,
        )
        return href, href is None
