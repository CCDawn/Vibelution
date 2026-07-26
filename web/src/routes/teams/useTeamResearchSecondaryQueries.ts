/**
 * Experiment planning + research-loop status/template queries for Teams.
 * EventSource-free; Route remains workspace-view gating boundary.
 */
import { useQuery } from "@tanstack/react-query";

import { fetchJson } from "../../api/client";
import type { ExperimentMethodCatalogPayload } from "../../api/types";
import {
  experimentMethodCatalogQueryKey,
  experimentPlanningStatusQueryKey,
  researchLoopStatusQueryKey,
  researchLoopTemplatesQueryKey,
  type ExperimentPlanningStatusPayload,
  type ResearchLoopStatusPayload,
  type ResearchLoopTemplatesPayload,
} from "./experimentLoopModel";
import type { ResearchWorkspaceView } from "./researchWorkspaceModel";

export type UseTeamResearchSecondaryQueriesOptions = {
  effectiveTeamId: string;
  researchWorkflowTeamSelected: boolean;
  researchWorkspaceView: ResearchWorkspaceView;
  sourceCollectionStandalone: boolean;
  researchSecondaryStatusQueryEnabled: boolean;
};

export function useTeamResearchSecondaryQueries(options: UseTeamResearchSecondaryQueriesOptions) {
  const experimentPlanningStatusQuery = useQuery({
    queryKey: experimentPlanningStatusQueryKey(options.effectiveTeamId || "none"),
    queryFn: ({ signal }) =>
      fetchJson<ExperimentPlanningStatusPayload>(
        `/api/teams/${encodeURIComponent(options.effectiveTeamId)}/workflow-orchestration/experiments/status`,
        { signal },
      ),
    enabled: options.researchSecondaryStatusQueryEnabled,
  });

  const experimentMethodCatalogQuery = useQuery({
    queryKey: experimentMethodCatalogQueryKey(options.effectiveTeamId || "none"),
    queryFn: ({ signal }) =>
      fetchJson<ExperimentMethodCatalogPayload>(
        `/api/teams/${encodeURIComponent(options.effectiveTeamId)}/workflow-orchestration/experiments/methods`,
        { signal },
      ),
    enabled: Boolean(
      options.effectiveTeamId
      && options.researchWorkflowTeamSelected
      && ["overview", "experiment"].includes(options.researchWorkspaceView)
      && !options.sourceCollectionStandalone,
    ),
  });

  const researchLoopTemplatesQuery = useQuery({
    queryKey: researchLoopTemplatesQueryKey(options.effectiveTeamId || "none"),
    queryFn: ({ signal }) =>
      fetchJson<ResearchLoopTemplatesPayload>(
        `/api/teams/${encodeURIComponent(options.effectiveTeamId)}/workflow-orchestration/research-loop/templates`,
        { signal },
      ),
    enabled: options.researchSecondaryStatusQueryEnabled,
  });

  const researchLoopStatusQuery = useQuery({
    queryKey: researchLoopStatusQueryKey(options.effectiveTeamId || "none"),
    queryFn: ({ signal }) =>
      fetchJson<ResearchLoopStatusPayload>(
        `/api/teams/${encodeURIComponent(options.effectiveTeamId)}/workflow-orchestration/research-loop/status`,
        { signal },
      ),
    enabled: options.researchSecondaryStatusQueryEnabled,
  });

  return {
    experimentPlanningStatusQuery,
    experimentMethodCatalogQuery,
    researchLoopTemplatesQuery,
    researchLoopStatusQuery,
  };
}
