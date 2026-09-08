"""Project-scoped campaign records with command replay and version checks."""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from core.research.operator_optimization.contracts import (
    CampaignBudget,
    OperatorObjective,
    OptimizationCampaign,
)
from core.research.workflow.contracts._canonical import sha256_hex

from ..storage_durability import inter_process_lock


class CampaignConflict(ValueError):
    """A stale version or a changed idempotent command cannot overwrite work."""


def _service():
    from core.web.services import team_workflow_orchestration_service
    return team_workflow_orchestration_service


def campaign_root(team_id: str, project_id: str) -> Path:
    s = _service()
    s.get_research_project(team_id, project_id)
    return s._team_workflow_root(team_id, project_id) / "operator_optimization"


def _path(team_id: str, project_id: str, campaign_id: str) -> Path:
    if not re.fullmatch(r"opt-[a-f0-9]{24}", campaign_id):
        raise ValueError("Invalid optimizationCampaignId")
    return campaign_root(team_id, project_id) / "campaigns" / f"{campaign_id}.json"


def _load(team_id: str, project_id: str, campaign_id: str) -> dict[str, Any]:
    path = _path(team_id, project_id, campaign_id)
    if not path.is_file():
        raise FileNotFoundError("Optimization campaign not found in this research project")
    record = _service()._read_json(path)
    campaign = OptimizationCampaign.model_validate(record["campaign"])
    if (campaign.teamId, campaign.researchProjectId, campaign.optimizationCampaignId) != (team_id, project_id, campaign_id):
        raise CampaignConflict("Optimization campaign scope mismatch")
    return record


def create_campaign(team_id: str, project_id: str, payload: Mapping[str, Any]) -> OptimizationCampaign:
    s = _service()
    key = str(payload.get("idempotencyKey") or "").strip()
    if not key or len(key) > 200:
        raise ValueError("A bounded idempotencyKey is required")
    objective = OperatorObjective.model_validate(payload.get("objective") or {})
    budget = CampaignBudget.model_validate(payload.get("budget") or {})
    if budget.authorized:
        raise ValueError("Budget authorization must use the server operator action")
    config = {"title": payload.get("title"), "objective": objective.model_dump(), "budget": budget.model_dump()}
    fingerprint = sha256_hex(config)
    campaign_id = "opt-" + sha256_hex({"team": team_id, "project": project_id, "key": key})[:24]
    path = _path(team_id, project_id, campaign_id)
    with s._WORKFLOW_LOCK, inter_process_lock(path):
        if path.is_file():
            record = _load(team_id, project_id, campaign_id)
            if record["createFingerprint"] != fingerprint:
                raise CampaignConflict("idempotencyKey already belongs to a different campaign request")
            return OptimizationCampaign.model_validate(record["campaign"])
        now = s.utc_now_iso()
        campaign = OptimizationCampaign(
            optimizationCampaignId=campaign_id, teamId=team_id, researchProjectId=project_id,
            title=config["title"], objective=objective, budget=budget,
            baselineSetupId=f"baseline-{campaign_id}", createdAt=now, updatedAt=now,
        )
        s._write_json(path, {"campaign": campaign.model_dump(mode="json"), "createFingerprint": fingerprint, "commands": {}})
        return campaign


def read_campaign(team_id: str, project_id: str, campaign_id: str) -> OptimizationCampaign:
    with _service()._WORKFLOW_LOCK:
        return OptimizationCampaign.model_validate(_load(team_id, project_id, campaign_id)["campaign"])


def list_campaigns(team_id: str, project_id: str) -> list[OptimizationCampaign]:
    root = campaign_root(team_id, project_id) / "campaigns"
    return [read_campaign(team_id, project_id, path.stem) for path in sorted(root.glob("opt-*.json"))]


def update_campaign(
    team_id: str, project_id: str, campaign_id: str, *, expected_version: int | None,
    command_key: str, command: Mapping[str, Any],
    transform: Callable[[OptimizationCampaign], OptimizationCampaign],
) -> OptimizationCampaign:
    if not command_key or len(command_key) > 240:
        raise ValueError("A bounded command idempotency key is required")
    s = _service()
    fingerprint = sha256_hex(dict(command))
    with s._WORKFLOW_LOCK, inter_process_lock(_path(team_id, project_id, campaign_id)):
        record = _load(team_id, project_id, campaign_id)
        prior = record["commands"].get(command_key)
        if prior:
            if prior["fingerprint"] != fingerprint:
                raise CampaignConflict("Command key reused with a different payload")
            return OptimizationCampaign.model_validate(prior["result"])
        current = OptimizationCampaign.model_validate(record["campaign"])
        # Internal receipt/reservation events serialize against the current
        # record. User commands continue to supply an explicit expected version.
        if expected_version is not None and current.revision != expected_version:
            raise CampaignConflict("expectedCampaignVersion is stale")
        changed = transform(current)
        for key in ("optimizationCampaignId", "teamId", "researchProjectId", "objective", "baselineSetupId", "createdAt"):
            if getattr(current, key) != getattr(changed, key):
                raise CampaignConflict(f"Immutable campaign field changed: {key}")
        if current.baselineRef is not None and changed.baselineRef != current.baselineRef:
            raise CampaignConflict("The initial baseline is immutable")
        if current.baselineCandidateRef is not None and changed.baselineCandidateRef != current.baselineCandidateRef:
            raise CampaignConflict("The initial baseline candidate is immutable")
        result = OptimizationCampaign.model_validate({
            **changed.model_dump(mode="json"), "revision": current.revision + 1, "updatedAt": s.utc_now_iso(),
        })
        record["campaign"] = result.model_dump(mode="json")
        record["commands"][command_key] = {"fingerprint": fingerprint, "result": record["campaign"]}
        s._write_json(_path(team_id, project_id, campaign_id), record)
        return result
