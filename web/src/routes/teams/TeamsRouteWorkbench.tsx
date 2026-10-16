import "../../design/route-css/teams.tailwind.css";
import { useSearchParams } from "react-router-dom";
import { GenericTeamWorkspaceRoute } from "./generic/GenericTeamWorkspaceRoute";
import { shouldOfferGenericWorkspace } from "./generic/workspaceRouteModel";

/**
 * Teams route entry (thin shell). Implementation lives in useTeamsWorkbenchModel.
 */
import {
  useTeamsWorkbenchModel,
  type TeamsRouteProps,
} from "./useTeamsWorkbenchModel";

export { linkedRoomRefetchInterval } from "./workflowPresentation";
export type { TeamsRouteProps };

function TeamsRouteInner(props: TeamsRouteProps) {
  return useTeamsWorkbenchModel(props);
}

export function TeamsRoute(props: TeamsRouteProps = {}) {
  const [params] = useSearchParams();
  const legacy = <TeamsRouteInner {...props} />;
  return shouldOfferGenericWorkspace(props, params)
    ? <GenericTeamWorkspaceRoute forcedTeamId={props.forcedTeamId} legacy={legacy} />
    : legacy;
}
