import { useQuery } from "@tanstack/react-query";
import { listTeamFlows, teamFlowKeys } from "../../../api/genericTeamWorkflows";

/** One server response is shared by route preparation, placeholders and drafts. */
export function useWorkflowDefinitions(teamId: string) {
  return useQuery({
    queryKey: teamFlowKeys.flows(teamId),
    queryFn: ({ signal }) => listTeamFlows(teamId, signal),
    enabled: Boolean(teamId),
    staleTime: 10_000,
  });
}
