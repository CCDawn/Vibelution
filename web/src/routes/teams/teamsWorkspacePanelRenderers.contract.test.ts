import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeSource = readFileSync(new URL("../TeamsRoute.tsx", import.meta.url), "utf8");
const renderersSource = readFileSync(new URL("./teamsWorkspacePanelRenderers.tsx", import.meta.url), "utf8");

describe("teamsWorkspacePanelRenderers extraction", () => {
  it("TeamsRoute composes workspace panel renderers from a factory", () => {
    expect(routeSource).toContain("createTeamsWorkspacePanelRenderers");
    expect(routeSource).toContain("renderExperimentPlanningLedgerPanel,");
    expect(routeSource).toContain("renderResearchLoopPanel,");
    expect(routeSource).toContain("renderTeamMemoryIndex,");
    expect(routeSource).not.toContain("function renderTeamMemoryIndex(");
    expect(routeSource).not.toContain("function renderResearchLoopPanel(");
    expect(routeSource).not.toContain("function renderExperimentPlanningLedgerPanel(");
    expect(routeSource).not.toContain("function renderAiSearchSourceScopePanel(");
  });

  it("factory owns memory/loop/ledger/canvas inspector mounts", () => {
    expect(renderersSource).toContain("function renderTeamMemoryIndex(");
    expect(renderersSource).toContain("function renderResearchLoopPanel(");
    expect(renderersSource).toContain("function renderExperimentPlanningLedgerPanel(");
    expect(renderersSource).toContain("function renderResearchCanvasReadOnlyPanel(");
    expect(renderersSource).toContain("function renderTeamNodeBindingPanel(");
    expect(renderersSource).toContain("TeamMemoryIndexPanel");
    expect(renderersSource).toContain("TeamExperimentPlanningLedgerPanel");
  });
});
