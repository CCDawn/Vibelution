import { describe, expect, it } from "vitest";

import routeShellSource from "./TeamsRouteWorkbench.tsx?raw";
import routeModelSourceThin from "./useTeamsWorkbenchModel.tsx?raw";
import routeFoundationSource from "./useTeamsWorkbenchFoundation.tsx?raw";
import routeShellPhaseSource from "./useTeamsWorkbenchShellPhase.tsx?raw";
const routeModelSource = `${routeModelSourceThin}\n${routeFoundationSource}\n${routeShellPhaseSource}`;
const routeSource = `${routeShellSource}\n${routeModelSource}\n${routeFoundationSource}\n${routeShellPhaseSource}`;
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
    expect(routeSource).toContain("challengeProgramProgressVisible: false");
    expect(routeSource).not.toContain("challengeTeamSurface");
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
    expect(queriesSource).toContain("fetchExperimentPlanningStatus<");
    expect(queriesSource).toContain("fetchExperimentMethodCatalog<");
    expect(queriesSource).not.toContain("/workflow-orchestration/experiments/status");
    expect(queriesSource).not.toContain("/workflow-orchestration/experiments/methods");
    expect(queriesSource).not.toContain("/workflow-orchestration/research-loop/templates");
    expect(queriesSource).not.toContain("/workflow-orchestration/research-loop/status");
    expect(queriesSource).toContain("fetchResearchLoopTemplates<");
    expect(queriesSource).toContain("fetchResearchLoopStatus<");
  });

  it("keeps the method catalog independent from live status projections", () => {
    expect(queriesSource).toContain('["overview", "experiment"].includes(options.researchWorkspaceView)');
    expect(queriesSource.match(/enabled: options\.researchSecondaryStatusQueryEnabled/g) ?? []).toHaveLength(3);
  });
});
