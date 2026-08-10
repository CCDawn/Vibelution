import { useQuery } from "@tanstack/react-query";

import { fetchTeamWorkflowResearchProjects } from "../../../api/researchWorkflow";
import { researchProjectQueryKey } from "../research-projects/ResearchProjectSwitcher";

export function useResearchWorkflowProjectContext(teamId: string) {
  const normalizedTeamId = teamId.trim();
  const query = useQuery({
    queryKey: researchProjectQueryKey(normalizedTeamId),
    queryFn: () => fetchTeamWorkflowResearchProjects(normalizedTeamId),
    enabled: Boolean(normalizedTeamId),
  });

  return {
    activeProjectId: String(query.data?.activeProjectId || "").trim(),
    activeProjectName: String(
      query.data?.projects?.find((project) => project.projectId === query.data?.activeProjectId)?.name
      || query.data?.project?.name
      || "",
    ).trim(),
    loading: query.isPending,
    error: query.error instanceof Error ? query.error.message : query.error ? String(query.error) : null,
  };
}
