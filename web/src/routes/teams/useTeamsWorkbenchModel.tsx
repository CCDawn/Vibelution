/**
 * R2-r: thin workbench entry — foundation data + lazy SC/shell phase.
 */
import { lazy, Suspense, type ReactNode } from "react";

import type { TeamsRouteProps } from "./teamsWorkbenchChrome";
export type { TeamsRouteProps } from "./teamsWorkbenchChrome";
import { useTeamsWorkbenchFoundation } from "./useTeamsWorkbenchFoundation";
import { TeamsLoadingShell } from "./TeamsLoadingShell";

const TeamsWorkbenchWithScPhase = lazy(() =>
  import("./TeamsWorkbenchWithScPhase").then((module) => ({
    default: module.TeamsWorkbenchWithScPhase,
  })),
);

export function useTeamsWorkbenchModel(props: TeamsRouteProps): ReactNode {
  const base = useTeamsWorkbenchFoundation(props);
  return (
    <Suspense
      fallback={<TeamsLoadingShell lang={base.lang === "en" ? "en" : "zh"} />}
    >
      <TeamsWorkbenchWithScPhase base={base} />
    </Suspense>
  );
}
