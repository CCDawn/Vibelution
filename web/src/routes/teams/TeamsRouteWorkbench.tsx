import "../../design/route-css/teams.tailwind.css";

/**
 * Teams route entry (thin shell). Implementation lives in useTeamsWorkbenchModel.
 */
import {
  useTeamsWorkbenchModel,
  type TeamsRouteProps,
} from "./useTeamsWorkbenchModel";

export { linkedRoomRefetchInterval } from "./workflowPresentation";
export type { TeamsRouteProps };

export function TeamsRoute(props: TeamsRouteProps = {}) {
  return useTeamsWorkbenchModel(props);
}
