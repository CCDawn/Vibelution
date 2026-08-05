import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeShellSource = readFileSync(new URL("./TeamsRouteWorkbench.tsx", import.meta.url), "utf8");
const routeModelSource = readFileSync(new URL("./useTeamsWorkbenchModel.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchFoundation.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchShellPhase.tsx", import.meta.url), "utf8");
const scCompositionSource = readFileSync(new URL("./useTeamsScComposition.ts", import.meta.url), "utf8");
const injectRenderersSource = readFileSync(new URL("./teamSourceCollectionInjectRenderers.tsx", import.meta.url), "utf8");
const researchSurfacesSource = readFileSync(new URL("./createTeamsResearchSurfaces.ts", import.meta.url), "utf8");
const routeSource = [routeShellSource, routeModelSource, scCompositionSource, injectRenderersSource, researchSurfacesSource].join("\n");

const surfaceSource = readFileSync(new URL("./teamResearchWorkflowSurfaceRenderers.tsx", import.meta.url), "utf8");
const modulesSource = readFileSync(new URL("./TeamResearchWorkflowStageModules.tsx", import.meta.url), "utf8");
const routeAndSurfaceSource = `${routeSource}\n${surfaceSource}`;

describe("TeamResearchWorkflowStageModules extraction contract", () => {
  it("TeamsRoute composes stage modules once via the extracted component", () => {
    expect(routeSource).toMatch(/createTeamsResearchSurfaces|createTeamsWorkbenchResearchSurfaces|buildTeamsWorkbenchResearchSurfacesFromBag/);
    expect(surfaceSource).toContain('from "./TeamResearchWorkflowStageModules"');
    expect(routeAndSurfaceSource).toContain("function renderResearchWorkflowModules(");
    expect(surfaceSource.match(/<TeamResearchWorkflowStageModules[\s\S]*?\/>/g)?.length).toBe(1);
    // Stage panel JSX no longer lives on the route.
    expect(routeSource).not.toContain("<TeamsSourceCollectionPanel");
    expect(routeSource).not.toContain("<TeamWorkflowCoordinationStatusPanel");
    expect(routeSource).not.toContain("<TeamWorkflowCandidatePreviewPanel");
    expect(routeSource).not.toContain("<TeamWorkflowSourceQualityStatusPanel");
  });

  it("modules host visibility-gated stage panels", () => {
    expect(modulesSource).toContain("visibility.sourceCollection");
    expect(modulesSource).toContain("visibility.coordination");
    expect(modulesSource).toContain("visibility.ingestion");
    expect(modulesSource).toContain("visibility.graph");
    expect(modulesSource).toContain("visibility.candidates");
    expect(modulesSource).toContain("TeamsSourceCollectionPanel");
    expect(modulesSource).toContain("TeamWorkflowCoordinationStatusPanel");
    expect(modulesSource).toContain("TeamWorkflowCandidatePreviewPanel");
    expect(modulesSource).toContain("资料搜索执行");
    expect(modulesSource).toContain("候选仓库还没有资料、笔记或机制候选");
  });
});
