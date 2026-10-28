import { lstatSync } from "node:fs";
import { isAbsolute, join } from "node:path";
import type { WorkbenchJobNative } from "../process/workbenchJob.js";
import { listInitialMigrationJobs, runInitialMigrationJob } from "./initialMigrationJob.js";
import type { InitialMigrationResults } from "./initialMigrationResults.js";
import type { AssistantProjectRegistryConnection } from "./projectRegistryConnection.js";

export type InitialMigrationStartupResult = { operationId: string; state: "completed" | "partial" | "unknown" };

/**
 * Main-only cold-start recovery, before the resident host owns the profile.
 * A missing or invalid prerequisite leaves the original intent unexecuted;
 * a claimed or uncertain attempt is never submitted again.
 */
export async function recoverInitialMigrations(input: {
  registry: AssistantProjectRegistryConnection; results: InitialMigrationResults;
  targetProfile: string; sourceConfig: string; targetConfig: (operationId: string, registryDigest: string) => Promise<string>;
  verifyResult: (operationId: string, state: "completed" | "partial") => Promise<boolean>;
  sourceRoot: string; pythonPath: string; pythonArguments: string[]; runtimeRoot: string;
  env: NodeJS.ProcessEnv; native?: WorkbenchJobNative; signal?: AbortSignal;
}): Promise<InitialMigrationStartupResult[]> {
  if (!isAbsolute(input.targetProfile)) throw new Error("INITIAL_MIGRATION_STARTUP_INVALID");
  try {
    const directory = lstatSync(join(input.targetProfile, "initial_migration_intents"));
    if (!directory.isDirectory() || directory.isSymbolicLink()) throw new Error("INITIAL_MIGRATION_INTENTS_UNAVAILABLE");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      // An orphaned refresh is evidence of an interrupted or damaged intent,
      // not evidence that no migration ever existed.
      try { lstatSync(join(input.targetProfile, "initial_migration_intent_refreshes")); }
      catch (refreshError) {
        if ((refreshError as NodeJS.ErrnoException).code === "ENOENT") return [];
      }
    }
    throw new Error("INITIAL_MIGRATION_INTENTS_UNAVAILABLE");
  }
  const jobs = await listInitialMigrationJobs(input);
  const output: InitialMigrationStartupResult[] = [];
  for (const job of jobs) {
    input.signal?.throwIfAborted();
    let previous: "completed" | "partial" | "unknown" | "not_started" | null;
    try { previous = await input.results.get(job.operationId); }
    catch {
      // A damaged receipt is ambiguous and must never cause a replay.
      output.push({ operationId: job.operationId, state: "unknown" });
      continue;
    }
    if (previous || job.state === "claimed_unknown") {
      output.push({ operationId: job.operationId, state: previous === "not_started" ? "unknown" : previous ?? "unknown" });
      continue;
    }
    try {
      if (!isAbsolute(input.sourceConfig)) throw new Error("INITIAL_MIGRATION_SOURCE_UNAVAILABLE");
      if (Object.entries(input.env).some(([key, value]) => /^AGENT_LLM_/i.test(key) && typeof value === "string" && value.trim()))
        throw new Error("INITIAL_MIGRATION_SOURCE_UNAVAILABLE");
      const targetConfig = await input.targetConfig(job.operationId, job.registryDigest);
      const result = await input.registry.withPreHostSource(job.registeredProjectId, async lease => {
        const outcome = await runInitialMigrationJob({ ...input, lease, binding: { registeredProjectId: job.registeredProjectId,
          sourceConfig: input.sourceConfig, targetProfile: input.targetProfile, targetConfig, operationId: job.operationId },
          ...(job.category === "knowledge_sync" || job.category === "knowledge_recovery" ? { registryDigest: job.registryDigest, beforeSpawn: async () => {
            if (!await input.results.begin(job.operationId)) throw new Error("KNOWLEDGE_SYNC_ALREADY_ATTEMPTED");
          }, onNotStarted: async () => { await input.results.recordNotStarted(job.operationId); } } : {}) });
        if ((outcome.state === "completed" || outcome.state === "partial") && await input.verifyResult(job.operationId, outcome.state)) {
          await input.results.record(job.operationId, outcome.state);
          return { ...outcome, state: outcome.state as "completed" | "partial" };
        }
        return { ...outcome, state: "unknown" as const };
      }, { operationId: job.operationId, receiptConfirmed: outcome => outcome.state === "completed" || outcome.state === "partial" });
      output.push({ operationId: job.operationId, state: result.state });
    } catch {
      // The writer may have committed before authority or delivery was lost.
      output.push({ operationId: job.operationId, state: "unknown" });
    }
  }
  return output;
}
