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

  it("is wired from TeamsRoute", () => {
    expect(routeSource).toContain("useTeamResearchSecondaryQueries({");
    expect(routeSource).not.toContain("const experimentPlanningStatusQuery = useQuery({");
    expect(routeSource).not.toContain("const researchLoopStatusQuery = useQuery({");
  });

  it("preserves key status endpoints", () => {
    expect(queriesSource).toContain("/workflow-orchestration/experiments/status");
    expect(queriesSource).toContain("/workflow-orchestration/experiments/methods");
    expect(queriesSource).toContain("/workflow-orchestration/research-loop/templates");
    expect(queriesSource).toContain("/workflow-orchestration/research-loop/status");
  });
});
