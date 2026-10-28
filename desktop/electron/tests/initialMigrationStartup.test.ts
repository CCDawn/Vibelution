import { mkdtempSync, mkdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { recoverInitialMigrations } from "../src/assistant/initialMigrationStartup.js";
import { listInitialMigrationJobs, runInitialMigrationJob } from "../src/assistant/initialMigrationJob.js";
import type { AssistantProjectRegistryConnection } from "../src/assistant/projectRegistryConnection.js";
import type { InitialMigrationResults } from "../src/assistant/initialMigrationResults.js";

vi.mock("../src/assistant/initialMigrationJob.js", () => ({ listInitialMigrationJobs: vi.fn(), runInitialMigrationJob: vi.fn() }));
afterEach(() => vi.clearAllMocks());

describe("initial migration startup", () => {
  it("does not claim an orphaned refresh is an empty migration history", async () => {
    const root = mkdtempSync(join(tmpdir(), "initial-startup-orphan-"));
    const profile = join(root, "profile"); mkdirSync(join(profile, "initial_migration_intent_refreshes"), { recursive: true });
    try {
      await expect(recoverInitialMigrations({ registry: {} as AssistantProjectRegistryConnection,
        results: {} as InitialMigrationResults, targetProfile: profile, sourceConfig: join(root, "source.toml"),
        targetConfig: async () => join(profile, "config.toml"), sourceRoot: root, pythonPath: join(root, "pythonw.exe"),
        verifyResult: async () => true, pythonArguments: [], runtimeRoot: join(root, "runtime"), env: {} }))
        .rejects.toThrow("INITIAL_MIGRATION_INTENTS_UNAVAILABLE");
      expect(listInitialMigrationJobs).not.toHaveBeenCalled();
    } finally { rmSync(root, { recursive: true, force: true }); }
  });
  it("verifies a drained partial result and never promotes an unknown result", async () => {
    const root = mkdtempSync(join(tmpdir(), "initial-startup-partial-"));
    const profile = join(root, "profile"); mkdirSync(join(profile, "initial_migration_intents"), { recursive: true });
    const first = "initial-" + "a".repeat(40), second = "initial-" + "b".repeat(40);
    vi.mocked(listInitialMigrationJobs).mockResolvedValue([first, second].map(operationId => ({
      operationId, registeredProjectId: "project:one", category: "personal" as const,
      registryDigest: "c".repeat(64), state: "dispatchable" as const,
    })));
    vi.mocked(runInitialMigrationJob).mockResolvedValueOnce({ schemaVersion: 1, operationId: first, state: "partial", readyForCutover: false })
      .mockResolvedValueOnce({ schemaVersion: 1, operationId: second, state: "unknown", readyForCutover: false });
    const verifyResult = vi.fn(async () => true), record = vi.fn(async () => undefined);
    const registry = { withPreHostSource: vi.fn(async (_id, callback) => await callback({})) } as unknown as AssistantProjectRegistryConnection;
    const results = { get: vi.fn(async () => null), record } as unknown as InitialMigrationResults;
    try {
      const output = await recoverInitialMigrations({ registry, results, targetProfile: profile, sourceConfig: join(root, "source.toml"),
        targetConfig: async () => join(profile, "config.toml"), sourceRoot: root, pythonPath: join(root, "pythonw.exe"),
        verifyResult, pythonArguments: [], runtimeRoot: join(root, "runtime"), env: {} });
      expect(output).toEqual([{ operationId: first, state: "partial" }, { operationId: second, state: "unknown" }]);
      expect(verifyResult).toHaveBeenCalledExactlyOnceWith(first, "partial");
      expect(record).toHaveBeenCalledExactlyOnceWith(first, "partial");
    } finally { rmSync(root, { recursive: true, force: true }); }
  });
  it("treats a damaged result as unknown without replaying it or blocking other jobs", async () => {
    const root = mkdtempSync(join(tmpdir(), "initial-startup-damaged-"));
    const profile = join(root, "profile"); mkdirSync(join(profile, "initial_migration_intents"), { recursive: true });
    const first = "initial-" + "a".repeat(40), second = "initial-" + "b".repeat(40);
    vi.mocked(listInitialMigrationJobs).mockResolvedValue([first, second].map(operationId => ({
      operationId, registeredProjectId: "project:one", category: "personal" as const,
      registryDigest: "c".repeat(64), state: "dispatchable" as const,
    })));
    vi.mocked(runInitialMigrationJob).mockResolvedValue({ schemaVersion: 1, operationId: second, state: "completed", readyForCutover: false });
    const registry = { withPreHostSource: vi.fn(async (_id, callback) => await callback({})) } as unknown as AssistantProjectRegistryConnection;
    const results = { get: vi.fn(async (id: string) => { if (id === first) throw new Error("damaged"); return null; }),
      record: vi.fn(async () => undefined) } as unknown as InitialMigrationResults;
    try {
      const output = await recoverInitialMigrations({ registry, results, targetProfile: profile, sourceConfig: join(root, "source.toml"),
        targetConfig: async () => join(profile, "config.toml"), sourceRoot: root, pythonPath: join(root, "pythonw.exe"),
        verifyResult: async () => true, pythonArguments: [], runtimeRoot: join(root, "runtime"), env: {} });
      expect(output).toEqual([{ operationId: first, state: "unknown" }, { operationId: second, state: "completed" }]);
      expect(runInitialMigrationJob).toHaveBeenCalledTimes(1);
      expect(vi.mocked(runInitialMigrationJob).mock.calls[0][0].binding.operationId).toBe(second);
      expect(vi.mocked(registry.withPreHostSource).mock.calls[0][2]).toMatchObject({ operationId: second, receiptConfirmed: expect.any(Function) });
    } finally { rmSync(root, { recursive: true, force: true }); }
  });
  it("does not replay a claimed attempt and records only a drained confirmed result", async () => {
    const root = mkdtempSync(join(tmpdir(), "initial-startup-"));
    const profile = join(root, "profile"); mkdirSync(join(profile, "initial_migration_intents"), { recursive: true });
    const first = "initial-" + "a".repeat(40), second = "initial-" + "b".repeat(40);
    vi.mocked(listInitialMigrationJobs).mockResolvedValue([
      { operationId: first, registeredProjectId: "project:one", category: "personal", registryDigest: "c".repeat(64), state: "claimed_unknown" },
      { operationId: second, registeredProjectId: "project:two", category: "knowledge", registryDigest: "d".repeat(64), state: "dispatchable" },
    ]);
    vi.mocked(runInitialMigrationJob).mockResolvedValue({ schemaVersion: 1, operationId: second, state: "completed", readyForCutover: false });
    const record = vi.fn(async () => undefined);
    const registry = { withPreHostSource: vi.fn(async (_id, callback) => await callback({})) } as unknown as AssistantProjectRegistryConnection;
    const results = { get: vi.fn(async () => null), record } as unknown as InitialMigrationResults;
    try {
      const output = await recoverInitialMigrations({ registry, results, targetProfile: profile, sourceConfig: join(root, "source.toml"),
        targetConfig: async () => join(profile, "config.toml"), sourceRoot: root, pythonPath: join(root, "pythonw.exe"),
        verifyResult: async () => true, pythonArguments: [], runtimeRoot: join(root, "runtime"), env: {} });
      expect(output).toEqual([{ operationId: first, state: "unknown" }, { operationId: second, state: "completed" }]);
      expect(runInitialMigrationJob).toHaveBeenCalledTimes(1);
      expect(record).toHaveBeenCalledWith(second, "completed");
      record.mockClear();
      const unverified = await recoverInitialMigrations({ registry, results, targetProfile: profile, sourceConfig: join(root, "source.toml"),
        targetConfig: async () => join(profile, "config.toml"), sourceRoot: root, pythonPath: join(root, "pythonw.exe"),
        verifyResult: async () => false, pythonArguments: [], runtimeRoot: join(root, "runtime"), env: {} });
      expect(unverified[1]).toEqual({ operationId: second, state: "unknown" });
      expect(record).not.toHaveBeenCalled();
    } finally { rmSync(root, { recursive: true, force: true }); }
  });
});
