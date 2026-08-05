import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeShellSource = readFileSync(new URL("./TeamsRouteWorkbench.tsx", import.meta.url), "utf8");
const routeModelSource = readFileSync(new URL("./useTeamsWorkbenchModel.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchFoundation.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchShellPhase.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./buildTeamsWorkbenchResearchSurfacesFromBag.ts", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./createTeamsWorkbenchResearchSurfaces.ts", import.meta.url), "utf8");
const scCompositionSource = readFileSync(new URL("./useTeamsScComposition.ts", import.meta.url), "utf8");
const injectRenderersSource = readFileSync(new URL("./teamSourceCollectionInjectRenderers.tsx", import.meta.url), "utf8");
const researchSurfacesSource = readFileSync(new URL("./createTeamsResearchSurfaces.ts", import.meta.url), "utf8");
const routeSource = [routeShellSource, routeModelSource, scCompositionSource, injectRenderersSource, researchSurfacesSource].join("\n");


describe("SC list chrome inject extraction", () => {
  it("TeamsRoute uses filter/pagination/stage-agents injects", () => {
    expect(routeSource).toContain("TeamSourceCollectionFilterBarInject");
    expect(routeSource).toContain("TeamSourceCollectionPaginationInject");
    expect(routeSource).toContain("TeamSourceCollectionStageAgentsInject");
    expect(routeSource).toContain("buildSourceCollectionControlsMetricsBag");
    expect(routeSource).toContain("buildSourceCollectionControlsFeedbackBag");
    // Inject components may appear in import names; workspace panels themselves must not mount.
    expect(routeSource).not.toMatch(/<TeamSourceCollectionFilterBar[\s>]/);
    expect(routeSource).not.toMatch(/<TeamSourceCollectionPagination[\s>]/);
    expect(routeSource).not.toMatch(/<TeamSourceCollectionStageAgentsPanel[\s>]/);
    expect(routeSource).not.toContain("source-step-${stageId}-");
  });
});
