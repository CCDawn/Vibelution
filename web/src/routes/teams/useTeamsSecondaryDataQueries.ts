/**
 * Secondary Teams data: panel pack warm-up + AI Search run list.
 * Phase R2-f extract from useTeamsWorkbenchModel (behavior-conserving).
 */
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import { queryKeys } from "../../api/queryKeys";
import { listTeamAiSearchRuns } from "../../api/teams";
import type { AiSearchRunListPayload } from "../../api/types";
import { AI_SEARCH_RUN_PREVIEW_LIMIT } from "./aiSearchPresentation";
import {
  prefetchTeamsPanelPacks,
  resolveTeamsPanelPrefetchPacks,
} from "./teamPanelPrefetch";
import { teamsPanelPackLoaders } from "./teamLazyPanels";
import {
  parseResearchWorkspaceView,
  type ResearchWorkspaceView,
} from "./researchWorkspaceModel";

export type UseTeamsSecondaryDataQueriesOptions = {
  effectiveTeamId: string;
  researchWorkflowTeamSelected: boolean;
  aiSearchScopeTeamSelected: boolean;
  sourceCollectionWorkspaceSelected: boolean;
  researchWorkspaceView: ResearchWorkspaceView | string;
};

export function useTeamsSecondaryDataQueries({
  effectiveTeamId,
  researchWorkflowTeamSelected,
  aiSearchScopeTeamSelected,
  sourceCollectionWorkspaceSelected,
  researchWorkspaceView,
}: UseTeamsSecondaryDataQueriesOptions) {
  // Path-scoped pack warm-up after team/view switch (not shell mount-all).
  useEffect(() => {
    const packs = resolveTeamsPanelPrefetchPacks({
      researchWorkflowTeamSelected,
      aiSearchScopeTeamSelected,
      sourceCollectionWorkspaceSelected,
      researchWorkspaceView:
        typeof researchWorkspaceView === "string"
          ? parseResearchWorkspaceView(researchWorkspaceView)
          : researchWorkspaceView,
    });
    if (packs.length === 0) {
      return;
    }
    prefetchTeamsPanelPacks(packs, teamsPanelPackLoaders);
  }, [
    researchWorkflowTeamSelected,
    aiSearchScopeTeamSelected,
    sourceCollectionWorkspaceSelected,
    researchWorkspaceView,
  ]);

  const aiSearchRunsQuery = useQuery<AiSearchRunListPayload>({
    queryKey: queryKeys.teamAiSearchRuns(effectiveTeamId || "none", AI_SEARCH_RUN_PREVIEW_LIMIT),
    queryFn: ({ signal }) =>
      listTeamAiSearchRuns(effectiveTeamId, {
        signal,
        limit: AI_SEARCH_RUN_PREVIEW_LIMIT,
      }),
    enabled: Boolean(effectiveTeamId && aiSearchScopeTeamSelected),
  });

  return {
    aiSearchRunsQuery,
  };
}
