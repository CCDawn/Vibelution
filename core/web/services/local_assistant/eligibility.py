"""Pure qualification shared by Launcher directory, discovery and task admission."""
from core.web.services.external_agent.policy import (
    ActiveTeamLookup,
    ExternalAgentEligibility,
    OperatorEnabled,
    external_mcp_eligibility,
)


def local_assistant_eligibility(agent, *, active_team_lookup: ActiveTeamLookup | None = None,
                                operator_enabled: OperatorEnabled | None = None) -> ExternalAgentEligibility:
    if isinstance(agent, dict) and (agent.get("protected") or agent.get("isProtected")):
        return ExternalAgentEligibility(False, "agent_protected")
    if isinstance(agent, dict):
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        # Archive protection (e.g. knowledge_steward's metadata.protected/fixedRole)
        # does not prohibit performing tasks. Dedicated Session identities do.
        if (agent.get("roleKey") == "personal_assistant" or any(metadata.get(key) or agent.get(key) for key in (
                "personalAssistantProfile", "virtualHumanCompanion", "virtualHumanSelfWake",
                "virtualHumanLifeSteward", "lifeStewardForAgentId", "selfWakeForAgentId", "companion"))):
            return ExternalAgentEligibility(False, "unsupported_agent_class")
    return external_mcp_eligibility(agent, active_team_lookup=active_team_lookup,
        operator_enabled=operator_enabled, operator_explicitly_enabled=lambda _agent_id: False)
