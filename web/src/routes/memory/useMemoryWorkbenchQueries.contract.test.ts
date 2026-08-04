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
});
