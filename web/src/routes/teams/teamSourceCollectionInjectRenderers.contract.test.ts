import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeShellSource = readFileSync(new URL("./TeamsRouteWorkbench.tsx", import.meta.url), "utf8");
const routeModelSource = readFileSync(new URL("./useTeamsWorkbenchModel.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchFoundation.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchShellPhase.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./buildTeamsWorkbenchResearchSurfacesFromBag.ts", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./createTeamsWorkbenchResearchSurfaces.ts", import.meta.url), "utf8");
const routeSource = `${routeShellSource}\n${routeModelSource}`;
const scCompositionSource = readFileSync(new URL("./useTeamsScComposition.ts", import.meta.url), "utf8");
const injectSource = readFileSync(new URL("./teamSourceCollectionInjectRenderers.tsx", import.meta.url), "utf8");
const controllerSource = readFileSync(
  new URL("./source-collection/createSourceCollectionController.tsx", import.meta.url),
  "utf8",
);

describe("teamSourceCollectionInjectRenderers extraction", () => {
  it("TeamsRoute composes SC inject via domain controller (P5/F1)", () => {
    // R1-a / R2-k: controller lives in composeSourceCollectionStageSurfaces via scComposition
    const composeSource = readFileSync(new URL("./composeSourceCollectionStageSurfaces.ts", import.meta.url), "utf8");
    expect(routeSource).toContain("useTeamsScComposition");
    expect(scCompositionSource).toContain("composeSourceCollectionStageSurfaces");
    expect(composeSource).toContain("createSourceCollectionController");
    expect(composeSource).toContain("renderSourceCollectionActiveStagePanel");
    expect(composeSource).toContain("renderSourceCollectionSearchBrief");
    expect(routeSource).not.toContain("createSourceCollectionInjectRenderers({");
    expect(controllerSource).toContain("createSourceCollectionInjectRenderers");
  });

  it("inject factory still owns panel mounts", () => {
    expect(injectSource).toContain("export function createSourceCollectionInjectRenderers");
    expect(injectSource).toContain("renderSourceCollectionActiveStagePanel");
  });
});
