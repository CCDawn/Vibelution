import { describe, expect, it, vi } from "vitest";

import {
  beginFrontendBuild,
  endFrontendBuild,
  frontendBuildInstanceIds,
  frontendBuildMarker,
  peekFrontendBuild,
  resetFrontendBuildStateForTests,
  runWithFrontendBuildGate
} from "../src/lifecycle/frontendBuildState.js";

describe("frontend build state markers", () => {
  it("tracks a building instance between begin and end", () => {
    resetFrontendBuildStateForTests();
    expect(peekFrontendBuild("main")).toBe(false);
    const marker = beginFrontendBuild("main", "start");
    expect(marker.instanceId).toBe("main");
    expect(marker.operation).toBe("start");
    expect(frontendBuildMarker("main")?.startedAt).toBeTruthy();
    expect(peekFrontendBuild("main")).toBe(true);
    expect(frontendBuildInstanceIds()).toEqual(["main"]);
    endFrontendBuild("main");
    expect(peekFrontendBuild("main")).toBe(false);
    expect(frontendBuildInstanceIds()).toEqual([]);
  });

  it("keeps the first marker when begin runs twice for one instance", () => {
    resetFrontendBuildStateForTests();
    const first = beginFrontendBuild("worktree:task", "restart");
    const second = beginFrontendBuild("worktree:task", "restart");
    expect(second).toBe(first);
    endFrontendBuild("worktree:task");
    expect(peekFrontendBuild("worktree:task")).toBe(false);
  });

  it("does not let a blank instance id leak across reset boundaries", () => {
    resetFrontendBuildStateForTests();
    beginFrontendBuild("   ");
    expect(frontendBuildInstanceIds()).toEqual([""]);
    endFrontendBuild("");
    expect(frontendBuildInstanceIds()).toEqual([]);
  });
});

describe("runWithFrontendBuildGate", () => {
  it("publishes building before the awaited work settles and clears it afterwards", async () => {
    resetFrontendBuildStateForTests();
    const events: string[] = [];
    const notify = vi.fn(() => events.push(peekFrontendBuild("main") ? "building" : "settled"));
    const result = await runWithFrontendBuildGate(
      "main",
      { operation: "restart", notify },
      async () => {
        events.push(`inside:${String(peekFrontendBuild("main"))}`);
        return "frontend";
      }
    );
    expect(result).toBe("frontend");
    // The first notification must land before the await resolves, otherwise
    // the renderer never sees the building state during a long build.
    expect(events).toEqual(["building", "inside:true", "settled"]);
    expect(notify).toHaveBeenCalledTimes(2);
    expect(peekFrontendBuild("main")).toBe(false);
  });

  it("clears the building marker when the gated work rejects", async () => {
    resetFrontendBuildStateForTests();
    const notify = vi.fn();
    await expect(
      runWithFrontendBuildGate("worktree:task", { operation: "start", notify }, async () => {
        expect(peekFrontendBuild("worktree:task")).toBe(true);
        throw new Error("frontend build preflight failed");
      })
    ).rejects.toThrow("frontend build preflight failed");
    expect(peekFrontendBuild("worktree:task")).toBe(false);
    expect(notify).toHaveBeenCalledTimes(2);
  });
});
