import { describe, expect, it } from "vitest";

import routeSource from "../MemoryRoute.tsx?raw";
import queriesSource from "./useMemoryWorkbenchQueries.ts?raw";

const coreOwners = [
  "overviewQuery",
  "projectMemoryUpdatesQuery",
  "memoryUsageContractQuery",
  "agentsQuery",
  "agentMemoryInventoryQuery",
  "agentMemoryDetailQuery",
  "knowledgeDashboardSnapshotQuery",
  "memoryKnowledgeGraphQuery",
  "memoryKnowledgeGraphNodeDetailQuery",
  "githubProjectLibraryQuery",
] as const;

const knowledgeOwners = [
  "knowledgeItemsQuery",
  "knowledgeSearchQuery",
  "knowledgeRagHealthQuery",
  "knowledgeRagRetrieveQuery",
  "ratingSuggestionsQuery",
  "permissionAuditQuery",
  "governanceTasksQuery",
  "ingestionAdaptersQuery",
  "knowledgeTraceQuery",
  "sourceInboxQuery",
  "centralSourcesQuery",
] as const;

describe("memory workbench queries contract", () => {
  it("owns MemoryRoute read queries across core + knowledge hooks", () => {
    expect(queriesSource.match(/\buseQuery\(/g) ?? []).toHaveLength(coreOwners.length + knowledgeOwners.length);
    [...coreOwners, ...knowledgeOwners].forEach((owner) => {
      expect(queriesSource).toContain(`const ${owner} = useQuery({`);
    });
    expect(queriesSource).toContain("export function useMemoryCoreQueries");
    expect(queriesSource).toContain("export function useMemoryKnowledgeQueries");
  });

  it("is wired from MemoryRoute without inline useQuery owners", () => {
    expect(routeSource).toContain("useMemoryCoreQueries({");
    expect(routeSource).toContain("useMemoryKnowledgeQueries({");
    [...coreOwners, ...knowledgeOwners].forEach((owner) => {
      expect(routeSource).not.toContain(`const ${owner} = useQuery({`);
      expect(routeSource).toContain(owner);
    });
    // Item detail stays route-local: depends on selected pair + contentDeferred after list derivation.
    expect(routeSource).toContain("const activeItemDetailQuery = useQuery({");
  });

  it("gates the overview poll by view and keeps content variants in the query key", () => {
    // Ops views (manage-family) and library render sections content; knowledge,
    // graph, personal/agents and team views must not pull full-content payloads.
    expect(queriesSource).toContain(
      "const overviewNeedsContent = isManageMemoryView(forcedView) || isLibraryMemoryView(forcedView)",
    );
    expect(queriesSource).toContain("queryKey: queryKeys.memoryOverview(overviewNeedsContent)");
    expect(queriesSource).toContain("fetchMemoryOverview<MemoryOverview>({ includeContent: overviewNeedsContent, signal })");
    expect(queriesSource).toContain("enabled: overviewNeedsContent");
  });

  it("loads private content only for the resolved Agent selection", () => {
    expect(queriesSource).toContain(
      "resolveDefaultAgentMemoryId(agentMemoryInventoryAgents, requestedKnowledgeActorAgentId)",
    );

    const detailQuery = extractQueryBlock("agentMemoryDetailQuery");
    expect(detailQuery).toContain("queryKey: queryKeys.memoryAgentDetail(selectedAgentMemoryAgentId, selectedAgentMemoryRevision)");
    expect(detailQuery).toContain("fetchMemoryAgentDetail<AgentMemoryInventoryPayload>(selectedAgentMemoryAgentId");
    expect(detailQuery).toContain("includeContent: true");
    expect(detailQuery).toContain("enabled: isPersonalMemoryView(forcedView) && Boolean(selectedAgentMemoryAgentId)");
  });

  it("requests formal knowledge and private metadata with actor-scoped graph and detail caches", () => {
    expect(queriesSource).toContain('const MEMORY_GRAPH_INCLUDE = "knowledge,privateMemory,officialResearchGraph"');
    const graph = extractQueryBlock("memoryKnowledgeGraphQuery");
    expect(graph).toContain("queryKeys.memoryKnowledgeGraph(fallbackKnowledgeActorAgentId, MEMORY_GRAPH_INCLUDE, requestedTeamId)");
    expect(graph).toContain("include: MEMORY_GRAPH_INCLUDE");
    expect(graph).toContain("teamId: requestedTeamId || undefined");
    const detail = extractQueryBlock("memoryKnowledgeGraphNodeDetailQuery");
    expect(detail).toContain("queryKeys.memoryKnowledgeGraphNodeDetail(selectedGraphNodeId, fallbackKnowledgeActorAgentId)");
    expect(routeSource).toContain('if (forcedView === "graph") return;');
    expect(routeSource).toContain("graphActorAgentId={fallbackKnowledgeActorAgentId}");
    expect(routeSource).toContain("graphTeamId={requestedTeamId}");
  });

  it("keeps polled queries cache-first with staleTime >= refetchInterval", () => {
    // Remounts inside one poll cycle must render from cache (no blocking reload)
    // while the interval keeps refreshing in place.
    const polledStaleTimeFloorMs: ReadonlyArray<readonly [string, number]> = [
      ["overviewQuery", 30_000],
      ["projectMemoryUpdatesQuery", 45_000],
      ["memoryUsageContractQuery", 60_000],
      ["agentsQuery", 60_000],
      ["agentMemoryInventoryQuery", 45_000],
      ["knowledgeDashboardSnapshotQuery", 45_000],
      ["memoryKnowledgeGraphQuery", 60_000],
      ["githubProjectLibraryQuery", 60_000],
      ["knowledgeItemsQuery", 45_000],
      ["knowledgeRagHealthQuery", 60_000],
      ["ratingSuggestionsQuery", 45_000],
      ["permissionAuditQuery", 60_000],
      ["governanceTasksQuery", 45_000],
      ["sourceInboxQuery", 45_000],
      ["centralSourcesQuery", 60_000],
    ];
    polledStaleTimeFloorMs.forEach(([owner, floorMs]) => {
      const block = extractQueryBlock(owner);
      const staleTime = readOptionMs(block, "staleTime");
      expect(staleTime, `${owner} staleTime`).not.toBeNull();
      expect(staleTime ?? 0).toBeGreaterThanOrEqual(floorMs);
    });
    // Non-polled detail reads still get a short stale window so a quick
    // remount does not immediately refetch.
    ["agentMemoryDetailQuery", "memoryKnowledgeGraphNodeDetailQuery"].forEach((owner) => {
      const staleTime = readOptionMs(extractQueryBlock(owner), "staleTime");
      expect(staleTime, `${owner} staleTime`).not.toBeNull();
      expect(staleTime ?? 0).toBeGreaterThanOrEqual(60_000);
    });
  });

  it("extends gcTime for heavy payload queries beyond the 5min default", () => {
    const heavyGcTimeFloorMs: ReadonlyArray<readonly [string, number]> = [
      ["overviewQuery", 600_000],
      ["agentMemoryDetailQuery", 900_000],
      ["knowledgeDashboardSnapshotQuery", 600_000],
    ];
    heavyGcTimeFloorMs.forEach(([owner, floorMs]) => {
      const gcTime = readOptionMs(extractQueryBlock(owner), "gcTime");
      expect(gcTime, `${owner} gcTime`).not.toBeNull();
      expect(gcTime ?? 0).toBeGreaterThanOrEqual(floorMs);
      expect(gcTime ?? 0).toBeGreaterThanOrEqual(600_000);
    });
  });
});

function extractQueryBlock(owner: string): string {
  const pattern = new RegExp(`const ${owner} = useQuery\\(\\{[\\s\\S]*?\\n  \\}\\);`);
  const match = queriesSource.match(pattern);
  expect(match, `query block for ${owner}`).not.toBeNull();
  return match?.[0] ?? "";
}

function readOptionMs(block: string, option: "staleTime" | "gcTime"): number | null {
  const match = block.match(new RegExp(`\\b${option}: (\\d+(?:_\\d+)*)`));
  return match ? Number(match[1].replace(/_/g, "")) : null;
}
