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

// Warm the heavy workbench chunk as soon as the route chunk lands, so its
// download runs in parallel with the foundation query instead of forming a
// second waterfall behind the "正在载入团队数据…" fallback. Render structure
// and data flow stay untouched; failures surface through the lazy boundary.
void import("./TeamsWorkbenchWithScPhase").catch(() => undefined);

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
