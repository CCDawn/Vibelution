import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeShellSource = readFileSync(new URL("../TeamsRouteWorkbench.tsx", import.meta.url), "utf8");
const routeModelSource = readFileSync(new URL("../useTeamsWorkbenchModel.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("../useTeamsWorkbenchFoundation.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("../useTeamsWorkbenchShellPhase.tsx", import.meta.url), "utf8");
const lazyScPhaseSource = readFileSync(new URL("../TeamsWorkbenchWithScPhase.tsx", import.meta.url), "utf8");
const scLayerSource = readFileSync(new URL("../useTeamsWorkbenchScLayer.ts", import.meta.url), "utf8");
const routeSource = `${routeShellSource}\n${routeModelSource}\n${lazyScPhaseSource}\n${scLayerSource}`;
const scCompositionSource = readFileSync(new URL("../useTeamsScComposition.ts", import.meta.url), "utf8");
const composeSurfacesSource = readFileSync(new URL("../composeSourceCollectionStageSurfaces.ts", import.meta.url), "utf8");
const controllerSource = readFileSync(new URL("./createSourceCollectionController.tsx", import.meta.url), "utf8");

describe("Clarity P5/F1 SourceCollectionController", () => {
  it("TeamsRoute does not own stage-session-task body or inject factory", () => {
    // R1-a / R2-k: workbench mounts SC composition; controller lives in composeSourceCollectionStageSurfaces
    expect(routeSource).toContain("useTeamsScComposition");
    expect(scCompositionSource).toContain("composeSourceCollectionStageSurfaces");
    expect(composeSurfacesSource).toContain("createSourceCollectionController");
    expect(composeSurfacesSource).toContain("createSourceCollectionStageAdvance");
    expect(routeSource).not.toContain("createSourceCollectionInjectRenderers");
    expect(routeSource).not.toContain("async function startSourceCollectionStageSessionTask");
    expect(routeSource).toContain("renderSourceCollectionStandalonePage");
  });

  it("controller owns stage advance + inject wiring + standalone render", () => {
    expect(controllerSource).toContain("export function createSourceCollectionStageAdvance");
    expect(controllerSource).toContain("export function createSourceCollectionController");
    expect(controllerSource).toContain("createSourceCollectionInjectRenderers");
    expect(controllerSource).toContain("preflightSourceCollectionStageAdvance");
    expect(controllerSource).toContain("renderStandalonePage");
    // ①: standalone chrome via SourceCollectionComposer (panel lives inside composer)
    expect(controllerSource).toContain("SourceCollectionComposer");
  });

  it("never falls back to a stale member id for Challenge Cup stage launch", () => {
    expect(controllerSource).toContain(
      'const agentId = String(binding?.agent?.agentId || "").trim();',
    );
    expect(controllerSource).not.toContain(
      'binding?.agent?.agentId || binding?.agentId',
    );
    expect(controllerSource).toContain("isChallengeCupResearchWorkflowTeam(selectedTeam)");
    expect(controllerSource).toContain('"/agents?pane=config"');
    expect(controllerSource).toContain("配置对应 Agent");
    expect(controllerSource).not.toContain("修复团队绑定");
    expect(controllerSource.indexOf("const initialChatState = sourceCollectionStageAgentChatState(stageId);"))
      .toBeLessThan(controllerSource.indexOf("const preflight = preflightSourceCollectionStageAdvance({"));
  });
});
