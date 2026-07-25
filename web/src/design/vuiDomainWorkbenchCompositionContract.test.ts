/**
 * Domain workbench composition contracts (Wave 6B + Wave 7A).
 *
 * Domain shells keep custom multi-pane layouts (not forced onto VListDetailPage
 * unless they already use that recipe). Composition means:
 * - domain recipe / domain-recipe markers
 * - region markers for directory-or-canvas / detail-or-inspector rails
 * - shared layoutId registry for permanent width (and height where applicable)
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const routesRoot = resolve(import.meta.dirname, "../routes");

describe("Wave 6B Agents management workbench composition", () => {
  it("marks Agents route + workspace shell recipe and regions", () => {
    const routeSource = readFileSync(resolve(routesRoot, "AgentsRoute.tsx"), "utf8");
    const workspaceSource = readFileSync(resolve(routesRoot, "AgentWorkspaceLayoutPanel.tsx"), "utf8");
    expect(routeSource).toContain('data-vui-recipe="agents-management-workbench"');
    expect(workspaceSource).toContain('data-vui-recipe="agents-workspace-shell"');
    expect(workspaceSource).toContain("WORKBENCH_LAYOUT_IDS.agents");
    expect(workspaceSource).toContain("data-vui-layout-id");
    expect(workspaceSource).toContain('data-vui-region="agents-directory"');
    expect(workspaceSource).toContain('data-vui-region="agents-detail"');
    expect(workspaceSource).toContain('data-vui-region="agents-inspector"');
  });
});

describe("Wave 6B Teams organization workbench composition", () => {
  it("marks Teams dense-ops domain recipe, workspace recipe, and canvas/inspector regions", () => {
    const routeSource = readFileSync(resolve(routesRoot, "TeamsRoute.tsx"), "utf8");
    expect(routeSource).toContain('data-vui-domain-recipe="teams-organization-workbench"');
    expect(routeSource).toContain('data-vui-recipe="teams-organization-workbench"');
    expect(routeSource).toContain("WORKBENCH_LAYOUT_IDS.teams");
    expect(routeSource).toContain("data-vui-layout-id");
    expect(routeSource).toContain('data-vui-region="teams-canvas"');
    expect(routeSource).toContain('data-vui-region="teams-inspector"');
  });
});

describe("Wave 6B Memory knowledge workbench composition", () => {
  it("marks Memory domain recipe on page + resizable workspaces", () => {
    const routeSource = readFileSync(resolve(routesRoot, "MemoryRoute.tsx"), "utf8");
    expect(routeSource).toContain('data-vui-domain-recipe="memory-knowledge-workbench"');
    expect(routeSource).toContain('data-vui-recipe="memory-knowledge-workbench"');
    expect(routeSource).toContain("WORKBENCH_LAYOUT_IDS.memory");
    expect(routeSource).toContain('data-vui-region="memory-sources-workspace"');
    expect(routeSource).toContain('data-vui-region="memory-knowledge-workspace"');
  });

  it("keeps Memory graph on shared height resize for the node list", () => {
    const graphSource = readFileSync(resolve(routesRoot, "MemoryGraphViewPanel.tsx"), "utf8");
    expect(graphSource).toContain("usePersistedPaneHeight");
    expect(graphSource).toContain("PaneHeightResizeHandle");
    expect(graphSource).toContain("WORKBENCH_LAYOUT_IDS.memory");
    expect(graphSource).toContain("graph-node-list");
    expect(graphSource).toContain('data-vui-region="memory-graph-canvas"');
    expect(graphSource).toContain('data-vui-region="memory-graph-node-list"');
  });
});

describe("Wave 7A remaining workbench domain recipes", () => {
  const cases: Array<{ file: string; recipe: string; layoutToken: string }> = [
    { file: "LogsRoute.tsx", recipe: "logs-workbench", layoutToken: "WORKBENCH_LAYOUT_IDS.logs" },
    { file: "GitRoute.tsx", recipe: "git-workbench", layoutToken: "WORKBENCH_LAYOUT_IDS.git" },
    { file: "ToolsRoute.tsx", recipe: "tools-workbench", layoutToken: "WORKBENCH_LAYOUT_IDS.tools" },
    { file: "EvolutionRoute.tsx", recipe: "evolution-workbench", layoutToken: "WORKBENCH_LAYOUT_IDS.evolution" },
    { file: "LauncherRoute.tsx", recipe: "launcher-workbench", layoutToken: "WORKBENCH_LAYOUT_IDS.launcher" },
    { file: "SupervisedReviewRoute.tsx", recipe: "supervised-review-workbench", layoutToken: "WORKBENCH_LAYOUT_IDS.supervisedReview" },
    { file: "SelfEvolutionTrack.tsx", recipe: "evolution-self-workbench", layoutToken: "WORKBENCH_LAYOUT_IDS.evolutionSelf" },
  ];

  it.each(cases)("marks $file with $recipe + registry layout id", ({ file, recipe, layoutToken }) => {
    const source = readFileSync(resolve(routesRoot, file), "utf8");
    expect(source).toContain(`data-vui-recipe="${recipe}"`);
    expect(source).toContain("data-vui-layout-id");
    expect(source).toContain(layoutToken);
  });

  it("marks list-detail pages with domain-recipe overlays", () => {
    const skills = readFileSync(resolve(routesRoot, "SkillsRoute.tsx"), "utf8");
    const kernel = readFileSync(resolve(routesRoot, "KernelTaskCenterRoute.tsx"), "utf8");
    const prompts = readFileSync(resolve(routesRoot, "PromptTemplatesRoute.tsx"), "utf8");
    expect(skills).toContain('data-vui-domain-recipe="skills-workbench"');
    expect(skills).toContain("WORKBENCH_LAYOUT_IDS.skills");
    expect(kernel).toContain('data-vui-domain-recipe="kernel-task-center-workbench"');
    expect(kernel).toContain("WORKBENCH_LAYOUT_IDS.kernelTaskCenter");
    expect(prompts).toContain('data-vui-domain-recipe="prompt-templates-workbench"');
    expect(prompts).toContain("WORKBENCH_LAYOUT_IDS.promptTemplates");
  });
});
