import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  fetchEffectiveAgentBindings,
  listResearchWorkflowRuns,
} from "../../../api/researchWorkflow";
import { queryKeys } from "../../../api/queryKeys";
import { CHALLENGE_CUP_WORKFLOW_ID } from "../../../api/types/researchWorkflow";
import { buildResearchRunOptions } from "./researchRunPresentation";

export function useResearchWorkflowCatalog(teamId: string, runVersion: number | null) {
  const enabled = Boolean(teamId.trim());
  const runsQuery = useQuery({
    queryKey: queryKeys.researchWorkflowRuns(CHALLENGE_CUP_WORKFLOW_ID, teamId),
    queryFn: () => listResearchWorkflowRuns(CHALLENGE_CUP_WORKFLOW_ID, { teamId }),
    enabled,
  });
  const bindingsQuery = useQuery({
    queryKey: queryKeys.researchWorkflowBindings(CHALLENGE_CUP_WORKFLOW_ID, teamId),
    queryFn: () => fetchEffectiveAgentBindings(CHALLENGE_CUP_WORKFLOW_ID, { teamId }),
    enabled,
  });

  useEffect(() => {
    if (enabled && runVersion !== null) void runsQuery.refetch();
    // Run version is a refresh signal, not query identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, runVersion]);

  const error = runsQuery.error || bindingsQuery.error;
  return {
    runOptions: buildResearchRunOptions(runsQuery.data?.runs ?? []),
    effectiveBindings: bindingsQuery.data?.bindings ?? null,
    loading: enabled && (runsQuery.isPending || bindingsQuery.isPending),
    error: !enabled
      ? "缺少 teamId，无法读取工作流目录"
      : error instanceof Error
        ? error.message
        : error
          ? String(error)
          : null,
  };
}
