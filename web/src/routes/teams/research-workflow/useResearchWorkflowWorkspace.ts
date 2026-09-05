import { useCallback, useEffect, useMemo, useRef } from "react";
import { useSearchParams } from "react-router-dom";

import {
  parseResearchProcessLocation,
  patchResearchProcessSearch,
} from "./researchProcessLocation";
import {
  shouldApplyCanvasNodeSelection,
  type ResearchProcessPanel,
} from "./researchProcessPanelSelection";

export function useResearchWorkflowWorkspace(teamId: string) {
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useMemo(
    () => parseResearchProcessLocation(searchParams),
    [searchParams],
  );
  const latestSearchRef = useRef(new URLSearchParams(searchParams));
  const pendingPanelRef = useRef<ResearchProcessPanel | null>(null);

  useEffect(() => {
    latestSearchRef.current = new URLSearchParams(searchParams);
  }, [searchParams]);

  useEffect(() => {
    if (pendingPanelRef.current === location.panel) pendingPanelRef.current = null;
  }, [location.panel]);

  const replaceParams = useCallback(
    (patch: Record<string, string | null | undefined>) => {
      const nextSearch = patchResearchProcessSearch({
        current: latestSearchRef.current,
        teamId,
        patch,
      });
      latestSearchRef.current = nextSearch;
      setSearchParams(nextSearch, { replace: true });
    },
    [setSearchParams, teamId],
  );

  const selectNode = useCallback(
    (nodeId: string | null) => {
      if (pendingPanelRef.current && pendingPanelRef.current !== "node") return;
      if (!shouldApplyCanvasNodeSelection({ nodeId, panel: location.panel })) return;
      replaceParams({ node: nodeId, panel: "node" });
    },
    [location.panel, replaceParams],
  );

  const openPanel = useCallback(
    (panel: ResearchProcessPanel) => {
      pendingPanelRef.current = panel;
      replaceParams({ panel });
    },
    [replaceParams],
  );

  return { ...location, replaceParams, selectNode, openPanel };
}
