import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  fetchEffectiveAgentBindings,
  fetchResearchWorkflowLaunchOptions,
} from "../../../api/researchWorkflow";
import { queryKeys } from "../../../api/queryKeys";
import { CHALLENGE_CUP_WORKFLOW_ID } from "../../../api/types/researchWorkflow";

export function useResearchWorkflowCatalog(teamId: string, runVersion: number | null) {
  const enabled = Boolean(teamId.trim());
  const launchQuery = useQuery({
    queryKey: queryKeys.researchWorkflowLaunchOptions(CHALLENGE_CUP_WORKFLOW_ID, teamId),
    queryFn: () => fetchResearchWorkflowLaunchOptions(CHALLENGE_CUP_WORKFLOW_ID, { teamId }),
    enabled,
  });
  const bindingsQuery = useQuery({
    queryKey: queryKeys.researchWorkflowBindings(CHALLENGE_CUP_WORKFLOW_ID, teamId),
    queryFn: () => fetchEffectiveAgentBindings(CHALLENGE_CUP_WORKFLOW_ID, { teamId }),
    enabled,
  });

  useEffect(() => {
    if (enabled && runVersion !== null) void launchQuery.refetch();
    // Run version is a refresh signal, not query identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, runVersion]);

  const error = launchQuery.error || bindingsQuery.error;
  return {
    questions: launchQuery.data?.questions ?? [],
    effectiveBindings: bindingsQuery.data?.bindings ?? null,
    loading: enabled && (launchQuery.isPending || bindingsQuery.isPending),
    error: !enabled
      ? "缺少 teamId，无法读取工作流目录"
      : error instanceof Error
        ? error.message
        : error
          ? String(error)
          : null,
  };
}
