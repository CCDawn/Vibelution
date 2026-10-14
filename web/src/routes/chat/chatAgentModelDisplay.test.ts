import { describe, expect, it } from "vitest";
import workbenchSource from "./ChatCodingRouteWorkbench.tsx?raw";

// The boundary matters: legacy draft model pins remain readable for the
// independent financial bridge, but ordinary Agent sends must ignore them.
describe("ordinary Agent model authority", () => {
  it("does not submit a saved composer override", () => {
    const start = workbenchSource.indexOf("} = useChatComposerSubmitActions({");
    expect(start).toBeGreaterThan(0);
    const submitProps = workbenchSource.slice(start, workbenchSource.indexOf("\n  });", start));
    expect(submitProps).toContain("turnModelSelection: financeSurface && activeSessionId ? turnModelSelections[activeSessionId] ?? null : null");
  });

  it("displays the bound Agent model without requiring the full choice list", () => {
    const start = workbenchSource.indexOf("const agentModel = sessionLlmOptions?.model");
    expect(start).toBeGreaterThan(0);
    const modelControls = workbenchSource.slice(start, workbenchSource.indexOf("\n  useEffect", start));
    expect(modelControls).toContain("model: agentModel");
    expect(modelControls).not.toContain("choices");
    expect(modelControls).not.toContain("onSelectionChange");
    expect(modelControls).not.toContain("setTurnModelSelections");
    expect(workbenchSource).toContain("handleOpenAgentConfig(activeSessionAgent, sessionsById.get(activeSessionId ?? \"\") ?? null)");
    expect(workbenchSource).toContain('refetchOnMount: "always"');
  });

  it("sizes the context ring from saved scoped parameters instead of only the last call", () => {
    const start = workbenchSource.indexOf("const composerContextRing = useMemo");
    const ring = workbenchSource.slice(start, workbenchSource.indexOf("\n  const {", start));
    expect(ring).toContain("resolveComposerContextLimit({");
    expect(ring).toContain("modelParameters: !financeSurface && !verifiedCompanionMode ? sessionLlmOptionsQuery.data : undefined");
    expect(ring).toContain("agentId: detail?.agentId");
    expect(ring).toContain("sessionLlmOptionsQuery.data,");
  });
});
