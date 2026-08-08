import { useQuery } from "@tanstack/react-query";

import { fetchJson } from "../../../api/client";
import type { TeamResearchProjectListPayload } from "../../../api/types/teams";
import { researchProjectQueryKey } from "../research-projects/ResearchProjectSwitcher";

export function useResearchWorkflowProjectContext(teamId: string) {
  const normalizedTeamId = teamId.trim();
  const query = useQuery({
    queryKey: researchProjectQueryKey(normalizedTeamId),
    queryFn: () =>
      fetchJson<TeamResearchProjectListPayload>(
        `/api/teams/${encodeURIComponent(normalizedTeamId)}/workflow-orchestration/research-projects`,
      ),
    enabled: Boolean(normalizedTeamId),
  });

  return {
    activeProjectId: String(query.data?.activeProjectId || "").trim(),
    loading: query.isPending,
    error: query.error instanceof Error ? query.error.message : query.error ? String(query.error) : null,
  };
}
