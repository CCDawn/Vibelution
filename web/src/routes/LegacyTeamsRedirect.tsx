import { Navigate, useLocation } from "react-router-dom";

import { teamWorkspaceRoute } from "./teams/researchWorkspaceModel";

export function resolveLegacyTeamsRedirect(search: string): string {
  const teamId = new URLSearchParams(search).get("team")?.trim() ?? "";
  if (!teamId) {
    return "/teams";
  }
  // Canonical team home (flow + canvas), not a bare ?team= shell.
  return teamWorkspaceRoute(teamId);
}

export function LegacyTeamsRedirect() {
  const location = useLocation();
  return <Navigate to={resolveLegacyTeamsRedirect(location.search)} replace />;
}
