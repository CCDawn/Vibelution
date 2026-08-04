import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeSource = readFileSync(new URL("../TeamsRoute.tsx", import.meta.url), "utf8");
const surfaceSource = readFileSync(new URL("./teamResearchWorkflowSurfaceRenderers.tsx", import.meta.url), "utf8");
const hostSource = readFileSync(new URL("./TeamResearchWorkflowPanelHost.tsx", import.meta.url), "utf8");
const routeAndSurfaceSource = `${routeSource}\n${surfaceSource}`;

describe("TeamResearchWorkflowPanelHost extraction contract", () => {
  it("TeamsRoute uses one host helper from both board and canvas shells", () => {
    expect(routeSource).toContain("createResearchWorkflowSurfaceRenderers");
    expect(surfaceSource).toContain('from "./TeamResearchWorkflowPanelHost"');
    expect(routeAndSurfaceSource).toContain("function renderResearchWorkflowPanel(");
    expect(routeAndSurfaceSource).toContain("function renderResearchWorkflowModules(");
    // Called from renderTeamsInspectorSharedPanels (used by board + canvas), not inlined twice.
    expect(routeSource.match(/\{renderResearchWorkflowPanel\(\)\}/g)?.length ?? 0).toBe(0);
    expect(routeSource.match(/\{renderTeamsInspectorSharedPanels\(\)\}/g)?.length).toBe(2);
    // Host JSX appears once inside the helper, not duplicated per shell.
    expect(surfaceSource.match(/<TeamResearchWorkflowPanelHost[\s\S]*?>/g)?.length).toBe(1);
    // Stage modules are composed once through TeamResearchWorkflowStageModules.
    expect(surfaceSource).toContain("TeamResearchWorkflowStageModules");
    expect(surfaceSource.match(/<TeamResearchWorkflowStageModules[\s\S]*?\/>/g)?.length).toBe(1);
  });

  it("host owns workflow section chrome, progressive loading, and empty states", () => {
    expect(hostSource).toContain('id="research-workflow-overview"');
    expect(hostSource).toContain("Research workflow");
    expect(hostSource).toContain("Loading research workflow");
    expect(hostSource).toContain("ProgressiveRegionSkeleton");
    expect(hostSource).not.toContain('tone="loading"');
    expect(hostSource).toContain("Research workflow is not initialized yet.");
    expect(hostSource).toContain("Select research-team to view the Challenge Cup workflow.");
    expect(hostSource).toContain("children");
  });
});
