import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { admitLifecycleCommand, resetAdmissionCacheForTests } from "../src/lifecycle/instanceAdmissionStore.js";

afterEach(() => {
  resetAdmissionCacheForTests();
});

describe("instance admission storm", () => {
  it("rejects a 1s burst of 10 restarts after the first 3 and keeps a closed terminal state", async () => {
    const dir = await mkdtemp(join(tmpdir(), "vibe-admission-storm-"));
    const storePath = join(dir, "instance-admission.json");
    const nowMs = 1_787_227_200_000;
    const decisions = [];
    for (let index = 0; index < 10; index += 1) {
      decisions.push(
        await admitLifecycleCommand({
          instanceId: "worktree:task",
          operation: "restart",
          storePath,
          nowMs: nowMs + index * 80
        })
      );
    }
    expect(decisions.filter((item) => item.admitted)).toHaveLength(3);
    expect(decisions.slice(3).every((item) => item.code === "rate_limited" && item.retryAfterMs > 0)).toBe(true);
    expect(decisions[9]?.message).toContain("秒后再试");
  });
});
