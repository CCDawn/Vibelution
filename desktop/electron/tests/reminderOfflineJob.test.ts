import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, expect, it, vi } from "vitest";

const bridge = vi.hoisted(() => ({ environment: {}, wasGranted: () => true, revoke: vi.fn(), closeAfterDrain: vi.fn(async () => {}) }));
vi.mock("../src/assistant/reminderOfflineBridge.js", () => ({ openReminderOfflineBridge: vi.fn(async () => bridge) }));
vi.mock("../src/process/workbenchBackend.js", () => ({ resolveNoConsolePython: (path: string) => path }));
import { runReminderOfflineJob } from "../src/assistant/reminderOfflineJob.js";

const roots: string[] = [];
afterEach(() => { bridge.closeAfterDrain.mockClear(); for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });

it("closes the capability after an exited Job even when its native handle fails to close", async () => {
  const root = mkdtempSync(join(tmpdir(), "reminder-job-close-")); roots.push(root);
  const native = { spawn: () => ({ job: {}, pid: 1 }), activeCount: () => 0, exitCode: () => 0,
    drainStatus: () => ({ complete: true, channels: [] }), close: () => { throw new Error("close failed"); } };
  await expect(runReminderOfflineJob({ sourceRoot: root, pythonPath: join(root, "pythonw.exe"), pythonArguments: [],
    runtimeRoot: root, env: {}, native: native as never, lease: { check: () => {} } as never,
    projectSeal: { drain: async () => {}, signal: new AbortController().signal } as never,
    binding: { registeredProjectId: "project", sourceConfig: root, sourceProjectsHome: root, targetProfile: root,
      targetConfig: join(root, "target.toml"), syncId: "affairs-test", mode: "start", recoveryId: null } })).rejects.toThrow();
  expect(bridge.closeAfterDrain).toHaveBeenCalledOnce();
});

it("does not report success when capability closure fails after drain", async () => {
  const root = mkdtempSync(join(tmpdir(), "reminder-bridge-close-")); roots.push(root);
  const close = vi.fn();
  bridge.closeAfterDrain.mockRejectedValueOnce(new Error("bridge close failed"));
  const native = { spawn: () => ({ job: {}, pid: 1 }), activeCount: () => 0, exitCode: () => 0,
    drainStatus: () => ({ complete: true, channels: [] }), close };
  await expect(runReminderOfflineJob({ sourceRoot: root, pythonPath: join(root, "pythonw.exe"), pythonArguments: [],
    runtimeRoot: root, env: {}, native: native as never, lease: { check: () => {} } as never,
    projectSeal: { drain: async () => {}, signal: new AbortController().signal } as never,
    binding: { registeredProjectId: "project", sourceConfig: root, sourceProjectsHome: root, targetProfile: root,
      targetConfig: join(root, "target.toml"), syncId: "affairs-test", mode: "start", recoveryId: null } })).rejects.toThrow("bridge close failed");
  expect(close).toHaveBeenCalledOnce();
});
