import { createContext, useContext, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { usePageVisibility } from "../../../app/pollingPolicy";
import { useTeamsCatalogQueries } from "../useTeamsCatalogQueries";
import { useWorkflowDefinitions } from "./useWorkflowDefinitions";
import { shouldOfferGenericWorkspace } from "./workspaceRouteModel";

const LoadingTeam = createContext({ teamId: "", teams: [] as { id: string; label: string }[] });
export const useWorkflowLoadingTeam = () => useContext(LoadingTeam);

/** Keep the request alive when Suspense hands off to the Teams route. */
function PrepareWorkflow({ children }: { children: ReactNode }) {
  const [params] = useSearchParams();
  const catalog = useTeamsCatalogQueries({
    pageVisible: usePageVisibility(),
    requestedTeamId: params.get("team") || params.get("teamId") || "",
    requestedAgentId: params.get("agent") || "",
  });
  // Use the real route's visible-team resolution, never raw URL IDs.
  const teamId = catalog.requestedVisibleTeamId || catalog.requestedVisibleAgentTeamId || catalog.fallbackVisibleTeamId;
  useWorkflowDefinitions(teamId);
  return <LoadingTeam.Provider value={{ teamId, teams: catalog.visibleTeams.map(team => ({ id: team.teamId, label: team.name })) }}>{children}</LoadingTeam.Provider>;
}

export function WorkflowLoadingBoundary({ children }: { children: ReactNode }) {
  const [params] = useSearchParams();
  return params.get("teamWorkspace") === "flows" && shouldOfferGenericWorkspace({}, params) ? <PrepareWorkflow>{children}</PrepareWorkflow> : children;
}
