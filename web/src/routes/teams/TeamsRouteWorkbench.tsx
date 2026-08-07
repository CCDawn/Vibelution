import "../../design/route-css/teams.tailwind.css";

/**
 * Teams route entry (thin shell). Implementation lives in useTeamsWorkbenchModel.
 * Legacy researchView is normalized at the boundary before shell surface branches.
 */
import {
  useTeamsWorkbenchModel,
  type TeamsRouteProps,
} from "./useTeamsWorkbenchModel";
import { TeamsLegacyResearchBoundary } from "./research-workflow/TeamsLegacyResearchBoundary";

export { linkedRoomRefetchInterval } from "./workflowPresentation";
export type { TeamsRouteProps };

function TeamsRouteInner(props: TeamsRouteProps) {
  return useTeamsWorkbenchModel(props);
}

export function TeamsRoute(props: TeamsRouteProps = {}) {
  return (
    <TeamsLegacyResearchBoundary>
      <TeamsRouteInner {...props} />
    </TeamsLegacyResearchBoundary>
  );
}
