import { readFileSync, existsSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeShellSource = readFileSync(new URL("./TeamsRouteWorkbench.tsx", import.meta.url), "utf8");
const routeModelSource = readFileSync(new URL("./useTeamsWorkbenchModel.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchFoundation.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchShellPhase.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchScLayer.ts", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./buildTeamsWorkbenchResearchSurfacesFromBag.ts", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./createTeamsWorkbenchResearchSurfaces.ts", import.meta.url), "utf8");
const canvasPageSource = readFileSync(new URL("./renderTeamsWorkbenchCanvasPage.tsx", import.meta.url), "utf8");
const boardPageSource = readFileSync(new URL("./renderTeamsWorkbenchBoardPage.tsx", import.meta.url), "utf8");
const routeSource = `${routeShellSource}\n${routeModelSource}\n${canvasPageSource}\n${boardPageSource}`;
const shellPath = new URL("./ResearchStageWorkbenchShell.tsx", import.meta.url);
const scComposerPath = new URL("./SourceCollectionComposer.tsx", import.meta.url);
const expComposerPath = new URL("./ExperimentStageComposer.tsx", import.meta.url);
const overviewComposerPath = new URL("./TeamsOverviewComposer.tsx", import.meta.url);
const canvasComposerPath = new URL("./TeamsCanvasComposer.tsx", import.meta.url);
const scController = readFileSync(
  new URL("./source-collection/createSourceCollectionController.tsx", import.meta.url),
  "utf8",
);
const expController = readFileSync(new URL("./createExperimentController.tsx", import.meta.url), "utf8");
const primaryRenderers = readFileSync(
  new URL("./teamResearchPrimarySurfaceRenderers.tsx", import.meta.url),
  "utf8",
);
const presentationSource = readFileSync(
  new URL("./useSourceCollectionPresentationCore.ts", import.meta.url),
  "utf8",
) + "\n" + readFileSync(
  new URL("./useSourceCollectionPresentationPipeline.ts", import.meta.url),
  "utf8",
) + "\n" + readFileSync(
  new URL("./useSourceCollectionPresentationMid.ts", import.meta.url),
  "utf8",
) + "\n" + readFileSync(
  new URL("./useSourceCollectionPresentationTail.ts", import.meta.url),
  "utf8",
);
const presentationMetricsPath = new URL(
  "./source-collection/presentationExtractionMetrics.ts",
  import.meta.url,
);
const scUiDir = new URL("./source-collection/ui/", import.meta.url);
const scPanelBarrel = readFileSync(new URL("./teamSourceCollectionPanels.ts", import.meta.url), "utf8");

describe("Teams clarity composers (① shell + F1/F4 controllers)", () => {
  it("stage shell and composers exist", () => {
    expect(existsSync(shellPath)).toBe(true);
    expect(existsSync(scComposerPath)).toBe(true);
    expect(existsSync(expComposerPath)).toBe(true);
    expect(existsSync(overviewComposerPath)).toBe(true);
    expect(existsSync(canvasComposerPath)).toBe(true);
    const shell = readFileSync(shellPath, "utf8");
    expect(shell).toContain('data-team-rail="hidden"');
    expect(shell).toContain("ResearchStageNav");
  });

  it("SC controller mounts SourceCollectionComposer", () => {
    expect(scController).toContain("SourceCollectionComposer");
    expect(scController).toContain("createSourceCollectionInjectRenderers");
    // R1-a: workbench uses composition; controller call not inline in workbench
    expect(routeSource).toContain("useTeamsScComposition");
    expect(routeSource).not.toContain("createSourceCollectionInjectRenderers({");
  });

  it("R1-b research surfaces factory exists", () => {
    expect(existsSync(new URL("./createTeamsResearchSurfaces.ts", import.meta.url))).toBe(true);
    const src = readFileSync(new URL("./createTeamsResearchSurfaces.ts", import.meta.url), "utf8");
    expect(src).toContain("createTeamsWorkspacePanelRenderers");
    expect(src).toContain("createResearchPrimarySurfaceRenderers");
    expect(src).toContain("createResearchWorkflowSurfaceRenderers");
    // R2-q: workbench uses createTeamsWorkbenchResearchSurfaces → createTeamsResearchSurfaces
    expect(routeSource).toMatch(/createTeamsResearchSurfaces|createTeamsWorkbenchResearchSurfaces|buildTeamsWorkbenchResearchSurfacesFromBag/);
    const workbenchResearch = readFileSync(new URL("./createTeamsWorkbenchResearchSurfaces.ts", import.meta.url), "utf8");
    expect(workbenchResearch).toContain("createTeamsResearchSurfaces");
  });

  it("R1-c shell frame helpers exist", () => {
    expect(existsSync(new URL("./renderTeamsShellFrame.tsx", import.meta.url))).toBe(true);
    const src = readFileSync(new URL("./renderTeamsShellFrame.tsx", import.meta.url), "utf8");
    expect(src).toContain("renderTeamsShellRail");
    expect(src).toContain("renderTeamsShellGate");
    expect(routeSource).toContain("renderTeamsShellGate");
  });

  it("R2-a/b workbench spreads scComposition and uses shell/overview bags", () => {
    expect(routeSource).toMatch(/\.\.\.scComposition|scComposition: d\.scComposition|scComposition,/);
    expect(routeSource).toContain("buildTeamsShellSurfaceModel");
    expect(routeSource).toContain("buildTeamWorkflowCandidatePreviewItems");
    expect(routeSource).toContain("buildSourceCollectionOverviewBag");
    expect(existsSync(new URL("./teamsShellSurfaceModel.ts", import.meta.url))).toBe(true);
    expect(existsSync(new URL("./buildTeamWorkflowCandidatePreviewItems.tsx", import.meta.url))).toBe(true);
    expect(existsSync(new URL("./buildSourceCollectionOverviewBag.ts", import.meta.url))).toBe(true);
  });

  it("R1-a workbench mounts SC via useTeamsScComposition", () => {
    expect(routeSource).toContain("useTeamsScComposition");
    expect(existsSync(new URL("./useTeamsScComposition.ts", import.meta.url))).toBe(true);
    const scComp = readFileSync(new URL("./useTeamsScComposition.ts", import.meta.url), "utf8");
    expect(scComp).toContain("useSourceCollectionPresentation");
    // R2-k: stage advance / modules / controller owned by composeSourceCollectionStageSurfaces
    expect(scComp).toContain("composeSourceCollectionStageSurfaces");
    const composeSurfaces = readFileSync(new URL("./composeSourceCollectionStageSurfaces.ts", import.meta.url), "utf8");
    expect(composeSurfaces).toContain("createSourceCollectionStageAdvance");
    expect(composeSurfaces).toContain("createSourceCollectionController");
    expect(composeSurfaces).toContain("buildSourceCollectionStageModules");
  });

  it("experiment controller owns standalone page render", () => {
    expect(expController).toContain("ExperimentStageComposer");
    expect(expController).toContain("renderStandalonePage");
    expect(primaryRenderers).toContain("createExperimentController");
    expect(primaryRenderers).not.toContain("TeamResearchStageStandalonePagePanel");
  });

  it("Overview/Canvas board mounts composers only (⑤)", () => {
    expect(routeSource).toContain("TeamsOverviewComposer");
    expect(routeSource).toContain("TeamsCanvasComposer");
    // R1-c: gate mounts via renderTeamsShellFrame → TeamsShellGateSurface
    expect(routeSource).toContain("renderTeamsShellGate");
    expect(routeSource).not.toContain("<VCanvasWorkbenchPage");
  });

  it("F3 presentation metrics extracted from hook body", () => {
    expect(existsSync(presentationMetricsPath)).toBe(true);
    expect(presentationSource).toContain("deriveSourceCollectionExtractionRecoveryMetrics");
    expect(presentationSource).toContain("presentationExtractionMetrics");
    // R2-m: count factory is owned by deriveSourceCollectionDisplayLabels
    const displayLabels = readFileSync(
      new URL("./source-collection/deriveSourceCollectionDisplayLabels.ts", import.meta.url),
      "utf8",
    );
    expect(displayLabels).toContain("makeSourceCollectionCountText");
    expect(presentationSource).toContain("deriveSourceCollectionDisplayLabels");
    expect(presentationSource).toContain("buildSourceCollectionActionReadinessBag");
    expect(presentationSource).toContain("buildSourceCollectionPipelineStepStates");
    expect(presentationSource).toContain("presentationActionReadiness");
    expect(presentationSource).toContain("presentationStepStates");
  });

  it("P4 SC panels live under source-collection/ui with pack re-exports", () => {
    expect(existsSync(new URL("./TeamSourceCollectionActiveStagePanel.tsx", scUiDir))).toBe(true);
    expect(scPanelBarrel).toContain('from "./source-collection/ui/TeamSourceCollectionActiveStagePanel"');
  });
});
