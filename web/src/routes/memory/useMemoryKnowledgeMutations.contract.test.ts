import { describe, expect, it } from "vitest";

import routeSource from "../MemoryRoute.tsx?raw";
import mutationsSource from "./useMemoryKnowledgeMutations.ts?raw";

const owners = [
  "proposalMutation",
  "reviewMutation",
  "ratingMutation",
  "ratingSuggestionReviewMutation",
  "ratingSuggestionBulkReviewMutation",
  "sourceInboxCollectMutation",
  "sourceInboxReviewMutation",
  "centralSourceAttachMutation",
] as const;

describe("memory knowledge mutations contract", () => {
  it("owns knowledge write mutations", () => {
    expect(mutationsSource.match(/\buseMutation\(/g) ?? []).toHaveLength(owners.length);
    owners.forEach((owner) => {
      expect(mutationsSource).toContain(`const ${owner} = useMutation({`);
    });
  });

  it("is wired from MemoryRoute without inline knowledge mutation definitions", () => {
    expect(routeSource).toContain("useMemoryKnowledgeMutations({");
    owners.forEach((owner) => {
      expect(routeSource).not.toContain(`const ${owner} = useMutation({`);
      expect(routeSource).toContain(owner);
    });
  });

  it("keeps heavy knowledge panels lazy for non-overview views", () => {
    expect(routeSource).toContain('import("./MemoryKnowledgeReviewPanel")');
    expect(routeSource).toContain('import("./MemoryAgentMemoryPanel")');
    expect(routeSource).toContain('import("./MemoryCleanupPanel")');
    expect(routeSource).not.toMatch(/import \{ MemoryAgentMemoryPanel \} from "\.\/MemoryAgentMemoryPanel"/);
  });
});
