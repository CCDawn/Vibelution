import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { resolveSourceCollectionScreeningRecommendedNextHint } from "./source-collection/injectModel";

const routeShellSource = readFileSync(new URL("./TeamsRouteWorkbench.tsx", import.meta.url), "utf8");
const routeModelSource = readFileSync(new URL("./useTeamsWorkbenchModel.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchFoundation.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchShellPhase.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./buildTeamsWorkbenchResearchSurfacesFromBag.ts", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./createTeamsWorkbenchResearchSurfaces.ts", import.meta.url), "utf8");
const scCompositionSource = readFileSync(new URL("./useTeamsScComposition.ts", import.meta.url), "utf8");
const injectRenderersSource = readFileSync(new URL("./teamSourceCollectionInjectRenderers.tsx", import.meta.url), "utf8");
const researchSurfacesSource = readFileSync(new URL("./createTeamsResearchSurfaces.ts", import.meta.url), "utf8");
const routeSource = [routeShellSource, routeModelSource, scCompositionSource, injectRenderersSource, researchSurfacesSource].join("\n");


describe("SC workspace inject extraction contract", () => {
  it("TeamsRoute mounts workspace injects instead of workspace panels directly", () => {
    expect(routeSource).toContain("TeamSourceCollectionRunSwitcherInject");
    expect(routeSource).toContain("TeamSourceCollectionScreeningInject");
    expect(routeSource).toContain("TeamSourceCollectionGraphInject");
    expect(routeSource).toContain("TeamSourceCollectionMemoryInject");
    expect(routeSource).toContain("TeamSourceCollectionSelectedSourceInject");
    expect(routeSource).toContain("TeamSourceCollectionConversationInject");
    expect(routeSource).not.toContain("<TeamSourceCollectionRunSwitcherPanel");
    expect(routeSource).not.toContain("<TeamSourceCollectionScreeningWorkspacePanel");
    expect(routeSource).not.toContain("<TeamSourceCollectionGraphWorkspacePanel");
    expect(routeSource).not.toContain("<TeamSourceCollectionMemoryWorkspacePanel");
    expect(routeSource).not.toContain("推荐下一步：右侧主按钮「补材料」");
  });

  it("screening recommended-next-hint pure rules stay deterministic", () => {
    expect(resolveSourceCollectionScreeningRecommendedNextHint({
      lang: "zh",
      needsAgentMaterial: true,
      pendingScreeningCount: 2,
      projectedApprovedCount: 0,
      screeningButtonText: "质量审查",
    })).toContain("补材料");

    expect(resolveSourceCollectionScreeningRecommendedNextHint({
      lang: "en",
      needsAgentMaterial: false,
      pendingScreeningCount: 3,
      projectedApprovedCount: 0,
      screeningButtonText: "Review",
    })).toContain("Review");

    expect(resolveSourceCollectionScreeningRecommendedNextHint({
      lang: "zh",
      needsAgentMaterial: false,
      pendingScreeningCount: 0,
      projectedApprovedCount: 2,
      screeningButtonText: "质量审查",
    })).toContain("进入关系整理");

    expect(resolveSourceCollectionScreeningRecommendedNextHint({
      lang: "en",
      needsAgentMaterial: false,
      pendingScreeningCount: 0,
      projectedApprovedCount: 0,
      screeningButtonText: "Review",
    })).toBeNull();
  });
});
