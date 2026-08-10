import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const webSrc = resolve(import.meta.dirname, "../../..");
const routesRoot = resolve(webSrc, "routes");
const routerSource = readFileSync(resolve(webSrc, "app/router.tsx"), "utf8");

describe("research workflow legacy cleanup", () => {
  it("does not expose the retired research routes", () => {
    expect(routerSource).not.toContain('path: "research"');
    expect(routerSource).not.toContain('path: "research/flow-canvas"');
    expect(routerSource).not.toContain("ResearchFlowCanvasRedirect");
  });

  it.each([
    "ResearchRoute.tsx",
    "ResearchRoute.styles.ts",
    "ResearchRoute.layout.test.ts",
    "ResearchFlowCanvasRoute.tsx",
    "ResearchFlowCanvasRoute.styles.ts",
    "teams/research-workflow/researchLegacyRouteResolver.ts",
    "teams/research-workflow/TeamsLegacyResearchBoundary.tsx",
    "teams/research-workflow/researchWorkflowPollingController.ts",
    "teams/research-workflow/IterationDecisionPanel.tsx",
    "teams/challenge-cup/ChallengeCupOperationsWorkspace.tsx",
    "teams/challenge-cup/ChallengeCupStageRail.tsx",
  ])("physically removes %s", (relativePath) => {
    expect(existsSync(resolve(routesRoot, relativePath))).toBe(false);
  });

  it("keeps the single workflow workspace and exact session anchors", () => {
    expect(existsSync(resolve(routesRoot, "teams/research-workflow/ResearchProcessWorkspace.tsx"))).toBe(true);
    const anchor = readFileSync(
      resolve(routesRoot, "teams/research-workflow/chatSessionAnchor.ts"),
      "utf8",
    );
    expect(anchor).toContain("focusTask");
    expect(anchor).toContain("focusTurn");
    expect(anchor).toContain('params.set("teamId"');
    expect(anchor).not.toContain('params.set("team"');
  });
});
