import { useEffect, useRef } from "react";

import {
  resolveResearchProcessAutofocus,
  type ResearchProcessPanel,
} from "./researchProcessPanelSelection";

export function useResearchProcessAutofocus(input: {
  panel: ResearchProcessPanel;
  selectedNodeId: string | null;
  nextTarget: string | null;
  replaceParams: (patch: Record<string, string | null | undefined>) => void;
}) {
  const previousNextTargetRef = useRef<string | null>(null);

  useEffect(() => {
    const patch = resolveResearchProcessAutofocus({
      panel: input.panel,
      selectedNodeId: input.selectedNodeId,
      nextTarget: input.nextTarget,
      previousNextTarget: previousNextTargetRef.current,
    });
    previousNextTargetRef.current = input.nextTarget ?? null;
    if (patch) input.replaceParams(patch);
  }, [input.nextTarget, input.panel, input.replaceParams, input.selectedNodeId]);
}
