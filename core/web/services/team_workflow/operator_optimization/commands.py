"""Activity commands own state transitions; HTTP is only a typed boundary."""
from __future__ import annotations

from ..research_runtime.operator_authorization import require_privileged_server_operator
from .store import CampaignConflict, update_campaign


def authorize_campaign(team_id: str, project_id: str, campaign_id: str, *, expected_version: int, command_key: str):
    # Use the existing privileged budget permission, not an unregistered action
    # name (unregistered action names do not enforce the role gate).
    operator = require_privileged_server_operator(command="extend_budget")

    def authorize(campaign):
        if campaign.status != "draft":
            raise CampaignConflict("Only a draft campaign budget can be authorized")
        if campaign.budget.gpuSecondsLimit <= 0:
            raise ValueError("A positive GPU time limit is required")
        return campaign.model_copy(update={
            "budget": campaign.budget.model_copy(update={"authorized": True}),
            "authorizedBy": operator.operator_id,
        })

    return update_campaign(team_id, project_id, campaign_id, expected_version=expected_version,
        command_key=command_key, command={"action": "authorize", "operatorId": operator.operator_id}, transform=authorize)
