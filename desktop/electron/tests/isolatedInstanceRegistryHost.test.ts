import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { AdmissionDeniedError } from "../src/lifecycle/instanceAdmissionControl.js";
import { admitLifecycleCommand, resetAdmissionCacheForTests } from "../src/lifecycle/instanceAdmissionStore.js";
import {
  claimIsolatedStart,
  collectExtraUsedPorts,
  resolveIsolatedClaimTarget
} from "../src/lifecycle/isolatedInstanceRegistryHost.js";

afterEach(() => {
  resetAdmissionCacheForTests();
});

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

  it("rejects a fourth isolated start inside the burst window", async () => {
    const dir = await mkdtemp(join(tmpdir(), "vibe-isolated-admission-"));
    const admissionStorePath = join(dir, "instance-admission.json");
    const registryPath = join(dir, "instances.json");
    const nowMs = 1_787_227_200_000;
    for (let index = 0; index < 3; index += 1) {
      await admitLifecycleCommand({
        instanceId: "worktree:task",
        operation: "start",
        storePath: admissionStorePath,
        nowMs: nowMs + index
      });
    }
    await expect(
      claimIsolatedStart({
        instanceId: "worktree:task",
        branchInstances: payload,
        commandId: "cmd-4",
        nowMs: nowMs + 10,
        registryPath,
        admissionStorePath
      })
    ).rejects.toBeInstanceOf(AdmissionDeniedError);
  });
});
