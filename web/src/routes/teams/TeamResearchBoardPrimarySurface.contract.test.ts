import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeSource = readFileSync(new URL("../TeamsRoute.tsx", import.meta.url), "utf8");
const surfaceSource = readFileSync(new URL("./TeamResearchBoardPrimarySurface.tsx", import.meta.url), "utf8");

describe("TeamResearchBoardPrimarySurface extraction contract", () => {
  it("TeamsRoute mounts the board primary surface once and shares inspector panels", () => {
    expect(routeSource).toContain(
      'import { TeamResearchBoardPrimarySurface } from "./teams/TeamResearchBoardPrimarySurface"',
    );
    expect(routeSource.match(/<TeamResearchBoardPrimarySurface[\s\S]*?\/>/g)?.length).toBe(1);
    // Shared inspector panels helper (function or extracted renderer binding).
    expect(routeSource).toContain("renderTeamsInspectorSharedPanels");
    expect(routeSource.match(/\{renderTeamsInspectorSharedPanels\(\)\}/g)?.length).toBe(2);
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
    expect(routeSource).toContain("boardPrimaryMode={boardPrimaryMode}");
    expect(routeSource).toContain("stageSlot=");
    expect(routeSource).toContain("renderResearchStageStandalonePage");
    expect(routeSource).toContain("showResearchStageWorkspace");
    // Stage tools live in a right resizable inspector, not stacked under primary.
    expect(routeSource).toContain("showBoardInspectorAside");
    expect(routeSource).toContain("aside={");
    expect(routeSource).toContain("TEAMS_BOARD_INSPECTOR_PANE");
    // Must not early-return the whole Teams shell for stage standalone.
    expect(routeSource).not.toMatch(
      /if\s*\(\s*stageStandaloneView\s*\)\s*\{\s*return\s+renderResearchStageStandalonePage/,
    );
    // CTA navigation must sync researchView into the URL.
    expect(routeSource).toContain('nextParams.set("researchView", view)');
  });

  it("surface progressive-fills overview shell; empty only when settled without workflow", () => {
    expect(surfaceSource).not.toContain("Loading research overview");
    expect(surfaceSource).not.toContain("正在读取科研总览");
    expect(surfaceSource).toContain("Research workflow is not initialized");
    expect(surfaceSource).toContain("workflowPending || workflowReady");
    expect(surfaceSource).toContain("fill");
  });
});
