/**
 * Teams main-entry boundary: normalize legacy research query → canonical workflow
 * BEFORE any board/stage surface branch. Uses replace to avoid back-button loops.
 */
import { type ReactNode, useMemo } from "react";
import { Navigate, useLocation } from "react-router-dom";

import {
  canonicalHref,
  resolveLegacyResearchLocation,
} from "./researchLegacyRouteResolver";

export type TeamsLegacyResearchBoundaryProps = {
  children: ReactNode;
  /** Optional override for tests. */
  pathname?: string;
  search?: string;
};

export function shouldReplaceLegacyResearchLocation(options: {
  pathname: string;
  search: string;
}): { replace: boolean; href: string; mappedFrom: string; wasCanonical: boolean } {
  const resolved = resolveLegacyResearchLocation({
    pathname: options.pathname || "/teams",
    search: options.search || "",
  });
  const href = canonicalHref(resolved);
  const currentPath = options.pathname || "/teams";
  const currentSearch = options.search.startsWith("?")
    ? options.search
    : options.search
      ? `?${options.search}`
      : "";
  // Normalize empty vs missing params carefully via URLSearchParams equality.
  const currentParams = new URLSearchParams(
    currentSearch.startsWith("?") ? currentSearch.slice(1) : currentSearch,
  );
  const nextParams = resolved.searchParams;
  const same =
    currentPath === resolved.pathname
    && paramsEqual(currentParams, nextParams);
  return {
    replace: !same,
    href,
    mappedFrom: resolved.mappedFrom,
    wasCanonical: resolved.wasCanonical && same,
  };
}

function paramsEqual(a: URLSearchParams, b: URLSearchParams): boolean {
  const keys = new Set([...a.keys(), ...b.keys()]);
  for (const key of keys) {
    if ((a.get(key) || "") !== (b.get(key) || "")) return false;
  }
  return true;
}

/**
 * On legacy URLs, replace-navigate to canonical workflow before children mount
 * business stage surfaces. Uses <Navigate replace> to avoid back-button loops.
 */
export function TeamsLegacyResearchBoundary({
  children,
  pathname: pathnameProp,
  search: searchProp,
}: TeamsLegacyResearchBoundaryProps) {
  const location = useLocation();
  const pathname = pathnameProp ?? location.pathname;
  const search = searchProp ?? location.search;
  const decision = useMemo(
    () => shouldReplaceLegacyResearchLocation({ pathname, search }),
    [pathname, search],
  );

  if (decision.replace) {
    return <Navigate to={decision.href} replace />;
  }
  return <>{children}</>;
}
