import { describe, expect, it } from "vitest";

import routeSource from "../TeamsRoute.tsx?raw";
import queriesSource from "./useTeamResearchSecondaryQueries.ts?raw";

describe("team research secondary queries contract", () => {
  it("owns experiment + research-loop status queries", () => {
    expect(queriesSource.match(/\buseQuery\(/g) ?? []).toHaveLength(4);
    expect(queriesSource).toContain("experimentPlanningStatusQuery");
    expect(queriesSource).toContain("experimentMethodCatalogQuery");
    expect(queriesSource).toContain("researchLoopTemplatesQuery");
    expect(queriesSource).toContain("researchLoopStatusQuery");
  });

  it("is wired via useResearchExperimentWorkspace from TeamsRoute", () => {
    expect(routeSource).toContain("resolveResearchSecondaryStatusQueryEnabled({");
    expect(routeSource).toMatch(
      /challengeProgramProgressVisible:\s*challengeCupResearchTeamSelected\s*&&\s*\(challengeTeamSurface === "progress"\s*\|\|\s*researchWorkspaceView === "overview"\)/,
    );
    // Phase 2: route owns enable gate; experiment workspace composes secondary queries.
    expect(routeSource).toContain("useResearchExperimentWorkspace({");
    expect(routeSource).toMatch(
      /useResearchExperimentWorkspace\(\{[\s\S]*researchSecondaryStatusQueryEnabled,[\s\S]*\}\)/,
    );
    expect(routeSource).not.toContain("useTeamResearchSecondaryQueries({");
    expect(routeSource).not.toContain("const experimentPlanningStatusQuery = useQuery({");
    expect(routeSource).not.toContain("const researchLoopStatusQuery = useQuery({");
  });

  it("preserves key status endpoints", () => {
    expect(queriesSource).toContain("/workflow-orchestration/experiments/status");
    expect(queriesSource).toContain("/workflow-orchestration/experiments/methods");
    expect(queriesSource).toContain("/workflow-orchestration/research-loop/templates");
    expect(queriesSource).toContain("/workflow-orchestration/research-loop/status");
  });

  it("keeps the method catalog independent from live status projections", () => {
    expect(queriesSource).toContain('["overview", "experiment"].includes(options.researchWorkspaceView)');
    expect(queriesSource.match(/enabled: options\.researchSecondaryStatusQueryEnabled/g) ?? []).toHaveLength(3);
  });
});
