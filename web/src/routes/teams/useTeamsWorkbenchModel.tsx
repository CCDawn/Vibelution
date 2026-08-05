/**
 * R2-r: thin workbench entry — foundation data + shell phase returns.
 */
import type { TeamsRouteProps } from "./teamsWorkbenchChrome";
export type { TeamsRouteProps } from "./teamsWorkbenchChrome";
import { useTeamsWorkbenchFoundation } from "./useTeamsWorkbenchFoundation";
import { useTeamsWorkbenchShellPhase } from "./useTeamsWorkbenchShellPhase";

export function useTeamsWorkbenchModel(props: TeamsRouteProps) {
  const d = useTeamsWorkbenchFoundation(props);
  return useTeamsWorkbenchShellPhase(d);
}
