import { describe, expect, it } from "vitest";

import {
  collectExtraUsedPorts,
  resolveIsolatedClaimTarget
} from "../src/lifecycle/isolatedInstanceRegistryHost.js";

const payload = {
  items: [
    { id: "main", path: "C:/repo", port: 8000, controlPort: 8765, current: true, alive: true },
    {
      id: "worktree:task",
      path: "C:/wt/task",
      branch: "task",
      port: 8003,
      controlPort: 8768,
      alive: false
    }
  ]
};

describe("isolatedInstanceRegistryHost", () => {
  it("resolves claim targets and skips the selected row when collecting live ports", () => {
    const target = resolveIsolatedClaimTarget(payload, "worktree:task");
    expect(target).toEqual({
      instanceId: "worktree:task",
      projectRoot: "C:/wt/task",
      branch: "task",
      preferredBackend: 8003,
      preferredControl: 8768,
      extraUsed: [8000, 8765],
      alive: false
    });
    expect(collectExtraUsedPorts(payload, "worktree:task")).toEqual([8000, 8765]);
  });

  it("returns null when the instance path is missing", () => {
    expect(resolveIsolatedClaimTarget({ items: [{ id: "worktree:task" }] }, "worktree:task")).toBeNull();
  });
});
