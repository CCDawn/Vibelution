import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeShellSource = readFileSync(new URL("./TeamsRouteWorkbench.tsx", import.meta.url), "utf8");
const routeModelSource = readFileSync(new URL("./useTeamsWorkbenchModel.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchFoundation.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchShellPhase.tsx", import.meta.url), "utf8");
const routeSource = `${routeShellSource}\n${routeModelSource}`;
const hookSource = readFileSync(new URL("./useResearchExperimentWorkspace.ts", import.meta.url), "utf8");

describe("useResearchExperimentWorkspace Phase 2 contract", () => {
  it("TeamsRoute consumes the experiment workspace hook and no longer declares experiment draft useState", () => {
    expect(routeSource).toContain("useResearchExperimentWorkspace({");
    expect(routeSource).not.toContain("const [preferredExperimentMethod, setPreferredExperimentMethod]");
    expect(routeSource).not.toContain("const [experimentBaselineArtifactDraft, setExperimentBaselineArtifactDraft]");
    expect(routeSource).not.toContain("const [researchLoopCreateDraft, setResearchLoopCreateDraft]");
    expect(routeSource).not.toContain("} = useTeamResearchSecondaryQueries({");
  });

  it("hook owns drafts and composes secondary status queries", () => {
    expect(hookSource).toContain("export function useResearchExperimentWorkspace");
    expect(hookSource).toContain("useTeamResearchSecondaryQueries");
    expect(hookSource).toContain("experimentBaselineArtifactDraft");
    expect(hookSource).toContain("researchLoopDecisionDraft");
    expect(hookSource).toContain("experimentPlanningStatusQuery");
  });
});
