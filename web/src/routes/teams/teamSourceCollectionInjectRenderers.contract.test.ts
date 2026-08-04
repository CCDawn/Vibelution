import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeSource = readFileSync(new URL("../TeamsRoute.tsx", import.meta.url), "utf8");
const renderersSource = readFileSync(
  new URL("./teamSourceCollectionInjectRenderers.tsx", import.meta.url),
  "utf8",
);

describe("teamSourceCollectionInjectRenderers extraction", () => {
  it("TeamsRoute composes SC inject renderers from a factory", () => {
    expect(routeSource).toContain("createSourceCollectionInjectRenderers");
    expect(routeSource).toContain("renderSourceCollectionActiveStagePanel,");
    expect(routeSource).toContain("renderSourceCollectionSearchBrief,");
    expect(routeSource).toContain("renderSourceCollectionControlsPanel,");
    expect(routeSource).not.toContain("function renderSourceCollectionStageAgents(");
    expect(routeSource).not.toContain("function renderSourceCollectionRunSwitcher(");
    expect(routeSource).not.toContain("function renderSourceCollectionActiveStagePanel(");
    expect(routeSource).not.toContain("function renderSourceCollectionControlsPanel(");
  });

  it("factory owns SC inject panel mounts and controls bags", () => {
    expect(renderersSource).toContain("function renderSourceCollectionStageAgents(");
    expect(renderersSource).toContain("function renderSourceCollectionConversation(");
    expect(renderersSource).toContain("function renderSourceCollectionScreeningPanel(");
    expect(renderersSource).toContain("function renderSourceCollectionControlsPanel(");
    expect(renderersSource).toContain("function buildActiveStageExtractionRecoveryBag(");
    expect(renderersSource).toContain("TeamSourceCollectionActiveStageInject");
    expect(renderersSource).toContain("TeamSourceCollectionControlsInject");
    expect(renderersSource).toContain("buildSourceCollectionControlsFeedbackBag");
  });
});
