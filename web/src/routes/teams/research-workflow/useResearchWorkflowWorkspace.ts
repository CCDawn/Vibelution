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
import { HYPOTHESIS_FIRST_GENERATION_NODE_ID } from "./hypothesisFirstCanvasRegion";

type ReplaceParams = (patch: Record<string, string | null | undefined>) => void;

type ArchivedRunResetRedirectInput = {
  runId: string;
  isArchivedRun: boolean;
  resetSource: string | undefined;
  currentPhase: string | undefined;
  replaceParams: ReplaceParams;
};

/**
 * A reset invalidates an archived formal run as an operational URL target.
 * Keep this routing consequence with the workspace URL adapter so the page
 * remains a composition of state readers and navigation owners.
 */
export function useArchivedRunResetRedirect({
  runId,
  isArchivedRun,
  resetSource,
  currentPhase,
  replaceParams,
}: ArchivedRunResetRedirectInput): void {
  const archivedRunSupersededByReset = Boolean(
    runId
    && isArchivedRun
    && resetSource === "question_reset_audit"
    && currentPhase !== "formal_runtime",
  );
  useEffect(() => {
    if (!archivedRunSupersededByReset) return;
    replaceParams({
      runId: null,
      node: HYPOTHESIS_FIRST_GENERATION_NODE_ID,
      panel: "node",
    });
  }, [archivedRunSupersededByReset, replaceParams]);
}

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
