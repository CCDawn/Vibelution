import { mkdirSync, mkdtempSync, readFileSync, statSync } from "node:fs";
import { isAbsolute, join } from "node:path";
import { loadWorkbenchJobNative, type WorkbenchJobDrainStatus, type WorkbenchJobHandle, type WorkbenchJobNative } from "../process/workbenchJob.js";
import { resolveNoConsolePython } from "../process/workbenchBackend.js";
import { openInitialMigrationBridge, type InitialMigrationLaunchBinding } from "./initialMigrationBridge.js";
import type { PreHostSourceLease } from "./projectRegistryConnection.js";

type Result = { schemaVersion: 1; operationId: string; state: "completed" | "partial" | "unknown" | "not_started"; readyForCutover: false };
export type InitialMigrationIntentRef = { operationId: string; registeredProjectId: string;
  category: "personal" | "knowledge" | "knowledge_sync" | "knowledge_recovery"; registryDigest: string; state: "dispatchable" | "claimed_unknown" };
type PythonJobInput = { sourceRoot: string; pythonPath: string; pythonArguments: string[]; runtimeRoot: string;
  env: NodeJS.ProcessEnv; native?: WorkbenchJobNative; signal?: AbortSignal };
const delay = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms));

/** Wait for the captured native Job and both output drains, not just its PID. */
async function runPythonJob(input: PythonJobInput, args: string[], beforeSpawn?: () => Promise<void>,
  cancelledBeforeSpawn?: () => Promise<void>): Promise<{ exit: number | null; value: unknown }> {
  if (![input.sourceRoot, input.pythonPath, input.runtimeRoot].every(path => isAbsolute(path)))
    throw new Error("INITIAL_MIGRATION_JOB_INVALID");
  const native = input.native ?? loadWorkbenchJobNative();
  if (typeof native.exitCode !== "function" || typeof native.drainStatus !== "function")
    throw new Error("INITIAL_MIGRATION_JOB_UNAVAILABLE");
  mkdirSync(input.runtimeRoot, { recursive: true });
  const directory = mkdtempSync(join(input.runtimeRoot, "initial-"));
  const stdout = join(directory, "stdout.log"), stderr = join(directory, "stderr.log");
  const allowed = new Set(["SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "SYSTEMDRIVE", "TEMP", "TMP",
    "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "VIBELUTION_PROJECTS_HOME", "VIBELUTION_CONFIG_HOME", "VIBELUTION_CONFIG_PATH",
    "VIBELUTION_INITIAL_MIGRATION_URL", "VIBELUTION_INITIAL_MIGRATION_TOKEN"]);
  const environment = Object.fromEntries(Object.entries(input.env).filter(([key]) => allowed.has(key.toUpperCase())));
  environment.PYTHONDONTWRITEBYTECODE = "1";
  environment.PYTHONIOENCODING = "utf-8";
  let job: WorkbenchJobHandle | undefined;
  let exit: number | null = null;
  let complete = false;
  let validPid = false;
  let finalDrain: WorkbenchJobDrainStatus | undefined;
  try {
    input.signal?.throwIfAborted();
    const executable = resolveNoConsolePython(input.pythonPath);
    // Persist the one-shot fence only after all main-side preflight and the
    // source lease have succeeded, immediately before the native spawn.
    if (beforeSpawn) await beforeSpawn();
    if (input.signal?.aborted && cancelledBeforeSpawn) await cancelledBeforeSpawn();
    input.signal?.throwIfAborted();
    const spawned = native.spawn({ executable,
      arguments: [...input.pythonArguments, join(input.sourceRoot, "scripts", "assistant_migration_inventory.py"), ...args],
      cwd: input.sourceRoot, env: environment, stdoutPath: stdout, stderrPath: stderr,
      containDescendants: true, maxLogBytes: 64 * 1024 });
    job = spawned.job;
    validPid = Number.isSafeInteger(spawned.pid) && spawned.pid > 0;
    // An inspection failure is not exit evidence. Keep owning the Job and
    // permit, retrying until the original handle confirms complete drain.
    while (!complete) {
      if (input.signal?.aborted) {
        // Terminate only the captured Job. Failure or an incomplete drain is
        // not evidence of retirement; keep its handle and permit and retry.
        try { native.terminate(job); } catch { /* Retry while retaining ownership. */ }
      }
      try {
        const status = native.drainStatus(job);
        exit = native.exitCode(job);
        complete = native.activeCount(job) === 0 && status.complete && exit !== null;
        if (complete) finalDrain = status;
      } catch { /* Preserve ownership until inspection succeeds. */ }
      if (!complete) await delay(1000);
    }
    let result: unknown;
    try {
      if (statSync(stdout).size > 64 * 1024) throw new Error();
      result = JSON.parse(readFileSync(stdout, "utf8"));
    } catch { result = null; }
    if (!input.signal?.aborted && validPid && finalDrain?.channels.length === 2
      && new Set(finalDrain.channels.map(channel => channel.stream)).size === 2
      && finalDrain.channels.every(channel => channel.complete && channel.errorCode === 0
      && channel.droppedBytes === 0 && channel.rotations === 0)) return { exit, value: result };
    return { exit: null, value: null };
  } finally {
    if (job && complete) native.close(job);
  }
}

/** Read published intents before host startup; unavailable is not an empty list. */
export async function listInitialMigrationJobs(input: PythonJobInput & { targetProfile: string }): Promise<InitialMigrationIntentRef[]> {
  if (!isAbsolute(input.targetProfile)) throw new Error("INITIAL_MIGRATION_JOB_INVALID");
  const environment = { ...input.env };
  for (const key of Object.keys(environment)) if (/^VIBELUTION_INITIAL_MIGRATION_(?:URL|TOKEN)$/i.test(key)) delete environment[key];
  const result = await runPythonJob({ ...input, env: environment }, ["--initial-list", "--target-profile", input.targetProfile]);
  if (result.exit !== 0 || !result.value || typeof result.value !== "object" || Array.isArray(result.value)) throw new Error("INITIAL_MIGRATION_INTENTS_UNAVAILABLE");
  const row = result.value as Record<string, unknown>;
  if (Object.keys(row).sort().join(",") !== "intents,schemaVersion" || row.schemaVersion !== 1 || !Array.isArray(row.intents) || row.intents.length > 512)
    throw new Error("INITIAL_MIGRATION_INTENTS_UNAVAILABLE");
  const seen = new Set<string>();
  return row.intents.map(value => {
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("INITIAL_MIGRATION_INTENTS_UNAVAILABLE");
    const item = value as Record<string, unknown>;
    if (Object.keys(item).sort().join(",") !== "category,operationId,registeredProjectId,registryDigest,state"
      || typeof item.operationId !== "string" || !/^(?:initial|ksync|krec)-[a-f0-9]{40}$/.test(item.operationId) || seen.has(item.operationId)
      || typeof item.registeredProjectId !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(item.registeredProjectId)
      || typeof item.registryDigest !== "string" || !/^[a-f0-9]{64}$/.test(item.registryDigest)
      || (item.category !== "personal" && item.category !== "knowledge" && item.category !== "knowledge_sync" && item.category !== "knowledge_recovery")
      || (item.category === "knowledge_sync") !== item.operationId.startsWith("ksync-")
      || (item.category === "knowledge_recovery") !== item.operationId.startsWith("krec-")
      || (item.state !== "dispatchable" && item.state !== "claimed_unknown")) throw new Error("INITIAL_MIGRATION_INTENTS_UNAVAILABLE");
    seen.add(item.operationId);
    return { operationId: item.operationId, registeredProjectId: item.registeredProjectId, category: item.category, registryDigest: item.registryDigest, state: item.state };
  });
}

/** Strict readback only after the original owned Job and its output drained. */
export async function verifyInitialMigrationResult(input: PythonJobInput & { targetProfile: string },
  operationId: string, state: "completed" | "partial"): Promise<boolean> {
  if (!isAbsolute(input.targetProfile) || !/^(?:initial|ksync|krec)-[a-f0-9]{40}$/.test(operationId)
    || (state !== "completed" && state !== "partial")) return false;
  const environment = { ...input.env };
  for (const key of Object.keys(environment)) if (/^VIBELUTION_INITIAL_MIGRATION_(?:URL|TOKEN)$/i.test(key)) delete environment[key];
  const result = await runPythonJob({ ...input, env: environment }, ["--initial-verify", "--target-profile", input.targetProfile,
    "--operation-id", operationId, ...(state === "partial" ? ["--allow-partial"] : [])]);
  if (result.exit !== 0 || !result.value || typeof result.value !== "object" || Array.isArray(result.value)) return false;
  const row = result.value as Record<string, unknown>;
  return Object.keys(row).sort().join(",") === "operationId,readyForCutover,schemaVersion,state"
    && row.schemaVersion === 1 && row.operationId === operationId
    && row.state === (state === "partial" ? "confirmed_partial" : "confirmed_completed") && row.readyForCutover === false;
}

/** Main-only isolated writer; its permit remains held until the owned Job drains. */
export async function runInitialMigrationJob(input: PythonJobInput & {
  lease: PreHostSourceLease; binding: InitialMigrationLaunchBinding; beforeSpawn?: () => Promise<void>;
  onNotStarted?: () => Promise<void>; registryDigest?: string;
}): Promise<Result> {
  const bridge = await openInitialMigrationBridge(input.lease, input.binding);
  let closed = false, fenced = false;
  try {
    const environment = { ...input.env };
    for (const key of Object.keys(environment)) if (/^VIBELUTION_INITIAL_MIGRATION_(?:URL|TOKEN)$/i.test(key)) delete environment[key];
    if (input.beforeSpawn) {
      input.lease.check();
      if (typeof input.registryDigest !== "string" || !/^[a-f0-9]{64}$/.test(input.registryDigest))
        throw new Error("KNOWLEDGE_PREFLIGHT_UNAVAILABLE");
      const preflight = await runPythonJob({ ...input, env: environment }, ["--knowledge-preflight", "--source-config", input.binding.sourceConfig,
        "--target-profile", input.binding.targetProfile, "--target-config", input.binding.targetConfig,
        "--operation-id", input.binding.operationId, "--registry-digest", input.registryDigest]);
      if (preflight.exit !== 0 || !preflight.value || typeof preflight.value !== "object" || Array.isArray(preflight.value)
        || Object.keys(preflight.value).sort().join(",") !== "schemaVersion,state"
        || (preflight.value as Record<string, unknown>).schemaVersion !== 1 || (preflight.value as Record<string, unknown>).state !== "ready")
        throw new Error("KNOWLEDGE_PREFLIGHT_UNAVAILABLE");
      input.lease.check();
    }
    Object.assign(environment, bridge.environment);
    const result = await runPythonJob({ ...input, env: environment }, ["--initial-offline"], async () => {
      input.signal?.throwIfAborted();
      input.lease.check();
      if (input.beforeSpawn) { await input.beforeSpawn(); fenced = true; }
    }, async () => {
      if (fenced && input.onNotStarted) await input.onNotStarted();
    });
    // A closed channel and a completely drained owned Job prove that no
    // delayed permit can grant this attempt authority after this point.
    await bridge.closeAfterDrain();
    closed = true;
    if (fenced && !bridge.wasGranted() && input.onNotStarted) {
      await input.onNotStarted();
      return { schemaVersion: 1, operationId: input.binding.operationId, state: "not_started", readyForCutover: false };
    }
    if (bridge.wasGranted() && result.exit === 0 && result.value && typeof result.value === "object" && !Array.isArray(result.value)) {
      const row = result.value as Record<string, unknown>;
      if (Object.keys(row).sort().join(",") === "operationId,readyForCutover,schemaVersion,state"
        && row.schemaVersion === 1 && row.operationId === input.binding.operationId && row.readyForCutover === false
        && (row.state === "completed" || row.state === "partial"))
        return { schemaVersion: 1, operationId: input.binding.operationId, state: row.state, readyForCutover: false };
    }
    return { schemaVersion: 1, operationId: input.binding.operationId, state: "unknown", readyForCutover: false };
  } finally { if (!closed) await bridge.closeAfterDrain(); }
}
