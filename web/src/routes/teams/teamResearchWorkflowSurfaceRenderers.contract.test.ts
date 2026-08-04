import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeSource = readFileSync(new URL("../TeamsRoute.tsx", import.meta.url), "utf8");
const renderersSource = readFileSync(
  new URL("./teamResearchWorkflowSurfaceRenderers.tsx", import.meta.url),
  "utf8",
);

describe("teamResearchWorkflowSurfaceRenderers extraction", () => {
  it("TeamsRoute composes research workflow surface renderers from a factory", () => {
    expect(routeSource).toContain("createResearchWorkflowSurfaceRenderers");
    expect(routeSource).toContain("renderResearchWorkflowPanel,");
    expect(routeSource).toContain("renderTeamCommunicationPanel,");
    expect(routeSource).not.toContain("function researchWorkflowStatusText()");
    expect(routeSource).not.toContain("function renderResearchWorkflowModules()");
    expect(routeSource).not.toContain("function renderTeamCommunicationPanel()");
  });

  it("factory owns workflow modules, panel host, and communication mounts", () => {
    expect(renderersSource).toContain("function researchWorkflowStatusText(");
    expect(renderersSource).toContain("function renderResearchWorkflowModules(");
    expect(renderersSource).toContain("function renderResearchWorkflowPanel(");
    expect(renderersSource).toContain("function renderTeamCommunicationPanel(");
    expect(renderersSource).toContain("TeamResearchWorkflowStageModules");
    expect(renderersSource).toContain("TeamResearchWorkflowPanelHost");
    expect(renderersSource).toContain("TeamCommunicationPanel");
  });
});
