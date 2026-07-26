import { describe, expect, it } from "vitest";

import routeSource from "../MemoryRoute.tsx?raw";
import mutationsSource from "./useMemoryItemMutations.ts?raw";

const owners = [
  "memoryMutation",
  "deleteMemoryMutation",
  "restoreMemoryMutation",
  "projectMemoryUpdateResolveMutation",
  "cleanupPreviewMutation",
  "cleanupExecuteMutation",
] as const;

describe("memory item mutations contract", () => {
  it("owns memory item/cleanup write mutations", () => {
    expect(mutationsSource.match(/\buseMutation\(/g) ?? []).toHaveLength(owners.length);
    owners.forEach((owner) => {
      expect(mutationsSource).toContain(`const ${owner} = useMutation({`);
    });
  });

  it("is wired from MemoryRoute without those inline definitions", () => {
    expect(routeSource).toContain("useMemoryItemMutations({");
    owners.forEach((owner) => {
      expect(routeSource).not.toContain(`const ${owner} = useMutation({`);
      expect(routeSource).toContain(owner);
    });
  });

  it("keeps the graph panel off the static Memory shell import", () => {
    expect(routeSource).toContain('import("./MemoryGraphViewPanel")');
    expect(routeSource).not.toMatch(/import \{[^}]*MemoryGraphViewPanel[^}]*\} from "\.\/MemoryGraphViewPanel"/);
  });
});
