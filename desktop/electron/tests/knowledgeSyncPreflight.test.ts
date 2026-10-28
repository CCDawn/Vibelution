import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, it } from "vitest";
import { runInitialMigrationJob } from "../src/assistant/initialMigrationJob.js";
import { InitialMigrationResults } from "../src/assistant/initialMigrationResults.js";
import type { PreHostSourceLease } from "../src/assistant/projectRegistryConnection.js";
import type { WorkbenchJobNative } from "../src/process/workbenchJob.js";

it("runs config preflight and acquires the lease before creating the one-shot spawn fence", async () => {
  const root = mkdtempSync(join(tmpdir(), "knowledge-preflight-job-")), profile = join(root, "profile"), project = join(root, "project");
  mkdirSync(profile); mkdirSync(project);
  const events: string[] = [];
  let ready = false;
  const operationId = "ksync-" + "a".repeat(40);
  const lease: PreHostSourceLease = { revision: 1, signal: new AbortController().signal,
    check: () => { events.push("lease"); },
    registration: { baseProjectId: "project", registrationUuid: "uuid", integrationRoot: project, root: project, active: true },
    commit: async work => await work() };
  const native: WorkbenchJobNative = {
    spawn: input => {
      const preflight = input.arguments.includes("--knowledge-preflight");
      events.push(preflight ? "preflight" : "writer");
      if (preflight) expect(input.env.VIBELUTION_INITIAL_MIGRATION_TOKEN).toBeUndefined();
      writeFileSync(input.stdoutPath, JSON.stringify(preflight ? { schemaVersion: 1, state: ready ? "ready" : "unavailable" }
        : { schemaVersion: 1, operationId, state: "unknown", readyForCutover: false }));
      writeFileSync(input.stderrPath, "");
      return { pid: 1, job: {} };
    },
    activeCount: () => 0, exitCode: () => 0, terminate: () => true, close: () => undefined,
    drainStatus: () => ({ complete: true, channels: ["stdout", "stderr"].map(stream => ({ stream: stream as "stdout" | "stderr",
      complete: true, errorCode: 0, droppedBytes: 0, rotations: 0 })) }),
  };
  const input = { lease, binding: { registeredProjectId: "project:uuid", sourceConfig: join(root, "source.toml"),
      targetProfile: profile, targetConfig: join(profile, "config.toml"), operationId }, sourceRoot: root,
    pythonPath: join(root, "pythonw.exe"), pythonArguments: [], runtimeRoot: join(root, "runtime"), env: {}, native,
    registryDigest: "b".repeat(64), beforeSpawn: async () => { events.push("fence"); } };
  try {
    await expect(runInitialMigrationJob(input)).rejects.toThrow("KNOWLEDGE_PREFLIGHT_UNAVAILABLE");
    expect(events).toContain("preflight"); expect(events).not.toContain("fence"); expect(events).not.toContain("writer");
    events.length = 0; ready = true;
    expect((await runInitialMigrationJob(input)).state).toBe("unknown");
    expect(events.indexOf("preflight")).toBeLessThan(events.indexOf("fence"));
    expect(events.indexOf("fence")).toBeLessThan(events.indexOf("writer"));
  } finally { rmSync(root, { recursive: true, force: true }); }
});

it("durably terminates an attempt cancelled while its fence is being persisted, without spawning the writer", async () => {
  const root = mkdtempSync(join(tmpdir(), "knowledge-cancel-before-spawn-")), profile = join(root, "profile"), project = join(root, "project");
  mkdirSync(profile); mkdirSync(project);
  const operationId = "ksync-" + "c".repeat(40), controller = new AbortController();
  const results = new InitialMigrationResults(join(root, "results"));
  const calls: string[] = [];
  const lease: PreHostSourceLease = { revision: 1, signal: new AbortController().signal, check: () => undefined,
    registration: { baseProjectId: "project", registrationUuid: "uuid", integrationRoot: project, root: project, active: true },
    commit: async work => await work() };
  const native: WorkbenchJobNative = {
    spawn: input => {
      const preflight = input.arguments.includes("--knowledge-preflight"); calls.push(preflight ? "preflight" : "writer");
      writeFileSync(input.stdoutPath, JSON.stringify({ schemaVersion: 1, state: "ready" }));
      writeFileSync(input.stderrPath, ""); return { pid: 1, job: {} };
    },
    activeCount: () => 0, exitCode: () => 0, terminate: () => true, close: () => undefined,
    drainStatus: () => ({ complete: true, channels: ["stdout", "stderr"].map(stream => ({ stream: stream as "stdout" | "stderr",
      complete: true, errorCode: 0, droppedBytes: 0, rotations: 0 })) }),
  };
  try {
    await expect(runInitialMigrationJob({ lease, binding: { registeredProjectId: "project:uuid", sourceConfig: join(root, "source.toml"),
      targetProfile: profile, targetConfig: join(profile, "config.toml"), operationId }, sourceRoot: root,
      pythonPath: join(root, "pythonw.exe"), pythonArguments: [], runtimeRoot: join(root, "runtime"), env: {}, native,
      signal: controller.signal, registryDigest: "b".repeat(64), beforeSpawn: async () => {
        const pending = results.begin(operationId);
        controller.abort(); // During the durable reservation's asynchronous handoff.
        if (!await pending) throw new Error("already attempted");
      }, onNotStarted: () => results.recordNotStarted(operationId) })).rejects.toThrow();
    expect(calls).toEqual(["preflight"]);
    expect(await new InitialMigrationResults(join(root, "results")).get(operationId)).toBe("not_started");
    expect(await results.begin(operationId)).toBe(false); // Original ID cannot silently replay.
  } finally { rmSync(root, { recursive: true, force: true }); }
});

it("marks a drained child with no permit as not started, but retains unknown after a permit", async () => {
  const root = mkdtempSync(join(tmpdir(), "knowledge-no-permit-")), profile = join(root, "profile"), project = join(root, "project");
  mkdirSync(profile); mkdirSync(project);
  const results = new InitialMigrationResults(join(root, "results"));
  const lease: PreHostSourceLease = { revision: 1, signal: new AbortController().signal, check: () => undefined,
    registration: { baseProjectId: "project", registrationUuid: "uuid", integrationRoot: project, root: project, active: true },
    commit: async work => await work() };
  async function run(operationId: string, grant: boolean) {
    let active = false;
    const native: WorkbenchJobNative = {
      spawn: input => {
        const preflight = input.arguments.includes("--knowledge-preflight");
        writeFileSync(input.stderrPath, "");
        if (preflight) writeFileSync(input.stdoutPath, JSON.stringify({ schemaVersion: 1, state: "ready" }));
        else {
          writeFileSync(input.stdoutPath, JSON.stringify({ schemaVersion: 1, operationId, state: "unknown", readyForCutover: false }));
          if (grant) {
            active = true;
            void fetch(`${input.env.VIBELUTION_INITIAL_MIGRATION_URL}/permit`, { method: "POST", body: "{}",
              headers: { Authorization: `Bearer ${input.env.VIBELUTION_INITIAL_MIGRATION_TOKEN}` } })
              .then(response => { expect(response.status).toBe(200); active = false; });
          }
        }
        return { pid: 1, job: {} };
      },
      activeCount: () => active ? 1 : 0, exitCode: () => active ? null : 0, terminate: () => true, close: () => undefined,
      drainStatus: () => ({ complete: !active, channels: ["stdout", "stderr"].map(stream => ({ stream: stream as "stdout" | "stderr",
        complete: !active, errorCode: 0, droppedBytes: 0, rotations: 0 })) }),
    };
    return runInitialMigrationJob({ lease, binding: { registeredProjectId: "project:uuid", sourceConfig: join(root, "source.toml"),
      targetProfile: profile, targetConfig: join(profile, "config.toml"), operationId }, sourceRoot: root,
      pythonPath: join(root, "pythonw.exe"), pythonArguments: [], runtimeRoot: join(root, "runtime"), env: {}, native,
      registryDigest: "b".repeat(64), beforeSpawn: async () => { if (!await results.begin(operationId)) throw new Error("already attempted"); },
      onNotStarted: () => results.recordNotStarted(operationId) });
  }
  try {
    const denied = "ksync-" + "d".repeat(40), granted = "ksync-" + "e".repeat(40);
    expect((await run(denied, false)).state).toBe("not_started");
    expect(await results.get(denied)).toBe("not_started");
    expect((await run(granted, true)).state).toBe("unknown");
    expect(await results.get(granted)).toBe("unknown");
  } finally { rmSync(root, { recursive: true, force: true }); }
}, 10000);
