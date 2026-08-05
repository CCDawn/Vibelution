import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeShellSource = readFileSync(new URL("./TeamsRouteWorkbench.tsx", import.meta.url), "utf8");
const routeModelSource = readFileSync(new URL("./useTeamsWorkbenchModel.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchFoundation.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchShellPhase.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./buildTeamsWorkbenchResearchSurfacesFromBag.ts", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./createTeamsWorkbenchResearchSurfaces.ts", import.meta.url), "utf8");
const boardPageSource = readFileSync(new URL("./renderTeamsWorkbenchBoardPage.tsx", import.meta.url), "utf8");
const routeSource = `${routeShellSource}\n${routeModelSource}\n${boardPageSource}`;
const researchSurfacesSource = readFileSync(
  new URL("./createTeamsResearchSurfaces.ts", import.meta.url),
  "utf8",
);
const renderersSource = readFileSync(
  new URL("./teamResearchPrimarySurfaceRenderers.tsx", import.meta.url),
  "utf8",
);

describe("teamResearchPrimarySurfaceRenderers extraction", () => {
  it("TeamsRoute composes launcher/overview/standalone via R1-b research surfaces", () => {
    // R1-b: workbench mounts createTeamsResearchSurfaces; factory wires primary renderers.
    expect(routeSource).toMatch(/createTeamsResearchSurfaces|createTeamsWorkbenchResearchSurfaces|buildTeamsWorkbenchResearchSurfacesFromBag/);
    expect(researchSurfacesSource).toContain("createResearchPrimarySurfaceRenderers");
    expect(routeSource).toContain("renderResearchStageLauncher,");
    expect(routeSource).toContain("renderResearchOverviewSurface,");
    expect(routeSource).toContain("renderResearchStageStandalonePage,");
    expect(routeSource).not.toContain("function renderResearchStageLauncher(");
    expect(routeSource).not.toContain("function renderResearchOverviewSurface(");
    expect(routeSource).not.toContain("function renderResearchStageStandalonePage(");
    // Stage destinations mount inside board primary surface (not whole-route early return).
    expect(routeSource).toContain("boardPrimaryMode");
    expect(routeSource).toContain("stageSlot");
    expect(routeSource).toContain("showResearchStageWorkspace");
    expect(routeSource).not.toMatch(
      /if\s*\(\s*stageStandaloneView\s*\)\s*\{\s*return\s+renderResearchStageStandalonePage/,
    );
    expect(routeSource).toMatch(/createTeamsResearchSurfaces\(|createTeamsWorkbenchResearchSurfaces\(|buildTeamsWorkbenchResearchSurfacesFromBag\(/);
    expect(routeSource).toContain("renderTeamsWorkbenchBoardPage");
  });

  it("factory owns ResearchOverviewSurface, launcher, and standalone mounts", () => {
    expect(renderersSource).toContain("function renderResearchStageLauncher(");
    expect(renderersSource).toContain("function renderResearchOverviewSurface(");
    expect(renderersSource).toContain("function renderResearchStageStandalonePage(");
    expect(renderersSource).toContain("ResearchOverviewSurface");
    expect(renderersSource).toContain("ResearchBoardKanban");
    expect(renderersSource).toContain("TeamResearchStageLauncherPanel");
    // F4: experiment stage chrome via createExperimentController + ExperimentStageComposer
    expect(renderersSource).toContain("createExperimentController");
    expect(renderersSource).not.toContain("TeamResearchStageStandalonePagePanel");
    expect(renderersSource).toContain("embeddedInBoard");
  });
});
