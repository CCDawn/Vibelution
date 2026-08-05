/**
 * R2-r: thin workbench entry — foundation data + lazy SC/shell phase.
 */
import { lazy, Suspense, type ReactNode } from "react";

import type { TeamsRouteProps } from "./teamsWorkbenchChrome";
export type { TeamsRouteProps } from "./teamsWorkbenchChrome";
import { useTeamsWorkbenchFoundation } from "./useTeamsWorkbenchFoundation";
import { teamsWorkbenchStyles as styles } from "./teamsWorkbenchChrome";

const TeamsWorkbenchWithScPhase = lazy(() =>
  import("./TeamsWorkbenchWithScPhase").then((module) => ({
    default: module.TeamsWorkbenchWithScPhase,
  })),
);

export function useTeamsWorkbenchModel(props: TeamsRouteProps): ReactNode {
  const base = useTeamsWorkbenchFoundation(props);
  return (
    <Suspense
      fallback={(
        <div className={styles.route} data-testid="teams-workbench-sc-loading" aria-busy="true">
          Loading teams workbench…
        </div>
      )}
    >
      <TeamsWorkbenchWithScPhase base={base} />
    </Suspense>
  );
}
