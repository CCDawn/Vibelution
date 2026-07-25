/**
 * Wave 6B domain workbench composition — Agents / Teams / Memory.
 *
 * Domain shells keep custom multi-pane layouts (not forced onto VListDetailPage).
 * Composition means:
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
