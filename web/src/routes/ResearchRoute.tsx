/**
 * Task 9: ResearchRoute is retired (router-unreachable orphan).
 * Kept as a redirect shell so any residual deep link collapses to canonical workflow.
 */
import { Navigate, useLocation } from "react-router-dom";

import { resolveLegacyResearchLocation, canonicalHref } from "./teams/research-workflow/researchLegacyRouteResolver";

export function ResearchRoute() {
  const location = useLocation();
  const resolved = resolveLegacyResearchLocation({
    pathname: location.pathname,
    search: location.search,
  });
  return <Navigate to={canonicalHref(resolved)} replace />;
}
