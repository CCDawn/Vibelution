import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeShellSource = readFileSync(new URL("./TeamsRouteWorkbench.tsx", import.meta.url), "utf8");
const routeModelSource = readFileSync(new URL("./useTeamsWorkbenchModel.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchFoundation.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchShellPhase.tsx", import.meta.url), "utf8");
const scCompositionSource = readFileSync(new URL("./useTeamsScComposition.ts", import.meta.url), "utf8");
const injectRenderersSource = readFileSync(new URL("./teamSourceCollectionInjectRenderers.tsx", import.meta.url), "utf8");
const researchSurfacesSource = readFileSync(new URL("./createTeamsResearchSurfaces.ts", import.meta.url), "utf8");
const canvasPageSource = readFileSync(new URL("./renderTeamsWorkbenchCanvasPage.tsx", import.meta.url), "utf8");
const boardPageSource = readFileSync(new URL("./renderTeamsWorkbenchBoardPage.tsx", import.meta.url), "utf8");
const routeSource = [routeShellSource, routeModelSource, scCompositionSource, injectRenderersSource, researchSurfacesSource, canvasPageSource, boardPageSource].join("\n");

const surfaceSource = readFileSync(new URL("./teamResearchWorkflowSurfaceRenderers.tsx", import.meta.url), "utf8");
const panelSource = readFileSync(new URL("./TeamCommunicationPanel.tsx", import.meta.url), "utf8");
const routeAndSurfaceSource = `${routeSource}\n${surfaceSource}`;

describe("TeamCommunicationPanel extraction contract", () => {
  it("TeamsRoute mounts the shared communication panel via one render helper used by both shells", () => {
    expect(routeSource).toMatch(/createTeamsResearchSurfaces|createTeamsWorkbenchResearchSurfaces|buildTeamsWorkbenchResearchSurfacesFromBag/);
    expect(routeAndSurfaceSource).toContain("function renderTeamCommunicationPanel(");
    expect(surfaceSource).toContain('from "./TeamCommunicationPanel"');
    // Called from renderTeamsInspectorSharedPanels (used by board + canvas), not inlined twice.
    expect(routeSource.match(/\{renderTeamCommunicationPanel\(\)\}/g)?.length ?? 0).toBe(0);
    // Board/canvas shells both consume inspector shared panels (object prop or JSX call).
    expect((routeSource.match(/renderTeamsInspectorSharedPanels\(\)/g) ?? []).length).toBeGreaterThanOrEqual(2);
    const mounts = surfaceSource.match(/<TeamCommunicationPanel[\s\S]*?\/>/g) || [];
    expect(mounts.length).toBe(1);
    // Board/canvas must not re-inline discussion/broadcast forms.
    expect(routeSource).not.toContain("research-workflow-discussion");
    expect(routeSource).not.toContain("teamTaskForm");
    expect(routeSource).not.toContain("teamMessageForm");
  });

  it("panel owns discussion, broadcast, and history surfaces", () => {
    expect(panelSource).toContain('id="research-workflow-discussion"');
    expect(panelSource).toContain("teamTaskForm");
    expect(panelSource).toContain("teamMessageForm");
    expect(panelSource).toContain("teamHistoryPanel");
    expect(panelSource).toContain("Start team round");
    expect(panelSource).toContain("Send to team");
    expect(panelSource).toContain("Recent team broadcasts");
  });
});
