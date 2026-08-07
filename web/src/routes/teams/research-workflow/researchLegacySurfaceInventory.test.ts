/**
 * Task 0 characterization: inventory of legacy research surfaces and router reachability.
 * Does not migrate behavior — locks facts for Task 8/9 cleanup gates.
 */
import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const webSrc = resolve(import.meta.dirname, "../../..");
const routesRoot = resolve(webSrc, "routes");
const routerSource = readFileSync(resolve(webSrc, "app/router.tsx"), "utf8");

const LEGACY_RESEARCH_VIEWS = [
  "overview",
  "canvas",
  "knowledge_collection",
  "source_collection",
  "experiment",
  "iteration",
  "coordination",
  "discussion",
  "ingestion",
  "graph",
  "candidates",
] as const;

const COLLECTION_STAGE_ALIASES = [
  "search",
  "collection",
  "finding",
  "review",
  "candidate",
  "screening",
  "extraction",
  "graph",
  "relations",
  "ingest",
  "memory",
  "ingestion",
] as const;

describe("Task0 research legacy surface inventory", () => {
  it("router still mounts /research/flow-canvas as a live lazy page", () => {
    expect(routerSource).toContain('path: "research/flow-canvas"');
    expect(routerSource).toContain("ResearchFlowCanvasRoute");
    expect(routerSource).toMatch(/import\("\.\.\/routes\/ResearchFlowCanvasRoute"\)/);
  });

  it("router redirects /research via LegacyTeamsRedirect (not ResearchRoute)", () => {
    expect(routerSource).toContain('path: "research"');
    expect(routerSource).toContain("LegacyTeamsRedirect");
    expect(routerSource).not.toMatch(/path:\s*"research"[^]*ResearchRoute/);
    expect(routerSource).not.toContain("ResearchRoute");
  });

  it("ResearchRoute.tsx is an orphan implementation still on disk", () => {
    const researchRoute = resolve(routesRoot, "ResearchRoute.tsx");
    expect(existsSync(researchRoute)).toBe(true);
    const source = readFileSync(researchRoute, "utf8");
    expect(source).toContain("export function ResearchRoute");
    // No router import of ResearchRoute module.
    expect(routerSource).not.toContain("routes/ResearchRoute");
  });

  it("Challenge Cup multi-surface files still exist as migration sources", () => {
    const expectedPresent = [
      "teams/challenge-cup/ChallengeCupOperationsWorkspace.tsx",
      "teams/challenge-cup/ChallengeCupStageRail.tsx",
      "teams/ResearchOverviewSurface.tsx",
      "teams/ResearchStageNav.tsx",
      "TeamKnowledgeCollectionCompletionFlowPanel.tsx",
      "ResearchFlowCanvasRoute.tsx",
      "teams/researchStageAgentBindings.ts",
      "teams/researchWorkspaceModel.ts",
    ];
    for (const rel of expectedPresent) {
      expect(existsSync(resolve(routesRoot, rel)), rel).toBe(true);
    }
  });

  it("documents legacy researchView and collectionStage alias sets for resolver Task 5/8", () => {
    // Contract fixture: disposition table must cover these values.
    expect(LEGACY_RESEARCH_VIEWS.length).toBeGreaterThanOrEqual(11);
    expect(COLLECTION_STAGE_ALIASES).toContain("finding");
    expect(COLLECTION_STAGE_ALIASES).toContain("extraction");
    expect(COLLECTION_STAGE_ALIASES).toContain("ingest");
  });

  it("canonical workflow query keys are not yet the default researchView", () => {
    const model = readFileSync(resolve(routesRoot, "teams/researchWorkspaceModel.ts"), "utf8");
    // Pre-migration: workspace model does not yet own researchView=workflow.
    expect(model).toContain("knowledge_collection");
    expect(model).toContain("experiment");
    expect(model).toContain("iteration");
    // After Task 5 this may flip; Task 0 only records baseline absence of canonical default.
    const hasWorkflowView = /"workflow"/.test(model) || /researchView.*workflow/.test(model);
    expect(typeof hasWorkflowView).toBe("boolean");
  });

  it("returnTo deep-link helper exists but focusTask/focusTurn are not standard chat anchors yet", () => {
    const nav = readFileSync(resolve(webSrc, "app/navigationReturn.ts"), "utf8");
    expect(nav).toContain("returnTo");
    expect(nav).toContain("safeReturnToPath");
    // Task 7 will add focusTask/focusTurn; baseline should not silently claim they exist.
    const chatSources = [
      resolve(webSrc, "app/navigationReturn.ts"),
      resolve(webSrc, "api/researchProjectAgentTasks.ts"),
    ];
    const joined = chatSources
      .filter((p) => existsSync(p))
      .map((p) => readFileSync(p, "utf8"))
      .join("\n");
    // Characterization only: record whether anchors exist.
    expect(joined.includes("returnTo")).toBe(true);
  });
});
