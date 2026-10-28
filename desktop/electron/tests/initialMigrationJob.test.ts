import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { listInitialMigrationJobs, runInitialMigrationJob, verifyInitialMigrationResult } from "../src/assistant/initialMigrationJob.js";
import type { PreHostSourceLease } from "../src/assistant/projectRegistryConnection.js";
import type { WorkbenchJobNative } from "../src/process/workbenchJob.js";

describe("initial migration owned job", () => {
  it("terminates the captured job on exit but retains the permit until its output drains", async () => {
    const root = mkdtempSync(join(tmpdir(), "initial-cancel-")), project = join(root, "project"), profile = join(root, "profile");
    mkdirSync(project); mkdirSync(profile);
    let active = true, drained = false, permitHeld = false, closed = false;
    const abort = new AbortController();
    let granted!: () => void;
    const permitGranted = new Promise<void>(resolve => { granted = resolve; });
    const lease: PreHostSourceLease = { revision: 1, signal: new AbortController().signal, check: () => undefined,
      registration: { baseProjectId: "project", registrationUuid: "uuid", integrationRoot: project, root: project, active: true },
      commit: async work => { permitHeld = true; try { return await work(); } finally { permitHeld = false; } } };
    const operationId = "initial-" + "e".repeat(40);
    const captured = {};
    const terminate = vi.fn((job: object) => {
      expect(job).toBe(captured);
      if (terminate.mock.calls.length === 1) return false;
      active = false;
      return true;
    });
    const native: WorkbenchJobNative = {
      spawn: input => {
        void (async () => {
          const response = await fetch(`${input.env.VIBELUTION_INITIAL_MIGRATION_URL}/permit`, { method: "POST",
            headers: { Authorization: `Bearer ${input.env.VIBELUTION_INITIAL_MIGRATION_TOKEN}` }, body: "{}" });
          expect(response.status).toBe(200); granted();
        })();
        return { pid: 123, job: captured };
      },
      activeCount: () => active ? 1 : 0, exitCode: () => active ? null : 1,
      drainStatus: () => ({ complete: drained, channels: ["stdout", "stderr"].map(stream => ({
        stream: stream as "stdout" | "stderr", complete: drained, errorCode: 0, droppedBytes: 0, rotations: 0 })) }),
      terminate, close: () => { closed = true; },
    };
    try {
      const running = runInitialMigrationJob({ lease, binding: { registeredProjectId: "project:uuid", sourceConfig: join(root, "source.toml"),
        targetProfile: profile, targetConfig: join(profile, "config.toml"), operationId }, sourceRoot: root,
        pythonPath: join(root, "pythonw.exe"), pythonArguments: [], runtimeRoot: join(root, "runtime"), env: {}, native, signal: abort.signal });
      await permitGranted;
      abort.abort();
      await vi.waitFor(() => expect(terminate).toHaveBeenCalled(), { timeout: 2500 });
      expect(permitHeld).toBe(true);
      expect(closed).toBe(false);
      expect(active).toBe(true);
      await vi.waitFor(() => expect(terminate).toHaveBeenCalledTimes(2), { timeout: 2500 });
      expect(permitHeld).toBe(true);
      expect(closed).toBe(false);
      drained = true;
      expect((await running).state).toBe("unknown");
      expect(permitHeld).toBe(false);
      expect(closed).toBe(true);
    } finally { rmSync(root, { recursive: true, force: true }); }
  });
  it("records success only after original business receipt verification", async () => {
    const root = mkdtempSync(join(tmpdir(), "initial-verify-")), operationId = "initial-" + "c".repeat(40);
    try {
      const native: WorkbenchJobNative = {
        spawn: input => { writeFileSync(input.stdoutPath, JSON.stringify({ schemaVersion: 1, operationId, state: "confirmed_completed", readyForCutover: false })); return { pid: 1, job: {} }; },
        activeCount: () => 0, exitCode: () => 0, terminate: () => true, close: () => undefined,
        drainStatus: () => ({ complete: true, channels: ["stdout", "stderr"].map(stream => ({ stream: stream as "stdout" | "stderr", complete: true, errorCode: 0, droppedBytes: 0, rotations: 0 })) }),
      };
      const input = { sourceRoot: root, pythonPath: join(root, "pythonw.exe"), pythonArguments: [], runtimeRoot: join(root, "runtime"), targetProfile: join(root, "profile"), env: {}, native };
      expect(await verifyInitialMigrationResult(input, operationId, "completed")).toBe(true);
      expect(await verifyInitialMigrationResult(input, operationId, "partial")).toBe(false);
    } finally { rmSync(root, { recursive: true, force: true }); }
  });
  it("verifies partial only with its explicit flag and a matching partial receipt", async () => {
    const root = mkdtempSync(join(tmpdir(), "initial-verify-partial-")), operationId = "initial-" + "f".repeat(40);
    let receipt = "confirmed_partial";
    let args: string[] = [];
    try {
      const native: WorkbenchJobNative = {
        spawn: input => { args = input.arguments; writeFileSync(input.stdoutPath, JSON.stringify({ schemaVersion: 1, operationId,
          state: receipt, readyForCutover: false })); return { pid: 1, job: {} }; },
        activeCount: () => 0, exitCode: () => 0, terminate: () => true, close: () => undefined,
        drainStatus: () => ({ complete: true, channels: ["stdout", "stderr"].map(stream => ({ stream: stream as "stdout" | "stderr", complete: true, errorCode: 0, droppedBytes: 0, rotations: 0 })) }),
      };
      const input = { sourceRoot: root, pythonPath: join(root, "pythonw.exe"), pythonArguments: [], runtimeRoot: join(root, "runtime"),
        targetProfile: join(root, "profile"), env: {}, native };
      expect(await verifyInitialMigrationResult(input, operationId, "partial")).toBe(true);
      expect(args).toContain("--allow-partial");
      expect(await verifyInitialMigrationResult(input, operationId, "completed")).toBe(false);
      expect(args).not.toContain("--allow-partial");
      receipt = "confirmed_completed";
      expect(await verifyInitialMigrationResult(input, operationId, "partial")).toBe(false);
    } finally { rmSync(root, { recursive: true, force: true }); }
  });
  it("reads only closed original intent identities and states", async () => {
    const root = mkdtempSync(join(tmpdir(), "initial-list-"));
    try {
      const row = { operationId: "initial-" + "b".repeat(40), registeredProjectId: "project:uuid", category: "personal", registryDigest: "d".repeat(64), state: "claimed_unknown" };
      const native: WorkbenchJobNative = {
        spawn: input => { writeFileSync(input.stdoutPath, JSON.stringify({ schemaVersion: 1, intents: [row] })); return { pid: 1, job: {} }; },
        activeCount: () => 0, exitCode: () => 0, terminate: () => true, close: () => undefined,
        drainStatus: () => ({ complete: true, channels: ["stdout", "stderr"].map(stream => ({ stream: stream as "stdout" | "stderr", complete: true, errorCode: 0, droppedBytes: 0, rotations: 0 })) }),
      };
      const result = await listInitialMigrationJobs({ sourceRoot: root, pythonPath: join(root, "pythonw.exe"), pythonArguments: [],
        runtimeRoot: join(root, "runtime"), targetProfile: join(root, "profile"), env: {}, native });
      expect(result).toEqual([row]);
    } finally { rmSync(root, { recursive: true, force: true }); }
  });
  it("keeps its permit until the exact job and both output channels drain", async () => {
    const root = mkdtempSync(join(tmpdir(), "initial-job-")), project = join(root, "project"), profile = join(root, "profile");
    mkdirSync(project); mkdirSync(profile);
    let active = true, closed = false, permitHeld = false;
    const lease: PreHostSourceLease = { revision: 1, signal: new AbortController().signal, check: () => undefined,
      registration: { baseProjectId: "project", registrationUuid: "uuid", integrationRoot: project, root: project, active: true },
      commit: async work => { permitHeld = true; try { return await work(); } finally { permitHeld = false; } } };
    const operationId = "initial-" + "a".repeat(40);
    const native: WorkbenchJobNative = {
      spawn: input => {
        expect(input.env.OPENAI_API_KEY).toBeUndefined();
        expect(input.env.VIBELUTION_PROJECTS_HOME).toBe(join(root, "projects"));
        void (async () => {
          const url = input.env.VIBELUTION_INITIAL_MIGRATION_URL!;
          const headers = { Authorization: `Bearer ${input.env.VIBELUTION_INITIAL_MIGRATION_TOKEN}` };
          const permit = await fetch(`${url}/permit`, { method: "POST", headers, body: "{}" });
          expect(permit.status).toBe(200);
          expect(permitHeld).toBe(true);
          writeFileSync(input.stdoutPath, JSON.stringify({ schemaVersion: 1, operationId, state: "completed", readyForCutover: false }));
          writeFileSync(input.stderrPath, "");
          active = false;
        })();
        return { pid: 123, job: {} };
      },
      activeCount: () => active ? 1 : 0,
      exitCode: () => active ? null : 0,
      drainStatus: () => ({ complete: !active, channels: ["stdout", "stderr"].map(stream => ({ stream: stream as "stdout" | "stderr", complete: !active, errorCode: 0, droppedBytes: 0, rotations: 0 })) }),
      terminate: vi.fn(() => true), close: () => { closed = true; },
    };
    try {
      const result = await runInitialMigrationJob({ lease, binding: { registeredProjectId: "project:uuid", sourceConfig: join(root, "source.toml"),
        targetProfile: profile, targetConfig: join(profile, "config.toml"), operationId }, sourceRoot: root,
        pythonPath: join(root, "pythonw.exe"), pythonArguments: [], runtimeRoot: join(root, "runtime"),
        env: { OPENAI_API_KEY: "synthetic-secret", VIBELUTION_PROJECTS_HOME: join(root, "projects") }, native });
      expect(result.state).toBe("completed");
      expect(closed).toBe(true);
      expect(permitHeld).toBe(false);
    } finally { rmSync(root, { recursive: true, force: true }); }
  });
});
