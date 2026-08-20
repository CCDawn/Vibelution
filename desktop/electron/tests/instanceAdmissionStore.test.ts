import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import {
  admitLifecycleCommand,
  ensureAdmissionLoaded,
  peekAdmissionDecision,
  recordAdmissionOutcome,
  resetAdmissionCacheForTests
} from "../src/lifecycle/instanceAdmissionStore.js";

afterEach(() => {
  resetAdmissionCacheForTests();
});

async function tempStore(): Promise<string> {
  const dir = await mkdtemp(join(tmpdir(), "vibe-admission-"));
  return join(dir, "instance-admission.json");
}

describe("instance admission store", () => {
  it("persists cooldown across a fresh cache load", async () => {
    const storePath = await tempStore();
    const nowMs = 1_787_227_200_000;
    await recordAdmissionOutcome({
      instanceId: "worktree:task",
      outcome: "failure",
      storePath,
      nowMs
    });
    resetAdmissionCacheForTests();
    await ensureAdmissionLoaded(storePath);
    const decision = peekAdmissionDecision("worktree:task", nowMs + 1_000, "start");
    expect(decision.admitted).toBe(false);
    expect(decision.code).toBe("crash_loop_backoff");
    expect(decision.retryAfterMs).toBe(9_000);
    const saved = JSON.parse(await readFile(storePath, "utf8")) as {
      instances: Record<string, { consecutiveFailures: number }>;
    };
    expect(saved.instances["worktree:task"].consecutiveFailures).toBe(1);
  });

  it("does not persist a denied start attempt", async () => {
    const storePath = await tempStore();
    const nowMs = 1_787_227_200_000;
    await admitLifecycleCommand({ instanceId: "main", operation: "start", storePath, nowMs });
    await admitLifecycleCommand({ instanceId: "main", operation: "start", storePath, nowMs: nowMs + 10 });
    await admitLifecycleCommand({ instanceId: "main", operation: "restart", storePath, nowMs: nowMs + 20 });
    const denied = await admitLifecycleCommand({
      instanceId: "main",
      operation: "start",
      storePath,
      nowMs: nowMs + 30
    });
    expect(denied.admitted).toBe(false);
    expect(denied.code).toBe("rate_limited");
    const saved = JSON.parse(await readFile(storePath, "utf8")) as {
      instances: Record<string, { startTimestampsMs: number[] }>;
    };
    expect(saved.instances.main.startTimestampsMs).toHaveLength(3);
  });
});
