"""Controlled-write binding configuration store for research workflows.

Stage/node override layers are persisted per (workflowId, teamId) so multiple
teams stay isolated. Team workflow defaults come only from Team members.
Legacy workflowDefaults remain readable for non-Team scopes, but a Team-scoped
write clears them. History is never affected — run snapshots are the only
per-run authority.
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


def _require_mapping(value: Any, *, field: str) -> dict[Any, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise BindingConfigValidationError(
            f"{field} must be an object mapping to agentId strings",
            code="invalid_binding_shape",
        )
    return value


def _require_agent_id(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise BindingConfigValidationError(
            f"{field} must be a string agentId",
            code="invalid_agent_id_type",
        )
    if not value.strip():
        raise BindingConfigValidationError(
            f"{field} requires a non-empty agentId",
            code="empty_agent",
        )
    return value


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
        # Team membership is the only workflow-default authority for a scoped
        # run.  Drop any legacy value at the storage boundary so direct store
        # callers cannot revive a retired second binding source.
        raw_workflow_defaults = (
            {}
            if str(team_id or "").strip()
            else data.get("workflowDefaults") or {}
        )
        candidate = {
            "workflowDefaults": raw_workflow_defaults,
            "stageOverrides": data.get("stageOverrides") or {},
            "nodeOverrides": data.get("nodeOverrides") or {},
        }
        try:
            self.validate_payload(candidate)
        except BindingConfigValidationError:
            return AgentBindingLayers()
        return AgentBindingLayers(
            workflowDefaults={str(k): v for k, v in raw_workflow_defaults.items()},
            stageOverrides={
                str(k): {str(rk): av for rk, av in v.items()}
                for k, v in candidate["stageOverrides"].items()
            },
            nodeOverrides={str(k): v for k, v in candidate["nodeOverrides"].items()},
        )

    def save(self, workflow_id: str, team_id: str, layers: AgentBindingLayers) -> dict[str, Any]:
        with self._lock:
            candidate = {
                "workflowDefaults": dict(layers.workflowDefaults),
                "stageOverrides": {k: dict(v) for k, v in layers.stageOverrides.items()},
                "nodeOverrides": dict(layers.nodeOverrides),
            }
            self.validate_payload(candidate)
            workflow_defaults = (
                {}
                if str(team_id or "").strip()
                else candidate["workflowDefaults"]
            )
            payload = {
                "workflowId": workflow_id,
                "teamId": str(team_id or "").strip(),
                "workflowDefaults": workflow_defaults,
                "stageOverrides": candidate["stageOverrides"],
                "nodeOverrides": candidate["nodeOverrides"],
                "updatedAt": _utc_now(),
            }
            atomic_write_text(self._path(workflow_id, team_id), json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            return payload

    def validate_payload(self, payload: dict[str, Any]) -> None:
        """Controlled-write validation against the workflow definition."""
        if not isinstance(payload, dict):
            raise BindingConfigValidationError(
                "binding payload must be an object",
                code="invalid_binding_shape",
            )
        definition = build_challenge_cup_workflow_definition()
        agent_nodes = [n for n in definition.nodes if n.actorKind is ActorKind.AGENT]
        role_keys = {n.primaryRoleKey for n in agent_nodes}
        stage_ids = {s.stageId.value for s in definition.stages}

        workflow_defaults = _require_mapping(
            payload.get("workflowDefaults"),
            field="workflowDefaults",
        )
        stage_overrides = _require_mapping(
            payload.get("stageOverrides"),
            field="stageOverrides",
        )
        node_overrides = _require_mapping(
            payload.get("nodeOverrides"),
            field="nodeOverrides",
        )

        for role, agent_id in workflow_defaults.items():
            if str(role) not in role_keys:
                raise BindingConfigValidationError(f"Unknown roleKey: {role}", code="unknown_role")
            _require_agent_id(agent_id, field=f"workflowDefault {role}")

        for stage_id, roles in stage_overrides.items():
            if str(stage_id) not in stage_ids:
                raise BindingConfigValidationError(f"Unknown stageId: {stage_id}", code="unknown_stage")
            stage_roles = _require_mapping(
                roles,
                field=f"stageOverride {stage_id}",
            )
            for role, agent_id in stage_roles.items():
                if str(role) not in role_keys:
                    raise BindingConfigValidationError(f"Unknown roleKey: {role}", code="unknown_role")
                _require_agent_id(
                    agent_id,
                    field=f"stageOverride {stage_id}/{role}",
                )

        for node_id, agent_id in node_overrides.items():
            spec = node_spec(str(node_id))
            if spec is None or spec.actorKind is not ActorKind.AGENT:
                raise BindingConfigValidationError(f"Unknown or non-agent nodeId: {node_id}", code="unknown_node")
            _require_agent_id(agent_id, field=f"nodeOverride {node_id}")


def default_binding_config_store() -> WorkflowBindingConfigStore:
    return WorkflowBindingConfigStore()
