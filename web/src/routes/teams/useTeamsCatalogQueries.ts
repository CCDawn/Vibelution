/**
 * Teams catalog bootstrap: list/query agents, derive picker visibility + membership.
 * Phase R2-d extract from useTeamsWorkbenchModel (behavior-conserving).
 * Team detail + canvas remain owned by the workbench model / shell hooks.
 */
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { fetchJson } from "../../api/client";
import {
  PROJECT_AGENT_BUS_TEAM_TIMELINE_LIMIT,
  listProjectAgentBusTimeline,
} from "../../api/projectAgentBus";
import { queryKeys } from "../../api/queryKeys";
import type { AgentConfigWorkspaceAgent, Team, TeamListPayload } from "../../api/types";
import { resolvePollingInterval } from "../../app/pollingPolicy";
import {
  RESEARCH_TEAM_ID,
  TEAM_PICKER_TEAM_IDS,
  resolveKnownRouteTeamId,
} from "../TeamsRoute.canvasData";
import { isEvolutionSystemTeam } from "./teamKindModel";
import {
  TEAM_BOOTSTRAP_ACTIVE_REFETCH_MS,
  TEAM_BOOTSTRAP_BACKGROUND_REFETCH_MS,
  TEAM_BOOTSTRAP_REFETCH_STATUSES,
} from "./workflowPresentation";

export type UseTeamsCatalogQueriesOptions = {
  pageVisible: boolean;
  /** Raw `team` search param (may be unknown / non-picker id). */
  requestedTeamId: string;
  /** Raw `agent` search param for membership deep-link. */
  requestedAgentId: string;
};

export function useTeamsCatalogQueries({
  pageVisible,
  requestedTeamId,
  requestedAgentId,
}: UseTeamsCatalogQueriesOptions) {
  const teamsQuery = useQuery({
    queryKey: queryKeys.teams(),
    queryFn: ({ signal }) => fetchJson<TeamListPayload>("/api/teams", { signal }),
    refetchInterval: (query) =>
      TEAM_BOOTSTRAP_REFETCH_STATUSES.has(query.state.data?.systemTeamBootstrap?.status ?? "")
        ? resolvePollingInterval(pageVisible, TEAM_BOOTSTRAP_ACTIVE_REFETCH_MS, {
          backgroundMs: TEAM_BOOTSTRAP_BACKGROUND_REFETCH_MS,
        })
        : false,
  });
  const agentSummaryQuery = useQuery({
    queryKey: queryKeys.agentSummary(false),
    queryFn: ({ signal }) => fetchJson<AgentConfigWorkspaceAgent[]>("/api/agents?detail=summary", { signal }),
    staleTime: 10_000,
  });
  const projectBusQuery = useQuery({
    queryKey: queryKeys.projectAgentBus(),
    queryFn: ({ signal }) => listProjectAgentBusTimeline(PROJECT_AGENT_BUS_TEAM_TIMELINE_LIMIT, { signal }),
  });

  const activeAgents = useMemo(
    () => (agentSummaryQuery.data ?? []).filter((agent) => agent.status !== "archived"),
    [agentSummaryQuery.data],
  );
  const activeAgentsById = useMemo(
    () => new Map(activeAgents.map((agent) => [agent.agentId, agent])),
    [activeAgents],
  );
  const teams = teamsQuery.data?.teams ?? [];
  const visibleTeams = useMemo(() => {
    const teamsById = new Map(
      teams.filter((team) => !isEvolutionSystemTeam(team)).map((team) => [team.teamId, team]),
    );
    return TEAM_PICKER_TEAM_IDS.map((teamId) => teamsById.get(teamId)).filter(
      (team): team is Team => Boolean(team),
    );
  }, [teams]);
  const visibleTeamIds = useMemo(
    () => new Set(visibleTeams.map((team) => team.teamId)),
    [visibleTeams],
  );
  const visibleTeamSummary = useMemo(() => {
    return visibleTeams.reduce(
      (summary, team) => {
        if (team.status !== "archived") {
          summary.activeTeamCount += 1;
        }
        summary.memberCount += team.memberCount ?? team.members.length;
        summary.staleMemberCount += team.members.filter((member) => member.agentStatus === "stale").length;
        return summary;
      },
      { activeTeamCount: 0, memberCount: 0, staleMemberCount: 0 },
    );
  }, [visibleTeams]);
  const hasTeams = visibleTeams.length > 0;
  const agentTeamMembership = useMemo(() => {
    const membership = new Map<string, { teamId: string; teamName: string }>();
    teams.forEach((team) => {
      if (team.status === "archived") {
        return;
      }
      (team.members ?? []).forEach((member) => {
        if (member.agentId) {
          membership.set(member.agentId, { teamId: team.teamId, teamName: team.name });
        }
      });
    });
    return membership;
  }, [teams]);

  const requestedAgentTeamId = requestedAgentId
    ? agentTeamMembership.get(requestedAgentId)?.teamId ?? ""
    : "";
  const requestedVisibleTeamId = resolveKnownRouteTeamId(requestedTeamId, visibleTeamIds);
  const requestedVisibleAgentTeamId =
    requestedAgentTeamId && visibleTeamIds.has(requestedAgentTeamId) ? requestedAgentTeamId : "";
  // Preview-aligned default: land on challenge-cup research board, not AI-search ops.
  const fallbackVisibleTeamId =
    (visibleTeamIds.has(RESEARCH_TEAM_ID) ? RESEARCH_TEAM_ID : "")
    || visibleTeams[0]?.teamId
    || "";

  return {
    teamsQuery,
    agentSummaryQuery,
    projectBusQuery,
    activeAgents,
    activeAgentsById,
    teams,
    visibleTeams,
    visibleTeamIds,
    visibleTeamSummary,
    hasTeams,
    agentTeamMembership,
    requestedAgentTeamId,
    requestedVisibleTeamId,
    requestedVisibleAgentTeamId,
    fallbackVisibleTeamId,
  };
}
