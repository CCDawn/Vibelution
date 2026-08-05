/**
 * Selected-team resolution + detail query + workflow-kind flags.
 * Phase R2-e extract from useTeamsWorkbenchModel (behavior-conserving).
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { fetchJson } from "../../api/client";
import { queryKeys } from "../../api/queryKeys";
import type { Team } from "../../api/types";
import { RESEARCH_TEAM_ID, resolveTeamsRouteEffectiveTeamId } from "../TeamsRoute.canvasData";
import { useResearchProjectAgentTasks } from "./research-projects/useResearchProjectAgentTasks";
import type { ResearchWorkspaceView } from "./researchWorkspaceModel";
import {
  isAiSearchScopeTeam,
  isChallengeCupResearchWorkflowTeam,
  isKnowledgeExpansionWorkflowTeam,
  isResearchWorkflowTeam,
} from "./teamKindModel";
import {
  isForeignTeamDetailQueryKey,
  resolveTeamDetailLoadMode,
} from "./teamDetailLoadPolicy";

export type UseTeamsSelectedTeamDetailOptions = {
  forcedTeamId?: string;
  selectedTeamId: string;
  requestedTeamId: string;
  requestedAgentTeamId: string;
  visibleTeamIds: Set<string>;
  fallbackVisibleTeamId: string;
  visibleTeams: Team[];
  sourceCollectionStandalone: boolean;
  researchWorkspaceView: ResearchWorkspaceView | string;
};

export function useTeamsSelectedTeamDetail({
  forcedTeamId = "",
  selectedTeamId,
  requestedTeamId,
  requestedAgentTeamId,
  visibleTeamIds,
  fallbackVisibleTeamId,
  visibleTeams,
  sourceCollectionStandalone,
  researchWorkspaceView,
}: UseTeamsSelectedTeamDetailOptions) {
  const queryClient = useQueryClient();
  const selectedVisibleTeamId = selectedTeamId && visibleTeamIds.has(selectedTeamId) ? selectedTeamId : "";
  const effectiveTeamId = resolveTeamsRouteEffectiveTeamId({
    forcedTeamId,
    selectedTeamId: selectedVisibleTeamId,
    requestedTeamId,
    requestedAgentTeamId,
    visibleTeamIds,
    fallbackTeamId: fallbackVisibleTeamId,
  });
  const teamDetailLoadMode = resolveTeamDetailLoadMode({
    sourceCollectionStandalone,
    researchWorkspaceView,
  });

  useEffect(() => {
    const activeId = String(effectiveTeamId || "").trim();
    if (!activeId) {
      return;
    }
    void queryClient.cancelQueries({
      predicate: (query) => isForeignTeamDetailQueryKey(query.queryKey, activeId),
    });
  }, [effectiveTeamId, queryClient]);

  const selectedTeamReference = visibleTeams.find((team) => team.teamId === effectiveTeamId) ?? null;
  const teamDetailQuery = useQuery<Team>({
    queryKey: queryKeys.team(effectiveTeamId, teamDetailLoadMode),
    queryFn: ({ signal }) =>
      fetchJson<Team>(
        `/api/teams/${encodeURIComponent(effectiveTeamId)}?detail=${teamDetailLoadMode}`,
        { signal },
      ),
    enabled: Boolean(effectiveTeamId),
    staleTime: 10_000,
    placeholderData: () =>
      (selectedTeamReference && selectedTeamReference.teamId === effectiveTeamId
        ? selectedTeamReference
        : undefined),
  });
  const selectedTeam = teamDetailQuery.data ?? selectedTeamReference ?? null;
  const selectedTeamDetailLoading = Boolean(
    effectiveTeamId && selectedTeamReference && !teamDetailQuery.data && teamDetailQuery.isPending,
  );
  const knowledgeExpansionWorkflowTeamSelected = isKnowledgeExpansionWorkflowTeam(selectedTeam);
  const researchWorkflowTeamSelected = isResearchWorkflowTeam(selectedTeam);
  const challengeCupResearchTeamSelected = isChallengeCupResearchWorkflowTeam(selectedTeam);
  const researchStageProjectAgentTasks = useResearchProjectAgentTasks({
    teamId: selectedTeam?.teamId || RESEARCH_TEAM_ID,
    enabled:
      challengeCupResearchTeamSelected
      && !sourceCollectionStandalone
      && researchWorkspaceView !== "source_collection"
      && researchWorkspaceView !== "knowledge_collection",
  });
  const aiSearchScopeTeamSelected = isAiSearchScopeTeam(selectedTeam);
  const sourceCollectionWorkspaceSelected =
    researchWorkflowTeamSelected
    && (
      sourceCollectionStandalone
      || researchWorkspaceView === "source_collection"
      || researchWorkspaceView === "knowledge_collection"
    );

  return {
    selectedVisibleTeamId,
    effectiveTeamId,
    teamDetailLoadMode,
    selectedTeamReference,
    teamDetailQuery,
    selectedTeam,
    selectedTeamDetailLoading,
    knowledgeExpansionWorkflowTeamSelected,
    researchWorkflowTeamSelected,
    challengeCupResearchTeamSelected,
    researchStageProjectAgentTasks,
    aiSearchScopeTeamSelected,
    sourceCollectionWorkspaceSelected,
  };
}
