import { mkdtempSync, mkdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, it, vi } from "vitest";
import { InitialMigrationResults } from "../src/assistant/initialMigrationResults.js";
import { recoverInitialMigrations } from "../src/assistant/initialMigrationStartup.js";
import { listInitialMigrationJobs, runInitialMigrationJob } from "../src/assistant/initialMigrationJob.js";
import type { AssistantProjectRegistryConnection } from "../src/assistant/projectRegistryConnection.js";

vi.mock("../src/assistant/initialMigrationJob.js", () => ({ listInitialMigrationJobs: vi.fn(), runInitialMigrationJob: vi.fn() }));

it("durably fences an unknown sync before dispatch and never starts it twice", async () => {
  const root = mkdtempSync(join(tmpdir(), "knowledge-startup-")), profile = join(root, "profile");
  mkdirSync(join(profile, "initial_migration_intents"), { recursive: true });
  const id = "ksync-" + "a".repeat(40);
  vi.mocked(listInitialMigrationJobs).mockResolvedValue([{ operationId: id, registeredProjectId: "project:one",
    category: "knowledge_sync", registryDigest: "b".repeat(64), state: "dispatchable" }]);
  vi.mocked(runInitialMigrationJob).mockImplementation(async input => {
    await input.beforeSpawn?.();
    return { schemaVersion: 1, operationId: id, state: "unknown", readyForCutover: false };
  });
  const registry = { withPreHostSource: vi.fn(async (_id, callback) => await callback({})) } as unknown as AssistantProjectRegistryConnection;
  const results = new InitialMigrationResults(join(root, "results"));
  const options = { registry, results, targetProfile: profile, sourceConfig: join(root, "source.toml"),
    targetConfig: async () => join(profile, "config.toml"), sourceRoot: root, pythonPath: join(root, "pythonw.exe"),
    verifyResult: async () => true, pythonArguments: [], runtimeRoot: join(root, "runtime"), env: {} };
  try {
    expect(await recoverInitialMigrations(options)).toEqual([{ operationId: id, state: "unknown" }]);
    expect(await new InitialMigrationResults(join(root, "results")).get(id)).toBe("unknown");
    expect(await recoverInitialMigrations(options)).toEqual([{ operationId: id, state: "unknown" }]);
    expect(runInitialMigrationJob).toHaveBeenCalledTimes(1);
    await results.record(id, "partial");
    expect(await new InitialMigrationResults(join(root, "results")).get(id)).toBe("partial");
  } finally { rmSync(root, { recursive: true, force: true }); vi.clearAllMocks(); }
});

it("keeps the operation dispatchable when preflight or the project lease rejects it", async () => {
  const root = mkdtempSync(join(tmpdir(), "knowledge-preflight-")), profile = join(root, "profile");
  mkdirSync(join(profile, "initial_migration_intents"), { recursive: true });
  const id = "ksync-" + "c".repeat(40);
  vi.mocked(listInitialMigrationJobs).mockResolvedValue([{ operationId: id, registeredProjectId: "project:one",
    category: "knowledge_sync", registryDigest: "b".repeat(64), state: "dispatchable" }]);
  const results = new InitialMigrationResults(join(root, "results"));
  const registry = { withPreHostSource: vi.fn(async () => { throw new Error("lease unavailable"); }) } as unknown as AssistantProjectRegistryConnection;
  const options = { registry, results, targetProfile: profile, sourceConfig: join(root, "source.toml"),
    targetConfig: async () => join(profile, "config.toml"), sourceRoot: root, pythonPath: join(root, "pythonw.exe"),
    verifyResult: async () => true, pythonArguments: [], runtimeRoot: join(root, "runtime"), env: {} };
  try {
    expect(await recoverInitialMigrations({ ...options, sourceConfig: "relative" })).toEqual([{ operationId: id, state: "unknown" }]);
    expect(await recoverInitialMigrations({ ...options, env: { AGENT_LLM_TOKEN: "fixture" } })).toEqual([{ operationId: id, state: "unknown" }]);
    expect(await recoverInitialMigrations({ ...options, targetConfig: async () => { throw new Error("no config"); } })).toEqual([{ operationId: id, state: "unknown" }]);
    expect(await recoverInitialMigrations(options)).toEqual([{ operationId: id, state: "unknown" }]);
    expect(await results.get(id)).toBeNull();
    expect(runInitialMigrationJob).not.toHaveBeenCalled();
  } finally { rmSync(root, { recursive: true, force: true }); vi.clearAllMocks(); }
});
