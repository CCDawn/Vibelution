import { Navigate, useLocation } from "react-router-dom";

export function resolveLegacyTeamsRedirect(search: string): string {
  const teamId = new URLSearchParams(search).get("team")?.trim() ?? "";
  if (!teamId) {
    return "/teams";
  }
  return `/teams?team=${encodeURIComponent(teamId)}`;
}

export function LegacyTeamsRedirect() {
  const location = useLocation();
  return <Navigate to={resolveLegacyTeamsRedirect(location.search)} replace />;
}
