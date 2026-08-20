import { describe, expect, it } from "vitest";

import apiSource from "./memory.ts?raw";
import itemMutationsSource from "../routes/memory/useMemoryItemMutations.ts?raw";
import workbenchQueriesSource from "../routes/memory/useMemoryWorkbenchQueries.ts?raw";
import routeSource from "../routes/MemoryRoute.tsx?raw";

describe("memory catalog API", () => {
  it("owns the memory overview, inventory, graph, item, and cleanup transports", () => {
    expect(apiSource).toContain("export function fetchMemoryOverview");
    expect(apiSource).toContain("export function fetchMemoryUsageContract");
    expect(apiSource).toContain("export function fetchMemoryAgents");
    expect(apiSource).toContain("export function fetchMemoryAgentDetail");
    expect(apiSource).toContain("export function fetchMemoryKnowledgeGraph");
    expect(apiSource).toContain("export function fetchMemoryKnowledgeGraphNodeDetail");
    expect(apiSource).toContain("export function fetchMemoryItemDetail");
    expect(apiSource).toContain("export function createMemoryItem");
    expect(apiSource).toContain("export function updateMemoryItem");
    expect(apiSource).toContain("export function deleteMemoryItem");
    expect(apiSource).toContain("export function restoreMemoryItem");
    expect(apiSource).toContain("export function previewMemoryCleanup");
    expect(apiSource).toContain("export function executeMemoryCleanup");
    expect(apiSource).toContain("/api/memory/overview");
    expect(apiSource).toContain("/api/memory/usage-contract");
    expect(apiSource).toContain("/api/memory/agents");
    expect(apiSource).toContain("/api/memory/agents/${encodeURIComponent(agentId)}");
    expect(apiSource).toContain("/api/memory/knowledge-graph?");
    expect(apiSource).toContain("/api/memory/knowledge-graph/node-detail?");
    expect(apiSource).toContain("/api/memory/items/${encodeURIComponent(sectionId)}/${encodeURIComponent(itemId)}");
    expect(apiSource).toContain('"/api/memory/items"');
    expect(apiSource).toContain('"/api/memory/cleanup/preview"');
    expect(apiSource).toContain('"/api/memory/cleanup/execute"');
    expect(apiSource).toContain("export function fetchGithubProjectLibrary");
    expect(apiSource).toContain("export function cloneGithubProject");
    expect(apiSource).toContain("/api/memory/github-projects");
  });

  it("keeps Memory workbench queries free of memory transport paths", () => {
    expect(workbenchQueriesSource).toContain("fetchMemoryOverview<");
    expect(workbenchQueriesSource).toContain("fetchMemoryUsageContract<");
    expect(workbenchQueriesSource).toContain("fetchMemoryAgents<");
    expect(workbenchQueriesSource).toContain("fetchMemoryAgentDetail<");
    expect(workbenchQueriesSource).toContain("fetchMemoryKnowledgeGraph<");
    expect(workbenchQueriesSource).toContain("fetchMemoryKnowledgeGraphNodeDetail<");
    expect(workbenchQueriesSource).toContain("fetchGithubProjectLibrary<GithubProjectLibraryPayload>({ signal })");
    expect(workbenchQueriesSource).not.toContain("/api/memory/");
  });

  it("keeps item mutations and MemoryRoute free of memory write paths", () => {
    expect(itemMutationsSource).toContain("createMemoryItem<");
    expect(itemMutationsSource).toContain("updateMemoryItem<");
    expect(itemMutationsSource).toContain("deleteMemoryItem<");
    expect(itemMutationsSource).toContain("restoreMemoryItem<");
    expect(itemMutationsSource).toContain("previewMemoryCleanup<");
    expect(itemMutationsSource).toContain("executeMemoryCleanup<");
    expect(itemMutationsSource).not.toContain("/api/memory/");
    expect(routeSource).toContain("fetchMemoryItemDetail<");
    expect(routeSource).toContain("restoreMemoryItem<");
    expect(routeSource).toContain("deleteMemoryItem<");
    expect(routeSource).not.toContain("/api/memory/");
  });
});
