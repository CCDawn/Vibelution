import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeSource = readFileSync(new URL("../TeamsRoute.tsx", import.meta.url), "utf8");
const renderersSource = readFileSync(
  new URL("./teamResearchPrimarySurfaceRenderers.tsx", import.meta.url),
  "utf8",
);

describe("teamResearchPrimarySurfaceRenderers extraction", () => {
  it("TeamsRoute composes launcher/overview/standalone from a factory after workspace panels", () => {
    expect(routeSource).toContain("createResearchPrimarySurfaceRenderers");
    expect(routeSource).toContain("renderResearchStageLauncher,");
    expect(routeSource).toContain("renderResearchOverviewSurface,");
    expect(routeSource).toContain("renderResearchStageStandalonePage,");
    expect(routeSource).not.toContain("function renderResearchStageLauncher(");
    expect(routeSource).not.toContain("function renderResearchOverviewSurface(");
    expect(routeSource).not.toContain("function renderResearchStageStandalonePage(");
    // stageStandalone must run after the factory initializes renderers
    const factoryAt = routeSource.indexOf("createResearchPrimarySurfaceRenderers({");
    const stageAt = routeSource.indexOf("if (stageStandaloneView)");
    expect(factoryAt).toBeGreaterThan(-1);
    expect(stageAt).toBeGreaterThan(factoryAt);
  });

  it("factory owns ResearchOverviewSurface, launcher, and standalone mounts", () => {
    expect(renderersSource).toContain("function renderResearchStageLauncher(");
    expect(renderersSource).toContain("function renderResearchOverviewSurface(");
    expect(renderersSource).toContain("function renderResearchStageStandalonePage(");
    expect(renderersSource).toContain("ResearchOverviewSurface");
    expect(renderersSource).toContain("ResearchBoardKanban");
    expect(renderersSource).toContain("TeamResearchStageLauncherPanel");
    expect(renderersSource).toContain("TeamResearchStageStandalonePagePanel");
  });
});
