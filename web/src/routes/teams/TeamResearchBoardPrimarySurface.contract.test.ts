import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeShellSource = readFileSync(new URL("./TeamsRouteWorkbench.tsx", import.meta.url), "utf8");
const routeModelSource = readFileSync(new URL("./useTeamsWorkbenchModel.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchFoundation.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchShellPhase.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./buildTeamsWorkbenchResearchSurfacesFromBag.ts", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./createTeamsWorkbenchResearchSurfaces.ts", import.meta.url), "utf8");
const scCompositionSource = readFileSync(new URL("./useTeamsScComposition.ts", import.meta.url), "utf8");
const injectRenderersSource = readFileSync(new URL("./teamSourceCollectionInjectRenderers.tsx", import.meta.url), "utf8");
const researchSurfacesSource = readFileSync(new URL("./createTeamsResearchSurfaces.ts", import.meta.url), "utf8");
const researchNavigationSource = readFileSync(new URL("./createTeamsResearchNavigation.ts", import.meta.url), "utf8");
const overviewComposerSource = readFileSync(new URL("./TeamsOverviewComposer.tsx", import.meta.url), "utf8");
const boardPageSource = readFileSync(new URL("./renderTeamsWorkbenchBoardPage.tsx", import.meta.url), "utf8");
const routeSource = [routeShellSource, routeModelSource, scCompositionSource, injectRenderersSource, researchSurfacesSource, researchNavigationSource, overviewComposerSource, boardPageSource].join("\n");

const surfaceSource = readFileSync(new URL("./TeamResearchBoardPrimarySurface.tsx", import.meta.url), "utf8");

describe("TeamResearchBoardPrimarySurface extraction contract", () => {
  it("TeamsRoute mounts the board primary surface once and shares inspector panels", () => {
    // Board primary surface mounts inside TeamsOverviewComposer (R1 overview path).
    expect(overviewComposerSource).toMatch(
      /import \{ TeamResearchBoardPrimarySurface \} from ["']\.\/(?:teams\/)?TeamResearchBoardPrimarySurface["']/,
    );
    expect(overviewComposerSource.match(/<TeamResearchBoardPrimarySurface[\s\S]*?\/>/g)?.length).toBe(1);
    expect(routeSource).toContain("TeamsOverviewComposer");
    // Shared inspector panels helper (function or extracted renderer binding).
    expect(routeSource).toContain("renderTeamsInspectorSharedPanels");
    expect((routeSource.match(/renderTeamsInspectorSharedPanels\(\)/g) ?? []).length).toBeGreaterThanOrEqual(2);
    // Board overview fill states live in the surface module, not the route.
    expect(routeSource).not.toContain("Loading research overview");
    expect(routeSource).not.toContain("Research workflow is not initialized");
    expect(routeSource).not.toContain("初始化后总览会占满此主区");
  });

  it("routes experiment/iteration to stageSlot, not three-card launcher only", () => {
    expect(surfaceSource).toContain('boardPrimaryMode === "stage"');
    expect(surfaceSource).toContain("stageSlot");
    expect(surfaceSource).toContain("overviewSlot");
    expect(surfaceSource).toContain("launcherSlot");
    expect(routeSource).toContain("boardPrimaryMode");
    expect(routeSource).toContain("stageSlot");
    expect(routeSource).toContain("renderResearchStageStandalonePage");
    expect(routeSource).toContain("showResearchStageWorkspace");
    // Stage tools live in a right resizable inspector, not stacked under primary.
    expect(routeSource).toContain("showBoardInspectorAside");
    expect(routeSource).toContain("aside=");
    expect(routeSource).toContain("TEAMS_BOARD_INSPECTOR_PANE");
    // Must not early-return the whole Teams shell for stage standalone.
    expect(routeSource).not.toMatch(
      /if\s*\(\s*stageStandaloneView\s*\)\s*\{\s*return\s+renderResearchStageStandalonePage/,
    );
    // CTA navigation must sync researchView into the URL.
    expect(routeSource).toContain('nextParams.set("researchView", view)');
  });

  it("keeps the Challenge Cup operation workspace behind the explicit progress surface", () => {
    const shellPhaseSource = readFileSync(new URL("./useTeamsWorkbenchShellPhase.tsx", import.meta.url), "utf8");

    expect(shellPhaseSource).toMatch(
      /if\s*\(challengeCupResearchTeamSelected\s*&&\s*challengeTeamSurface\s*===\s*"progress"\)\s*\{\s*return renderResearchStageLauncher\("interactive"\);/,
    );
  });

  it("surface progressive-fills overview shell; empty only when settled without workflow", () => {
    expect(surfaceSource).not.toContain("Loading research overview");
    expect(surfaceSource).not.toContain("正在读取科研总览");
    expect(surfaceSource).toContain("Research workflow is not initialized");
    expect(surfaceSource).toContain("workflowPending || workflowReady");
    expect(surfaceSource).toContain("fill");
  });
});
