"""Controlled-write binding configuration store for research workflows.

Config layers are persisted per (workflowId, teamId) so multiple teams stay
isolated. Writing is "controlled": every payload is validated against the
workflow definition (roleKeys / stageIds / nodeIds must exist and target
agent nodes) before it is persisted. History is never affected — run
snapshots are the only per-run authority.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.research.workflow.bindings import node_spec
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.models import ActorKind, AgentBindingLayers

from .atomic_fs import atomic_write_text
from .store import default_run_store_dir


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class BindingConfigValidationError(Exception):
    def __init__(self, message: str, *, code: str = "invalid_binding_config"):
        super().__init__(message)
        self.code = code


class WorkflowBindingConfigStore:
    """Persists AgentBindingLayers under <root>/binding_config/{wf}--{team}.json.

    team_id "" is the shared default scope (workflow-level, no team).
    """

    def __init__(self, root: Path | None = None):
        self.root = (Path(root) if root else default_run_store_dir()) / "binding_config"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, workflow_id: str, team_id: str) -> Path:
        scope = str(team_id or "").strip() or "default"
        safe_team = "".join(c for c in scope if c.isalnum() or c in "-_")[:80]
        safe_workflow = "".join(c for c in str(workflow_id or "workflow").strip() if c.isalnum() or c in "-_")[:80]
        return self.root / f"{safe_workflow}--{safe_team}.json"

    def load(self, workflow_id: str, team_id: str) -> AgentBindingLayers:
        path = self._path(workflow_id, team_id)
        if not path.exists():
            return AgentBindingLayers()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return AgentBindingLayers()
        if not isinstance(data, dict):
            return AgentBindingLayers()
        return AgentBindingLayers(
            workflowDefaults={str(k): str(v) for k, v in (data.get("workflowDefaults") or {}).items()},
            stageOverrides={
                str(k): {str(rk): str(av) for rk, av in v.items()}
                for k, v in (data.get("stageOverrides") or {}).items()
            },
            nodeOverrides={str(k): str(v) for k, v in (data.get("nodeOverrides") or {}).items()},
        )

    def save(self, workflow_id: str, team_id: str, layers: AgentBindingLayers) -> dict[str, Any]:
        with self._lock:
            payload = {
                "workflowId": workflow_id,
                "teamId": str(team_id or "").strip(),
                "workflowDefaults": dict(layers.workflowDefaults),
                "stageOverrides": {k: dict(v) for k, v in layers.stageOverrides.items()},
                "nodeOverrides": dict(layers.nodeOverrides),
                "updatedAt": _utc_now(),
            }
            atomic_write_text(self._path(workflow_id, team_id), json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            return payload

    def validate_payload(self, payload: dict[str, Any]) -> None:
        """Controlled-write validation against the workflow definition."""
        definition = build_challenge_cup_workflow_definition()
        agent_nodes = [n for n in definition.nodes if n.actorKind is ActorKind.AGENT]
        role_keys = {n.primaryRoleKey for n in agent_nodes}
        stage_ids = {s.stageId.value for s in definition.stages}

        for role, agent_id in (payload.get("workflowDefaults") or {}).items():
            if str(role) not in role_keys:
                raise BindingConfigValidationError(f"Unknown roleKey: {role}", code="unknown_role")
            if not str(agent_id or "").strip():
                raise BindingConfigValidationError(f"workflowDefault {role} requires a non-empty agentId", code="empty_agent")

        for stage_id, roles in (payload.get("stageOverrides") or {}).items():
            if str(stage_id) not in stage_ids:
                raise BindingConfigValidationError(f"Unknown stageId: {stage_id}", code="unknown_stage")
            for role, agent_id in roles.items():
                if str(role) not in role_keys:
                    raise BindingConfigValidationError(f"Unknown roleKey: {role}", code="unknown_role")
                if not str(agent_id or "").strip():
                    raise BindingConfigValidationError(f"stageOverride {stage_id}/{role} requires a non-empty agentId", code="empty_agent")

        for node_id, agent_id in (payload.get("nodeOverrides") or {}).items():
            spec = node_spec(str(node_id))
            if spec is None or spec.actorKind is not ActorKind.AGENT:
                raise BindingConfigValidationError(f"Unknown or non-agent nodeId: {node_id}", code="unknown_node")
            if not str(agent_id or "").strip():
                raise BindingConfigValidationError(f"nodeOverride {node_id} requires a non-empty agentId", code="empty_agent")


def default_binding_config_store() -> WorkflowBindingConfigStore:
    return WorkflowBindingConfigStore()
