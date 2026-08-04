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
    expect(routeSource).toContain("function renderTeamsInspectorSharedPanels()");
    expect(routeSource.match(/\{renderTeamsInspectorSharedPanels\(\)\}/g)?.length).toBe(2);
    // Board overview fill states live in the surface module, not the route.
    expect(routeSource).not.toContain("Loading research overview");
    expect(routeSource).not.toContain("Research workflow is not initialized");
    expect(routeSource).not.toContain("初始化后总览会占满此主区");
  });

  it("surface owns overview loading/empty/ready and launcher branch", () => {
    expect(surfaceSource).toContain("Loading research overview");
    expect(surfaceSource).toContain("Research workflow is not initialized");
    expect(surfaceSource).toContain("overviewSlot");
    expect(surfaceSource).toContain("launcherSlot");
    expect(surfaceSource).toContain("fill");
  });
});
