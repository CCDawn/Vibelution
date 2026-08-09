import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

import {
  parseResearchProcessLocation,
  patchResearchProcessSearch,
} from "./researchProcessLocation";
import { shouldApplyCanvasNodeSelection } from "./researchProcessPanelSelection";

export function useResearchWorkflowWorkspace(teamId: string) {
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useMemo(
    () => parseResearchProcessLocation(searchParams),
    [searchParams],
  );

  const replaceParams = useCallback(
    (patch: Record<string, string | null | undefined>) => {
      setSearchParams(
        patchResearchProcessSearch({ current: searchParams, teamId, patch }),
        { replace: true },
      );
    },
    [searchParams, setSearchParams, teamId],
  );

  const selectNode = useCallback(
    (nodeId: string | null) => {
      if (!shouldApplyCanvasNodeSelection({ nodeId, panel: location.panel })) return;
      replaceParams({ node: nodeId, panel: "node" });
    },
    [location.panel, replaceParams],
  );

  return { ...location, replaceParams, selectNode };
}
